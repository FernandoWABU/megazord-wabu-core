#!/usr/bin/env python3
# ==========================================
# MEGAZORD LIVERPOOL - VERSIÓN ENTERPRISE V5.4
# ==========================================
# 🚀 AUTO-RENOVACIÓN DE TOKENS (PLAYWRIGHT)
# 🚀 ARQUITECTURA MULTI-TENANT (MULTI-CUENTA)
# 🛡️ V5.4: DATADOME PRESERVATION & HYBRID FALLBACK
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
    url = f"https://pro-api.liverpool.com.mx/api/offermanagement/offers?shop_id={SHOP_ID_INTERNO}&sku={urllib.parse.quote(sku_test)}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 401: return False
        return True
    except: 
        return True 

# ==========================================
# 🕵️‍♂️ FUNCIÓN AUXILIAR - WARM-UP DATADOME
# ==========================================
def calentar_datadome(page, context, logger):
    """
    🔥 V5.5: WARM-UP AGRESIVO CON URLS DINÁMICAS + INTERACCIÓN HUMANA + DIAGNÓSTICO
    
    Datadome puede ignorar navegación pasiva. Forzamos interacción humana.
    Loguea TODAS las cookies para diagnóstico.
    """
    
    logger.info(f"🔥 WARM-UP V5.5: Calentamiento agresivo con interacción...")
    
    urls_warmup_dinamicas = [
        ("marketplace search", "https://marketplace.liverpool.com.mx/?search=test&sort=relevance"),
        ("product list", "https://marketplace.liverpool.com.mx/offers?category=electronics&page=1"),
        ("raíz con session", "https://marketplace.liverpool.com.mx/?nocache=" + str(int(time.time()))),
    ]
    
    for nombre_url, url in urls_warmup_dinamicas:
        try:
            logger.info(f"   🌐 Navegando a {nombre_url}...")
            page.goto(url, wait_until="domcontentloaded", timeout=10000)
            
            # Simular actividad humana
            logger.info(f"   👆 Simular scroll y clic...")
            page.evaluate("window.scrollBy(0, 300)")
            page.wait_for_timeout(500)
            
            # Buscar elemento clicable
            try:
                enlaces = page.locator("a").all()
                if enlaces:
                    enlaces[0].click(force=True, delay=100)
                    logger.info(f"   ✅ Clic ejecutado")
            except:
                pass
            
            page.wait_for_timeout(3000)
            
            # Verificar cookies
            todas_cookies = context.cookies()
            tiene_datadome = any(
                x in c.get('name', '').lower() 
                for c in todas_cookies 
                for x in ['datadome', 'cf_clearance', '__cf', 'cf_bm']
            )
            
            # DEBUG: Listar TODAS las cookies
            logger.info(f"   📦 Cookies después de {nombre_url}:")
            if todas_cookies:
                for c in todas_cookies:
                    logger.info(f"      - {c['name']} (domain: {c.get('domain', 'N/A')})")
            else:
                logger.warning(f"   ⚠️ NO HAY COOKIES - Datadome BLOQUEANDO")
            
            if tiene_datadome:
                logger.info(f"   ✅ Datadome clearance obtenido")
                return True
            else:
                logger.warning(f"   ⚠️ Sin clearance en {nombre_url}, intentando siguiente...")
        
        except Exception as e:
            logger.warning(f"   ⚠️ Error en warm-up {nombre_url}: {e}")
            continue
    
    logger.warning(f"   ⚠️ WARM-UP V5.5 completado SIN clearance")
    logger.error(f"   🚨 DIAGNÓSTICO: Datadome parece estar HARD BLOQUEANDO desde GitHub Actions")
    
    return False

# ==========================================
# 🕵️‍♂️ FUNCIÓN AUXILIAR - DIAGNÓSTICO WHITE SCREEN
# ==========================================
def diagnosticar_white_screen(page, logger):
    """
    🔍 RUTA 1: Analiza si es White Screen real o página de bloqueo
    Captura HTML completo para análisis forense
    """
    try:
        html = page.content()
        titulo = page.title()
        
        logger.error(f"📄 DIAGNÓSTICO DE PÁGINA:")
        logger.error(f"   - Título: {titulo}")
        logger.error(f"   - HTML Length: {len(html)} caracteres")
        logger.error(f"   - URL actual: {page.url}")
        
        # Buscar indicios de bloqueo Datadome/Cloudflare
        indicios_bloqueo = {
            "503 Service Unavailable": "Servicio no disponible",
            "Access Denied": "Acceso denegado",
            "blocked": "Bloqueado",
            "captcha": "CAPTCHA detectado",
            "verify": "Verificación requerida",
            "robot": "Detección de bot",
            "automated": "Tráfico automatizado",
            "datadome": "Datadome bloqueo",
            "perimeter": "PerimeterX bloqueo",
            "challenge": "Desafío de seguridad",
        }
        
        indicios_encontrados = []
        for indicio, descripcion in indicios_bloqueo.items():
            if indicio.lower() in html.lower():
                indicios_encontrados.append(descripcion)
                logger.error(f"   🚨 {descripcion}")
        
        # Análisis de estructura HTML
        tiene_inputs = "input" in html.lower()
        tiene_forms = "form" in html.lower()
        tiene_buttons = "button" in html.lower()
        tiene_react = "react" in html.lower() or "__NEXT_DATA__" in html
        
        logger.error(f"   ✓ Tiene <input>: {tiene_inputs}")
        logger.error(f"   ✓ Tiene <form>: {tiene_forms}")
        logger.error(f"   ✓ Tiene <button>: {tiene_buttons}")
        logger.error(f"   ✓ Detectado React/Next: {tiene_react}")
        
        # Diagnóstico final
        if indicios_encontrados:
            return "BLOQUEADO_POR_SEGURIDAD", indicios_encontrados
        elif len(html) < 500:
            return "WHITE_SCREEN", ["HTML muy pequeño"]
        elif not tiene_inputs and not tiene_forms:
            return "PAGINA_SIN_FORM", ["No hay campos de entrada"]
        elif tiene_react and not tiene_inputs:
            return "REACT_NO_RENDERIZADO", ["React cargado pero sin contenido"]
        else:
            return "DESCONOCIDO", []
    
    except Exception as e:
        logger.error(f"❌ Error diagnosticando: {e}")
        return "ERROR_DIAGNOSTICO", [str(e)]

# ==========================================
# 🕵️‍♂️ FUNCIÓN AUXILIAR - MOBILE API FALLBACK
# ==========================================
def intentar_login_mobile_api(email_usuario, password, logger):
    """
    🔄 RUTA 2: Fallback via Mobile API si Datadome bloquea web
    Las APIs mobile tienen menos protección que web
    """
    
    logger.info(f"📱 RUTA 2: Intentando login via Mobile API...")
    
    # Endpoints mobile hipotéticos (ajustar según Liverpool real)
    endpoints_mobile = [
        ("GraphQL API", "https://mobile-api.liverpool.com.mx/graphql", "graphql"),
        ("REST Auth", "https://api.liverpool.com.mx/v1/auth/login", "rest"),
        ("Legacy Mobile", "https://m.liverpool.com.mx/api/login", "legacy"),
    ]
    
    session = crear_session_con_retry()
    
    for nombre_endpoint, url, tipo in endpoints_mobile:
        try:
            logger.info(f"   🔄 Intentando {nombre_endpoint}...")
            
            if tipo == "graphql":
                # GraphQL query
                payload = {
                    "query": """
                    mutation Login($email: String!, $password: String!) {
                        login(email: $email, password: $password) {
                            token
                            bearer
                            accessToken
                        }
                    }
                    """,
                    "variables": {
                        "email": email_usuario,
                        "password": password
                    }
                }
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "Liverpool-Mobile/2.0",
                }
            else:
                # REST API
                payload = {
                    "email": email_usuario,
                    "password": password,
                    "device_id": "megazord_v54",
                    "client_id": "mobile_app"
                }
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "Liverpool-Mobile/2.0 (Android)",
                }
            
            response = session.post(url, json=payload, headers=headers, timeout=15)
            
            logger.info(f"   📊 Status: {response.status_code}")
            
            if response.status_code in [200, 201]:
                data = response.json()
                logger.info(f"   ✓ Response keys: {list(data.keys())}")
                
                # Buscar token en diferentes campos posibles
                token_campos = ["token", "bearer", "accessToken", "access_token", 
                               "authorization", "auth_token", "jwt"]
                
                for campo in token_campos:
                    if campo in data:
                        token = data[campo]
                        if token and len(str(token)) > 20:
                            logger.info(f"   🔑 ✅ TOKEN ENCONTRADO en '{campo}'")
                            return token
                    
                    # Buscar en nested objects
                    if "data" in data and isinstance(data["data"], dict):
                        if campo in data["data"]:
                            token = data["data"][campo]
                            if token and len(str(token)) > 20:
                                logger.info(f"   🔑 ✅ TOKEN ENCONTRADO en data.{campo}")
                                return token
                
                logger.warning(f"   ⚠️ Response OK pero token no encontrado en campos esperados")
                logger.debug(f"   Full response: {data}")
            
            else:
                logger.warning(f"   ❌ {nombre_endpoint} devolvió {response.status_code}")
        
        except Exception as e:
            logger.warning(f"   ⚠️ Error en {nombre_endpoint}: {e}")
            continue
    
    logger.error(f"❌ RUTA 2 FALLIDA: No se pudo obtener token via Mobile API")
    return None

