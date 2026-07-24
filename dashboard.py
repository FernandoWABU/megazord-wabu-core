#!/usr/bin/env python3
# ==========================================
# MEGAZORD WAR ROOM - DASHBOARD ENTERPRISE V2.2
# Centro de Comando Ejecutivo con BI Real-Time
# MULTI-TENANT ARCHITECTURE INTEGRATED
# ✅ COMPATIBLE CON STREAMLIT CLOUD
# ==========================================

import streamlit as st
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import logging
from typing import Dict, List, Tuple, Optional
import time
import requests
import hashlib
import hmac

# ==========================================
# 🔧 CONFIGURACIÓN & LOGGING
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(message)s'
)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="🤖 MEGAZORD War Room",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 🎨 DARK MODE CSS
# ==========================================

DARK_MODE_CSS = """
<style>
    :root {
        --primary-dark: #0a0e27;
        --secondary-dark: #1a1f3a;
        --accent-blue: #00d9ff;
    }
    
    body, .main { background-color: #0a0e27 !important; color: #ffffff !important; }
    
    .stContainer { background-color: #0a0e27 !important; }
    
    [data-testid="stSidebar"] {
        background-color: #1a1f3a !important;
        border-right: 2px solid #00d9ff !important;
    }
    
    [data-testid="stSidebar"] span, 
    [data-testid="stSidebar"] div { 
        color: #ffffff !important; 
    }
    
    [data-testid="stSidebar"] h1, 
    [data-testid="stSidebar"] h2, 
    [data-testid="stSidebar"] h3 { 
        color: #00d9ff !important; 
        font-weight: bold;
    }

    h1, h2, h3 { color: #00d9ff; text-shadow: 0 0 10px rgba(0, 217, 255, 0.3); font-weight: 700; }
    .metric-box { background: linear-gradient(135deg, #1a1f3a 0%, #0f2540 100%); border: 2px solid #00d9ff; border-radius: 8px; padding: 20px; box-shadow: 0 0 20px rgba(0, 217, 255, 0.2); transition: all 0.3s ease; }
    .stButton > button { background: linear-gradient(135deg, #00d9ff 0%, #1db954 100%); color: #0a0e27; border: none; border-radius: 6px; font-weight: bold; padding: 12px 24px; transition: all 0.3s ease; text-transform: uppercase; }
    .stDataFrame { background: #1a1f3a; border: 2px solid #00d9ff; }
</style>
"""
st.markdown(DARK_MODE_CSS, unsafe_allow_html=True)

# ==========================================
# 🔐 SEGURIDAD & BD POSTGRESQL (SQLAlchemy)
# ==========================================

class AuthManager:
    def __init__(self):
        # 🛡️ Parche de Seguridad: Hasheo en memoria
        password_plain = os.getenv("DASHBOARD_PASSWORD", "megazord2025")
        self.password_hash = hashlib.sha256(password_plain.encode()).hexdigest()
        self.session_timeout = 3600

    def login(self, password: str) -> bool:
        # 🛡️ Comparación segura contra Timing Attacks
        input_hash = hashlib.sha256(password.encode()).hexdigest()
        if hmac.compare_digest(input_hash, self.password_hash):
            st.session_state['authenticated'] = True
            st.session_state['auth_time'] = time.time()
            return True
        return False

    def is_authenticated(self) -> bool:
        if 'auth_time' not in st.session_state: return False
        if time.time() - st.session_state['auth_time'] > self.session_timeout:
            st.session_state['authenticated'] = False
            return False
        return st.session_state.get('authenticated', False)

