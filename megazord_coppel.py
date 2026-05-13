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
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('megazord_coppel.log', encoding='utf-8')
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
print(f"🔑 API: {COPPEL_BASE_URL}")
print("="*80 + "\n")

# ==========================================
# FUNCIONES DE ENMASCARAMIENTO
# ==========================================
def enmascarar_sku(sku_real):
    """Enmascara SKU en logs públicos."""
    hash_sku = hashlib.md5(str(sku_real).encode()).hexdigest()[:6].upper()
    return f"SKU_{hash_sku}"


def enmascarar_precio(precio_real):
    """Enmascara precio en logs públicos."""
    try:
        return f"${int(float(precio_real))}.XX"
    except:
        return "$X.XX"


def enmascarar_vendedor(nombre_vendedor):
    """Enmascara vendedor - detecta si somos nosotros."""
    if not nombre_vendedor:
        return "Desconocido"
    if TIENDA_DETECTABLE in str(nombre_vendedor).upper():
        return "🟡 NOSOTROS"
    return "RIVAL"

# ==========================================
# RATE LIMITER
# ==========================================
class RateLimiter:
    """Limita llamadas a API."""
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
    """Crea sesión HTTP con reintentos automáticos."""
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
    """
    Calcula rentabilidad según reglas de Coppel.
    
    Retorna: (ganancia_neta, margen_porcentaje)
    """
    costo_con_iva = costo_odoo * IVA_ODOO
    comision = precio_venta * COMISION_PLATAFORMA
    
    ganancia_neta = precio_venta - costo_con_iva - comision - COSTO_GUIA_FIJO
    margen_porcentaje = (ganancia_neta / precio_venta * 100) if precio_venta > 0 else 0
    
    return round(ganancia_neta, 2), round(margen_porcentaje, 1)


def es_precio_rentable(precio_venta: float, costo_odoo: float, minimo: float) -> bool:
    """Verifica si un precio es rentable."""
    ganancia, _ = calcular_rentabilidad_coppel(precio_venta, costo_odoo)
    return ganancia > 0 and precio_venta >= minimo

# ==========================================
# FUNCIONES DE SEGURIDAD (FRENO 15%)
# ==========================================
def aplicar_freno_15_porciento(precio_actual: float, precio_propuesto: float) -> Tuple[float, bool]:
    """
    Freno de mano: incremento máximo 15%.
    """
    if precio_actual <= 0:
        return precio_propuesto, False
    
    limite_seguro = round(precio_actual * (1 + FRENO_SUBIDA_PORCENTAJE), 2)
    
    if precio_propuesto > limite_seguro:
        logger.warning(
            f"🛡️ FRENO 15%: Incremento limitado\n"
            f"   Precio actual: ${precio_actual}\n"
            f"   Propuesto: ${precio_propuesto}\n"
            f"   Límite (15%): ${limite_seguro}"
        )
        return limite_seguro, True
    
    return precio_propuesto, False

