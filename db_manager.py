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
        """Devuelve los SKUs activos usando el ID numérico como llave maestra"""
        col_estatus = f"estatus_{marketplace}" if marketplace != 'liverpool' else "estatus"
        query = f"""
            SELECT id, sku_{marketplace} as sku, precio_minimo, precio_maximo, costo_odoo, stock 
            FROM catalogo_maestro_v3 
            WHERE {col_estatus} = 'ACTIVO' AND sku_{marketplace} IS NOT NULL
        """
        return self.execute_query(query, fetch=True)

    def registrar_historial(self, catalogo_id, marketplace, precio_ant, precio_nuv, stock, regla, resultado, notas=""):
        query = """
            INSERT INTO historial_operaciones 
            (catalogo_id, marketplace, precio_anterior, precio_nuevo, stock_momento, regla_aplicada, resultado, notas)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        return self.execute_query(query, (catalogo_id, marketplace, precio_ant, precio_nuv, stock, regla, resultado, notas))

    def actualizar_precio(self, catalogo_id, nuevo_precio, stock):
        """Actualiza el catálogo. El trigger de SQL cambiará el updated_at automáticamente."""
        # Se requiere lógica para saber en qué marketplace se actualiza, pero a nivel base de datos:
        query = "UPDATE catalogo_maestro_v3 SET stock = %s WHERE id = %s"
        return self.execute_query(query, (stock, catalogo_id))