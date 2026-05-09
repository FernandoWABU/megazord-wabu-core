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

DATABASE_URL = os.getenv("DATABASE_URL")

# ==========================================
# FUNCIONES DE ENMASCARAMIENTO (LOGS PÚBLICOS PARA GITHUB)
# ==========================================
def enmascarar_sku(sku_real):
    """Convierte SKU real en hash para logs públicos de GitHub."""
    hash_sku = hashlib.md5(str(sku_real).encode()).hexdigest()[:6].upper()
    return f"SKU_{hash_sku}"

def enmascarar_vendedor(nombre_vendedor):
    """Protege identidades de competidores en logs públicos."""
    if not nombre_vendedor or nombre_vendedor == "Desconocido":
        return "Desconocido"
    marca_propia = os.getenv("PROPIA_BRAND_NAME", "WABU").upper()
    if marca_propia in str(nombre_vendedor).upper():
        return "NOSOTROS"
    return "RIVAL"

def enmascarar_precio(precio_real):
    """Oculta precios exactos en la consola de GitHub Actions."""
    try:
        return f"${int(float(precio_real))}.XX"
    except:
        return "$X.XX"

# ==========================================
# OPERACIÓN GAFETE VIP (ENCRIPTADO CON FERNET)
# ==========================================
def obtener_cipher():
    """Obtiene el cifrador Fernet desde variable de entorno.
    Retorna None si no está configurado (modo sin encriptación)."""
    llave = os.getenv("GOOGLE_ENCRYPTION_KEY")
    if not llave:
        logger.warning("⚠️ GOOGLE_ENCRYPTION_KEY no configurada - Gafete VIP funcionará sin encriptación")
        return None
    try:
        return Fernet(llave.encode())
    except Exception as e:
        logger.warning(f"⚠️ Error inicializando Fernet: {e} - Continuando sin encriptación")
        return None

def cargar_gafete_vip(gc_client, context):
    """Carga cookies desde Bóveda VIP (desencriptadas si es posible, sin encriptación si no)."""
    try:
        cipher = obtener_cipher()
        spreadsheet = gc_client.open_by_key(GOOGLE_SHEET_ID)
        hoja_boveda = spreadsheet.worksheet('Boveda_VIP')
        registros = hoja_boveda.get_all_records()
        for fila in registros:
            if fila.get('Tienda') == 'Liverpool' and fila.get('Cookies'):
                try:
                    # Si hay cifrador, desencriptar; si no, usar directo
                    if cipher:
                        datos_desencriptados = cipher.decrypt(fila['Cookies'].encode()).decode()
                        context.add_cookies(json.loads(datos_desencriptados))
                        logger.info("🍪 ¡Gafete VIP encriptado cargado exitosamente!")
                    else:
                        # Sin encriptación, asumir que están en JSON plano
                        context.add_cookies(json.loads(fila['Cookies']))
                        logger.info("🍪 ¡Gafete VIP cargado (sin encriptación)!")
                    return True
                except Exception as e:
                    logger.warning(f"⚠️ Cookies inválidas o corrupto: {e}")
                    return False
        return False
    except Exception as e:
        logger.warning(f"⚠️ No se encontró Bóveda VIP o error: {e}")
        return False

def guardar_gafete_vip(gc_client, context):
    """Guarda cookies en Bóveda VIP (encriptadas si es posible, sin encriptación si no)."""
    try:
        cipher = obtener_cipher()
        spreadsheet = gc_client.open_by_key(GOOGLE_SHEET_ID)
        hoja_boveda = spreadsheet.worksheet('Boveda_VIP')
        
        cookies_json = json.dumps(context.cookies())
        
        # Si hay cifrador, encriptar; si no, guardar en plano
        if cipher:
            cookies_guardados = cipher.encrypt(cookies_json.encode()).decode()
            msg = "🔐 ¡Nuevo Gafete VIP blindado y guardado en la Bóveda!"
        else:
            cookies_guardados = cookies_json
            msg = "🔐 ¡Nuevo Gafete VIP guardado en la Bóveda (sin encriptación)!"
        
        celdas = hoja_boveda.findall('Liverpool')
        if celdas:
            hoja_boveda.update_cell(celdas[0].row, 2, cookies_guardados)
        else:
            hoja_boveda.append_row(['Liverpool', cookies_guardados])
        logger.info(msg)
    except Exception as e:
        logger.error(f"❌ Error al guardar Gafete: {e}")

