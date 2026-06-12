#!/usr/bin/env python3
# ==========================================
# MEGAZORD LIVERPOOL - VERSIÓN ENTERPRISE V4
# ==========================================
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
            "userModified": GMAIL_USER,
            "index": 0
        }]
    }]
    
    try:
        if MODO_SIMULACION:
            imprint_simulacion(f"DISPARAR_PRECIO | SKU: {sku_notificacion} | Bajaría a: ${nuevo_precio}")
            return True
            
        logger.info(f"🎯 DISPARAR_PRECIO REAL | SKU: {sku_notificacion} | Bajando a: ${nuevo_precio}")
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
# CEREBRO ESTRATÉGICO MULTI-CUENTA (CON LOGGING FORENSE)
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
        
        # 🔴 DEBUG ESPECIAL PARA EL SKU PROBLEMÁTICO
        if sku_i == "1140609443" or sku_lp == "1140609443":
            logger.info(f"\n{'='*60}")
            logger.info(f"🔴 DEBUG ESPECIAL PARA 1140609443")
            logger.info(f"{'='*60}")
            logger.info(f"precio_actual: {precio_actual}")
            logger.info(f"base_price: {base_price}")
            logger.info(f"cantidad: {cantidad}")
            logger.info(f"offer_id: {offer_id}")
            logger.info(f"token válido: {bool(token) and len(token) > 20}")
            logger.info(f"{'='*60}\n")

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
                logger.info(f"   🎯 [{id_cuenta}] VENTA ESPECIAL | Trinquete + Ruleta + Escudo Sombra")
                
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
                else:
                    pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                    bb_con_motivo = f"{bb} | {motivo}"
                    resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo if precios_rivales else "SIN RIVAL", precio_actual, cantidad, pos, bb_con_motivo, id_cuenta])

            # =========================================
            # REGLAS 1, 4, 5, 6, 7, 8 (FORENSE APLICADO)
            # =========================================
            else:
                logger.info(f"   🎯 REGLA GLADIADOR - Analizando {sku_i}")
                
                if not precios_rivales:
                    logger.info(f"   👑 MONOPOLIO: {sku_i} sin rivales detectados")
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
                    # CÁLCULO DE MARGEN CORREGIDO
                    diferencia_actual = round(float(rival_mas_bajo) - float(precio_actual), 2)
                    logger.debug(f"      diferencia_actual (rival - nuestro): ${diferencia_actual}")
                    
                    if -1.95 <= diferencia_actual <= -1.50:
                        logger.info(f"   ℹ️ MARGEN ÓPTIMO: Ya somos ${abs(diferencia_actual)} más baratos")
                        pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                        resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                    else:
                        baja = round(random.uniform(1.50, 1.95), 2)
                        nuevo_precio = round(rival_mas_bajo - baja, 2)
                        
                        if precio_maximo_regla > 0 and nuevo_precio > precio_maximo_regla:
                            nuevo_precio = precio_maximo_regla
                        
                        if nuevo_precio < precio_minimo_regla:
                            logger.error(f"   ❌ Nuevo precio BAJO mínimo: ${nuevo_precio} < ${precio_minimo_regla}")
                            pos, bb = calcular_posicion_buybox(precios_rivales, precio_actual)
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                            return
                        
                        if float(precio_actual) == float(nuevo_precio):
                            pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                            return
                        
                        logger.info(f"   🚀 DISPARANDO: ${precio_actual} → ${nuevo_precio}")
                        pos, bb = calcular_posicion_buybox(precios_rivales, nuevo_precio)
                        
                        resultado_disparo = disparar_precio(token, offer_id, cantidad, base_price, nuevo_precio, sku_i)
                        
                        if resultado_disparo:
                            logger.info(f"   ✅ DISPARO EXITOSO: ${nuevo_precio}")
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, nuevo_precio, cantidad, pos, bb, id_cuenta])
                        else:
                            logger.error(f"   ❌ DISPARO FALLÓ - disparar_precio() devolvió False")
                            resultados.agregar_historial([hora_actual_str, sku_i, sku_lp, rival_mas_bajo, precio_actual, cantidad, pos, bb, id_cuenta])
                
                else:
                    logger.warning(f"   🛑 RIVAL INDEFENDIBLE: ${rival_mas_bajo} < ${precio_minimo_regla}")
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
                        logger.error(f"   🛑 ALERTA ROJA: Congelado en ${precio_actual}")
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
    """Guarda historial con la columna id_cuenta usando conexión directa a psycopg2"""
    if MODO_SIMULACION:
        imprimir_simulacion(f"SQL OMITIDO | Se guardarían {len(filas)} registros.")
        return
    if not filas:
        return

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
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()

# ==========================================
# FUNCIÓN PRINCIPAL MULTI-TENANT
# ==========================================
def ejecutar_bot():
    logger.info("\n--- INICIANDO MEGAZORD LIVERPOOL V4 ENTERPRISE MULTI-CUENTA ---")
    enviar_telegram("🤖 *Megazord Liverpool V4 (Multi-Cuenta)* despertando...")
    
    # 1. Configurar Conexiones
    try:
        db = DbManager()
    except:
        db = None

    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        gc_connection = gspread.authorize(creds)
    except:
        gc_connection = None

    # 2. LEER CUENTAS ACTIVAS DE LA BÓVEDA
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT id_cuenta, nombre_descriptivo, token_autorizacion, cookie_vip FROM cuentas_liverpool WHERE is_active = TRUE")
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

    # 3. ITERAR POR CADA CUENTA (EL NUEVO MOTOR V8)
    for cuenta in cuentas_activas:
        id_cuenta = cuenta[0]
        nombre_desc = cuenta[1]
        token_cuenta = cuenta[2]

        logger.info(f"\n==========================================")
        logger.info(f"🏪 CARGANDO MOTOR PARA: {nombre_desc} ({id_cuenta})")
        logger.info(f"==========================================")

        if not token_cuenta:
            logger.warning(f"⚠️ La cuenta {id_cuenta} no tiene Token guardado en el Dashboard. Omitiendo...")
            continue

        # Extraer SKUs asignados EXCLUSIVAMENTE a esta cuenta
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

        total_skus_procesados += len(reglas_cuenta)
        logger.info(f"🚀 Iniciando cacería concurrente con 3 hilos para {len(reglas_cuenta)} SKUs de {id_cuenta}...")

        # LANZAR HILOS DE ESTA CUENTA
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

    # 4. GUARDADO FINAL DE TODAS LAS CUENTAS
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

    # Circuit Breaker para Google Sheets (Mantenido por precaución)
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
    enviar_telegram(f"🏁 *BARRIDO MEGAZORD COMPLETADO*\nTotal de SKUs evaluados en todas las cuentas: {total_skus_procesados}")

# ==========================================
# GATILLO DE ARRANQUE
# ==========================================
if __name__ == "__main__":
    ejecutar_bot()
