#!/usr/bin/env python3
# ==========================================
# MEGAZORD WAR ROOM - DASHBOARD V3.0
# Admin + Executive Mode (Dual Interface)
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
    .stButton > button { background: linear-gradient(135deg, #00d9ff 0%, #1db954 100%); color: #0a0e27; border: none; border-radius: 6px; font-weight: bold; padding: 12px 24px; transition: all 0.3s ease; text-transform: uppercase; }
    .stDataFrame { background: #1a1f3a; border: 2px solid #00d9ff; }
    
    .metric-value { color: #00d9ff; font-size: 2.5em; font-weight: bold; }
    .metric-label { color: #ffffff; font-size: 1em; }
</style>
"""
st.markdown(DARK_MODE_CSS, unsafe_allow_html=True)

# ==========================================
# 🔐 SEGURIDAD & BD POSTGRESQL
# ==========================================

class AuthManager:
    def __init__(self):
        password_plain = os.getenv("DASHBOARD_PASSWORD", "123")
        self.password_hash = hashlib.sha256(password_plain.encode()).hexdigest()
        self.session_timeout = 3600

    def login(self, password: str) -> bool:
        input_hash = hashlib.sha256(password.encode()).hexdigest()
        if hmac.compare_digest(input_hash, self.password_hash):
            st.session_state['authenticated'] = True
            st.session_state['auth_time'] = time.time()
            return True
        return False

    def is_authenticated(self) -> bool:
        if 'auth_time' not in st.session_state: 
            return False
        if time.time() - st.session_state['auth_time'] > self.session_timeout:
            st.session_state['authenticated'] = False
            return False
        return st.session_state.get('authenticated', False)

class PostgreSQLManager:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None
        self._initialize_engine()

    def _initialize_engine(self):
        try:
            self.engine = create_engine(
                self.database_url, 
                poolclass=NullPool,
                connect_args={"connect_timeout": 10, "options": "-c statement_timeout=30000"}
            )
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ Conexión PostgreSQL: EXITOSA")
        except Exception as e:
            logger.error(f"❌ Error conectando a PostgreSQL: {e}")
            self.engine = None

    def execute_query(self, query: str, params: dict = None) -> pd.DataFrame:
        try:
            if self.engine is None:
                st.warning("⚠️ Conexión a BD no disponible")
                return pd.DataFrame()
            
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params or {})
                columns = result.keys()
                data = result.fetchall()
                return pd.DataFrame(data, columns=columns)
        except Exception as e:
            logger.error(f"❌ Error en query: {e}")
            st.warning(f"⚠️ Error consultando BD: {str(e)[:100]}")
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
# 📊 CACHED DATA FUNCTIONS
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
    LIMIT 5000
    """
    return db.execute_query(query, {"fecha_desde": datetime.now() - timedelta(days=days)})

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
        st.markdown("<br><br><div style='text-align: center;'><h1 style='color: #00d9ff;'>⚡ MEGAZORD WAR ROOM</h1></div><br>", unsafe_allow_html=True)
        
        st.markdown("<div style='text-align: center;'><h3>¿Quién eres?</h3></div>", unsafe_allow_html=True)
        
        col_exec, col_admin = st.columns(2, gap="large")
        
        # OPCIÓN 1: EXECUTIVE (SIN CONTRASEÑA)
        with col_exec:
            st.markdown("### 👁️ Ejecutivo")
            st.markdown("*Ver datos (solo lectura)*")
            if st.button("📊 Acceder como Ejecutivo", use_container_width=True, key="btn_exec"):
                st.session_state['authenticated'] = False
                st.session_state['admin_mode'] = False
                st.session_state['executive_mode'] = True
                st.success("✅ Acceso como Ejecutivo")
                st.rerun()
        
        # OPCIÓN 2: ADMIN (CON CONTRASEÑA)
        with col_admin:
            st.markdown("### 🔐 Administrador")
            st.markdown("*Acceso completo (editar)*")
            
            password = st.text_input("🔐 Contraseña", type="password", key="admin_password")
            if st.button("🚀 Acceder como Admin", use_container_width=True, key="btn_admin"):
                if password == "":
                    st.error("❌ Ingresa la contraseña")
                elif auth.login(password):
                    st.session_state['admin_mode'] = True
                    st.session_state['executive_mode'] = False
                    st.session_state['authenticated'] = True
                    st.success("✅ Admin mode activado")
                    st.rerun()
                else:
                    st.error("❌ Contraseña incorrecta")

# ==========================================
# 🎯 EXECUTIVE VIEW (Read-Only)
# ==========================================

def show_executive_dashboard():
    st.markdown("<h1 style='text-align: center; color: #00d9ff;'>⚡ MEGAZORD - Vista Ejecutiva</h1>", unsafe_allow_html=True)
    
    with st.sidebar:
        st.markdown("---")
        st.subheader("👁️ Modo: Lectura")
        st.markdown("*No se puede editar. Solo visualización.*")
        st.markdown("---")
        
        cuentas = get_cuentas_disponibles()
        opciones = ["🌍 TODAS LAS CUENTAS"] + [f"✅ {cta}" for cta in cuentas]
        map_cuentas = {"🌍 TODAS LAS CUENTAS": "TODAS"}
        for cta in cuentas:
            map_cuentas[f"✅ {cta}"] = cta
        
        cta_label = st.selectbox("Filtrar por cuenta:", opciones)
        id_cuenta_filtro = map_cuentas[cta_label]
        
        st.markdown("---")
        st.subheader("📊 Métricas en Vivo")
        
        try:
            df_skus = db.execute_query("SELECT COUNT(*) as total FROM catalogo_maestro_v3 WHERE estatus = 'ACTIVO'")
            total_skus = df_skus['total'].values[0] if not df_skus.empty else 0
        except:
            total_skus = 0
        
        try:
            df_updates = db.execute_query("SELECT COUNT(*) as total FROM historial_precios WHERE fecha_hora > NOW() - INTERVAL '1 hour'")
            updates_hora = df_updates['total'].values[0] if not df_updates.empty else 0
        except:
            updates_hora = 0
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🎯 SKUs Activos", total_skus)
        with col2:
            st.metric("⚡ Updates/Hora", updates_hora)
    
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📈 Histórico", "📋 Catálogo"])
    
    with tab1:
        st.subheader("📊 Resumen en Vivo")
        
        with st.spinner("⏳ Cargando datos..."):
            df_hist = get_historial_precios(days=1)
        
        if not df_hist.empty:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Precios Revisados", len(df_hist))
            with col2:
                ajustes = df_hist[df_hist['precio_nuv'] != df_hist['precio_ant']].shape[0]
                st.metric("Ajustes Realizados", ajustes)
            with col3:
                buybox_count = (df_hist['resultado'] == 'GANADOR').sum()
                st.metric("Ganando Buybox", buybox_count)
            with col4:
                porcentaje = (buybox_count/len(df_hist)*100) if len(df_hist) > 0 else 0
                st.metric("% Ganancia", f"{porcentaje:.1f}%")
            
            st.markdown("### 📈 Evolución de Precios (Últimas 24h)")
            try:
                fig = px.line(df_hist.head(100), x='created_at', y=['precio_ant', 'precio_nuv'], 
                             title='Comparación: Rival vs Nuestro Precio',
                             labels={'price': 'Precio ($)', 'created_at': 'Hora'})
                fig.update_layout(template="plotly_dark", height=400)
                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.warning(f"⚠️ No se pudo graficar: {e}")
        else:
            st.info("📭 No hay datos disponibles")
    
    with tab2:
        st.subheader("📈 Análisis Histórico")
        days = st.slider("Días a mostrar:", 1, 30, 7)
        
        with st.spinner("⏳ Cargando histórico..."):
            df_hist = get_historial_precios(days=days)
        
        if not df_hist.empty:
            st.dataframe(df_hist, use_container_width=True, height=400)
            
            csv = df_hist.to_csv(index=False)
            st.download_button(
                label="📥 Descargar CSV",
                data=csv,
                file_name=f"historial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        else:
            st.info("📭 No hay datos para descargar")
    
    with tab3:
        st.subheader("📋 Catálogo Maestro")
        
        with st.spinner("⏳ Cargando catálogo..."):
            df_cat = get_catalogo_maestro()
        
        if not df_cat.empty:
            col1, col2 = st.columns(2)
            with col1:
                status_filter = st.multiselect("Estado:", df_cat['estatus'].unique(), default=df_cat['estatus'].unique())
            with col2:
                sku_filter = st.text_input("Buscar SKU:")
            
            df_filtered = df_cat[df_cat['estatus'].isin(status_filter)]
            if sku_filter:
                df_filtered = df_filtered[df_filtered['sku_limpio'].str.contains(sku_filter, case=False, na=False)]
            
            st.dataframe(df_filtered, use_container_width=True, height=400)
        else:
            st.info("📭 No hay catálogo disponible")

# ==========================================
# 🔐 ADMIN VIEW (Full Control)
# ==========================================

def show_admin_dashboard():
    st.markdown("<h1 style='text-align: center; color: #00d9ff;'>⚡ MEGAZORD War Room - Admin Panel</h1>", unsafe_allow_html=True)
    
    with st.sidebar:
        st.markdown("---")
        st.subheader("🔐 Modo: Administrador")
        st.markdown("*Acceso completo. Puedes editar.*")
        st.markdown("---")
        
        if st.button("🚪 Cerrar Sesión"):
            st.session_state['authenticated'] = False
            st.session_state['admin_mode'] = False
            st.rerun()
        
        st.markdown("---")
        st.subheader("📍 Selección de Tienda")
        
        cuentas = get_cuentas_disponibles()
        opciones = ["🌍 TODAS LAS CUENTAS"] + [f"✅ {cta}" for cta in cuentas]
        map_cuentas = {"🌍 TODAS LAS CUENTAS": "TODAS"}
        for cta in cuentas:
            map_cuentas[f"✅ {cta}"] = cta
        
        cta_label = st.selectbox("Filtrar por cuenta:", opciones)
        id_cuenta_filtro = map_cuentas[cta_label]
        
        st.markdown("---")
        st.subheader("📊 Métricas en Vivo")
        
        try:
            df_skus = db.execute_query("SELECT COUNT(*) as total FROM catalogo_maestro_v3 WHERE estatus = 'ACTIVO'")
            total_skus = df_skus['total'].values[0] if not df_skus.empty else 0
        except:
            total_skus = 0
        
        try:
            df_updates = db.execute_query("SELECT COUNT(*) as total FROM historial_precios WHERE fecha_hora > NOW() - INTERVAL '1 hour'")
            updates_hora = df_updates['total'].values[0] if not df_updates.empty else 0
        except:
            updates_hora = 0
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🎯 SKUs Activos", total_skus)
        with col2:
            st.metric("⚡ Updates/Hora", updates_hora)
    
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "📈 Histórico", "📋 Catálogo", "⚙️ Configuración"])
    
    with tab1:
        st.subheader("📊 Resumen en Vivo")
        
        with st.spinner("⏳ Cargando datos..."):
            df_hist = get_historial_precios(days=1)
        
        if not df_hist.empty:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Precios Revisados", len(df_hist))
            with col2:
                ajustes = df_hist[df_hist['precio_nuv'] != df_hist['precio_ant']].shape[0]
                st.metric("Ajustes Realizados", ajustes)
            with col3:
                buybox_count = (df_hist['resultado'] == 'GANADOR').sum()
                st.metric("Ganando Buybox", buybox_count)
            with col4:
                porcentaje = (buybox_count/len(df_hist)*100) if len(df_hist) > 0 else 0
                st.metric("% Ganancia", f"{porcentaje:.1f}%")
            
            st.markdown("### 📈 Evolución de Precios (Últimas 24h)")
            try:
                fig = px.line(df_hist.head(100), x='created_at', y=['precio_ant', 'precio_nuv'], 
                             title='Comparación: Rival vs Nuestro Precio',
                             labels={'price': 'Precio ($)', 'created_at': 'Hora'})
                fig.update_layout(template="plotly_dark", height=400)
                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.warning(f"⚠️ No se pudo graficar: {e}")
        else:
            st.info("📭 No hay datos disponibles")
    
    with tab2:
        st.subheader("📈 Análisis Histórico")
        days = st.slider("Días a mostrar:", 1, 30, 7)
        
        with st.spinner("⏳ Cargando histórico..."):
            df_hist = get_historial_precios(days=days)
        
        if not df_hist.empty:
            st.dataframe(df_hist, use_container_width=True, height=400)
            
            csv = df_hist.to_csv(index=False)
            st.download_button(
                label="📥 Descargar CSV",
                data=csv,
                file_name=f"historial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        else:
            st.info("📭 No hay datos para descargar")
    
    with tab3:
        st.subheader("📋 Catálogo Maestro")
        
        with st.spinner("⏳ Cargando catálogo..."):
            df_cat = get_catalogo_maestro()
        
        if not df_cat.empty:
            col1, col2 = st.columns(2)
            with col1:
                status_filter = st.multiselect("Estado:", df_cat['estatus'].unique(), default=df_cat['estatus'].unique())
            with col2:
                sku_filter = st.text_input("Buscar SKU:")
            
            df_filtered = df_cat[df_cat['estatus'].isin(status_filter)]
            if sku_filter:
                df_filtered = df_filtered[df_filtered['sku_limpio'].str.contains(sku_filter, case=False, na=False)]
            
            st.dataframe(df_filtered, use_container_width=True, height=400)
        else:
            st.info("📭 No hay catálogo disponible")
    
    with tab4:
        st.subheader("⚙️ Configuración")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔄 Limpiar Caché"):
                st.cache_data.clear()
                st.success("✅ Caché limpiado")
        
        with col2:
            if st.button("🔄 Recargar Datos"):
                st.rerun()
        
        with col3:
            if st.button("🚪 Cerrar Sesión"):
                st.session_state['authenticated'] = False
                st.session_state['admin_mode'] = False
                st.rerun()
        
        st.markdown("---")
        st.info("""
        ### 📊 Información del Dashboard
        - **Versión:** 3.0 (Dual Mode)
        - **Status:** ✅ Activo
        - **Base de datos:** PostgreSQL
        - **Actualización:** Cada 5 minutos (caché)
        - **Modo Admin:** Con contraseña
        - **Modo Executive:** Sin contraseña (solo lectura)
        """)

# ==========================================
# 🚀 MAIN LOGIC
# ==========================================

def main():
    # Inicializar session state
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "admin_mode" not in st.session_state:
        st.session_state.admin_mode = False
    if "executive_mode" not in st.session_state:
        st.session_state.executive_mode = False
    
    # Mostrar vista correspondiente
    if st.session_state.admin_mode and st.session_state.authenticated:
        show_admin_dashboard()
    elif st.session_state.executive_mode:
        show_executive_dashboard()
    else:
        show_login_page()

if __name__ == "__main__":
    main()
