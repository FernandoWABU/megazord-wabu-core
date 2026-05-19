#!/usr/bin/env python3
# ==========================================
# MEGAZORD WALMART - VERSIÓN ENTERPRISE V3
# ==========================================
# Concurrencia multihilo, integración PostgreSQL
# y ScraperAPI con rotación de llaves.

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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
from datetime import datetime
from db_manager import DbManager

# ==========================================
# CONFIGURACIÓN DEL LOGGER
# ==========================================
logging.basicConfig(
    format='%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# FUNCIONES DE ENMASCARAMIENTO
# ==========================================
def enmascarar_sku(sku_real):
    hash_sku = hashlib.md5(str(sku_real).encode()).hexdigest()[:6].upper()
    return f"SKU_{hash_sku}"

def enmascarar_vendedor(nombre_vendedor):
    if not nombre_vendedor or nombre_vendedor == "Desconocido":
        return "Desconocido"
        
    nombre_upper = str(nombre_vendedor).upper()
    if "AROMANDOTE" in nombre_upper or "WABU" in nombre_upper or "NUARE" in nombre_upper:
        return "NOSOTROS"
        
    return "RIVAL"

# ==========================================
# ARMERÍA DE MERCENARIOS (ScraperAPI)
# ==========================================
def obtener_llaves_scraper():
    credenciales_crudas = [
        os.getenv("SCRAPERAPI_KEY_1", "").strip(),
        os.getenv("SCRAPERAPI_KEY_2", "").strip(),
        os.getenv("SCRAPERAPI_KEY_3", "").strip(),
        os.getenv("SCRAPERAPI_KEY_4", "").strip(), 
    ]
    return [cred for cred in credenciales_crudas if cred]

# ==========================================
# RADIO TELEGRAM
# ==========================================
def enviar_mensaje_telegram(mensaje):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_WMT") 
    
    if not token or not chat_id:
        return
        
    url_telegram = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}
    
    try:
        requests.post(url_telegram, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"❌ Error enviando mensaje a Telegram")

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
    
    try:
        res = requests.post(url, headers=headers, data="grant_type=client_credentials", timeout=15)
        if res.status_code == 200:
            logger.info("✅ Autenticación API Walmart exitosa")
            return res.json().get("access_token"), creds_b64
        else:
            logger.error(f"❌ Error de autenticación HTTP {res.status_code}")
            return None, None
    except Exception as e:
        logger.error(f"❌ Error de conexión API: {e}")
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
            return int(res.json().get("quantity", {}).get("amount", 0))
    except: pass
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
            return float(res.json().get("pricing", [{}])[0].get("currentPrice", {}).get("amount", 0.0))
    except: pass
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
            logger.info(f"   ✅ Precio actualizado en Walmart API a ${nuevo_precio}")
            return True
    except: pass
    return False

# ==========================================
# EL ESCÁNER DE PRECIOS (Rayos X)
# ==========================================
def espiar_ofertas_walmart(url_producto, llaves_scraper):
    for credencial in llaves_scraper:
        payload = {
            'api_key': credencial, 
            'url': url_producto,
            'country_code': 'mx',
            'render': 'false'
        }
        
        try:
            res = requests.get('https://api.scraperapi.com/', params=payload, timeout=60)
            if res.status_code in [429, 403]: continue
            if res.status_code != 200 or not res.text or len(res.text) < 100: return 0.0, [], "Error"
            
            precio_actual = 0.0
            ganador = "Desconocido"
            rivales = []
            
            # JSON oculto __NEXT_DATA__
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
                        ofertas_json = sorted(ofertas_json, key=lambda x: float(x.get("price", 0)))
                        primer_lugar = ofertas_json[0]
                        precio_actual = float(primer_lugar.get("price", 0))
                        ganador = primer_lugar.get("sellerName", primer_lugar.get("sellerId", "WALMART"))
                        
                        for idx, oferta in enumerate(ofertas_json):
                            precio_r = float(oferta.get("price", 0))
                            nombre_r = oferta.get("sellerName", oferta.get("sellerId", "Desconocido"))
                            rivales.append({"precio": precio_r, "nombre": nombre_r, "posicion": idx + 1})
                            
                        return precio_actual, rivales, ganador
                except: pass
            
            # Fallback Tradicional
            match_precio = re.search(r'"price":\s*([0-9.]+)', res.text) or re.search(r'"priceAmount":\s*([0-9.]+)', res.text)
            if match_precio: precio_actual = float(match_precio.group(1))

            match_vendedor = re.search(r'"sellerName":\s*"([^"]+)"', res.text) or re.search(r'Vendido y enviado por\s*([^<]+)', res.text)
            if match_vendedor: ganador = match_vendedor.group(1).strip()
            elif precio_actual > 0: ganador = "WALMART"

            match_rival = re.search(r'Desde \$([0-9,]+(?:\.[0-9]+)?)', res.text)
            precio_rival_secundario = float(match_rival.group(1).replace(',', '')) if match_rival else 0.0

            rivales = [{"precio": precio_actual, "nombre": ganador, "posicion": 1}]
            if precio_rival_secundario > 0:
                rivales.append({"precio": precio_rival_secundario, "nombre": "Segundo", "posicion": 2})
                
            return precio_actual, rivales, ganador

        except: continue
    return 0.0, [], "Bloqueado"