# ==========================================
# FUNCIONES DE TELEGRAM
# ==========================================
def enviar_mensaje_telegram(mensaje: str) -> bool:
    """Envía mensaje a Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ Credenciales de Telegram no configuradas")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            logger.info("📤 Mensaje Telegram enviado")
            return True
        else:
            logger.warning(f"⚠️ Telegram error: HTTP {response.status_code}")
            return False
    
    except Exception as e:
        logger.error(f"❌ Error enviando Telegram: {e}")
        return False

# ==========================================
# API MIRAKL - OPERACIONES
# ==========================================
class MiraklCoppel:
    """Cliente REST para API Mirakl de Coppel."""
    
    def __init__(self, api_key: str, base_url: str, shop_id: str):
        self.api_key = api_key
        self.base_url = base_url
        self.shop_id = shop_id
        self.session = crear_session_mirakl()
        self.headers = {
            "Authorization": f"{api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        """Realiza request a Mirakl con manejo de errores."""
        rate_limiter.wait()
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url, headers=self.headers, timeout=30, **kwargs)
            elif method.upper() == "PUT":
                response = self.session.put(url, headers=self.headers, timeout=30, **kwargs)
            elif method.upper() == "POST":
                response = self.session.post(url, headers=self.headers, timeout=30, **kwargs)
            else:
                logger.error(f"❌ Método HTTP no soportado: {method}")
                return None
            
            # Log de respuesta
            logger.debug(f"{method} {url} → HTTP {response.status_code}")
            
            if response.status_code in [200, 201, 204]:
                try:
                    return response.json() if response.text else {}
                except:
                    return {}
            else:
                logger.error(f"❌ Mirakl error HTTP {response.status_code}: {response.text}")
                return None
        
        except requests.Timeout:
            logger.error(f"❌ Timeout en {endpoint}")
            return None
        except Exception as e:
            logger.error(f"❌ Error en request: {e}")
            return None
    
    def obtener_mi_oferta(self, sku_oferta: str) -> Optional[Dict]:
        """Paso 1: Obtiene NUESTRA oferta usando nuestro SKU interno de Excel."""
        endpoint = "/offers"
        params = {
            "shop_id": self.shop_id,
            "sku": sku_oferta,  # Mirakl usa 'sku' para buscar el SKU del vendedor
            "states": "ACTIVE"
        }
        result = self._request("GET", endpoint, params=params)
        if result and "offers" in result and len(result["offers"]) > 0:
            return result["offers"][0]
        return None

    def obtener_ofertas_por_producto(self, product_id: str) -> List[Dict]:
        """Paso 2: Obtiene TODAS las ofertas (competencia + nuestra) usando el radar global."""
        # Cambiamos /offers por /products/offers (El radar de competencia)
        endpoint = "/products/offers"
        params = {
            "product_ids": product_id
        }
        result = self._request("GET", endpoint, params=params)
        
        # El radar devuelve los datos agrupados por producto
        if result and "products" in result and len(result["products"]) > 0:
            return result["products"][0].get("offers", [])
            
        return []
        
    def actualizar_precio_oferta(self, sku_vendedor: str, nuevo_precio: float, stock_actual: int) -> bool:
        """Actualiza precio y mantiene stock para evitar que Mirakl lo ponga en 0."""
        endpoint = "/offers"
        payload = {
            "offers": [
                {
                    "shop_sku": sku_vendedor,
                    "price": float(nuevo_precio),
                    "quantity": int(stock_actual), # Enviamos el stock para proteger la publicación
                    "update_delete": "update"
                }
            ]
        }
        result = self._request("POST", endpoint, json=payload)
        return result is not None
        
        if result is not None:
            logger.info(f"✅ Precio actualizado en Mirakl a: ${nuevo_precio}")
            return True
        else:
            logger.error(f"❌ Fallo al actualizar precio en la API")
            return False

# ==========================================
# GOOGLE SHEETS
# ==========================================
class GoogleSheetsHandler:
    """Maneja interacción con Google Sheets."""
    
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        self.spreadsheet_id = spreadsheet_id
        self.gc = self._autenticar(credentials_path)
        self.sheet = self.gc.open_by_key(spreadsheet_id)
        self.hoja_principal = self.sheet.worksheet("Hoja 1")
        
        try:
            self.hoja_rivales = self.sheet.worksheet("Rivales cop")
        except:
            logger.warning("⚠️ Hoja 'Rivales cop' no existe. Creándola...")
            self.hoja_rivales = self.sheet.add_worksheet("Rivales cop", 1000, 10)
    
    def _autenticar(self, credentials_path: str):
        """Autentica con Google Sheets."""
        try:
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            credentials = ServiceAccountCredentials.from_json_keyfile_name(
                credentials_path,
                scopes=scope
            )
            
            return gspread.authorize(credentials)
        except Exception as e:
            logger.error(f"❌ Error autenticando Google Sheets: {e}")
            sys.exit(1)
    
    def obtener_skus_activos(self) -> List[Dict]:
        """
        Obtiene SKUs ACTIVOS de Coppel CON STOCK DISPONIBLE.
        
        FILTROS (ambos deben cumplirse):
        1. estatus_coppel == 'ACTIVO'
        2. stock_coppel > 0 (con manejo robusto de vacíos/inválidos)
        
        RETORNA:
            Lista de diccionarios con SKUs válidos
            Lista vacía si hay error o ninguno cumple
        
        MANEJO DE ERRORES:
        - stock_coppel vacío → Ignorar SKU
        - stock_coppel = "0" → Ignorar SKU
        - stock_coppel = "ABC" (texto) → Ignorar SKU
        - stock_coppel = "-5" (negativo) → Ignorar SKU
        - stock_coppel = "10.5" (decimal) → Aceptar si > 0
        """
        try:
            # Leer todos los registros
            registros = self.hoja_principal.get_all_records()
            
            if not registros:
                logger.warning("⚠️ Google Sheets vacío o sin registros")
                return []
            
            # Aplicar filtros
            skus_validos = []
            skus_rechazados = 0
            
            for registro in registros:
                # FILTRO 1: Validar estatus
                estatus = str(registro.get('estatus_coppel', '')).strip().upper()
                
                if estatus != 'ACTIVO':
                    skus_rechazados += 1
                    continue
                
                # FILTRO 2: Validar stock > 0
                stock_raw = registro.get('stock_coppel', '')
                stock_valido = False
                
                try:
                    # Intentar convertir a float
                    if stock_raw == '' or stock_raw is None:
                        # Celda vacía
                        stock_valido = False
                    else:
                        stock_valor = float(stock_raw)
                        stock_valido = stock_valor > 0
                
                except (ValueError, TypeError):
                    # Celda tiene texto no convertible o tipo inválido
                    stock_valido = False
                
                if not stock_valido:
                    skus_rechazados += 1
                    continue
                
                # SKU pasa AMBOS filtros
                skus_validos.append(registro)
            
            # Logging
            logger.info(
                f"📋 Filtrado: {len(skus_validos)} ACTIVOS con stock "
                f"({skus_rechazados} rechazados sin stock/inactivos)"
            )
            
            return skus_validos
        
        except Exception as e:
            logger.error(f"❌ Error obteniendo SKUs: {e}")
            return []
    
    def guardar_rival(self, sku_limpio: str, nombre_rival: str, precio_rival: float):
        """Guarda un rival escaneado en 'Rivales cop'."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fila = [timestamp, sku_limpio, nombre_rival, precio_rival]
            
            self.hoja_rivales.append_row(fila)
            
        except Exception as e:
            logger.warning(f"⚠️ Error guardando rival: {e}")

    def actualizar_stock_batch(self, batch_updates: List[Tuple[int, int, int]]) -> bool:
        """Actualiza múltiples celdas de stock en una sola operación rápida."""
        try:
            if not batch_updates: return True
            cell_list = []
            for row_num, col_num, valor in batch_updates:
                cell = self.hoja_principal.cell(row_num, col_num)
                cell.value = valor
                cell_list.append(cell)
            self.hoja_principal.update_cells(cell_list)
            return True
        except Exception as e:
            logger.error(f"❌ Error en actualizar_stock_batch: {e}")
            return False

