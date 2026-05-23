#!/usr/bin/env python3
# ==========================================
# MEGAZORD LIVERPOOL - VERSIÓN ENTERPRISE V3
# ==========================================
# Se mantiene la tabla 'historial_precios' (Camino 2)
# Conectado a DbManager para lectura/escritura segura

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

# NUEVO: Importar DbManager para PostgreSQL
import psycopg2  # Para fallback directo
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
# OPERACIÓN GAFETE VIP
# ==========================================
def obtener_cipher():
    llave = os.getenv("GOOGLE_ENCRYPTION_KEY")
    if not llave:
        logger.warning("⚠️ GOOGLE_ENCRYPTION_KEY no configurada")
        return None
    try:
        return Fernet(llave.encode())
    except Exception as e:
        logger.warning(f"⚠️ Error inicializando Fernet: {e}")
        return None

def cargar_gafete_vip(gc_client, context):
    try:
        cipher = obtener_cipher()
        spreadsheet = gc_client.open_by_key(GOOGLE_SHEET_ID)
        hoja_boveda = spreadsheet.worksheet('Boveda_VIP')
        registros = hoja_boveda.get_all_records()
        for fila in registros:
            if fila.get('Tienda') == 'Liverpool' and fila.get('Cookies'):
                try:
                    if cipher:
                        datos_desencriptados = cipher.decrypt(fila['Cookies'].encode()).decode()
                        context.add_cookies(json.loads(datos_desencriptados))
                        logger.info("🍪 ¡Gafete VIP encriptado cargado!")
                    else:
                        context.add_cookies(json.loads(fila['Cookies']))
                        logger.info("🍪 ¡Gafete VIP cargado (sin encriptación)!")
                    return True
                except Exception as e:
                    logger.warning(f"⚠️ Cookies inválidas: {e}")
                    return False
        return False
    except Exception as e:
        logger.warning(f"⚠️ No se encontró Bóveda VIP: {e}")
        return False

def guardar_gafete_vip(gc_client, context):
    try:
        cipher = obtener_cipher()
        spreadsheet = gc_client.open_by_key(GOOGLE_SHEET_ID)
        hoja_boveda = spreadsheet.worksheet('Boveda_VIP')
        
        cookies_json = json.dumps(context.cookies())
        
        if cipher:
            cookies_guardados = cipher.encrypt(cookies_json.encode()).decode()
            msg = "🔐 ¡Gafete VIP blindado y guardado!"
        else:
            cookies_guardados = cookies_json
            msg = "🔐 ¡Gafete VIP guardado (sin encriptación)!"
        
        celdas = hoja_boveda.findall('Liverpool')
        if celdas:
            hoja_boveda.update_cell(celdas[0].row, 2, cookies_guardados)
        else:
            hoja_boveda.append_row(['Liverpool', cookies_guardados])
        logger.info(msg)
    except Exception as e:
        logger.error(f"❌ Error guardando Gafete: {e}")

# ==========================================
# LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('megazord.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# RATE LIMITER
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

