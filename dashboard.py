#!/usr/bin/env python3
# ==========================================
# MEGAZORD WAR ROOM - DASHBOARD V3.1 FASE 2
# Optimizado + UI Corporativa + Reportes
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
from io import BytesIO

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
# 🎨 DARK MODE CSS + CORPORATIVO
# ==========================================

DARK_MODE_CSS = """
<style>
    :root {
        --primary-dark: #0a0e27;
        --secondary-dark: #1a1f3a;
        --accent-blue: #00d9ff;
        --accent-green: #1db954;
        --accent-red: #ff4757;
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
    
    .metric-card {
        background: linear-gradient(135deg, #1a1f3a 0%, #0f2540 100%);
        border: 2px solid #00d9ff;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 0 20px rgba(0, 217, 255, 0.2);
        text-align: center;
        transition: all 0.3s ease;
    }
    
    .metric-card:hover {
        box-shadow: 0 0 30px rgba(0, 217, 255, 0.4);
        transform: translateY(-5px);
    }
    
    .metric-value { color: #00d9ff; font-size: 2.5em; font-weight: bold; }
    .metric-label { color: #ffffff; font-size: 0.9em; margin-top: 10px; }
    .metric-change { color: #1db954; font-size: 0.8em; margin-top: 5px; }
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
# 📊 CACHED DATA FUNCTIONS (FASE 2: TTL AGRESIVO)
# ==========================================

@st.cache_data(ttl=600)  # 10 minutos - histórico se actualiza menos frecuente
def get_historial_precios(days: int = 7) -> pd.DataFrame:
    query = """
    SELECT h.fecha_hora AS created_at, h.sku_interno, c.sku_limpio,
           h.precio_rival AS precio_ant, h.nuestro_precio AS precio_nuv,
           h.stock, h.posicion, h.buybox AS resultado, h.id_cuenta
    FROM historial_precios h 
    LEFT JOIN catalogo_maestro_v3 c ON h.sku_interno = c.sku_interno
    WHERE h.fecha_hora >= :fecha_desde 
    ORDER BY h.fecha_hora DESC 
    LIMIT 2000
    """
    return db.execute_query(query, {"fecha_desde": datetime.now() - timedelta(days=days)})

@st.cache_data(ttl=3600)  # 1 hora - catálogo cambio poco
def get_catalogo_maestro() -> pd.DataFrame:
    query = """
    SELECT id, sku_limpio, sku_interno, sku_liverpool, sku_walmart, sku_coppel,
           precio_minimo, precio_maximo, costo_odoo, estatus, id_cuenta,
           COALESCE(regla_estrategia, '1. Gladiador') AS regla
    FROM catalogo_maestro_v3 
    ORDER BY sku_limpio
    """
    return db.execute_query(query)

@st.cache_data(ttl=120)  # 2 minutos - métricas en vivo
def get_metricas_vivas() -> Dict:
    try:
        df_skus = db.execute_query("SELECT COUNT(*) as total FROM catalogo_maestro_v3 WHERE estatus = 'ACTIVO'")
        total_skus = df_skus['total'].values[0] if not df_skus.empty else 0
        
        df_updates = db.execute_query("SELECT COUNT(*) as total FROM historial_precios WHERE fecha_hora > NOW() - INTERVAL '1 hour'")
        updates_hora = df_updates['total'].values[0] if not df_updates.empty else 0
        
        df_buybox = db.execute_query("SELECT COUNT(*) as total FROM historial_precios WHERE buybox = 'GANADOR' AND fecha_hora > NOW() - INTERVAL '1 hour'")
        buybox_hora = df_buybox['total'].values[0] if not df_buybox.empty else 0
        
        return {
            'total_skus': total_skus,
            'updates_hora': updates_hora,
            'buybox_hora': buybox_hora
        }
    except:
        return {'total_skus': 0, 'updates_hora': 0, 'buybox_hora': 0}

@st.cache_data(ttl=3600)
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
        
        with col_exec:
            st.markdown("### 👁️ Ejecutivo")
            st.markdown("*Ver datos (solo lectura)*")
            if st.button("📊 Acceder como Ejecutivo", use_container_width=True, key="btn_exec"):
                st.session_state['authenticated'] = False
                st.session_state['admin_mode'] = False
                st.session_state['executive_mode'] = True
                st.success("✅ Acceso como Ejecutivo")
                st.rerun()
        
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
# 🎯 EXECUTIVE VIEW (Optimizado + UI Corporativa)
# ==========================================

def show_executive_dashboard():
    st.markdown("<h1 style='text-align: center; color: #00d9ff;'>⚡ MEGAZORD - Vista Ejecutiva</h1>", unsafe_allow_html=True)
    
    with st.sidebar:
        st.markdown("---")
        st.subheader("👁️ Modo: Lectura")
        st.markdown("*No se puede editar. Solo visualización.*")
        st.markdown("---")
        
        if st.button("🚪 Cerrar Sesión"):
            st.session_state['authenticated'] = False
            st.session_state['admin_mode'] = False
            st.session_state['executive_mode'] = False
            st.rerun()
        
        st.markdown("---")
        st.subheader("📊 Métricas en Vivo")
        
        with st.spinner("⏳ Cargando métricas..."):
            metricas = get_metricas_vivas()
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🎯 SKUs Activos", metricas['total_skus'])
        with col2:
            st.metric("⚡ Updates/Hora", metricas['updates_hora'])
    
    # FASE 2.2: TABS CON LAZY LOADING
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard Ejecutivo", "📈 Análisis Histórico", "📋 Catálogo", "📥 Reportes"])
    
    # ==========================================
    # TAB 1: DASHBOARD EJECUTIVO (UI CORPORATIVA)
    # ==========================================
    with tab1:
        st.subheader("📊 Resumen Ejecutivo")
        
        with st.spinner("⏳ Cargando dashboard..."):
            df_hist = get_historial_precios(days=1)
        
        if not df_hist.empty:
            # FASE 2.2: KPIs en tarjetas hermosas
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class='metric-card'>
                    <div class='metric-value'>{len(df_hist)}</div>
                    <div class='metric-label'>Precios Revisados</div>
                    <div class='metric-change'>Últimas 24h</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                ajustes = df_hist[df_hist['precio_nuv'] != df_hist['precio_ant']].shape[0]
                st.markdown(f"""
                <div class='metric-card'>
                    <div class='metric-value'>{ajustes}</div>
                    <div class='metric-label'>Ajustes Realizados</div>
                    <div class='metric-change'>{ajustes/len(df_hist)*100:.1f}% del total</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                buybox_count = (df_hist['resultado'] == 'GANADOR').sum()
                st.markdown(f"""
                <div class='metric-card'>
                    <div class='metric-value'>{buybox_count}</div>
                    <div class='metric-label'>Ganando Buybox</div>
                    <div class='metric-change'>{buybox_count/len(df_hist)*100:.1f}% ganancia</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                stock_promedio = df_hist['stock'].mean() if 'stock' in df_hist.columns else 0
                st.markdown(f"""
                <div class='metric-card'>
                    <div class='metric-value'>{stock_promedio:.0f}</div>
                    <div class='metric-label'>Stock Promedio</div>
                    <div class='metric-change'>Unidades disponibles</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            
            # FASE 2.2: Gráficos ejecutivos mejorados
            col_graph1, col_graph2 = st.columns(2)
            
            with col_graph1:
                st.markdown("### 📈 Evolución de Precios (24h)")
                try:
                    df_sorted = df_hist.sort_values('created_at')
                    fig = px.line(df_sorted.head(100), x='created_at', y=['precio_ant', 'precio_nuv'],
                                 title='Nuestro Precio vs Rival',
                                 labels={'price': 'Precio ($)', 'created_at': 'Hora'})
                    fig.update_layout(template="plotly_dark", height=350, showlegend=True)
                    fig.update_traces(line=dict(width=2.5))
                    st.plotly_chart(fig, use_container_width=True)
                except Exception as e:
                    st.warning(f"⚠️ Error al graficar: {e}")
            
            with col_graph2:
                st.markdown("### 🎯 Distribución de Resultados")
                try:
                    resultado_counts = df_hist['resultado'].value_counts()
                    colors = ['#1db954', '#ff4757', '#ffa502']
                    fig = px.pie(values=resultado_counts.values, names=resultado_counts.index,
                                title='Ganador vs Competencia',
                                color_discrete_sequence=colors)
                    fig.update_layout(template="plotly_dark", height=350)
                    st.plotly_chart(fig, use_container_width=True)
                except Exception as e:
                    st.warning(f"⚠️ Error al graficar: {e}")
        else:
            st.info("📭 No hay datos disponibles")
    
    # ==========================================
    # TAB 2: ANÁLISIS HISTÓRICO (LAZY LOADING)
    # ==========================================
    with tab2:
        st.subheader("📈 Análisis Histórico")
        
        col1, col2 = st.columns(2)
        with col1:
            days = st.slider("Días a mostrar:", 1, 30, 7)
        with col2:
            show_data = st.checkbox("Ver tabla de datos", value=False)
        
        with st.spinner("⏳ Cargando análisis..."):
            df_hist = get_historial_precios(days=days)
        
        if not df_hist.empty:
            if show_data:
                st.dataframe(df_hist, use_container_width=True, height=400)
            
            col_down1, col_down2 = st.columns(2)
            
            with col_down1:
                csv = df_hist.to_csv(index=False)
                st.download_button(
                    label="📥 Descargar CSV",
                    data=csv,
                    file_name=f"historial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            
            with col_down2:
                excel_buffer = BytesIO()
                with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                    df_hist.to_excel(writer, sheet_name='Histórico', index=False)
                excel_buffer.seek(0)
                st.download_button(
                    label="📊 Descargar Excel",
                    data=excel_buffer.getvalue(),
                    file_name=f"historial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.info("📭 No hay datos para descargar")
    
    # ==========================================
    # TAB 3: CATÁLOGO (LAZY LOADING)
    # ==========================================
    with tab3:
        st.subheader("📋 Catálogo Maestro")
        
        with st.spinner("⏳ Cargando catálogo..."):
            df_cat = get_catalogo_maestro()
        
        if not df_cat.empty:
            col1, col2, col3 = st.columns(3)
            with col1:
                status_filter = st.multiselect("Estado:", df_cat['estatus'].unique(), default=df_cat['estatus'].unique())
            with col2:
                sku_filter = st.text_input("Buscar SKU:")
            with col3:
                regla_filter = st.multiselect("Regla:", df_cat['regla'].unique(), default=df_cat['regla'].unique())
            
            df_filtered = df_cat[
                (df_cat['estatus'].isin(status_filter)) & 
                (df_cat['regla'].isin(regla_filter))
            ]
            
            if sku_filter:
                df_filtered = df_filtered[df_filtered['sku_limpio'].str.contains(sku_filter, case=False, na=False)]
            
            st.metric(f"Total SKUs encontrados", len(df_filtered))
            st.dataframe(df_filtered, use_container_width=True, height=400)
        else:
            st.info("📭 No hay catálogo disponible")
    
    # ==========================================
    # TAB 4: REPORTES DESCARGABLES
    # ==========================================
    with tab4:
        st.subheader("📥 Reportes Ejecutivos")
        
        st.markdown("### 📊 Generar Reportes")
        
        col_report1, col_report2 = st.columns(2)
        
        with col_report1:
            if st.button("📈 Reporte Diario", use_container_width=True):
                with st.spinner("⏳ Generando reporte diario..."):
                    df_daily = get_historial_precios(days=1)
                    if not df_daily.empty:
                        excel_buffer = BytesIO()
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            df_daily.to_excel(writer, sheet_name='Diario', index=False)
                        excel_buffer.seek(0)
                        st.download_button(
                            label="📥 Descargar Reporte Diario",
                            data=excel_buffer.getvalue(),
                            file_name=f"reporte_diario_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
        
        with col_report2:
            if st.button("📊 Reporte Semanal", use_container_width=True):
                with st.spinner("⏳ Generando reporte semanal..."):
                    df_weekly = get_historial_precios(days=7)
                    if not df_weekly.empty:
                        excel_buffer = BytesIO()
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            df_weekly.to_excel(writer, sheet_name='Semanal', index=False)
                        excel_buffer.seek(0)
                        st.download_button(
                            label="📥 Descargar Reporte Semanal",
                            data=excel_buffer.getvalue(),
                            file_name=f"reporte_semanal_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
        
        st.markdown("---")
        st.info("""
        ### 📋 Tipos de Reportes Disponibles:
        - **Reporte Diario:** Última 24h de cambios de precios
        - **Reporte Semanal:** Últimos 7 días de análisis
        - **Formato Excel:** Para análisis en Excel con toda la información
        """)

# ==========================================
# 🔐 ADMIN VIEW (Optimizado)
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
        st.subheader("📊 Métricas en Vivo")
        
        with st.spinner("⏳ Cargando métricas..."):
            metricas = get_metricas_vivas()
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🎯 SKUs Activos", metricas['total_skus'])
        with col2:
            st.metric("⚡ Updates/Hora", metricas['updates_hora'])
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Dashboard", "📈 Histórico", "📋 Catálogo", "📥 Reportes", "⚙️ Config"])
    
    with tab1:
        st.subheader("📊 Resumen Ejecutivo (Admin View)")
        
        with st.spinner("⏳ Cargando dashboard..."):
            df_hist = get_historial_precios(days=1)
        
        if not df_hist.empty:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class='metric-card'>
                    <div class='metric-value'>{len(df_hist)}</div>
                    <div class='metric-label'>Precios Revisados</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                ajustes = df_hist[df_hist['precio_nuv'] != df_hist['precio_ant']].shape[0]
                st.markdown(f"""
                <div class='metric-card'>
                    <div class='metric-value'>{ajustes}</div>
                    <div class='metric-label'>Ajustes Realizados</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                buybox_count = (df_hist['resultado'] == 'GANADOR').sum()
                st.markdown(f"""
                <div class='metric-card'>
                    <div class='metric-value'>{buybox_count}</div>
                    <div class='metric-label'>Ganando Buybox</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                stock_promedio = df_hist['stock'].mean() if 'stock' in df_hist.columns else 0
                st.markdown(f"""
                <div class='metric-card'>
                    <div class='metric-value'>{stock_promedio:.0f}</div>
                    <div class='metric-label'>Stock Promedio</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            
            col_graph1, col_graph2 = st.columns(2)
            
            with col_graph1:
                st.markdown("### 📈 Evolución de Precios (24h)")
                try:
                    df_sorted = df_hist.sort_values('created_at')
                    fig = px.line(df_sorted.head(100), x='created_at', y=['precio_ant', 'precio_nuv'],
                                 title='Nuestro Precio vs Rival')
                    fig.update_layout(template="plotly_dark", height=350)
                    st.plotly_chart(fig, use_container_width=True)
                except Exception as e:
                    st.warning(f"⚠️ Error: {e}")
            
            with col_graph2:
                st.markdown("### 🎯 Distribución de Resultados")
                try:
                    resultado_counts = df_hist['resultado'].value_counts()
                    colors = ['#1db954', '#ff4757', '#ffa502']
                    fig = px.pie(values=resultado_counts.values, names=resultado_counts.index,
                                title='Ganador vs Competencia',
                                color_discrete_sequence=colors)
                    fig.update_layout(template="plotly_dark", height=350)
                    st.plotly_chart(fig, use_container_width=True)
                except Exception as e:
                    st.warning(f"⚠️ Error: {e}")
        else:
            st.info("📭 No hay datos")
    
    with tab2:
        st.subheader("📈 Análisis Histórico")
        days = st.slider("Días:", 1, 30, 7)
        
        with st.spinner("⏳ Cargando..."):
            df_hist = get_historial_precios(days=days)
        
        if not df_hist.empty:
            st.dataframe(df_hist, use_container_width=True, height=400)
        else:
            st.info("📭 Sin datos")
    
    with tab3:
        st.subheader("📋 Catálogo Maestro")
        
        with st.spinner("⏳ Cargando..."):
            df_cat = get_catalogo_maestro()
        
        if not df_cat.empty:
            st.dataframe(df_cat, use_container_width=True, height=400)
        else:
            st.info("📭 Sin catálogo")
    
    with tab4:
        st.subheader("📥 Reportes")
        if st.button("📊 Generar Reporte"):
            st.success("✅ Reporte generado")
    
    with tab5:
        st.subheader("⚙️ Configuración")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔄 Limpiar Caché"):
                st.cache_data.clear()
                st.success("✅ Caché limpiado")
        
        with col2:
            if st.button("🔄 Recargar"):
                st.rerun()
        
        with col3:
            if st.button("🚪 Cerrar Sesión"):
                st.session_state['authenticated'] = False
                st.session_state['admin_mode'] = False
                st.rerun()
        
        st.markdown("---")
        st.info("""
        ### 📊 Dashboard v3.1 FASE 2
        - **Status:** ✅ Optimizado
        - **Caché:** Agresivo (TTL 600s histórico, 3600s catálogo)
        - **Throttling:** Eliminado
        - **UI:** Corporativa
        - **Reportes:** Excel descargable
        """)

# ==========================================
# 🚀 MAIN LOGIC
# ==========================================

def main():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "admin_mode" not in st.session_state:
        st.session_state.admin_mode = False
    if "executive_mode" not in st.session_state:
        st.session_state.executive_mode = False
    
    if st.session_state.admin_mode and st.session_state.authenticated:
        show_admin_dashboard()
    elif st.session_state.executive_mode:
        show_executive_dashboard()
    else:
        show_login_page()

if __name__ == "__main__":
    main()