# ==========================================
# 🛡️ CLASE THREAD-SAFE Y SEGURIDAD
# ==========================================
class ResultadosThreadSafe:
    def __init__(self):
        self._lock = threading.Lock()
        self.historial_sheets = []
        self.alertas = []

    def agregar_historial_sheet(self, fila):
        with self._lock:
            self.historial_sheets.append(fila)

    def agregar_alerta(self, mensaje):
        with self._lock:
            self.alertas.append(mensaje)

def aplicar_freno_8_porciento(nuestro_precio_actual, nuevo_precio_propuesto):
    if nuestro_precio_actual <= 0: return nuevo_precio_propuesto, False
    limite_seguro = round(nuestro_precio_actual * 1.08, 2)
    if nuevo_precio_propuesto > limite_seguro:
        limite_con_firma = float(int(limite_seguro - 1)) + 0.09
        return limite_con_firma, True
    return nuevo_precio_propuesto, False

# ==========================================
# CEREBRO CONCURRENTE POR SKU
# ==========================================
def procesar_sku(producto, token_wmt, creds_b64, db, llaves_scraper, resultados):
    # Traductor Universal
    catalogo_id = producto.get('id')
    sku_wmt = str(producto.get('sku', producto.get('sku_walmart', '')))
    sku_limpio = str(producto.get('sku_limpio', producto.get('sku_interno', sku_wmt)))
    url_wmt = str(producto.get('url_walmart', ''))
    
    try:
        min_wmt = float(producto.get('precio_minimo', producto.get('minimo_wmt', 0)))
        max_wmt = float(producto.get('precio_maximo', producto.get('maximo_wmt', 0)))
    except:
        min_wmt, max_wmt = 0.0, 0.0
        
    logger.info(f"\n🔍 Evaluando: {enmascarar_sku(sku_wmt)}")
    
    # 1. REVISIÓN DE INVENTARIO
    stock_actual = obtener_inventario_walmart(token_wmt, creds_b64, sku_wmt)
    mi_precio_actual = obtener_mi_precio_walmart(token_wmt, creds_b64, sku_wmt)
    
    if stock_actual <= 0:
        logger.info(f"   ⏭️ Sin stock físico. Ejecutando Circuit Breaker...")
        if db and catalogo_id:
            try:
                db.registrar_alerta(catalogo_id, 'WALMART', 'STOCK_CRITICO', 'ALTA', f"Stock crítico (0). SKU: {sku_limpio}")
                # Apagado automático en PostgreSQL
                db.execute_query("UPDATE catalogo_maestro_v3 SET estatus_wmt = 'INACTIVO' WHERE id = %s", (catalogo_id,))
                logger.info(f"   🔌 Apagado automático exitoso en BD para {sku_limpio}")
            except Exception as e:
                logger.warning(f"   ⚠️ Error en Circuit Breaker BD: {e}")
        resultados.agregar_alerta(f"🚨 *Circuit Breaker*: Producto `{sku_limpio}` sin stock. Marcado INACTIVO.")
        return True
        
    # 2. ESPIONAJE DE PRECIOS
    if not url_wmt:
        logger.warning(f"   ⚠️ SKU {sku_limpio} no tiene URL de Walmart. Omitiendo escaneo.")
        return False
        
    precio_bb, rivales, ganador = espiar_ofertas_walmart(url_wmt, llaves_scraper)
    ganador_enmascarado = enmascarar_vendedor(ganador)
    logger.info(f"   👑 BuyBox: ${precio_bb} ({ganador_enmascarado}) | Rivales: {len(rivales)}")

    if db and catalogo_id and rivales:
        try:
            for rival in rivales:
                db.registrar_rival(catalogo_id, 'WALMART', rival.get('nombre', 'Desconocido'), float(rival.get('precio', 0)), rival.get('posicion', 0))
        except: pass
    
    # 3. TÁCTICAS DE COMBATE
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
                es_rentable = precio_r >= min_wmt
                es_nuestra_firma = (precio_r == max_wmt) or (precio_r >= min_wmt and f"{precio_r:.2f}".endswith('.09'))
                
                if "Segundo" in nombre_original and es_nuestra_firma: continue
                if es_rentable and enmascarar_vendedor(nombre_original) != "NOSOTROS":
                    rivales_viables.append(r)
                    
            if rivales_viables:
                rival_objetivo = min([float(r.get("precio", 0)) for r in rivales_viables])
                tipo_ataque = "GUERRILLA"
        
        if rival_objetivo and rival_objetivo > 0:
            undercut_random = random.uniform(5, 10)
            nuevo_precio = float(int(rival_objetivo - undercut_random)) + 0.09
            
            if nuevo_precio < min_wmt: nuevo_precio = float(int(min_wmt) + 1) + 0.09
            if max_wmt > 0 and nuevo_precio > max_wmt: nuevo_precio = float(int(max_wmt) - 1) + 0.09

            if nuevo_precio >= min_wmt:
                logger.info(f"   🎯 Objetivo {tipo_ataque}: ${rival_objetivo} | Nuevo: ${nuevo_precio}")
                if actualizar_precio_walmart(token_wmt, creds_b64, sku_wmt, nuevo_precio):
                    if db and catalogo_id:
                        try:
                            db.registrar_historial(catalogo_id, 'WALMART', mi_precio_actual, nuevo_precio, stock_actual, tipo_ataque, "EJECUTADO", f"Rival: ${rival_objetivo}")
                        except: pass
                    
                    # Preparar para Google Sheets
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    resultados.agregar_historial_sheet([timestamp, sku_limpio, sku_limpio, sku_wmt, mi_precio_actual, tipo_ataque, nuevo_precio, stock_actual, ganador])
                    resultados.agregar_alerta(f"⚔️ *{tipo_ataque}* | `{sku_limpio}`\nObjetivo: `${rival_objetivo}` → Nuevo: `${nuevo_precio}`")
            else:
                logger.info(f"   ⚠️ Precio objetivo ${nuevo_precio} perfora el mínimo de ${min_wmt}. Abortando ataque.")
        else:
            logger.info(f"   🛡️ Sin rivales viables en nuestro rango.")
            
    elif "NOSOTROS" in ganador_enmascarado:
        precio_segundo = float(rivales[1].get("precio", 0)) if len(rivales) > 1 else 0.0
        
        if precio_segundo > precio_bb:
            nuevo_precio = float(int(precio_segundo - random.randint(4, 6))) + 0.09
            if max_wmt > 0 and nuevo_precio > max_wmt: nuevo_precio = float(int(max_wmt) - 1) + 0.09
                
            if nuevo_precio > precio_bb:
                nuevo_precio, fue_limitado = aplicar_freno_8_porciento(precio_bb, nuevo_precio)
                
                logger.info(f"   🚀 Optimizando margen a ${nuevo_precio} {'(FRENO aplicado)' if fue_limitado else ''}")
                if actualizar_precio_walmart(token_wmt, creds_b64, sku_wmt, nuevo_precio):
                    if db and catalogo_id:
                        try:
                            db.registrar_historial(catalogo_id, 'WALMART', mi_precio_actual, nuevo_precio, stock_actual, "Optimización", "EJECUTADO", f"Freno: {fue_limitado}")
                        except: pass
                    
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    resultados.agregar_historial_sheet([timestamp, sku_limpio, sku_limpio, sku_wmt, mi_precio_actual, "Optimización", nuevo_precio, stock_actual, ganador])
                    
                    msg = f"🚀 *Optimización* | `{sku_limpio}`\nAnterior: `${precio_bb}` → Nuevo: `${nuevo_precio}`"
                    if fue_limitado: msg += "\n🛡️ (Freno 8% aplicado)"
                    resultados.agregar_alerta(msg)
            else:
                logger.info("   ✅ Margen ya optimizado")
        else:
            logger.info("   ✅ Posición dominante confirmada")
    
    return True