# ==========================================
# RETRY STRATEGY
# ==========================================
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
# CONSTANTES
# ==========================================
SHOP_ID_INTERNO = os.getenv("SHOP_ID_INTERNO", "").strip()
SHOP_ID_PUBLICO = os.getenv("SHOP_ID_PUBLICO", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GMAIL_USER = os.getenv("LIVERPOOL_USER")
LIVERPOOL_PASS = os.getenv("LIVERPOOL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")

# ==========================================
# TELEGRAM
# ==========================================
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

def enviar_foto_telegram(ruta_foto, mensaje):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_WMT:
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(ruta_foto, 'rb') as foto:
            requests.post(url, data={'chat_id': TELEGRAM_CHAT_WMT, 'caption': mensaje}, files={'photo': foto})
    except Exception as e:
        logger.error(f"Error foto Telegram: {e}")

def obtener_conexion_sheets(gc):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    return gspread.authorize(creds)

# ==========================================
# MATEMÁTICAS
# ==========================================
def safe_float(valor):
    try:
        if valor is None or str(valor).strip() == '':
            return 0.0
        return float(str(valor).replace('$', '').replace(',', '').strip())
    except:
        return 0.0

def calcular_rentabilidad(precio_venta, costo_odoo):
    try:
        precio_venta = float(precio_venta)
        costo_odoo = float(costo_odoo)
        if precio_venta <= 0:
            return 0.0, 0.0
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
# OBTENER TOKEN - BÓVEDA VIP PLAYWRIGHT
# ==========================================
def obtener_token_autonomo(gc_client):
    logger.info("🚀 Iniciando sesión en Liverpool (Modo GAFETE VIP + SIMULACIÓN HUMANA)...")
    token_atrapado = None
    p = None
    browser = None

    try:
        p = sync_playwright().start()
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-gpu',
                '--no-zygote',
                '--disable-extensions',
                '--js-flags="--max-old-space-size=120"'
            ]
        )

        context = browser.new_context(
            viewport={'width': 600, 'height': 400},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        cargar_gafete_vip(gc_client, context)
        page = context.new_page()

        def rastrear_red(request):
            nonlocal token_atrapado
            if "pro-api.liverpool.com.mx" in request.url:
                auth = request.headers.get("authorization", "")
                if "Bearer " in auth:
                    token_atrapado = auth.replace("Bearer ", "")

        page.on("request", rastrear_red)
        page.goto("https://marketplace.liverpool.com.mx/")

        necesita_login = True
        try:
            page.wait_for_selector('input#username, #username, input[name="username"], input[type="email"]', timeout=8000)
            logger.info("🛑 El gafete caducó o es nuevo. Iniciando login con Modo Humano...")
        except Exception:
            necesita_login = False
            logger.info("✅ ¡Aduana saltada con éxito! Ya estamos en el Dashboard.")
            
            page.reload()
            page.wait_for_timeout(10000) 
            
            if token_atrapado:
                logger.info("🔑 ¡TOKEN VIP ATRAPADO DIRECTO!")
                guardar_gafete_vip(gc_client, context)
                return token_atrapado
            else:
                logger.warning("⚠️ Entramos pero no soltó el token, forzaremos login.")
                necesita_login = True

        if necesita_login:
            page.goto("https://marketplace.liverpool.com.mx/")
            page.wait_for_selector('input#username, #username, input[name="username"], input[type="email"]', timeout=30000)

            page.locator('input#username').click()
            page.locator('input#username').type(GMAIL_USER, delay=random.randint(100, 250))
            page.wait_for_timeout(random.randint(500, 1000))
            
            page.locator('input#password').click()
            page.locator('input#password').type(LIVERPOOL_PASS, delay=random.randint(100, 250))

            try:
                hoja_config = gc_client.open_by_key(GOOGLE_SHEET_ID).worksheet("Config")
            except Exception as e:
                logger.warning(f"⚠️ No se pudo abrir pestaña Config: {e}")
                hoja_config = None

            page.wait_for_timeout(random.randint(500, 1000))
            page.click('button[type="submit"]')

            logger.info("⏳ Esperando a que el espía de Google atrape el código...")
            logger.info("⏳ Dando 15 segundos de ventaja para que el correo viaje...")
            time.sleep(15)

            codigo_antiguo = ""
            codigo_exitoso = False

            for i in range(18):
                time.sleep(10)
                codigo_nuevo = ""
                
                if hoja_config:
                    try:
                        codigo_nuevo = str(hoja_config.acell("B1").value).replace("'", "").strip()
                    except Exception as e:
                        logger.warning(f"⚠️ Error leyendo Excel B1: {e}")
                
                logger.info(f"🔄 Intento {i+1}/18 | Código actual en Excel: {codigo_nuevo}")

                if codigo_nuevo != codigo_antiguo and len(codigo_nuevo) == 6:
                    logger.info(f"✅ ¡NUEVO Código interceptado!: {codigo_nuevo}")
                    codigo_antiguo = codigo_nuevo

                    caja_codigo = page.locator('input:not([disabled]):not([readonly]):not([type="checkbox"]):not([type="hidden"]):visible').first
                    caja_codigo.click(force=True)
                    page.wait_for_timeout(500)
                    
                    page.keyboard.type(codigo_nuevo, delay=random.randint(200, 400))
                    page.wait_for_timeout(1500)

                    boton_continuar = page.locator('button:has-text("Continuar")').first
                    boton_continuar.click(force=True)

                    logger.info("⏳ Esperando token... (timeout inteligente + recarga + screenshot)")
                    
                    error_detectado = False
                    tiempo_inicio_espera = time.time()
                    timeout_token = 60
                    pagina_recargada = False
                    botones_buscados = False
                    
                    while time.time() - tiempo_inicio_espera < timeout_token:
                        tiempo_pasado = time.time() - tiempo_inicio_espera
                        time.sleep(1)
                        
                        if token_atrapado:
                            logger.info("🔑 ¡TOKEN ATRAPADO CON ÉXITO!")
                            guardar_gafete_vip(gc_client, context)
                            codigo_exitoso = True
                            break
                        
                        try:
                            mensajes_error = [
                                "código inválido", "código incorrecto", "código expirado",
                                "código caducado", "código erróneo", "invalid code",
                                "incorrect code", "expired code", "intento fallido",
                                "no válido", "algo salió mal", "vuelve a intentar",
                                "error de verificación", "el código que ingresó es incorrecto"
                            ]
                            
                            contenido_pagina = page.content().lower()
                            
                            for msg_error in mensajes_error:
                                if msg_error in contenido_pagina:
                                    error_detectado = True
                                    logger.error(f"🚨 ERROR 2FA DETECTADO: '{msg_error}'")
                                    
                                    try:
                                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        ruta_error = f"error_2fa_{timestamp}.png"
                                        page.screenshot(path=ruta_error)
                                        logger.error(f"📸 Captura error 2FA: {ruta_error}")
                                        
                                        mensaje_error = (
                                            f"🚨 *ERROR 2FA DETECTADO*\n\n"
                                            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                                            f"❌ {msg_error}\n"
                                            f"📸 Ver captura: {ruta_error}\n\n"
                                            f"Acción recomendada:\n"
                                            f"• Solicitar código nuevamente\n"
                                            f"• Revisar que Apps Script envía código FRESCO"
                                        )
                                        enviar_telegram(mensaje_error)
                                    except Exception as e:
                                        logger.error(f"Error capturando: {e}")
                                    break
                            
                            if error_detectado:
                                break
                            
                        except Exception:
                            pass
                        
                        if tiempo_pasado >= 15 and not pagina_recargada:
                            logger.warning(f"⏰ 15 segundos sin token - Intentando recarga...")
                            try:
                                page.reload()
                                page.wait_for_timeout(3000)
                                logger.info("♻️ Página recargada - Esperando 10 seg más...")
                                pagina_recargada = True
                            except Exception as e:
                                logger.warning(f"⚠️ Error recargando: {e}")
                        
                        if tiempo_pasado >= 25 and not botones_buscados:
                            logger.info("🔍 25 seg - Buscando botones adicionales...")
                            try:
                                selectores_boton = [
                                    'button:has-text("Validar")', 'button:has-text("Verificar")',
                                    'button:has-text("Confirmar")', 'button:has-text("Enviar")',
                                    'button:has-text("Aceptar")', 'button:has-text("OK")',
                                    'button[type="submit"]', 'a:has-text("Enviar código nuevamente")',
                                    'a:has-text("Reenviar")'
                                ]
                                for selector in selectores_boton:
                                    try:
                                        boton = page.locator(selector).first
                                        if boton.is_visible():
                                            logger.info(f"✅ Encontrado botón: {selector}")
                                            boton.click(force=True)
                                            page.wait_for_timeout(2000)
                                            break
                                    except:
                                        pass
                                botones_buscados = True
                            except Exception as e:
                                logger.warning(f"Error buscando botones: {e}")
                        
                        if tiempo_pasado >= 40:
                            try:
                                frames = page.frames
                                for frame in frames:
                                    try:
                                        if "Bearer " in str(frame.content()):
                                            logger.warning("⚠️ Token puede estar en iframe")
                                    except:
                                        pass
                            except:
                                pass
                    
                    if not token_atrapado and not error_detectado:
                        logger.error("❌ TIMEOUT FINAL: 60 segundos sin token ni error")
                        try:
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            ruta_timeout = f"timeout_final_{timestamp}.png"
                            page.screenshot(path=ruta_timeout)
                            logger.error(f"✅ Captura guardada: {ruta_timeout}")
                            msg_timeout = (
                                f"🚨 *TIMEOUT FINAL - 60 SEGUNDOS SIN TOKEN*\n\n"
                                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"❌ No se atrapó Bearer token\n"
                                f"📸 Captura: {ruta_timeout}\n\n"
                            )
                            enviar_telegram(msg_timeout)
                        except Exception as e:
                            logger.error(f"❌ ERROR CAPTURANDO TIMEOUT: {e}")
                        codigo_exitoso = False
                    
                    break

            if not codigo_exitoso:
                logger.error("❌ No se pudo obtener token después de 18 intentos")
                return None

            page.wait_for_timeout(5000)
            
            if token_atrapado:
                logger.info("💾 Token detectado. Guardando Gafete VIP...")
                guardar_gafete_vip(gc_client, context)
                return token_atrapado

    except Exception as e:
        logger.error(f"❌ Excepción crítica: {e}")
        return None

    finally:
        logger.info("🧹 Limpiando Playwright...")
        if browser:
            try:
                browser.close()
            except:
                pass
        if p:
            try:
                p.stop()
            except:
                pass
        gc.collect()

# ==========================================
# 4. MÓDULO DE CACERÍA DE OFERTAS
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
        except: 
            pass
    return None

def obtener_info_rivales(liverpool_sku):
    url = f"https://shoppapp.liverpool.com.mx/appclienteservices/services/v2/marketplace/pdp/getSellersOfferDetailsPdp?skuId={liverpool_sku}"
    try:
        res = crear_session_con_retry().get(url, headers={"User-Agent": "Liverpool/2.2.0"}, timeout=30)
        if res.status_code == 200:
            rivales = []
            for v in res.json().get("sellersOfferDetails", []):
                if str(v.get("sellerId")) != str(SHOP_ID_PUBLICO):
                    rivales.append({
                        "precio": float(v.get("promoPrice") or v.get("salePrice")), 
                        "nombre": str(v.get("sellerName"))
                    })
            return sorted(rivales, key=lambda x: x["precio"])
    except: 
        pass
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
                if isinstance(fila[0], (list, tuple)):
                    self.historial_rows.extend(fila)
                else:
                    self.historial_rows.append(fila)
            else:
                self.historial_rows.append(fila)

    def agregar_archivo_negro(self, fila):
        with self._lock:
            self.archivo_negro_rows.append(fila)

    def agregar_alerta(self, mensaje):
        with self._lock:
            self.alertas.append(mensaje)

    def apagar_sku_liverpool(self, fila_excel, sku_i):
        with self._lock:
            self.skus_agotados_a_apagar.append((fila_excel, sku_i))

    def obtener_todos(self):
        with self._lock:
            return (
                list(self.historial_rows),
                list(self.archivo_negro_rows),
                list(self.alertas)
            )

# ==========================================
# 5. DISPARAR PRECIO
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
            "userModified": GMAIL_USER,
            "index": 0
        }]
    }]
    
    try:
        if MODO_SIMULACION:
            imprimir_simulacion(f"DISPARAR_PRECIO | SKU: {sku_notificacion} | Bajaría a: ${nuevo_precio}")
            return True
            
        logger.info(f"🎯 DISPARAR_PRECIO REAL | SKU: {sku_notificacion} | Bajando a: ${nuevo_precio}")
        logger.info(f"   SKU: {sku_notificacion}")
        logger.info(f"   Precio Nuevo: ${nuevo_precio}")
        logger.debug(f"   📦 PAYLOAD ENVIADO: {json.dumps(payload, indent=2, default=str)}")
        
        liverpool_rate_limiter.wait()
        session = crear_session_con_retry()
        
        response = session.put(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code in [200, 204]:
            logger.info(f"✅ Ajuste ejecutado: {enmascarar_precio(nuevo_precio)}")
            return True
        else:
            logger.error(f"❌ ERROR HTTP {response.status_code}")
            logger.error(f"❌ RESPUESTA COMPLETA DEL SERVIDOR: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Excepción en disparar_precio: {e}")
        return False

# ==========================================
# 🧠 CEREBRO ESTRATÉGICO LIVERPOOL (MODO LOCUTOR + POSTGRESQL)
# ==========================================

def procesar_sku(prod, token_lvp, db, resultados, contexto_scraping=None):
    """
    Cerebro táctico de Liverpool adaptado a PostgreSQL.
    Incluye Anti-Dumping, Circuit Breakers, Shadow Pricing y RADIO TELEGRAM.
    """
    try:
        # 1. Extracción de datos
        sku_lp = prod.get('sku_liverpool', '')
        sku_i = prod.get('sku_interno', prod.get('sku_limpio', 'Sin SKU'))
        estatus_regla = str(prod.get('estatus', 'ACTIVO')).strip().upper()
        tipo_regla = str(prod.get('regla_estrategia', '1. Gladiador')).strip()
        catalogo_id = prod.get('id')

        precio_minimo_regla = float(prod.get('precio_minimo', 0))
        precio_maximo_regla = float(prod.get('precio_maximo', 0))
        costo_odoo_sheet = float(prod.get('costo_odoo', 0))

        if not sku_lp:
            return

        # 2. Consultar nuestro estado actual
        oferta_mia = cazar_oferta_especifica(token_lvp, sku_i, sku_lp)

        query_historial = """
        INSERT INTO historial_precios (fecha_hora, sku_interno, sku_liverpool, precio_rival, nuestro_precio, stock, posicion, buybox)
        VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s)
        """

        if not oferta_mia or str(oferta_mia.get("state_code", "")).upper() != "ACTIVE":
            db.execute_update(query_historial, (sku_i, sku_lp, 0, 0, 0, 0, 'NO EJECUTADO'))
            return

        cantidad = int(oferta_mia.get("quantity", 0))
        offer_id = oferta_mia.get("offerId")
        base_price = float(oferta_mia.get("basePrice", 0))
        precio_actual = float(oferta_mia.get("discountPrice") or base_price)

        # 🔌 CIRCUIT BREAKER: Apagado automático por falta de stock
        if cantidad == 0:
            db.execute_update(query_historial, (sku_i, sku_lp, 0, precio_actual, 0, 0, 'Agotado'))
            if estatus_regla == 'ACTIVO':
                db.execute_update("UPDATE catalogo_maestro_v3 SET estatus = 'INACTIVO' WHERE id = %s", (catalogo_id,))
                resultados.skus_agotados_a_apagar.append((catalogo_id, sku_i))
                # 📢 ALERTA TELEGRAM
                resultados.agregar_alerta(f"🚨 *CIRCUIT BREAKER LVP*\nEl producto *{sku_i}* se quedó sin stock. Se apagó automáticamente (INACTIVO).")
            return

        # 3. Radar Espía (Rivales)
        info_rivales = obtener_info_rivales(sku_lp) 
        precios_rivales = [r["precio"] for r in info_rivales]

        logger.info(f"🔍 Escaneando {sku_i} | Regla: {tipo_regla}")

        # Guardar en BD para Dashboard
        if catalogo_id and info_rivales:
            for idx, r in enumerate(info_rivales[:5]):
                query_rival = "INSERT INTO monitoreo_rivales (catalogo_id, marketplace, nombre_rival, precio_rival, created_at) VALUES (%s, 'LIVERPOOL', %s, %s, NOW())"
                db.execute_update(query_rival, (catalogo_id, r["nombre"], float(r["precio"])))

        rival_mas_bajo = precios_rivales[0] if precios_rivales else 0.0

        # 📡 ANTI-DUMPING (Telegram)
        if precios_rivales:
            precio_viejo = resultados.ultimo_precio_conocido.get(sku_i, rival_mas_bajo) if hasattr(resultados, 'ultimo_precio_conocido') else rival_mas_bajo
            caida = float(precio_viejo) - float(rival_mas_bajo)
            if caida >= 100:
                culpable = info_rivales[0]["nombre"]
                resultados.agregar_alerta(f"🚨 *ALERTA ANTI-DUMPING*\nEl vendedor _{culpable}_ acaba de desplomar el mercado en *{sku_i}*.\n📉 Anterior: `${precio_viejo}` | 🩸 Nuevo: `${rival_mas_bajo}`")

        # ================= LÓGICA DE REGLAS Y TELEGRAM =================
        nuevo_precio = precio_actual

        if estatus_regla == 'INACTIVO':
            if info_rivales:
                rival_1 = info_rivales[0]
                estado_precio = "✅ TIENES MARGEN!" if precio_minimo_regla > 0 and rival_1["precio"] >= precio_minimo_regla else "❌ RIVAL REMATANDO."
                msg = f"🕵️ *RADAR ESPÍA*\n📦 *{sku_i}*\n👑 *Precio de la BuyBox:* `${rival_1['precio']}`\n📊 {estado_precio}\n🛡️ Tu mínimo: `${precio_minimo_regla}`"
                if costo_odoo_sheet > 0:
                    try:
                        gan, mar = calcular_rentabilidad(rival_1["precio"], costo_odoo_sheet)
                        msg += f"\n💡 *Para ganar a `${rival_1['precio']}`:*\nGanancia: `${gan:.2f}` (Margen: `{mar:.1f}%`)"
                    except: pass
                resultados.agregar_alerta(msg)
            db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, 0, 'INACTIVO'))
            return

        if estatus_regla == 'ACTIVO':
            # REGLA 2: ANCLA MÍNIMO
            if tipo_regla.startswith('2'):
                nuevo_precio = precio_minimo_regla
                if float(precio_actual) != float(nuevo_precio):
                    if disparar_precio(token_lvp, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        resultados.agregar_alerta(f"📌 *LÍMITE MÍNIMO ACTIVADO*\n\n📦 *{sku_i}*\nPrecio fijado en mínimo: `${nuevo_precio}`")
                        db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, 1, 'EJECUTADO'))
                else:
                    db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, 1, 'MANTENIDO'))

            # REGLA 3: COSECHA MÁXIMO
            elif tipo_regla.startswith('3'):
                nuevo_precio = precio_maximo_regla
                if float(precio_actual) != float(nuevo_precio):
                    if disparar_precio(token_lvp, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, 1, 'EJECUTADO'))
                else:
                    db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, 1, 'MANTENIDO'))

            # REGLAS COMPLEJAS (1, 4, 5, 6, 7, 8)
            else:
                if precios_rivales:
                    if tipo_regla.startswith('4') and rival_mas_bajo > precio_maximo_regla:
                        mejor_historico = resultados.max_precio_buybox_historico.get(sku_i, 0) if hasattr(resultados, 'max_precio_buybox_historico') else 0
                        nuevo_precio = mejor_historico if mejor_historico > 0 else precio_maximo_regla
                        msg_alerta = f"🧠 *ANALISTA HISTÓRICO*\n\n📦 *{sku_i}*\nRivales muy caros. Ajustando a histórico/máximo: `${nuevo_precio}`"
                        
                        if float(precio_actual) != float(nuevo_precio):
                            if disparar_precio(token_lvp, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                resultados.agregar_alerta(msg_alerta)
                                db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, 1, 'EJECUTADO'))
                        else:
                            db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, 1, 'MANTENIDO'))
                    else:
                        if rival_mas_bajo >= precio_minimo_regla:
                            margen_actual = round(float(rival_mas_bajo) - float(precio_actual), 2)
                            if 1.50 <= margen_actual <= 1.96:
                                db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, 1, 'MANTENIDO'))
                            else:
                                baja = round(random.uniform(1.50, 1.96), 2)
                                nuevo_precio = round(rival_mas_bajo - baja, 2)
                                if precio_maximo_regla > 0 and nuevo_precio > precio_maximo_regla: nuevo_precio = precio_maximo_regla
                                if nuevo_precio >= precio_minimo_regla:
                                    if disparar_precio(token_lvp, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                        db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, 1, 'EJECUTADO'))
                        else:
                            rivales_viables = [p for p in precios_rivales if p >= precio_minimo_regla]
                            if rivales_viables:
                                objetivo_sombra = rivales_viables[0]
                                nuevo_precio = round(float(int(objetivo_sombra) - 1) + 0.09, 2)
                                if nuevo_precio > precio_maximo_regla > 0: nuevo_precio = precio_maximo_regla
                                if nuevo_precio < precio_minimo_regla: nuevo_precio = precio_minimo_regla
                                
                                vendedor_ganador = info_rivales[0]["nombre"] if info_rivales else "Desconocido"
                                msg_alerta = f"🚨 *ALERTA TÁCTICA: Sombra Activada*\n\n📦 *{sku_i}*\n👑 Ganador actual: *{vendedor_ganador}*\n💰 Precio BuyBox: `${rival_mas_bajo}`\n🎯 Haciendo Sombra a: `${nuevo_precio}`...\n"
                                if costo_odoo_sheet > 0:
                                    try:
                                        gan, mar = calcular_rentabilidad(rival_mas_bajo, costo_odoo_sheet)
                                        msg_alerta += f"💡 Para ganar a `${rival_mas_bajo}`: Ganancia: `${gan:.2f}` | Margen: `{mar:.1f}%`"
                                    except: pass
                                
                                if disparar_precio(token_lvp, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                    resultados.agregar_alerta(msg_alerta)
                                    db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, 1, 'EJECUTADO'))
                            else:
                                vendedor_ganador = info_rivales[0]["nombre"] if info_rivales else "Desconocido"
                                msg_alerta = f"🛑 *ALERTA ROJA: Has perdido la BuyBox*\n\n📦 *{sku_i}*\n👑 Ganador actual: *{vendedor_ganador}*\n💰 Precio BuyBox: `${rival_mas_bajo}`\n🥶 Me quedo congelado en `${precio_actual}` (Mínimo: `${precio_minimo_regla}`).\n"
                                if costo_odoo_sheet > 0:
                                    try:
                                        gan_roja, mar_roja = calcular_rentabilidad(rival_mas_bajo, costo_odoo_sheet)
                                        msg_alerta += f"💡 Para salir (igualando a `${rival_mas_bajo}`):\nGanancia: `${gan_roja:.2f}` | Margen: `{mar_roja:.1f}%`"
                                    except: pass
                                resultados.agregar_alerta(msg_alerta)
                                db.execute_update(query_historial, (sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, 0, 'PERDIDA ROJA'))
                else:
                    nuevo_precio = precio_maximo_regla
                    if disparar_precio(token_lvp, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        db.execute_update(query_historial, (sku_i, sku_lp, 0, nuevo_precio, cantidad, 1, 'EJECUTADO'))

    except Exception as e:
        logger.error(f"❌ Error crítico en procesar_sku Liverpool: {e}")
        resultados.agregar_historial([
            (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
            str(sku_i) if 'sku_i' in locals() else sku_lp, sku_lp, "ERROR", 0, 0, "ERROR", str(e)
        ])

# ==========================================
# GUARDADO EN SQL A TRAVÉS DE DBMANAGER
# ==========================================
def guardar_en_sql(filas, db=None):
    """Guarda historial con DbManager PRIMARY + psycopg2 FALLBACK"""
    if MODO_SIMULACION:
        imprimir_simulacion(f"SQL OMITIDO | Se guardarían {len(filas)} registros.")
        return
    if not filas:
        return

    # Intento 1: DbManager (preferido)
    if db:
        try:
            registros_guardados = db.registrar_historial_liverpool(filas)
            logger.info(f"☁️ ¡{registros_guardados} registros via DbManager!")
            return
        except Exception as e:
            logger.warning(f"⚠️ DbManager falló: {e}. Usando psycopg2...")
    
    # Intento 2: psycopg2 directo (fallback)
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        query = """INSERT INTO historial_precios 
        (fecha_hora, sku_interno, sku_liverpool, precio_rival, nuestro_precio, stock, posicion, buybox) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
        cursor.executemany(query, filas)
        conn.commit()
        logger.info(f"☁️ ¡{cursor.rowcount} registros via psycopg2 fallback!")
    except Exception as e:
        logger.error(f"❌ CRÍTICO: Ambos métodos fallaron: {e}")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()

# ==========================================
# TRADUCTOR UNIVERSAL (NUBE O SHEETS)
# ==========================================
def obtener_reglas(gc_client, db):
    """Obtiene reglas de pricing desde PostgreSQL (V3) o Google Sheets como Fallback."""
    reglas = {}
    
    # Intento 1: Bóveda PostgreSQL
    if db:
        try:
            skus_bd = db.obtener_skus_activos('liverpool')
            if skus_bd:
                for idx, item in enumerate(skus_bd):
                    sku_lp = str(item.get('sku', '')).strip()
                    if sku_lp:
                        reglas[sku_lp] = {
                            'id': item.get('id'),
                            'sku_interno': str(item.get('sku_interno', sku_lp)),
                            'sku_liverpool': sku_lp,
                            'precio_minimo': item.get('precio_minimo', 0),
                            'precio_maximo': item.get('precio_maximo', 0),
                            'costo_odoo': item.get('costo_odoo', 0),
                            'estatus': 'ACTIVO',
                            'regla_estrategia': item.get('regla_estrategia', '1. Gladiador'),
                            'fila_excel': idx + 2  # Referencia para Circuit Breaker
                        }
                logger.info(f"📥 {len(reglas)} SKUs activos cargados desde PostgreSQL.")
                return reglas
        except Exception as e:
            logger.warning(f"⚠️ Error obteniendo SKUs desde BD: {e}. Activando Fallback a Sheets...")

    # Intento 2: Google Sheets (Fallback)
    try:
        hoja = gc_client.open_by_key(GOOGLE_SHEET_ID).worksheet("Hoja 1")
        registros = hoja.get_all_records()
        for idx, fila in enumerate(registros):
            sku_lp = str(fila.get('sku_liverpool') or fila.get('SKU_Liverpool') or fila.get('sku_lp', '')).strip()
            if sku_lp and str(fila.get('estatus', '')).strip().upper() == 'ACTIVO':
                fila['fila_excel'] = idx + 2
                reglas[sku_lp] = fila
        logger.info(f"📥 {len(reglas)} SKUs activos cargados desde Google Sheets (Fallback).")
        return reglas
    except Exception as e:
        logger.error(f"❌ Error obteniendo reglas de Sheets: {e}")
        return {}

# ==========================================
# FUNCIÓN PRINCIPAL
# ==========================================
def ejecutar_bot():
    logger.info("\n--- INICIANDO MEGAZORD LIVERPOOL V3 ENTERPRISE ---")
    enviar_telegram("🤖 *Megazord Liverpool* despertando...")
    
    load_dotenv()
    
    # 1. INICIALIZAR BASE DE DATOS
    try:
        db = DbManager()
        logger.info("✅ Conexión a PostgreSQL establecida")
    except Exception as e:
        logger.warning(f"⚠️ Error conectando a BD: {e}")
        db = None
    
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

    if not os.path.exists('credentials.json'):
        logger.error("❌ credentials.json no encontrado.")
        enviar_telegram("🚨 *ERROR MEGAZORD:* credentials.json no encontrado.")
        return

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        gc_connection = gspread.authorize(creds)
    except Exception as e:
        logger.error(f"❌ No se pudo conectar a Google Sheets: {e}")
        enviar_telegram("🚨 ERROR MEGAZORD: No se pudo conectar a Google Sheets.")
        return

    # Obtener token de Liverpool
    token = obtener_token_autonomo(gc_connection)
    if not token:
        logger.error("❌ No se pudo obtener token de Liverpool")
        enviar_telegram("🚨 ERROR MEGAZORD: No se pudo iniciar sesión en Liverpool.")
        return

    logger.info("🔑 Token obtenido exitosamente")
    logger.info("🧹 Garbage collector ejecutado - RAM limpia antes de la cacería")

    try:
        hoja_config = gc_connection.open_by_key(GOOGLE_SHEET_ID).worksheet("Config")
        hoja_rivales = gc_connection.open_by_key(GOOGLE_SHEET_ID).worksheet("Rivales")
    except Exception as e:
        logger.error(f"❌ No se pudo acceder a las hojas de cálculo: {e}")
        enviar_telegram("ERROR MEGAZORD: No se pudo acceder a las hojas de cálculo.")
        return

    # Obtener reglas (usando Traductor Universal)
    reglas = obtener_reglas(gc_connection, db)
    
    if not reglas:
        logger.warning("⚠️ No se encontraron SKUs activos para procesar.")
        return
        
    logger.info(f"🚀 Iniciando cacería concurrente con 3 hilos para {len(reglas)} SKUs...")

    resultados = ResultadosThreadSafe()
    sesion_compartida = crear_session_con_retry()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                procesar_sku_threadsafe,
                token, sku_lp, regla, resultados, gc_connection, hoja_config, sesion_compartida
            ): sku_lp
            for sku_lp, regla in reglas.items()
        }

        completados = 0
        for future in as_completed(futures):
            completados += 1
            if completados % 10 == 0:
                logger.info(f"⏳ Progreso: {completados}/{len(reglas)} SKUs procesados")

    logger.info(f"✅ Cacería completada: {completados} SKUs procesados")

    # Guardado final
    historial_rows, archivo_negro_rows, alertas = resultados.obtener_todos()

    # Enviar alertas acumuladas
    for alerta in alertas:
        enviar_alerta_telegram(alerta)

    # Guardar historial en PostgreSQL (Camino 2)
    if historial_rows:
        guardar_en_sql(historial_rows, db)

    # 🟢 NUEVO: Guardar Rivales en PostgreSQL (monitoreo_rivales)
    if archivo_negro_rows and db:
        guardados = 0
        for rival_data in archivo_negro_rows:
            try:
                db.registrar_rival(*rival_data)
                guardados += 1
            except:
                pass
        logger.info(f"📡 ¡{guardados} rivales inyectados en la tabla monitoreo_rivales de PostgreSQL!")
    elif archivo_negro_rows and not db:
        logger.warning("⚠️ DbManager no disponible, radar de rivales omitido.")

    # Actualizar contador de corridas
    try:
        corridas_actuales = int(hoja_config.acell("D3").value or 0)
        hoja_config.update_acell("D3", corridas_actuales + 1)
    except Exception as e:
        logger.warning(f"Error actualizando contador: {e}")

    # 🔌 CIRCUIT BREAKER: Apagar SKUs sin stock
    if resultados.skus_agotados_a_apagar:
        try:
            hoja_principal = gc_connection.open_by_key(GOOGLE_SHEET_ID).worksheet("Hoja 1")
            for fila_excel, sku_i in resultados.skus_agotados_a_apagar:
                hoja_principal.update_cell(fila_excel, 5, "INACTIVO")
                enviar_alerta_telegram(f"🚨 *CIRCUIT BREAKER LVP*\nProducto sin stock: `{sku_i}` → INACTIVO automático")
            logger.info(f"🔌 Circuit Breaker ejecutado. {len(resultados.skus_agotados_a_apagar)} productos apagados.")
        except Exception as e:
            logger.error(f"Error ejecutando Circuit Breaker: {e}")

    logger.info("🗑️ Forzando garbage collector final...")
    gc.collect()

    logger.info("\n🏁 Misión cumplida.")
    enviar_telegram("🏁 *BARRIDO MEGAZORD LIVERPOOL COMPLETADO*")

# ==========================================
# GATILLO DE ARRANQUE
# ==========================================
if __name__ == "__main__":
    ejecutar_bot()