# ==========================================
# 🔄 FUNCIÓN RENOVAR TOKEN VIA REFRESH TOKEN (OPCIÓN 2 - FALLBACK)
# ==========================================
def renovar_token_con_refresh_token(refresh_token_guardado, logger, gc_client=None, timeout_2fa=180):
    """
    🔄 Intentar renovar token via refresh_token
    
    SI FUNCIONA: Retorna nuevo token + refresh_token
    SI FALLA POR MFA: Retorna error pero permite continuar
    SI REFRESH EXPIRÓ: Requiere intervención manual
    """
    
    logger.info(f"🔄 Intentando renovar token con refresh_token...")
    
    url = "https://login-entradaunica.liverpool.com.mx/oauth/token"
    
    payload = {
        "client_id": "vX4c873p5H4hWLBiLAFYqT9K491fLbTm",
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_guardado,
        "scope": "openid profile email offline_access"
    }
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    
    try:
        session = crear_session_con_retry()
        response = session.post(url, json=payload, headers=headers, timeout=15)
        
        logger.info(f"   📊 Status: {response.status_code}")
        
        # ✅ ÉXITO: Token renovado
        if response.status_code == 200:
            data = response.json()
            
            if "access_token" in data:
                nuevo_token = data["access_token"]
                nuevo_refresh = data.get("refresh_token", refresh_token_guardado)
                expires_in = data.get("expires_in", 86400)
                
                logger.info(f"   ✅ TOKEN RENOVADO EXITOSAMENTE")
                logger.info(f"   ⏰ Expira en: {expires_in} segundos ({expires_in/3600:.1f} horas)")
                
                return {
                    "access_token": nuevo_token,
                    "refresh_token": nuevo_refresh,
                    "expires_in": expires_in,
                    "success": True,
                    "error_type": None
                }
            else:
                logger.error(f"   ❌ Token no en response")
                return {
                    "success": False, 
                    "error": "Token not in response",
                    "error_type": "response_malformed",
                    "can_continue": False
                }
        
        # 🔴 MFA REQUERIDA - No podemos resolver
        elif response.status_code == 403:
            data = response.json()
            
            logger.error(f"   📋 RESPUESTA 403:")
            logger.error(f"   Error: {data.get('error')}")
            logger.error(f"   Descripción: {data.get('error_description')}")
            
            if data.get("error") == "mfa_required":
                logger.warning(f"   ⚠️ MFA REQUERIDA - No se puede renovar automáticamente")
                logger.warning(f"   💡 Soluciones:")
                logger.warning(f"      1. Desactiva MFA en marketplace.liverpool.com.mx")
                logger.warning(f"      2. O captura token manualmente cada 29 días")
                
                return {
                    "success": False,
                    "error": "MFA required - grant_type not allowed",
                    "error_type": "mfa_required",
                    "can_continue": True  # ← PERMITE CONTINUAR CON TOKEN VIEJO
                }
            
            elif data.get("error") == "unauthorized_client":
                logger.error(f"   ❌ Grant type 'mfa-otp' no permitido para este cliente")
                
                return {
                    "success": False,
                    "error": "MFA grant_type not allowed",
                    "error_type": "mfa_required",
                    "can_continue": True  # ← PERMITE CONTINUAR
                }
            
            else:
                logger.error(f"   ❌ Error 403 desconocido: {data.get('error')}")
                return {
                    "success": False,
                    "error": f"403: {data.get('error')}",
                    "error_type": "unknown_403",
                    "can_continue": False
                }
        
        # 🔴 REFRESH TOKEN EXPIRÓ
        elif response.status_code == 401:
            token_valido = False  # ← AQUÍ estaba el problema
            data = response.json()
            logger.error(f"   ❌ Refresh token expirado o inválido (401)")
            logger.error(f"   Error: {data.get('error')}")
            
            return {
                "success": False,
                "error": "Refresh token expired",
                "error_type": "refresh_token_expired",
                "can_continue": False  # ← NO PERMITE CONTINUAR
            }
        
        # 🔴 OTROS ERRORES
        else:
            logger.error(f"   ❌ Error {response.status_code}: {response.text}")
            return {
                "success": False,
                "error": f"Status {response.status_code}",
                "error_type": "http_error",
                "can_continue": False
            }
    
    except Exception as e:
        logger.error(f"   ❌ Exception: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": "exception",
            "can_continue": False
        }


# ==========================================
# 🔐 FUNCIÓN LOGIN AUTH0 DIRECTO (Para primer login)
# ==========================================
def intentar_login_auth0_directo_completo(email_usuario, password, logger):
    """
    🔐 RUTA 3: Authorization Code Flow completo de Auth0
    Solo se usa UNA VEZ cuando falla Playwright
    
    NOTA: Esta es una función stub. El flujo real requiere:
    1. Obtener authorization_code de Auth0
    2. Intercambiar por access_token + refresh_token
    
    Por ahora, retorna None indicando que necesita setup manual.
    """
    
    logger.info(f"🔐 RUTA 3: Intento de login Auth0 directo...")
    logger.error(f"   ⚠️ Esta ruta requiere flujo MANUAL en navegador")
    logger.error(f"   ⚠️ No puede automatizarse sin capturar authorization_code")
    logger.error(f"❌ RUTA 3: Requiere manual setup - ver documentación")
    
    return None

