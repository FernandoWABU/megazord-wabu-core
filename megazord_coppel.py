#!/usr/bin/env python3
# ==========================================
# MEGAZORD COPPEL - BOT DE REPRICING MIRAKL
# ==========================================
# Marketplace: Coppel (API REST Mirakl)
# Tienda: NUARE INVEST
# Función: Repricing inteligente + Guerrilla
# ==========================================

import os
import sys
import logging
import json
import time
import random
import re
import hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional

# NUEVO: Importar DbManager para PostgreSQL
from db_manager import DbManager
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# ==========================================
# CONFIGURACIÓN INICIAL
# ==========================================
load_dotenv()

# ---- CREDENCIALES ----
COPPEL_API_KEY = os.getenv("COPPEL_API_KEY", "")
COPPEL_BASE_URL = "https://coppel.mirakl.net/api"
COPPEL_SHOP_ID = "9187"
COPPEL_TIENDA_NOMBRE = "NUARE INVEST"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_COPPEL", "")

GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
SPREADSHEET_ID = os.getenv("COPPEL_SPREADSHEET_ID", "")

# ---- CONSTANTES DE NEGOCIO ----
COSTO_GUIA_FIJO = 92.00
COMISION_PLATAFORMA = 0.15  # 15%
IVA_ODOO = 1.16  # Aplicar al costo
TIENDA_DETECTABLE = "NUARE"  # Para detectar si somos nosotros

# ---- RANGOS DE OPERACIÓN ----
MIN_UNDERCUT = 5.00
MAX_UNDERCUT = 10.00
FRENO_SUBIDA_PORCENTAJE = 0.15  # 15% máximo de incremento

