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
# 📊 QUERIES OPTIMIZADAS CON CACHE
# ==========================================

@st.cache_data(ttl=300)
def get_historial_operaciones(days: int = 7) -> pd.DataFrame:
    query = """
    SELECT 
        h.created_at as fecha_hora,
        c.sku_limpio as sku_interno,
        h.marketplace as sku_liverpool,
        h.precio_ant as precio_rival,
        h.precio_nuv as nuestro_precio,
        h.stock,
        0 as posicion,
        h.resultado as buybox,
        (h.precio_nuv - h.precio_ant) as diferencia_precio
    FROM historial_operaciones h
    LEFT JOIN catalogo_maestro_v3 c ON h.catalogo_id = c.id
    WHERE h.created_at >= NOW() - INTERVAL '%s days'
    ORDER BY h.created_at DESC
    LIMIT 5000
    """
    return db.execute_query(query, (days,))

@st.cache_data(ttl=300)
def get_monitoreo_rivales(limit: int = 1000) -> pd.DataFrame:
    query = """
    SELECT 
        c.sku_limpio as sku_interno,
        m.nombre_rival,
        m.precio_rival as precio,
        m.marketplace,
        m.created_at as fecha_registro,
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
        sku_limpio as sku,
        sku_interno,
        precio_minimo,
        precio_maximo,
        costo_odoo,
        'Multiverso' as marketplace,
        estatus
    FROM catalogo_maestro_v3
    WHERE sku_limpio IS NOT NULL
    ORDER BY sku_limpio
    """
    return db.execute_query(query)

@st.cache_data(ttl=300)
def get_alertas() -> pd.DataFrame:
    query = """
    SELECT 
        id,
        tipo_alerta as tipo,
        mensaje,
        severidad as severity,
        created_at as fecha_creacion,
        FALSE as resuelta
    FROM alertas
    ORDER BY created_at DESC
    LIMIT 100
    """
    return db.execute_query(query)