# ==========================================
# CEREBRO PRINCIPAL
# ==========================================
def ejecutar_bot_walmart():
    logger.info("="*80)
    logger.info("🚀 INICIANDO MEGAZORD WALMART V3 ENTERPRISE")
    logger.info("="*80)
    
    load_dotenv()
    enviar_mensaje_telegram("🤖 *Megazord Walmart V3* despertando. Conectando a la matriz...")
    
    token_wmt, creds_b64 = obtener_token_walmart()
    if not token_wmt:
        logger.error("❌ Abortando: Sin token de Walmart")
        return
        
    llaves_scraper = obtener_llaves_scraper()
    if not llaves_scraper:
        logger.error("❌ Faltan llaves de ScraperAPI")
        return

    # 1. INICIALIZAR DBMANAGER
    db = None
    try:
        db = DbManager()
        logger.info("✅ Conexión a PostgreSQL establecida")
    except Exception as e:
        logger.warning(f"⚠️ BD no disponible: {e}")

    # 2. OBTENER SKUS
    skus_para_procesar = []
    hoja_historial = None
    
    if db:
        skus_para_procesar = db.obtener_skus_activos('walmart')
        logger.info(f"📥 {len(skus_para_procesar)} SKUs activos obtenidos de PostgreSQL")
        
    if not skus_para_procesar:
        logger.warning("⚠️ Sin datos en BD. Intentando Fallback a Google Sheets...")
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            cliente_gspread = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope))
            hoja_principal = cliente_gspread.open_by_key(os.getenv("GOOGLE_SHEET_ID")).worksheet("Hoja 1")
            df = pd.DataFrame(hoja_principal.get_all_records())
            df.columns = df.columns.str.strip().str.lower()
            skus_para_procesar = df[df['estatus_wmt'].astype(str).str.upper() == 'ACTIVO'].to_dict('records')
            logger.info(f"📥 {len(skus_para_procesar)} SKUs obtenidos del Excel")
        except Exception as e:
            logger.error(f"❌ Fallo masivo obteniendo SKUs: {e}")
            return

    # Para el historial antiguo (opcional, si falla Sheets no detenemos el bot)
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        cliente_gspread = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope))
        hoja_historial = cliente_gspread.open_by_key(os.getenv("GOOGLE_SHEET_ID")).worksheet("Historial_WMT")
    except: pass

    # 3. PROCESAMIENTO MULTIHILO
    resultados = ResultadosThreadSafe()
    
    logger.info(f"🚀 Lanzando patrulla concurrente con 3 hilos...")
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(procesar_sku, prod, token_wmt, creds_b64, db, llaves_scraper, resultados) for prod in skus_para_procesar]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: logger.error(f"❌ Error en hilo: {e}")

    # 4. GUARDADO BATCH Y ALERTAS
    if hoja_historial and resultados.historial_sheets:
        try:
            hoja_historial.append_rows(resultados.historial_sheets)
            logger.info(f"📝 {len(resultados.historial_sheets)} registros guardados en Historial_WMT de Sheets")
        except Exception as e:
            logger.warning(f"⚠️ Error guardando en Sheets: {e}")

    if resultados.alertas:
        enviar_mensaje_telegram("🟡 *Reporte Walmart V3*\n\n" + "\n\n".join(resultados.alertas))

    logger.info("="*80)
    logger.info("🏁 MEGAZORD WALMART COMPLETADO")
    enviar_mensaje_telegram("🏁 *Patrullaje V3 completado*. Sistema en espera.")

if __name__ == "__main__":
    ejecutar_bot_walmart()
