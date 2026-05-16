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
from db_manager import DbManager

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
    hash_sku = hashlib.md5(sku_real.encode()).hexdigest()[:6].upper()
    return f"SKU_{hash_sku}"

def enmascarar_vendedor(nombre_vendedor):
    if not nombre_vendedor or nombre_vendedor == "Desconocido":
        return "Desconocido"
        
    nombre_upper = str(nombre_vendedor).upper()
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
    os.getenv("SCRAPERAPI_KEY_4", "").strip(), # 👈 Agregas esta línea
]

EXTERNAL_API_CREDENTIALS = [cred for cred in credenciales_crudas if cred]
CREDENTIAL_ROTATION_INDEX = 0

# ==========================================
# RADIO TELEGRAM (DATOS REALES)
# ==========================================
def enviar_mensaje_telegram(mensaje):
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

def obtener_inventario_walmart(token_wmt, credenciales_b64, sku_wmt):
    url = f"https://marketplace.walmartapis.com/v3/inventory?sku={sku_wmt}"
    headers = {
        "Authorization": f"Basic {credenciales_b64}",
        "WM_SEC.ACCESS_TOKEN": token_wmt,
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

def obtener_mi_precio_walmart(token_wmt, credenciales_b64, sku_wmt):
    url = f"https://marketplace.walmartapis.com/v3/price?sku={sku_wmt}"
    headers = {
        "Authorization": f"Basic {credenciales_b64}",
        "WM_SEC.ACCESS_TOKEN": token_wmt,
        "WM_SVC.NAME": "Walmart Marketplace",
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "Accept": "application/json",
        "WM_MARKET": "mx"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        
        if res.status_code == 200:
            precio = float(res.json().get("pricing", [{}])[0].get("currentPrice", {}).get("amount", 0.0))
            if precio == 0.0:
                logger.warning(f"   ⚠️ API retornó estructura pero precio = 0.0")
            return precio
    except:
        pass
    return 0.0

def actualizar_precio_walmart(token_wmt, credenciales_b64, sku_wmt, nuevo_precio):
    url = f"https://marketplace.walmartapis.com/v3/price?sku={sku_wmt}"
    headers = {
        "Authorization": f"Basic {credenciales_b64}",
        "WM_SEC.ACCESS_TOKEN": token_wmt,
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
# EL ESCÁNER DE PRECIOS (Visión de Rayos X - JSON)
# ==========================================
def espiar_ofertas_walmart(url_producto):
    # ELIMINAMOS la variable global CREDENTIAL_ROTATION_INDEX que causaba el bloqueo
    
    try:
        # El bot intentará con cada llave de tu armería para cada producto
        for credencial in EXTERNAL_API_CREDENTIALS:
            logger.info(f"🥷 Iniciando escaneo de precios (Rayos X)...")
            
            payload = {
                'api_key': credencial, 
                'url': url_producto,
                'country_code': 'mx',
                'render': 'false'  # 👈 Apagamos el renderizado caro
                # Eliminamos premium y device_type para volver al costo de 1 crédito
            }
            
            try:
                res = requests.get('https://api.scraperapi.com/', params=payload, timeout=60)
                
                if res.status_code == 429 or res.status_code == 403:
                    logger.warning(f"⚠️ Credencial rechazada o límite de tasa. Intentando con la siguiente llave...")
                    continue # Falla esta llave, intenta con la siguiente del "for"
                
                if res.status_code != 200 or not res.text or len(res.text) < 100:
                    logger.warning(f"⚠️ Error de escaneo o respuesta vacía")
                    return 0.0, [], "Error"
                
                precio_actual = 0.0
                ganador = "Desconocido"
                rivales = []
                
                # 👁️ VISIÓN DE RAYOS X: Buscar el JSON oculto __NEXT_DATA__
                match_json = re.search(r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>', res.text, re.DOTALL)
                
                if match_json:
                    try:
                        datos_json = json.loads(match_json.group(1))
                        queries = datos_json.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
                        ofertas_json = []
                        
                        for q in queries:
                            data = q.get("state", {}).get("data", {})
                            if "product" in data and "offers" in data["product"]:
                                ofertas_json = data["product"]["offers"]
                                break
                        
                        if ofertas_json:
                            logger.info(f"   ✅ JSON decodificado: Encontrados {len(ofertas_json)} competidores.")
                            ofertas_json = sorted(ofertas_json, key=lambda x: float(x.get("price", 0)))
                            
                            primer_lugar = ofertas_json[0]
                            precio_actual = float(primer_lugar.get("price", 0))
                            ganador = primer_lugar.get("sellerName", primer_lugar.get("sellerId", "WALMART"))
                            
                            for oferta in ofertas_json:
                                precio_r = float(oferta.get("price", 0))
                                nombre_r = oferta.get("sellerName", oferta.get("sellerId", "Desconocido"))
                                rivales.append({"precio": precio_r, "nombre": nombre_r})
                                
                            return precio_actual, rivales, ganador
                            
                    except json.JSONDecodeError:
                        logger.warning("   ⚠️ Error decodificando el JSON. Usando Fallback.")
                
                # 🛡️ FALLBACK TRADICIONAL
                logger.warning("   ⚠️ No se encontró JSON. Activando escáner tradicional...")
                match_precio = re.search(r'"price":\s*([0-9.]+)', res.text) or \
                               re.search(r'"priceAmount":\s*([0-9.]+)', res.text) or \
                               re.search(r'itemprop="price"[^>]*content="([0-9.]+)"', res.text)
                if match_precio:
                    precio_actual = float(match_precio.group(1))

                match_vendedor = re.search(r'"sellerName":\s*"([^"]+)"', res.text) or \
                                 re.search(r'Vendido y enviado por\s*([^<]+)', res.text)
                if match_vendedor:
                    ganador = match_vendedor.group(1).strip()
                elif precio_actual > 0:
                    ganador = "WALMART"

                match_rival = re.search(r'Desde \$([0-9,]+(?:\.[0-9]+)?)', res.text)
                if match_rival:
                    precio_rival_secundario = float(match_rival.group(1).replace(',', ''))

                rivales = [{"precio": precio_actual, "nombre": ganador}]
                if precio_rival_secundario > 0:
                    rivales.append({"precio": precio_rival_secundario, "nombre": "Segundo"})
                    
                return precio_actual, rivales, ganador

            except requests.Timeout:
                logger.warning(f"⚠️ Timeout en escaneo. Reintentando...")
                continue
            except Exception as e:
                logger.warning(f"⚠️ Error en escaneo: {str(e)[:50]}")
                continue
        
        # Si termina el ciclo 'for' y ninguna de las 3 llaves funcionó:
        return 0.0, [], "Bloqueado"
        
    except Exception as e:
        logger.warning(f"⚠️ Error crítico en escáner: {str(e)[:50]}")
        return 0.0, [], "Error"

# ==========================================
# 🛡️ FUNCIONES DE SEGURIDAD E HISTORIAL
# ==========================================
def aplicar_freno_8_porciento(nuestro_precio_actual, nuevo_precio_propuesto):
    if nuestro_precio_actual <= 0:
        return nuevo_precio_propuesto, False
    
    limite_seguro = round(nuestro_precio_actual * 1.08, 2)
    
    if nuevo_precio_propuesto > limite_seguro:
        # 🛡️ Aplicar el freno, pero RESTAURANDO la firma .09 para no perder la identidad
        limite_con_firma = float(int(limite_seguro - 1)) + 0.09
        logger.warning(f"🛡️ FRENO 8%: Limitado a ${limite_con_firma:.2f} (Firma restaurada)")
        return limite_con_firma, True
    else:
        return nuevo_precio_propuesto, False

def guardar_historial_walmart(hoja_historial, sku_wmt, mi_precio_anterior, nuevo_precio, ganancia, ganador_bb):
    """Guarda los movimientos en la pestaña Historial_WMT"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fila = [
            timestamp, 
            "Sin SKU",           # B: SKU_Interno
            "Sin SKU",           # C: SKU_Limpio
            sku_wmt,             # D: SKU_Walmart
            mi_precio_anterior,  # E: Nuestro_Precio Anterior
            "Guerrilla/Opt",     # F: Regla_Aplicada
            nuevo_precio,        # G: Resultado (Nuevo Precio)
            "N/A",               # H: Stock
            ganador_bb           # I: Observaciones / Ganador
        ]
        hoja_historial.append_row(fila)
    except Exception as e:
        logger.error(f"⚠️ Error guardando historial en Sheets: {e}")

# ==========================================
# CEREBRO PRINCIPAL DE WALMART
# ==========================================
def ejecutar_bot_walmart(token_wmt, creds_b64, hoja_principal, hoja_rivales, hoja_historial):
    logger.info("🚀 INICIANDO MEGAZORD WALMART")
    enviar_mensaje_telegram("🤖 *Megazord Walmart* despertando. Iniciando patrullaje...")
    
    try:
        identificador_hoja = os.getenv("GOOGLE_SHEET_ID", "").strip()
        
        if not identificador_hoja:
            logger.error("❌ GOOGLE_SHEET_ID no configurado")
            return
            
        # Reutilizamos el cliente ya autenticado que pasaremos por parámetro (ver gatillo)
        cliente_gspread = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_name("credentials.json", ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]))
        
        if "http" in identificador_hoja:
            matriz = cliente_gspread.open_by_url(identificador_hoja)
        else:
            matriz = cliente_gspread.open_by_key(identificador_hoja)
            
        hoja_walmart = matriz.worksheet("Hoja 1")
        datos = hoja_walmart.get_all_records()
        df = pd.DataFrame(datos)
        
        df.columns = df.columns.str.strip()
        df_activos = df[df['estatus_wmt'].astype(str).str.upper() == 'ACTIVO']
        logger.info(f"📋 Procesando {len(df_activos)} productos activos")
        
# ==========================================
        # INICIALIZAR GESTOR DE BASE DE DATOS
        # ==========================================
        def limpiar_precio(valor):
            try:
                if pd.isna(valor): return 0.0
                return float(str(valor).replace('$', '').replace(',', '').strip())
            except Exception:
                return 0.0

        try:
            db = DbManager()
            logger.info("✅ Conexión a PostgreSQL establecida")
        except Exception as e:
            logger.error(f"❌ Error conectando a BD: {e}")
            db = None

        if db:
            logger.info("📥 Obteniendo SKUs activos de PostgreSQL...")
            skus_bd = db.obtener_skus_activos('walmart')
            if not skus_bd:
                logger.warning("⚠️ No hay SKUs activos en la BD para Walmart")
                skus_bd = []
        else:
            logger.warning("⚠️ BD no disponible, usando Google Sheets")
            skus_bd = []

        skus_para_procesar = skus_bd if skus_bd else df_activos

        for producto in skus_para_procesar:
            if db and isinstance(producto, dict):
                catalogo_id = producto.get('id')
                sku_wmt = producto.get('sku', '')
                min_wmt = float(producto.get('precio_minimo', 0))
                max_wmt = float(producto.get('precio_maximo', 0))
                stock_actual = producto.get('stock', 0)
                url_wmt = ""  
            else:
                catalogo_id = None
                sku_wmt = str(producto.get('sku_walmart', '') if isinstance(producto, dict) else producto['sku_walmart'])
                url_wmt = str(producto.get('url_walmart', '') if isinstance(producto, dict) else producto['url_walmart'])
                min_wmt = limpiar_precio(producto.get('minimo_wmt', 0) if isinstance(producto, dict) else producto.get('minimo_wmt', 0))
                max_wmt = limpiar_precio(producto.get('maximo_wmt', 0) if isinstance(producto, dict) else producto.get('maximo_wmt', 0))
                
            sku_display = enmascarar_sku(sku_wmt)
            logger.info(f"🔍 Evaluando: {sku_display}")
            
            # --- 1. REVISIÓN DE INVENTARIO ---
            stock_actual = obtener_inventario_walmart(token_wmt, creds_b64, sku_wmt)
            mi_precio_actual = obtener_mi_precio_walmart(token_wmt, creds_b64, sku_wmt)
            
            try:
                hoja_walmart.update_cell(index + 2, 15, stock_actual)
            except Exception as e:
                pass
            
            # Circuit Breaker
            if stock_actual <= 0:
                logger.info(f"   ⏭️ Sin stock. Desactivando automáticamente...")
                
                # Registrar alerta en BD
                if db and catalogo_id:
                    try:
                        db.registrar_alerta(
                            catalogo_id=catalogo_id,
                            marketplace='WALMART',
                            tipo_alerta='STOCK_CRITICO',
                            severidad='ALTA',
                            mensaje=f"Stock crítico (0). SKU: {sku_wmt}"
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Error registrando alerta: {e}")
                
                try:
                    hoja_walmart.update_cell(index + 2, 10, "INACTIVO")
                    enviar_mensaje_telegram(f"🚨 *Sin Stock*...")
                except Exception as e:
                    logger.warning(f"Error al desactivar SKU")
                continue
                
            # --- 2. ESPIONAJE DE PRECIOS ---
            precio_bb, rivales, ganador = espiar_ofertas_walmart(url_wmt)
            ganador_enmascarado = enmascarar_vendedor(ganador)
            logger.info(f"   👑 BuyBox: ${precio_bb} (Vendedor: {ganador_enmascarado})")

            # Registrar rivales en la BD
            if db and catalogo_id and rivales:
                try:
                    for rival in rivales:
                        db.registrar_rival(
                            catalogo_id=catalogo_id,
                            marketplace='WALMART',
                            nombre_rival=rival.get('nombre', 'Desconocido'),
                            precio_rival=float(rival.get('precio', 0)),
                            posicion=rival.get('posicion', 0)
                        )
                    logger.info(f"✅ {len(rivales)} rivales registrados en BD")
                except Exception as e:
                    logger.warning(f"⚠️ Error registrando rivales: {e}")
            
            # --- 3. TÁCTICAS DE COMBATE: INTELIGENCIA GUERRILLA ---
            if "NOSOTROS" not in ganador_enmascarado and precio_bb > 0:
                
                buybox_defendible = precio_bb >= min_wmt
                rival_objetivo = None
                tipo_ataque = "NONE"
                
                if buybox_defendible:
                    rival_objetivo = precio_bb
                    tipo_ataque = "DIRECTO"
                else:
                    rivales_viables = []
                    
                    for r in rivales:
                        precio_r = float(r.get("precio", 0))
                        nombre_original = r.get("nombre", "")
                        nombre_r = enmascarar_vendedor(nombre_original)
                        
                        es_rentable = precio_r >= min_wmt
                        es_segundo = "Segundo" in nombre_original
                        
                        es_nuestra_firma = (precio_r == max_wmt) or (precio_r >= min_wmt and f"{precio_r:.2f}".endswith('.09'))
                        
                        if es_segundo and es_nuestra_firma:
                            logger.warning(f"   🛡️ SEGURO BLINDADO ACTIVADO: Ignorando a 'Segundo' (${precio_r})")
                            continue
                            
                        es_enemigo_por_nombre = (nombre_r != "NOSOTROS")
                        if es_rentable and es_enemigo_por_nombre:
                            rivales_viables.append(r)
                            
                    if rivales_viables:
                        # 🎯 CURA DE CLAUDE CORRECTAMENTE INDENTADA
                        rival_objetivo = min([float(r.get("precio", 0)) for r in rivales_viables])
                        tipo_ataque = "GUERRILLA"
                
                # EJECUTAR ATAQUE
                if rival_objetivo and rival_objetivo > 0:
                    undercut_random = random.uniform(5, 10) # Mayor undercut para despegarse
                    nuevo_precio = float(int(rival_objetivo - undercut_random)) + 0.09
                    
                    # Candados de seguridad con protección de decimales
                    if nuevo_precio < min_wmt:
                        # Sumamos 1 al entero para asegurar que el .09 rebase tu mínimo con decimales
                        nuevo_precio = float(int(min_wmt) + 1) + 0.09
                        
                    if max_wmt > 0 and nuevo_precio > max_wmt:
                        # Restamos 1 al entero para asegurar que el .09 no perfore tu máximo
                        nuevo_precio = float(int(max_wmt) - 1) + 0.09

                    if nuevo_precio >= min_wmt:
                        logger.info(f"   🎯 Objetivo {tipo_ataque}: ${rival_objetivo} | Undercut | Nuevo: ${nuevo_precio}")
                        actualizar_precio_walmart(token_wmt, creds_b64, sku_wmt, nuevo_precio)

                    # Registrar en historial de BD
                    if db and catalogo_id:
                        try:
                            db.registrar_historial(
                                catalogo_id=catalogo_id,
                                marketplace='WALMART',
                                precio_ant=mi_precio_actual,
                                precio_nuv=nuevo_precio,
                                stock=stock_actual,
                                regla="Guerrilla Inteligente" if tipo_ataque == "GUERRILLA" else "Directo",
                                resultado="EJECUTADO",
                                notas=f"Rival objetivo: ${rival_objetivo:.2f}, Undercut: ${undercut_random:.2f}"
                            )
                            logger.info(f"✅ Historial registrado en BD (ID: {catalogo_id})")
                        except Exception as e:
                            logger.warning(f"⚠️ Error registrando en historial: {e}")    
                        
                        # 📝 GUARDAR EN HISTORIAL
                        guardar_historial_walmart(hoja_historial, sku_wmt, mi_precio_actual, nuevo_precio, round(nuevo_precio - min_wmt, 2), ganador)
                        
                        mensaje_telegram = (
                            f"⚔️ *Gladiador {tipo_ataque.title()}*\n"
                            f"SKU: {sku_wmt}\n"
                            f"Rival Objetivo: ${rival_objetivo}\n"
                            f"Tu Nuevo Precio: ${nuevo_precio}\n"
                            f"Margen: ${nuevo_precio - min_wmt:.2f}"
                        )
                        enviar_mensaje_telegram(mensaje_telegram)
                    else:
                        logger.info(f"   ⚠️ Margen insuficiente tras cálculo. No atacando.")
                else:
                    logger.info(f"   🛡️ Posición defensiva: sin rivales viables en nuestro rango.")
                    
            elif "NOSOTROS" in ganador_enmascarado:
                # Táctica 3: Optimización (ya ganamos)
                precio_segundo = 0.0
                if len(rivales) > 1:
                    precio_segundo = float(rivales[1].get("precio", 0))
                
                if precio_segundo > precio_bb:
                    distancia_random = random.randint(4, 6) 
                    nuevo_precio = float(int(precio_segundo - distancia_random)) + 0.09
                    
                    if max_wmt > 0 and nuevo_precio > max_wmt:
                        # Restamos 1 al entero para asegurar que el .09 no perfore tu máximo
                        nuevo_precio = float(int(max_wmt) - 1) + 0.09
                        
                    if nuevo_precio > precio_bb:
                        nuestro_precio_actual = precio_bb  
                        
                        nuevo_precio, fue_limitado = aplicar_freno_8_porciento(
                            nuestro_precio_actual,
                            nuevo_precio
                        )
                        
                        logger.info(f"   🚀 Optimización de margen ejecutada {'(FRENO aplicado)' if fue_limitado else ''}")
                        actualizar_precio_walmart(token_wmt, creds_b64, sku_wmt, nuevo_precio)
                        
                        # 📝 GUARDAR EN HISTORIAL
                        guardar_historial_walmart(hoja_historial, sku_wmt, mi_precio_actual, nuevo_precio, round(nuevo_precio - min_wmt, 2), ganador)
                        
                        mensaje = (
                            f"🚀 *Optimización de Margen*\n"
                            f"SKU: {sku_wmt}\n"
                            f"Precio Anterior: ${precio_bb}\n"
                            f"Nuevo Precio: ${nuevo_precio}"
                        )
                        if fue_limitado:
                            mensaje += f"\n\n🛡️ (Freno 8% aplicado)"
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
        
        # Buscamos la variable en plural o en singular para evitar errores de GitHub
        GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID") or os.getenv("GOOGLE_SHEET_ID")
        
        if not GOOGLE_SHEETS_ID:
            logger.error("❌ El ID de Google Sheets está vacío. Revisa tus GitHub Secrets o archivo .env")
            exit(1)
        hoja_principal = cliente_gspread.open_by_key(GOOGLE_SHEETS_ID).worksheet("Hoja 1")
        hoja_rivales = cliente_gspread.open_by_key(GOOGLE_SHEETS_ID).worksheet("Rivales_WMT")
        hoja_historial = cliente_gspread.open_by_key(GOOGLE_SHEETS_ID).worksheet("Historial_WMT")
        
    except Exception as e:
        logger.error(f"❌ Error al conectar Google Sheets: {e}")
        exit(1)

    token_wmt, creds_b64 = obtener_token_walmart()

    if token_wmt:
        ejecutar_bot_walmart(token_wmt, creds_b64, hoja_principal, hoja_rivales, hoja_historial)
    else:
        logger.error("❌ No se pudo obtener el token de Walmart.")