class PostgreSQLManager:
    """
    ✅ COMPATIBLE CON STREAMLIT CLOUD
    Usa SQLAlchemy en lugar de psycopg2
    """
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None
        self._initialize_engine()

    def _initialize_engine(self):
        try:
            # ✅ SQLAlchemy es compatible con Streamlit Cloud
            self.engine = create_engine(
                self.database_url, 
                poolclass=NullPool,  # ← Mejor para Streamlit
                connect_args={"connect_timeout": 5}
            )
            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ Conexión PostgreSQL: EXITOSA")
        except Exception as e:
            logger.error(f"❌ Error conectando a PostgreSQL: {e}")
            self.engine = None

    def execute_query(self, query: str, params: dict = None) -> pd.DataFrame:
        try:
            if self.engine is None:
                return pd.DataFrame()
            
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params or {})
                columns = result.keys()
                data = result.fetchall()
                return pd.DataFrame(data, columns=columns)
        except Exception as e:
            logger.error(f"❌ Error en query: {e}")
            return pd.DataFrame()

    def execute_update(self, query: str, params: dict = None) -> bool:
        try:
            if self.engine is None:
                return False
            
            with self.engine.begin() as conn:
                conn.execute(text(query), params or {})
            logger.info("✅ Update ejecutado")
            return True
        except Exception as e:
            logger.error(f"❌ Error en update: {e}")
            return False

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    st.error("❌ DATABASE_URL no configurada en Streamlit Secrets")
    st.stop()

db = PostgreSQLManager(DATABASE_URL)
auth = AuthManager()

# ==========================================
# 📊 CACHED DATA FUNCTIONS (Mejor performance)
# ==========================================

@st.cache_data(ttl=300)
def get_historial_precios(days: int = 7) -> pd.DataFrame:
    query = """
    SELECT h.fecha_hora AS created_at, h.sku_interno, c.sku_limpio,
           h.precio_rival AS precio_ant, h.nuestro_precio AS precio_nuv,
           h.stock, h.posicion, h.buybox AS resultado, h.id_cuenta
    FROM historial_precios h 
    LEFT JOIN catalogo_maestro_v3 c ON h.sku_interno = c.sku_interno
    WHERE h.fecha_hora >= :fecha_desde 
    ORDER BY h.fecha_hora DESC 
    LIMIT 50000
    """
    return db.execute_query(query, {
        "fecha_desde": datetime.now() - timedelta(days=days)
    })

@st.cache_data(ttl=300)
def get_catalogo_maestro() -> pd.DataFrame:
    query = """
    SELECT id, sku_limpio, sku_interno, sku_liverpool, sku_walmart, sku_coppel,
           precio_minimo, precio_maximo, costo_odoo, estatus, id_cuenta,
           COALESCE(regla_estrategia, '1. Gladiador') AS regla
    FROM catalogo_maestro_v3 
    ORDER BY sku_limpio
    """
    return db.execute_query(query)

@st.cache_data(ttl=600)
def get_cuentas_disponibles() -> list:
    df_ctas = db.execute_query("SELECT id_cuenta FROM cuentas_liverpool ORDER BY id_cuenta ASC")
    return df_ctas['id_cuenta'].tolist() if not df_ctas.empty else ['LVP_01']

# ==========================================
# 📱 LOGIN PAGE
# ==========================================

def show_login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br><br><div style='text-align: center;'><h1 style='color: #00d9ff;'>⚡ MEGAZORD WAR ROOM</h1></div><br><br>", unsafe_allow_html=True)
        password = st.text_input("🔐 Contraseña de Acceso", type="password")
        if st.button("🚀 ACCESO RESTRINGIDO", use_container_width=True):
            if auth.login(password): 
                st.rerun()
            else: 
                st.error("❌ Contraseña incorrecta")

# ==========================================
# 🔐 DASHBOARD PRIVADO
# ==========================================

