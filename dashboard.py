#!/usr/bin/env python3
# ==========================================
# MEGAZORD WAR ROOM - DASHBOARD V4.0
# ADMIN COMPLETO + GESTIÓN DE CATÁLOGO
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
# 🎨 DARK MODE CSS
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
    
    .warning-box { background: #ff4757; padding: 15px; border-radius: 6px; color: white; font-weight: bold; }
    .success-box { background: #1db954; padding: 15px; border-radius: 6px; color: white; font-weight: bold; }
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
        """Ejecuta UPDATE/INSERT/DELETE directamente"""
        try:
            if self.engine is None:
                logger.error("❌ Engine es None")
                return False
            
            logger.info(f"📝 Query: {query[:80]}...")
            
            # Usar raw_connection directo
            connection = self.engine.raw_connection()
            try:
                cursor = connection.cursor()
                cursor.execute(query)
                connection.commit()
                
                rows = cursor.rowcount
                logger.info(f"✅ Ejecutado - Filas afectadas: {rows}")
                cursor.close()
                return True
            except Exception as e:
                connection.rollback()
                logger.error(f"❌ Error: {e}")
                return False
            finally:
                connection.close()
        except Exception as e:
            logger.error(f"❌ Error crítico: {e}")
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

@st.cache_data(ttl=600)
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

@st.cache_data(ttl=3600)
def get_catalogo_maestro() -> pd.DataFrame:
    query = """
    SELECT id, sku_limpio, sku_interno, sku_liverpool, sku_walmart, sku_coppel,
           precio_minimo, precio_maximo, costo_odoo, estatus, id_cuenta,
           COALESCE(regla_estrategia, '1. Gladiador') AS regla
    FROM catalogo_maestro_v3 
    ORDER BY sku_limpio
    """
    return db.execute_query(query)

@st.cache_data(ttl=120)
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

@st.cache_data(ttl=120)
def get_cuentas_disponibles() -> list:
    df_ctas = db.execute_query("SELECT id_cuenta FROM cuentas_liverpool ORDER BY id_cuenta ASC")
    return df_ctas['id_cuenta'].tolist() if not df_ctas.empty else ['LVP_01']

@st.cache_data(ttl=120)
def get_reglas_disponibles() -> list:
    return ['1. Gladiador', '2. Sombra', '3. Invasor', '4. Mantener Margen']

def get_buybox_price_actual(sku_interno: str) -> Optional[float]:
    """Obtiene el precio actual de Buybox para un SKU"""
    try:
        query = """
        SELECT precio_rival FROM historial_precios 
        WHERE sku_interno = :sku_interno 
        ORDER BY fecha_hora DESC 
        LIMIT 1
        """
        df = db.execute_query(query, {"sku_interno": sku_interno})
        if not df.empty:
            return float(df['precio_rival'].values[0])
        return None
    except:
        return None

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
            if st.button("📊 Acceder como Ejecutivo", width="stretch", key="btn_exec"):
                st.session_state['authenticated'] = False
                st.session_state['admin_mode'] = False
                st.session_state['executive_mode'] = True
                st.success("✅ Acceso como Ejecutivo")
                st.rerun()
        
        with col_admin:
            st.markdown("### 🔐 Administrador")
            st.markdown("*Acceso completo (editar)*")
            
            password = st.text_input("🔐 Contraseña", type="password", key="admin_password")
            if st.button("🚀 Acceder como Admin", width="stretch", key="btn_admin"):
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
# 👁️ EXECUTIVE VIEW (v3.1 - Sin cambios)
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
    
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard Ejecutivo", "📈 Análisis Histórico", "📋 Catálogo", "📥 Reportes"])
    
    with tab1:
        st.subheader("📊 Resumen Ejecutivo")
        
        with st.spinner("⏳ Cargando dashboard..."):
            df_hist = get_historial_precios(days=1)
        
        if not df_hist.empty:
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
                try:
                    stock_temp = pd.to_numeric(df_hist['stock'], errors='coerce').mean() if 'stock' in df_hist.columns else 0
                    stock_promedio = 0 if (pd.isna(stock_temp) or np.isnan(stock_temp)) else int(stock_temp)
                except:
                    stock_promedio = 0
                st.markdown(f"""
                <div class='metric-card'>
                    <div class='metric-value'>{stock_promedio}</div>
                    <div class='metric-label'>Stock Promedio</div>
                    <div class='metric-change'>Unidades disponibles</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            
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
                    st.plotly_chart(fig, width="stretch")
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
                    st.plotly_chart(fig, width="stretch")
                except Exception as e:
                    st.warning(f"⚠️ Error al graficar: {e}")
        else:
            st.info("📭 No hay datos disponibles")
    
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
                st.dataframe(convertir_decimal_a_float(df_hist), width="stretch", height=400)
            
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
            st.dataframe(convertir_decimal_a_float(df_filtered), width="stretch", height=400)
        else:
            st.info("📭 No hay catálogo disponible")
    
    with tab4:
        st.subheader("📥 Reportes Ejecutivos")
        
        st.markdown("### 📊 Generar Reportes")
        
        col_report1, col_report2 = st.columns(2)
        
        with col_report1:
            if st.button("📈 Reporte Diario", width="stretch"):
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
            if st.button("📊 Reporte Semanal", width="stretch"):
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

# ==========================================
# 🔐 ADMIN VIEW + GESTIÓN DE CATÁLOGO (v4.0)
# ==========================================

def show_admin_dashboard():
    st.markdown("<h1 style='text-align: center; color: #00d9ff;'>⚡ MEGAZORD War Room - Admin Panel</h1>", unsafe_allow_html=True)
    
    with st.sidebar:
        st.markdown("---")
        st.subheader("🔐 Modo: Administrador")
        st.markdown("*Acceso completo. Puedes editar.*")
        st.markdown("---")
        
        # NUEVO: Botón para ejecutar barrido (main.yml)
        st.subheader("🤖 Ejecutar Barrido Bot")
        
        marketplace_ejecutar = st.selectbox(
            "Selecciona Marketplace:",
            ["🔴 LIVERPOOL", "🟦 WALMART", "🟩 AMBAS"],
            index=0,
            key="marketplace_trigger"
        )
        
        # Session state para barrido
        if "barrido_ejecutado" not in st.session_state:
            st.session_state.barrido_ejecutado = False
        if "barrido_resultado" not in st.session_state:
            st.session_state.barrido_resultado = None
        
        # Mostrar resultado anterior si existe
        if st.session_state.barrido_resultado:
            if st.session_state.barrido_resultado.get("exito"):
                st.success(st.session_state.barrido_resultado.get("mensaje", "✅ Barrido completado"))
            else:
                st.error(st.session_state.barrido_resultado.get("mensaje", "❌ Error en barrido"))
        
        # Botón para ejecutar barrido
        if st.button("▶️ Ejecutar Barrido Ahora", width="stretch", key="trigger_barrido"):
            with st.spinner(f"⏳ Ejecutando barrido para {marketplace_ejecutar}..."):
                logger.info(f"🚀 Barrido iniciado para: {marketplace_ejecutar}")
                
                try:
                    # ╔═══════════════════════════════════════════════════════════════╗
                    # ║  INTEGRACIÓN CON WEBHOOK/BOT                                  ║
                    # ║  Reemplazar con tu logica real de ejecución                   ║
                    # ╚═══════════════════════════════════════════════════════════════╝
                    
                    if marketplace_ejecutar == "🔴 LIVERPOOL":
                        # TODO: Llamar a tu webhook en Railway o ejecutar bot local
                        # resultado = ejecutar_barrido_liverpool()
                        resultado = ejecutar_barrido_simulado()
                    elif marketplace_ejecutar == "🟦 WALMART":
                        # TODO: Llamar a tu webhook de Walmart
                        # resultado = ejecutar_barrido_walmart()
                        resultado = ejecutar_barrido_simulado()
                    elif marketplace_ejecutar == "🟩 AMBAS":
                        # TODO: Ejecutar ambos
                        # resultado_lv = ejecutar_barrido_liverpool()
                        # resultado_wm = ejecutar_barrido_walmart()
                        resultado = ejecutar_barrido_simulado()
                    
                    st.session_state.barrido_resultado = resultado
                    st.rerun()
                    
                except Exception as e:
                    logger.error(f"❌ Error en barrido: {e}")
                    st.session_state.barrido_resultado = {
                        "exito": False,
                        "mensaje": f"❌ Error: {str(e)}"
                    }
                    st.rerun()
        
        # FUTURO: Botón para Coppel (deshabilitado por ahora)
        if st.button("🟪 Coppel (Próximamente)", width="stretch", disabled=True):
            pass
        
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
    
    # TAB 6: NUEVO - GESTIÓN DE CATÁLOGO (ADMIN COMPLETO)
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Dashboard", 
        "📈 Histórico", 
        "📋 Catálogo", 
        "📥 Reportes", 
        "⚙️ Config",
        "✏️ Gestión de Catálogo"  # ← NUEVA TAB
    ])
    
    with tab1:
        st.subheader("📊 Resumen Ejecutivo (Admin View)")
        
        with st.spinner("⏳ Cargando métricas..."):
            metricas_dash = get_metricas_dashboard(dias=1)
        
        # NUEVAS MÉTRICAS
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "📊 Precios Revisados",
                metricas_dash['precios_revisados'],
                help="Total de actualizaciones en el último día"
            )
        
        with col2:
            st.metric(
                "🎯 SKUs Ganando Buybox",
                metricas_dash['ganando_buybox'],
                help="SKUs con precio <= competencia (más competitivos)"
            )
        
        with col3:
            st.metric(
                "✅ SKUs Saludables",
                metricas_dash['skus_saludables'],
                help="SKUs con margen >= 10%"
            )
        
        with col4:
            st.metric(
                "💰 Ganancia Neta Total",
                f"${metricas_dash['ganancia_neta_total']:.2f}",
                help="Ganancia neta acumulada (últimas 24h)"
            )
        
        st.markdown("---")
        
        # GRÁFICAS DEL DASHBOARD - REEMPLAZADAS
        tab_tendencias, tab_actividad = st.tabs(["📈 Tendencias de Precio", "🔥 Heatmap de Actividad"])
        
        with tab_tendencias:
            st.markdown("### 📈 Tendencias de Precio (últimas 24h)")
            try:
                tendencias_result = get_analisis_tendencias(dias=1)
                if tendencias_result['success'] and tendencias_result['data'] is not None:
                    df_tendencias = tendencias_result['data']
                    
                    fig = px.line(
                        df_tendencias.head(50),
                        x='fecha',
                        y=['precio_promedio'],
                        title='Evolución de Precios Promedio',
                        labels={'valor': 'Precio ($)', 'fecha': 'Fecha'}
                    )
                    fig.update_layout(template="plotly_dark", height=400, hovermode='x unified')
                    st.plotly_chart(fig, width="stretch")
                    
                    # Tabla de tendencias
                    st.markdown("#### Detalle de Tendencias")
                    st.dataframe(
                        df_tendencias[['sku_interno', 'fecha', 'precio_promedio', 'precio_min', 'precio_max']].head(20),
                        width="stretch"
                    )
                else:
                    st.warning("⚠️ No hay datos de tendencias")
            except Exception as e:
                st.error(f"❌ Error: {e}")
        
        with tab_actividad:
            st.markdown("### 🔥 Actividad Horaria (últimas 24h)")
            try:
                actividad_result = get_heatmap_actividad(dias=1)
                if actividad_result['success'] and actividad_result['data'] is not None:
                    df_actividad = actividad_result['data']
                    
                    fig = px.bar(
                        df_actividad,
                        x='hora',
                        y='cambios',
                        title='Cambios de Precio por Hora',
                        labels={'cambios': 'Número de Cambios', 'hora': 'Hora del Día'}
                    )
                    fig.update_layout(template="plotly_dark", height=400, showlegend=False)
                    st.plotly_chart(fig, width="stretch")
                    
                    # Tabla de actividad
                    st.markdown("#### Detalle de Actividad")
                    st.dataframe(
                        df_actividad,
                        width="stretch"
                    )
                else:
                    st.warning("⚠️ No hay datos de actividad")
            except Exception as e:
                st.error(f"❌ Error: {e}")
    
    with tab2:
        st.subheader("📈 Análisis Histórico")
        days = st.slider("Días:", 1, 30, 7)
        
        with st.spinner("⏳ Cargando..."):
            df_hist = get_historial_precios(days=days)
        
        if not df_hist.empty:
            st.dataframe(convertir_decimal_a_float(df_hist), width="stretch", height=400)
        else:
            st.info("📭 Sin datos")
    
    with tab3:
        st.subheader("📋 Catálogo Maestro")
        
        with st.spinner("⏳ Cargando..."):
            df_cat = get_catalogo_maestro()
        
        if not df_cat.empty:
            st.dataframe(convertir_decimal_a_float(df_cat), width="stretch", height=400)
        else:
            st.info("📭 Sin catálogo")
    
    with tab4:
        st.subheader("📊 Análisis Avanzado - Fase 3B")
        st.markdown("Análisis interactivos y detallados de rendimiento, competencia y tendencias")
        
        st.markdown("---")
        
        # SELECTOR DE PERÍODO
        col_period1, col_period2, col_period3 = st.columns(3)
        
        with col_period1:
            periodo = st.radio(
                "Período de análisis:",
                ["📅 Últimos 7 días", "📅 Últimos 30 días", "📅 Últimos 90 días", "📅 Personalizado"],
                index=0,
                horizontal=False
            )
        
        # Mapear período a número de días
        periodo_map = {
            "📅 Últimos 7 días": 7,
            "📅 Últimos 30 días": 30,
            "📅 Últimos 90 días": 90,
        }
        
        if periodo == "📅 Personalizado":
            with col_period2:
                dias_custom = st.number_input("Días personalizados:", min_value=1, max_value=365, value=7)
            dias_analisis = dias_custom
        else:
            dias_analisis = periodo_map.get(periodo, 7)
        
        st.markdown("---")
        
        # SUBTABS DE ANÁLISIS
        subtab1, subtab2, subtab3, subtab4, subtab5, subtab6, subtab7 = st.tabs([
            "📈 Tendencias",
            "🥇 Top 10",
            "💵 Margen",
            "🏆 Competencia",
            "🔥 Actividad",
            "📊 Distribución",
            "📉 Críticos"
        ])
        
        # ==========================================
        # SUBTAB 1: TENDENCIAS DE PRECIO
        # ==========================================
        with subtab1:
            st.markdown("### 📈 Tendencias de Precio")
            
            with st.spinner("⏳ Cargando tendencias..."):
                trend_result = get_analisis_tendencias(dias_analisis)
            
            if trend_result["success"] and trend_result["data"] is not None:
                df_trend = trend_result["data"]
                
                # Gráfico de tendencia por SKU
                if not df_trend.empty:
                    # Pivot para gráfico
                    df_pivot = df_trend.pivot_table(
                        values='precio_promedio',
                        index='fecha',
                        columns='sku_interno',
                        aggfunc='mean'
                    )
                    
                    fig_trend = go.Figure()
                    for col in df_pivot.columns[:10]:  # Top 10 SKUs
                        fig_trend.add_trace(go.Scatter(
                            x=df_pivot.index,
                            y=df_pivot[col],
                            mode='lines+markers',
                            name=col,
                            hovertemplate=f'{col}<br>Fecha: %{{x}}<br>Precio: $%{{y:.2f}}<extra></extra>'
                        ))
                    
                    fig_trend.update_layout(
                        title=f'Tendencia de Precios - Últimos {dias_analisis} días',
                        xaxis_title='Fecha',
                        yaxis_title='Precio Promedio ($)',
                        template='plotly_dark',
                        height=500,
                        hovermode='x unified'
                    )
                    
                    st.plotly_chart(fig_trend, width="stretch")
                    
                    # Tabla de tendencias
                    st.markdown("#### Resumen de Tendencias")
                    col_t1, col_t2, col_t3 = st.columns(3)
                    
                    with col_t1:
                        st.metric("SKUs monitoreados", df_trend['sku_interno'].nunique())
                    with col_t2:
                        st.metric("Cambios totales", len(df_trend))
                    with col_t3:
                        st.metric("Precio promedio", f"${df_trend['precio_promedio'].mean():.2f}")
                    
                    # Mostrar datos
                    st.markdown("#### Datos detallados")
                    st.dataframe(
                        df_trend.sort_values('fecha', ascending=False),
                        width="stretch"
                    )
            else:
                st.warning("❌ No hay datos de tendencias disponibles")
        
        # ==========================================
        # SUBTAB 2: TOP 10 SKUs POR PERFORMANCE
        # ==========================================
        with subtab2:
            st.markdown("### 🥇 Top 10 SKUs - Mayor Ganancia")
            
            with st.spinner("⏳ Cargando top SKUs..."):
                top_result = get_top_skus_performance(dias_analisis)
            
            if top_result["success"] and top_result["data"] is not None:
                df_top = top_result["data"]
                
                # Gráfico de barras
                if not df_top.empty:
                    fig_top = go.Figure()
                    
                    fig_top.add_trace(go.Bar(
                        y=df_top['sku_limpio'],
                        x=df_top['ganancia_neta'],
                        orientation='h',
                        marker=dict(
                            color=df_top['ganancia_neta'],
                            colorscale='Greens',
                            showscale=True
                        ),
                        text=[f"${v:.2f}" for v in df_top['ganancia_neta']],
                        textposition='auto',
                        hovertemplate='<b>%{y}</b><br>Ganancia: $%{x:.2f}<extra></extra>'
                    ))
                    
                    fig_top.update_layout(
                        title=f'Top 10 SKUs por Ganancia Monetaria - Últimos {dias_analisis} días',
                        xaxis_title='Ganancia Monetaria ($)',
                        yaxis_title='SKU',
                        template='plotly_dark',
                        height=500,
                        showlegend=False
                    )
                    
                    st.plotly_chart(fig_top, width="stretch")
                    
                    # Métricas
                    col_top1, col_top2, col_top3, col_top4 = st.columns(4)
                    
                    with col_top1:
                        st.metric("Ganancia Total", f"${df_top['ganancia_neta'].sum():.2f}")
                    with col_top2:
                        st.metric("Ganancia Promedio", f"${df_top['ganancia_neta'].mean():.2f}")
                    with col_top3:
                        st.metric("Cambios realizados", int(df_top['cambios_realizados'].sum()))
                    with col_top4:
                        st.metric("SKUs activos", len(df_top))
                    
                    # Tabla
                    st.markdown("#### Detalle de SKUs")
                    df_top_display = df_top[['sku_limpio', 'precio_actual', 'costo', 'ganancia_neta', 'ganancia_porcentaje', 'cambios_realizados', 'regla']].copy()
                    df_top_display = convertir_decimal_a_float(df_top_display)  # ✨ Convertir ANTES de renombrar
                    df_top_display.columns = ['SKU', 'Precio Actual', 'Costo', 'Ganancia Neta', 'Margen %', 'Cambios', 'Regla']
                    
                    st.dataframe(
                        df_top_display.style.format({
                            'Precio Actual': '${:.2f}',
                            'Costo': '${:.2f}',
                            'Ganancia Neta': '${:.2f}',
                            'Margen %': '{:.1f}%'
                        }),
                        width="stretch"
                    )
            else:
                st.warning("❌ No hay datos de top SKUs")
        
        # ==========================================
        # SUBTAB 3: ANÁLISIS DE MARGEN
        # ==========================================
        with subtab3:
            st.markdown("### 💵 Análisis de Margen vs Rivales")
            
            with st.spinner("⏳ Cargando análisis de margen..."):
                margen_result = get_analisis_margen(dias_analisis)
            
            if margen_result["success"] and margen_result["data"] is not None:
                df_margen = margen_result["data"]
                
                if not df_margen.empty:
                    # Gráfico scatter: Margen vs Diferencia de Precio
                    fig_margen = go.Figure()
                    
                    fig_margen.add_trace(go.Scatter(
                        x=df_margen['diferencia_precio'],
                        y=df_margen['margen_porcentaje'],
                        mode='markers',
                        marker=dict(
                            size=10,
                            color=df_margen['margen_porcentaje'],
                            colorscale='RdYlGn',
                            showscale=True,
                            colorbar=dict(title="Margen %")
                        ),
                        text=df_margen['sku_limpio'],
                        hovertemplate='<b>%{text}</b><br>Diferencia precio: $%{x:.2f}<br>Margen: %{y:.1f}%<extra></extra>'
                    ))
                    
                    fig_margen.update_layout(
                        title=f'Margen vs Diferencia de Precio - Últimos {dias_analisis} días',
                        xaxis_title='Diferencia Precio (Nuestro - Rival) ($)',
                        yaxis_title='Margen (%)',
                        template='plotly_dark',
                        height=500,
                        hovermode='closest'
                    )
                    
                    st.plotly_chart(fig_margen, width="stretch")
                    
                    # Métricas
                    col_marg1, col_marg2, col_marg3 = st.columns(3)
                    
                    margen_avg = df_margen[df_margen['margen_porcentaje'] > 0]['margen_porcentaje'].mean()
                    ganancia_total = df_margen['ganancia_neta'].sum()
                    skus_perdida = len(df_margen[df_margen['margen_porcentaje'] < 0])
                    
                    with col_marg1:
                        st.metric("Margen Promedio", f"{margen_avg:.1f}%")
                    with col_marg2:
                        st.metric("Ganancia Total", f"${ganancia_total:.2f}")
                    with col_marg3:
                        st.metric("SKUs en pérdida", skus_perdida)
                    
                    # Tabla
                    st.markdown("#### Detalle de Márgenes")
                    df_marg_display = df_margen[['sku_limpio', 'nuestro_precio', 'precio_rival', 'costo', 'ganancia_neta', 'margen_porcentaje']].copy()
                    df_marg_display = convertir_decimal_a_float(df_marg_display)  # ✨ Convertir ANTES de renombrar
                    df_marg_display.columns = ['SKU', 'Nuestro $', 'Rival $', 'Costo $', 'Ganancia $', 'Margen %']
                    
                    st.dataframe(
                        df_marg_display.sort_values('Margen %', ascending=False).style.format({
                            'Nuestro $': '${:.2f}',
                            'Rival $': '${:.2f}',
                            'Costo $': '${:.2f}',
                            'Ganancia $': '${:.2f}',
                            'Margen %': '{:.1f}%'
                        }),
                        width="stretch"
                    )
            else:
                st.warning("❌ No hay datos de margen")
        
        # ==========================================
        # SUBTAB 4: ANÁLISIS DE COMPETENCIA
        # ==========================================
        with subtab4:
            st.markdown("### 🏆 Análisis de Competencia")
            
            with st.spinner("⏳ Cargando análisis de competencia..."):
                comp_result = get_competencia_precios(dias_analisis)
            
            if comp_result["success"] and comp_result["data"] is not None:
                df_comp = comp_result["data"]
                
                if not df_comp.empty:
                    # Gráfico de diferencia de precio
                    df_comp['diferencia'] = df_comp['nuestro_precio'] - df_comp['precio_rival']
                    
                    fig_comp = go.Figure()
                    
                    colors = ['#1db954' if x <= 0 else '#ff4757' for x in df_comp['diferencia']]
                    
                    fig_comp.add_trace(go.Bar(
                        y=df_comp['sku_limpio'],
                        x=df_comp['diferencia'],
                        orientation='h',
                        marker=dict(color=colors),
                        text=[f"${v:.2f}" for v in df_comp['diferencia']],
                        textposition='auto',
                        hovertemplate='<b>%{y}</b><br>Diferencia: $%{x:.2f}<extra></extra>'
                    ))
                    
                    fig_comp.update_layout(
                        title=f'Diferencia de Precio vs Rivales - Últimos {dias_analisis} días',
                        xaxis_title='Diferencia (Nuestro - Rival) ($) - Verde=Más Bajo, Rojo=Más Alto',
                        yaxis_title='SKU',
                        template='plotly_dark',
                        height=500,
                        showlegend=False
                    )
                    
                    st.plotly_chart(fig_comp, width="stretch")
                    
                    # Resumen competitivo
                    mas_bajos = len(df_comp[df_comp['diferencia'] <= 0])
                    mas_altos = len(df_comp[df_comp['diferencia'] > 0])
                    
                    col_comp1, col_comp2, col_comp3 = st.columns(3)
                    
                    with col_comp1:
                        st.metric("✅ Más BAJOS que rivales", mas_bajos)
                    with col_comp2:
                        st.metric("⚠️ Más ALTOS que rivales", mas_altos)
                    with col_comp3:
                        st.metric("Promedio diferencia", f"${df_comp['diferencia'].mean():.2f}")
                    
                    # Tabla
                    st.markdown("#### Detalle Competitivo")
                    df_comp_display = df_comp[['sku_limpio', 'nuestro_precio', 'precio_rival', 'diferencia', 'posicion', 'total_cambios']].copy()
                    df_comp_display = convertir_decimal_a_float(df_comp_display)  # ✨ Convertir ANTES de renombrar
                    df_comp_display.columns = ['SKU', 'Nuestro $', 'Rival $', 'Diferencia $', 'Posición', 'Cambios']
                    
                    st.dataframe(
                        df_comp_display.sort_values('Diferencia $').style.format({
                            'Nuestro $': '${:.2f}',
                            'Rival $': '${:.2f}',
                            'Diferencia $': '${:.2f}'
                        }),
                        width="stretch"
                    )
            else:
                st.warning("❌ No hay datos de competencia")
        
        # ==========================================
        # SUBTAB 5: HEATMAP ACTIVIDAD
        # ==========================================
        with subtab5:
            st.markdown("### 🔥 Heatmap de Actividad")
            
            with st.spinner("⏳ Cargando actividad..."):
                heat_result = get_heatmap_actividad(dias_analisis)
            
            if heat_result["success"] and heat_result["data"] is not None:
                df_heat = heat_result["data"]
                
                if not df_heat.empty:
                    # Gráfico de actividad por hora
                    fig_heat = go.Figure()
                    
                    fig_heat.add_trace(go.Bar(
                        x=df_heat['hora'].astype(int),
                        y=df_heat['cambios'],
                        marker=dict(
                            color=df_heat['cambios'],
                            colorscale='Hot',
                            showscale=True
                        ),
                        text=df_heat['cambios'],
                        textposition='auto',
                        hovertemplate='<b>Hora: %{x}:00</b><br>Cambios: %{y}<extra></extra>'
                    ))
                    
                    fig_heat.update_layout(
                        title=f'Actividad de Repricing por Hora - Últimos {dias_analisis} días',
                        xaxis_title='Hora del día',
                        yaxis_title='Cantidad de cambios',
                        template='plotly_dark',
                        height=500,
                        showlegend=False,
                        xaxis=dict(tickmode='linear', tick0=0, dtick=1)
                    )
                    
                    st.plotly_chart(fig_heat, width="stretch")
                    
                    # Métricas
                    hora_pico = df_heat.loc[df_heat['cambios'].idxmax(), 'hora'] if not df_heat.empty else 0
                    cambios_total = df_heat['cambios'].sum()
                    
                    col_heat1, col_heat2, col_heat3 = st.columns(3)
                    
                    with col_heat1:
                        st.metric("Cambios totales", int(cambios_total))
                    with col_heat2:
                        st.metric("Hora pico", f"{int(hora_pico)}:00")
                    with col_heat3:
                        st.metric("Cambios en hora pico", int(df_heat['cambios'].max()))
                    
                    # Tabla
                    st.markdown("#### Actividad por hora")
                    df_heat_display = df_heat.copy()
                    df_heat_display['hora'] = df_heat_display['hora'].astype(int).astype(str) + ':00'
                    df_heat_display = convertir_decimal_a_float(df_heat_display)  # ✨ Convertir Decimal a float
                    st.dataframe(df_heat_display.sort_values('cambios', ascending=False), width="stretch")
            else:
                st.warning("❌ No hay datos de actividad")
        
        # ==========================================
        # SUBTAB 6: DISTRIBUCIÓN DE PRECIOS
        # ==========================================
        with subtab6:
            st.markdown("### 📊 Distribución de Precios")
            
            with st.spinner("⏳ Cargando distribución..."):
                dist_result = get_distribucion_precios(dias_analisis)
            
            if dist_result["success"] and dist_result["data"] is not None:
                df_dist = dist_result["data"]
                
                if not df_dist.empty:
                    # Gráfico de pie
                    fig_dist = go.Figure()
                    
                    fig_dist.add_trace(go.Pie(
                        labels=df_dist['rango_precio'],
                        values=df_dist['cantidad_skus'],
                        hovertemplate='<b>%{label}</b><br>SKUs: %{value}<extra></extra>'
                    ))
                    
                    fig_dist.update_layout(
                        title=f'Distribución de SKUs por Rango de Precio - Últimos {dias_analisis} días',
                        template='plotly_dark',
                        height=500
                    )
                    
                    st.plotly_chart(fig_dist, width="stretch")
                    
                    # Tabla
                    st.markdown("#### Detalle por rango")
                    df_dist_display = df_dist[['rango_precio', 'cantidad_skus', 'precio_promedio']].copy()
                    df_dist_display = convertir_decimal_a_float(df_dist_display)  # ✨ Convertir ANTES de renombrar
                    df_dist_display.columns = ['Rango Precio', 'Cantidad SKUs', 'Precio Promedio']
                    
                    st.dataframe(
                        df_dist_display.style.format({
                            'Precio Promedio': '${:.2f}'
                        }),
                        width="stretch"
                    )
            else:
                st.warning("❌ No hay datos de distribución")
        
        # ==========================================
        # SUBTAB 7: SKUs CRÍTICOS
        # ==========================================
        with subtab7:
            st.markdown("### 📉 SKUs Críticos - Baja Ganancia")
            
            with st.spinner("⏳ Cargando SKUs críticos..."):
                critico_result = get_skus_criticos(dias_analisis)
            
            if critico_result["success"] and critico_result["data"] is not None:
                df_critico = critico_result["data"]
                
                if not df_critico.empty:
                    # Gráfico de margen crítico
                    fig_critico = go.Figure()
                    
                    fig_critico.add_trace(go.Bar(
                        y=df_critico['sku_limpio'],
                        x=df_critico['margen_porcentaje'],
                        orientation='h',
                        marker=dict(
                            color=df_critico['margen_porcentaje'],
                            colorscale='RdYlGn',
                            showscale=True
                        ),
                        text=[f"{v:.1f}%" for v in df_critico['margen_porcentaje']],
                        textposition='auto',
                        hovertemplate='<b>%{y}</b><br>Margen: %{x:.1f}%<extra></extra>'
                    ))
                    
                    fig_critico.update_layout(
                        title=f'SKUs Críticos - Margen < 10% - Últimos {dias_analisis} días',
                        xaxis_title='Margen (%)',
                        yaxis_title='SKU',
                        template='plotly_dark',
                        height=500,
                        showlegend=False
                    )
                    
                    st.plotly_chart(fig_critico, width="stretch")
                    
                    # Alerta
                    st.error(f"⚠️ {len(df_critico)} SKUs con margen < 10% - Requieren revisión urgente")
                    
                    # Tabla
                    st.markdown("#### SKUs a Revisar Urgentemente")
                    df_crit_display = df_critico[['sku_limpio', 'precio_minimo', 'precio_maximo', 'precio_actual', 'costo', 'margen_porcentaje', 'regla_estrategia']].copy()
                    df_crit_display = convertir_decimal_a_float(df_crit_display)  # ✨ Convertir ANTES de renombrar
                    df_crit_display.columns = ['SKU', 'Precio Mín', 'Precio Máx', 'Precio Actual', 'Costo', 'Margen %', 'Regla']
                    
                    st.dataframe(
                        df_crit_display.sort_values('Margen %').style.format({
                            'Precio Mín': '${:.2f}',
                            'Precio Máx': '${:.2f}',
                            'Precio Actual': '${:.2f}',
                            'Costo': '${:.2f}',
                            'Margen %': '{:.1f}%'
                        }),
                        width="stretch"
                    )
            else:
                st.warning("❌ No hay SKUs críticos (¡Buen trabajo!)")
    
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
        ### 📊 Dashboard v4.0 - Admin Completo
        - **Status:** ✅ Operativo
        - **Modo:** Administrador
        - **Features:** Dashboard + Gestión Catálogo
        - **Marketplace:** Liverpool
        """)
    
    # ==========================================
    # TAB 6: GESTIÓN DE CATÁLOGO (NUEVO - v4.0)
    # ==========================================
    with tab6:
        st.subheader("✏️ Gestión de Catálogo (ADMIN COMPLETO)")
        st.markdown("---")
        
        # Opciones de gestión
        gestion_option = st.radio(
            "¿Qué deseas hacer?",
            ["📝 Editar Precios", "🔄 Cambiar Regla", "✅ Activar/Desactivar SKU", "➕ Cargar Nuevo SKU"],
            horizontal=True
        )
        
        # ==========================================
        # OPCIÓN 1: EDITAR PRECIOS
        # ==========================================
        if gestion_option == "📝 Editar Precios":
            st.markdown("### 📝 Editar Precios Mín/Máx de SKU")
            
            with st.spinner("⏳ Cargando catálogo..."):
                df_cat = get_catalogo_maestro()
            
            if not df_cat.empty:
                col1, col2 = st.columns(2)
                
                with col1:
                    sku_buscar = st.text_input("🔍 Buscar SKU Liverpool:", placeholder="Ej: 789012")
                    df_filtered = df_cat[df_cat['sku_liverpool'].astype(str).str.contains(sku_buscar, case=False, na=False)] if sku_buscar else df_cat
                    
                    if not df_filtered.empty:
                        sku_selected = st.selectbox(
                            "Selecciona SKU Liverpool:",
                            df_filtered['sku_liverpool'].tolist(),
                            key="sku_edit_select"
                        )
                    else:
                        st.warning("❌ SKU Liverpool no encontrado")
                        sku_selected = None
                
                if sku_selected:
                    sku_data = df_filtered[df_filtered['sku_liverpool'] == sku_selected].iloc[0]
                    
                    with col2:
                        st.markdown(f"**SKU Interno:** {sku_data['sku_interno']}")
                        st.markdown(f"**Regla Actual:** {sku_data['regla']}")
                        st.markdown(f"**Estado:** {sku_data['estatus']}")
                    
                    # NUEVO: Mostrar tienda como recuadro informativo
                    tienda_actual = sku_data.get('id_cuenta', 'LVP_01') or 'LVP_01'
                    st.markdown(f"""
                    <div style='background: #1a1f3a; border: 2px solid #00d9ff; border-radius: 8px; padding: 10px; text-align: center;'>
                        <div style='color: #00d9ff; font-size: 0.9em;'>🏪 Tienda Liverpool</div>
                        <div style='color: #1db954; font-size: 1.4em; font-weight: bold;'>{tienda_actual}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.markdown("---")
                    
                    # NUEVO: Obtener precio actual de Buybox
                    buybox_price = get_buybox_price_actual(sku_data['sku_interno'])
                    
                    # Convertir costo_odoo a float puro (importante para st.number_input)
                    try:
                        costo_odoo = float(sku_data['costo_odoo']) if sku_data['costo_odoo'] else 0.0
                    except (ValueError, TypeError):
                        costo_odoo = 0.0
                    
                    # Mostrar información de Buybox y Costo
                    col_info1, col_info2, col_info3 = st.columns(3)
                    
                    with col_info1:
                        st.markdown(f"""
                        <div style='background: #1a1f3a; border: 2px solid #00d9ff; border-radius: 8px; padding: 15px; text-align: center;'>
                            <div style='color: #00d9ff; font-size: 0.9em;'>💰 Buybox Actual</div>
                            <div style='color: #1db954; font-size: 1.8em; font-weight: bold;'>${buybox_price if buybox_price else 'N/A'}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col_info2:
                        st.markdown(f"""
                        <div style='background: #1a1f3a; border: 2px solid #ffa502; border-radius: 8px; padding: 15px; text-align: center;'>
                            <div style='color: #ffa502; font-size: 0.9em;'>📦 Costo Odoo</div>
                            <div style='color: #ffffff; font-size: 1.8em; font-weight: bold;'>${costo_odoo:.2f}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col_info3:
                        # Costo simulado para análisis de margen
                        costo_simulado = st.number_input(
                            "Costo Simulado (solo visual):",
                            min_value=0.0,
                            value=float(costo_odoo),  # Convertir explícitamente a float
                            step=0.01,
                            help="Editable solo para simular ganancias. NO se guarda en BD."
                        )
                    
                    st.markdown("---")
                    
                    # ANÁLISIS DE MARGEN (si hay Buybox price) - FÓRMULA CORRECTA
                    if buybox_price:
                        buybox_price = float(buybox_price)  # Asegurar que es float puro
                        ganancia_buybox = calcular_ganancia_correcta(buybox_price, float(costo_simulado))
                        
                        col_margen1, col_margen2, col_margen3 = st.columns(3)
                        
                        with col_margen1:
                            st.markdown(f"""
                            <div style='background: #1a1f3a; border: 2px solid #ffa502; border-radius: 8px; padding: 12px; text-align: center;'>
                                <div style='color: #ffa502; font-size: 0.8em;'>📦 Ingreso Neto</div>
                                <div style='color: #ffffff; font-size: 1.6em; font-weight: bold;'>${ganancia_buybox['ingreso_neto']:.2f}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        with col_margen2:
                            color_gan = "#1db954" if ganancia_buybox['ganancia_neta'] > 0 else "#ff4757"
                            st.markdown(f"""
                            <div style='background: #1a1f3a; border: 2px solid {color_gan}; border-radius: 8px; padding: 12px; text-align: center;'>
                                <div style='color: {color_gan}; font-size: 0.8em;'>💵 Ganancia Neta</div>
                                <div style='color: {color_gan}; font-size: 1.6em; font-weight: bold;'>${ganancia_buybox['ganancia_neta']:.2f}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        with col_margen3:
                            color_porc = "#1db954" if ganancia_buybox['ganancia_porcentaje'] >= 10 else "#ff4757"
                            st.markdown(f"""
                            <div style='background: #1a1f3a; border: 2px solid {color_porc}; border-radius: 8px; padding: 12px; text-align: center;'>
                                <div style='color: {color_porc}; font-size: 0.8em;'>📊 Margen %</div>
                                <div style='color: {color_porc}; font-size: 1.6em; font-weight: bold;'>{ganancia_buybox['ganancia_porcentaje']:.1f}%</div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        st.markdown("---")
                    
                    col_edit1, col_edit2 = st.columns(2)
                    
                    with col_edit1:
                        new_precio_min = st.number_input(
                            f"Precio Mínimo (Actual: ${float(sku_data['precio_minimo']):.2f})",
                            min_value=0.0,
                            value=float(sku_data['precio_minimo']),
                            step=0.01
                        )
                    
                    with col_edit2:
                        new_precio_max = st.number_input(
                            f"Precio Máximo (Actual: ${float(sku_data['precio_maximo']):.2f})",
                            min_value=0.0,
                            value=float(sku_data['precio_maximo']),
                            step=0.01
                        )
                    
                    if new_precio_min >= new_precio_max:
                        st.error("❌ El precio mínimo no puede ser mayor o igual al máximo")
                    else:
                        st.markdown("---")
                        st.subheader("📊 SIMULADOR DE GANANCIA - CÁLCULO CORRECTO")
                        st.info("💡 Ajusta el precio para ver cómo cambia tu ganancia REAL (con impuestos, comisiones y costos)")
                        
                        # SIMULADOR: Precio de venta simulado
                        precio_simulado_venta = st.slider(
                            "💰 Precio de Venta Simulado (para análisis):",
                            min_value=float(new_precio_min),
                            max_value=float(new_precio_max),
                            value=(float(new_precio_min) + float(new_precio_max)) / 2,
                            step=0.01,
                            help="Ajusta para ver cómo cambiaría tu ganancia REAL"
                        )
                        
                        # Calcular ganancias CORRECTAS usando la función maestra
                        ganancia_sim = calcular_ganancia_correcta(float(precio_simulado_venta), float(costo_simulado))
                        
                        col_sim1, col_sim2, col_sim3, col_sim4 = st.columns(4)
                        
                        with col_sim1:
                            st.markdown(f"""
                            <div style='background: #1a1f3a; border: 2px solid #00d9ff; border-radius: 8px; padding: 12px; text-align: center;'>
                                <div style='color: #00d9ff; font-size: 0.8em;'>💰 Precio Venta</div>
                                <div style='color: #ffffff; font-size: 1.6em; font-weight: bold;'>${float(precio_simulado_venta):.2f}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        with col_sim2:
                            st.markdown(f"""
                            <div style='background: #1a1f3a; border: 2px solid #ffa502; border-radius: 8px; padding: 12px; text-align: center;'>
                                <div style='color: #ffa502; font-size: 0.8em;'>📦 Ingreso Neto</div>
                                <div style='color: #ffffff; font-size: 1.6em; font-weight: bold;'>${ganancia_sim['ingreso_neto']:.2f}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        with col_sim3:
                            color_gan = "#1db954" if ganancia_sim['ganancia_neta'] > 0 else "#ff4757"
                            st.markdown(f"""
                            <div style='background: #1a1f3a; border: 2px solid {color_gan}; border-radius: 8px; padding: 12px; text-align: center;'>
                                <div style='color: {color_gan}; font-size: 0.8em;'>💵 Ganancia Neta</div>
                                <div style='color: {color_gan}; font-size: 1.6em; font-weight: bold;'>${ganancia_sim['ganancia_neta']:.2f}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        with col_sim4:
                            color_porc = "#1db954" if ganancia_sim['ganancia_porcentaje'] >= 10 else "#ff4757"
                            st.markdown(f"""
                            <div style='background: #1a1f3a; border: 2px solid {color_porc}; border-radius: 8px; padding: 12px; text-align: center;'>
                                <div style='color: {color_porc}; font-size: 0.8em;'>📊 Margen %</div>
                                <div style='color: {color_porc}; font-size: 1.6em; font-weight: bold;'>{ganancia_sim['ganancia_porcentaje']:.1f}%</div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        # Mostrar detalles del cálculo
                        st.markdown("#### 📋 Detalles del Cálculo:")
                        col_det1, col_det2, col_det3 = st.columns(3)
                        
                        with col_det1:
                            st.markdown(f"""
                            **Ingreso Bruto:** ${ganancia_sim['ingreso_bruto']:.2f}
                            - Precio: ${precio_simulado_venta:.2f}
                            - Comisión (-17%): ${ganancia_sim['comision']:.2f}
                            - Guía (-130): $130.00
                            """)
                        
                        with col_det2:
                            st.markdown(f"""
                            **Impuestos:** ${ganancia_sim['impuestos_totales']:.2f}
                            - ISR (2.5%): ${ganancia_sim['isr']:.2f}
                            - IVA (8%): ${ganancia_sim['iva']:.2f}
                            """)
                        
                        with col_det3:
                            st.markdown(f"""
                            **Costo:** ${ganancia_sim['costo_con_iva']:.2f}
                            - Costo ODOO: ${ganancia_sim['costo_odoo']:.2f}
                            - + IVA (x1.16): ${ganancia_sim['costo_con_iva']:.2f}
                            """)
                        
                        # Indicador de margen saludable
                        if ganancia_sim['margen_saludable']:
                            st.success(f"✅ {ganancia_sim['mensaje_margen']} ({ganancia_sim['ganancia_porcentaje']:.1f}% >= 10%)")
                        else:
                            st.error(f"⚠️ {ganancia_sim['mensaje_margen']} ({ganancia_sim['ganancia_porcentaje']:.1f}% < 10%)")
                        
                        st.markdown("---")
                        
                        # USAR SESSION_STATE para mantener flujo consistente
                        if "edit_precio_confirm" not in st.session_state:
                            st.session_state.edit_precio_confirm = False
                        
                        col_btn1, col_btn2 = st.columns(2)
                        
                        with col_btn1:
                            if st.button("💾 Guardar Cambios de Precios", width="stretch", key="btn_guardar_precio"):
                                st.session_state.edit_precio_confirm = True
                                st.rerun()
                        
                        with col_btn2:
                            if st.button("🔄 Resetear", width="stretch", key="btn_reset_precio"):
                                st.session_state.edit_precio_confirm = False
                                st.rerun()
                        
                        # MOSTRAR CONFIRMACIÓN SOLO SI ESTADO = TRUE
                        if st.session_state.edit_precio_confirm:
                            st.warning(f"""
                            ⚠️ CONFIRMA LOS CAMBIOS:
                            
                            SKU: {sku_data['sku_interno']}
                            Precio Mín: ${float(sku_data['precio_minimo']):.2f} → ${float(new_precio_min):.2f}
                            Precio Máx: ${float(sku_data['precio_maximo']):.2f} → ${float(new_precio_max):.2f}
                            """)
                            
                            col_confirm1, col_confirm2 = st.columns(2)
                            
                            with col_confirm1:
                                if st.button("✅ CONFIRMAR GUARDADO", width="stretch", key="confirm_final_precio"):
                                    with st.spinner("⏳ Guardando cambios en BD..."):
                                        try:
                                            logger.info(f"📝 UPDATE: SKU {sku_data['sku_interno']}")
                                            logger.info(f"📝 Nuevo min: {new_precio_min}, Nuevo max: {new_precio_max}")
                                            
                                            update_query = f"""
                                            UPDATE catalogo_maestro_v3 
                                            SET precio_minimo = {float(new_precio_min)}, 
                                                precio_maximo = {float(new_precio_max)}
                                            WHERE sku_interno = '{sku_data['sku_interno']}'
                                            """
                                            
                                            resultado = db.execute_update(update_query)
                                            
                                            if resultado:
                                                st.success("✅ ¡ÉXITO! Precios guardados en BD")
                                                st.balloons()
                                                st.session_state.edit_precio_confirm = False
                                                logger.info("✅ UPDATE COMPLETADO")
                                                time.sleep(2)
                                                st.cache_data.clear()
                                                st.rerun()
                                            else:
                                                st.error("❌ No se guardó - Revisa logs")
                                        except Exception as e:
                                            st.error(f"❌ ERROR: {str(e)}")
                                            logger.error(f"❌ Excepción: {e}")
                            
                            with col_confirm2:
                                if st.button("❌ CANCELAR", width="stretch", key="cancel_final_precio"):
                                    st.session_state.edit_precio_confirm = False
                                    st.rerun()
            else:
                st.error("❌ No hay catálogo disponible")
        
        # ==========================================
        # OPCIÓN 2: CAMBIAR REGLA
        # ==========================================
        elif gestion_option == "🔄 Cambiar Regla":
            st.markdown("### 🔄 Cambiar Regla de Estrategia")
            
            with st.spinner("⏳ Cargando catálogo..."):
                df_cat = get_catalogo_maestro()
            
            if not df_cat.empty:
                sku_buscar = st.text_input("🔍 Buscar SKU Liverpool:", placeholder="Ej: 789012", key="sku_rule_search")
                df_filtered = df_cat[df_cat['sku_liverpool'].astype(str).str.contains(sku_buscar, case=False, na=False)] if sku_buscar else df_cat
                
                if not df_filtered.empty:
                    sku_selected = st.selectbox(
                        "Selecciona SKU Liverpool:",
                        df_filtered['sku_liverpool'].tolist(),
                        key="sku_rule_select"
                    )
                    
                    sku_data = df_filtered[df_filtered['sku_liverpool'] == sku_selected].iloc[0]
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Regla Actual:** {sku_data['regla']}")
                    with col2:
                        new_regla = st.selectbox(
                            "Nueva Regla:",
                            get_reglas_disponibles(),
                            key="new_rule_select"
                        )
                    
                    # SESSION STATE para mantener flujo
                    if "change_rule_confirm" not in st.session_state:
                        st.session_state.change_rule_confirm = False
                    
                    col_btn1, col_btn2 = st.columns(2)
                    
                    with col_btn1:
                        if st.button("💾 Cambiar Regla", width="stretch", key="btn_cambiar_regla"):
                            st.session_state.change_rule_confirm = True
                            st.rerun()
                    
                    with col_btn2:
                        if st.button("🔄 Resetear", width="stretch", key="btn_reset_regla"):
                            st.session_state.change_rule_confirm = False
                            st.rerun()
                    
                    if st.session_state.change_rule_confirm:
                        st.warning(f"""
                        ⚠️ CONFIRMA EL CAMBIO:
                        
                        SKU: {sku_data['sku_interno']}
                        Regla Actual: {sku_data['regla']}
                        Nueva Regla: {new_regla}
                        """)
                        
                        col_confirm1, col_confirm2 = st.columns(2)
                        with col_confirm1:
                            if st.button("✅ CONFIRMAR CAMBIO", width="stretch", key="confirm_final_rule"):
                                with st.spinner("⏳ Guardando cambios..."):
                                    try:
                                        logger.info(f"📝 CAMBIO REGLA: SKU {sku_data['sku_interno']}")
                                        logger.info(f"📝 Nueva regla: {new_regla}")
                                        
                                        update_query = f"""
                                        UPDATE catalogo_maestro_v3 
                                        SET regla_estrategia = '{new_regla}'
                                        WHERE sku_interno = '{sku_data['sku_interno']}'
                                        """
                                        resultado = db.execute_update(update_query)
                                        
                                        if resultado:
                                            st.success("✅ ¡ÉXITO! Regla actualizada")
                                            st.balloons()
                                            st.session_state.change_rule_confirm = False
                                            logger.info("✅ CAMBIO REGLA COMPLETADO")
                                            time.sleep(2)
                                            st.cache_data.clear()
                                            st.rerun()
                                        else:
                                            st.error("❌ No se cambió - Revisa logs")
                                    except Exception as e:
                                        st.error(f"❌ ERROR: {str(e)}")
                                        logger.error(f"❌ Excepción: {e}")
                        
                        with col_confirm2:
                            if st.button("❌ CANCELAR", width="stretch", key="cancel_final_rule"):
                                st.session_state.change_rule_confirm = False
                                st.rerun()
                else:
                    st.warning("❌ SKU no encontrado")
            else:
                st.error("❌ No hay catálogo disponible")
        
        # ==========================================
        # OPCIÓN 3: ACTIVAR/DESACTIVAR
        # ==========================================
        elif gestion_option == "✅ Activar/Desactivar SKU":
            st.markdown("### ✅ Activar o Desactivar SKU")
            
            with st.spinner("⏳ Cargando catálogo..."):
                df_cat = get_catalogo_maestro()
            
            if not df_cat.empty:
                sku_buscar = st.text_input("🔍 Buscar SKU Liverpool:", placeholder="Ej: 789012", key="sku_status_search")
                df_filtered = df_cat[df_cat['sku_liverpool'].astype(str).str.contains(sku_buscar, case=False, na=False)] if sku_buscar else df_cat
                
                if not df_filtered.empty:
                    sku_selected = st.selectbox(
                        "Selecciona SKU Liverpool:",
                        df_filtered['sku_liverpool'].tolist(),
                        key="sku_status_select"
                    )
                    
                    sku_data = df_filtered[df_filtered['sku_liverpool'] == sku_selected].iloc[0]
                    estatus_actual = sku_data['estatus']
                    nuevo_estatus = "INACTIVO" if estatus_actual == "ACTIVO" else "ACTIVO"
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Estado Actual:** {estatus_actual}")
                    with col2:
                        st.markdown(f"**Nuevo Estado:** {nuevo_estatus}")
                    
                    # SESSION STATE para mantener flujo
                    if "change_status_confirm" not in st.session_state:
                        st.session_state.change_status_confirm = False
                    
                    col_btn1, col_btn2 = st.columns(2)
                    
                    with col_btn1:
                        if st.button("💾 Cambiar Estado", width="stretch", key="btn_cambiar_estado"):
                            st.session_state.change_status_confirm = True
                            st.rerun()
                    
                    with col_btn2:
                        if st.button("🔄 Resetear", width="stretch", key="btn_reset_estado"):
                            st.session_state.change_status_confirm = False
                            st.rerun()
                    
                    if st.session_state.change_status_confirm:
                        st.warning(f"""
                        ⚠️ CONFIRMA EL CAMBIO:
                        
                        SKU: {sku_data['sku_interno']}
                        Estado Actual: {estatus_actual}
                        Nuevo Estado: {nuevo_estatus}
                        """)
                        
                        col_confirm1, col_confirm2 = st.columns(2)
                        with col_confirm1:
                            if st.button("✅ CONFIRMAR CAMBIO", width="stretch", key="confirm_final_status"):
                                with st.spinner("⏳ Guardando cambios..."):
                                    try:
                                        logger.info(f"📝 CAMBIO ESTADO: SKU {sku_data['sku_interno']}")
                                        logger.info(f"📝 Nuevo estado: {nuevo_estatus}")
                                        
                                        update_query = f"""
                                        UPDATE catalogo_maestro_v3 
                                        SET estatus = '{nuevo_estatus}'
                                        WHERE sku_interno = '{sku_data['sku_interno']}'
                                        """
                                        resultado = db.execute_update(update_query)
                                        
                                        if resultado:
                                            st.success(f"✅ ¡ÉXITO! Estado cambiado a {nuevo_estatus}")
                                            st.balloons()
                                            st.session_state.change_status_confirm = False
                                            logger.info("✅ CAMBIO ESTADO COMPLETADO")
                                            time.sleep(2)
                                            st.cache_data.clear()
                                            st.rerun()
                                        else:
                                            st.error("❌ No se cambió - Revisa logs")
                                    except Exception as e:
                                        st.error(f"❌ ERROR: {str(e)}")
                                        logger.error(f"❌ Excepción: {e}")
                        
                        with col_confirm2:
                            if st.button("❌ CANCELAR", width="stretch", key="cancel_final_status"):
                                st.session_state.change_status_confirm = False
                                st.rerun()
                else:
                    st.warning("❌ SKU no encontrado")
            else:
                st.error("❌ No hay catálogo disponible")
        
        # ==========================================
        # OPCIÓN 4: CARGAR NUEVO SKU
        # ==========================================
        elif gestion_option == "➕ Cargar Nuevo SKU":
            st.markdown("### ➕ Cargar Nuevo SKU")
            
            col1, col2 = st.columns(2)
            
            with col1:
                sku_limpio = st.text_input("SKU Limpio:", placeholder="PERFUME-001")
                sku_interno = st.text_input("SKU Interno:", placeholder="123456")
                sku_liverpool = st.text_input("SKU Liverpool:", placeholder="789012")
            
            with col2:
                precio_minimo = st.number_input("Precio Mínimo ($):", min_value=0.0, step=0.01)
                precio_maximo = st.number_input("Precio Máximo ($):", min_value=0.0, step=0.01)
                costo_odoo = st.number_input("Costo Odoo ($) - Opcional:", min_value=0.0, step=0.01, value=0.0, help="Se actualiza automáticamente 2x/día desde ODOO")
            
            col3, col4 = st.columns(2)
            
            with col3:
                regla = st.selectbox("Regla de Estrategia:", get_reglas_disponibles())
            
            with col4:
                estatus = st.selectbox("Estado:", ["ACTIVO", "INACTIVO"])
            
            # NUEVA COLUMNA: Selector de Tienda
            col5, col6 = st.columns(2)
            
            with col5:
                id_cuenta = st.selectbox(
                    "Tienda Liverpool:",
                    ["LVP_01", "LVP_02"],
                    index=0,
                    help="LVP_01 = Tienda Principal (Precio Genial)\nLVP_02 = Tienda Secundaria (futuro)"
                )
            
            # ✨ NUEVO: CALCULADOR DE GANANCIA REAL
            st.markdown("---")
            st.subheader("📊 PREVISIÓN DE GANANCIA")
            
            if costo_odoo > 0 and (precio_minimo + precio_maximo) > 0:
                # Calcular ganancia con precio promedio (entre min y max)
                precio_promedio = (precio_minimo + precio_maximo) / 2
                ganancia_prevista = calcular_ganancia_correcta(precio_promedio, costo_odoo)
                
                col_prev1, col_prev2, col_prev3, col_prev4 = st.columns(4)
                
                with col_prev1:
                    st.markdown(f"""
                    <div style='background: #1a1f3a; border: 2px solid #00d9ff; border-radius: 8px; padding: 12px; text-align: center;'>
                        <div style='color: #00d9ff; font-size: 0.8em;'>💰 Precio Promedio</div>
                        <div style='color: #ffffff; font-size: 1.5em; font-weight: bold;'>${precio_promedio:.2f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col_prev2:
                    st.markdown(f"""
                    <div style='background: #1a1f3a; border: 2px solid #ffa502; border-radius: 8px; padding: 12px; text-align: center;'>
                        <div style='color: #ffa502; font-size: 0.8em;'>📦 Ingreso Neto</div>
                        <div style='color: #ffffff; font-size: 1.5em; font-weight: bold;'>${ganancia_prevista['ingreso_neto']:.2f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col_prev3:
                    color_gan = "#1db954" if ganancia_prevista['ganancia_neta'] > 0 else "#ff4757"
                    st.markdown(f"""
                    <div style='background: #1a1f3a; border: 2px solid {color_gan}; border-radius: 8px; padding: 12px; text-align: center;'>
                        <div style='color: {color_gan}; font-size: 0.8em;'>💵 Ganancia Neta</div>
                        <div style='color: {color_gan}; font-size: 1.5em; font-weight: bold;'>${ganancia_prevista['ganancia_neta']:.2f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col_prev4:
                    color_porc = "#1db954" if ganancia_prevista['ganancia_porcentaje'] >= 10 else "#ff4757"
                    st.markdown(f"""
                    <div style='background: #1a1f3a; border: 2px solid {color_porc}; border-radius: 8px; padding: 12px; text-align: center;'>
                        <div style='color: {color_porc}; font-size: 0.8em;'>📊 Margen %</div>
                        <div style='color: {color_porc}; font-size: 1.5em; font-weight: bold;'>{ganancia_prevista['ganancia_porcentaje']:.1f}%</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Indicador de margen saludable
                if ganancia_prevista['margen_saludable']:
                    st.success(f"✅ {ganancia_prevista['mensaje_margen']} ({ganancia_prevista['ganancia_porcentaje']:.1f}% >= 10%)")
                else:
                    st.error(f"⚠️ {ganancia_prevista['mensaje_margen']} ({ganancia_prevista['ganancia_porcentaje']:.1f}% < 10%)")
            
            st.markdown("---")
            
            # VALIDAR PRIMERO
            # Costo Odoo NO es obligatorio - ODOO lo actualiza automáticamente
            # Si está en 0, poner como None (NULL en BD)
            if costo_odoo == 0.0:
                costo_odoo_insert = None
            else:
                costo_odoo_insert = costo_odoo
            
            validacion_ok = (sku_limpio and sku_interno and sku_liverpool) and (precio_minimo < precio_maximo)
            
            if not validacion_ok:
                if not (sku_limpio and sku_interno and sku_liverpool):
                    st.error("❌ Completa todos los campos obligatorios")
                elif precio_minimo >= precio_maximo:
                    st.error("❌ Precio mínimo debe ser menor a máximo")
            
            # SESSION STATE
            if "create_sku_confirm" not in st.session_state:
                st.session_state.create_sku_confirm = False
            
            col_btn1, col_btn2 = st.columns(2)
            
            with col_btn1:
                if st.button("➕ Crear SKU", width="stretch", key="btn_crear_sku", disabled=not validacion_ok):
                    st.session_state.create_sku_confirm = True
                    st.rerun()
            
            with col_btn2:
                if st.button("🔄 Resetear", width="stretch", key="btn_reset_sku"):
                    st.session_state.create_sku_confirm = False
                    st.rerun()
            
            if st.session_state.create_sku_confirm and validacion_ok:
                st.warning(f"""
                ⚠️ CONFIRMA LA CREACIÓN:
                
                SKU Limpio: {sku_limpio}
                SKU Interno: {sku_interno}
                SKU Liverpool: {sku_liverpool}
                Precio: ${precio_minimo:.2f} - ${precio_maximo:.2f}
                Costo Odoo: ${costo_odoo:.2f}
                Regla: {regla}
                Estado: {estatus}
                """)
                
                col_confirm1, col_confirm2 = st.columns(2)
                with col_confirm1:
                    if st.button("✅ CONFIRMAR CREACIÓN", width="stretch", key="confirm_final_create"):
                        with st.spinner("⏳ Creando SKU..."):
                            try:
                                logger.info(f"📝 CREATE SKU: {sku_limpio}")
                                logger.info(f"📝 SKU Interno: {sku_interno}, Liverpool: {sku_liverpool}")
                                logger.info(f"📝 Tienda: {id_cuenta}")
                                
                                # INSERT SIN especificar ID - PostgreSQL lo genera automáticamente
                                # Manejo de costo_odoo: si es 0 o None, insertar NULL (ODOO lo actualizará)
                                costo_sql = f"{float(costo_odoo_insert)}" if costo_odoo_insert else "NULL"
                                
                                insert_query = f"""
                                INSERT INTO catalogo_maestro_v3 
                                (sku_limpio, sku_interno, sku_liverpool, precio_minimo, precio_maximo, costo_odoo, regla_estrategia, estatus, id_cuenta)
                                VALUES ('{sku_limpio}', '{sku_interno}', '{sku_liverpool}', {float(precio_minimo)}, {float(precio_maximo)}, {costo_sql}, '{regla}', '{estatus}', '{id_cuenta}')
                                RETURNING id
                                """
                                resultado = db.execute_update(insert_query)
                                
                                if resultado:
                                    st.success("✅ ¡ÉXITO! SKU creado correctamente")
                                    st.balloons()
                                    st.session_state.create_sku_confirm = False
                                    logger.info("✅ CREATE SKU COMPLETADO")
                                    time.sleep(2)
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error("❌ No se creó - Revisa logs de PostgreSQL")
                                    logger.error("❌ Posible causa: ID duplicado o secuencia desincronizada")
                            except Exception as e:
                                st.error(f"❌ ERROR: {str(e)}")
                                logger.error(f"❌ Excepción: {e}")
                                st.info("""
                                💡 Si ves "duplicate key value" o "already exists":
                                Ejecuta en DBeaver (SQL Editor):
                                
                                SELECT setval('catalogo_maestro_v3_id_seq', (SELECT MAX(id) FROM catalogo_maestro_v3));
                                """)
                
                with col_confirm2:
                    if st.button("❌ CANCELAR", width="stretch", key="cancel_final_create"):
                        st.session_state.create_sku_confirm = False
                        st.rerun()


# ==========================================
# 💡 FUNCIONES PARA ÚLTIMO PRECIO (Dinámico)
# ==========================================

@st.cache_data(ttl=120)
def get_ultimo_precio_sku(sku_interno: str) -> float:
    """
    Obtiene el ÚLTIMO PRECIO registrado de un SKU.
    ✨ Dinámico - Si está en stock out, usa último precio ANTES del stock out
    ✨ NO PROMEDIA - Toma el más reciente
    """
    try:
        query = f"""
        SELECT nuestro_precio::float
        FROM historial_precios
        WHERE sku_interno = '{sku_interno}'
            AND nuestro_precio IS NOT NULL
            AND nuestro_precio ~ '^[0-9.]+$'
        ORDER BY fecha_hora DESC
        LIMIT 1
        """
        result = db.execute_query(query)
        
        if not result.empty:
            precio = float(result.iloc[0]['nuestro_precio'])
            return precio if precio > 0 else 0.0
        else:
            return 0.0
    except Exception as e:
        logger.error(f"❌ Error obteniendo último precio para {sku_interno}: {e}")
        return 0.0

@st.cache_data(ttl=120)
def get_ultimos_precios_batch(dias: int = 7) -> dict:
    """
    Obtiene el ÚLTIMO PRECIO para CADA SKU (batch - más eficiente).
    
    ✨ Dinámico - Toma último precio registrado de cada SKU
    ✨ Retorna: {sku_interno: último_precio}
    """
    try:
        query = f"""
        SELECT 
            sku_interno,
            nuestro_precio::float as precio
        FROM (
            SELECT 
                sku_interno,
                nuestro_precio,
                ROW_NUMBER() OVER (PARTITION BY sku_interno ORDER BY fecha_hora DESC) as rn
            FROM historial_precios
            WHERE fecha_hora >= NOW() - INTERVAL '{dias} days'
                AND nuestro_precio IS NOT NULL
                AND nuestro_precio ~ '^[0-9.]+$'
                AND CAST(nuestro_precio AS FLOAT) > 0
        ) ranked
        WHERE rn = 1
        """
        df = db.execute_query(query)
        
        if not df.empty:
            precio_dict = dict(zip(df['sku_interno'], df['precio']))
            return precio_dict
        else:
            return {}
    except Exception as e:
        logger.error(f"❌ Error obteniendo últimos precios batch: {e}")
        return {}

@st.cache_data(ttl=60)
def get_metricas_dashboard(dias: int = 1) -> dict:
    """
    Obtiene métricas principales para el dashboard.
    
    Retorna:
    - precios_revisados: Total de registros en historial
    - ajustes_realizados: SKUs donde precio cambió
    - ganando_buybox: SKUs donde nuestro precio <= precio_rival
    - skus_con_ganancia_saludable: SKUs con margen >= 10%
    - ingreso_neto_total: Suma de ingresos netos
    - ganancia_neta_total: Suma de ganancias netas
    """
    try:
        # Obtener datos recientes
        query = f"""
        SELECT 
            h.sku_interno,
            h.nuestro_precio,
            h.precio_rival,
            c.costo_odoo,
            COUNT(*) as cambios
        FROM historial_precios h
        LEFT JOIN catalogo_maestro_v3 c ON h.sku_interno = c.sku_interno
        WHERE h.fecha_hora >= NOW() - INTERVAL '{dias} days'
            AND c.estatus = 'ACTIVO'
        GROUP BY h.sku_interno, h.nuestro_precio, h.precio_rival, c.costo_odoo
        """
        
        df = db.execute_query(query)
        
        if df.empty:
            return {
                'precios_revisados': 0,
                'ajustes_realizados': 0,
                'ganando_buybox': 0,
                'skus_saludables': 0,
                'ingreso_neto_total': 0.0,
                'ganancia_neta_total': 0.0
            }
        
        # CALCULAR MÉTRICAS
        precios_revisados = len(df)
        
        # Ajustes: contar cambios > 1 (significa que hubo ajuste)
        ajustes_realizados = (df['cambios'] > 1).sum()
        
        # GANANDO BUYBOX: nuestro precio <= precio_rival (más competitivo)
        df['nuestro_precio_float'] = pd.to_numeric(df['nuestro_precio'], errors='coerce')
        df['precio_rival_float'] = pd.to_numeric(df['precio_rival'], errors='coerce')
        ganando_buybox = (df['nuestro_precio_float'] <= df['precio_rival_float']).sum()
        
        # Calcular ganancias para cada SKU
        ingreso_neto_total = 0.0
        ganancia_neta_total = 0.0
        skus_saludables = 0
        
        for idx, row in df.iterrows():
            if pd.notna(row['nuestro_precio_float']) and row['costo_odoo']:
                resultado = calcular_ganancia_correcta(row['nuestro_precio_float'], row['costo_odoo'])
                ingreso_neto_total += resultado['ingreso_neto']
                ganancia_neta_total += resultado['ganancia_neta']
                if resultado['margen_saludable']:
                    skus_saludables += 1
        
        return {
            'precios_revisados': precios_revisados,
            'ajustes_realizados': ajustes_realizados,
            'ganando_buybox': ganando_buybox,
            'skus_saludables': skus_saludables,
            'ingreso_neto_total': round(ingreso_neto_total, 2),
            'ganancia_neta_total': round(ganancia_neta_total, 2)
        }
    except Exception as e:
        logger.error(f"❌ Error en métricas dashboard: {e}")
        return {
            'precios_revisados': 0,
            'ajustes_realizados': 0,
            'ganando_buybox': 0,
            'skus_saludables': 0,
            'ingreso_neto_total': 0.0,
            'ganancia_neta_total': 0.0
        }

def get_ultimos_precios_batch(dias: int = 7) -> dict:
    """
    Obtiene el ÚLTIMO PRECIO VÁLIDO para TODOS los SKUs en UN QUERY.
    
    Estrategia por SKU:
    1️⃣ Si hay registros con STOCK > 0 → promedio de esos precios
    2️⃣ Si NO → último precio histórico
    
    Retorna: {sku_interno: precio_valido, ...}
    """
    try:
        query = f"""
        WITH precios_con_stock AS (
            -- Precios donde hay STOCK > 0
            SELECT 
                h.sku_interno,
                AVG(h.nuestro_precio::float) as precio_promedio_valido
            FROM historial_precios h
            WHERE h.fecha_hora >= NOW() - INTERVAL '{dias} days'
                AND CAST(h.stock AS float) > 0
            GROUP BY h.sku_interno
        ),
        ultimos_precios AS (
            -- Último precio registrado (por si no hay stock)
            SELECT 
                DISTINCT ON (sku_interno) sku_interno,
                nuestro_precio::float as ultimo_precio
            FROM historial_precios
            WHERE fecha_hora >= NOW() - INTERVAL '{dias} days'
            ORDER BY sku_interno, fecha_hora DESC
        )
        SELECT 
            COALESCE(pcs.sku_interno, up.sku_interno) as sku_interno,
            COALESCE(pcs.precio_promedio_valido, up.ultimo_precio) as precio_final
        FROM precios_con_stock pcs
        FULL OUTER JOIN ultimos_precios up ON pcs.sku_interno = up.sku_interno
        """
        
        df = db.execute_query(query)
        
        if df.empty:
            return {}
        
        # Convertir a diccionario {sku_interno: precio}
        resultado = {}
        for idx, row in df.iterrows():
            sku = row['sku_interno']
            precio = float(row['precio_final']) if row['precio_final'] else 0.0
            resultado[sku] = round(precio, 2)
        
        return resultado
    
    except Exception as e:
        logger.error(f"❌ Error en batch de precios: {e}")
        return {}

@st.cache_data(ttl=300)
def get_ultimo_precio_valido(sku_interno: str, dias: int = 7) -> float:
    """
    Obtiene el ÚLTIMO PRECIO válido para un SKU.
    
    Estrategia:
    1️⃣ Si hay registros con STOCK > 0 → USA EL PROMEDIO (representa venta activa)
    2️⃣ Si NO hay stock > 0 → USA EL ÚLTIMO PRECIO HISTÓRICO (antes de stock out)
    
    Esto evita que el promedio se vea afectado por períodos de stock out (0).
    
    Retorna: float (precio válido) o None
    """
    try:
        # Obtener histórico reciente
        query = f"""
        SELECT 
            h.nuestro_precio::float as precio,
            CAST(h.stock AS float) as stock_val,
            h.fecha_hora
        FROM historial_precios h
        WHERE h.sku_interno = '{sku_interno}'
            AND h.fecha_hora >= NOW() - INTERVAL '{dias} days'
        ORDER BY h.fecha_hora DESC
        LIMIT 500
        """
        
        df = db.execute_query(query)
        
        if df.empty:
            return None
        
        # ESTRATEGIA 1: Buscar precios con STOCK > 0
        df_con_stock = df[pd.to_numeric(df['stock_val'], errors='coerce') > 0]
        
        if not df_con_stock.empty:
            # ✅ Hay stock → usar promedio de precios válidos
            precio_valido = df_con_stock['precio'].mean()
            return round(float(precio_valido), 2)
        else:
            # ⚠️ NO hay stock > 0 → usar el último precio histórico
            ultimo_precio = df['precio'].iloc[0]  # Primera fila = más reciente (DESC)
            return round(float(ultimo_precio), 2)
    
    except Exception as e:
        logger.error(f"❌ Error obteniendo último precio para {sku_interno}: {e}")
        return None

def convertir_decimal_a_float(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte TODOS los valores Decimal a float en un DataFrame.
    
    Esto evita el error de PyArrow cuando intenta serializar para Streamlit.
    
    Error que previene:
    "Could not convert Decimal with type decimal.Decimal: tried to convert to double"
    """
    try:
        # Convertir todas las columnas object que contengan Decimal
        for col in df.columns:
            if df[col].dtype == 'object':
                # Intentar convertir a float si es posible
                try:
                    df[col] = pd.to_numeric(df[col], errors='ignore')
                except:
                    pass
        
        # Convertir específicamente columnas numéricas conocidas
        columnas_numericas = [
            'precio_promedio', 'precio_min', 'precio_max', 'nuestro_precio', 
            'precio_rival', 'costo', 'costo_odoo', 'ganancia_neta', 
            'ganancia_porcentaje', 'margen_porcentaje', 'ingreso_neto', 
            'precio_actual', 'diferencia_precio', 'precio_minimo', 'precio_maximo',
            'cambios_realizados', 'cambios', 'stock_val'
        ]
        
        for col in columnas_numericas:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    except Exception as e:
        logger.warning(f"⚠️ Error al convertir Decimal a float: {e}")
        return df

def ejecutar_barrido_simulado() -> dict:
    """
    Simula un barrido - reemplazar con llamada real a webhook/bot
    """
    import random
    skus_revisados = random.randint(50, 200)
    precios_actualizados = random.randint(10, 50)
    buybox_ganados = random.randint(5, 30)
    
    return {
        "exito": True,
        "mensaje": f"""✅ BARRIDO COMPLETADO
        
        📊 Estadísticas:
        • SKUs revisados: {skus_revisados}
        • Precios actualizados: {precios_actualizados}
        • Buybox ganados: {buybox_ganados}
        • Duración: ~2-3 minutos
        """,
        "skus_revisados": skus_revisados,
        "precios_actualizados": precios_actualizados,
        "buybox_ganados": buybox_ganados
    }

def ejecutar_barrido_liverpool_real() -> dict:
    """
    PLACEHOLDER: Implementar llamada real a webhook en Railway
    
    Opciones:
    1. Llamar webhook HTTP en Railway:
       POST https://megazord-wabu-core-production.up.railway.app/trigger
       Headers: {'Authorization': 'Bearer TOKEN'}
       Body: {'marketplace': 'liverpool', 'action': 'scan_prices'}
    
    2. Ejecutar GitHub Actions workflow:
       POST https://api.github.com/repos/FernandoWABU/megazord-wabu-core/dispatches
       Headers: {'Authorization': 'token GITHUB_TOKEN'}
       Body: {'event_type': 'manual_scan', 'client_payload': {'marketplace': 'liverpool'}}
    
    3. Ejecutar en local si está disponible:
       subprocess.run(['python', 'megazord_liverpool.py'], timeout=600)
    """
    try:
        import requests
        
        # OPCIÓN 1: Webhook en Railway (comentado - necesita configuración)
        # webhook_url = "https://megazord-wabu-core-production.up.railway.app/trigger"
        # response = requests.post(
        #     webhook_url,
        #     json={"marketplace": "liverpool", "action": "scan_prices"},
        #     headers={"Authorization": "Bearer YOUR_WEBHOOK_SECRET"},
        #     timeout=30
        # )
        # if response.status_code == 200:
        #     return {"exito": True, "mensaje": "✅ Barrido iniciado en Railway"}
        
        # Por ahora, retornar simulado
        return ejecutar_barrido_simulado()
        
    except Exception as e:
        logger.error(f"❌ Error al ejecutar barrido: {e}")
        return {
            "exito": False,
            "mensaje": f"❌ Error: {str(e)}"
        }

def ejecutar_barrido_walmart_real() -> dict:
    """
    PLACEHOLDER: Implementar llamada real a webhook de Walmart
    Ver documentación en ejecutar_barrido_liverpool_real()
    """
    try:
        # TODO: Implementar lógica de Walmart
        return ejecutar_barrido_simulado()
    except Exception as e:
        logger.error(f"❌ Error al ejecutar barrido Walmart: {e}")
        return {
            "exito": False,
            "mensaje": f"❌ Error: {str(e)}"
        }

# ==========================================
# 💰 FUNCIÓN MAESTRA DE CÁLCULO DE GANANCIA
# ==========================================

def calcular_ganancia_correcta(precio_venta: float, costo_odoo: float) -> dict:
    """
    Calcula ganancia CORRECTA con todos los impuestos y costos.
    
    Constantes:
    - GUIA: 130 (costo fijo de envío/guía)
    - CP: 17% (comisión plataforma Liverpool) ✅ ACTUALIZADO
    - ISR: 2.5% (impuesto sobre ingresos)
    - IVA: 8% (impuesto valor agregado)
    
    ✨ CADA OPERACIÓN SE REDONDEA A 2 DECIMALES
    
    Retorna:
    {
        'ingreso_bruto': float,
        'isr': float,
        'iva': float,
        'impuestos_totales': float,
        'ingreso_neto': float,
        'costo_con_iva': float,
        'ganancia_neta': float,
        'ganancia_porcentaje': float,
        'margen_saludable': bool (>=10%)
    }
    """
    try:
        # ✨ CONVERTIR DECIMAL A FLOAT (PostgreSQL retorna Decimal)
        precio_venta = float(precio_venta) if precio_venta else 0.0
        costo_odoo = float(costo_odoo) if costo_odoo else 0.0
        
        # CONSTANTES
        GUIA = 130.0
        CP = 0.17  # ✅ ACTUALIZADO: Comisión 17% (era 15%)
        ISR_RATE = 0.025  # 2.5%
        IVA_RATE = 0.08  # 8%
        MARGEN_MINIMO = 10.0  # 10%
        
        # ✨ Paso 1: INGRESO BRUTO (REDONDEADO)
        comision = round(precio_venta * CP, 2)  # ✨ REDONDEAR COMISIÓN
        ingreso_bruto = round((precio_venta - comision - GUIA), 2)  # ✨ REDONDEAR BRUTO
        
        # ✨ Paso 2-3: IMPUESTOS (ISR + IVA) (REDONDEADOS)
        base_impuesto = round(precio_venta / 1.16, 2)  # ✨ REDONDEAR BASE
        isr = round(base_impuesto * ISR_RATE, 2)  # ✨ REDONDEAR ISR
        iva = round(base_impuesto * IVA_RATE, 2)  # ✨ REDONDEAR IVA
        impuestos_totales = round(isr + iva, 2)  # ✨ REDONDEAR TOTAL IMPUESTOS
        
        # ✨ Paso 4: INGRESO NETO (REDONDEADO)
        ingreso_neto = round(ingreso_bruto - impuestos_totales, 2)  # ✨ REDONDEAR NETO
        
        # ✨ Paso 5: COSTO CON IVA (REDONDEADO)
        costo_con_iva = round(costo_odoo * 1.16, 2) if costo_odoo else 0.0  # ✨ REDONDEAR COSTO
        
        # ✨ Paso 6: GANANCIA NETA (REDONDEADA)
        ganancia_neta = round(ingreso_neto - costo_con_iva, 2)  # ✨ REDONDEAR GANANCIA
        
        # ✨ Paso 7: GANANCIA PORCENTUAL (REDONDEADA)
        if costo_con_iva > 0:
            ganancia_porcentaje = round(((ingreso_neto / costo_con_iva) - 1) * 100, 2)  # ✨ REDONDEAR %
        else:
            ganancia_porcentaje = 0.0
        
        # Paso 8: ¿MARGEN SALUDABLE?
        margen_saludable = ganancia_porcentaje >= MARGEN_MINIMO
        
        return {
            'ingreso_bruto': ingreso_bruto,
            'comision': comision,  # ✨ NUEVO: mostrar comisión
            'isr': isr,
            'iva': iva,
            'impuestos_totales': impuestos_totales,
            'ingreso_neto': ingreso_neto,
            'costo_odoo': round(costo_odoo, 2) if costo_odoo else 0.0,
            'costo_con_iva': costo_con_iva,
            'ganancia_neta': ganancia_neta,
            'ganancia_porcentaje': ganancia_porcentaje,
            'margen_saludable': margen_saludable,
            'mensaje_margen': "✅ MARGEN SALUDABLE" if margen_saludable else "⚠️ MARGEN BAJO"
        }
    except Exception as e:
        logger.error(f"❌ Error en cálculo de ganancia: {e}")
        return {
            'ingreso_bruto': 0.0,
            'comision': 0.0,
            'isr': 0.0,
            'iva': 0.0,
            'impuestos_totales': 0.0,
            'ingreso_neto': 0.0,
            'costo_odoo': 0.0,
            'costo_con_iva': 0.0,
            'ganancia_neta': 0.0,
            'ganancia_porcentaje': 0.0,
            'margen_saludable': False,
            'mensaje_margen': '❌ ERROR EN CÁLCULO'
        }

# ==========================================
# 📊 FUNCIONES DE ANÁLISIS AVANZADO - FASE 3B
# ==========================================

@st.cache_data(ttl=300)
def get_analisis_tendencias(dias: int = 7) -> dict:
    """Obtiene tendencias de precio últimos X días"""
    try:
        query = f"""
        SELECT 
            sku_interno,
            DATE(fecha_hora) as fecha,
            AVG(nuestro_precio::float) as precio_promedio,
            MIN(nuestro_precio::float) as precio_min,
            MAX(nuestro_precio::float) as precio_max,
            COUNT(*) as cambios
        FROM historial_precios
        WHERE fecha_hora >= NOW() - INTERVAL '{dias} days'
        GROUP BY sku_interno, DATE(fecha_hora)
        ORDER BY fecha DESC
        """
        df = db.execute_query(query)
        return {"data": df, "success": not df.empty}
    except Exception as e:
        logger.error(f"❌ Error en tendencias: {e}")
        return {"data": None, "success": False}

@st.cache_data(ttl=300)
def get_top_skus_performance(dias: int = 7) -> dict:
    """Obtiene Top 10 SKUs por ganancia CORRECTA - Usa ÚLTIMO PRECIO (dinámico)"""
    try:
        query = f"""
        SELECT 
            c.sku_limpio,
            c.sku_interno,
            c.precio_minimo,
            c.precio_maximo,
            c.costo_odoo::float as costo,
            c.regla_estrategia as regla,
            COUNT(h.id) as cambios_realizados
        FROM catalogo_maestro_v3 c
        LEFT JOIN historial_precios h ON c.sku_interno = h.sku_interno
            AND h.fecha_hora >= NOW() - INTERVAL '{dias} days'
        WHERE c.estatus = 'ACTIVO' AND c.costo_odoo IS NOT NULL AND c.costo_odoo > 0
        GROUP BY c.sku_limpio, c.sku_interno, c.precio_minimo, c.precio_maximo, c.costo_odoo, c.regla_estrategia
        ORDER BY c.sku_interno
        """
        df = db.execute_query(query)
        
        if df.empty:
            return {"data": None, "success": False}
        
        # ✨ OBTENER ÚLTIMOS PRECIOS EN BATCH (más eficiente)
        ultimos_precios = get_ultimos_precios_batch(dias)
        
        # ✨ APLICAR FÓRMULA CORRECTA A CADA ROW - Usa ÚLTIMO PRECIO
        ganancia_neta_list = []
        ganancia_porc_list = []
        margen_saludable_list = []
        precio_actual_list = []
        
        for idx, row in df.iterrows():
            # ✨ Obtener último precio registrado (dinámico)
            ultimo_precio = ultimos_precios.get(row['sku_interno'], 0.0)
            
            if ultimo_precio <= 0:
                # Si no hay último precio, usar promedio entre min y max
                precio_venta = (row['precio_minimo'] + row['precio_maximo']) / 2
            else:
                precio_venta = ultimo_precio  # ✨ USA ÚLTIMO PRECIO
            
            precio_actual_list.append(precio_venta)
            resultado = calcular_ganancia_correcta(precio_venta, row['costo'])
            
            ganancia_neta_list.append(resultado['ganancia_neta'])
            ganancia_porc_list.append(resultado['ganancia_porcentaje'])
            margen_saludable_list.append(resultado['margen_saludable'])
        
        df['precio_actual'] = precio_actual_list  # ✨ NUEVO: muestra último precio
        df['ganancia_neta'] = ganancia_neta_list
        df['ganancia_porcentaje'] = ganancia_porc_list
        df['margen_saludable'] = margen_saludable_list
        
        # Ordenar por ganancia neta descendente
        df = df.sort_values('ganancia_neta', ascending=False).head(10)
        
        return {"data": df, "success": True}
    except Exception as e:
        logger.error(f"❌ Error en top SKUs: {e}")
        return {"data": None, "success": False}

@st.cache_data(ttl=300)
def get_analisis_margen(dias: int = 7) -> dict:
    """Análisis de margen CORRECTO - Usa ÚLTIMO PRECIO (dinámico, no promedio)"""
    try:
        query = f"""
        SELECT 
            c.sku_limpio,
            c.sku_interno,
            c.precio_minimo,
            c.precio_maximo,
            AVG(CASE WHEN h.precio_rival ~ '^[0-9.]+$' THEN h.precio_rival::float ELSE NULL END) as precio_rival,
            c.costo_odoo::float as costo
        FROM catalogo_maestro_v3 c
        LEFT JOIN historial_precios h ON c.sku_interno = h.sku_interno
            AND h.fecha_hora >= NOW() - INTERVAL '{dias} days'
        WHERE c.estatus = 'ACTIVO' AND c.costo_odoo IS NOT NULL AND c.costo_odoo > 0
        GROUP BY c.sku_limpio, c.sku_interno, c.precio_minimo, c.precio_maximo, c.costo_odoo
        ORDER BY c.sku_interno
        """
        df = db.execute_query(query)
        
        if df.empty:
            return {"data": None, "success": False}
        
        # ✨ OBTENER ÚLTIMOS PRECIOS EN BATCH
        ultimos_precios = get_ultimos_precios_batch(dias)
        
        # ✨ APLICAR FÓRMULA CORRECTA A CADA ROW - Usa ÚLTIMO PRECIO
        ingreso_neto_list = []
        ganancia_neta_list = []
        ganancia_porc_list = []
        margen_saludable_list = []
        diferencia_precio_list = []
        nuestro_precio_list = []
        
        for idx, row in df.iterrows():
            # ✨ Obtener último precio (dinámico)
            ultimo_precio = ultimos_precios.get(row['sku_interno'], 0.0)
            
            if ultimo_precio <= 0:
                precio_venta = (row['precio_minimo'] + row['precio_maximo']) / 2
            else:
                precio_venta = ultimo_precio  # ✨ USA ÚLTIMO PRECIO
            
            nuestro_precio_list.append(precio_venta)
            resultado = calcular_ganancia_correcta(precio_venta, row['costo'])
            
            ingreso_neto_list.append(resultado['ingreso_neto'])
            ganancia_neta_list.append(resultado['ganancia_neta'])
            ganancia_porc_list.append(resultado['ganancia_porcentaje'])
            margen_saludable_list.append(resultado['margen_saludable'])
            
            # Diferencia de precio vs rivales
            if pd.notna(row['precio_rival']):
                diferencia_precio_list.append(precio_venta - row['precio_rival'])
            else:
                diferencia_precio_list.append(0.0)
        
        df['nuestro_precio'] = nuestro_precio_list  # ✨ ACTUAL (último precio)
        df['ingreso_neto'] = ingreso_neto_list
        df['ganancia_neta'] = ganancia_neta_list
        df['margen_porcentaje'] = ganancia_porc_list
        df['margen_saludable'] = margen_saludable_list
        df['diferencia_precio'] = diferencia_precio_list
        
        # Ordenar por margen porcentaje descendente
        df = df.sort_values('margen_porcentaje', ascending=False)
        
        return {"data": df, "success": True}
    except Exception as e:
        logger.error(f"❌ Error en margen: {e}")
        return {"data": None, "success": False}

@st.cache_data(ttl=300)
def get_competencia_precios(dias: int = 7) -> dict:
    """Análisis de competencia vs rivales"""
    try:
        query = f"""
        SELECT 
            c.sku_limpio,
            c.sku_interno,
            AVG(h.nuestro_precio::float) as nuestro_precio,
            AVG(CASE WHEN h.precio_rival ~ '^[0-9.]+$' THEN h.precio_rival::float ELSE NULL END) as precio_rival,
            COUNT(DISTINCT h.fecha_hora::date) as dias_monitoreados,
            COUNT(h.id) as total_cambios,
            CASE 
                WHEN AVG(CASE WHEN h.precio_rival ~ '^[0-9.]+$' THEN h.precio_rival::float ELSE NULL END) > AVG(h.nuestro_precio::float) THEN '✅ MÁS BAJO'
                WHEN AVG(CASE WHEN h.precio_rival ~ '^[0-9.]+$' THEN h.precio_rival::float ELSE NULL END) < AVG(h.nuestro_precio::float) THEN '⚠️ MÁS ALTO'
                ELSE '⚖️ IGUAL'
            END as posicion
        FROM catalogo_maestro_v3 c
        LEFT JOIN historial_precios h ON c.sku_interno = h.sku_interno
            AND h.fecha_hora >= NOW() - INTERVAL '{dias} days'
        WHERE c.estatus = 'ACTIVO' AND h.precio_rival IS NOT NULL
        GROUP BY c.sku_limpio, c.sku_interno
        ORDER BY ABS(AVG(CASE WHEN h.precio_rival ~ '^[0-9.]+$' THEN h.precio_rival::float ELSE NULL END) - AVG(h.nuestro_precio::float)) DESC
        LIMIT 20
        """
        df = db.execute_query(query)
        return {"data": df, "success": not df.empty}
    except Exception as e:
        logger.error(f"❌ Error en competencia: {e}")
        return {"data": None, "success": False}

@st.cache_data(ttl=300)
def get_heatmap_actividad(dias: int = 7) -> dict:
    """Heatmap de actividad por hora del día"""
    try:
        query = f"""
        SELECT 
            EXTRACT(HOUR FROM fecha_hora) as hora,
            COUNT(id) as cambios,
            COUNT(DISTINCT DATE(fecha_hora)) as dias_activos
        FROM historial_precios
        WHERE fecha_hora >= NOW() - INTERVAL '{dias} days'
        GROUP BY EXTRACT(HOUR FROM fecha_hora)
        ORDER BY hora
        """
        df = db.execute_query(query)
        return {"data": df, "success": not df.empty}
    except Exception as e:
        logger.error(f"❌ Error en heatmap: {e}")
        return {"data": None, "success": False}

@st.cache_data(ttl=300)
def get_distribucion_precios(dias: int = 7) -> dict:
    """Distribución de precios por rangos"""
    try:
        query = f"""
        SELECT 
            CASE 
                WHEN h.nuestro_precio::float < 100 THEN '$0-100'
                WHEN h.nuestro_precio::float < 500 THEN '$100-500'
                WHEN h.nuestro_precio::float < 1000 THEN '$500-1000'
                WHEN h.nuestro_precio::float < 5000 THEN '$1000-5000'
                ELSE '$5000+'
            END as rango_precio,
            COUNT(DISTINCT c.sku_interno) as cantidad_skus,
            AVG(h.nuestro_precio::float) as precio_promedio
        FROM historial_precios h
        JOIN catalogo_maestro_v3 c ON h.sku_interno = c.sku_interno
        WHERE h.fecha_hora >= NOW() - INTERVAL '{dias} days'
            AND c.estatus = 'ACTIVO'
        GROUP BY rango_precio
        ORDER BY MIN(h.nuestro_precio::float)
        """
        df = db.execute_query(query)
        return {"data": df, "success": not df.empty}
    except Exception as e:
        logger.error(f"❌ Error en distribución: {e}")
        return {"data": None, "success": False}

@st.cache_data(ttl=300)
def get_skus_criticos(dias: int = 7) -> dict:
    """SKUs críticos con margen < 10% (ALERTA ROJA) - Usa ÚLTIMO PRECIO"""
    try:
        query = f"""
        SELECT 
            c.sku_limpio,
            c.sku_interno,
            c.precio_minimo,
            c.precio_maximo,
            c.costo_odoo::float as costo,
            c.estatus,
            c.regla_estrategia
        FROM catalogo_maestro_v3 c
        WHERE c.estatus = 'ACTIVO' AND c.costo_odoo IS NOT NULL AND c.costo_odoo > 0
        ORDER BY c.sku_interno
        """
        df = db.execute_query(query)
        
        if df.empty:
            return {"data": None, "success": False}
        
        # ✨ OBTENER ÚLTIMOS PRECIOS EN BATCH
        ultimos_precios = get_ultimos_precios_batch(dias)
        
        # ✨ APLICAR FÓRMULA CORRECTA A CADA ROW - Usa ÚLTIMO PRECIO
        margen_porc_list = []
        margen_saludable_list = []
        ganancia_neta_list = []
        precio_actual_list = []
        
        for idx, row in df.iterrows():
            # ✨ Obtener último precio (dinámico)
            ultimo_precio = ultimos_precios.get(row['sku_interno'], 0.0)
            
            if ultimo_precio <= 0:
                precio_venta = (row['precio_minimo'] + row['precio_maximo']) / 2
            else:
                precio_venta = ultimo_precio  # ✨ USA ÚLTIMO PRECIO
            
            precio_actual_list.append(precio_venta)
            resultado = calcular_ganancia_correcta(precio_venta, row['costo'])
            
            margen_porc_list.append(resultado['ganancia_porcentaje'])
            margen_saludable_list.append(resultado['margen_saludable'])
            ganancia_neta_list.append(resultado['ganancia_neta'])
        
        df['precio_actual'] = precio_actual_list  # ✨ NUEVO: precio dinámico
        df['margen_porcentaje'] = margen_porc_list
        df['margen_saludable'] = margen_saludable_list
        df['ganancia_neta'] = ganancia_neta_list
        
        # FILTRAR: Solo SKUs con margen < 10%
        df_criticos = df[df['margen_porcentaje'] < 10].sort_values('margen_porcentaje', ascending=True).head(15)
        
        return {"data": df_criticos if not df_criticos.empty else None, "success": not df_criticos.empty}
    except Exception as e:
        logger.error(f"❌ Error en SKUs críticos: {e}")
        return {"data": None, "success": False}

# ==========================================
# 🚀 MAIN LOGIC
# =========================================

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
