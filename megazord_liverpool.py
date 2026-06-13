#!/usr/bin/env python3
# ==========================================
# MEGAZORD LIVERPOOL - VERSIÓN ENTERPRISE V5
# ==========================================
# 🚀 AUTO-RENOVACIÓN DE TOKENS (PLAYWRIGHT)
# 🚀 ARQUITECTURA MULTI-TENANT (MULTI-CUENTA)
# Cero dependencias de Sheets para Reglas.
# Lectura de Tokens y SKUs directo desde PostgreSQL.
# ==========================================

import urllib.parse
import random
import os
import time
import logging
import sys
import gc
import threading
import hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import json
import psycopg2 
from db_manager import DbManager

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# ==========================================
# 🧪 MODO SIMULACRO (DRY-RUN)
# ==========================================
MODO_SIMULACION = False  

SIMULACION_BANNER = "🧪 [SIMULACIÓN] "
SIMULACION_COLOR = "\033[94m"
RESET_COLOR = "\033[0m"

def imprimir_simulacion(mensaje):
    print(f"{SIMULACION_COLOR}{SIMULACION_BANNER}{mensaje}{RESET_COLOR}")
    logger.info(f"{SIMULACION_BANNER}{mensaje}")

# ==========================================
# FUNCIONES DE ENMASCARAMIENTO
# ==========================================
def enmascarar_sku(sku_real):
    hash_sku = hashlib.md5(str(sku_real).encode()).hexdigest()[:6].upper()
    return f"SKU_{hash_sku}"

def enmascarar_vendedor(nombre_vendedor):
    if not nombre_vendedor or nombre_vendedor == "Desconocido":
        return "Desconocido"
    marca_propia = os.getenv("PROPIA_BRAND_NAME", "WABU").upper()
    if marca_propia in str(nombre_vendedor).upper():
        return "NOSOTROS"
    return "RIVAL"

def enmascarar_precio(precio_real):
    try:
        return f"${int(float(precio_real))}.XX"
    except:
        return "$X.XX"

# ==========================================
# LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,  # <--- SE QUEDA EN INFO PARA MANTENER LA CONSOLA LIMPIA
    format='%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('megazord.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# RATE LIMITER Y RETRY
# ==========================================
class RateLimiter:
    def __init__(self, calls_per_second=3):
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            elapsed = time.time() - self.last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_call = time.time()

liverpool_rate_limiter = RateLimiter(calls_per_second=3)

def crear_session_con_retry():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "PUT", "POST"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# ==========================================
# CONSTANTES Y TELEGRAM
# ==========================================
SHOP_ID_INTERNO = os.getenv("SHOP_ID_INTERNO", "").strip()
SHOP_ID_PUBLICO = os.getenv("SHOP_ID_PUBLICO", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
LIVERPOOL_PASS = os.getenv("LIVERPOOL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")

def enviar_alerta_telegram(mensaje):
    enviar_telegram(mensaje)

def enviar_telegram(mensaje):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_WMT:
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_WMT, "text": mensaje, "parse_mode": "Markdown"})
    except Exception as e:
        logger.error(f"Error Telegram: {e}")

# ==========================================
# MATEMÁTICAS
# ==========================================
def safe_float(valor):
    try:
        if valor is None or str(valor).strip() == '': return 0.0
        return float(str(valor).replace('$', '').replace(',', '').strip())
    except:
        return 0.0

def calcular_rentabilidad(precio_venta, costo_odoo):
    try:
        precio_venta = float(precio_venta)
        costo_odoo = float(costo_odoo)
        if precio_venta <= 0: return 0.0, 0.0
        costo_con_iva = costo_odoo * 1.16
        comision = precio_venta * 0.17
        envio_fijo = 130.0
        precio_base = precio_venta / 1.16
        retenciones = precio_base * 0.105
        ingreso_neto = precio_venta - comision - envio_fijo - retenciones
        ganancia = ingreso_neto - costo_con_iva
        margen = (ganancia / costo_con_iva) * 100 if costo_con_iva > 0 else 0
        return ganancia, margen
    except:
        return 0.0, 0.0

# ==========================================
# 🕵️‍♂️ MÓDULO DE INFILTRACIÓN AUTOMÁTICA (PLAYWRIGHT)
# ==========================================
def obtener_cipher():
    llave = os.getenv("GOOGLE_ENCRYPTION_KEY")
    if not llave: return None
    try: return Fernet(llave.encode())
    except: return None