# ==========================================
# CONFIGURACIÓN DE LOGGING ESTRUCTURADO
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
# CONFIGURACIÓN DE RATE LIMITING
# ==========================================
class RateLimiter:
    """Controla la velocidad de peticiones para evitar bloqueos de API."""
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
# CONFIGURACIÓN DE RETRY CON BACKOFF
# ==========================================
def crear_session_con_retry():
    """Crea sesión requests con reintentos automáticos."""
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
# CONSTANTES DEL SISTEMA
# ==========================================
SHOP_ID_INTERNO = os.getenv("SHOP_ID_INTERNO", "").strip()
SHOP_ID_PUBLICO = os.getenv("SHOP_ID_PUBLICO", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GMAIL_USER = os.getenv("LIVERPOOL_USER")
LIVERPOOL_PASS = os.getenv("LIVERPOOL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")

# ==========================================
# FUNCIONES DE TELEGRAM Y CONEXIÓN
# ==========================================
def enviar_alerta_telegram(mensaje):
    """Envía alerta a Telegram (datos REALES - privado)."""
    enviar_telegram(mensaje)

def enviar_telegram(mensaje):
    """Envía mensaje a Telegram CON DATOS REALES (es privado, no enmascaramos)."""
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_WMT:
            logger.warning("Telegram no configurado (TOKEN o CHAT_ID faltantes)")
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_WMT, "text": mensaje, "parse_mode": "Markdown"})
    except Exception as e:
        logger.error(f"Error enviando Telegram: {e}")

def enviar_foto_telegram(ruta_foto, mensaje):
    """Envía foto por Telegram."""
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_WMT:
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(ruta_foto, 'rb') as foto:
            requests.post(url, data={'chat_id': TELEGRAM_CHAT_WMT, 'caption': mensaje}, files={'photo': foto})
    except Exception as e:
        logger.error(f"Error al enviar foto por Telegram: {e}")

def obtener_conexion_sheets(gc):
    """Obtiene conexión a Google Sheets."""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    return gspread.authorize(creds)

# ==========================================
# FUNCIONES DE MATEMÁTICAS
# ==========================================
def safe_float(valor):
    """Convierte valor a float de forma segura."""
    try:
        if valor is None or str(valor).strip() == '':
            return 0.0
        return float(str(valor).replace('$', '').replace(',', '').strip())
    except Exception as e:
        logger.warning(f"safe_float falló con '{valor}': {e}")
        return 0.0

def calcular_rentabilidad(precio_venta, costo_odoo):
    """
    Calcula ganancia y margen según el Simulador Financiero de Liverpool.
    Fórmula: (ingreso_neto - costo_con_iva) / costo_con_iva * 100
    """
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
    except Exception as e:
        logger.warning(f"Error en calcular_rentabilidad: {e}")
        return 0.0, 0.0