# ==========================================
# 🕵️‍♂️ FUNCIÓN RENOVACIÓN DE CREDENCIALES - V5.4 DATADOME PRESERVATION + WARM-UP
# ==========================================
def renovar_credenciales_postgresql(db, gc_client, id_cuenta, email_usuario, cookie_encriptada_actual):
    """
    🛡️ V5.4 - DATADOME COOKIE PRESERVATION + WARM-UP
    
    NIVEL 1: Intento eficiente (cookies + múltiples URLs)
    NIVEL 2: Fallback robusto (Warm-up público -> Logout -> Re-Warm-up -> Login fresco + 2FA)
    """
    logger.info(f"🤖 [{id_cuenta}] V5.4 DATADOME PRESERVATION iniciando...")
    token_atrapado = None
    p = None
    browser = None
    page = None
    context = None
    cipher = obtener_cipher()
    
    nivel_ejecutado = None
    tiempo_inicio = time.time()

    try:
        p = sync_playwright().start()
        
        # ==========================================
        # CONFIGURACIÓN BASE
        # ==========================================
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=TranslateUI',
                '--disable-component-update',
                '--disable-sync',
                '--metrics-recording-only',
            ]
        )
        
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            locale='es-MX',
            timezone_id='America/Mexico_City',
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'es-MX,es;q=0.9,en-US;q=0.8,en;q=0.7',
                'Cache-Control': 'max-age=0',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
            }
        )
        
        page = context.new_page()
        
        # ==========================================
        # STEALTH SCRIPTS
        # ==========================================
        script_basic_stealth = """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'chromeFlags', { get: () => undefined });
        Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 10 });
        """
        
        script_permissions_api = """
        const originalQuery = navigator.permissions.query;
        navigator.permissions.query = (params) => {
            if (params.name === 'notifications') {
                return new Promise((resolve) => {
                    resolve({ state: Notification.permission });
                });
            }
            return originalQuery(params);
        };
        """
        
        script_plugins = """
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Plugin', description: 'Portable Document Format', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', description: '', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client Executable', description: '', filename: 'internal-nacl-plugin' },
            ],
        });
        """
        
        script_webgl = """
        const canvas = document.createElement('canvas');
        const webglContext = canvas.getContext('webgl');
        if (webglContext) {
            const extension = webglContext.getExtension('WEBGL_debug_renderer_info');
            if (extension) {
                const originalGetParameter = webglContext.getParameter.bind(webglContext);
                webglContext.getParameter = function(pname) {
                    if (pname === extension.UNMASKED_RENDERER_WEBGL) {
                        return 'Intel(R) UHD Graphics 630';
                    }
                    if (pname === extension.UNMASKED_VENDOR_WEBGL) {
                        return 'Intel Inc.';
                    }
                    return originalGetParameter(pname);
                };
            }
        }
        """
        
        script_canvas = """
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            if (this.width < 300 && this.height < 300) {
                return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';
            }
            return originalToDataURL.call(this, type);
        };
        """
        
        script_languages = """
        Object.defineProperty(navigator, 'languages', {
            get: () => ['es-MX', 'es', 'en-US', 'en'],
        });
        Object.defineProperty(navigator, 'language', { get: () => 'es-MX' });
        """
        
        script_chrome_api = """
        if (!window.chrome) { window.chrome = {}; }
        window.chrome.runtime = { getManifest: () => null, id: 'extension-id-here' };
        const originalSendMessage = window.chrome.runtime.sendMessage;
        window.chrome.runtime.sendMessage = function(msg, callback) {
            if (typeof callback === 'function') { setTimeout(() => callback(), 0); }
            return true;
        };
        """
        
        scripts_list = [
            script_basic_stealth, script_permissions_api, script_plugins,
            script_webgl, script_canvas, script_languages, script_chrome_api
        ]
        
        for idx, script in enumerate(scripts_list):
            try:
                page.add_init_script(script)
            except Exception as e:
                logger.warning(f"⚠️ Error stealth script {idx+1}: {e}")
        
        try:
            from playwright_stealth import stealth_sync
            stealth_sync(page)
        except ImportError:
            logger.debug("ℹ️ playwright-stealth no disponible")
        
        # ==========================================
        # RASTREADOR DE NETWORK
        # ==========================================
        def rastrear_red(request):
            nonlocal token_atrapado
            if "pro-api.liverpool.com.mx" in request.url:
                auth = request.headers.get("authorization", "")
                if "Bearer " in auth and not token_atrapado:
                    token_atrapado = auth.replace("Bearer ", "")
                    logger.info(f"🔑 Token capturado en: {request.method} {request.url}")

        page.on("request", rastrear_red)
        
        # ==========================================
        # NIVEL 1: INTENTO EFICIENTE (Cookies + Múltiples URLs)
        # ==========================================
        logger.info(f"📍 [{id_cuenta}] NIVEL 1: Intentando con cookies existentes...")
        nivel_ejecutado = "NIVEL_1_COOKIES"
        
        cookies_inyectadas = False
        if cookie_encriptada_actual and cookie_encriptada_actual != "NaN":
            try:
                if cipher: 
                    cookies_data = json.loads(cipher.decrypt(cookie_encriptada_actual.encode()).decode())
                else: 
                    cookies_data = json.loads(cookie_encriptada_actual)
                context.add_cookies(cookies_data)
                cookies_inyectadas = True
                logger.info(f"🍪 {len(cookies_data)} cookies inyectadas")
            except Exception as e:
                logger.warning(f"⚠️ Error inyectando cookies: {e}")
                cookies_inyectadas = False

        if cookies_inyectadas:
            urls_nivel1 = [
                ("dashboard (raíz)", "https://marketplace.liverpool.com.mx/dashboard"),
                ("dashboard/orders", "https://marketplace.liverpool.com.mx/dashboard/orders"),
                ("dashboard/inventory", "https://marketplace.liverpool.com.mx/dashboard/inventory"),
            ]
            
            for nombre_url, url in urls_nivel1:
                logger.info(f"🌐 NIVEL 1.{urls_nivel1.index((nombre_url, url))+1}: Navegando a {nombre_url}...")
                
                try:
                    page.goto(url, wait_until="networkidle", timeout=15000)
                    
                    logger.info(f"⏳ Esperando 8s a que React dispare API...")
                    tiempo_inicio_intento = time.time()
                    while (time.time() - tiempo_inicio_intento) < 8:
                        if token_atrapado:
                            logger.info(f"✅ NIVEL 1 EXITOSO en {nombre_url}")
                            cookies_json = json.dumps(context.cookies())
                            cookie_final = cipher.encrypt(cookies_json.encode()).decode() if cipher else cookies_json
                            try:
                                with psycopg2.connect(DATABASE_URL) as conn:
                                    with conn.cursor() as cursor:
                                        cursor.execute("""
                                            UPDATE cuentas_liverpool 
                                            SET token_autorizacion=%s, cookie_vip=%s, timestamp_token=NOW()
                                            WHERE id_cuenta=%s
                                        """, (token_atrapado, cookie_final, id_cuenta))
                                logger.info(f"💾 Token guardado en BD")
                            except Exception as e:
                                logger.error(f"❌ Error guardando token: {e}")
                            
                            return token_atrapado, cookie_final
                        
                        time.sleep(0.5)
                    
                    if nombre_url == urls_nivel1[0][0]:
                        logger.info(f"↕️ Intentando scroll para lazy-load...")
                        page.evaluate("window.scrollBy(0, 500)")
                        page.wait_for_timeout(3000)
                        if token_atrapado:
                            logger.info(f"✅ NIVEL 1 EXITOSO (post-scroll)")
                            cookies_json = json.dumps(context.cookies())
                            cookie_final = cipher.encrypt(cookies_json.encode()).decode() if cipher else cookies_json
                            try:
                                with psycopg2.connect(DATABASE_URL) as conn:
                                    with conn.cursor() as cursor:
                                        cursor.execute("""
                                            UPDATE cuentas_liverpool 
                                            SET token_autorizacion=%s, cookie_vip=%s, timestamp_token=NOW()
                                            WHERE id_cuenta=%s
                                        """, (token_atrapado, cookie_final, id_cuenta))
                            except Exception as e:
                                logger.error(f"❌ Error guardando token: {e}")
                            return token_atrapado, cookie_final
                    
                except Exception as e:
                    logger.warning(f"⚠️ Error en {nombre_url}: {e}")
                    continue
            
            logger.warning(f"⚠️ NIVEL 1 FALLIDO en todas las URLs, escalando a NIVEL 2...")

        # ==========================================
        # NIVEL 2: FALLBACK ROBUSTO (Logout sin destruir Datadome + WARM-UP)
        # ==========================================
        logger.info(f"📍 [{id_cuenta}] NIVEL 2: Ejecutando fallback...")
        nivel_ejecutado = "NIVEL_2_FALLBACK_LOGOUT_PRESERVE_DATADOME"
        
        # ✅ PASO 0: WARM-UP (Obtener clearance de Datadome ANTES de logout)
        logger.info(f"🔥 Paso 0/6: WARM-UP - Calentando Datadome...")
        calentar_datadome(page, context, logger)
        
        # ✅ CLAVE V5.4 REVISADA: Extraer cookies de Datadome DESPUÉS del warm-up
        todas_cookies = context.cookies()
        cookies_datadome = [
            cookie for cookie in todas_cookies 
            if any(x in cookie.get('name', '').lower() for x in ['datadome', 'cf_clearance', 'cf_bm', '__cf'])
        ]
        
        logger.info(f"🔐 Después de warm-up, preservando {len(cookies_datadome)} cookies de seguridad:")
        for c in cookies_datadome:
            logger.info(f"   - {c['name']} (expira: {c.get('expires', 'session')})")
        
        # Si aún NO tenemos clearance después del warm-up, es un problema grave
        if len(cookies_datadome) == 0:
            logger.error(f"❌ NIVEL 2 CRÍTICO: Datadome NO emitió clearance después de warm-up")
            logger.warning(f"   Intentando sin clearance (probable fallo)...")
        
        # Paso 1: Logout en servidor (limpia sesión Liverpool)
        logger.info(f"🔓 Paso 1/6: Logout en servidor (preservando Datadome)...")
        try:
            page.goto("https://marketplace.liverpool.com.mx/logout", wait_until="domcontentloaded", timeout=10000)
            page.wait_for_timeout(2000)
            logger.info(f"✅ Logout ejecutado")
        except Exception as e:
            logger.warning(f"⚠️ Logout falló: {e}")
        
        # Paso 2: Re-calentar Datadome DESPUÉS del logout (por si acaso se invalidó)
        logger.info(f"🔥 Paso 2/6: Re-calentamiento post-logout...")
        calentar_datadome(page, context, logger)
        
        # Paso 3: Navegar a login (cookies Datadome aún en contexto)
        logger.info(f"🌐 Paso 3/6: Navegando a login...")
        try:
            page.goto("https://marketplace.liverpool.com.mx/", wait_until="domcontentloaded", timeout=15000)
            logger.info(f"✅ Login page cargada")
        except Exception as e:
            logger.error(f"❌ NIVEL 2 FALLÓ: Error navegando a login: {e}")
            page.screenshot(path="debug_nivel2_v5_4_login_nav.png")
            return None, None
        
        # Paso 4: Ingresando credenciales
        logger.info(f"⌨️ Paso 4/6: Ingresando credenciales...")
        
        email_field = None
        for selector in ['input#username', 'input[name="username"]', 'input[name="email"]', 'input[type="email"]']:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=5000):
                    email_field = locator
                    break
            except: 
                pass
        
        if not email_field:
            logger.error(f"❌ NIVEL 2: No se encontró campo email - ACTIVANDO DIAGNÓSTICO")
            
            # RUTA 1: Diagnosticar qué pasó
            tipo_problema, indicios = diagnosticar_white_screen(page, logger)
            logger.error(f"   📋 Tipo de problema: {tipo_problema}")
            logger.error(f"   📋 Indicios: {indicios}")
            
            # Captura screenshot para análisis
            page.screenshot(path="debug_nivel2_v5_4_email.png")
            logger.error(f"   📸 Screenshot guardado: debug_nivel2_v5_4_email.png")
            
            # RUTA 2: Intentar Mobile API como fallback
            logger.error(f"❌ NIVEL 2 WEB FALLIDO ({tipo_problema}) - Escalando a RUTA 2 (Mobile API)")
            
            token_mobile = intentar_login_mobile_api(email_usuario, os.getenv("LIVERPOOL_PASS"), logger)
            
            if token_mobile:
                logger.info(f"✅ ¡TOKEN OBTENIDO VIA RUTA 2 (MOBILE API)!")
                
                # Guardar en BD con la cookie que tenemos
                cookies_json = json.dumps(context.cookies())
                cookie_final = cipher.encrypt(cookies_json.encode()).decode() if cipher else cookies_json
                
                try:
                    with psycopg2.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cursor:
                            # Calcular cuándo expira el token (por si lo tienes)
                            token_expira_en = datetime.now() + timedelta(seconds=expires_in)

                            cursor.execute("""
                                UPDATE cuentas_liverpool 
                                SET token_autorizacion=%s, 
                                    cookie_vip=%s, 
                                    timestamp_token=NOW(),
                                    refresh_token=%s,
                                    token_expira_en=%s
                                WHERE id_cuenta=%s
                            """, (token_mobile, cookie_final, None, token_expira_en, id_cuenta))
                    logger.info(f"💾 Token Mobile guardado en BD")
                except Exception as e:
                    logger.error(f"❌ Error guardando token: {e}")
                
                return token_mobile, cookie_final
            
            else:
                logger.error(f"❌ RUTA 2 TAMBIÉN FALLÓ - NIVEL 2 COMPLETAMENTE FALLIDO")
                return None, None
        
        try:
            email_field.scroll_into_view_if_needed()
            email_field.click(force=True, delay=100)
            email_field.type(email_usuario, delay=random.randint(100, 200))
            logger.info(f"✅ Email ingresado")
        except Exception as e:
            logger.error(f"❌ Error ingresando email: {e}")
            page.screenshot(path="debug_nivel2_v5_4_email.png")
            return None, None
        
        password_field = None
        for selector in ['input#password', 'input[name="password"]', 'input[type="password"]']:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=5000):
                    password_field = locator
                    break
            except: 
                pass
        
        if not password_field:
            logger.error(f"❌ NIVEL 2 FALLÓ: No se encontró campo password")
            page.screenshot(path="debug_nivel2_v5_4_password.png")
            return None, None
        
        try:
            password_field.scroll_into_view_if_needed()
            password_field.click(force=True, delay=100)
            password = os.getenv("LIVERPOOL_PASS")
            if not password:
                logger.error("❌ LIVERPOOL_PASS no configurada")
                return None, None
            password_field.type(password, delay=random.randint(100, 200))
            logger.info(f"✅ Password ingresado")
        except Exception as e:
            logger.error(f"❌ Error ingresando password: {e}")
            page.screenshot(path="debug_nivel2_v5_4_password.png")
            return None, None
        
        try:
            submit_button = page.locator('button[type="submit"]').first
            if not submit_button or not submit_button.is_visible(timeout=5000):
                logger.error(f"❌ NIVEL 2 FALLÓ: No se encontró botón submit")
                page.screenshot(path="debug_nivel2_v5_4_submit.png")
                return None, None
            
            submit_button.scroll_into_view_if_needed()
            submit_button.click(force=True, delay=100)
            logger.info(f"✅ Submit clickeado")
        except Exception as e:
            logger.error(f"❌ Error en submit: {e}")
            page.screenshot(path="debug_nivel2_v5_4_submit.png")
            return None, None
        
        page.wait_for_timeout(2000)
        
        # Paso 5: 2FA
        logger.info(f"📱 Paso 5/6: Interceptando código 2FA...")
        tiempo_inicio_2fa = time.time()
        timeout_total_2fa = 180
        
        try: 
            hoja_config = gc_client.open_by_key(os.getenv("GOOGLE_SHEET_ID")).worksheet("Config")
        except: 
            hoja_config = None

        codigo_antiguo = ""
        codigo_exitoso = False

        while (time.time() - tiempo_inicio_2fa) < timeout_total_2fa:
            codigo_nuevo = ""
            if hoja_config:
                try: 
                    codigo_nuevo = str(hoja_config.acell("B1").value).replace("'", "").strip()
                except: 
                    pass
            
            tiempo_transcurrido = int(time.time() - tiempo_inicio_2fa)
            
            if codigo_nuevo != codigo_antiguo and len(codigo_nuevo) == 6 and codigo_nuevo.isdigit():
                logger.info(f"✅ Código detectado: {codigo_nuevo}")
                codigo_antiguo = codigo_nuevo
                
                try:
                    codigo_input = None
                    for selector in ['input[name="code"]', 'input[name="otp"]', 'input[maxlength="6"]']:
                        try:
                            locator = page.locator(selector).first
                            if locator.is_visible(timeout=5000):
                                codigo_input = locator
                                break
                        except: 
                            pass
                    
                    if not codigo_input: 
                        continue
                    
                    codigo_input.scroll_into_view_if_needed()
                    codigo_input.click(force=True)
                    codigo_input.clear()
                    codigo_input.type(codigo_nuevo, delay=random.randint(150, 250))
                    page.wait_for_timeout(800)
                    
                    continuar_button = page.locator('button:has-text("Continuar")').first
                    if continuar_button and continuar_button.is_visible():
                        continuar_button.click(force=True)
                    
                    tiempo_espera_token = time.time()
                    while (time.time() - tiempo_espera_token) < 60:
                        time.sleep(1)
                        if token_atrapado:
                            logger.info(f"🔑 Token capturado en POST de 2FA")
                            codigo_exitoso = True
                            break
                    
                    if codigo_exitoso: 
                        break
                    
                except Exception as e:
                    logger.error(f"❌ Error inyectando código 2FA: {e}")
                    page.screenshot(path="debug_nivel2_v5_4_2fa.png")
            
            time.sleep(5)
        
        if not codigo_exitoso:
            logger.error(f"❌ NIVEL 2 FALLÓ: Timeout 2FA")
            page.screenshot(path="debug_nivel2_v5_4_timeout.png")
            return None, None
        
        # Paso 6: Guardar en BD
        logger.info(f"💾 Paso 6/6: Guardando token en BD...")
        if token_atrapado:
            cookies_json = json.dumps(context.cookies())
            cookie_final = cipher.encrypt(cookies_json.encode()).decode() if cipher else cookies_json
            
            try:
                with psycopg2.connect(DATABASE_URL) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            UPDATE cuentas_liverpool 
                            SET token_autorizacion=%s, cookie_vip=%s, timestamp_token=NOW()
                            WHERE id_cuenta=%s
                        """, (token_atrapado, cookie_final, id_cuenta))
                logger.info(f"✅ NIVEL 2 EXITOSO: Token guardado en BD")
            except Exception as e:
                logger.error(f"❌ Error guardando token: {e}")

            return token_atrapado, cookie_final
        else:
            logger.error(f"❌ NIVEL 2 FALLÓ: Token no capturado")
            return None, None

    except Exception as e:
        logger.error(f"❌ Fallo crítico: {e}")
        import traceback
        traceback.print_exc()
        return None, None
        
    finally:
        tiempo_total = time.time() - tiempo_inicio
        logger.info(f"🧹 Cleanup... (Total: {tiempo_total:.1f}s, Nivel: {nivel_ejecutado})")
        
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
        import gc
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

def obtener_info_rivales_nuevo_endpoint(liverpool_sku):
    """Nuevo endpoint: www.liverpool.com.mx/tienda/mirakl/offerListing"""
    try:
        url = f"https://www.liverpool.com.mx/tienda/mirakl/offerListing?productId={liverpool_sku}&skuId={liverpool_sku}"
        res = crear_session_con_retry().get(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, 
            timeout=30
        )
        if res.status_code == 200:
            rivales = []
            # Ajusta el parsing según la estructura que vimos en el JSON
            ofertas = res.json().get("offers", []) or res.json().get("sellersOfferDetails", [])
            
            for oferta in ofertas:
                seller_id = str(oferta.get("sellerId") or oferta.get("seller", {}).get("id", ""))
                if seller_id != str(SHOP_ID_PUBLICO):
                    # Intentar múltiples campos de precio
                    precio = (
                        oferta.get("price") or 
                        oferta.get("promoPrice") or 
                        oferta.get("salePrice") or
                        oferta.get("currentPrice") or
                        0
                    )
                    
                    try:
                        precio_float = float(precio) if precio else 0.0
                        if precio_float > 0:
                            rivales.append({
                                "precio": precio_float,
                                "nombre": str(oferta.get("sellerName") or oferta.get("seller", {}).get("name", "Desconocido")),
                                "source": "NUEVO"  # FLAG para tracking
                            })
                    except (ValueError, TypeError):
                        pass
            
            return sorted(rivales, key=lambda x: x["precio"]) if rivales else None
    except Exception as e:
        logger.warning(f"❌ NUEVO ENDPOINT ERROR: {type(e).__name__}: {e}")
        import traceback
        logger.debug(traceback.format_exc())
    return None


def obtener_info_rivales_viejo_endpoint(liverpool_sku):
    """Viejo endpoint: shoppapp.liverpool.com.mx (fallback)"""
    try:
        url = f"https://shoppapp.liverpool.com.mx/appclienteservices/services/v2/marketplace/pdp/getSellersOfferDetailsPdp?skuId={liverpool_sku}"
        res = crear_session_con_retry().get(
            url, 
            headers={"User-Agent": "Liverpool/2.2.0"}, 
            timeout=30
        )
        if res.status_code == 200:
            rivales = []
            for v in res.json().get("sellersOfferDetails", []):
                if str(v.get("sellerId")) != str(SHOP_ID_PUBLICO):
                    precio_raw = v.get("promoPrice") or v.get("salePrice")
                    try:
                        precio = float(precio_raw) if precio_raw else 0.0
                        if precio > 0:
                            rivales.append({
                                "precio": precio,
                                "nombre": str(v.get("sellerName", "Desconocido")),
                                "source": "VIEJO"  # FLAG para tracking
                            })
                    except (ValueError, TypeError):
                        pass
            
            return sorted(rivales, key=lambda x: x["precio"]) if rivales else None
    except Exception as e:
        logger.debug(f"❌ Viejo endpoint falló: {e}")
    return None


def comparar_rivales(nuevos, viejos):
    """Detecta discrepancias entre endpoints."""
    if not nuevos or not viejos:
        return False  # No hay discrepancia si uno está vacío
    
    if len(nuevos) != len(viejos):
        return True  # Diferente cantidad de rivales = discrepancia
    
    # Comparar precios del rival #1
    precio_nuevo = nuevos[0]["precio"]
    precio_viejo = viejos[0]["precio"]
    
    discrepancia = abs(precio_nuevo - precio_viejo) > 0.01  # Mayor a 1 centavo
    
    if discrepancia:
        logger.warning(
            f"⚠️ DISCREPANCIA DETECTADA - Rival #1: "
            f"Nuevo=${precio_nuevo} vs Viejo=${precio_viejo} | "
            f"Diferencia: ${abs(precio_nuevo - precio_viejo):.2f}"
        )
    
    return discrepancia


def obtener_info_rivales(liverpool_sku):
    """
    🔄 HYBRID DUAL-ENDPOINT
    
    Intenta obtener datos de AMBOS endpoints en paralelo.
    Prefiere datos nuevos, usa viejo como fallback.
    Detecta discrepancias para auditoría.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # PASO 1: Llamar ambos endpoints en paralelo
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_nuevo = executor.submit(obtener_info_rivales_nuevo_endpoint, liverpool_sku)
        future_viejo = executor.submit(obtener_info_rivales_viejo_endpoint, liverpool_sku)
        
        nuevos = future_nuevo.result(timeout=35)
        viejos = future_viejo.result(timeout=35)
    
    # PASO 2: Decidir qué datos usar
    if nuevos:
        # Nuevo endpoint tiene prioridad (es más fresco)
        datos_confiables = nuevos
        source = "NUEVO"
    elif viejos:
        # Fallback al viejo si el nuevo falló
        datos_confiables = viejos
        source = "VIEJO (FALLBACK)"
        logger.warning(f"⚠️ Usando viejo endpoint como fallback para {liverpool_sku}")
    else:
        # Ambos fallaron
        logger.error(f"❌ AMBOS endpoints fallaron para {liverpool_sku}")
        return []
    
    # PASO 3: Detectar discrepancias (si ambos devolvieron datos)
    if nuevos and viejos:
        hay_discrepancia = comparar_rivales(nuevos, viejos)
        if hay_discrepancia:
            logger.info(
                f"📊 Usando datos NUEVOS (más confiables). "
                f"Descarte: viejo endpoint detectado stale."
            )
    
    return datos_confiables

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

    # 🛡️ ALTO #2: Race Condition parchado con método thread-safe
    def obtener_precio_conocido(self, sku, default):
        with self._lock:
            return self.ultimo_precio_conocido.get(sku, default)

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
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "shopid": SHOP_ID_INTERNO}
    payload = [{
        "basePrice": float(base_price),
        "offerId": int(offer_id),
        "quantity": int(stock),
        "offerPriceManagement": [{"discountPrice": float(nuevo_precio), "updatedAt": datetime.now(timezone.utc).isoformat(), "userModified": "MEGAZORD_API", "index": 0}]
    }]
    try:
        if MODO_SIMULACION:
            imprimir_simulacion(f"DISPARAR_PRECIO | SKU: {sku_notificacion} | Bajaría a: ${nuevo_precio}")
            return True
        liverpool_rate_limiter.wait()
        response = crear_session_con_retry().put(url, headers=headers, json=payload, timeout=30)
        if response.status_code in [200, 204]:
            logger.info(f"✅ Ajuste ejecutado: {enmascarar_precio(nuevo_precio)}")
            return True
        else: return False
    except: return False

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
            resultados.agregar_historial([(datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"), str(sku_i), str(sku_lp), "Oculto/Agotado", 0, 0, "N/A", "N/A", id_cuenta])
            return

        # 🛡️ ALTO #4: JSON Parsing quantity parchado
        cantidad = int(prod.get("quantity") or 0)
        offer_id = prod.get("offerId")
        base_price = float(prod.get("basePrice", 0))
        precio_actual = float(prod.get("discountPrice") or base_price)
        nuevo_precio = precio_actual

        if cantidad == 0:
            resultados.agregar_historial([(datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"), str(sku_i), str(sku_lp), "Agotado", precio_actual, 0, "N/A", "N/A", id_cuenta])
            if estatus_regla == 'ACTIVO': resultados.apagar_sku_liverpool(fila_excel, sku_i)
            return

        info_rivales = obtener_info_rivales(sku_lp)
        precios_rivales = [r["precio"] for r in info_rivales]

        precio_minimo_regla = safe_float(regla.get('precio_minimo', 0))
        precio_maximo_regla = safe_float(regla.get('precio_maximo', base_price) or base_price)
        costo_odoo_sheet = safe_float(regla.get('costo_odoo', 0))

        sku_display = enmascarar_sku(sku_lp)
        logger.info(f"🔍 [{id_cuenta}] Escaneando {sku_display} | BB: {enmascarar_vendedor(info_rivales[0]['nombre'] if info_rivales else 'N/A')}")

        hora_actual_str = (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        
        catalogo_id = regla.get('id')
        if catalogo_id:
            for idx, r in enumerate(info_rivales[:5]): resultados.agregar_archivo_negro((catalogo_id, 'LIVERPOOL', r["nombre"], r["precio"], idx + 1))

        if precios_rivales:
            rival_mas_bajo = precios_rivales[0]
            precio_viejo = resultados.obtener_precio_conocido(sku_i, rival_mas_bajo)
            if (precio_viejo - rival_mas_bajo) >= 100:
                resultados.agregar_alerta(f"🚨 *ALERTA ANTI-DUMPING ({id_cuenta})*\nEl vendedor _{info_rivales[0]['nombre']}_ desplomó el mercado en *{sku_i}*.\n📉 Anterior: `${precio_viejo}` | 🩸 Nuevo: `${rival_mas_bajo}`")

        # ================= LÓGICA DE REGLAS =================
        if estatus_regla == 'INACTIVO':
            if info_rivales:
                estado_precio = "✅ TIENES MARGEN!" if precio_minimo_regla > 0 and info_rivales[0]["precio"] >= precio_minimo_regla else "❌ RIVAL REMATANDO."
                msg = f"🕵️ *RADAR ESPÍA ({id_cuenta})*\n📦 *{sku_i}*\n👑 *BuyBox:* `${info_rivales[0]['precio']}`\n📊 {estado_precio}\n🛡️ Mínimo: `${precio_minimo_regla}`"
                if costo_odoo_sheet > 0:
                    gan, mar = calcular_rentabilidad(info_rivales[0]["precio"], costo_odoo_sheet)
                    msg += f"\n💡 *Para igualar:* Ganancia: `${gan:.2f}` (Margen: `{mar:.1f}%`)"
                resultados.agregar_alerta(msg)
            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", precio_actual, cantidad, "Inactivo", "Inactivo", id_cuenta])
            return

        if estatus_regla == 'ACTIVO':
            if tipo_regla.startswith('2'):
                nuevo_precio = precio_minimo_regla
                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                if float(precio_actual) != float(nuevo_precio) and disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                    resultados.agregar_alerta(f"📌 *LÍMITE MÍNIMO ACTIVADO ({id_cuenta})*\n\n📦 *{sku_i}*\nPrecio fijado en mínimo: `${nuevo_precio}`")
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", nuevo_precio, cantidad, pos, bb, id_cuenta])
                else:
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", precio_actual, cantidad, pos, bb, id_cuenta])

            elif tipo_regla.startswith('3'):
                nuevo_precio = precio_maximo_regla
                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                if float(precio_actual) != float(nuevo_precio) and disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", nuevo_precio, cantidad, pos, bb, id_cuenta])
                else:
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, precios_rivales[0] if precios_rivales else "SIN RIVAL", precio_actual, cantidad, pos, bb, id_cuenta])

            elif tipo_regla.startswith('9'):
                if precios_rivales:
                    rival_mas_bajo = precios_rivales[0]
                    if rival_mas_bajo >= precio_minimo_regla:
                        nuevo_precio_propuesto = round(rival_mas_bajo - round(random.uniform(1.50, 1.95), 2), 2)
                        if nuevo_precio_propuesto >= precio_actual:
                            if random.randint(1, 9) == 1:
                                nuevo_precio = round(precio_actual - 1.50, 2)
                                # 🛡️ CRÍTICO #3: Evitar precio negativo en Ruleta Rusa
                                if nuevo_precio <= 0: nuevo_precio = precio_minimo_regla
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
                            nuevo_precio = round(float(int(rivales_viables[0]) - 1) + 0.09, 2)
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
                    if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo if precios_rivales else "SIN RIVAL", nuevo_precio, cantidad, pos, f"{bb} | {motivo}", id_cuenta])
                else:
                    pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                    if motivo == "🛑 Alerta Roja (Perdida BB)":
                        gan_roja, mar_roja = calcular_rentabilidad(rival_mas_bajo, costo_odoo_sheet)
                        resultados.agregar_alerta(f"🛑 *ALERTA ROJA: Has perdido la BuyBox ({id_cuenta})*\n\n📦 *{sku_i}*\n👑 Ganador actual: *{info_rivales[0]['nombre']}*\n💰 Precio de la BuyBox: `${rival_mas_bajo}`\n🥶 Congelado en `${precio_actual}` (Mínimo: `${precio_minimo_regla}`).\n💡 Para poder salir (igualando a `${rival_mas_bajo}`):\nGanancia: `${gan_roja:.2f}` | Margen: `{mar_roja:.1f}%`")
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo if precios_rivales else "SIN RIVAL", precio_actual, cantidad, pos, f"{bb} | {motivo}", id_cuenta])

            else:
                if precios_rivales:
                    rival_mas_bajo = precios_rivales[0]
                    
                    if tipo_regla.startswith('4') and rival_mas_bajo > precio_maximo_regla:
                        mejor_historico = resultados.max_precio_buybox_historico.get(sku_i, 0) if hasattr(resultados, 'max_precio_buybox_historico') else 0
                        # ESTAMOS GANANDO (Rival es más caro que nuestro techo). Nos pegamos a nuestro máximo exacto, sin .09
                        nuevo_precio = mejor_historico if mejor_historico > 0 else precio_maximo_regla
                        pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                        if float(precio_actual) != float(nuevo_precio) and disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, pos, bb, id_cuenta])
                        else:
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                    else:
                        diferencia_actual = round(float(rival_mas_bajo) - float(precio_actual), 2)
                        
                        # Si el rival está por encima del mínimo y ya estamos en el margen perfecto de Gladiador
                        if rival_mas_bajo >= precio_minimo_regla and 1.50 <= diferencia_actual <= 1.95:
                            pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                        else:
                            baja = round(random.uniform(1.50, 1.95), 2)
                            nuevo_precio_ataque = round(rival_mas_bajo - baja, 2)
                            
                            # 🛡️ PARCHE VISUAL: Evitar terminación .09 en ataques ganadores para no confundir con Modo Sombra
                            if str(format(nuevo_precio_ataque, '.2f')).endswith('.09'):
                                nuevo_precio_ataque = round(nuevo_precio_ataque - 0.01, 2)
                            
                            if nuevo_precio_ataque <= 0:
                                logger.error(f"❌ ALERTA MATEMÁTICA: Precio negativo calculado para {sku_i}")
                                return
                                
                            # Si el ataque es viable matemáticamente contra nuestro mínimo
                            if rival_mas_bajo >= precio_minimo_regla and nuevo_precio_ataque >= precio_minimo_regla:
                                nuevo_precio = nuevo_precio_ataque
                                if precio_maximo_regla > 0 and nuevo_precio > precio_maximo_regla: 
                                    # ESTAMOS GANANDO, pero el ataque se pasó de nuestro máximo. Nos limitamos al máximo exacto, sin .09
                                    nuevo_precio = precio_maximo_regla
                            else:
                                # 🦇 MODO SOMBRA (PERDIENDO LA BUYBOX): 
                                # Si no podemos vencer al #1, buscamos al SIGUIENTE competidor (#2)
                                rivales_superiores = [p for p in precios_rivales if p > rival_mas_bajo and p >= precio_minimo_regla]
                                
                                if rivales_superiores:
                                    # Nos pegamos al siguiente rival viable con firma .09
                                    nuevo_precio = round(float(int(rivales_superiores[0]) - 1) + 0.09, 2)
                                else:
                                    # Si no hay siguiente rival, huimos al techo con firma .09
                                    nuevo_precio = round(float(int(precio_maximo_regla) - 1) + 0.09, 2)
                                
                                # 🛡️ APLICAR TOPES ESTRATÉGICOS (MANTENIENDO EL .09)
                                if precio_maximo_regla > 0 and nuevo_precio > precio_maximo_regla: 
                                    nuevo_precio = round(float(int(precio_maximo_regla) - 1) + 0.09, 2)
                                
                                if nuevo_precio < precio_minimo_regla: 
                                    nuevo_precio = round(float(int(precio_minimo_regla)) + 0.09, 2)
                                    # Seguridad extrema por si el mínimo tenía decimales (ej. 741.99)
                                    if nuevo_precio < precio_minimo_regla:
                                        nuevo_precio = round(nuevo_precio + 1.00, 2)
                            
                            if float(precio_actual) != float(nuevo_precio):
                                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                                if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, pos, bb, id_cuenta])
                                else:
                                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                            else:
                                pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                                resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                else:
                    # 👑 ESTAMOS SOLOS (1 de 1). Nos quedamos en el máximo exacto, sin firma de .09
                    nuevo_precio = mejor_historico if (tipo_regla.startswith('4') and (mejor_historico := resultados.max_precio_buybox_historico.get(sku_i, 0)) > 0) else precio_maximo_regla
                    if float(precio_actual) != float(nuevo_precio) and disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, "SIN RIVAL", nuevo_precio, cantidad, "1 de 1", "¡Nosotros! 👑", id_cuenta])
                    else:
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, "SIN RIVAL", precio_actual, cantidad, "1 de 1", "¡Nosotros! 👑", id_cuenta])

    except Exception as e:
        logger.error(f"❌ Error en procesar_sku_threadsafe: {e}")