# ==========================================
# LÓGICA PRINCIPAL DE REPRICING
# ==========================================
class MegazordCoppel:
    """Motor principal de repricing Guerrilla."""
    
    def __init__(self, mirakl: MiraklCoppel, sheets: GoogleSheetsHandler):
        self.mirakl = mirakl
        self.sheets = sheets
        self.alertas = []

    def sincronizar_inventario(self) -> Tuple[int, int]:
        """
        Sincroniza el inventario (stock) desde Mirakl a Google Sheets.
        """
        logger.info("\n" + "="*80)
        logger.info("🔄 SINCRONIZACIÓN DE INVENTARIO DESDE MIRAKL")
        logger.info("="*80)
        
        try:
            # PASO 1: Leer TODOS los registros (no solo activos)
            registros = self.sheets.hoja_principal.get_all_records()
            
            if not registros:
                logger.warning("⚠️ Google Sheets vacío")
                return 0, 0
            
            # PASO 2: Obtener encabezados para localizar columna stock_coppel
            headers = self.sheets.hoja_principal.row_values(1)
            
            try:
                stock_column_index = headers.index('stock_coppel') + 1  # +1 porque gspread usa 1-indexing
            except ValueError:
                logger.error("❌ Columna 'stock_coppel' no encontrada en headers")
                return 0, len(registros)
            
            # PASO 3: Preparar batch de actualizaciones
            batch_updates = []  # Lista de (row_number, stock_value)
            actualizados = 0
            errores = 0
            
            for row_index, registro in enumerate(registros, start=2):  # Comienza en fila 2
                # 🚀 MAGIA: Saltar inmediatamente si no está ACTIVO
                if str(registro.get('estatus_coppel', '')).strip().upper() != 'ACTIVO':
                    continue

                sku_coppel = registro.get('sku_coppel', '')
                sku_limpio = registro.get('sku_limpio', '')
                
                if not sku_coppel:
                    logger.debug(f"⏭️  Fila {row_index}: Sin SKU Coppel")
                    errores += 1
                    continue
                
                try:
                    # Consultar Mirakl
                    mi_oferta = self.mirakl.obtener_mi_oferta(sku_coppel)
                    
                    # Extraer quantity con fallback a 0
                    if mi_oferta:
                        stock_mirakl = mi_oferta.get('quantity', 0)
                    else:
                        stock_mirakl = 0
                    
                    # Agregar al batch
                    batch_updates.append((row_index, stock_column_index, stock_mirakl))
                    actualizados += 1
                    
                    logger.debug(f"   ✅ {enmascarar_sku(sku_coppel)}: {stock_mirakl} unidades")
                
                except Exception as e:
                    logger.warning(f"⚠️ Error sincronizando {sku_coppel}: {e}")
                    errores += 1
                    continue
            
            # PASO 4: Ejecutar batch update
            if batch_updates:
                logger.info(f"\n📤 Aplicando {len(batch_updates)} actualizaciones en bloque...")
                
                try:
                    # Preparar celdas para actualizar (formato gspread)
                    cell_list = []
                    
                    for row_num, col_num, valor in batch_updates:
                        cell = self.sheets.hoja_principal.cell(row_num, col_num)
                        cell.value = valor
                        cell_list.append(cell)
                    
                    # Actualizar todas las celdas de una vez
                    self.sheets.hoja_principal.update_cells(cell_list)
                    
                    logger.info(f"✅ {len(batch_updates)} celdas actualizadas exitosamente")
                
                except Exception as e:
                    logger.error(f"❌ Error en batch update: {e}")
                    # Fallback: Intentar actualizaciones individuales
                    logger.warning("⚠️ Intentando actualización individual como fallback...")
                    
                    for row_num, col_num, valor in batch_updates:
                        try:
                            self.sheets.hoja_principal.update_cell(row_num, col_num, valor)
                        except:
                            pass
            
            # PASO 5: Logging final
            logger.info("\n📊 RESULTADO DE SINCRONIZACIÓN")
            logger.info(f"   ✅ Actualizados: {actualizados}")
            logger.info(f"   ❌ Errores: {errores}")
            logger.info(f"   Total procesados: {actualizados + errores}")
            
            return actualizados, errores
        
        except Exception as e:
            logger.error(f"❌ Error fatal en sincronización: {e}")
            return 0, len(registros)
    
    def procesar_sku(self, sku_dict: Dict) -> bool:
        """Procesa UN SKU según estrategia de Guerrilla."""
        
        sku_limpio = sku_dict.get('sku_limpio', '')
        sku_coppel = sku_dict.get('sku_coppel', '')
        costo_odoo = float(sku_dict.get('costo_odoo', 0))
        minimo = float(sku_dict.get('minimo_coppel', 0))
        maximo = float(sku_dict.get('maximo_coppel', 0))
        regla = sku_dict.get('regla_coppel', '1. Gladiador')
        
        logger.info(f"\n🔍 Procesando: {enmascarar_sku(sku_coppel)}")
        
        # 1. OBTENER NUESTRA OFERTA (Para extraer el Product ID global)
        mi_oferta = self.mirakl.obtener_mi_oferta(sku_coppel)
        
        if not mi_oferta:
            logger.warning(f"⚠️ No se encontró oferta ACTIVA para nuestro SKU: {sku_coppel}")
            return False

        mi_oferta_id = mi_oferta.get("offer_id") or mi_oferta.get("id")
        mi_precio_actual = float(mi_oferta.get("price", 0))
        
        # Mirakl puede devolver el ID del producto como 'product_id' o 'product_sku'
        product_id = mi_oferta.get("product_id") or mi_oferta.get("product_sku")
        
        if not product_id:
            logger.warning(f"⚠️ No se pudo extraer el Product ID de Coppel.")
            return False

        # 2. OBTENER TODAS LAS OFERTAS DE LA COMPETENCIA (RADAR GLOBAL)
        ofertas_crudas = self.mirakl.obtener_ofertas_por_producto(product_id)
        
        logger.info(f"   📡 Radar Global devolvió {len(ofertas_crudas)} ofertas totales.")
        
        # 🧹 CAZAFANTASMAS V3: Traductor Universal
        ofertas = []
        for o in ofertas_crudas:
            # En el Radar, el nombre a veces viene directo o adentro de 'shop'
            nombre_rival = o.get("shop_name") or o.get("shop", {}).get("name", "Desconocido")
            precio_rival = float(o.get("price", 0))
            
            stock = int(o.get("quantity") or o.get("total_quantity") or 0)
            es_activa = str(o.get("active", "true")).lower() == "true"
            
            logger.info(f"      - Rival: {nombre_rival} | Precio: ${precio_rival} | Stock: {stock} | Activo: {es_activa}")

            if precio_rival > 10 and es_activa:
                es_nosotros = str(o.get("shop_id", "")) == str(COPPEL_SHOP_ID)
                if stock > 0 or es_nosotros:
                    ofertas.append(o)
        
        if not ofertas:
            logger.warning(f"⚠️ No se encontraron ofertas válidas para procesar en el producto {product_id}")
            return False
        
        # Ordenar por precio (BuyBox es la primera)
        ofertas = sorted(ofertas, key=lambda x: float(x.get("price", 999999)))
        
        # Extraer datos
        precio_bb = float(ofertas[0].get("price", 0))
        ganador_bb = ofertas[0].get("shop", {}).get("name", "Desconocido")
        ganador_enmascarado = enmascarar_vendedor(ganador_bb)
        
        logger.info(f"   👑 BuyBox: ${precio_bb} ({ganador_enmascarado})")
        
        # Guardar rivales en sheets
        for oferta in ofertas[:5]:  # Primeros 5
            nombre = oferta.get("shop", {}).get("name", "Desconocido")
            precio = float(oferta.get("price", 0))
            self.sheets.guardar_rival(sku_limpio, nombre, precio)
        
        # ==========================================
        # LÓGICA DE COMBATE: GUERRILLA
        # ==========================================
        
        if "NUARE" not in ganador_enmascarado:
            # CASO 1: NO TENEMOS LA BUYBOX
            logger.info(f"   ⚠️ No tenemos BuyBox")
            
            if precio_bb >= minimo:
                # BuyBox es defendible: atacar directo
                undercut = random.uniform(MIN_UNDERCUT, MAX_UNDERCUT)
                # ✨ Magia de los .09
                nuevo_precio = float(int(precio_bb - undercut)) + 0.09
                tipo_ataque = "DIRECTO"
            else:
                # 🛡️ Filtrar rivales viables: Que sean rentables Y QUE NO SEAMOS NOSOTROS
                rivales_viables = [
                    r for r in ofertas 
                    if float(r.get("price", 0)) >= minimo 
                    and str(r.get("shop_id", "")) != str(COPPEL_SHOP_ID)
                ]
                
                if rivales_viables:
                    objetivo = min(rivales_viables, key=lambda x: float(x.get("price", 0)))
                    precio_objetivo = float(objetivo.get("price", 0))
                    undercut = random.uniform(MIN_UNDERCUT, MAX_UNDERCUT)
                    # ✨ Magia de los .09
                    nuevo_precio = float(int(precio_objetivo - undercut)) + 0.09
                    tipo_ataque = "GUERRILLA"
                else:
                    logger.info(f"   🛡️ Sin rivales viables")
                    return False
            
            # Validar rentabilidad
            if nuevo_precio >= minimo and es_precio_rentable(nuevo_precio, costo_odoo, minimo):
                # EJECUTAR ATAQUE
                if self.mirakl.actualizar_precio_oferta(sku_coppel, nuevo_precio):
                    ganancia, margen = calcular_rentabilidad_coppel(nuevo_precio, costo_odoo)
                    
                    mensaje = (
                        f"⚔️ *Gladiador {tipo_ataque.title()}*\n"
                        f"SKU: {sku_limpio}\n"
                        f"BuyBox: ${precio_bb}\n"
                        f"Nuevo Precio: ${nuevo_precio}\n"
                        f"Ganancia: ${ganancia} ({margen}%)"
                    )
                    self.alertas.append(mensaje)
                    logger.info(f"   ✅ Ataque ejecutado: ${nuevo_precio}")
                    return True
            else:
                logger.info(f"   ⚠️ Precio no rentable: ${nuevo_precio}")
        
        else:
            # CASO 2: TENEMOS LA BUYBOX
            logger.info(f"   👑 TENEMOS LA BUYBOX")
            
            if len(ofertas) > 1:
                precio_segundo = float(ofertas[1].get("price", 0))
                
                if precio_segundo > precio_bb:
                    # ✨ Magia de los .09 para la subida
                    nuevo_precio = float(int(precio_segundo - 5)) + 0.09
                    
                    # APLICAR FRENO 15%
                    nuevo_precio, fue_limitado = aplicar_freno_15_porciento(
                        mi_precio_actual,
                        nuevo_precio
                    )
                    
                    if nuevo_precio > precio_bb:
                        # EJECUTAR OPTIMIZACIÓN
                        if self.mirakl.actualizar_precio_oferta(sku_coppel, nuevo_precio):
                            ganancia, margen = calcular_rentabilidad_coppel(nuevo_precio, costo_odoo)
                            
                            mensaje = (
                                f"🚀 *Optimización de Margen*\n"
                                f"SKU: {sku_limpio}\n"
                                f"Nuevo Precio: ${nuevo_precio}\n"
                                f"Ganancia: ${ganancia} ({margen}%)"
                            )
                            
                            if fue_limitado:
                                mensaje += f"\n\n🛡️ (Freno 15% aplicado)"
                            
                            self.alertas.append(mensaje)
                            logger.info(f"   ✅ Margen optimizado: ${nuevo_precio}")
                            return True
        
        return False
    
    def procesar_lote(self, skus: List[Dict], max_workers: int = 3):
        """Procesa SKUs en paralelo."""
        logger.info(f"\n🚀 Iniciando procesamiento de {len(skus)} SKUs...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.procesar_sku, sku): sku['sku_limpio']
                for sku in skus
            }
            
            resultados = 0
            for future in as_completed(futures):
                try:
                    if future.result():
                        resultados += 1
                except Exception as e:
                    sku_name = futures[future]
                    logger.error(f"❌ Error procesando {sku_name}: {e}")
        
        logger.info(f"✅ {resultados}/{len(skus)} SKUs procesados exitosamente")
        
        # Enviar alertas a Telegram
        if self.alertas:
            mensaje_final = "🟡 *MEGAZORD COPPEL*\n\n" + "\n\n".join(self.alertas)
            mensaje_final += f"\n\n🏁 Barrido completado ({resultados} cambios)"
            enviar_mensaje_telegram(mensaje_final)