# ==========================================
# LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(funcName)-25s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# BANNER DE INICIO
# ==========================================
print("\n" + "="*80)
print("🟡 MEGAZORD COPPEL - BOT DE REPRICING MIRAKL")
print("="*80)
print(f"⏰ Iniciado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"🏪 Tienda: {COPPEL_TIENDA_NOMBRE}")
print("="*80 + "\n")

# ==========================================
# FUNCIONES DE ENMASCARAMIENTO
# ==========================================
def enmascarar_sku(sku_real):
    hash_sku = hashlib.md5(str(sku_real).encode()).hexdigest()[:6].upper()
    return f"SKU_{hash_sku}"

def enmascarar_precio(precio_real):
    try:
        return f"${int(float(precio_real))}.XX"
    except:
        return "$X.XX"

def enmascarar_vendedor(nombre_vendedor):
    if not nombre_vendedor:
        return "Desconocido"
    if TIENDA_DETECTABLE in str(nombre_vendedor).upper():
        return "🟡 NOSOTROS"
    return "RIVAL"

# ==========================================
# RATE LIMITER
# ==========================================
class RateLimiter:
    def __init__(self, calls_per_second=3):
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0

    def wait(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()

rate_limiter = RateLimiter(calls_per_second=2)

# ==========================================
# SESIÓN CON REINTENTOS
# ==========================================
def crear_session_mirakl():
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
# FUNCIONES DE CÁLCULO
# ==========================================
def calcular_rentabilidad_coppel(precio_venta: float, costo_odoo: float) -> Tuple[float, float]:
    costo_con_iva = costo_odoo * IVA_ODOO
    comision = precio_venta * COMISION_PLATAFORMA
    ganancia_neta = precio_venta - costo_con_iva - comision - COSTO_GUIA_FIJO
    margen_porcentaje = (ganancia_neta / precio_venta * 100) if precio_venta > 0 else 0
    return round(ganancia_neta, 2), round(margen_porcentaje, 1)

def es_precio_rentable(precio_venta: float, costo_odoo: float, minimo: float) -> bool:
    ganancia, _ = calcular_rentabilidad_coppel(precio_venta, costo_odoo)
    return ganancia > 0 and precio_venta >= minimo

# ==========================================
# FUNCIONES DE SEGURIDAD (FRENO 15%)
# ==========================================
def aplicar_freno_15_porciento(precio_actual: float, precio_propuesto: float) -> Tuple[float, bool]:
    if precio_actual <= 0:
        return precio_propuesto, False
    limite_seguro = round(precio_actual * (1 + FRENO_SUBIDA_PORCENTAJE), 2)
    if precio_propuesto > limite_seguro:
        logger.warning(f"🛡️ FRENO 15%: Incremento limitado a ${limite_seguro}")
        return limite_seguro, True
    return precio_propuesto, False

# ==========================================
# FUNCIONES DE TELEGRAM
# ==========================================
def enviar_mensaje_telegram(mensaje: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception:
        return False

# ==========================================
# API MIRAKL - OPERACIONES
# ==========================================
class MiraklCoppel:
    def __init__(self, api_key: str, base_url: str, shop_id: str):
        self.api_key = api_key
        self.base_url = base_url
        self.shop_id = shop_id
        self.session = crear_session_mirakl()
        self.headers = {"Authorization": f"{api_key}", "Content-Type": "application/json", "Accept": "application/json"}
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        rate_limiter.wait()
        url = f"{self.base_url}{endpoint}"
        try:
            if method.upper() == "GET": response = self.session.get(url, headers=self.headers, timeout=30, **kwargs)
            elif method.upper() == "PUT": response = self.session.put(url, headers=self.headers, timeout=30, **kwargs)
            elif method.upper() == "POST": response = self.session.post(url, headers=self.headers, timeout=30, **kwargs)
            else: return None
            
            if response.status_code in [200, 201, 204]:
                try: return response.json() if response.text else {}
                except: return {}
            return None
        except:
            return None
    
    def obtener_mi_oferta(self, sku_oferta: str) -> Optional[Dict]:
        endpoint = "/offers"
        params = {"shop_id": self.shop_id, "sku": sku_oferta, "states": "ACTIVE"}
        result = self._request("GET", endpoint, params=params)
        if result and "offers" in result and len(result["offers"]) > 0:
            return result["offers"][0]
        return None

    def obtener_ofertas_por_producto(self, product_id: str) -> List[Dict]:
        endpoint = "/products/offers"
        params = {"product_ids": product_id}
        result = self._request("GET", endpoint, params=params)
        if result and "products" in result and len(result["products"]) > 0:
            return result["products"][0].get("offers", [])
        return []
        
    def actualizar_precio_oferta(self, sku_vendedor: str, nuevo_precio: float, stock_actual: int) -> bool:
        endpoint = "/offers"
        payload = {"offers": [{"shop_sku": sku_vendedor, "price": float(nuevo_precio), "quantity": int(stock_actual), "update_delete": "update"}]}
        result = self._request("POST", endpoint, json=payload)
        return result is not None

# ==========================================
# GOOGLE SHEETS
# ==========================================
class GoogleSheetsHandler:
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        self.spreadsheet_id = spreadsheet_id
        self.gc = self._autenticar(credentials_path)
        self.sheet = self.gc.open_by_key(spreadsheet_id)
        self.hoja_principal = self.sheet.worksheet("Hoja 1")
        try:
            self.hoja_rivales = self.sheet.worksheet("Rivales cop")
        except:
            self.hoja_rivales = self.sheet.add_worksheet("Rivales cop", 1000, 10)
    
    def _autenticar(self, credentials_path: str):
        try:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            credentials = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scopes=scope)
            return gspread.authorize(credentials)
        except Exception as e:
            logger.error(f"❌ Error autenticando Google Sheets: {e}")
            sys.exit(1)
    
    def obtener_skus_activos(self) -> List[Dict]:
        try:
            registros = self.hoja_principal.get_all_records()
            if not registros: return []
            
            skus_validos = []
            for registro in registros:
                estatus = str(registro.get('estatus_coppel', '')).strip().upper()
                if estatus != 'ACTIVO': continue
                
                stock_raw = registro.get('stock_coppel', '')
                try:
                    if stock_raw != '' and stock_raw is not None and float(stock_raw) > 0:
                        skus_validos.append(registro)
                except:
                    continue
            return skus_validos
        except Exception as e:
            return []
    
    def guardar_rival(self, sku_limpio: str, nombre_rival: str, precio_rival: float):
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.hoja_rivales.append_row([timestamp, sku_limpio, nombre_rival, precio_rival])
        except:
            pass

# ==========================================
# LÓGICA PRINCIPAL DE REPRICING
# ==========================================
class MegazordCoppel:
    def __init__(self, mirakl: MiraklCoppel, sheets: GoogleSheetsHandler, db=None):
        self.mirakl = mirakl
        self.sheets = sheets
        self.db = db  
        self.alertas = []

    def sincronizar_inventario(self) -> Tuple[int, int]:
        logger.info("\n" + "="*80)
        logger.info("🔄 SINCRONIZACIÓN DE INVENTARIO DESDE MIRAKL")
        logger.info("="*80)
        try:
            registros = self.sheets.hoja_principal.get_all_records()
            if not registros: return 0, 0
            
            headers = self.sheets.hoja_principal.row_values(1)
            try:
                stock_column_index = headers.index('stock_coppel') + 1 
            except:
                return 0, len(registros)
            
            batch_updates = [] 
            actualizados, errores = 0, 0
            
            for row_index, registro in enumerate(registros, start=2):
                if str(registro.get('estatus_coppel', '')).strip().upper() != 'ACTIVO':
                    continue

                sku_coppel = registro.get('sku_coppel', '')
                if not sku_coppel:
                    errores += 1
                    continue
                
                try:
                    mi_oferta = self.mirakl.obtener_mi_oferta(sku_coppel)
                    stock_mirakl = mi_oferta.get('quantity', 0) if mi_oferta else 0
                    batch_updates.append((row_index, stock_column_index, stock_mirakl))
                    actualizados += 1
                except:
                    errores += 1
                    continue
            
            if batch_updates:
                try:
                    cell_list = []
                    for row_num, col_num, valor in batch_updates:
                        cell = self.sheets.hoja_principal.cell(row_num, col_num)
                        cell.value = valor
                        cell_list.append(cell)
                    self.sheets.hoja_principal.update_cells(cell_list)
                except:
                    pass
            
            return actualizados, errores
        except:
            return 0, 0
    
    def procesar_sku(self, sku_dict: Dict) -> bool:
        """Procesa UN SKU según estrategia de Guerrilla."""
        
        # 🧹 TRADUCTOR UNIVERSAL (BD <-> Sheets)
        sku_coppel = sku_dict.get('sku') or sku_dict.get('sku_coppel', '')
        sku_limpio = sku_dict.get('sku_limpio') or sku_coppel
        costo_odoo = float(sku_dict.get('costo_odoo', 0))
        minimo = float(sku_dict.get('precio_minimo') or sku_dict.get('minimo_coppel', 0))
        maximo = float(sku_dict.get('precio_maximo') or sku_dict.get('maximo_coppel', 0))
        
        # OBTENER CATALOGO_ID DE LA BD (Para relacionar historiales)
        catalogo_id = sku_dict.get('id')
        if self.db and not catalogo_id:
            try:
                resultado = self.db.execute_query(
                    "SELECT id FROM catalogo_maestro_v3 WHERE sku_coppel = %s LIMIT 1",
                    (sku_coppel,),
                    fetch=True
                )
                if resultado:
                    catalogo_id = resultado[0]['id']
            except Exception as e:
                pass
        
        logger.info(f"\n🔍 Procesando: {enmascarar_sku(sku_coppel)}")
        
        # ==========================================
        # ALERTAS CRÍTICAS
        # ==========================================
        mi_oferta = self.mirakl.obtener_mi_oferta(sku_coppel)
        mi_stock_actual = mi_oferta.get("quantity", 0) if mi_oferta else 0
        
        if mi_stock_actual <= 0 and self.db and catalogo_id:
            try:
                self.db.registrar_alerta(catalogo_id, 'COPPEL', 'STOCK_CRITICO', 'ALTA', f"Stock crítico (0). SKU: {sku_coppel}")
            except: pass
        
        if minimo < 50 and self.db and catalogo_id:
            try:
                self.db.registrar_alerta(catalogo_id, 'COPPEL', 'PRECIO_BAJO', 'MEDIA', f"Precio mínimo anormal: ${minimo}")
            except: pass
        
        # ==========================================
        # ANÁLISIS DE MERCADO
        # ==========================================
        if not mi_oferta:
            logger.warning(f"⚠️ Oferta no encontrada en Mirakl para {sku_coppel}")
            return False

        mi_precio_actual = float(mi_oferta.get("price", 0))
        product_id = mi_oferta.get("product_id") or mi_oferta.get("product_sku")
        
        if not product_id: return False

        ofertas_crudas = self.mirakl.obtener_ofertas_por_producto(product_id)
        
        ofertas = []
        for o in ofertas_crudas:
            nombre_rival = o.get("shop_name") or o.get("shop", {}).get("name", "Desconocido")
            precio_rival = float(o.get("price", 0))
            stock = int(o.get("quantity") or o.get("total_quantity") or 0)
            es_activa = str(o.get("active", "true")).lower() == "true"
            
            if precio_rival > 10 and es_activa:
                es_nosotros = (str(COPPEL_SHOP_ID) in str(o.get("shop_id", ""))) or ("NUARE" in str(nombre_rival).upper())
                if stock > 0 or es_nosotros:
                    ofertas.append(o)
        
        if not ofertas: return False
        
        ofertas = sorted(ofertas, key=lambda x: float(x.get("price", 999999)))
        precio_bb = float(ofertas[0].get("price", 0))
        ganador_bb = ofertas[0].get("shop", {}).get("name", "Desconocido")
        ganador_enmascarado = enmascarar_vendedor(ganador_bb)
        
        logger.info(f"   👑 BuyBox: ${precio_bb} ({ganador_enmascarado})")
        
        # GUARDAR RIVALES EN BD Y SHEETS
        for idx, oferta in enumerate(ofertas[:5]):
            nombre = oferta.get("shop_name") or oferta.get("shop", {}).get("name", "Desconocido")
            nombre = str(nombre).replace("=", "").strip()
            precio = float(oferta.get("price", 0))
            
            self.sheets.guardar_rival(sku_limpio, nombre, precio)
            
            if self.db and catalogo_id:
                try:
                    self.db.registrar_rival(catalogo_id, 'COPPEL', nombre, precio, idx+1)
                except: pass
        
        # ==========================================
        # LÓGICA DE COMBATE: GUERRILLA
        # ==========================================
        if "NUARE" not in ganador_enmascarado:
            if precio_bb >= minimo:
                undercut = random.uniform(MIN_UNDERCUT, MAX_UNDERCUT)
                nuevo_precio = float(int(precio_bb - undercut)) + 0.09
                tipo_ataque = "DIRECTO"
            else:
                rivales_viables = [r for r in ofertas if float(r.get("price", 0)) >= minimo and "NUARE" not in str(r.get("shop_name", "")).upper()]
                
                if rivales_viables:
                    precio_objetivo = min([float(r.get("price", 0)) for r in rivales_viables])
                    undercut = random.uniform(MIN_UNDERCUT, MAX_UNDERCUT)
                    nuevo_precio = float(int(precio_objetivo - undercut)) + 0.09
                    tipo_ataque = "GUERRILLA"
                else:
                    logger.info(f"   🛡️ Sin rivales viables en rango.")
                    return False
            
            if nuevo_precio >= minimo and es_precio_rentable(nuevo_precio, costo_odoo, minimo):
                if self.mirakl.actualizar_precio_oferta(sku_coppel, nuevo_precio, stock_actual=mi_stock_actual):
                    ganancia, margen = calcular_rentabilidad_coppel(nuevo_precio, costo_odoo)
                    
                    if self.db and catalogo_id:
                        try:
                            self.db.registrar_historial(catalogo_id, 'COPPEL', mi_precio_actual, nuevo_precio, mi_stock_actual, tipo_ataque, "EJECUTADO", f"Ganancia: ${ganancia}")
                        except: pass
                    
                    self.alertas.append(f"⚔️ *{tipo_ataque}*\nSKU: {sku_limpio}\nBuyBox: ${precio_bb}\nNuevo: ${nuevo_precio}")
                    logger.info(f"   ✅ Ataque ejecutado: ${nuevo_precio}")
                    return True
            else:
                logger.info(f"   ⚠️ Precio no rentable: ${nuevo_precio}")
        
        else:
            if len(ofertas) > 1:
                precio_segundo = float(ofertas[1].get("price", 0))
                if precio_segundo > precio_bb:
                    nuevo_precio = float(int(precio_segundo - 5)) + 0.09
                    nuevo_precio, fue_limitado = aplicar_freno_15_porciento(mi_precio_actual, nuevo_precio)

                    if nuevo_precio > precio_bb:
                        if self.mirakl.actualizar_precio_oferta(sku_coppel, nuevo_precio, stock_actual=mi_stock_actual):
                            ganancia, margen = calcular_rentabilidad_coppel(nuevo_precio, costo_odoo)
                            
                            if self.db and catalogo_id:
                                try:
                                    self.db.registrar_historial(catalogo_id, 'COPPEL', mi_precio_actual, nuevo_precio, mi_stock_actual, "Optimización Margen", "EJECUTADO", f"Freno 15%: {fue_limitado}")
                                except: pass
                            
                            mensaje = f"🚀 *Optimización*\nSKU: {sku_limpio}\nNuevo: ${nuevo_precio}"
                            if fue_limitado: mensaje += f"\n🛡️ (Freno aplicado)"
                            self.alertas.append(mensaje)
                            logger.info(f"   ✅ Margen optimizado: ${nuevo_precio}")
                            return True
        return False
    
    def procesar_lote(self, skus: List[Dict], max_workers: int = 3):
        logger.info(f"\n🚀 Iniciando procesamiento de {len(skus)} SKUs...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.procesar_sku, sku): sku.get('sku_limpio', 'Desconocido') for sku in skus}
            resultados = 0
            for future in as_completed(futures):
                try:
                    if future.result(): resultados += 1
                except Exception as e:
                    logger.error(f"❌ Error procesando {futures[future]}: {e}")
        
        logger.info(f"✅ {resultados}/{len(skus)} SKUs procesados")
        if self.alertas:
            enviar_mensaje_telegram("🟡 *MEGAZORD COPPEL*\n\n" + "\n\n".join(self.alertas) + f"\n\n🏁 Cambios: {resultados}")

# ==========================================
# MAIN
# ==========================================
def main():
    logger.info("="*80)
    logger.info("🟡 MEGAZORD COPPEL INICIADO")
    logger.info("="*80)

    if not COPPEL_API_KEY or not SPREADSHEET_ID:
        logger.error("❌ Credenciales COPPEL o SPREADSHEET_ID no configuradas")
        sys.exit(1)
    
    try:
        try:
            db = DbManager()
            logger.info("✅ Conexión a PostgreSQL establecida")
        except Exception as e:
            logger.warning(f"⚠️ BD no disponible: {e}")
            db = None

        mirakl = MiraklCoppel(COPPEL_API_KEY, COPPEL_BASE_URL, COPPEL_SHOP_ID)
        sheets = GoogleSheetsHandler(GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID)
        megazord = MegazordCoppel(mirakl, sheets, db)
        
    except Exception as e:
        logger.error(f"❌ Error inicializando: {e}")
        sys.exit(1)
    
    logger.info("\n🔄 Iniciando sincronización de inventario...")
    megazord.sincronizar_inventario()
    
    if db:
        logger.info("📥 Obteniendo SKUs de PostgreSQL...")
        try:
            skus_activos = db.obtener_skus_activos('coppel')
            if not skus_activos:
                logger.warning("⚠️ Sin SKUs en BD, usando Google Sheets (Fallback)...")
                skus_activos = sheets.obtener_skus_activos()
        except Exception as e:
            logger.warning(f"⚠️ Error conectando a BD: {e}, usando Fallback...")
            skus_activos = sheets.obtener_skus_activos()
    else:
        logger.warning("⚠️ BD desconectada, usando Google Sheets (Fallback)...")
        skus_activos = sheets.obtener_skus_activos()
    
    if not skus_activos:
        logger.warning("⚠️ Sin SKUs activos para procesar")
        return
    
    megazord.procesar_lote(skus_activos, max_workers=3)
    
    logger.info("\n" + "="*80)
    logger.info("🏁 MEGAZORD COPPEL COMPLETADO")
    logger.info("="*80)

if __name__ == "__main__":
    main()