# ==========================================
# 3. MÓDULO DE INFILTRACIÓN (PLAYWRIGHT COMPLETO)
# ==========================================
def obtener_token_autonomo(gc_client):
    """Obtiene token de Liverpool usando Gafete VIP + Playwright con simulación humana."""
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
        
        # 🟢 INYECTAR GAFETE ANTES DE ABRIR LA PÁGINA
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

        # 🟢 VERIFICAR SI EL GAFETE FUNCIONÓ
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
            # FLUJO NORMAL CON SIMULACIÓN HUMANA
            page.goto("https://marketplace.liverpool.com.mx/")
            page.wait_for_selector('input#username, #username, input[name="username"], input[type="email"]', timeout=30000)

            # SIMULACIÓN HUMANA - TECLEO LENTO Y PAUSAS
            page.locator('input#username').click()
            page.locator('input#username').type(GMAIL_USER, delay=random.randint(100, 250))
            page.wait_for_timeout(random.randint(500, 1000))
            
            page.locator('input#password').click()
            page.locator('input#password').type(LIVERPOOL_PASS, delay=random.randint(100, 250))

            # Obtener hoja de config para capturar código 2FA
            try:
                gc_aux = obtener_conexion_sheets(None)
                matriz = gc_aux.open_by_key(GOOGLE_SHEET_ID)
                hoja_config = matriz.worksheet("Config")
            except:
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
                if hoja_config:
                    try:
                        codigo_nuevo = str(hoja_config.acell("B1").value).replace("'", "").strip()
                        logger.info(f"🔄 Intento {i+1}/18 | Código actual en Excel: {codigo_nuevo}")

                        if codigo_nuevo != codigo_antiguo and len(codigo_nuevo) == 6:
                            logger.info(f"✅ ¡NUEVO Código interceptado!: {codigo_nuevo}")

                            caja_codigo = page.locator('input:not([disabled]):not([readonly]):not([type="checkbox"]):not([type="hidden"]):visible').first
                            caja_codigo.click(force=True)
                            page.wait_for_timeout(500)
                            
                            page.keyboard.type(codigo_nuevo, delay=random.randint(200, 400))
                            page.wait_for_timeout(1500)

                            boton_continuar = page.locator('button:has-text("Continuar")').first
                            boton_continuar.click(force=True)

                            # ==========================================
                            # ESPERANZA INTELIGENTE: DETECTAR ERRORES 2FA EN VIVO
                            # ==========================================
                            logger.info("⏳ Esperando token... (monitoreo de errores 2FA activo)")
                            
                            error_detectado = False
                            tiempo_inicio_espera = time.time()
                            timeout_token = 60
                            
                            while time.time() - tiempo_inicio_espera < timeout_token:
                                time.sleep(1)
                                
                                # VERIFICAR SI EL TOKEN APARECIÓ
                                if token_atrapado:
                                    logger.info("🔑 ¡TOKEN ATRAPADO CON ÉXITO!")
                                    guardar_gafete_vip(gc_client, context)
                                    codigo_exitoso = True
                                    break
                                
                                # VERIFICAR SI APARECE ERROR EN LA PÁGINA
                                try:
                                    mensajes_error = [
                                        "código inválido",
                                        "código incorrecto",
                                        "código expirado",
                                        "código caducado",
                                        "código erróneo",
                                        "invalid code",
                                        "incorrect code",
                                        "expired code",
                                        "intento fallido",
                                        "no válido",
                                        "algo salió mal",
                                        "vuelve a intentar",
                                        "error de verificación"
                                    ]
                                    
                                    contenido_pagina = page.content().lower()
                                    
                                    for msg_error in mensajes_error:
                                        if msg_error in contenido_pagina:
                                            error_detectado = True
                                            logger.error(f"🚨 ERROR 2FA DETECTADO: '{msg_error}'")
                                            break
                                    
                                    if error_detectado:
                                        break
                                    
                                except Exception as e:
                                    pass
                            
                            # MANEJO DE RESULTADO
                            if error_detectado:
                                logger.error("❌ ERROR 2FA DETECTADO - Aborting inmediatamente...")
                                try:
                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    ruta_error = f"error_2fa_{timestamp}.png"
                                    page.screenshot(path=ruta_error)
                                    logger.error(f"📸 Captura guardada: {ruta_error}")
                                    
                                    mensaje_error = (
                                        f"🚨 *ERROR 2FA LIVERPOOL*\n\n"
                                        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                                        f"❌ Liverpool rechazó el código\n"
                                        f"📸 Ver captura\n\n"
                                        f"Causas posibles:\n"
                                        f"• Código caducado (>30 min)\n"
                                        f"• Gmail atrasada\n"
                                        f"• Error de Liverpool"
                                    )
                                    enviar_telegram(mensaje_error)
                                    enviar_foto_telegram(ruta_error, "🚨 Error 2FA: Rechazado")
                                except Exception as e:
                                    logger.error(f"Error capturando: {e}")
                                
                                codigo_exitoso = False
                            
                            elif not token_atrapado:
                                logger.error("❌ TIMEOUT: 60 segundos sin token")
                                try:
                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    ruta_timeout = f"timeout_2fa_{timestamp}.png"
                                    page.screenshot(path=ruta_timeout)
                                    enviar_foto_telegram(ruta_timeout, "⏱️ Timeout: Sin token en 60s")
                                except:
                                    pass
                                codigo_exitoso = False
                            
                            break
                    except:
                        pass

            if not codigo_exitoso:
                logger.error("❌ TIEMPO AGOTADO: El código en el Excel no cambió.")
                return None

            page.wait_for_timeout(15000)
            
            if token_atrapado:
                logger.info("💾 Token detectado. Guardando Gafete VIP en la bóveda...")
                guardar_gafete_vip(gc_client, context)
                
            return token_atrapado

    finally:
        logger.info("🧹 Limpiando instancias de Playwright...")
        if browser is not None:
            try:
                browser.close()
                logger.info("✅ Browser cerrado")
            except Exception as e:
                logger.warning(f"Error al cerrar browser: {e}")
                
        if p is not None:
            try:
                p.stop()
                logger.info("✅ Playwright detenido")
            except Exception as e:
                logger.warning(f"Error al detener Playwright: {e}")
        
        logger.info("🗑️ Forzando garbage collector para liberar RAM...")
        gc.collect()
        
        return token_atrapado