# ==========================================
# MAIN
# ==========================================
def main():
    """Punto de entrada principal."""
    
    logger.info("="*80)
    logger.info("🟡 MEGAZORD COPPEL INICIADO")
    logger.info("="*80)
    
    # Validar credenciales
    if not COPPEL_API_KEY:
        logger.error("❌ COPPEL_API_KEY no configurada")
        sys.exit(1)
    
    if not SPREADSHEET_ID:
        logger.error("❌ COPPEL_SPREADSHEET_ID no configurada")
        sys.exit(1)
    
    # Inicializar clientes
    try:
        mirakl = MiraklCoppel(COPPEL_API_KEY, COPPEL_BASE_URL, COPPEL_SHOP_ID)
        sheets = GoogleSheetsHandler(GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID)
        megazord = MegazordCoppel(mirakl, sheets)
    except Exception as e:
        logger.error(f"❌ Error inicializando: {e}")
        sys.exit(1)
    
    # ========== NUEVO: SINCRONIZAR INVENTARIO ==========
    logger.info("\n🔄 Iniciando sincronización de inventario...")
    actualizados, errores = megazord.sincronizar_inventario()
    
    if actualizados == 0 and errores > 0:
        logger.warning("⚠️ Sincronización completada con errores")
    
    # ========== FIN SINCRONIZACIÓN ==========
    
    # Obtener SKUs activos (DESPUÉS de sincronizar)
    skus_activos = sheets.obtener_skus_activos()
    
    if not skus_activos:
        logger.warning("⚠️ Sin SKUs activos para procesar")
        return
    
    # Procesar en lote
    megazord.procesar_lote(skus_activos, max_workers=3)
    
    logger.info("\n" + "="*80)
    logger.info("🏁 MEGAZORD COPPEL COMPLETADO")
    logger.info("="*80)


if __name__ == "__main__":
    main()
