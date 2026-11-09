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
    codigo_por_id = {}  # id de producto Odoo -> código (para el stock por almacén)
    stock_filas = []    # (codigo, ubicación, cantidad, reservado)
    nombres_dict = {}   # {CODIGO: (nombre, costo)} -> tabla odoo_productos (para mostrar nombres en el dashboard)
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
            {'fields': ['id', 'default_code', 'name', 'standard_price']}
        )
        
        for p in productos_odoo:
            sku = str(p.get('default_code', '')).strip().upper()
            costo = float(p.get('standard_price', 0.0))
            if sku:
                costos_dict[sku] = costo
            if p.get('default_code'):   # solo productos con código real (Odoo manda False si no tiene)
                nombres_dict[sku] = (str(p.get('name') or '').strip(), costo)
                codigo_por_id[p['id']] = sku
                
        logger.info(f"📦 {len(costos_dict)} productos base leídos desde Odoo.")

        # Stock por ubicación (solo lectura). Si falla, NO afecta la sincronización de costos.
        try:
            quants = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD, 'stock.quant', 'search_read',
                [[('location_id.usage', '=', 'internal')]],
                {'fields': ['product_id', 'location_id', 'quantity', 'reserved_quantity']}
            )
            for q in quants:
                pid = q['product_id'][0] if q.get('product_id') else None
                codigo = codigo_por_id.get(pid)
                if not codigo or not q.get('location_id'):
                    continue
                stock_filas.append((codigo, str(q['location_id'][1]).strip(), float(q.get('quantity') or 0), float(q.get('reserved_quantity') or 0)))
            logger.info(f"🏬 {len(stock_filas)} registros de stock por ubicación leídos desde Odoo.")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo leer el stock de Odoo (los costos siguen normal): {e}")
        
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

        # Guarda nombres reales de Odoo para el dashboard (si falla, NO afecta la sincronización de costos)
        try:
            cursor.execute("""CREATE TABLE IF NOT EXISTS odoo_productos (
                               default_code VARCHAR PRIMARY KEY, nombre TEXT, costo NUMERIC,
                               actualizado TIMESTAMP DEFAULT NOW())""")
            filas_nombres = [(codigo, n, c) for codigo, (n, c) in nombres_dict.items()]
            cursor.executemany("""INSERT INTO odoo_productos (default_code, nombre, costo, actualizado)
                                   VALUES (%s, %s, %s, NOW())
                                   ON CONFLICT (default_code) DO UPDATE
                                   SET nombre = EXCLUDED.nombre, costo = EXCLUDED.costo, actualizado = NOW()""", filas_nombres)
            conn.commit()
            logger.info(f"📛 {len(filas_nombres)} nombres de producto guardados en odoo_productos")
        except Exception as e:
            conn.rollback()
            logger.warning(f"⚠️ No se pudieron guardar los nombres de Odoo (los costos siguen normal): {e}")

        # Stock por ubicación: se reemplaza completo en cada corrida (si no se pudo leer, se conserva el anterior)
        if stock_filas:
            try:
                cursor.execute("""CREATE TABLE IF NOT EXISTS odoo_stock (
                                   default_code VARCHAR NOT NULL, ubicacion VARCHAR NOT NULL, cantidad NUMERIC, reservado NUMERIC,
                                   actualizado TIMESTAMP DEFAULT NOW(), PRIMARY KEY (default_code, ubicacion))""")
                cursor.execute("DELETE FROM odoo_stock")
                agregado = {}
                for codigo, ubic, cant, res in stock_filas:
                    a = agregado.setdefault((codigo, ubic), [0.0, 0.0]); a[0] += cant; a[1] += res
                cursor.executemany("INSERT INTO odoo_stock (default_code, ubicacion, cantidad, reservado, actualizado) VALUES (%s, %s, %s, %s, NOW())",
                                   [(c, u, v[0], v[1]) for (c, u), v in agregado.items()])
                conn.commit()
                logger.info(f"🏬 {len(agregado)} filas guardadas en odoo_stock")
            except Exception as e:
                conn.rollback()
                logger.warning(f"⚠️ No se pudo guardar el stock de Odoo (los costos siguen normal): {e}")

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