# ==========================================
# 4. MÓDULO DE CACERÍA DE OFERTAS
# ==========================================
def cazar_oferta_especifica(token, sku_interno, sku_liverpool):
    """Obtiene detalles de una oferta específica usando API interna."""
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
    """Obtiene lista de rivales ordenada por precio."""
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
    """Calcula posición en la BuyBox."""
    if not precios_rivales:
        return "1 de 1", "¡Nosotros! 👑"
    todos = sorted(precios_rivales + [nuestro_precio])
    posicion = todos.index(nuestro_precio) + 1
    total = len(todos)
    return f"#{posicion} de {total}", "¡Nosotros! 👑" if posicion == 1 else f"Rival (${todos[0]})"

# ==========================================
# CLASE DE RESULTADOS THREAD-SAFE (FUNDAMENTAL)
# ==========================================
class ResultadosThreadSafe:
    """Almacena resultados de forma thread-safe para evitar race conditions."""
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
        """Agrega fila de historial de forma thread-safe."""
        with self._lock:
            if isinstance(fila, list) and fila:
                # Si es lista de listas, extiende; si es una sola fila, apéndice
                if isinstance(fila[0], (list, tuple)):
                    self.historial_rows.extend(fila)
                else:
                    self.historial_rows.append(fila)
            else:
                self.historial_rows.append(fila)

    def agregar_archivo_negro(self, fila):
        """Agrega registro de rival al archivo negro de forma thread-safe."""
        with self._lock:
            self.archivo_negro_rows.append(fila)

    def agregar_alerta(self, mensaje):
        """Agrega alerta de Telegram de forma thread-safe."""
        with self._lock:
            self.alertas.append(mensaje)

    def apagar_sku_liverpool(self, fila_excel, sku_i):
        """Marca un SKU para apagarse (sin stock) de forma thread-safe."""
        with self._lock:
            self.skus_agotados_a_apagar.append((fila_excel, sku_i))

    def obtener_todos(self):
        """Retorna copias seguras de todos los datos acumulados."""
        with self._lock:
            return (
                list(self.historial_rows),
                list(self.archivo_negro_rows),
                list(self.alertas)
            )

