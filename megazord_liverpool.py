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
                if locator.is_visible(timeout=15000):
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
                if locator.is_visible(timeout=15000):
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
            if not submit_button or not submit_button.is_visible(timeout=15000):
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
                            if locator.is_visible(timeout=15000):
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

# ==========================================
# CIRCUIT BREAKER GLOBALES
# ==========================================
CIRCUIT_LOCK = threading.Lock()
STATS_PW = {"intentos": 0, "timeouts": 0, "abortar": False}

def obtener_info_rivales(token, liverpool_sku):
    """Scraping con Circuit Breaker anti-timeout."""
    global STATS_PW
    
    with CIRCUIT_LOCK:
        if STATS_PW["abortar"]:
            logger.warning(f"🛑 Circuit Breaker ACTIVO - devolviendo vacío para SKU {liverpool_sku}")
            return []
        STATS_PW["intentos"] += 1
    
    url = f"https://www.liverpool.com.mx/tienda/producto/{liverpool_sku}"
    logger.info(f"🔍 Scrapeando: {liverpool_sku}")
    
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_selector('.price-tag', timeout=15000)  # ← TIMEOUT ACTUALIZADO
            html = page.content()
            browser.close()
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        rivales = []
        seller_boxes = soup.find_all('div', class_='seller-offer')
        
        for seller in seller_boxes:
            try:
                nombre = seller.find('span', class_='seller-name').text.strip()
                precio_text = seller.find('span', class_='seller-price').text.strip()
                precio = float(precio_text.replace('$', '').replace(',', ''))
                
                if nombre.upper() != 'PRECIOS UNICOS':
                    rivales.append({"precio": precio, "nombre": nombre})
            except:
                continue
        
        return sorted(rivales, key=lambda x: x["precio"])
        
    except Exception as e:
        logger.error(f"❌ Playwright timeout: {e}")
        
        # CIRCUIT BREAKER LOGIC
        with CIRCUIT_LOCK:
            STATS_PW["timeouts"] += 1
            ratio = STATS_PW["timeouts"] / STATS_PW["intentos"] if STATS_PW["intentos"] > 0 else 0
            
            if STATS_PW["intentos"] >= 10 and ratio >= 0.30 and not STATS_PW["abortar"]:
                STATS_PW["abortar"] = True
                msg = f"🛑 *CIRCUIT BREAKER ACTIVADO*\n{STATS_PW['timeouts']}/{STATS_PW['intentos']} timeouts ({(ratio*100):.1f}%)\nBot pausado temporalmente."
                logger.error(msg)
                enviar_telegram(msg)
        
        # 🚫 NO usamos ShoppApp (datos viejos)
        return []
        
        # Buscar todos los sellers en la página
        seller_boxes = soup.find_all('div', class_='seller-offer')
        
        logger.info(f"✅ Sellers encontrados: {len(seller_boxes)}")
        
        for seller in seller_boxes:
            try:
                nombre = seller.find('span', class_='seller-name').text.strip()
                precio_text = seller.find('span', class_='seller-price').text.strip()
                precio = float(precio_text.replace('$', '').replace(',', ''))
                
                # No incluir tu propia tienda
                if nombre.upper() != 'PRECIOS UNICOS':
                    rivales.append({
                        "precio": precio,
                        "nombre": nombre
                    })
                    logger.info(f"  ✅ Rival: {nombre} - ${precio}")
            except Exception as e:
                logger.error(f"  ❌ Error parseando seller: {e}")
                continue
        
        logger.info(f"🎯 Total rivales reales: {len(rivales)}")
        return sorted(rivales, key=lambda x: x["precio"])
        
    except Exception as e:
        logger.error(f"❌ Error scrapeando HTML: {e}")
        logger.warning(f"⚠️ Cayendo a shoppapp como fallback...")
        
        # FALLBACK: Usar shoppapp si falla Playwright
        try:
            url_fallback = f"https://shoppapp.liverpool.com.mx/appclienteservices/services/v2/marketplace/pdp/getSellersOfferDetailsPdp?skuId={liverpool_sku}"
            res = crear_session_con_retry().get(url_fallback, headers={"User-Agent": "Liverpool/2.2.0"}, timeout=30)
            
            if res.status_code == 200:
                rivales = []
                for v in res.json().get("sellersOfferDetails", []):
                    if str(v.get("sellerId")) != str(SHOP_ID_PUBLICO):
                        precio = float(v.get("promoPrice") or v.get("salePrice") or 0)
                        if precio > 0:
                            rivales.append({
                                "precio": precio,
                                "nombre": str(v.get("sellerName", "Desconocido"))
                            })
                return sorted(rivales, key=lambda x: x["precio"])
        except Exception as e2:
            logger.error(f"❌ Fallback shoppapp también falló: {e2}")
    
    logger.warning(f"⚠️ Retornando lista vacía para SKU: {liverpool_sku}")
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
    
    # 🔍 DEBUG: Ver qué se va a enviar
    print(f"🚀 DISPARAR_PRECIO LLAMADO:", flush=True)
    print(f"   📍 URL: {url}", flush=True)
    print(f"   🎫 Offer ID: {offer_id}", flush=True)
    print(f"   💰 Nuevo precio: ${nuevo_precio}", flush=True)
    print(f"   📦 Stock: {stock}", flush=True)
    print(f"   🔐 Token (primeros 20): {token[:20]}...", flush=True)
    logger.info(f"🚀 DISPARAR_PRECIO LLAMADO - Offer: {offer_id}, Precio: ${nuevo_precio}, Stock: {stock}")
    
    try:
        if MODO_SIMULACION:
            imprimir_simulacion(f"DISPARAR_PRECIO | SKU: {sku_notificacion} | Bajaría a: ${nuevo_precio}")
            return True
        liverpool_rate_limiter.wait()
        
        # 📤 Hacer el request
        print(f"📤 Enviando PUT a pro-api...", flush=True)
        response = crear_session_con_retry().put(url, headers=headers, json=payload, timeout=30)
        
        # 🔍 DEBUG: Ver la respuesta
        print(f"📤 Response Status: {response.status_code}", flush=True)
        print(f"📤 Response Body (primeros 300 chars): {response.text[:300]}", flush=True)
        logger.info(f"📤 PUT Response: {response.status_code} - {response.text[:100]}")
        
        if response.status_code in [200, 204]:
            print(f"✅ Ajuste ejecutado: ${nuevo_precio}", flush=True)
            logger.info(f"✅ Ajuste ejecutado: {enmascarar_precio(nuevo_precio)}")
            return True
        else:
            print(f"❌ Error disparar_precio: Status {response.status_code} - {response.text[:200]}", flush=True)
            logger.error(f"❌ Error disparar_precio: Status {response.status_code} - {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"❌ Exception en disparar_precio: {e}", flush=True)
        print(f"❌ Traceback: {traceback.format_exc()}", flush=True)
        logger.error(f"❌ disparar_precio exception: {e}")
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
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

        info_rivales = obtener_info_rivales(token, sku_lp)  # ← Agregar token
        precios_rivales = [r["precio"] for r in info_rivales]

        precio_minimo_regla = safe_float(regla.get('precio_minimo', 0))
        precio_maximo_regla = safe_float(regla.get('precio_maximo', base_price) or base_price)
        costo_odoo_sheet = safe_float(regla.get('costo_odoo', 0))

        sku_display = enmascarar_sku(sku_lp)
        logger.info(f"🔍 [{id_cuenta}] Escaneando {sku_display} | BB: {enmascarar_vendedor(info_rivales[0]['nombre'] if info_rivales else 'N/A')}")

        hora_actual_str = (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        
        catalogo_id = regla.get('id')
        if catalogo_id:
            for idx, r in enumerate(info_rivales): resultados.agregar_archivo_negro((catalogo_id, 'LIVERPOOL', r["nombre"], r["precio"], idx + 1))

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
                        margen_actual = round(float(rival_mas_bajo) - float(precio_actual), 2)
                        
                        # 🔍 DEBUG: Ver margen y precio
                        logger.info(f"💰 [SKU: {sku_i}] Rival más bajo: ${rival_mas_bajo} | Tu precio: ${precio_actual} | Margen: ${margen_actual}")
                        logger.info(f"📊 [SKU: {sku_i}] Rango: min=${precio_minimo_regla} max=${precio_maximo_regla}")
                        
                        # 🎯 SOLUCIÓN PROBLEMA 1:
                        
                        # 🎯 SOLUCIÓN PROBLEMA 1: CHECK "YA ESTAMOS GANANDO" (Propuesta mejorada de Gemini)
                        # Si estamos ganando por centavos o hasta por $2.00, CONGELAMOS EL PRECIO
                        if 0.01 <= margen_actual <= 2.00:
                            # ✅ YA ESTAMOS GANANDO CON MARGEN SALUDABLE
                            pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                            resultados.agregar_historial([
                                hora_actual_str, sku_i, sku_lp, rival_mas_bajo, 
                                precio_actual, cantidad, pos, bb, id_cuenta
                            ])
                            with resultados._lock:
                                resultados.ultimo_estado_conocido[sku_i] = {
                                    'hay_rivales': True,
                                    'ciclo_anterior': 'manteniendo_posicion_ganadora'
                                }
                        
                        # ⚔️ ATAQUE: Si estamos más caros, o si la ventaja es mayor a $2.00 (estamos perdiendo dinero a lo tonto)
                        else:
                            baja = round(random.uniform(1.50, 1.96), 2)
                            nuevo_precio = round(rival_mas_bajo - baja, 2)
                            
                            if precio_maximo_regla > 0 and nuevo_precio > precio_maximo_regla:
                                nuevo_precio = precio_maximo_regla
                            
                            if nuevo_precio >= precio_minimo_regla:
                                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                                if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                    resultados.agregar_historial([
                                        hora_actual_str, sku_i, sku_lp, rival_mas_bajo, 
                                        nuevo_precio, cantidad, pos, bb, id_cuenta
                                    ])
                                    with resultados._lock:
                                        resultados.ultimo_estado_conocido[sku_i] = {
                                            'hay_rivales': True,
                                            'ciclo_anterior': 'ataque_ejecutado'
                                        }
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
                                
                                with resultados._lock:
                                    resultados.ultimo_estado_conocido[sku_i] = {
                                        'hay_rivales': True,
                                        'ciclo_anterior': 'modo_sombra_activado'
                                    }
                            
                            if float(precio_actual) != float(nuevo_precio):
                                pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                                if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                    resultados.agregar_historial([
                                        hora_actual_str, sku_i, sku_lp, rival_mas_bajo, 
                                        nuevo_precio, cantidad, pos, bb, id_cuenta
                                    ])
                                else:
                                    resultados.agregar_historial([
                                        hora_actual_str, sku_i, sku_lp, rival_mas_bajo, 
                                        precio_actual, cantidad, pos, bb, id_cuenta
                                    ])
                            else:
                                pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                                resultados.agregar_historial([
                                    hora_actual_str, sku_i, sku_lp, rival_mas_bajo, 
                                    precio_actual, cantidad, pos, bb, id_cuenta
                                ])
                else:
                    # 🎯 SOLUCIÓN PROBLEMA 2: DEBOUNCING PARA MONOPOLIO FALSO
                    # SIN RIVALES: Verificar si es monopolio real o falso positivo
                    
                    # Obtener estado del ciclo anterior
                    with resultados._lock:
                        estado_anterior = resultados.ultimo_estado_conocido.get(sku_i, None)
                    
                    # =============== LÓGICA DE DOBLE CHECK MEJORADA ===============
                    if estado_anterior is None:
                        # 🟡 CASO 1: PRIMERA VEZ SIN RIVALES
                        # No es monopolio confirmado aún, esperar siguiente ciclo
                        pos, bb = calcular_posicion_buybox([], precio_actual)
                        
                        msg_alerta = (
                            f"⏳ *PRIMERA DETECCIÓN SIN RIVALES ({id_cuenta})*\n\n"
                            f"📦 *{sku_i}*\n"
                            f"ℹ️ API no devolvió competidores en este ciclo.\n"
                            f"🔄 Acción: Manteniendo precio `${precio_actual}` para confirmación.\n"
                            f"⚠️ Si persiste en próximo ciclo, consideraremos monopolio real."
                        )
                        
                        resultados.agregar_alerta(msg_alerta)
                        resultados.agregar_historial([
                            hora_actual_str, sku_i, sku_lp, "PRIMERA VEZ - SIN RIVAL", 
                            precio_actual, cantidad, pos, bb, id_cuenta
                        ])
                        
                        with resultados._lock:
                            resultados.ultimo_estado_conocido[sku_i] = {
                                'hay_rivales': False,
                                'ciclo_anterior': 'primera_vez_sin_rivales'
                            }
                    
                    elif estado_anterior.get('hay_rivales') == True:
                        # ⚠️ CASO 2: DOBLE CHECK
                        # En el ciclo anterior SÍ había rivales, ahora NO
                        # Probabilidad: Es un falso positivo de la API (falla temporal)
                        # ACCIÓN: Mantener precio actual y esperar confirmación
                        pos, bb = calcular_posicion_buybox([], precio_actual)
                        
                        msg_alerta = (
                            f"⏳ *DOBLE CHECK: Esperando confirmación de Monopolio ({id_cuenta})*\n\n"
                            f"📦 *{sku_i}*\n"
                            f"ℹ️ API no devolvió rivales en este ciclo.\n"
                            f"💼 Ciclo anterior: Había rivales disponibles.\n"
                            f"🔄 Acción: Manteniendo precio `${precio_actual}` hasta confirmación.\n"
                            f"⚠️ Si persiste, consideraremos monopolio real en próximo ciclo."
                        )
                        
                        resultados.agregar_alerta(msg_alerta)
                        resultados.agregar_historial([
                            hora_actual_str, sku_i, sku_lp, "DOBLE CHECK - SIN RIVAL", 
                            precio_actual, cantidad, pos, bb, id_cuenta
                        ])
                        
                        with resultados._lock:
                            resultados.ultimo_estado_conocido[sku_i] = {
                                'hay_rivales': False,
                                'ciclo_anterior': 'doble_check_activado'
                            }
                    
                    else:
                        # ✅ CASO 3: MONOPOLIO CONFIRMADO
                        # Sin rivales ciclo anterior y actual (estado_anterior['hay_rivales'] == False)
                        # Disparar al máximo (es seguro)
                        if tipo_regla.startswith('4'):
                            mejor_historico = resultados.max_precio_buybox_historico.get(sku_i, precio_maximo_regla) if hasattr(resultados, 'max_precio_buybox_historico') else precio_maximo_regla
                            nuevo_precio = mejor_historico if mejor_historico > 0 else precio_maximo_regla
                        else:
                            nuevo_precio = precio_maximo_regla
                        
                        pos, bb = calcular_posicion_buybox([], nuevo_precio)
                        
                        if float(precio_actual) != float(nuevo_precio):
                            if disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i):
                                msg_alerta = (
                                    f"👑 *MONOPOLIO CONFIRMADO ({id_cuenta})*\n\n"
                                    f"📦 *{sku_i}*\n"
                                    f"🎯 Somos los únicos vendedores.\n"
                                    f"💰 Precio ajustado a máximo: `${nuevo_precio}`"
                                )
                                resultados.agregar_alerta(msg_alerta)
                                resultados.agregar_historial([
                                    hora_actual_str, sku_i, sku_lp, "SIN RIVAL", 
                                    nuevo_precio, cantidad, pos, bb, id_cuenta
                                ])
                        else:
                            resultados.agregar_historial([
                                hora_actual_str, sku_i, sku_lp, "SIN RIVAL", 
                                precio_actual, cantidad, pos, bb, id_cuenta
                            ])
                        
                        with resultados._lock:
                            resultados.ultimo_estado_conocido[sku_i] = {
                                'hay_rivales': False,
                                'ciclo_anterior': 'monopolio_confirmado'
                            }

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

def reset_circuit_breaker():
    """Reinicia los contadores del Circuit Breaker cuando Liverpool está estable."""
    global STATS_PW
    
    with CIRCUIT_LOCK:
        STATS_PW = {"intentos": 0, "timeouts": 0, "abortar": False}
        logger.info("🔄 CIRCUIT BREAKER RESETEADO - Sistema listo para operar")
        enviar_telegram("🔄 *Circuit Breaker reseteado* - Sistema listo para operar nuevamente")

# AGREGAR AL INICIO DE ejecutar_bot():
if STATS_PW["abortar"]:
    logger.info("ℹ️ Circuit Breaker estaba activo. Evaluando...")
    # Aquí podrías preguntar manualmente o agregar lógica de recuperación

def ejecutar_bot():
    """Función principal del bot"""
    logger.info("--- INICIANDO MEGAZORD LIVERPOOL ---")
    
    # ✅ NUEVA: Verificar si hay orden de reset del Circuit Breaker
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT valor FROM config_sistema WHERE clave = 'reset_circuit_breaker'")
                resultado = cursor.fetchone()
                if resultado and resultado[0] == 'true':
                    reset_circuit_breaker()  # Tu función local de reset
                    cursor.execute("UPDATE config_sistema SET valor = 'false' WHERE clave = 'reset_circuit_breaker'")
                    conn.commit()
                    logger.info("♻️ Circuit Breaker reseteado por orden externa (CLI/Dashboard)")
    except Exception as e:
        logger.error(f"⚠️ Error verificando bandera de reset: {e}")
    
    # ... resto de tu código ejecutar_bot() ...
    
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
                cursor.execute("SELECT id_cuenta, nombre_descriptivo, email_usuario, token_autorizacion, cookie_vip, timestamp_token FROM cuentas_liverpool WHERE is_active = TRUE")
                cuentas_activas = cursor.fetchall()

                if not cuentas_activas:
                    logger.warning("⚠️ No hay cuentas activas en la Bóveda VIP.")
                    return
                
                # 🛑 STALENESS DETECTION
                for cuenta in cuentas_activas:
                    id_cuenta, nombre_desc, email_usuario, token_cuenta, cookie_vip, timestamp_token = cuenta
                    
                    if timestamp_token:
                        horas_transcurridas = (datetime.now() - timestamp_token).total_seconds() / 3600
                        if horas_transcurridas > 24:
                            msg = f"🚨 *CRÍTICO: TOKEN OBSOLETO ({id_cuenta})*\n\nEl Bearer Token tiene {horas_transcurridas:.1f} horas de antigüedad.\n🛑 Bot abortado para evitar operar a ciegas."
                            logger.error(msg)
                            enviar_telegram(msg)
                            continue  # Salta esta cuenta
                
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
    
        # DEBUG: Ver qué viene de la BD
        print(f"🔍 Token de BD (primeros 50 chars): {token_cuenta[:50] if token_cuenta else 'NULO'}")
        logger.info(f"🔍 Token de BD (primeros 50 chars): {token_cuenta[:50] if token_cuenta else 'NULO'}")
    
        # ✅ DESENCRIPTAR
        FERNET_ENCRYPTION_KEY = os.getenv("FERNET_ENCRYPTION_KEY")
        print(f"🔐 FERNET_ENCRYPTION_KEY existe?: {bool(FERNET_ENCRYPTION_KEY)}")
        logger.info(f"🔐 FERNET_ENCRYPTION_KEY existe?: {bool(FERNET_ENCRYPTION_KEY)}")
    
        if FERNET_ENCRYPTION_KEY and token_cuenta:
            try:
                cipher = Fernet(FERNET_ENCRYPTION_KEY.encode())
                token_cuenta = cipher.decrypt(token_cuenta.encode()).decode()
                print(f"✅ Token desencriptado! (primeros 50 chars): {token_cuenta[:50]}")
                print(f"🔐 Token completo (SOLO DEBUGGING): {token_cuenta[:100]}...")  # ← AGREGAR ESTA LÍNEA
                logger.info(f"✅ Token desencriptado! (primeros 50 chars): {token_cuenta[:50]}")
                logger.info(f"🔐 Token completo (SOLO DEBUGGING): {token_cuenta[:100]}...")  # ← AGREGAR ESTA LÍNEA
            except Exception as e:
                print(f"❌ Error desencriptando: {e}")
                logger.error(f"❌ Error desencriptando: {e}")
                continue
        else:
            print(f"⚠️ No hay clave o token es nulo")
            logger.warning(f"⚠️ No hay clave o token es nulo")
            continue
        
        logger.info(f"\n==========================================")
        logger.info(f"🏪 CARGANDO MOTOR PARA: {nombre_desc} ({id_cuenta})")
        # ... resto igual

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

            # 🔍 DEBUG: Ver exactamente qué header se está enviando
            print(f"🔍 HEADER PING: Authorization: Bearer {token_cuenta[:50]}...", flush=True)
            logger.info(f"🔍 HEADER PING: Authorization: Bearer {token_cuenta[:50]}...")
            
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
                logger.warning(f"💀 El Ping devolvió 401. Intentando rescate...")
    
                try:
                    with psycopg2.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cursor:
                            # Buscar PENÚLTIMO token
                            cursor.execute("""
                                SELECT token_encriptado FROM bearer_token_history 
                                WHERE id_cuenta = %s AND status = 'active' 
                                ORDER BY captured_at DESC OFFSET 1 LIMIT 1
                            """, (id_cuenta,))
                            token_respaldo_row = cursor.fetchone()
                            
                            if token_respaldo_row and FERNET_ENCRYPTION_KEY:
                                token_respaldo_enc = token_respaldo_row[0]
                                cipher = Fernet(FERNET_ENCRYPTION_KEY.encode())
                                token_respaldo = cipher.decrypt(token_respaldo_enc.encode()).decode()
                                
                                logger.info("🔄 Probando ping con token de respaldo...")
                                headers_respaldo = {"Authorization": f"Bearer {token_respaldo}"}
                                res_respaldo = crear_session_con_retry().get(url_ping, headers=headers_respaldo, timeout=10)
                                
                                if res_respaldo.status_code == 200:
                                    logger.info("✅ ¡RESCATE EXITOSO! Token anterior vivo.")
                                    token_cuenta = token_respaldo
                                    token_valido = True
                                    
                                    # Actualizar BD
                                    cursor.execute("UPDATE cuentas_liverpool SET token_autorizacion=%s WHERE id_cuenta=%s", 
                                                  (token_respaldo_enc, id_cuenta))
                                    conn.commit()
                                else:
                                    logger.error("❌ Token de respaldo también 401")
                            else:
                                logger.error("❌ No hay tokens en historial")
                except Exception as e:
                    logger.error(f"❌ Error retry logic: {e}")
                
                if not token_valido:
                    msg = f"🚨 *CAÍDA DE TOKENS ({id_cuenta})*\nPrincipal y respaldo devolvieron 401."
                    enviar_telegram(msg)
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

# ==========================================
# CLI INTERFACE
# ==========================================
import argparse
import sys

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Megazord Liverpool - Repricing Bot")
    parser.add_argument("--reset-breaker", action="store_true", 
                       help="Resetea Circuit Breaker en la BD y sale")
    parser.add_argument("--run", action="store_true", default=True,
                       help="Ejecuta el bot normalmente (default)")
    
    args = parser.parse_args()
    
    if args.reset_breaker:
        try:
            print("🔄 Reseteando Circuit Breaker en PostgreSQL...")
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE config_sistema SET valor = 'true' WHERE clave = 'reset_circuit_breaker'")
                    conn.commit()
            print("✅ CLI: Circuit Breaker reseteado exitosamente.")
            print("📌 Megazord leerá la bandera en el próximo ciclo.")
            sys.exit(0)
        except Exception as e:
            print(f"❌ CLI Error: {e}")
            sys.exit(1)
    
    # Ejecutar bot normalmente
    ejecutar_bot()
