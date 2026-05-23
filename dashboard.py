#!/usr/bin/env python3
# ==========================================
# MEGAZORD WAR ROOM - DASHBOARD ENTERPRISE V2.0
# Centro de Comando Ejecutivo con BI Real-Time
# ==========================================
# Arquitecto: Senior Software Architect
# BI Specialist: Enterprise Dashboard Designer
# 
# 🚀 MIGRACION COMPLETA: Google Sheets → PostgreSQL Warp Speed
# 🎨 DISEÑO: Dark Mode Executive (Tesla/Bloomberg Style)
# 📊 VISUALIZACIONES: Plotly Interactive + Real-Time Metrics
# 🔐 SEGURIDAD: Password Protection + Role-Based Views
# ==========================================

import streamlit as st
import pandas as pd
import numpy as np
import psycopg2
from psycopg2 import pool
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import logging
from typing import Dict, List, Tuple, Optional
import hashlib
import json
from functools import wraps
import time

# ==========================================
# 🔧 CONFIGURACIÓN & LOGGING
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(message)s'
)
logger = logging.getLogger(__name__)

# Set Streamlit page config FIRST
st.set_page_config(
    page_title="🤖 MEGAZORD War Room",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://github.com/FernandoWABU/megazord-wabu-core',
        'Report a bug': 'https://github.com/FernandoWABU/megazord-wabu-core/issues',
        'About': "Enterprise Repricing War Room v2.0"
    }
)

# ==========================================
# 🎨 DARK MODE CSS - TESLA/BLOOMBERG STYLE
# ==========================================

DARK_MODE_CSS = """
<style>
    :root {
        --primary-dark: #0a0e27;
        --secondary-dark: #1a1f3a;
        --accent-blue: #00d9ff;
        --accent-green: #1db954;
        --accent-red: #ff003c;
        --text-primary: #ffffff;
        --text-secondary: #b0bec5;
        --border-color: #00d9ff;
    }

    /* Fondo principal */
    .main {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
        color: #ffffff;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f1428 0%, #1a1f3a 100%);
        border-right: 2px solid #00d9ff;
    }

    /* Títulos */
    h1, h2, h3 {
        color: #00d9ff;
        text-shadow: 0 0 10px rgba(0, 217, 255, 0.3);
        font-weight: 700;
        letter-spacing: 1px;
    }

    /* Métricas brillantes */
    .metric-box {
        background: linear-gradient(135deg, #1a1f3a 0%, #0f2540 100%);
        border: 2px solid #00d9ff;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 0 20px rgba(0, 217, 255, 0.2);
        transition: all 0.3s ease;
    }

    .metric-box:hover {
        border-color: #1db954;
        box-shadow: 0 0 30px rgba(0, 255, 65, 0.3);
    }

    /* Botones */
    .stButton > button {
        background: linear-gradient(135deg, #00d9ff 0%, #1db954 100%);
        color: #0a0e27;
        border: none;
        border-radius: 6px;
        font-weight: bold;
        padding: 12px 24px;
        transition: all 0.3s ease;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .stButton > button:hover {
        transform: scale(1.05);
        box-shadow: 0 0 20px rgba(0, 255, 65, 0.4);
    }

    /* Input fields */
    .stTextInput > div > div > input,
    .stPasswordInput > div > div > input,
    .stNumberInput > div > div > input {
        background: #1a1f3a;
        color: #ffffff;
        border: 2px solid #00d9ff;
        border-radius: 6px;
        padding: 10px 15px;
    }

    .stTextInput > div > div > input:focus,
    .stPasswordInput > div > div > input:focus,
    .stNumberInput > div > div > input:focus {
        border-color: #1db954;
        box-shadow: 0 0 10px rgba(0, 255, 65, 0.2);
    }

    /* Tables */
    .stDataFrame {
        background: #1a1f3a;
        border: 2px solid #00d9ff;
    }

    /* Status indicators */
    .status-green {
        color: #1db954;
        font-weight: bold;
    }

    .status-red {
        color: #ff003c;
        font-weight: bold;
    }

    .status-yellow {
        color: #ffaa00;
        font-weight: bold;
    }

    /* Alerts */
    .alert-box {
        background: rgba(255, 0, 60, 0.1);
        border-left: 4px solid #ff003c;
        padding: 15px;
        border-radius: 4px;
        margin: 10px 0;
    }

    .success-box {
        background: rgba(0, 255, 65, 0.1);
        border-left: 4px solid #1db954;
        padding: 15px;
        border-radius: 4px;
        margin: 10px 0;
    }
</style>
"""

st.markdown(DARK_MODE_CSS, unsafe_allow_html=True)

# ==========================================
# 🔐 SEGURIDAD & AUTENTICACIÓN
# ==========================================

