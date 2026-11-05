# Conexión a PostgreSQL: una sola vez por servidor, con pool de conexiones reutilizable.
import os
import logging
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


class PostgreSQLManager:
    def __init__(self, database_url: str):
        self.engine = None
        try:
            self.engine = create_engine(
                database_url,
                pool_size=3, max_overflow=2, pool_pre_ping=True, pool_recycle=240,
                connect_args={"connect_timeout": 10, "options": "-c statement_timeout=30000"},
            )
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            logger.error(f"Error conectando a PostgreSQL: {e}")
            self.engine = None

    def execute_query(self, query: str, params: dict = None) -> pd.DataFrame:
        if self.engine is None:
            return pd.DataFrame()
        try:
            with self.engine.connect() as conn:
                res = conn.execute(text(query), params or {})
                return pd.DataFrame(res.fetchall(), columns=list(res.keys()))
        except Exception as e:
            logger.error(f"Error en query: {e}")
            st.warning(f"⚠️ Error consultando la base: {str(e)[:120]}")
            return pd.DataFrame()


@st.cache_resource(show_spinner=False)
def _crear(url: str):
    return PostgreSQLManager(url)


def get_db() -> PostgreSQLManager:
    url = os.getenv("DATABASE_URL")
    if not url:
        st.error("❌ DATABASE_URL no está configurada en los Secrets de Streamlit")
        st.stop()
    for prefijo in ("postgresql://", "postgres://"):
        if url.startswith(prefijo):
            url = "postgresql+psycopg://" + url[len(prefijo):]
    return _crear(url)
