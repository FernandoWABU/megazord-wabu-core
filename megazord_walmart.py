import requests
import json
import uuid
import re
import random
import time
import os
import base64
import logging
import hashlib
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
from datetime import datetime

# ==========================================
# CONFIGURACIÓN DEL LOGGER
# ==========================================
logging.basicConfig(
    format='%(asctime)s | %(levelname)-8s | %(funcName)s | %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# FUNCIONES DE ENMASCARAMIENTO (LOGS PÚBLICOS SOLO)
# ==========================================
def enmascarar_sku(sku_real):
    """
    Convierte SKU real en hash para logs públicos.
    Ejemplo: SKU12345 -> SKU_a1b2c3
    
    NOTA: Esto se usa SOLO en logger.info() para GitHub Actions.
    Para Telegram (privado), usamos el SKU real.
    """
    hash_sku = hashlib.md5(sku_real.encode()).hexdigest()[:6].upper()
    return f"SKU_{hash_sku}"

def enmascarar_vendedor(nombre_vendedor):
    """Enmascara vendedor - detecta si somos nosotros."""
    if not nombre_vendedor or nombre_vendedor == "Desconocido":
        return "Desconocido"
        
    nombre_upper = str(nombre_vendedor).upper()
    
    # ¡AQUÍ ESTÁ LA CLAVE! Agregar todas las identidades de tu empresa
    if "AROMANDOTE" in nombre_upper or "WABU" in nombre_upper or "NUARE" in nombre_upper:
        return "NOSOTROS"
        
    return "RIVAL"

# ==========================================
# ARMERÍA DE MERCENARIOS
# ==========================================
credenciales_crudas = [
    os.getenv("SCRAPERAPI_KEY_1", "").strip(),
    os.getenv("SCRAPERAPI_KEY_2", "").strip(),
    os.getenv("SCRAPERAPI_KEY_3", "").strip(),
]

EXTERNAL_API_CREDENTIALS = [cred for cred in credenciales_crudas if cred]
CREDENTIAL_ROTATION_INDEX = 0

# ==========================================
# RADIO TELEGRAM (DATOS REALES)
# ==========================================
def enviar_mensaje_telegram(mensaje):
    """Envía un reporte a tu celular vía Telegram CON DATOS REALES"""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_WMT") 
    
    if not token or not chat_id:
        logger.warning("⚠️ No se encontraron las credenciales de Telegram en el entorno.")
        return
        
    url_telegram = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url_telegram, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"❌ Error enviando mensaje: Verifica TELEGRAM_TOKEN")

# ==========================================
# FUNCIONES DE WALMART API
# ==========================================
def obtener_token_walmart():
    """Obtiene token de acceso a API de Walmart"""
    client_id = os.getenv("WALMART_USER", "").strip(" \n\r\t\"'")
    client_secret = os.getenv("WALMART_PASS", "").strip(" \n\r\t\"'")
    
    if not client_id or not client_secret:
        logger.error("❌ Faltan credenciales WALMART_USER o WALMART_PASS")
        return None, None

    auth_str = f"{client_id}:{client_secret}"
    creds_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    
    url = "https://marketplace.walmartapis.com/v3/token"
    
    headers = {
        "Authorization": f"Basic {creds_b64}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "WM_SVC.NAME": "Walmart Marketplace",
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "WM_MARKET": "mx"  
    }
    
    data = "grant_type=client_credentials"
    
    logger.info("🔵 Solicitando token de acceso...")
    try:
        res = requests.post(url, headers=headers, data=data, timeout=15)
        if res.status_code == 200:
            logger.info("✅ Autenticación exitosa")
            return res.json().get("access_token"), creds_b64
        else:
            logger.error(f"❌ Error de autenticación HTTP {res.status_code}")
            return None, None
    except Exception as e:
        logger.error(f"❌ Error de conexión: {str(e)[:100]}")
        return None, None