# ==========================================
# 5. DISPARAR PRECIO (SOLO ACTUALIZACIÓN + NOTIFICACIÓN)
# ==========================================
def disparar_precio(token, offer_id, stock, base_price, nuevo_precio, sku_notificacion=""):
    """
    Actualiza precio en Liverpool y notifica.
    DUAL LOGS: Enmascarado en GitHub, REAL en Telegram.
    """
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
            "userModified": os.getenv("LIVERPOOL_USER", "Bot"),
            "index": 0
        }]
    }]
    try:
        liverpool_rate_limiter.wait()
        session = crear_session_con_retry()
        response = session.put(url, headers=headers, json=payload, timeout=30)
        if response.status_code in [200, 204]:
            # ✅ DUAL LOGS: GitHub enmascarado, Telegram REAL
            logger.info(f"✅ Ajuste táctico ejecutado: {enmascarar_precio(nuevo_precio)}")
            enviar_telegram(f"🔫 *FRANCOTIRADOR LIVERPOOL*\n🎯 Producto: `{sku_notificacion}`\n💰 Nuevo Precio: *${nuevo_precio:,.2f}*")
            return True
        else:
            logger.warning(f"⚠️ Error al actualizar precio: HTTP {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Excepción en disparar_precio: {e}")
        return False

