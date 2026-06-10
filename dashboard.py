#!/usr/bin/env python3
# ==========================================
# MEGAZORD WAR ROOM - DASHBOARD ENTERPRISE V2.0
# Centro de Comando Ejecutivo con BI Real-Time
# MULTI-TENANT ARCHITECTURE INTEGRATED
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
import time
import requests

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
    initial_sidebar_state="expanded"
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
    .main { background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%); color: #ffffff; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #0f1428 0%, #1a1f3a 100%); border-right: 2px solid #00d9ff; }
    h1, h2, h3 { color: #00d9ff; text-shadow: 0 0 10px rgba(0, 217, 255, 0.3); font-weight: 700; }
    .metric-box { background: linear-gradient(135deg, #1a1f3a 0%, #0f2540 100%); border: 2px solid #00d9ff; border-radius: 8px; padding: 20px; box-shadow: 0 0 20px rgba(0, 217, 255, 0.2); transition: all 0.3s ease; }
    .metric-box:hover { border-color: #1db954; box-shadow: 0 0 30px rgba(0, 255, 65, 0.3); }
    .stButton > button { background: linear-gradient(135deg, #00d9ff 0%, #1db954 100%); color: #0a0e27; border: none; border-radius: 6px; font-weight: bold; padding: 12px 24px; transition: all 0.3s ease; text-transform: uppercase; }
    .stButton > button:hover { transform: scale(1.05); box-shadow: 0 0 20px rgba(0, 255, 65, 0.4); }
    .stTextInput > div > div > input, .stPasswordInput > div > div > input, .stNumberInput > div > div > input { background: #1a1f3a; color: #ffffff; border: 2px solid #00d9ff; border-radius: 6px; }
    .stDataFrame { background: #1a1f3a; border: 2px solid #00d9ff; }
</style>
"""
st.markdown(DARK_MODE_CSS, unsafe_allow_html=True)

# ==========================================
# 🔐 SEGURIDAD & AUTENTICACIÓN
# ==========================================

class AuthManager:
    def __init__(self):
        self.password_hash = os.getenv("DASHBOARD_PASSWORD", "megazord2025")
        self.session_timeout = 3600
    def verify_password(self, password: str) -> bool:
        return password == self.password_hash
    def is_authenticated(self) -> bool:
        if 'auth_time' not in st.session_state: return False
        if time.time() - st.session_state['auth_time'] > self.session_timeout:
            st.session_state['authenticated'] = False
            return False
        return st.session_state.get('authenticated', False)
    def login(self, password: str) -> bool:
        if self.verify_password(password):
            st.session_state['authenticated'] = True
            st.session_state['auth_time'] = time.time()
            return True
        return False

# ==========================================
# 🗄️ GESTOR DE BASE DE DATOS POSTGRESQL
# ==========================================

class PostgreSQLManager:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool = None
        self._initialize_pool()
    def _initialize_pool(self):
        try:
            self._pool = psycopg2.pool.SimpleConnectionPool(1, 10, self.database_url, connect_timeout=5)
        except Exception as e:
            st.error("❌ No se pudo conectar a PostgreSQL")
    def execute_query(self, query: str, params: tuple = None) -> pd.DataFrame:
        try:
            conn = self._pool.getconn()
            cursor = conn.cursor()
            if params: cursor.execute(query, params)
            else: cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()
            cursor.close()
            self._pool.putconn(conn)
            return pd.DataFrame(data, columns=columns)
        except Exception as e:
            return pd.DataFrame()
    def execute_update(self, query: str, params: tuple = None) -> bool:
        try:
            conn = self._pool.getconn()
            cursor = conn.cursor()
            if params: cursor.execute(query, params)
            else: cursor.execute(query)
            conn.commit()
            cursor.close()
            self._pool.putconn(conn)
            return True
        except Exception as e:
            if conn: conn.rollback()
            self._pool.putconn(conn)
            return False

# ==========================================
# 💾 INICIALIZACIÓN GLOBAL
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    st.error("❌ DATABASE_URL no configurado")
    st.stop()
db = PostgreSQLManager(DATABASE_URL)
auth = AuthManager()

# ==========================================
# 🧩 COMPONENTES CLAUDE: MULTI-TENANT
# ==========================================

def renderizar_selector_cuenta_global(db):
    """Paso 1: Selector en el Sidebar"""
    st.sidebar.subheader("📍 Filtro de Cuenta")
    try:
        query = "SELECT id_cuenta, nombre_descriptivo, is_active FROM cuentas_liverpool ORDER BY id_cuenta ASC"
        resultado = db.execute_query(query)
        if resultado.empty:
            st.sidebar.error("❌ No hay cuentas")
            return "TODAS"
        
        opciones = ["🌍 TODAS LAS CUENTAS"]
        map_cuentas = {"🌍 TODAS LAS CUENTAS": "TODAS"}
        
        for _, row in resultado.iterrows():
            icono = "✅" if row['is_active'] else "⏸️"
            opcion_texto = f"{icono} {row['id_cuenta']} - {row['nombre_descriptivo']}"
            opciones.append(opcion_texto)
            map_cuentas[opcion_texto] = row['id_cuenta']
            
        if 'cuenta_seleccionada' not in st.session_state:
            st.session_state.cuenta_seleccionada = "🌍 TODAS LAS CUENTAS"
            
        seleccion = st.sidebar.selectbox(
            "Selecciona la tienda activa:",
            opciones,
            index=opciones.index(st.session_state.cuenta_seleccionada) if st.session_state.cuenta_seleccionada in opciones else 0
        )
        st.session_state.cuenta_seleccionada = seleccion
        id_cuenta_filtro = map_cuentas[seleccion]
        st.sidebar.info(f"📌 Visualizando: **{id_cuenta_filtro}**")
        return id_cuenta_filtro
    except Exception as e:
        return "TODAS"

def renderizar_historial_precios_filtrado(db, id_cuenta_filtro):
    """Paso 2: Gráfica Global con soporte Multi-Cuenta"""
    st.subheader("📊 Gráfica Global Multi-Cuenta (Últimos 30 días)")
    try:
        if id_cuenta_filtro == "TODAS":
            query = """SELECT fecha_hora, sku_interno, nuestro_precio, id_cuenta FROM historial_precios WHERE fecha_hora >= NOW() - INTERVAL '30 days' ORDER BY fecha_hora ASC LIMIT 1000"""
            df = db.execute_query(query)
        else:
            query = """SELECT fecha_hora, sku_interno, nuestro_precio, id_cuenta FROM historial_precios WHERE id_cuenta = %s AND fecha_hora >= NOW() - INTERVAL '30 days' ORDER BY fecha_hora ASC LIMIT 1000"""
            df = db.execute_query(query, (id_cuenta_filtro,))
            
        if df.empty:
            st.warning("⚠️ No hay datos para graficar en este filtro.")
            return
            
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
        df['nuestro_precio'] = pd.to_numeric(df['nuestro_precio'], errors='coerce')
        fig = go.Figure()
        
        if id_cuenta_filtro == "TODAS":
            cuentas = df['id_cuenta'].unique()
            colores = ['#00D9FF', '#FF6B6B', '#1db954', '#FF69B4']
            for idx, c in enumerate(cuentas):
                df_c = df[df['id_cuenta'] == c]
                fig.add_trace(go.Scatter(x=df_c['fecha_hora'], y=df_c['nuestro_precio'], mode='lines+markers', name=f'Cuenta: {c}', line=dict(color=colores[idx % 4], width=2)))
        else:
            skus = df['sku_interno'].unique()[:5] # Max 5 lineas
            for sku in skus:
                df_sku = df[df['sku_interno'] == sku]
                fig.add_trace(go.Scatter(x=df_sku['fecha_hora'], y=df_sku['nuestro_precio'], mode='lines+markers', name=f'SKU: {sku}'))
                
        fig.update_layout(plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font=dict(color='#FFFFFF'), hovermode='x unified', height=500)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Error gráfica: {e}")

def renderizar_panel_admin_boveda(db):
    """Paso 3: Bóveda Secreta de Control de Tokens"""
    with st.expander("🔐 Bóveda de Cuentas (Administración de Cookies e Interruptor)", expanded=False):
        st.markdown("### Gestión de Servidor PostgreSQL")
        try:
            query = "SELECT id_cuenta, nombre_descriptivo, email_usuario, cookie_vip, is_active FROM cuentas_liverpool ORDER BY id_cuenta ASC"
            df = db.execute_query(query)
            if df.empty: return
            
            st.markdown("💡 *Modifica las cookies o el switch de ON/OFF y presiona guardar:*")
            df_editado = st.data_editor(
                df,
                column_config={
                    "id_cuenta": st.column_config.TextColumn("ID", disabled=True),
                    "nombre_descriptivo": "Nombre",
                    "email_usuario": "Email",
                    "cookie_vip": "Cookie VIP",
                    "is_active": st.column_config.CheckboxColumn("Activa (ON/OFF)")
                },
                hide_index=True, use_container_width=True
            )
            
            if st.button("💾 Guardar Bóveda en Servidor"):
                cambios = 0
                for idx, row in df_editado.iterrows():
                    orig = df.iloc[idx]
                    if row['cookie_vip'] != orig['cookie_vip'] or row['is_active'] != orig['is_active']:
                        # CORRECCIÓN VITAL: Aquí Claude usó execute_query, pero debe ser execute_update
                        update_q = "UPDATE cuentas_liverpool SET cookie_vip = %s, is_active = %s WHERE id_cuenta = %s"
                        db.execute_update(update_q, (row['cookie_vip'], row['is_active'], row['id_cuenta']))
                        cambios += 1
                if cambios > 0:
                    st.success(f"✅ ¡Bóveda actualizada! {cambios} cuenta(s) modificada(s).")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.info("No detecté cambios.")
        except Exception as e:
            st.error(f"Error Bóveda: {e}")

# ==========================================
# 📊 QUERIES BASE Y METRICAS
# ==========================================

@st.cache_data(ttl=300)
def get_historial_precios(days: int = 7) -> pd.DataFrame:
    limit_date = datetime.now() - timedelta(days=days)
    query = """
    SELECT h.fecha_hora AS created_at, h.fecha_hora, h.sku_interno, c.sku_limpio, h.precio_rival AS precio_ant, h.nuestro_precio AS precio_nuv, h.stock, h.posicion, h.buybox AS resultado, h.id_cuenta
    FROM historial_precios h LEFT JOIN catalogo_maestro_v3 c ON h.sku_interno = c.sku_interno WHERE h.fecha_hora >= %s ORDER BY h.fecha_hora DESC LIMIT 50000
    """
    return db.execute_query(query, (limit_date,))

@st.cache_data(ttl=300)
def get_monitoreo_rivales(limit: int = 1000) -> pd.DataFrame:
    query = "SELECT c.sku_interno, c.sku_limpio, m.nombre_rival, m.precio_rival as precio, m.marketplace, m.created_at, COUNT(*) OVER (PARTITION BY m.nombre_rival) as apariciones_rival FROM monitoreo_rivales m LEFT JOIN catalogo_maestro_v3 c ON m.catalogo_id = c.id ORDER BY m.created_at DESC LIMIT %s"
    return db.execute_query(query, (limit,))

@st.cache_data(ttl=300)
def get_catalogo_maestro() -> pd.DataFrame:
    query = "SELECT id, sku_limpio, sku_limpio as sku, sku_interno, sku_liverpool, sku_walmart, sku_coppel, precio_minimo, precio_maximo, costo_odoo, estatus, COALESCE(regla_estrategia, '1. Gladiador') AS regla, id_cuenta FROM catalogo_maestro_v3 ORDER BY sku_limpio"
    return db.execute_query(query)

@st.cache_data(ttl=600)
def get_metrics_dashboard() -> Dict:
    df_catalogo = get_catalogo_maestro()
    limit_date = datetime.now() - timedelta(days=1)
    df_24h = db.execute_query("SELECT COUNT(*) as cambios FROM historial_precios WHERE fecha_hora >= %s", (limit_date,))
    limit_date_7d = datetime.now() - timedelta(days=7)
    df_buybox = db.execute_query("SELECT COUNT(CASE WHEN UPPER(buybox) IN ('EJECUTADO', 'SÍ', 'SI', 'TRUE') THEN 1 END) as ganadas, COUNT(*) as total FROM historial_precios WHERE fecha_hora >= %s", (limit_date_7d,))
    df_margen = db.execute_query("SELECT AVG(nuestro_precio - precio_rival) FROM historial_precios WHERE fecha_hora >= %s", (limit_date_7d,))
    
    return {
        'total_skus': len(df_catalogo),
        'cambios_24h': df_24h.iloc[0,0] if not df_24h.empty else 0,
        'win_rate_buybox': (df_buybox.iloc[0]['ganadas'] / df_buybox.iloc[0]['total'] * 100) if not df_buybox.empty and df_buybox.iloc[0]['total'] > 0 else 0,
        'margen_promedio': df_margen.iloc[0,0] if not df_margen.empty and df_margen.iloc[0,0] else 0
    }

def render_metric_card(title: str, value: str, subtitle: str = "", status: str = "neutral", icon: str = "📊"):
    colors = {'positive': '#1db954', 'negative': '#ff003c', 'neutral': '#00d9ff', 'warning': '#ffaa00'}
    color = colors.get(status, colors['neutral'])
    st.markdown(f"""
    <div class="metric-box" style="border-color: {color};">
        <div style="display: flex; justify-content: space-between; align-items: start;">
            <div>
                <p style="color: #b0bec5; margin: 0; font-size: 12px; text-transform: uppercase;">{title}</p>
                <h2 style="color: {color}; margin: 10px 0 0 0; font-size: 32px; font-weight: bold;">{value}</h2>
                <p style="color: #b0bec5; margin: 5px 0 0 0; font-size: 12px;">{subtitle}</p>
            </div>
            <div style="font-size: 40px; opacity: 0.5;">{icon}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_alert_box(message: str, alert_type: str = "info"):
    colors = {'success': '#1db954', 'error': '#ff003c', 'warning': '#ffaa00', 'info': '#00d9ff'}
    color = colors.get(alert_type, colors['info'])
    st.markdown(f'<div style="background: rgba(0, 217, 255, 0.1); border-left: 4px solid {color}; padding: 15px; border-radius: 4px; margin: 10px 0;"><p style="color: {color}; margin: 0; font-weight: bold;">{message}</p></div>', unsafe_allow_html=True)

# ==========================================
# 📱 PÁGINA DE LOGIN Y PÚBLICA (Se mantienen igual)
# ==========================================

def show_login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br><br><div style='text-align: center;'><h1 style='color: #00d9ff;'>⚡ MEGAZORD WAR ROOM</h1><p>CENTRO DE COMANDO EJECUTIVO</p></div><br><br>", unsafe_allow_html=True)
        password = st.text_input("🔐 Contraseña de Acceso", type="password")
        if st.button("🚀 ACCESO RESTRINGIDO", use_container_width=True):
            if auth.login(password):
                st.success("✅ ¡Bienvenido Comandante!")
                st.rerun()
            else: st.error("❌ Contraseña incorrecta")

def show_public_dashboard():
    st.markdown("<h1>📊 CENTRO DE INTELIGENCIA EJECUTIVA - MODO LECTURA</h1>", unsafe_allow_html=True)
    st.info("Modo de sólo lectura activado.")
    metrics = get_metrics_dashboard()
    col1, col2, col3 = st.columns(3)
    with col1: render_metric_card("Total SKUs Activos", f"{metrics['total_skus']:,}", "Catálogo", "positive", "📦")
    with col2: render_metric_card("Cambios 24h", f"{metrics['cambios_24h']:,}", "Actualizaciones", "neutral", "⚡")
    with col3: render_metric_card("Win Rate BuyBox", f"{metrics['win_rate_buybox']:.1f}%", "Victorias", "positive" if metrics['win_rate_buybox'] > 50 else "negative", "👑")
    if st.button("🔐 Regresar al Login", use_container_width=True):
        st.session_state['public_view'] = False
        st.rerun()

# ==========================================
# 🔐 SECCIÓN PRIVADA (CON MULTI-TENANT)
# ==========================================

def show_private_dashboard():
    
    # 📍 INYECCIÓN PASO 1: SIDEBAR MULTI-CUENTA
    with st.sidebar:
        st.markdown("---")
        id_cuenta_filtro = renderizar_selector_cuenta_global(db)

    st.markdown("<h1>🔐 SALA DE CONTROL EJECUTIVA - MODO COMANDANTE</h1>", unsafe_allow_html=True)
    
    try:
        df_catalogo = get_catalogo_maestro()
        
        # Filtramos también el catálogo si el usuario seleccionó una cuenta específica
        if id_cuenta_filtro != "TODAS" and not df_catalogo.empty:
            df_catalogo = df_catalogo[df_catalogo['id_cuenta'] == id_cuenta_filtro]
            
        if not df_catalogo.empty:
            st.markdown("### 🏬 1. Selecciona el Canal de Venta")
            tienda_activa = st.selectbox("¿Qué canal deseas inspeccionar?", ["LIVERPOOL", "WALMART", "COPPEL"])
            
            df_canal = df_catalogo.copy()
            if tienda_activa == "LIVERPOOL": df_canal = df_canal[df_canal['sku_liverpool'].notna() & (df_canal['sku_liverpool'] != '')]
            elif tienda_activa == "WALMART": df_canal = df_canal[df_canal['sku_walmart'].notna() & (df_canal['sku_walmart'] != '')]
            elif tienda_activa == "COPPEL": df_canal = df_canal[df_canal['sku_coppel'].notna() & (df_canal['sku_coppel'] != '')]

            st.markdown("---")
            
            st.markdown("### 🎯 2. Buscador Predictivo y Editor de Estrategia")
            termino_busqueda = st.text_input(f"🔍 Buscar en {tienda_activa}:")
            
            df_filtrado = df_canal.copy()
            if termino_busqueda:
                df_filtrado = df_canal[
                    df_canal['sku_limpio'].astype(str).str.contains(termino_busqueda, case=False, na=False) |
                    df_canal['sku_interno'].astype(str).str.contains(termino_busqueda, case=False, na=False) |
                    df_canal['sku_liverpool'].astype(str).str.contains(termino_busqueda, case=False, na=False)
                ]
            
            if not df_filtrado.empty:
                opciones = df_filtrado.apply(lambda r: f"🆔 ID: {r['id']} | 📦 {r['sku_limpio']} | Cuenta: {r['id_cuenta']}", axis=1).tolist()
                seleccion_idx = st.selectbox("Coincidencias:", range(len(df_filtrado)), format_func=lambda x: opciones[x])
                
                sku_data = df_filtrado.iloc[seleccion_idx]
                row_id_unico = sku_data['id']
                
                col1, col2, col3, col4 = st.columns(4)
                with col1: new_min = st.number_input("Precio Mínimo", value=float(sku_data['precio_minimo']), step=0.01)
                with col2: new_max = st.number_input("Precio Máximo", value=float(sku_data['precio_maximo']), step=0.01)
                with col3: 
                    lista_reglas = ["1. Gladiador", "2. Ancla Mínimo", "3. Cosecha Máximo", "4. Analista Histórico", "5. Depredador (1+3)", "6. Francotirador (1+4)", "7. Bomba de Tiempo (2+3)", "8. Liquidador Sabio (2+4)", "9. Venta Especial"]
                    regla_actual = str(sku_data['regla']).strip() if str(sku_data['regla']).strip() in lista_reglas else lista_reglas[0]
                    new_rule = st.selectbox("Regla", options=lista_reglas, index=lista_reglas.index(regla_actual))
                with col4: st.metric("Costo ODOO", f"${float(sku_data['costo_odoo']):.2f}")
                
                if st.button("💾 Guardar Configuración"):
                    update_query = "UPDATE catalogo_maestro_v3 SET precio_minimo = %s, precio_maximo = %s, regla_estrategia = %s WHERE id = %s"
                    if db.execute_update(update_query, (new_min, new_max, new_rule, int(row_id_unico))):
                        st.success("✅ Guardado")
                        time.sleep(1)
                        st.rerun()
                
                # Radar de Precios Individual adaptado
                st.markdown("#### 📈 Radar de Precios del Producto")
                if tienda_activa == "LIVERPOOL":
                    sku_int_param = f"%{str(sku_data.get('sku_interno')).strip()}%"
                    
                    # Se añade el filtro de id_cuenta para que no se mezclen las líneas si el mismo perfume está en 2 tiendas
                    if id_cuenta_filtro == "TODAS":
                        query_lvp = "SELECT fecha_hora as created_at, nuestro_precio, precio_rival, stock, buybox, id_cuenta FROM historial_precios WHERE sku_interno ILIKE %s AND fecha_hora >= NOW() - INTERVAL '30 days' ORDER BY fecha_hora ASC"
                        df_grafica = db.execute_query(query_lvp, (sku_int_param,))
                    else:
                        query_lvp = "SELECT fecha_hora as created_at, nuestro_precio, precio_rival, stock, buybox, id_cuenta FROM historial_precios WHERE sku_interno ILIKE %s AND id_cuenta = %s AND fecha_hora >= NOW() - INTERVAL '30 days' ORDER BY fecha_hora ASC"
                        df_grafica = db.execute_query(query_lvp, (sku_int_param, id_cuenta_filtro))
                        
                    if not df_grafica.empty:
                        df_grafica['created_at'] = pd.to_datetime(df_grafica['created_at'])
                        fig = px.line(df_grafica, x='created_at', y='nuestro_precio', color='id_cuenta', title="Evolución de Nuestro Precio")
                        fig.update_layout(plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font=dict(color='#FFFFFF'))
                        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error: {e}")

    # ==========================================
    # 📍 INYECCIÓN PASO 2 y 3: GRAFICA GLOBAL Y PANEL BÓVEDA
    # ==========================================
    st.markdown("---")
    renderizar_historial_precios_filtrado(db, id_cuenta_filtro)
    
    st.markdown("---")
    renderizar_panel_admin_boveda(db)
    
    # ==========================================
    # TABLA DE HISTORIAL DETALLADO
    # ==========================================
    st.markdown("---")
    st.markdown("### 📜 HISTORIAL DE CAMBIOS DETALLADO")
    df_historial = get_historial_precios(days=7)
    if not df_historial.empty:
        # Filtramos la tabla de abajo también por el id_cuenta
        if id_cuenta_filtro != "TODAS":
            df_historial = df_historial[df_historial['id_cuenta'] == id_cuenta_filtro]
            
        st.dataframe(df_historial.head(100), use_container_width=True, hide_index=True)

    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state['authenticated'] = False
            st.rerun()

# ==========================================
# 🎬 MAIN APP LOGIC
# ==========================================
def main():
    if st.session_state.get('public_view', False): show_public_dashboard()
    elif auth.is_authenticated(): show_private_dashboard()
    else: show_login_page()

if __name__ == "__main__":
    main()