def obtener_inventario_walmart(token, credenciales_b64, sku_wmt):
    """Consulta el stock real de un SKU específico"""
    url = f"https://marketplace.walmartapis.com/v3/inventory?sku={sku_wmt}"
    headers = {
        "Authorization": f"Basic {credenciales_b64}",
        "WM_SEC.ACCESS_TOKEN": token,
        "WM_SVC.NAME": "Walmart Marketplace",
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "Accept": "application/json",
        "WM_MARKET": "mx"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return int(data.get("quantity", {}).get("amount", 0))
    except Exception as e:
        logger.warning(f"⚠️ Error consultando inventario")
    return 0

def actualizar_precio_walmart(token, credenciales_b64, sku_wmt, nuevo_precio):
    """Actualiza el precio de un producto en Walmart"""
    url = f"https://marketplace.walmartapis.com/v3/price?sku={sku_wmt}"
    headers = {
        "Authorization": f"Basic {credenciales_b64}",
        "WM_SEC.ACCESS_TOKEN": token,
        "WM_SVC.NAME": "Walmart Marketplace",
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "WM_MARKET": "mx"
    }
    
    payload = {
        "sku": sku_wmt,
        "pricing": [{
            "currentPrice": {"currency": "MXN", "amount": float(nuevo_precio)},
            "currentPriceType": "BASE"
        }]
    }
    
    try:
        res = requests.put(url, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            logger.info(f"✅ Precio actualizado correctamente")
            return True
    except Exception as e:
        logger.warning(f"⚠️ Error al actualizar precio")
    return False

# ==========================================
# EL ESCÁNER DE PRECIOS (Secure)
# ==========================================
def espiar_ofertas_walmart(url_producto):
    """
    Escanea precios de competencia usando ScraperAPI.
    Versión segura: HTTPS, credencial rotación, validación robusta.
    """
    global CREDENTIAL_ROTATION_INDEX
    
    try:
        while CREDENTIAL_ROTATION_INDEX < len(EXTERNAL_API_CREDENTIALS):
            credencial = EXTERNAL_API_CREDENTIALS[CREDENTIAL_ROTATION_INDEX]
            logger.info(f"🥷 Iniciando escaneo de precios...")
            
            payload = {
                'api_key': credencial, 
                'url': url_producto,
                'country_code': 'mx',
                'render': 'false'
            }
            
            try:
                # ✅ HTTPS en lugar de HTTP
                res = requests.get(
                    'https://api.scraperapi.com/',
                    params=payload, 
                    timeout=60
                )
                
                # Validación robusta de respuesta
                if res.status_code == 429:  # Rate limit
                    logger.warning(f"⚠️ Límite de tasa alcanzado. Rotando credencial...")
                    CREDENTIAL_ROTATION_INDEX += 1 
                    continue
                
                if res.status_code == 403:  # Unauthorized
                    logger.warning(f"⚠️ Credencial rechazada. Rotando...")
                    CREDENTIAL_ROTATION_INDEX += 1 
                    continue
                
                if res.status_code != 200:
                    logger.warning(f"⚠️ Error de escaneo")
                    return 0.0, [], "Indisponible"
                
                # Validar que haya contenido
                if not res.text or len(res.text) < 100:
                    logger.warning("⚠️ Respuesta vacía o corrupta")
                    return 0.0, [], "Corrupto"
                
                # ==========================================
                # PARSEO DE PRECIOS
                # ==========================================
                precio_actual = 0.0
                ganador = "Desconocido"
                precio_rival_secundario = 0.0
                
                # Buscar precio principal
                match_precio = re.search(r'"price":\s*([0-9.]+)', res.text) or \
                               re.search(r'"priceAmount":\s*([0-9.]+)', res.text) or \
                               re.search(r'itemprop="price"[^>]*content="([0-9.]+)"', res.text)
                if match_precio:
                    precio_actual = float(match_precio.group(1))

                # Buscar vendedor (nombre real para Telegram)
                match_vendedor = re.search(r'"sellerName":\s*"([^"]+)"', res.text) or \
                                 re.search(r'Vendido y enviado por\s*([^<]+)', res.text)
                if match_vendedor:
                    ganador = match_vendedor.group(1).strip()
                elif precio_actual > 0:
                    ganador = "WALMART"

                # Buscar precio rival
                match_rival = re.search(r'Desde \$([0-9,]+(?:\.[0-9]+)?)', res.text)
                if match_rival:
                    precio_rival_secundario = float(match_rival.group(1).replace(',', ''))

                rivales = [{"precio": precio_actual, "nombre": ganador}]
                if precio_rival_secundario > 0:
                    rivales.append({"precio": precio_rival_secundario, "nombre": "Segundo"})
                    
                return precio_actual, rivales, ganador

            except requests.Timeout:
                logger.warning(f"⚠️ Timeout en escaneo. Reintentando...")
                time.sleep(2)
                continue
            except Exception as e:
                logger.warning(f"⚠️ Error en escaneo: {str(e)[:50]}")
                return 0.0, [], "Error"
        
        return 0.0, [], "Bloqueado"
        
    except Exception as e:
        logger.warning(f"⚠️ Error crítico en escáner: {str(e)[:50]}")
        return 0.0, [], "Error"

# ==========================================
# 🛡️ FRENO DE SEGURIDAD: PROTECCIÓN 8%
# ==========================================
def aplicar_freno_8_porciento(nuestro_precio_actual, nuevo_precio_propuesto):
    # Validación: si no tenemos precio válido, permitir
    if nuestro_precio_actual <= 0:
        return nuevo_precio_propuesto, False
    
    # Calcular límite seguro (8% de incremento máximo)
    limite_seguro = round(nuestro_precio_actual * 1.08, 2)
    
    # Verificar si excede límite
    if nuevo_precio_propuesto > limite_seguro:
        # 🚨 FRENO ACTIVADO
        logger.warning(
            f"🛡️ FRENO 8%: Incremento demasiado brusco detectado\n"
            f"   Precio actual: ${nuestro_precio_actual:.2f}\n"
            f"   Precio propuesto: ${nuevo_precio_propuesto:.2f}\n"
            f"   Límite seguro (8%): ${limite_seguro:.2f}\n"
            f"   ACCIÓN: Limitado a ${limite_seguro:.2f}"
        )
        return limite_seguro, True  # Fue limitado
    else:
        # ✅ Incremento dentro de límites seguros
        return nuevo_precio_propuesto, False  # No fue limitado

# ==========================================
# CEREBRO PRINCIPAL DE WALMART
# ==========================================
def ejecutar_bot_walmart(token, creds_b64, cliente_gspread):
    logger.info("🚀 INICIANDO MEGAZORD WALMART")
    enviar_mensaje_telegram("🤖 *Megazord Walmart* despertando. Iniciando patrullaje...")
    
    try:
        identificador_hoja = os.getenv("GOOGLE_SHEET_ID", "").strip()
        
        if not identificador_hoja:
            logger.error("❌ GOOGLE_SHEET_ID no configurado")
            return
            
        if "http" in identificador_hoja:
            matriz = cliente_gspread.open_by_url(identificador_hoja)
        else:
            matriz = cliente_gspread.open_by_key(identificador_hoja)
            
        hoja_walmart = matriz.worksheet("Hoja 1")
        datos = hoja_walmart.get_all_records()
        df = pd.DataFrame(datos)
        
        # Limpieza de datos
        df.columns = df.columns.str.strip()
        df_activos = df[df['estatus_wmt'].astype(str).str.upper() == 'ACTIVO']
        logger.info(f"📋 Procesando {len(df_activos)} productos activos")
        
        # Función auxiliar
        def limpiar_precio(valor):
            try:
                if pd.isna(valor): return 0.0
                return float(str(valor).replace('$', '').replace(',', '').strip())
            except:
                return 0.0

        for index, row in df_activos.iterrows():
            sku_wmt = str(row['sku_walmart'])
            url_wmt = str(row['url_walmart'])
            min_wmt = limpiar_precio(row.get('minimo_wmt', 0))
            max_wmt = limpiar_precio(row.get('maximo_wmt', 0))
            
            # ✅ PARA LOGS: usar SKU enmascarado
            sku_display = enmascarar_sku(sku_wmt)
            logger.info(f"🔍 Evaluando: {sku_display}")
            
            # --- 1. REVISIÓN DE INVENTARIO ---
            stock_actual = obtener_inventario_walmart(token, creds_b64, sku_wmt)
            
            try:
                hoja_walmart.update_cell(index + 2, 15, stock_actual)
            except Exception as e:
                pass
            
            # Circuit Breaker
            if stock_actual <= 0:
                logger.info(f"   ⏭️ Sin stock. Desactivando automáticamente...")
                try:
                    hoja_walmart.update_cell(index + 2, 10, "INACTIVO")
                    # ✅ TELEGRAM RECIBE DATOS REALES
                    enviar_mensaje_telegram(f"🚨 *Sin Stock*\nProducto: {sku_wmt}\nAcción: Desactivado automáticamente")
                except Exception as e:
                    logger.warning(f"Error al desactivar SKU")
                continue
                
            # --- 2. ESPIONAJE DE PRECIOS ---
            precio_bb, rivales, ganador = espiar_ofertas_walmart(url_wmt)
            
            # ✅ PARA LOGS: usar vendedor enmascarado
            ganador_enmascarado = enmascarar_vendedor(ganador)
            logger.info(f"   👑 BuyBox: ${precio_bb} (Vendedor: {ganador_enmascarado})")
            
# --- 3. TÁCTICAS DE COMBATE: INTELIGENCIA GUERRILLA ---
            if "NOSOTROS" not in ganador_enmascarado and precio_bb > 0:
                
                # ==========================================
                # TÁCTICA GLADIADOR - VERSIÓN GUERRILLA
                # ==========================================
                
                # Paso 1: Validar si BuyBox es defendible
                buybox_defendible = precio_bb >= min_wmt
                
                # Paso 2: Encontrar "Rival Válido"
                rival_objetivo = None
                tipo_ataque = "NONE"
                
                if buybox_defendible:
                    # BuyBox está en nuestro rango: atacar directo
                    rival_objetivo = precio_bb
                    tipo_ataque = "DIRECTO"
                else:
                    # 🛡️ Filtrar rivales que tengan stock, sean rentables Y QUE NO SEAMOS NOSOTROS
                    rivales_viables = [
                        r for r in rivales 
                        if r.get("precio", 0) >= min_wmt and enmascarar_vendedor(r.get("nombre", "")) != "NOSOTROS"
                    ]
                    
                    if rivales_viables:
                        # Tomar el más barato de los viables
                        rival_objetivo = min(rivales_viables, key=lambda x: x["precio"])["precio"]
                        tipo_ataque = "GUERRILLA"
                
                # Paso 3: Aplicar undercut aleatorio
                if rival_objetivo and rival_objetivo > 0:
                    undercut_random = random.randint(3, 6)
                    nuevo_precio = round(rival_objetivo - undercut_random, 2)
                    
                    # Protección: nunca bajar del mínimo
                    if nuevo_precio >= min_wmt:
                        logger.info(f"   ⚔️ Ataque {tipo_ataque}: Rival ${rival_objetivo} - ${undercut_random} = ${nuevo_precio}")
                        actualizar_precio_walmart(token, creds_b64, sku_wmt, nuevo_precio)
                        
                        mensaje_telegram = (
                            f"⚔️ *Gladiador {tipo_ataque.title()}*\n"
                            f"SKU: {sku_wmt}\n"
                            f"Rival Objetivo: ${rival_objetivo}\n"
                            f"Undercut: ${undercut_random}\n"
                            f"Tu Nuevo Precio: ${nuevo_precio}\n"
                            f"Margen de Ganancia: ${nuevo_precio - min_wmt:.2f}"
                        )
                        
                        if tipo_ataque == "GUERRILLA":
                            mensaje_telegram += f"\n\n🎯 Atacando al 2do rival porque el BuyBox (${precio_bb}) es muy bajo."
                        
                        enviar_mensaje_telegram(mensaje_telegram)
                    else:
                        logger.info(f"   ⚠️ Margen insuficiente. No atacando.")
                        enviar_mensaje_telegram(
                            f"⚠️ *Sin Margen*\n"
                            f"SKU: {sku_wmt}\n"
                            f"Rival más viable: ${rival_objetivo}\n"
                            f"Tu mínimo: ${min_wmt}\n"
                            f"No hay margen suficiente para atacar."
                        )
                else:
                    logger.info(f"   🛡️ Posición defensiva: sin rivales viables en nuestro rango.")
                    
            elif "NOSOTROS" in ganador_enmascarado:
                # Táctica 3: Optimización (ya ganamos)
                precio_segundo = 0.0
                if len(rivales) > 1:
                    precio_segundo = rivales[1]["precio"]
                
                if precio_segundo > precio_bb:
                    distancia_random = random.randint(4, 6) 
                    nuevo_precio = round(precio_segundo - distancia_random, 2)
                    
                    if max_wmt > 0 and nuevo_precio > max_wmt:
                        nuevo_precio = max_wmt
                        
                    if nuevo_precio > precio_bb:
                        # ========== 🛡️ FRENO DEL 8% ==========
                        nuestro_precio_actual = precio_bb  # Estamos en el BuyBox
                        
                        # Aplicar freno: limitar incremento a máximo 8%
                        nuevo_precio, fue_limitado = aplicar_freno_8_porciento(
                            nuestro_precio_actual,
                            nuevo_precio
                        )
                        
                        if fue_limitado:
                            logger.info(f"   🚀 Optimización de margen ejecutada (FRENO aplicado)")
                        else:
                            logger.info(f"   🚀 Optimización de margen ejecutada")
                        
                        actualizar_precio_walmart(token, creds_b64, sku_wmt, nuevo_precio)
                        
                        mensaje = (
                            f"🚀 *Optimización de Margen*\n"
                            f"SKU: {sku_wmt}\n"
                            f"Precio Anterior: ${precio_bb}\n"
                            f"Nuevo Precio: ${nuevo_precio}"
                        )
                        
                        if fue_limitado:
                            mensaje += f"\n\n🛡️ (Freno 8% aplicado para proteger cuenta)"
                        
                        enviar_mensaje_telegram(mensaje)
                    else:
                        logger.info("   ✅ Margen ya optimizado")
                else:
                    logger.info("   ✅ Posición dominante confirmada")
            else:
                logger.info("   ✅ Sin acción requerida")
                
        logger.info("🏁 Barrido completado")
        enviar_mensaje_telegram("🏁 *Patrullaje completado*. Sistema en espera.")
        
    except Exception as e:
        logger.error(f"❌ Error crítico: {str(e)[:100]}")
        enviar_mensaje_telegram(f"🚨 *Alerta*: Error durante patrullaje. Verifica logs.")

# ==========================================
# GATILLO DE ARRANQUE
# ==========================================
if __name__ == "__main__":
    load_dotenv()

    logger.info(f"⏰ Ejecutando ciclo de patrullaje manual o por CRON...")

    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        cliente_gspread = gspread.authorize(creds)
    except Exception as e:
        logger.error(f"❌ Error al conectar Google Sheets")
        exit(1)

    token_wmt, creds_b64 = obtener_token_walmart()

    if token_wmt:
        ejecutar_bot_walmart(token_wmt, creds_b64, cliente_gspread)
    else:
        logger.error("❌ No se pudo autenticar")

    else:
        logger.info(f"💤 Sistema en modo reposo. Próximo ciclo en 1 hora.")
