#!/usr/bin/env python3
# ==========================================
# PUENTE ODOO -> POSTGRESQL (DBEAVER)
# ==========================================
# Función: Extraer costos de Odoo, calcular
# SKUs compuestos y actualizar catalogo_maestro_v3
# ==========================================

import os
import xmlrpc.client
import psycopg2
import logging
from dotenv import load_dotenv

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

def calcular_costo_real(sku_limpio, costos_odoo):
    """
    Cerebro Calculador: Descifra combos y multiplicadores.
    - Caso A: "HNAU" -> Busca HNAU
    - Caso B: "HNAU/2" -> Busca HNAU y multiplica x2
    - Caso C: "HNAU/HNAUV" -> Busca ambos y suma sus costos
    Si no encuentra algo, vale $0.
    """
    if not sku_limpio:
        return 0.0

    partes = [p.strip().upper() for p in str(sku_limpio).split('/')]

    # Caso B: Multiplicador (Ej. HNAU/2)
    # Si son exactamente 2 partes y la segunda es un número
    if len(partes) == 2 and partes[1].isdigit():
        base_sku = partes[0]
        multiplicador = int(partes[1])
        costo_base = costos_odoo.get(base_sku, 0.0)
        return costo_base * multiplicador

    # Caso A y C: SKU único o Combo de SKUs (Ej. HNAU o HNAU/HNAUV/HNAUB)
    costo_total = 0.0
    for parte in partes:
        costo_total += costos_odoo.get(parte, 0.0)
        
    return costo_total

def sincronizar_costos():
    logger.info("🚀 Iniciando Sincronización de Costos: ODOO -> PostgreSQL")
    load_dotenv()

    # 1. CREDENCIALES
    ODOO_URL = os.getenv("ODOO_URL")
    ODOO_DB = os.getenv("ODOO_DB")
    ODOO_USER = os.getenv("ODOO_USER")
    ODOO_PASSWORD = os.getenv("ODOO_API_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL")

    if not all([ODOO_USER, ODOO_PASSWORD, DATABASE_URL]):
        logger.error("❌ Faltan credenciales de Odoo o PostgreSQL en el entorno.")
        return

    # ==========================================
    # FASE 1: EXTRAER COSTOS BÁSICOS DE ODOO
    # ==========================================
    costos_dict = {}
    try:
        logger.info("🔵 Conectando a Odoo (Autenticando)...")
        common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(ODOO_URL))
        uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
        
        if not uid:
            logger.error("❌ Autenticación fallida en Odoo. Revisa Usuario/API Key o el nombre de la DB.")
            return
            
        logger.info("✅ Autenticación Odoo exitosa. Descargando catálogo matriz...")
        models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(ODOO_URL))
        
        # Traer todos los productos activos de Odoo
        productos_odoo = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'product.product', 'search_read',
            [[('active', '=', True)]],
            {'fields': ['default_code', 'standard_price']}
        )
        
        for p in productos_odoo:
            sku = str(p.get('default_code', '')).strip().upper()
            costo = float(p.get('standard_price', 0.0))
            if sku:
                costos_dict[sku] = costo
                
        logger.info(f"📦 {len(costos_dict)} productos base leídos desde Odoo.")
        
    except Exception as e:
        logger.error(f"❌ Error conectando o leyendo de Odoo: {e}")
        return

    # ==========================================
    # FASE 2: CALCULAR E INYECTAR EN DBEAVER
    # ==========================================
    conn = None
    try:
        logger.info("🔵 Conectando a PostgreSQL (DBeaver)...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Leemos TODOS los registros por su id, usando sku_limpio
        cursor.execute("SELECT id, sku_limpio, costo_odoo FROM catalogo_maestro_v3 WHERE sku_limpio IS NOT NULL")
        catalogo_db = cursor.fetchall()
        
        actualizaciones = []
        for db_id, sku_limpio, costo_actual in catalogo_db:
            # Calculamos el costo con la función matemática que resuelve combos y multiplicadores
            nuevo_costo = calcular_costo_real(sku_limpio, costos_dict)
            
            # Si el costo calculado es diferente al que ya tiene DBeaver, lo actualizamos
            # (Incluso si el nuevo costo es $0 porque no existe en Odoo)
            if round(float(costo_actual or 0), 2) != round(nuevo_costo, 2):
                actualizaciones.append((nuevo_costo, db_id))
        
        if actualizaciones:
            logger.info(f"⚙️ Aplicando {len(actualizaciones)} actualizaciones de costo en DBeaver...")
            query_update = "UPDATE catalogo_maestro_v3 SET costo_odoo = %s WHERE id = %s"
            cursor.executemany(query_update, actualizaciones)
            conn.commit()
            logger.info(f"🎉 ¡Sincronización Exitosa! {len(actualizaciones)} filas actualizadas (incluyendo IDs duplicados).")
        else:
            logger.info("✅ Todos los costos en PostgreSQL ya están al día con Odoo. No hay cambios.")
            
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"❌ Error actualizando PostgreSQL: {e}")
    finally:
        if conn:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    sincronizar_costos()