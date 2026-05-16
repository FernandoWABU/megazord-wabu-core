import os
import time
import logging
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

class DbManager:
    _pool = None

    def __init__(self):
        if DbManager._pool is None:
            self._crear_pool()

    def _crear_pool(self):
        try:
            # Reemplazar con tus variables de entorno reales
            DbManager._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10, # Soporta los 3 bots simultáneos sin problema
                dsn=os.getenv("DATABASE_URL")
            )
            logger.info("✅ Pool de conexiones PostgreSQL inicializado.")
        except Exception as e:
            logger.error(f"❌ Error creando pool de BD: {e}")
            raise

    def execute_query(self, query, params=None, fetch=False, retries=3):
        """Ejecutor blindado con backoff exponencial y auto-rollback en caso de choque de transacciones"""
        delay = 1
        for intento in range(retries):
            conn = None
            try:
                conn = DbManager._pool.getconn()
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(query, params)
                    if fetch:
                        result = cursor.fetchall()
                        conn.commit()
                        return result
                    else:
                        conn.commit()
                        return True
            except psycopg2.OperationalError as e:
                if conn: conn.rollback()
                logger.warning(f"⚠️ Error de conexión (Intento {intento+1}/{retries}): {e}")
                time.sleep(delay)
                delay *= 2  # Backoff exponencial (1s, 2s, 4s)
            except Exception as e:
                if conn: conn.rollback()
                logger.error(f"❌ Error ejecutando query: {e}")
                raise
            finally:
                if conn:
                    DbManager._pool.putconn(conn)
        return False

    # ---------------- MÉTODOS CRUD ESPECÍFICOS ----------------

    def obtener_skus_activos(self, marketplace):
        """Devuelve los SKUs activos mapeando los nombres exactos de catalogo_maestro_v3"""
        if marketplace == 'walmart':
            query = """
                SELECT id, sku_walmart as sku, minimo_wmt as precio_minimo, maximo_wmt as precio_maximo, costo_odoo, stock, url_walmart 
                FROM catalogo_maestro_v3 
                WHERE estatus_wmt = 'ACTIVO' AND sku_walmart IS NOT NULL
            """
        elif marketplace == 'coppel':
            query = """
                SELECT id, sku_coppel as sku, minimo_coppel as precio_minimo, maximo_coppel as precio_maximo, costo_odoo, stock_coppel as stock 
                FROM catalogo_maestro_v3 
                WHERE estatus_coppel = 'ACTIVO' AND sku_coppel IS NOT NULL
            """
        elif marketplace == 'liverpool':
            query = """
                SELECT id, sku_liverpool as sku, precio_minimo, precio_maximo, costo_odoo, stock 
                FROM catalogo_maestro_v3 
                WHERE estatus = 'ACTIVO' AND sku_liverpool IS NOT NULL
            """
        else:
            return []
            
        return self.execute_query(query, fetch=True)

    def registrar_rival(self, catalogo_id, marketplace, nombre_rival, precio_rival, posicion):
        """Inserta los precios de la competencia en la tabla monitoreo_rivales"""
        query = """
            INSERT INTO monitoreo_rivales 
            (catalogo_id, marketplace, nombre_rival, precio_rival, posicion)
            VALUES (%s, %s, %s, %s, %s)
        """
        return self.execute_query(query, (catalogo_id, marketplace, nombre_rival, precio_rival, posicion))

    def actualizar_precio(self, catalogo_id, nuevo_precio, stock):
        """Actualiza el catálogo. El trigger de SQL cambiará el updated_at automáticamente."""
        # Se requiere lógica para saber en qué marketplace se actualiza, pero a nivel base de datos:
        query = "UPDATE catalogo_maestro_v3 SET stock = %s WHERE id = %s"
        return self.execute_query(query, (stock, catalogo_id))