class AuthManager:
    """Gestor de autenticación con contraseña hasheada"""
    
    def __init__(self):
        self.password_hash = os.getenv("DASHBOARD_PASSWORD", "megazord2025")
        self.session_timeout = 3600  # 1 hora
    
    def hash_password(self, password: str) -> str:
        """Hash seguro de contraseña"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def verify_password(self, password: str) -> bool:
        """Verifica contraseña (Comparación directa con Streamlit Secrets)"""
        return password == self.password_hash
    
    def is_authenticated(self) -> bool:
        """Verifica si el usuario está autenticado"""
        if 'auth_time' not in st.session_state:
            return False
        
        elapsed = time.time() - st.session_state['auth_time']
        if elapsed > self.session_timeout:
            st.session_state['authenticated'] = False
            return False
        
        return st.session_state.get('authenticated', False)
    
    def login(self, password: str) -> bool:
        """Autentica usuario"""
        if self.verify_password(password):
            st.session_state['authenticated'] = True
            st.session_state['auth_time'] = time.time()
            return True
        return False

# ==========================================
# 🗄️ GESTOR DE BASE DE DATOS POSTGRESQL
# ==========================================

class PostgreSQLManager:
    """Gestor de conexiones PostgreSQL con pool y cache"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool = None
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Inicializa connection pool"""
        try:
            self._pool = psycopg2.pool.SimpleConnectionPool(
                1,  # min
                10, # max
                self.database_url,
                connect_timeout=5
            )
            logger.info("✅ PostgreSQL connection pool initialized")
        except Exception as e:
            logger.error(f"❌ Error initializing pool: {e}")
            st.error("❌ No se pudo conectar a PostgreSQL")
    
    def execute_query(self, query: str, params: tuple = None) -> pd.DataFrame:
        """Ejecuta query y retorna DataFrame"""
        try:
            conn = self._pool.getconn()
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()
            
            cursor.close()
            self._pool.putconn(conn)
            
            return pd.DataFrame(data, columns=columns)
        
        except Exception as e:
            logger.error(f"❌ Query error: {e}")
            return pd.DataFrame()
    
    def execute_update(self, query: str, params: tuple = None) -> bool:
        """Ejecuta UPDATE/INSERT/DELETE"""
        try:
            conn = self._pool.getconn()
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            conn.commit()
            affected_rows = cursor.rowcount
            
            cursor.close()
            self._pool.putconn(conn)
            
            logger.info(f"✅ {affected_rows} rows affected")
            return True
        
        except Exception as e:
            logger.error(f"❌ Update error: {e}")
            if conn:
                conn.rollback()
                self._pool.putconn(conn)
            return False
    
    def close(self):
        """Cierra todos los pools"""
        if self._pool:
            self._pool.closeall()

# ==========================================
# 💾 INICIALIZACIÓN GLOBAL
# ==========================================

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    st.error("❌ DATABASE_URL no configurado en variables de entorno")
    st.stop()

db = PostgreSQLManager(DATABASE_URL)
auth = AuthManager()

# ==========================================
# 📊 QUERIES OPTIMIZADAS CON CACHE (ALINEACIÓN TOTAL DE COLUMNAS)
# ==========================================

@st.cache_data(ttl=300)
def get_historial_precios(days: int = 7) -> pd.DataFrame:
    limit_date = datetime.now() - timedelta(days=days)
    query = """
    SELECT 
        h.fecha_hora AS created_at,
        h.fecha_hora,
        h.sku_interno,
        c.sku_limpio,
        h.precio_rival AS precio_ant,
        h.nuestro_precio AS precio_nuv,
        h.stock,
        h.posicion,
        h.buybox AS resultado
    FROM historial_precios h
    LEFT JOIN catalogo_maestro_v3 c ON h.sku_interno = c.sku_interno
    WHERE h.fecha_hora >= %s
    ORDER BY h.fecha_hora DESC
    LIMIT 50000
    """
    return db.execute_query(query, (limit_date,))

@st.cache_data(ttl=300)
def get_monitoreo_rivales(limit: int = 1000) -> pd.DataFrame:
    query = """
    SELECT 
        c.sku_interno,
        c.sku_limpio,
        m.nombre_rival,
        m.precio_rival as precio,
        m.marketplace,
        m.created_at,
        COUNT(*) OVER (PARTITION BY m.nombre_rival) as apariciones_rival
    FROM monitoreo_rivales m
    LEFT JOIN catalogo_maestro_v3 c ON m.catalogo_id = c.id
    ORDER BY m.created_at DESC
    LIMIT %s
    """
    return db.execute_query(query, (limit,))

@st.cache_data(ttl=300)
def get_catalogo_maestro() -> pd.DataFrame:
    query = """
    SELECT 
        id,
        sku_limpio,
        sku_limpio as sku, -- Auxiliar para el st.data_editor
        sku_interno,
        sku_liverpool,
        sku_walmart,
        sku_coppel,
        precio_minimo,
        precio_maximo,
        costo_odoo,
        estatus
    FROM catalogo_maestro_v3
    ORDER BY sku_limpio
    """
    return db.execute_query(query)

@st.cache_data(ttl=300)
def get_alertas() -> pd.DataFrame:
    query = """
    SELECT 
        id,
        tipo_alerta AS tipo,
        mensaje,
        severidad AS severity,
        created_at,
        resuelta
    FROM alertas
    WHERE resuelta = FALSE
    ORDER BY created_at DESC
    LIMIT 100
    """
    return db.execute_query(query)

@st.cache_data(ttl=600)
def get_metrics_dashboard() -> Dict:
    df_catalogo = get_catalogo_maestro()
    total_skus = len(df_catalogo)
    
    limit_date = datetime.now() - timedelta(days=1)
    query_24h = "SELECT COUNT(*) as cambios FROM historial_precios WHERE fecha_hora >= %s"
    df_24h = db.execute_query(query_24h, (limit_date,))
    cambios_24h = df_24h.iloc[0, 0] if len(df_24h) > 0 else 0
    
    limit_date_7d = datetime.now() - timedelta(days=7)
    query_buybox = """
    SELECT 
        COUNT(CASE WHEN UPPER(buybox) IN ('EJECUTADO', 'SÍ', 'SI', 'TRUE') THEN 1 END) as ganadas,
        COUNT(*) as total
    FROM historial_precios
    WHERE fecha_hora >= %s
    """
    df_buybox = db.execute_query(query_buybox, (limit_date_7d,))
    if len(df_buybox) > 0:
        ganadas = df_buybox.iloc[0]['ganadas']
        total = df_buybox.iloc[0]['total']
        win_rate = (ganadas / total * 100) if total > 0 else 0
    else:
        win_rate = 0
    
    df_rivales = get_monitoreo_rivales()
    rivales_unicos = df_rivales['nombre_rival'].nunique() if len(df_rivales) > 0 else 0
    
    query_margen = "SELECT AVG(nuestro_precio - precio_rival) as margen_promedio FROM historial_precios WHERE fecha_hora >= %s"
    df_margen = db.execute_query(query_margen, (limit_date_7d,))
    margen_promedio = df_margen.iloc[0, 0] if len(df_margen) > 0 else 0
    
    return {
        'total_skus': total_skus,
        'cambios_24h': int(cambios_24h),
        'win_rate_buybox': round(win_rate, 1),
        'rivales_unicos': rivales_unicos,
        'margen_promedio': round(float(margen_promedio), 2) if margen_promedio else 0
    }

# ==========================================
# 🎨 COMPONENTES UI REUTILIZABLES
# ==========================================

def render_metric_card(title: str, value: str, subtitle: str = "", 
                       status: str = "neutral", icon: str = "📊"):
    """Renderiza card de métrica estilo Tesla/Bloomberg"""
    
    colors = {
        'positive': '#1db954',
        'negative': '#ff003c',
        'neutral': '#00d9ff',
        'warning': '#ffaa00'
    }
    
    color = colors.get(status, colors['neutral'])
    
    html = f"""
    <div class="metric-box" style="border-color: {color};">
        <div style="display: flex; justify-content: space-between; align-items: start;">
            <div>
                <p style="color: #b0bec5; margin: 0; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;">
                    {title}
                </p>
                <h2 style="color: {color}; margin: 10px 0 0 0; font-size: 32px; font-weight: bold;">
                    {value}
                </h2>
                {f'<p style="color: #b0bec5; margin: 5px 0 0 0; font-size: 12px;">{subtitle}</p>' if subtitle else ''}
            </div>
            <div style="font-size: 40px; opacity: 0.5;">{icon}</div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