@st.cache_data(ttl=600)
def get_metrics_dashboard() -> Dict:
    df_catalogo = get_catalogo_maestro()
    total_skus = len(df_catalogo)
    
    query_24h = "SELECT COUNT(*) as cambios FROM historial_operaciones WHERE created_at >= NOW() - INTERVAL '1 day'"
    df_24h = db.execute_query(query_24h)
    cambios_24h = df_24h.iloc[0, 0] if len(df_24h) > 0 else 0
    
    query_buybox = """
    SELECT 
        COUNT(CASE WHEN resultado = 'EJECUTADO' THEN 1 END) as ganadas,
        COUNT(*) as total
    FROM historial_operaciones
    WHERE created_at >= NOW() - INTERVAL '7 days'
    """
    df_buybox = db.execute_query(query_buybox)
    if len(df_buybox) > 0:
        ganadas = df_buybox.iloc[0]['ganadas']
        total = df_buybox.iloc[0]['total']
        win_rate = (ganadas / total * 100) if total > 0 else 0
    else:
        win_rate = 0
    
    df_rivales = get_monitoreo_rivales()
    rivales_unicos = df_rivales['nombre_rival'].nunique() if len(df_rivales) > 0 else 0
    
    query_margen = "SELECT AVG(precio_nuv - precio_ant) as margen_promedio FROM historial_operaciones WHERE created_at >= NOW() - INTERVAL '7 days'"
    df_margen = db.execute_query(query_margen)
    margen_promedio = df_margen.iloc[0, 0] if len(df_margen) > 0 else 0
    
    return {
        'total_skus': total_skus,
        'cambios_24h': int(cambios_24h),
        'win_rate_buybox': round(win_rate, 1),
        'rivales_unicos': rivales_unicos,
        'margen_promedio': round(float(margen_promedio), 2) if pd.notnull(margen_promedio) else 0
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
            FROM historial_operaciones
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
                AVG(nuestro_precio - precio_rival) as margen_promedio,
                MIN(nuestro_precio - precio_rival) as margen_minimo,
                MAX(nuestro_precio - precio_rival) as margen_maximo
            FROM historial_operaciones
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
            FROM historial_operaciones
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
    """Dashboard privado con editor de precios y datos sensibles"""
    
    st.markdown("""
    <h1 style="color: #1db954; text-shadow: 0 0 10px rgba(0, 255, 65, 0.3);">
        🔐 SALA DE CONTROL EJECUTIVA - MODO COMANDANTE
    </h1>
    """, unsafe_allow_html=True)
    
    st.markdown(f"**🕐 Sesión activa desde:** {datetime.fromtimestamp(st.session_state.get('auth_time', time.time())).strftime('%H:%M:%S')}")
    
    # ========== EDITOR FINANCIERO ==========
    st.markdown("### 💰 EDITOR FINANCIERO - Actualizar Precios Mínimos/Máximos")
    
    try:
        df_catalogo = get_catalogo_maestro()
        
        if len(df_catalogo) > 0:
            # Selector de SKU para editar
            selected_sku = st.selectbox(
                "Selecciona SKU para editar",
                df_catalogo['sku'].unique(),
                key="sku_selector"
            )
            
            # Obtener datos del SKU seleccionado
            sku_data = df_catalogo[df_catalogo['sku'] == selected_sku].iloc[0]
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                new_min = st.number_input(
                    "Precio Mínimo",
                    value=float(sku_data['precio_minimo']),
                    step=0.01,
                    format="%.2f"
                )
            
            with col2:
                new_max = st.number_input(
                    "Precio Máximo",
                    value=float(sku_data['precio_maximo']),
                    step=0.01,
                    format="%.2f"
                )
            
            with col3:
                st.metric("Costo ODOO", f"${float(sku_data['costo_odoo']):.2f}")
            
            # Validaciones
            if new_min >= new_max:
                render_alert_box("❌ Precio mínimo no puede ser >= máximo", "error")
            elif new_min < float(sku_data['costo_odoo']):
                render_alert_box(f"⚠️ Precio mínimo está por debajo del costo ({sku_data['costo_odoo']})", "warning")
            else:
                if st.button("💾 Guardar Cambios en PostgreSQL", use_container_width=True):
                    update_query = """
                    UPDATE catalogo_maestro_v3
                    SET precio_minimo = %s, precio_maximo = %s, fecha_actualizacion = NOW()
                    WHERE sku = %s
                    """
                    
                    if db.execute_update(update_query, (new_min, new_max, selected_sku)):
                        st.success(f"✅ Precios actualizados para {selected_sku}")
                        # Limpiar cache
                        st.cache_data.clear()
                    else:
                        st.error("❌ Error al actualizar en PostgreSQL")
        else:
            st.warning("⚠️ No hay SKUs disponibles")
    
    except Exception as e:
        st.error(f"❌ Error en editor: {e}")
    
    st.markdown("---")
    
    # ========== TABLA EDITABLE ==========
    st.markdown("### 📊 EDITOR DE CATALOGO (Edición masiva)")
    
    try:
        df_catalogo = get_catalogo_maestro()
        
        if len(df_catalogo) > 0:
            # Mostrar en data_editor
            st.markdown("**Nota:** Los cambios en la tabla inferior se guardan en PostgreSQL al hacer click en 'Guardar Cambios'")
            
            edited_df = st.data_editor(
                df_catalogo[['sku', 'precio_minimo', 'precio_maximo', 'marketplace', 'estatus']],
                use_container_width=True,
                key="catalog_editor",
                hide_index=True,
                column_config={
                    'sku': st.column_config.TextColumn("SKU", disabled=True),
                    'precio_minimo': st.column_config.NumberColumn(
                        "Precio Mínimo",
                        format="$%.2f"
                    ),
                    'precio_maximo': st.column_config.NumberColumn(
                        "Precio Máximo",
                        format="$%.2f"
                    ),
                    'marketplace': st.column_config.SelectboxColumn(
                        "Marketplace",
                        options=['liverpool', 'coppel', 'walmart']
                    ),
                    'estatus': st.column_config.SelectboxColumn(
                        "Estatus",
                        options=['ACTIVO', 'INACTIVO']
                    )
                },
                num_rows="dynamic"
            )
            
            # Botón para guardar cambios
            if st.button("💾 Guardar Cambios Masivos en PostgreSQL", use_container_width=True):
                cambios = 0
                errores = []
                
                for idx, row in edited_df.iterrows():
                    if idx < len(df_catalogo):
                        original = df_catalogo.iloc[idx]
                        
                        # Detectar cambios
                        if (row['precio_minimo'] != original['precio_minimo'] or 
                            row['precio_maximo'] != original['precio_maximo'] or
                            row['estatus'] != original['estatus']):
                            
                            update_query = """
                            UPDATE catalogo_maestro_v3
                            SET precio_minimo = %s, precio_maximo = %s, estatus = %s, fecha_actualizacion = NOW()
                            WHERE sku = %s
                            """
                            
                            if db.execute_update(
                                update_query,
                                (row['precio_minimo'], row['precio_maximo'], row['estatus'], row['sku'])
                            ):
                                cambios += 1
                            else:
                                errores.append(row['sku'])
                
                if errores:
                    st.error(f"❌ Error actualizando {len(errores)} SKUs: {', '.join(errores)}")
                else:
                    st.success(f"✅ {cambios} registros actualizados correctamente en PostgreSQL")
                
                # Limpiar cache
                st.cache_data.clear()
        else:
            st.warning("⚠️ No hay datos para editar")
    
    except Exception as e:
        st.error(f"❌ Error en tabla editable: {e}")
    
    st.markdown("---")
    
    # ========== HISTORIAL DETALLADO ==========
    st.markdown("### 📜 HISTORIAL DE CAMBIOS (Últimos 7 días)")
    
    try:
        df_historial = get_historial_operaciones(days=7)
        
        if len(df_historial) > 0:
            # Filtros
            col1, col2, col3 = st.columns(3)
            
            with col1:
                filter_sku = st.text_input("Buscar SKU:", placeholder="Ej: SKU_123")
            
            with col2:
                filter_buybox = st.selectbox(
                    "Filtrar BuyBox:",
                    ["Todos", "Sí (Ganado)", "No (Perdido)"]
                )
            
            with col3:
                max_rows = st.number_input("Mostrar últimos N registros:", value=100, min_value=10, max_value=1000)
            
            # Aplicar filtros
            if filter_sku:
                df_historial = df_historial[df_historial['sku_interno'].str.contains(filter_sku, case=False)]
            
            if filter_buybox != "Todos":
                buybox_val = "Sí" if "Ganado" in filter_buybox else "No"
                df_historial = df_historial[df_historial['buybox'] == buybox_val]
            
            # Mostrar tabla
            st.dataframe(
                df_historial.head(max_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    'fecha_hora': st.column_config.TextColumn("Fecha"),
                    'sku_interno': st.column_config.TextColumn("SKU Interno"),
                    'precio_rival': st.column_config.NumberColumn("Precio Rival", format="$%.2f"),
                    'nuestro_precio': st.column_config.NumberColumn("Nuestro Precio", format="$%.2f"),
                    'diferencia_precio': st.column_config.NumberColumn("Margen", format="$%.2f"),
                    'stock': st.column_config.NumberColumn("Stock"),
                    'posicion': st.column_config.NumberColumn("Posición"),
                    'buybox': st.column_config.TextColumn("BuyBox")
                }
            )
        else:
            st.warning("⚠️ Sin historial disponible")
    
    except Exception as e:
        st.error(f"❌ Error en historial: {e}")
    
    st.markdown("---")
    
    # ========== BOTÓN DE LOGOUT ==========
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