def show_private_dashboard():
    
    # 📍 SIDEBAR FILTER
    with st.sidebar:
        st.markdown("---")
        st.subheader("📍 Selección de Tienda")
        
        res_ctas = db.execute_query("SELECT id_cuenta, nombre_descriptivo FROM cuentas_liverpool ORDER BY id_cuenta ASC")
        opciones = ["🌍 TODAS LAS CUENTAS"]
        map_cuentas = {"🌍 TODAS LAS CUENTAS": "TODAS"}
        
        if not res_ctas.empty:
            for _, r in res_ctas.iterrows():
                lbl = f"✅ {r['nombre_descriptivo']} ({r['id_cuenta']})"
                opciones.append(lbl)
                map_cuentas[lbl] = r['id_cuenta']
        
        cta_label = st.selectbox("Filtrar por cuenta:", opciones)
        id_cuenta_filtro = map_cuentas[cta_label]

        # ==========================================
        # 📊 MÉTRICAS PRINCIPALES
        # ==========================================
        st.markdown("---")
        st.subheader("📊 Métricas en Vivo")
        
        # SKUs Activos
        df_skus = db.execute_query("SELECT COUNT(*) as total FROM catalogo_maestro_v3 WHERE estatus = 'ACTIVO'")
        total_skus = df_skus['total'].values[0] if not df_skus.empty else 0
        
        # Últimas actualizaciones
        df_updates = db.execute_query("SELECT COUNT(*) as total FROM historial_precios WHERE fecha_hora > NOW() - INTERVAL '1 hour'")
        updates_hora = df_updates['total'].values[0] if not df_updates.empty else 0
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🎯 SKUs Activos", total_skus)
        with col2:
            st.metric("⚡ Updates/Hora", updates_hora)

    # ==========================================
    # 📊 MAIN CONTENT
    # ==========================================
    
    st.markdown("<h1 style='text-align: center; color: #00d9ff;'>⚡ MEGAZORD WAR ROOM - Centro de Control</h1>", unsafe_allow_html=True)
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "📈 Histórico", "📋 Catálogo", "⚙️ Configuración"])
    
    with tab1:
        st.subheader("📊 Resumen en Vivo")
        
        df_hist = get_historial_precios(days=1)
        if not df_hist.empty:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Precios Revisados", len(df_hist))
            with col2:
                st.metric("Ajustes Realizados", df_hist[df_hist['precio_nuv'] != df_hist['precio_ant']].shape[0])
            with col3:
                buybox_count = (df_hist['resultado'] == 'GANADOR').sum()
                st.metric("Ganando Buybox", buybox_count)
            with col4:
                st.metric("% Ganancia", f"{(buybox_count/len(df_hist)*100):.1f}%")
            
            # Gráfico de precios
            st.markdown("### 📈 Evolución de Precios (Últimas 24h)")
            fig = px.line(df_hist.head(100), x='created_at', y=['precio_ant', 'precio_nuv'], 
                         title='Comparación: Rival vs Nuestro Precio')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("📭 No hay datos disponibles")
    
    with tab2:
        st.subheader("📈 Análisis Histórico")
        days = st.slider("Días a mostrar:", 1, 30, 7)
        df_hist = get_historial_precios(days=days)
        
        if not df_hist.empty:
            st.dataframe(df_hist, use_container_width=True)
            
            # Descargar CSV
            csv = df_hist.to_csv(index=False)
            st.download_button(
                label="📥 Descargar CSV",
                data=csv,
                file_name=f"historial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
    
    with tab3:
        st.subheader("📋 Catálogo Maestro")
        df_cat = get_catalogo_maestro()
        
        if not df_cat.empty:
            # Filtros
            col1, col2 = st.columns(2)
            with col1:
                status_filter = st.multiselect("Estado:", df_cat['estatus'].unique(), default=df_cat['estatus'].unique())
            with col2:
                sku_filter = st.text_input("Buscar SKU:")
            
            # Aplicar filtros
            df_filtered = df_cat[df_cat['estatus'].isin(status_filter)]
            if sku_filter:
                df_filtered = df_filtered[df_filtered['sku_limpio'].str.contains(sku_filter, case=False, na=False)]
            
            st.dataframe(df_filtered, use_container_width=True)
    
    with tab4:
        st.subheader("⚙️ Configuración")
        
        if st.button("🔄 Limpiar Caché"):
            st.cache_data.clear()
            st.success("✅ Caché limpiado")
        
        if st.button("🚪 Cerrar Sesión"):
            st.session_state['authenticated'] = False
            st.rerun()

# ==========================================
# 🚀 MAIN LOGIC
# ==========================================

def main():
    if auth.is_authenticated():
        show_private_dashboard()
    else:
        show_login_page()

if __name__ == "__main__":
    main()