def render_alert_box(message: str, alert_type: str = "info"):
    """Renderiza box de alerta"""
    
    colors = {
        'success': '#1db954',
        'error': '#ff003c',
        'warning': '#ffaa00',
        'info': '#00d9ff'
    }
    
    color = colors.get(alert_type, colors['info'])
    class_name = f"{alert_type}-box"
    
    html = f"""
    <div style="background: rgba(0, 217, 255, 0.1); border-left: 4px solid {color}; padding: 15px; border-radius: 4px; margin: 10px 0;">
        <p style="color: {color}; margin: 0; font-weight: bold;">{message}</p>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# ==========================================
# 📱 PÁGINA DE LOGIN
# ==========================================

def show_login_page():
    """Página de autenticación"""
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("<br>" * 3, unsafe_allow_html=True)
        
        st.markdown("""
        <div style="text-align: center;">
            <h1 style="color: #00d9ff; font-size: 48px; text-shadow: 0 0 20px rgba(0, 217, 255, 0.5);">
                ⚡ MEGAZORD WAR ROOM
            </h1>
            <p style="color: #b0bec5; font-size: 16px; letter-spacing: 2px;">
                CENTRO DE COMANDO EJECUTIVO
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<br>" * 2, unsafe_allow_html=True)
        
        password = st.text_input(
            "🔐 Contraseña de Acceso",
            type="password",
            placeholder="Ingresa contraseña del Comandante"
        )
        
        if st.button("🚀 ACCESO RESTRINGIDO", use_container_width=True):
            if auth.login(password):
                st.success("✅ ¡Bienvenido Comandante!")
                st.rerun()
            else:
                st.error("❌ Contraseña incorrecta")
        
        st.markdown("<br>" * 5, unsafe_allow_html=True)
        
        # Public preview (sin datos sensibles)
        st.markdown("---")
        st.markdown("""
        <div style="text-align: center; opacity: 0.6;">
            <p style="color: #b0bec5; font-size: 12px;">
                📊 Dashboard Público (Lectura):<br>
                Acceso sin contraseña a gráficas ejecutivas
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("📈 Ver Visualizaciones Públicas", use_container_width=True):
            st.session_state['public_view'] = True
            st.rerun()

# ==========================================
# 📊 SECCIÓN PÚBLICA (VISUALIZACIONES)
# ==========================================

def show_public_dashboard():
    """Dashboard público con visualizaciones (sin editor de datos)"""
    
    st.markdown("""
    <h1 style="color: #00d9ff; text-shadow: 0 0 10px rgba(0, 217, 255, 0.3);">
        📊 CENTRO DE INTELIGENCIA EJECUTIVA - MODO LECTURA
    </h1>
    """, unsafe_allow_html=True)
    
    st.markdown("*Última actualización: * " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    # ========== MÉTRICAS PRINCIPALES ==========
    st.markdown("### 📈 MÉTRICAS CLAVE (7 días)")
    
    try:
        metrics = get_metrics_dashboard()
        
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            render_metric_card(
                "Total SKUs Activos",
                f"{metrics['total_skus']:,}",
                "Catálogo Master",
                "positive",
                "📦"
            )
        
        with col2:
            render_metric_card(
                "Cambios 24h",
                f"{metrics['cambios_24h']:,}",
                "Actualizaciones",
                "neutral",
                "⚡"
            )
        
        with col3:
            status = "positive" if metrics['win_rate_buybox'] >= 50 else "negative"
            render_metric_card(
                "Win Rate BuyBox",
                f"{metrics['win_rate_buybox']:.1f}%",
                "Victorias",
                status,
                "👑"
            )
        
        with col4:
            render_metric_card(
                "Rivales Únicos",
                f"{metrics['rivales_unicos']}",
                "Monitoreados",
                "warning",
                "🎯"
            )
        
        with col5:
            status = "positive" if metrics['margen_promedio'] > 0 else "negative"
            render_metric_card(
                "Margen Promedio",
                f"${metrics['margen_promedio']:.2f}",
                "Diferencia precio",
                status,
                "💰"
            )
    
    except Exception as e:
        st.error(f"❌ Error cargando métricas: {e}")
        return
    
    st.markdown("---")
    
    # ========== GRÁFICAS PLOTLY ==========
    st.markdown("### 🎯 VISUALIZACIONES INTERACTIVAS")
    
    # Tabs para diferentes vistas
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📊 Win Rate", "🏆 Top Rivales", "📈 Margen Dinámico", "⏰ Timeline"]
    )
    
    with tab1:
        st.markdown("#### Win Rate de BuyBox (Últimos 7 días)")
        
        try:
            query = """
            SELECT 
                buybox,
                COUNT(*) as cantidad
            FROM historial_precios
            WHERE fecha_hora >= NOW() - INTERVAL '7 days'
            GROUP BY buybox
            """
            df = db.execute_query(query)
            
            if len(df) > 0:
                # Convertir 'Sí' a 'Ganado' y 'No' a 'Perdido'
                df['Estado'] = df['buybox'].apply(
                    lambda x: '✅ GANADO' if x == 'Sí' else '❌ PERDIDO'
                )
                
                fig = px.pie(
                    df,
                    values='cantidad',
                    names='Estado',
                    title='Distribución de Victorias en BuyBox',
                    color_discrete_map={
                        '✅ GANADO': '#1db954',
                        '❌ PERDIDO': '#ff003c'
                    },
                    hole=0.4  # Dona
                )
                
                fig.update_layout(
                    paper_bgcolor='rgba(10, 14, 39, 0)',
                    plot_bgcolor='rgba(10, 14, 39, 0)',
                    font=dict(color='#ffffff', family='Arial'),
                    showlegend=True,
                    hovermode='closest'
                )
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("⚠️ Sin datos disponibles para este período")
        
        except Exception as e:
            st.error(f"❌ Error en gráfica: {e}")
    
    with tab2:
        st.markdown("#### 🏆 TOP 10 Competidores Más Agresivos")
        
        try:
            df_rivales = get_monitoreo_rivales(limit=1000)
            
            if len(df_rivales) > 0:
                # Top 10 rivales
                top_rivales = df_rivales['nombre_rival'].value_counts().head(10)
                
                fig = px.bar(
                    x=top_rivales.values,
                    y=top_rivales.index,
                    orientation='h',
                    title='Rivales Detectados por Frecuencia',
                    labels={'x': 'Apariciones', 'y': 'Nombre Rival'},
                    color=top_rivales.values,
                    color_continuous_scale='blues'
                )
                
                fig.update_layout(
                    paper_bgcolor='rgba(10, 14, 39, 0)',
                    plot_bgcolor='rgba(26, 31, 58, 0.5)',
                    font=dict(color='#ffffff', family='Arial'),
                    showlegend=False,
                    hovermode='closest',
                    xaxis_title='Frecuencia de Detección',
                    yaxis_title='Nombre del Rival'
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Tabla detallada
                st.markdown("#### Detalles de Rivales:")
                cols = st.columns(3)
                for idx, (rival, count) in enumerate(top_rivales.head(9).items()):
                    col = cols[idx % 3]
                    with col:
                        render_metric_card(
                            rival[:20],
                            str(count),
                            "detecciones",
                            "warning",
                            "🎯"
                        )
            else:
                st.warning("⚠️ Sin rivales detectados")
        
        except Exception as e:
            st.error(f"❌ Error en Top Rivales: {e}")
    
    with tab3:
        st.markdown("#### 📈 Evolución de Margen Dinámico")
        
        try:
            query = """
            SELECT 
                DATE(fecha_hora) as fecha,
                DATE(fecha_hora) as created_at, -- Auxiliar para compatibilidad de layout
                AVG(nuestro_precio - precio_rival) as margen_promedio,
                MIN(nuestro_precio - precio_rival) as margen_minimo,
                MAX(nuestro_precio - precio_rival) as margen_maximo
            FROM historial_precios
            WHERE fecha_hora >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(fecha_hora)
            ORDER BY fecha
            """
            
            df = db.execute_query(query)
            
            if len(df) > 0:
                fig = go.Figure()
                
                fig.add_trace(go.Scatter(
                    x=df['fecha'],
                    y=df['margen_promedio'],
                    mode='lines+markers',
                    name='Margen Promedio',
                    line=dict(color='#00d9ff', width=3),
                    marker=dict(size=8)
                ))
                
                fig.add_trace(go.Scatter(
                    x=df['fecha'],
                    y=df['margen_maximo'],
                    name='Máximo',
                    line=dict(color='#1db954', width=2, dash='dot'),
                    fill=None
                ))
                
                fig.add_trace(go.Scatter(
                    x=df['fecha'],
                    y=df['margen_minimo'],
                    name='Mínimo',
                    line=dict(color='#ff003c', width=2, dash='dot'),
                    fill='tonexty'
                ))
                
                fig.update_layout(
                    title='Margen de Precio vs Competencia (30 días)',
                    paper_bgcolor='rgba(10, 14, 39, 0)',
                    plot_bgcolor='rgba(26, 31, 58, 0.3)',
                    font=dict(color='#ffffff'),
                    hovermode='x unified',
                    xaxis_title='Fecha',
                    yaxis_title='Margen ($)'
                )
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("⚠️ Sin datos históricos disponibles")
        
        except Exception as e:
            st.error(f"❌ Error en Timeline: {e}")
    
    with tab4:
        st.markdown("#### ⏰ Actividad por Hora del Día")
        
        try:
            query = """
            SELECT 
                EXTRACT(HOUR FROM fecha_hora)::int as hora,
                COUNT(*) as cambios,
                AVG(nuestro_precio - precio_rival) as margen
            FROM historial_precios
            WHERE fecha_hora >= NOW() - INTERVAL '7 days'
            GROUP BY EXTRACT(HOUR FROM fecha_hora)
            ORDER BY hora
            """
            
            df = db.execute_query(query)
            
            if len(df) > 0:
                fig = px.bar(
                    df,
                    x='hora',
                    y='cambios',
                    color='margen',
                    color_continuous_scale='viridis',
                    title='Actividad del Repricing por Hora',
                    labels={'hora': 'Hora del Día', 'cambios': 'Cambios de Precio'}
                )
                
                fig.update_layout(
                    paper_bgcolor='rgba(10, 14, 39, 0)',
                    plot_bgcolor='rgba(26, 31, 58, 0.5)',
                    font=dict(color='#ffffff'),
                    xaxis=dict(tickformat='0h')
                )
                
                st.plotly_chart(fig, use_container_width=True)
        
        except Exception as e:
            st.error(f"❌ Error: {e}")
    
    st.markdown("---")
    
    # ========== ALERTAS ==========
    st.markdown("### 🚨 ALERTAS ACTIVAS")
    
    try:
        df_alertas = get_alertas()
        
        if len(df_alertas) > 0:
            critical_alerts = len(df_alertas[df_alertas['severity'] == 'CRITICAL'])
            warning_alerts = len(df_alertas[df_alertas['severity'] == 'WARNING'])
            
            col1, col2 = st.columns(2)
            
            with col1:
                render_metric_card(
                    "Alertas Críticas",
                    str(critical_alerts),
                    "Requieren acción inmediata",
                    "negative" if critical_alerts > 0 else "positive",
                    "🚨"
                )
            
            with col2:
                render_metric_card(
                    "Alertas de Aviso",
                    str(warning_alerts),
                    "Requieren monitoreo",
                    "warning",
                    "⚠️"
                )
            
            # Mostrar alertas recientes
            st.markdown("#### Últimas Alertas:")
            for idx, row in df_alertas.head(5).iterrows():
                color = '#ff003c' if row['severity'] == 'CRITICAL' else '#ffaa00'
                st.markdown(f"""
                <div style="background: rgba(255, 0, 60, 0.1); border-left: 4px solid {color}; 
                           padding: 10px; margin: 5px 0; border-radius: 4px;">
                    <p style="color: {color}; margin: 0; font-weight: bold;">
                        [{row['tipo']}] {row['mensaje']}
                    </p>
                    <p style="color: #b0bec5; margin: 3px 0 0 0; font-size: 11px;">
                        {row['fecha_creacion']}
                    </p>
                </div>
                """, unsafe_allow_html=True)
        else:
            render_alert_box("✅ Sin alertas críticas en este momento", "success")
    
    except Exception as e:
        st.warning(f"⚠️ No se pudieron cargar alertas: {e}")
    
    # Botón para cambiar a vista privada
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("🔐 Acceso Privado (Comandante)", use_container_width=True):
            st.session_state['public_view'] = False
            st.rerun()

# ==========================================
# 🔐 SECCIÓN PRIVADA (EDITOR DE DATOS)
# ==========================================

def show_private_dashboard():
    """Dashboard privado con buscador inteligente multi-columna y editor de precios"""
    
    st.markdown("""
    <h1 style="color: #1db954; text-shadow: 0 0 10px rgba(29, 185, 84, 0.3);">
        🔐 SALA DE CONTROL EJECUTIVA - MODO COMANDANTE
    </h1>
    """, unsafe_allow_html=True)
    
    st.markdown(f"**🕐 Sesión activa desde:** {datetime.fromtimestamp(st.session_state.get('auth_time', time.time())).strftime('%H:%M:%S')}")
    
    # ========== EDITOR FINANCIERO CON BUSCADOR INTELIGENTE ==========
    st.markdown("### 💰 EDITOR FINANCIERO - Buscador Predictivo Universal")
    
    try:
        df_catalogo = get_catalogo_maestro()
        
        if len(df_catalogo) > 0:
            # 🟢 LA MEJORA: Barra de texto libre que busca en todas las columnas críticas en tiempo real
            termino_busqueda = st.text_input(
                "🔍 Ingresa cualquier identificador (SKU Limpio, SKU Interno, SKU Liverpool, Walmart o Coppel):",
                placeholder="Ej: HCK13.3atomizador, SKU_48819B..."
            )
            
            df_filtrado = df_catalogo.copy()
            if termino_busqueda:
                # Escáner multi-columna tolerante a mayúsculas y minúsculas
                df_filtrado = df_catalogo[
                    df_catalogo['sku_limpio'].astype(str).str.contains(termino_busqueda, case=False, na=False) |
                    df_catalogo['sku_interno'].astype(str).str.contains(termino_busqueda, case=False, na=False) |
                    df_catalogo['sku_liverpool'].astype(str).str.contains(termino_busqueda, case=False, na=False) |
                    df_catalogo['sku_walmart'].astype(str).str.contains(termino_busqueda, case=False, na=False) |
                    df_catalogo['sku_coppel'].astype(str).str.contains(termino_busqueda, case=False, na=False)
                ]
            
            if not df_filtrado.empty:
                # Generar etiquetas dinámicas ultra descriptivas para el menú desplegable
                opciones_formateadas = df_filtrado.apply(
                    lambda r: f"📦 {r['sku_limpio']} | Int: {r['sku_interno']} | LVP: {r['sku_liverpool'] or 'N/A'} | WMT: {r['sku_walmart'] or 'N/A'}", 
                    axis=1
                ).tolist()
                
                seleccion_idx = st.selectbox(
                    f"🎯 Coincidencias encontradas ({len(df_filtrado)}). Elige el producto a modificar:",
                    range(len(df_filtrado)),
                    format_func=lambda x: opciones_formateadas[x]
                )
                
                sku_data = df_filtrado.iloc[seleccion_idx]
                selected_sku = sku_data['sku_limpio']
                
                # Desglose de campos de edición en pantalla
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_min = st.number_input("Precio Mínimo", value=float(sku_data['precio_minimo']), step=0.01, format="%.2f")
                with col2:
                    new_max = st.number_input("Precio Máximo", value=float(sku_data['precio_maximo']), step=0.01, format="%.2f")
                with col3:
                    st.metric("Costo ODOO (Base)", f"${float(sku_data['costo_odoo']):.2f}")
                
                if new_min >= new_max:
                    render_alert_box("❌ El precio mínimo no puede ser mayor o igual al precio máximo", "error")
                elif new_min < float(sku_data['costo_odoo']):
                    render_alert_box(f"⚠️ Atención: El precio mínimo está por debajo del costo base de almacén ({sku_data['costo_odoo']})", "warning")
                else:
                    if st.button("💾 Guardar Cambios en PostgreSQL", use_container_width=True):
                        update_query = """
                        UPDATE catalogo_maestro_v3
                        SET precio_minimo = %s, precio_maximo = %s
                        WHERE sku_limpio = %s
                        """
                        if db.execute_update(update_query, (new_min, new_max, selected_sku)):
                            st.success(f"✅ Parámetros actualizados exitosamente para el producto {selected_sku}")
                            st.cache_data.clear()
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("❌ Ocurrió un error al guardar los cambios en PostgreSQL")
            else:
                st.warning("⚠️ No se encontraron productos que coincidan con la búsqueda")
        else:
            st.warning("⚠️ El catálogo maestro se encuentra vacío en la base de datos")
            
    except Exception as e:
        st.error(f"❌ Error crítico en el módulo de edición: {e}")
    
    st.markdown("---")
    
    # ========== TABLA EDITABLE MASIVA ENRIQUECIDA ==========
    st.markdown("### 📊 EDITOR DE CATALOGO (Edición masiva)")
    
    try:
        if len(df_catalogo) > 0:
            st.markdown("**Consejo:** Puedes visualizar los códigos de cada plataforma en las columnas bloqueadas para mantener el control.")
            
            # Mostramos el mapa completo de SKUs para que edites masivamente con contexto total
            edited_df = st.data_editor(
                df_catalogo[['sku_limpio', 'sku_interno', 'sku_liverpool', 'sku_walmart', 'sku_coppel', 'precio_minimo', 'precio_maximo', 'estatus']],
                use_container_width=True,
                key="catalog_editor",
                hide_index=True,
                column_config={
                    'sku_limpio': st.column_config.TextColumn("SKU Limpio", disabled=True),
                    'sku_interno': st.column_config.TextColumn("SKU Interno", disabled=True),
                    'sku_liverpool': st.column_config.TextColumn("SKU Liverpool", disabled=True),
                    'sku_walmart': st.column_config.TextColumn("SKU Walmart", disabled=True),
                    'sku_coppel': st.column_config.TextColumn("SKU Coppel", disabled=True),
                    'precio_minimo': st.column_config.NumberColumn("Precio Mínimo", format="$%.2f"),
                    'precio_maximo': st.column_config.NumberColumn("Precio Máximo", format="$%.2f"),
                    'estatus': st.column_config.SelectboxColumn("Estatus", options=['ACTIVO', 'INACTIVO'])
                },
                num_rows="dynamic"
            )
            
            if st.button("💾 Guardar Cambios Masivos en PostgreSQL", use_container_width=True):
                cambios = 0
                errores = []
                
                for idx, row in edited_df.iterrows():
                    if idx < len(df_catalogo):
                        original = df_catalogo.iloc[idx]
                        if (row['precio_minimo'] != original['precio_minimo'] or 
                            row['precio_maximo'] != original['precio_maximo'] or
                            row['estatus'] != original['estatus']):
                            
                            update_query = """
                            UPDATE catalogo_maestro_v3
                            SET precio_minimo = %s, precio_maximo = %s, estatus = %s
                            WHERE sku_limpio = %s
                            """
                            if db.execute_update(update_query, (row['precio_minimo'], row['precio_maximo'], row['estatus'], row['sku_limpio'])):
                                cambios += 1
                            else:
                                errores.append(row['sku_limpio'])
                
                if errores:
                    st.error(f"❌ No se pudieron actualizar los siguientes SKUs: {', '.join(errores)}")
                else:
                    st.success(f"✅ Operación exitosa: {cambios} registros modificados en la base de datos central")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
        else:
            st.warning("⚠️ No hay datos mapeados en el catálogo")
            
    except Exception as e:
        st.error(f"❌ Error en el procesamiento masivo: {e}")
    
    st.markdown("---")

    # ==========================================
    # 🧮 SIMULADOR Y CALCULADORA DE REGLAS FINANCIERAS
    # ==========================================
    st.markdown("### 🧮 Simulador de Utilidades y Reglas Financieras")
    
    with st.expander("🦅 Abrir Calculadora de Comisiones y Retenciones (Liverpool vs Walmart)", expanded=False):
        col_calc1, col_calc2, col_calc3, col_calc4 = st.columns(4)
        
        with col_calc1:
            mkt_simular = st.selectbox("Marketplace a Simular", ["LIVERPOOL", "WALMART"], key="sim_mkt")
        with col_calc2:
            costo_base_sim = st.number_input("Costo Base Odoo (Sin IVA)", min_value=0.0, value=100.0, step=10.0)
        with col_calc3:
            precio_venta_sim = st.number_input("Precio de Venta Propuesto", min_value=0.0, value=350.0, step=10.0)
            
        costo_con_iva = costo_base_sim * 1.16
        precio_neto_sin_iva = precio_venta_sim / 1.16
        retenciones_fiscales = precio_neto_sin_iva * (0.025 + 0.08)
        
        if mkt_simular == "LIVERPOOL":
            ingreso_bruto = (precio_venta_sim * 0.83) - 130
            comision_mkt = precio_venta_sim * 0.17 + 130
            regla_texto = "📋 Regla LVP: Comisión 17% + $130 fijo de envío."
        else:
            ingreso_bruto = (precio_venta_sim * 0.85) - 76
            comision_mkt = precio_venta_sim * 0.15 + 76
            regla_texto = "📋 Regla WMT: Comisión 15% + $76 fijo de envío."
            
        utilidad_neta = ingreso_bruto - costo_con_iva - retenciones_fiscales
        margen_porcentual = (utilidad_neta / costo_con_iva * 100) if costo_con_iva > 0 else 0.0
        
        with col_calc4:
            st.markdown(f"**Estatus de la Operación**")
            if utilidad_neta > 0:
                st.success(f"🟢 RENTABLE ({margen_porcentual:.1f}%)")
            else:
                st.error(f"🔴 PÉRDIDA ({margen_porcentual:.1f}%)")
                
        st.info(regla_texto)
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        metric_col1.metric("📦 Costo + IVA (Almacén)", f"${costo_con_iva:.2f}")
        metric_col2.metric("💸 Comisión + Envío Mkt", f"${comision_mkt:.2f}")
        metric_col3.metric("🏛️ Retención SAT (10.5%)", f"${retenciones_fiscales:.2f}")
        metric_col4.metric("💰 Utilidad Real Neta", f"${utilidad_neta:.2f}", 
                           delta=f"{margen_porcentual:.1f}% ROI", 
                           delta_color="normal" if utilidad_neta > 0 else "inverse")
    
    st.markdown("---")
    
    # ========== HISTORIAL DETALLADO ==========
    st.markdown("### 📜 HISTORIAL DE CAMBIOS (Últimos 7 días)")
    
    try:
        # LLAMADA CORREGIDA A LA FUNCIÓN
        df_historial = get_historial_precios(days=7)
        
        if len(df_historial) > 0:
            col1, col2, col3 = st.columns(3)
            with col1: filter_sku = st.text_input("Buscar SKU:", placeholder="Ej: SKU_123")
            with col2: filter_resultado = st.selectbox("Filtrar por Resultado:", ["Todos", "EJECUTADO", "NO EJECUTADO"])
            with col3: max_rows = st.number_input("Mostrar últimos N registros:", value=100, min_value=10, max_value=1000)
            
            if filter_sku: df_historial = df_historial[df_historial['sku_interno'].str.contains(filter_sku, case=False)]
            if filter_resultado != "Todos": df_historial = df_historial[df_historial['resultado'] == filter_resultado]
            
            st.dataframe(
                df_historial.head(max_rows),
                use_container_width=True, hide_index=True,
                column_config={
                    'created_at': st.column_config.TextColumn("Fecha"),
                    'sku_interno': st.column_config.TextColumn("SKU Interno"),
                    'sku_limpio': st.column_config.TextColumn("SKU Limpio"),
                    'precio_ant': st.column_config.NumberColumn("Precio Anterior", format="$%.2f"),
                    'precio_nuv': st.column_config.NumberColumn("Precio Nuevo", format="$%.2f"),
                    'stock': st.column_config.NumberColumn("Stock"),
                    'resultado': st.column_config.TextColumn("Resultado")
                }
            )
        else:
            st.warning("⚠️ Sin historial disponible")
    
    except Exception as e:
        st.error(f"❌ Error en historial: {e}")
    
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state['authenticated'] = False
            st.session_state.clear()
            st.rerun()
# ==========================================
# 🎬 MAIN APP LOGIC
# ==========================================

def main():
    """Función principal de la aplicación"""
    
    # Verificar si es vista pública
    if st.session_state.get('public_view', False):
        show_public_dashboard()
    # Verificar autenticación
    elif auth.is_authenticated():
        show_private_dashboard()
    else:
        show_login_page()

if __name__ == "__main__":
    main()