# ==========================================
# GUARDADO DE HISTORIAL SEGURO EN SQL
# ==========================================
def guardar_en_sql(filas):
    if MODO_SIMULACION: return
    if not filas: return
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                query = """INSERT INTO historial_precios (fecha_hora, sku_interno, sku_liverpool, precio_rival, nuestro_precio, stock, posicion, buybox, id_cuenta) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                cursor.executemany(query, filas)
    except Exception as e: logger.error(f"❌ CRÍTICO: Error guardando en BD: {e}")

# ==========================================
# 🚨 FUNCIÓN AUXILIAR - MANEJO DE RENOVACIÓN FALLIDA
# ==========================================
def manejar_renovacion_fallida(id_cuenta, error_tipo, logger):
    """
    Maneja las diferentes razones por las que falló la renovación de token
    
    error_tipo puede ser:
    - "mfa_required": MFA habilitada (no podemos resolver automáticamente)
    - "refresh_token_expired": refresh_token expiró (necesita login manual)
    - "other": Otro error
    """
    
    if "mfa" in error_tipo.lower():
        logger.warning(f"⚠️ MFA REQUERIDA - No se puede renovar automáticamente")
        mensaje = (
            f"⚠️ *ATENCIÓN: RENOVACIÓN DE TOKEN FALLIDA ({id_cuenta})*\n\n"
            f"*Motivo:* MFA habilitada en cuenta Liverpool\n\n"
            f"*Estado actual:* Token vigente por ~24 horas más\n\n"
            f"*Acción requerida en ~24h:*\n"
            f"1️⃣ Ve a https://marketplace.liverpool.com.mx/dashboard\n"
            f"2️⃣ Abre DevTools (F12) → Network\n"
            f"3️⃣ Busca request a `pro-api.liverpool.com.mx`\n"
            f"4️⃣ Copia el `Authorization: Bearer eyJ...`\n"
            f"5️⃣ Manda el token a @bot_megazord\n\n"
            f"*Solución permanente:*\n"
            f"Contacta al Admin de Liverpool para desactivar MFA"
        )
        enviar_alerta_telegram(mensaje)
        return True  # Continuar con token viejo
    
    elif "refresh_token_expired" in error_tipo:
        logger.error(f"❌ REFRESH TOKEN EXPIRADO - Login manual requerido AHORA")
        mensaje = (
            f"🚨 *CRÍTICO: REFRESH TOKEN EXPIRADO ({id_cuenta})*\n\n"
            f"*Estado:* No se puede renovar automáticamente\n\n"
            f"*Acción INMEDIATA:*\n"
            f"1️⃣ Ve a https://marketplace.liverpool.com.mx/dashboard\n"
            f"2️⃣ Haz login manualmente (si no está ya)\n"
            f"3️⃣ Abre DevTools (F12) → Network\n"
            f"4️⃣ Busca request a `pro-api.liverpool.com.mx`\n"
            f"5️⃣ Copia el `Authorization: Bearer eyJ...`\n"
            f"6️⃣ Manda el token URGENTE\n\n"
            f"*Bot está PAUSADO hasta recibir nuevo token*"
        )
        enviar_alerta_telegram(mensaje)
        return False  # NO continuar - token está muerto
    
    else:
        logger.error(f"❌ RENOVACIÓN FALLÓ (Motivo desconocido): {error_tipo}")
        return False


def token_aun_valido_por_intento(token_expira_en):
    """
    Verifica si el token tiene margen de validez para procesamiento
    Retorna True si faltan MÁS de 30 minutos
    """
    if not token_expira_en:
        return True  # Sin información, asumir que está bien
    
    try:
        tiempo_faltante = token_expira_en - datetime.now()
        minutos_faltantes = tiempo_faltante.total_seconds() / 60
        
        if minutos_faltantes > 30:
            return True
        else:
            return False
    except:
        return True

# ==========================================
# FUNCIÓN PRINCIPAL MULTI-TENANT
# ==========================================
def ejecutar_bot():
    logger.info("\n--- INICIANDO MEGAZORD LIVERPOOL V5.4 (DATADOME PRESERVATION) ---")
    
    try: db = DbManager()
    except: db = None

    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        gc_connection = gspread.authorize(creds)
    except: gc_connection = None

    # 🛡️ ALTO #1: Fuga de conexión parchada en el bloque inicial
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_cuenta, nombre_descriptivo, email_usuario, token_autorizacion, cookie_vip FROM cuentas_liverpool WHERE is_active = TRUE")
                cuentas_activas = cursor.fetchall()
                
                if not cuentas_activas:
                    logger.warning("⚠️ No hay cuentas activas en la Bóveda VIP.")
                    return
                
                # Extraemos de una vez todo el catálogo activo
                cursor.execute("SELECT id, sku_limpio, sku_interno, sku_liverpool, precio_minimo, precio_maximo, costo_odoo, regla_estrategia, estatus, id_cuenta FROM catalogo_maestro_v3 WHERE estatus = 'ACTIVO' AND sku_liverpool IS NOT NULL AND sku_liverpool != ''")
                columnas_cat = [desc[0] for desc in cursor.description]
                catalogo_completo = cursor.fetchall()
                
    except Exception as e:
        logger.error(f"❌ Error leyendo DB inicial: {e}")
        return

    resultados = ResultadosThreadSafe()
    sesion_compartida = crear_session_con_retry()
    total_skus_procesados = 0

    for cuenta in cuentas_activas:
        id_cuenta, nombre_desc, email_usuario, token_cuenta, cookie_vip = cuenta
        logger.info(f"\n==========================================")
        logger.info(f"🏪 CARGANDO MOTOR PARA: {nombre_desc} ({id_cuenta})")
        logger.info(f"==========================================")

        reglas_cuenta = {}
        for row in catalogo_completo:
            fila_dict = dict(zip(columnas_cat, row))
            if fila_dict['id_cuenta'] == id_cuenta:
                reglas_cuenta[fila_dict['sku_liverpool']] = fila_dict

        if not reglas_cuenta: continue

        sku_muestra = next(iter(reglas_cuenta.values()))['sku_interno']
        token_valido = True
            
        # ✅ PING INICIAL PARA VALIDAR TOKEN
        if not SHOP_ID_INTERNO:
            logger.warning(f"⚠️ SHOP_ID_INTERNO no configurado - saltando validación de token")
            token_valido = True  # Asumir que está bien
        else:
            url_ping = f"https://pro-api.liverpool.com.mx/api/offermanagement/offers?shop_id={SHOP_ID_INTERNO}&sku={urllib.parse.quote(sku_muestra)}"
            headers_ping = {"Authorization": f"Bearer {token_cuenta}", "Content-Type": "application/json"}
            
            try:
                response = crear_session_con_retry().get(url_ping, headers=headers_ping, timeout=10)
            except:
                response = None
            
            # ✅ VALIDAR RESPUESTA
            if not response or response.status_code == 401:
                token_valido = False
            else:
                token_valido = True
            
            # ✅ SI EL TOKEN NO ES VÁLIDO, INTENTAR RENOVAR
            if not token_valido:
                logger.warning(f"💀 El Ping devolvió 401. Token MUERTO.")
                logger.info(f"🔄 INTENTANDO RENOVAR TOKEN CON REFRESH TOKEN...")
                
                try:
                    with psycopg2.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cursor:
                            cursor.execute("""
                                SELECT refresh_token, token_expira_en 
                                FROM cuentas_liverpool 
                                WHERE id_cuenta = %s
                            """, (id_cuenta,))
                            resultado = cursor.fetchone()
                            
                            if resultado:
                                refresh_token_guardado, token_expira_en = resultado
                                
                                if refresh_token_guardado:
                                    logger.info(f"   ✓ Refresh token encontrado en BD")
                                    
                                    # INTENTAR RENOVACIÓN
                                    resultado_renovacion = renovar_token_con_refresh_token(
                                        refresh_token_guardado, 
                                        logger,
                                        gc_client=gc_connection,
                                        timeout_2fa=180
                                    )
                                    
                                    if resultado_renovacion["success"]:
                                        # ✅ RENOVACIÓN EXITOSA
                                        nuevo_token = resultado_renovacion["access_token"]
                                        nuevo_refresh = resultado_renovacion["refresh_token"]
                                        expires_in = resultado_renovacion["expires_in"]
                                        
                                        token_expira_en = datetime.now() + timedelta(seconds=expires_in)
                                        
                                        with psycopg2.connect(DATABASE_URL) as conn2:
                                            with conn2.cursor() as cursor2:
                                                cursor2.execute("""
                                                    UPDATE cuentas_liverpool 
                                                    SET token_autorizacion=%s, 
                                                        refresh_token=%s, 
                                                        timestamp_token=NOW(),
                                                        token_expira_en=%s
                                                    WHERE id_cuenta=%s
                                                """, (nuevo_token, nuevo_refresh, token_expira_en, id_cuenta))
                                        
                                        logger.info(f"✅ Token renovado y guardado en BD")
                                        token_cuenta = nuevo_token
                                        token_valido = True
                                    
                                    else:
                                        # ❌ RENOVACIÓN FALLÓ
                                        error_tipo = resultado_renovacion.get("error_type", "unknown")
                                        puede_continuar = resultado_renovacion.get("can_continue", False)
                                        
                                        logger.error(f"❌ Error renovando token: {resultado_renovacion.get('error')}")
                                        
                                        # Manejar el error
                                        debe_continuar = manejar_renovacion_fallida(
                                            id_cuenta, 
                                            error_tipo, 
                                            logger
                                        )
                                        
                                        if debe_continuar and token_aun_valido_por_intento(token_expira_en):
                                            # 🟡 FALLBACK: Continuar con token viejo
                                            logger.warning(f"🟡 [{id_cuenta}] Continuando con token antiguo (MFA bloqueando renovación)")
                                            token_valido = True  # Asumir que sigue siendo válido
                                        else:
                                            # 🔴 NO PODEMOS CONTINUAR
                                            logger.error(f"❌ No se pudo obtener token válido para {id_cuenta}. Saltando...")
                                            token_valido = False
                                
                                else:
                                    logger.error(f"❌ No hay refresh token guardado - necesitas login manual")
                                    token_valido = False
                            
                            else:
                                logger.error(f"❌ Cuenta no encontrada en BD")
                                token_valido = False
                
                except Exception as e:
                    logger.error(f"❌ Error renovando token: {e}")
                    token_valido = False
        
        # ✅ SECURITY CHECK: Token debe ser válido para procesar
        if not token_valido:
            logger.error(f"❌ No se pudo obtener token válido para {id_cuenta}. Saltando...")
            continue
            
        total_skus_procesados += len(reglas_cuenta)
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(procesar_sku_threadsafe, token_cuenta, sku_lp, regla, resultados, gc_connection, None, sesion_compartida, id_cuenta): sku_lp for sku_lp, regla in reglas_cuenta.items()}
            completados = 0
            for future in as_completed(futures):
                completados += 1
                if completados % 10 == 0: logger.info(f"⏳ [{id_cuenta}] Progreso: {completados}/{len(reglas_cuenta)} SKUs")

    historial_rows, archivo_negro_rows, alertas = resultados.obtener_todos()
    for alerta in alertas: enviar_alerta_telegram(alerta)
    if historial_rows: guardar_en_sql(historial_rows)
    if archivo_negro_rows and db:
        for rival_data in archivo_negro_rows:
            try: db.registrar_rival(*rival_data)
            except: pass

    gc.collect()
    logger.info("\n🏁 Misión cumplida.")
    enviar_telegram(f"🏁 *BARRIDO MEGAZORD V5.4 COMPLETADO*\nTotal de SKUs evaluados: {total_skus_procesados}")

if __name__ == "__main__":
    ejecutar_bot()