def validar_token_vivo(token, sku_test):
    """Lanza un Ping silencioso a Liverpool para ver si el Token sigue vivo"""
    url = f"https://pro-api.liverpool.com.mx/api/offermanagement/offers?shop_id={SHOP_ID_INTERNO}&sku={urllib.parse.quote(sku_test)}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 401: return False
        return True
    except: 
        return True # Asumimos True si hay error de red temporal para no invocar a Playwright sin razón

def renovar_credenciales_postgresql(db, gc_client, id_cuenta, email_usuario, cookie_encriptada_actual):
    """Robot de Playwright que intercepta el 2FA y actualiza la base de datos"""
    logger.info(f"🤖 [{id_cuenta}] Desplegando Escuadrón Playwright para Extracción de Token...")
    token_atrapado = None
    p = None
    browser = None
    cipher = obtener_cipher()

    try:
        p = sync_playwright().start()
        browser = p.chromium.launch(headless=True, args=['--disable-dev-shm-usage', '--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'])
        context = browser.new_context(viewport={'width': 600, 'height': 400}, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        if cookie_encriptada_actual and cookie_encriptada_actual != "NaN":
            try:
                if cipher: context.add_cookies(json.loads(cipher.decrypt(cookie_encriptada_actual.encode()).decode()))
                else: context.add_cookies(json.loads(cookie_encriptada_actual))
                logger.info(f"🍪 [{id_cuenta}] Gafete VIP previo inyectado en el navegador.")
            except: pass

        page = context.new_page()

        def rastrear_red(request):
            nonlocal token_atrapado
            if "pro-api.liverpool.com.mx" in request.url:
                auth = request.headers.get("authorization", "")
                if "Bearer " in auth: token_atrapado = auth.replace("Bearer ", "")

        page.on("request", rastrear_red)
        page.goto("https://marketplace.liverpool.com.mx/")

        necesita_login = True
        try:
            page.wait_for_selector('input#username, #username, input[name="username"], input[type="email"]', timeout=8000)
            logger.info(f"🛑 [{id_cuenta}] Nos detectaron. Iniciando protocolo de Login y 2FA...")
        except:
            necesita_login = False
            logger.info(f"✅ [{id_cuenta}] Pasamos la aduana. Buscando el token en la red...")
            page.reload()
            page.wait_for_timeout(8000)
            if not token_atrapado:
                logger.warning(f"⚠️ [{id_cuenta}] No soltaron el token. Forzando login humano.")
                necesita_login = True

        if necesita_login:
            page.goto("https://marketplace.liverpool.com.mx/")
            page.wait_for_selector('input#username, #username, input[name="username"], input[type="email"]', timeout=30000)
            page.locator('input#username').click()
            page.locator('input#username').type(email_usuario, delay=random.randint(100, 250))
            page.locator('input#password').click()
            page.locator('input#password').type(LIVERPOOL_PASS, delay=random.randint(100, 250))
            
            try: hoja_config = gc_client.open_by_key(GOOGLE_SHEET_ID).worksheet("Config")
            except: hoja_config = None

            page.click('button[type="submit"]')
            logger.info("⏳ Esperando que el correo viaje a Apps Script (15 seg)...")
            time.sleep(15)

            codigo_antiguo = ""
            codigo_exitoso = False

            for i in range(18):
                time.sleep(10)
                codigo_nuevo = ""
                if hoja_config:
                    try: codigo_nuevo = str(hoja_config.acell("B1").value).replace("'", "").strip()
                    except: pass
                
                logger.info(f"🔄 Intento {i+1}/18 | Código Excel: {codigo_nuevo}")

                if codigo_nuevo != codigo_antiguo and len(codigo_nuevo) == 6:
                    logger.info(f"✅ ¡Código FRESCO interceptado!: {codigo_nuevo}")
                    codigo_antiguo = codigo_nuevo
                    caja_codigo = page.locator('input:not([disabled]):not([readonly]):not([type="checkbox"]):not([type="hidden"]):visible').first
                    caja_codigo.click(force=True)
                    page.keyboard.type(codigo_nuevo, delay=random.randint(200, 400))
                    page.wait_for_timeout(1500)
                    page.locator('button:has-text("Continuar")').first.click(force=True)

                    tiempo_inicio = time.time()
                    while time.time() - tiempo_inicio < 60:
                        time.sleep(1)
                        if token_atrapado:
                            logger.info(f"🔑 [{id_cuenta}] ¡TOKEN BEARER ATRAPADO CON ÉXITO!")
                            codigo_exitoso = True
                            break
                        if time.time() - tiempo_inicio == 20:
                            try: page.reload(); page.wait_for_timeout(3000)
                            except: pass
                    if codigo_exitoso: break

            if not codigo_exitoso:
                logger.error(f"❌ [{id_cuenta}] Misión Abortada. No soltaron el token después de meter el código.")
                return None, None

        page.wait_for_timeout(3000)
        
        if token_atrapado:
            logger.info(f"💾 [{id_cuenta}] Guardando llaves maestras en Bóveda de PostgreSQL...")
            cookies_json = json.dumps(context.cookies())
            cookie_final = cipher.encrypt(cookies_json.encode()).decode() if cipher else cookies_json
            
            try:
                conn = psycopg2.connect(DATABASE_URL)
                cursor = conn.cursor()
                cursor.execute("UPDATE cuentas_liverpool SET token_autorizacion=%s, cookie_vip=%s WHERE id_cuenta=%s", 
                               (token_atrapado, cookie_final, id_cuenta))
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                logger.error(f"Error guardando token en DB: {e}")

            return token_atrapado, cookie_final

    except Exception as e:
        logger.error(f"❌ Fallo crítico en Playwright: {e}")
        return None, None
    finally:
        logger.info("🧹 Limpiando Playwright...")
        if browser:
            try: browser.close()
            except: pass
        if p:
            try: p.stop()
            except: pass
        gc.collect()

# ==========================================
# MÓDULO DE CACERÍA DE OFERTAS
# ==========================================
def cazar_oferta_especifica(token, sku_interno, sku_liverpool):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    sku_l = str(sku_liverpool).strip()
    urls = [
        f"https://pro-api.liverpool.com.mx/api/offermanagement/offers?shop_id={SHOP_ID_INTERNO}&sku={urllib.parse.quote(str(sku_interno).strip())}",
        f"https://pro-api.liverpool.com.mx/api/offermanagement/offers?shop_id={SHOP_ID_INTERNO}&product_id={sku_l}"
    ]
    for url in urls:
        try:
            liverpool_rate_limiter.wait()
            res = crear_session_con_retry().get(url, headers=headers, timeout=30)
            if res.status_code == 200:
                for prod in res.json().get("offers", []):
                    if str(prod.get("product_sku", "")).strip() == sku_l:
                        return prod
        except: pass
    return None

def obtener_info_rivales(liverpool_sku):
    url = f"https://shoppapp.liverpool.com.mx/appclienteservices/services/v2/marketplace/pdp/getSellersOfferDetailsPdp?skuId={liverpool_sku}"
    try:
        res = crear_session_con_retry().get(url, headers={"User-Agent": "Liverpool/2.2.0"}, timeout=30)
        if res.status_code == 200:
            rivales = []
            for v in res.json().get("sellersOfferDetails", []):
                if str(v.get("sellerId")) != str(SHOP_ID_PUBLICO):
                    rivales.append({"precio": float(v.get("promoPrice") or v.get("salePrice")), "nombre": str(v.get("sellerName"))})
            return sorted(rivales, key=lambda x: x["precio"])
    except: pass
    return []

def calcular_posicion_buybox(precios_rivales, nuestro_precio):
    if not precios_rivales:
        return "1 de 1", "¡Nosotros! 👑"
    todos = sorted(precios_rivales + [nuestro_precio])
    posicion = todos.index(nuestro_precio) + 1
    total = len(todos)
    return f"#{posicion} de {total}", "¡Nosotros! 👑" if posicion == 1 else f"Rival (${todos[0]})"

# ==========================================
# CLASE DE RESULTADOS THREAD-SAFE
# ==========================================
class ResultadosThreadSafe:
    def __init__(self):
        self._lock = threading.Lock()
        self.historial_rows = []
        self.archivo_negro_rows = []
        self.alertas = []
        self.skus_agotados_a_apagar = []
        self.ultimo_precio_conocido = {}
        self.max_precio_buybox_historico = {}
        self.ultimo_estado_conocido = {}

    def agregar_historial(self, fila):
        with self._lock:
            if isinstance(fila, list) and fila:
                if isinstance(fila[0], (list, tuple)): self.historial_rows.extend(fila)
                else: self.historial_rows.append(fila)
            else: self.historial_rows.append(fila)

    def agregar_archivo_negro(self, fila):
        with self._lock: self.archivo_negro_rows.append(fila)

    def agregar_alerta(self, mensaje):
        with self._lock: self.alertas.append(mensaje)

    def apagar_sku_liverpool(self, fila_excel, sku_i):
        with self._lock: self.skus_agotados_a_apagar.append((fila_excel, sku_i))

    def obtener_todos(self):
        with self._lock:
            return (list(self.historial_rows), list(self.archivo_negro_rows), list(self.alertas))

# ==========================================
# DISPARAR PRECIO
# ==========================================
def disparar_precio(token, offer_id, stock, base_price, nuevo_precio, sku_notificacion=""):
    url = "https://pro-api.liverpool.com.mx/api/offermanagement/offers/price-quantity"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "shopid": SHOP_ID_INTERNO
    }
    payload = [{
        "basePrice": float(base_price),
        "offerId": int(offer_id),
        "quantity": int(stock),
        "offerPriceManagement": [{
            "discountPrice": float(nuevo_precio),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "userModified": "MEGAZORD_API",
            "index": 0
        }]
    }]
    
    try:
        if MODO_SIMULACION:
            imprimir_simulacion(f"DISPARAR_PRECIO | SKU: {sku_notificacion} | Bajaría a: ${nuevo_precio}")
            return True
            
        liverpool_rate_limiter.wait()
        session = crear_session_con_retry()
        response = session.put(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code in [200, 204]:
            logger.info(f"✅ Ajuste ejecutado: {enmascarar_precio(nuevo_precio)}")
            return True
        else:
            logger.error(f"❌ ERROR HTTP {response.status_code} | {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Excepción en disparar_precio: {e}")
        return False

# ==========================================
# CEREBRO ESTRATÉGICO MULTI-CUENTA
# ==========================================
def procesar_sku_threadsafe(token, sku_lp, regla, resultados, gc_client, hoja_config, session, id_cuenta):
    try:
        sku_i = str(regla.get('sku') or regla.get('sku_interno') or regla.get('SKU_Interno') or regla.get('SKU') or 'Sin SKU')
        estatus_regla = str(regla.get('estatus', '')).strip().upper()
        tipo_regla = str(regla.get('regla_estrategia', '1. Gladiador')).strip()
        fila_excel = regla.get('fila_excel', 0)

        prod = cazar_oferta_especifica(token, sku_i, sku_lp)

        if not prod or str(prod.get("state_code", "")).upper() != "ACTIVE":
            resultados.agregar_historial([
                (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                str(sku_i), str(sku_lp), "Oculto/Agotado", 0, 0, "N/A", "N/A", id_cuenta
            ])
            return

        cantidad = int(prod.get("quantity", 0))
        offer_id = prod.get("offerId")
        base_price = float(prod.get("basePrice", 0))
        precio_actual = float(prod.get("discountPrice") or base_price)

        nuevo_precio = precio_actual

        if cantidad is None:
            logger.warning(f"⚠️ Error de API al leer stock de {sku_i}. Reintentando en siguiente ciclo.")
            return
        
        if cantidad == 0:
            resultados.agregar_historial([
                (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                str(sku_i), str(sku_lp), "Agotado", precio_actual, 0, "N/A", "N/A", id_cuenta
            ])
            if estatus_regla == 'ACTIVO':
                resultados.apagar_sku_liverpool(fila_excel, sku_i)
            return

        info_rivales = obtener_info_rivales(sku_lp)
        precios_rivales = [r["precio"] for r in info_rivales]

        precio_minimo_regla = safe_float(regla.get('precio_minimo', 0))
        precio_maximo_regla = safe_float(regla.get('precio_maximo', base_price) or base_price)
        costo_odoo_sheet = safe_float(regla.get('costo_odoo', 0))

        sku_display = enmascarar_sku(sku_lp)
        logger.info(f"🔍 [{id_cuenta}] Escaneando {sku_display} | BB: {enmascarar_vendedor(info_rivales[0]['nombre'] if info_rivales else 'N/A')}")

        hora_actual_str = (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")

        # Preparar radar de rivales para PostgreSQL
        catalogo_id = regla.get('id')
        if catalogo_id:
            for idx, r in enumerate(info_rivales[:5]):
                resultados.agregar_archivo_negro((catalogo_id, 'LIVERPOOL', r["nombre"], r["precio"], idx + 1))

        if precios_rivales:
            rival_mas_bajo = precios_rivales[0]
            precio_viejo = resultados.ultimo_precio_conocido.get(sku_i, rival_mas_bajo) if hasattr(resultados, 'ultimo_precio_conocido') else rival_mas_bajo
            caida = precio_viejo - rival_mas_bajo
            if caida >= 100:
                culpable = info_rivales[0]["nombre"]
                resultados.agregar_alerta(f"🚨 *ALERTA ANTI-DUMPING ({id_cuenta})*\nEl vendedor _{culpable}_ acaba de desplomar el mercado en *{sku_i}*.\n📉 Anterior: `${precio_viejo}` | 🩸 Nuevo: `${rival_mas_bajo}`")

        # ================= LÓGICA DE REGLAS =================
        if estatus_regla == 'INACTIVO':
            if info_rivales:
                rival_1 = info_rivales[0]
                estado_precio = "✅ TIENES MARGEN!" if precio_minimo_regla > 0 and rival_1["precio"] >= precio_minimo_regla else "❌ RIVAL REMATANDO."
                msg = f"🕵️ *RADAR ESPÍA ({id_cuenta})*\n📦 *{sku_i}*\n👑 *Precio de la BuyBox:* `${rival_1['precio']}`\n📊 {estado_precio}\n🛡️ Tu mínimo: `${precio_minimo_regla}`"
                if costo_odoo_sheet > 0:
                    gan, mar = calcular_rentabilidad(rival_1["precio"], costo_odoo_sheet)
                    msg += f"\n💡 *Para ganar a `${rival_1['precio']}`:*\nGanancia: `${gan:.2f}` (Margen: `{mar:.1f}%`)"
                resultados.agregar_alerta(msg)
            resultados.agregar_historial([
                hora_actual_str, sku_i, sku_lp,
                precios_rivales[0] if precios_rivales else "SIN RIVAL",
                precio_actual, cantidad, "Inactivo", "Inactivo", id_cuenta
            ])
            return

        if estatus_regla == 'ACTIVO':
            # REGLA 2: ANCLA MÍNIMO
            if tipo_regla.startswith('2'):
                nuevo_precio = precio_minimo_regla
                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                if float(precio_actual) != float(nuevo_precio):
                    if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        msg_alerta = f"📌 *LÍMITE MÍNIMO ACTIVADO ({id_cuenta})*\n\n📦 *{sku_i}*\nPrecio fijado en mínimo: `${nuevo_precio}`"
                        resultados.agregar_alerta(msg_alerta)
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", nuevo_precio, cantidad, pos, bb, id_cuenta])
                else:
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", precio_actual, cantidad, pos, bb, id_cuenta])

            # REGLA 3: COSECHA MÁXIMO
            elif tipo_regla.startswith('3'):
                nuevo_precio = precio_maximo_regla
                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                if float(precio_actual) != float(nuevo_precio):
                    if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", nuevo_precio, cantidad, pos, bb, id_cuenta])
                else:
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", precio_actual, cantidad, pos, bb, id_cuenta])

            # =========================================
            # ⭐ REGLA 9: VENTA ESPECIAL (HOT SALE + RULETA RUSA) ⭐
            # =========================================
            elif tipo_regla.startswith('9'):
                logger.debug(f"   🎯 [{id_cuenta}] VENTA ESPECIAL | Trinquete + Ruleta + Escudo Sombra")
                if precios_rivales:
                    rival_mas_bajo = precios_rivales[0]
                    if rival_mas_bajo >= precio_minimo_regla:
                        baja_aleatoria = round(random.uniform(1.50, 1.95), 2)
                        nuevo_precio_propuesto = round(rival_mas_bajo - baja_aleatoria, 2)
                        if nuevo_precio_propuesto >= precio_actual:
                            dado = random.randint(1, 9)
                            if dado == 1:
                                nuevo_precio = round(precio_actual - 1.50, 2)
                                motivo = "🔥 Hachazo Ruleta Rusa"
                            else:
                                nuevo_precio = precio_actual
                                motivo = "🛡️ Trinquete Anti-Rebote"
                        else:
                            nuevo_precio = nuevo_precio_propuesto
                            motivo = "⚔️ Ataque Normal"
                    else:
                        rivales_viables = [p for p in precios_rivales if p >= precio_minimo_regla]
                        if rivales_viables:
                            objetivo_sombra = rivales_viables[0]
                            nuevo_precio = round(float(int(objetivo_sombra) - 1) + 0.09, 2)
                            motivo = "🎯 Sombra Activada (.09)"
                        else:
                            nuevo_precio = precio_actual
                            motivo = "🛑 Alerta Roja (Perdida BB)"
                else:
                    nuevo_precio = precio_maximo_regla
                    motivo = "👑 Monopolio"
                    
                nuevo_precio = max(nuevo_precio, precio_minimo_regla)
                nuevo_precio = min(nuevo_precio, precio_maximo_regla)
                
                if float(precio_actual) != float(nuevo_precio):
                    pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                    bb_con_motivo = f"{bb} | {motivo}"
                    if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo if precios_rivales else "SIN RIVAL", nuevo_precio, cantidad, pos, bb_con_motivo, id_cuenta])
                        if motivo == "🎯 Sombra Activada (.09)":
                            vendedor_ganador = info_rivales[0]["nombre"] if info_rivales else "Desconocido"
                            msg_alerta = (f"🚨 *ALERTA TÁCTICA: Sombra Activada ({id_cuenta})*\n\n📦 *{sku_i}*\n"
                                          f"👑 Ganador actual: *{vendedor_ganador}*\n"
                                          f"💰 Precio de la BuyBox: `${rival_mas_bajo}`\n"
                                          f"🎯 Haciendo Sombra a: `${nuevo_precio}`...")
                        else:
                            msg_alerta = (f"🎯 *VENTA ESPECIAL ACTIVADA ({id_cuenta})*\n\n📦 *{sku_i}*\n"
                                          f"👑 Rival: `${rival_mas_bajo if precios_rivales else 'N/A'}`\n"
                                          f"📉 Anterior: `${precio_actual}` → Nuevo: `${nuevo_precio}`\n"
                                          f"⚙️ Táctica: {motivo}")
                        if costo_odoo_sheet > 0:
                            gan, mar = calcular_rentabilidad(nuevo_precio if motivo != "🎯 Sombra Activada (.09)" else rival_mas_bajo, costo_odoo_sheet)
                            msg_alerta += f"\n💡 Ganancia referencial: `${gan:.2f}` | Margen: `{mar:.1f}%`"
                        resultados.agregar_alerta(msg_alerta)
                else:
                    pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                    bb_con_motivo = f"{bb} | {motivo}"
                    if motivo == "🛑 Alerta Roja (Perdida BB)":
                        gan_roja, mar_roja = calcular_rentabilidad(rival_mas_bajo, costo_odoo_sheet)
                        vendedor_ganador = info_rivales[0]["nombre"] if info_rivales else "Desconocido"
                        msg_alerta = (f"🛑 *ALERTA ROJA: Has perdido la BuyBox ({id_cuenta})*\n\n"
                                      f"📦 *{sku_i}*\n"
                                      f"👑 Ganador actual: *{vendedor_ganador}*\n"
                                      f"💰 Precio de la BuyBox: `${rival_mas_bajo}`\n"
                                      f"🥶 Congelado en `${precio_actual}` (Mínimo: `${precio_minimo_regla}`).\n"
                                      f"💡 Para salir:\nGanancia: `${gan_roja:.2f}` | Margen: `{mar_roja:.1f}%`")
                        resultados.agregar_alerta(msg_alerta)
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo if precios_rivales else "SIN RIVAL", precio_actual, cantidad, pos, bb_con_motivo, id_cuenta])

            # =========================================
            # REGLAS 1, 4, 5, 6, 7, 8 (GLADIADOR FINO)
            # =========================================
            else:
                if not precios_rivales:
                    nuevo_precio = precio_maximo_regla
                    pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                    if float(precio_actual) != float(nuevo_precio):
                        if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, "SIN_RIVAL", nuevo_precio, cantidad, pos, bb, id_cuenta])
                        else:
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, "SIN_RIVAL", precio_actual, cantidad, pos, bb, id_cuenta])
                    else:
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, "SIN_RIVAL", precio_actual, cantidad, pos, bb, id_cuenta])
                    return
                
                rival_mas_bajo = precios_rivales[0]
                
                try:
                    rival_mas_bajo = float(rival_mas_bajo)
                    precio_actual = float(precio_actual)
                    precio_minimo_regla = float(precio_minimo_regla)
                    precio_maximo_regla = float(precio_maximo_regla)
                except (ValueError, TypeError) as e:
                    logger.error(f"   ❌ Error casting a float: {e}")
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, f"ERROR_CAST:{str(e)}", precio_actual, cantidad, "ERROR", "ERROR", id_cuenta])
                    return
                
                if rival_mas_bajo >= precio_minimo_regla:
                    diferencia_actual = round(float(rival_mas_bajo) - float(precio_actual), 2)
                    
                    # 🎯 ¡PARCHE APLICADO! Evaluamos en positivo (1.50 a 1.95)
                    if 1.50 <= diferencia_actual <= 1.95:
                        pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                    else:
                        baja = round(random.uniform(1.50, 1.95), 2)
                        nuevo_precio = round(rival_mas_bajo - baja, 2)
                        
                        if precio_maximo_regla > 0 and nuevo_precio > precio_maximo_regla:
                            nuevo_precio = precio_maximo_regla
                        
                        if nuevo_precio < precio_minimo_regla:
                            pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                            return
                        
                        if float(precio_actual) == float(nuevo_precio):
                            pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                            return
                        
                        pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                        if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, pos, bb, id_cuenta])
                        else:
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                
                else:
                    rivales_viables = [p for p in precios_rivales if p >= precio_minimo_regla]
                    
                    if rivales_viables:
                        objetivo_sombra = rivales_viables[0]
                        nuevo_precio = round(float(int(objetivo_sombra) - 1) + 0.09, 2)
                        
                        if precio_maximo_regla > 0 and nuevo_precio > precio_maximo_regla:
                            nuevo_precio = precio_maximo_regla
                        if nuevo_precio < precio_minimo_regla:
                            nuevo_precio = precio_minimo_regla
                        
                        pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                        
                        if float(precio_actual) != float(nuevo_precio):
                            if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, pos, bb, id_cuenta])
                            else:
                                resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                        else:
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                    else:
                        pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])

    except Exception as e:
        logger.error(f"❌ Error en procesar_sku_threadsafe: {e}")
        resultados.agregar_historial([
            (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
            str(sku_i) if 'sku_i' in locals() else sku_lp, sku_lp, "ERROR", 0, 0, "ERROR", str(e), id_cuenta
        ])

# ==========================================
# GUARDADO DE HISTORIAL SEGURO EN SQL
# ==========================================
def guardar_en_sql(filas):
    if MODO_SIMULACION:
        imprimir_simulacion(f"SQL OMITIDO | Se guardarían {len(filas)} registros.")
        return
    if not filas: return

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        query = """INSERT INTO historial_precios 
        (fecha_hora, sku_interno, sku_liverpool, precio_rival, nuestro_precio, stock, posicion, buybox, id_cuenta) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        
        cursor.executemany(query, filas)
        conn.commit()
        logger.info(f"☁️ ¡{cursor.rowcount} registros MULTI-CUENTA guardados en el Dashboard!")
        
    except Exception as e:
        logger.error(f"❌ CRÍTICO: Error guardando en base de datos: {e}")
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if 'conn' in locals() and conn: conn.close()

# ==========================================
# FUNCIÓN PRINCIPAL MULTI-TENANT CON AUTO-TOKEN
# ==========================================
def ejecutar_bot():
    logger.info("\n--- INICIANDO MEGAZORD LIVERPOOL V5 ENTERPRISE MULTI-CUENTA ---")
    enviar_telegram("🤖 *Megazord Liverpool V5 (Auto-Token)* despertando...")
    
    try: db = DbManager()
    except: db = None

    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        gc_connection = gspread.authorize(creds)
    except:
        gc_connection = None

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT id_cuenta, nombre_descriptivo, email_usuario, token_autorizacion, cookie_vip FROM cuentas_liverpool WHERE is_active = TRUE")
        cuentas_activas = cursor.fetchall()
    except Exception as e:
        logger.error(f"❌ Error leyendo Bóveda VIP: {e}")
        enviar_telegram("🚨 ERROR: No se pudo leer la Bóveda VIP en PostgreSQL.")
        return

    if not cuentas_activas:
        logger.warning("⚠️ No hay cuentas activas en la Bóveda VIP del Dashboard.")
        enviar_telegram("⚠️ No hay cuentas activas en la Bóveda VIP del Dashboard.")
        return

    resultados = ResultadosThreadSafe()
    sesion_compartida = crear_session_con_retry()
    total_skus_procesados = 0

    for cuenta in cuentas_activas:
        id_cuenta = cuenta[0]
        nombre_desc = cuenta[1]
        email_usuario = cuenta[2]
        token_cuenta = cuenta[3]
        cookie_vip = cuenta[4]

        logger.info(f"\n==========================================")
        logger.info(f"🏪 CARGANDO MOTOR PARA: {nombre_desc} ({id_cuenta})")
        logger.info(f"==========================================")

        try:
            cursor.execute("""
                SELECT id, sku_limpio, sku_interno, sku_liverpool, precio_minimo, precio_maximo, costo_odoo, regla_estrategia, estatus
                FROM catalogo_maestro_v3
                WHERE id_cuenta = %s AND estatus = 'ACTIVO' AND sku_liverpool IS NOT NULL AND sku_liverpool != ''
            """, (id_cuenta,))

            columnas = [desc[0] for desc in cursor.description]
            skus_raw = cursor.fetchall()

            reglas_cuenta = {}
            for row in skus_raw:
                fila_dict = dict(zip(columnas, row))
                sku_lp = fila_dict['sku_liverpool']
                reglas_cuenta[sku_lp] = fila_dict

        except Exception as e:
            logger.error(f"❌ Error obteniendo SKUs para {id_cuenta}: {e}")
            continue

        if not reglas_cuenta:
            logger.info(f"⚠️ No hay SKUs activos asignados a la cuenta {id_cuenta}.")
            continue

        # 🟢 PING DEL TOKEN: Verificar si la llave guardada sigue viva
        sku_muestra = next(iter(reglas_cuenta.values()))['sku_interno']
        token_valido = True
        
        if token_cuenta:
            logger.info(f"📡 Enviando Ping a Liverpool para verificar Token de {id_cuenta}...")
            token_valido = validar_token_vivo(token_cuenta, sku_muestra)
            if not token_valido:
                logger.warning(f"💀 El Ping devolvió 401. El Token está MUERTO.")

        # 🤖 PLAYWRIGHT: Si el token está muerto o no existe, iniciar infiltración
        if not token_cuenta or not token_valido:
            logger.warning(f"🚨 Activando Modo Infiltración (Playwright) para {id_cuenta}...")
            nuevo_token, nueva_cookie = renovar_credenciales_postgresql(db, gc_connection, id_cuenta, email_usuario, cookie_vip)
            if nuevo_token:
                token_cuenta = nuevo_token
                logger.info(f"🎉 Infiltración exitosa. Comenzando cacería.")
            else:
                logger.error(f"❌ Falló la infiltración de {id_cuenta}. Omitiendo cuenta para evitar baneos.")
                continue

        total_skus_procesados += len(reglas_cuenta)
        logger.info(f"🚀 Iniciando cacería concurrente con 3 hilos para {len(reglas_cuenta)} SKUs de {id_cuenta}...")

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(
                    procesar_sku_threadsafe,
                    token_cuenta, sku_lp, regla, resultados, gc_connection, None, sesion_compartida, id_cuenta
                ): sku_lp
                for sku_lp, regla in reglas_cuenta.items()
            }

            completados = 0
            for future in as_completed(futures):
                completados += 1
                if completados % 10 == 0:
                    logger.info(f"⏳ [{id_cuenta}] Progreso: {completados}/{len(reglas_cuenta)} SKUs procesados")

        logger.info(f"✅ Cacería de {id_cuenta} completada.")

    logger.info("\n💾 Guardando resultados globales en PostgreSQL...")

    historial_rows, archivo_negro_rows, alertas = resultados.obtener_todos()

    for alerta in alertas:
        enviar_alerta_telegram(alerta)

    if historial_rows:
        guardar_en_sql(historial_rows)

    if archivo_negro_rows and db:
        guardados = 0
        for rival_data in archivo_negro_rows:
            try:
                db.registrar_rival(*rival_data)
                guardados += 1
            except:
                pass
        logger.info(f"📡 ¡{guardados} rivales inyectados en la tabla de monitoreo de rivales!")

    if resultados.skus_agotados_a_apagar and gc_connection:
        try:
            hoja_principal = gc_connection.open_by_key(GOOGLE_SHEET_ID).worksheet("Hoja 1")
            for fila_excel, sku_i in resultados.skus_agotados_a_apagar:
                if fila_excel > 0:
                    hoja_principal.update_cell(fila_excel, 5, "INACTIVO")
            logger.info(f"🔌 Circuit Breaker ejecutado para {len(resultados.skus_agotados_a_apagar)} productos.")
        except:
            pass

    try:
        if 'cursor' in locals() and cursor: cursor.close()
        if 'conn' in locals() and conn: conn.close()
    except:
        pass

    logger.info("🗑️ Forzando garbage collector final...")
    gc.collect()

    logger.info("\n🏁 Misión cumplida.")
    enviar_telegram(f"🏁 *BARRIDO MEGAZORD V5 COMPLETADO*\nTotal de SKUs evaluados: {total_skus_procesados}")

if __name__ == "__main__":
    ejecutar_bot()