# ==========================================
# 6. CEREBRO ESTRATÉGICO (LÓGICA COMPLETA DE COMBATE - LAS 8 REGLAS INTACTAS)
# ==========================================
def procesar_sku_threadsafe(token, sku_lp, regla, resultados, gc_client, hoja_config, session):
    """
    Procesa un SKU con TODA la lógica de combate.
    PROHIBIDO MUTILAR: Aquí van las 8 reglas COMPLETAS.
    """
    try:
        sku_i = str(regla.get('sku') or regla.get('sku_interno') or regla.get('SKU_Interno') or regla.get('SKU') or 'Sin SKU')
        estatus_regla = str(regla.get('estatus', '')).strip().upper()
        tipo_regla = str(regla.get('regla_estrategia', '1. Gladiador')).strip()
        fila_excel = regla.get('fila_excel', 0)

        # Cazar oferta
        prod = cazar_oferta_especifica(token, sku_i, sku_lp)

        if not prod or str(prod.get("state_code", "")).upper() != "ACTIVE":
            resultados.agregar_historial([
                (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                str(sku_i), str(sku_lp), "Oculto/Agotado", 0, 0, "N/A", "N/A"
            ])
            return

        cantidad = int(prod.get("quantity", 0))
        offer_id = prod.get("offerId")
        base_price = float(prod.get("basePrice", 0))
        precio_actual = float(prod.get("discountPrice") or base_price)

        # 🟢 INICIALIZAR NUEVO_PRECIO COMO SEGURO
        nuevo_precio = precio_actual

        # Verificar quiebre de inventario
        if cantidad == 0:
            resultados.agregar_historial([
                (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                str(sku_i), str(sku_lp), "Agotado", precio_actual, 0, "N/A", "N/A"
            ])
            if estatus_regla == 'ACTIVO':
                resultados.apagar_sku_liverpool(fila_excel, sku_i)
            return

        # Obtener info de rivales
        info_rivales = obtener_info_rivales(sku_lp)
        precios_rivales = [r["precio"] for r in info_rivales]

        precio_minimo_regla = safe_float(regla.get('precio_minimo', 0))
        precio_maximo_regla = safe_float(regla.get('precio_maximo', base_price) or base_price)
        costo_odoo_sheet = safe_float(regla.get('costo_odoo', 0))

        # ✅ LOGS PÚBLICOS - ENMASCARADOS
        sku_display = enmascarar_sku(sku_lp)
        logger.info(f"🔍 Escaneando {sku_display} | BB: {enmascarar_vendedor(info_rivales[0]['nombre'] if info_rivales else 'N/A')}")

        # Registro de rivales (Archivo Negro)
        hora_actual_str = (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        for r in info_rivales[:5]:
            resultados.agregar_archivo_negro([hora_actual_str, sku_i, r["nombre"], r["precio"]])

        # Alerta anti-dumping
        if precios_rivales:
            rival_mas_bajo = precios_rivales[0]
            precio_viejo = resultados.ultimo_precio_conocido.get(sku_i, rival_mas_bajo) if hasattr(resultados, 'ultimo_precio_conocido') else rival_mas_bajo
            caida = precio_viejo - rival_mas_bajo
            if caida >= 100:
                culpable = info_rivales[0]["nombre"]
                resultados.agregar_alerta(f"🚨 *ALERTA ANTI-DUMPING*\nEl vendedor _{culpable}_ acaba de desplomar el mercado en *{sku_i}*.\n📉 Anterior: `${precio_viejo}` | 🩸 Nuevo: `${rival_mas_bajo}`")

        # ========== LÓGICA POR TIPO DE REGLA (CEREBRO COMPLETO) ==========
        if estatus_regla == 'INACTIVO':
            # MODO ESPÍA: Solo observa, no actúa
            if info_rivales:
                rival_1 = info_rivales[0]
                estado_precio = "✅ TIENES MARGEN!" if precio_minimo_regla > 0 and rival_1["precio"] >= precio_minimo_regla else "❌ RIVAL REMATANDO."
                msg = f"🕵️ *RADAR ESPÍA*\n📦 *{sku_i}*\n👑 *Precio de la BuyBox:* `${rival_1['precio']}`\n📊 {estado_precio}\n🛡️ Tu mínimo: `${precio_minimo_regla}`"
                if costo_odoo_sheet > 0:
                    gan, mar = calcular_rentabilidad(rival_1["precio"], costo_odoo_sheet)
                    msg += f"\n💡 *Para ganar a `${rival_1['precio']}`:*\nGanancia: `${gan:.2f}` (Margen: `{mar:.1f}%`)"
                resultados.agregar_alerta(msg)
            resultados.agregar_historial([
                hora_actual_str, sku_i, sku_lp,
                precios_rivales[0] if precios_rivales else "SIN RIVAL",
                precio_actual, cantidad, "Inactivo", "Inactivo"
            ])
            return

        if estatus_regla == 'ACTIVO':
            # REGLA 2: ANCLA MÍNIMO
            if tipo_regla.startswith('2'):
                nuevo_precio = precio_minimo_regla
                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                if float(precio_actual) != float(nuevo_precio):
                    if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", nuevo_precio, cantidad, pos, bb])
                else:
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", precio_actual, cantidad, pos, bb])

            # REGLA 3: COSECHA MÁXIMO
            elif tipo_regla.startswith('3'):
                nuevo_precio = precio_maximo_regla
                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                if float(precio_actual) != float(nuevo_precio):
                    if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", nuevo_precio, cantidad, pos, bb])
                else:
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", precio_actual, cantidad, pos, bb])

            # REGLAS 1, 4, 5, 6, 7, 8: GLADIADOR Y DERIVADOS (LÓGICA DE PELEA COMPLETA)
            else:
                if precios_rivales:
                    rival_mas_bajo = precios_rivales[0]

                    # REGLA 4: ANALISTA HISTÓRICO
                    if tipo_regla.startswith('4') and rival_mas_bajo > precio_maximo_regla:
                        mejor_historico = resultados.max_precio_buybox_historico.get(sku_i, 0) if hasattr(resultados, 'max_precio_buybox_historico') else 0
                        if mejor_historico > 0:
                            nuevo_precio = mejor_historico
                            msg_alerta = f"🧠 *ANALISTA HISTÓRICO*\nRivales muy caros en *{sku_i}*. Ajustando a tu mejor precio histórico ganador: `${nuevo_precio}`."
                        else:
                            nuevo_precio = precio_maximo_regla
                            msg_alerta = f"🧠 *ANALISTA HISTÓRICO*\nRivales muy caros en *{sku_i}*. Sin historial previo, ajustando a tu máximo: `${nuevo_precio}`."

                        pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                        if float(precio_actual) != float(nuevo_precio):
                            if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                resultados.agregar_alerta(msg_alerta)
                                resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, pos, bb])
                        else:
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb])

                    # REGLAS 1, 5, 6, 7, 8: GLADIADOR Y VARIANTES (LÓGICA DE ATAQUE)
                    else:
                        if rival_mas_bajo >= precio_minimo_regla:
                            margen_actual = round(float(rival_mas_bajo) - float(precio_actual), 2)
                            if 1.50 <= margen_actual <= 1.96:
                                # El margen ya es óptimo, no hacer nada
                                pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                                resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb])
                            else:
                                # Calcular baja aleatoria entre 1.50 y 1.96
                                baja = round(random.uniform(1.50, 1.96), 2)
                                nuevo_precio = round(rival_mas_bajo - baja, 2)
                                if precio_maximo_regla > 0 and nuevo_precio > precio_maximo_regla:
                                    nuevo_precio = precio_maximo_regla

                                if nuevo_precio >= precio_minimo_regla:
                                    pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                                    if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, pos, bb])
                        else:
                            # EL RIVAL ESTÁ MUY BAJO: ACTIVAR SOMBRA
                            rivales_viables = [p for p in precios_rivales if p >= precio_minimo_regla]
                            if rivales_viables:
                                objetivo_sombra = rivales_viables[0]
                                nuevo_precio = round(float(int(objetivo_sombra) - 1) + 0.09, 2)
                                if precio_maximo_regla > 0 and nuevo_precio > precio_maximo_regla:
                                    nuevo_precio = precio_maximo_regla
                                if nuevo_precio < precio_minimo_regla:
                                    nuevo_precio = precio_minimo_regla

                                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                                msg_alerta = (f"🛡️ *ALERTA TÁCTICA: Sombra Activada*\n\n"
                                              f"📦 *{sku_i}*\n"
                                              f"👑 *Precio de la BuyBox:* `${rival_mas_bajo}`\n"
                                              f"⚠️ _Haciendo Sombra a `${nuevo_precio}`..._")
                                if costo_odoo_sheet > 0:
                                    gan, mar = calcular_rentabilidad(rival_mas_bajo, costo_odoo_sheet)
                                    msg_alerta += f"\n💡 *Proyección para 1er lugar (a `${rival_mas_bajo}`):*\nGanancia: `${gan:.2f}` | Margen: `{mar:.1f}%`"

                                resultados.agregar_alerta(msg_alerta)
                                if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, pos, bb])
                            else:
                                # DERROTA: CONGELARSE EN MÍNIMO
                                pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                                msg_alerta = (f"🛑 *ALERTA ROJA: Has perdido la BuyBox*\n\n"
                                              f"📦 *{sku_i}*\n"
                                              f"👑 *Precio de la BuyBox:* `${rival_mas_bajo}`\n"
                                              f"🥶 _Me quedo congelado en `${precio_actual}` (Mínimo: `${precio_minimo_regla}`)._")
                                if costo_odoo_sheet > 0:
                                    gan, mar = calcular_rentabilidad(rival_mas_bajo, costo_odoo_sheet)
                                    msg_alerta += f"\n💡 *Para poder salir (igualando a `${rival_mas_bajo}`):*\nGanancia: `${gan:.2f}` | Margen: `{mar:.1f}%`"

                                resultados.agregar_alerta(msg_alerta)
                                resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb])
                else:
                    # SIN RIVALES: SOLO NOSOTROS
                    if tipo_regla.startswith('4'):
                        mejor_historico = resultados.max_precio_buybox_historico.get(sku_i, precio_maximo_regla) if hasattr(resultados, 'max_precio_buybox_historico') else precio_maximo_regla
                        nuevo_precio = mejor_historico if mejor_historico > 0 else precio_maximo_regla
                        if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, "SIN RIVAL", nuevo_precio, cantidad, "1 de 1", "¡Nosotros! 👑"])
                    else:
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, "SIN RIVAL", precio_actual, cantidad, "1 de 1", "¡Nosotros! 👑"])

    except Exception as e:
        logger.error(f"❌ Error procesando SKU {enmascarar_sku(sku_lp)}: {e}")
        resultados.agregar_historial([
            (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
            str(sku_i) if 'sku_i' in locals() else sku_lp, sku_lp, "ERROR", 0, 0, "ERROR", str(e)
        ])

# ==========================================
# GUARDADO EN SQL
# ==========================================
def guardar_en_sql(filas):
    """Guarda historial en PostgreSQL (Render)."""
    if not filas:
        return

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        query = """
        INSERT INTO historial_precios 
        (fecha_hora, sku_interno, sku_liverpool, precio_rival, nuestro_precio, stock, posicion, buybox) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """

        cursor.executemany(query, filas)
        conn.commit()
        logger.info(f"☁️ ¡{cursor.rowcount} registros guardados exitosamente en la Nube SQL!")

    except Exception as e:
        logger.error(f"❌ Error al guardar en SQL: {e}")
    finally:
        if 'cursor' in locals() and cursor: 
            cursor.close()
        if 'conn' in locals() and conn: 
            conn.close()

# ==========================================
# OBTENER REGLAS DESDE SHEETS
# ==========================================
def obtener_reglas_sheets(gc_client):
    """Obtiene reglas de pricing desde Google Sheets."""
    try:
        hoja = gc_client.open_by_key(GOOGLE_SHEET_ID).worksheet("Hoja 1")
        registros = hoja.get_all_records()
        reglas = {}

        for idx, fila in enumerate(registros):
            sku_lp = str(fila.get('sku_liverpool') or fila.get('SKU_Liverpool') or fila.get('sku_lp', '')).strip()
            if sku_lp:
                fila['fila_excel'] = idx + 2
                reglas[sku_lp] = fila

        return reglas
    except Exception as e:
        logger.error(f"❌ Error obteniendo reglas: {e}")
        return {}

# ==========================================
# FUNCIÓN PRINCIPAL
# ==========================================
def ejecutar_bot():
    """Ejecuta el bot principal de Liverpool con toda su potencia."""
    logger.info("\n--- INICIANDO MEGAZORD LIVERPOOL V16.0 (CONCURRENCIA + DUAL LOGS + ENCRIPTADO) ---")
    enviar_telegram("🤖 *Megazord Liverpool* despertando...")
    
    load_dotenv()
    
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

    # Validar existencia de credentials
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
        hoja_rivales = gc_connection.open_by_key(GOOGLE_SHEET_ID).worksheet("Archivo Negro")
    except Exception as e:
        logger.error(f"❌ No se pudo acceder a las hojas de cálculo: {e}")
        enviar_telegram("ERROR MEGAZORD: No se pudo acceder a las hojas de cálculo.")
        return

    reglas = obtener_reglas_sheets(gc_connection)
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

    # Guardar historial
    if historial_rows:
        guardar_en_sql(historial_rows)

    # Guardar Archivo Negro
    if archivo_negro_rows:
        try:
            hoja_rivales.append_rows(archivo_negro_rows)
            logger.info(f"📝 Guardados {len(archivo_negro_rows)} registros en Archivo Negro")
        except Exception as e:
            logger.error(f"Error guardando Archivo Negro: {e}")

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
