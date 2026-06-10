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
from functools import wraps
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
# 🗄️ GESTOR DE BD POSTGRESQL
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
# 📊 QUERIES OPTIMIZADAS CON id_cuenta
# ==========================================

@st.cache_data(ttl=300)
def get_historial_precios(days: int = 7) -> pd.DataFrame:
    limit_date = datetime.now() - timedelta(days=days)
    query = """
    SELECT 
        h.fecha_hora AS created_at, h.fecha_hora, h.sku_interno, c.sku_limpio,
        h.precio_rival AS precio_ant, h.nuestro_precio AS precio_nuv,
        h.stock, h.posicion, h.buybox AS resultado, h.id_cuenta
    FROM historial_precios h
    LEFT JOIN catalogo_maestro_v3 c ON h.sku_interno = c.sku_interno
    WHERE h.fecha_hora >= %s
    ORDER BY h.fecha_hora DESC
    LIMIT 50000
    """
    return db.execute_query(query, (limit_date,))

@st.cache_data(ttl=300)
def get_monitoreo_rivales(limit: int = 1000) -> pd.DataFrame:
    query = "SELECT c.sku_interno, c.sku_limpio, m.nombre_rival, m.precio_rival as precio, m.marketplace, m.created_at, COUNT(*) OVER (PARTITION BY m.nombre_rival) as apariciones_rival FROM monitoreo_rivales m LEFT JOIN catalogo_maestro_v3 c ON m.catalogo_id = c.id ORDER BY m.created_at DESC LIMIT %s"
    return db.execute_query(query, (limit,))

@st.cache_data(ttl=300)
def get_catalogo_maestro() -> pd.DataFrame:
    query = """
    SELECT 
        id, sku_limpio, sku_limpio as sku, sku_interno, sku_liverpool, sku_walmart, sku_coppel,
        precio_minimo, precio_maximo, costo_odoo, estatus, id_cuenta,
        COALESCE(regla_estrategia, '1. Gladiador') AS regla
    FROM catalogo_maestro_v3
    ORDER BY sku_limpio
    """
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
# 📱 PÁGINA DE LOGIN Y PÚBLICA
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
    
    # ==========================================
    # 📍 FILTRO GLOBAL MULTI-CUENTA (BARRA LATERAL)
    # ==========================================
    with st.sidebar:
        st.markdown("---")
        st.subheader("📍 Selección de Cuenta Liverpool")
        try:
            query_cuentas = "SELECT id_cuenta, nombre_descriptivo, is_active FROM cuentas_liverpool ORDER BY id_cuenta ASC"
            resultado_cuentas = db.execute_query(query_cuentas)
            
            opciones = ["🌍 TODAS LAS CUENTAS"]
            map_cuentas = {"🌍 TODAS LAS CUENTAS": "TODAS"}
            
            if not resultado_cuentas.empty:
                for _, row in resultado_cuentas.iterrows():
                    icono = "✅" if row['is_active'] else "⏸️"
                    label = f"{icono} {row['nombre_descriptivo']} ({row['id_cuenta']})"
                    opciones.append(label)
                    map_cuentas[label] = row['id_cuenta']
                    
            cuenta_seleccionada_label = st.selectbox("Filtrar Dashboard por:", opciones)
            id_cuenta_filtro = map_cuentas[cuenta_seleccionada_label]
        except Exception as e:
            st.error(f"Error Bóveda: {e}")
            id_cuenta_filtro = "TODAS"

    st.markdown("""
    <h1 style="color: #1db954; text-shadow: 0 0 10px rgba(29, 185, 84, 0.3);">
        🔐 SALA DE CONTROL EJECUTIVA - MODO COMANDANTE
    </h1>
    """, unsafe_allow_html=True)
    
    try:
        df_catalogo = get_catalogo_maestro()
        
        # Filtramos el catálogo según la cuenta seleccionada en la Bóveda
        if id_cuenta_filtro != "TODAS" and not df_catalogo.empty:
            df_catalogo = df_catalogo[df_catalogo['id_cuenta'] == id_cuenta_filtro]
            
        if len(df_catalogo) > 0:
            
            # ==========================================
            # 🏬 FILTRO TÁCTICO DE MARKETPLACE
            # ==========================================
            st.markdown("### 🏬 1. Selecciona el Canal de Venta")
            tienda_activa = st.selectbox(
                "¿Qué canal deseas inspeccionar o modificar?",
                ["TODOS", "LIVERPOOL", "WALMART", "COPPEL"],
                key="tienda_activa_selector"
            )
            
            df_canal = df_catalogo.copy()
            if tienda_activa == "LIVERPOOL":
                df_canal = df_canal[df_canal['sku_liverpool'].notna() & (df_canal['sku_liverpool'] != '')]
            elif tienda_activa == "WALMART":
                df_canal = df_canal[df_canal['sku_walmart'].notna() & (df_canal['sku_walmart'] != '')]
            elif tienda_activa == "COPPEL":
                df_canal = df_canal[df_canal['sku_coppel'].notna() & (df_canal['sku_coppel'] != '')]

            st.markdown(f"**Productos en este canal:** {len(df_canal)}")
            st.markdown("---")
            
            # ==========================================
            # 💰 EDITOR FINANCIERO INDIVIDUAL (POR ID)
            # ==========================================
            st.markdown("### 🎯 2. Buscador Predictivo y Editor de Estrategia")
            
            termino_busqueda = st.text_input(
                f"🔍 Buscar en {tienda_activa} (Puedes usar SKU Limpio, Interno o código de barra):",
                placeholder="Ej: HCK13.3atomizador, SKU_48819B..."
            )
            
            df_filtrado = df_canal.copy()
            if termino_busqueda:
                df_filtrado = df_canal[
                    df_canal['sku_limpio'].astype(str).str.contains(termino_busqueda, case=False, na=False) |
                    df_canal['sku_interno'].astype(str).str.contains(termino_busqueda, case=False, na=False) |
                    df_canal['sku_liverpool'].astype(str).str.contains(termino_busqueda, case=False, na=False)
                ]
            
            if not df_filtrado.empty:
                opciones_formateadas = df_filtrado.apply(
                    lambda r: f"🆔 ID: {r['id']} | 📦 {r['sku_limpio']} | Cta: {r['id_cuenta']}", 
                    axis=1
                ).tolist()
                
                seleccion_idx = st.selectbox(
                    f"Coincidencias en {tienda_activa}: ({len(df_filtrado)}). Elige el registro exacto:",
                    range(len(df_filtrado)),
                    format_func=lambda x: opciones_formateadas[x]
                )
                
                sku_data = df_filtrado.iloc[seleccion_idx]
                row_id_unico = sku_data['id']
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1: new_min = st.number_input("Precio Mínimo", value=float(sku_data['precio_minimo']), step=0.01)
                with col2: new_max = st.number_input("Precio Máximo", value=float(sku_data['precio_maximo']), step=0.01)
                with col3:
                    lista_reglas_oficiales = ["1. Gladiador", "2. Ancla Mínimo", "3. Cosecha Máximo", "4. Analista Histórico", "5. Depredador (1+3)", "6. Francotirador (1+4)", "7. Bomba de Tiempo (2+3)", "8. Liquidador Sabio (2+4)", "9. Venta Especial"]
                    regla_limpia = str(sku_data['regla']).strip()
                    regla_actual_bd = regla_limpia if regla_limpia in lista_reglas_oficiales else lista_reglas_oficiales[0]
                    new_rule = st.selectbox("Regla de Repricing", options=lista_reglas_oficiales, index=lista_reglas_oficiales.index(regla_actual_bd))
                with col4: st.metric("Costo ODOO Base", f"${float(sku_data['costo_odoo']):.2f}")
                
                if st.button("💾 Guardar Configuración en PostgreSQL", use_container_width=True):
                    update_query = "UPDATE catalogo_maestro_v3 SET precio_minimo = %s, precio_maximo = %s, regla_estrategia = %s WHERE id = %s"
                    if db.execute_update(update_query, (new_min, new_max, new_rule, int(row_id_unico))):
                        st.success(f"✅ Configuración blindada guardada para el ID {row_id_unico}")
                        st.cache_data.clear()
                        time.sleep(0.8)
                        st.rerun()
                    else:
                        st.error("❌ Error de comunicación con la base de datos central.")

                # ==========================================
                # 📈 RADAR DE PRECIOS ADAPTADO A MULTI-TENANT
                # ==========================================
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown(f"#### 📈 Radar de Precios (Histórico Completo) - {tienda_activa}")
                
                try:
                    if tienda_activa == "LIVERPOOL":
                        sku_int = str(sku_data.get('sku_interno') or '').strip()
                        sku_lvp = str(sku_data.get('sku_liverpool') or '').strip()
                        sku_int_param = f"%{sku_int}%" if sku_int else "%VALOR_NULO%"
                        sku_lvp_param = f"%{sku_lvp}%" if sku_lvp else "%VALOR_NULO%"
                        
                        # Si eliges "Todas", traemos de todas y pintamos varias líneas
                        if id_cuenta_filtro == "TODAS":
                            query_lvp = """
                            SELECT fecha_hora as created_at, nuestro_precio, precio_rival, stock, buybox, id_cuenta 
                            FROM historial_precios 
                            WHERE (sku_interno ILIKE %s OR sku_liverpool ILIKE %s) 
                            AND fecha_hora >= NOW() - INTERVAL '30 days' 
                            ORDER BY fecha_hora ASC
                            """
                            df_grafica = db.execute_query(query_lvp, (sku_int_param, sku_lvp_param))
                        else:
                            # Filtramos por la cuenta específica
                            query_lvp = """
                            SELECT fecha_hora as created_at, nuestro_precio, precio_rival, stock, buybox, id_cuenta 
                            FROM historial_precios 
                            WHERE (sku_interno ILIKE %s OR sku_liverpool ILIKE %s) 
                            AND id_cuenta = %s AND fecha_hora >= NOW() - INTERVAL '30 days' 
                            ORDER BY fecha_hora ASC
                            """
                            df_grafica = db.execute_query(query_lvp, (sku_int_param, sku_lvp_param, id_cuenta_filtro))
                        
                        if not df_grafica.empty:
                            df_grafica['created_at'] = pd.to_datetime(df_grafica['created_at'])
                            df_grafica['nuestro_precio'] = pd.to_numeric(df_grafica['nuestro_precio'], errors='coerce')
                            df_grafica['precio_rival'] = pd.to_numeric(df_grafica['precio_rival'], errors='coerce')
                            
                            fig = go.Figure()
                            
                            # Iteramos por cuenta para dibujar varias líneas si es necesario
                            cuentas_en_grafica = df_grafica['id_cuenta'].unique()
                            colores_nuestros = ['#00D9FF', '#1db954', '#FFA500']
                            
                            for i, cta in enumerate(cuentas_en_grafica):
                                df_cta = df_grafica[df_grafica['id_cuenta'] == cta]
                                
                                # Nuestro Precio
                                fig.add_trace(go.Scatter(
                                    x=df_cta['created_at'], y=df_cta['nuestro_precio'], 
                                    mode='lines+markers', name=f'🔵 Nuestro Precio ({cta})', 
                                    line=dict(color=colores_nuestros[i % len(colores_nuestros)], width=3)
                                ))
                                
                                # Precio Rival
                                fig.add_trace(go.Scatter(
                                    x=df_cta['created_at'], y=df_cta['precio_rival'], 
                                    mode='lines', name=f'🔴 BuyBox Rival ({cta})', 
                                    line=dict(color='#FF003C', width=2, dash='dot')
                                ))
                            
                            fig.update_layout(plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font=dict(color='#FFFFFF'), hovermode='x unified', height=400)
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.info("No hay historial de cambios para este SKU en los últimos 30 días.")
                            
                    elif tienda_activa == "WALMART":
                        # Lógica de Walmart se mantiene igual
                        pass
                except Exception as e:
                    st.error(f"Error cargando gráfica: {e}")
            else:
                st.warning(f"⚠️ No se encontraron listados en {tienda_activa} con ese criterio.")
        else:
            st.warning("⚠️ Catálogo maestro no disponible.")
    except Exception as e:
        st.error(f"❌ Error en Sala de Control: {e}")
    
    st.markdown("---")

    # ==========================================
    # 🚀 GATILLO MANUAL DE EMERGENCIA (GITHUB TRIGGER)
    # ==========================================
    st.markdown("### 🚀 Sistema de Lanzamiento de Patrullas (Barrido de Emergencia)")
    col_git1, col_git2 = st.columns([2, 1])
    with col_git1:
        tienda_lanzar = st.selectbox("Selecciona qué escuadrón deseas despertar:", ["ambas", "liverpool", "walmart"], key="git_tienda_selector")
    with col_git2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔥 DISPARAR BARRIDO AHORA", use_container_width=True):
            REPO = "FernandoWABU/megazord-wabu-core"
            WORKFLOW_FILE = "main.yml"
            TOKEN_GITHUB = st.secrets.get("GITHUB_PAT", "")
            if not TOKEN_GITHUB:
                st.error("❌ Error: No se encontró el 'GITHUB_PAT' en los Secrets.")
            else:
                with st.spinner("📬 Enviando orden de ataque a GitHub..."):
                    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
                    headers = {"Authorization": f"Bearer {TOKEN_GITHUB}", "Accept": "application/vnd.github+json"}
                    data = {"ref": "main", "inputs": {"tienda": tienda_lanzar}}
                    res = requests.post(url, headers=headers, json=data)
                    if res.status_code == 204: st.success("🚀 ¡MISIL LANZADO con éxito!")
                    else: st.error(f"❌ Falla: {res.text}")

    st.markdown("---")
    
    # ==========================================
    # 📊 EDITOR MASIVO
    # ==========================================
    st.markdown("### 📊 3. Editor Masivo del Canal Activo")
    try:
        if len(df_canal) > 0:
            edited_df = st.data_editor(
                df_canal[['id', 'sku_limpio', 'sku_interno', 'sku_liverpool', 'sku_walmart', 'sku_coppel', 'precio_minimo', 'precio_maximo', 'regla', 'estatus']],
                use_container_width=True, hide_index=True,
                column_config={
                    'id': st.column_config.NumberColumn("ID Único", disabled=True),
                    'sku_limpio': st.column_config.TextColumn("SKU Limpio", disabled=True),
                    'precio_minimo': st.column_config.NumberColumn("Precio Mínimo", format="$%.2f"),
                    'precio_maximo': st.column_config.NumberColumn("Precio Máximo", format="$%.2f"),
                    'regla': st.column_config.SelectboxColumn("Regla", options=["1. Gladiador", "2. Ancla Mínimo", "3. Cosecha Máximo", "4. Analista Histórico", "5. Depredador (1+3)", "6. Francotirador (1+4)", "7. Bomba de Tiempo (2+3)", "8. Liquidador Sabio (2+4)", "9. Venta Especial"]),
                    'estatus': st.column_config.SelectboxColumn("Estatus", options=['ACTIVO', 'INACTIVO'])
                }
            )
            if st.button("💾 Guardar Cambios Masivos", use_container_width=True):
                for idx, row in edited_df.iterrows():
                    original = df_canal.iloc[idx]
                    if row['precio_minimo'] != original['precio_minimo'] or row['regla'] != original['regla']:
                        db.execute_update("UPDATE catalogo_maestro_v3 SET precio_minimo = %s, precio_maximo = %s, regla_estrategia = %s, estatus = %s WHERE id = %s", 
                                          (row['precio_minimo'], row['precio_maximo'], row['regla'], row['estatus'], int(row['id'])))
                st.success("✅ Éxito Masivo guardado.")
                time.sleep(0.8)
                st.rerun()
    except Exception as e:
        st.error(f"Error editor masivo: {e}")
    
    st.markdown("---")

    # ==========================================
    # 🧮 CALCULADORA DE COMISIONES (MANTENIDA)
    # ==========================================
    st.markdown("### 🧮 Simulador de Utilidades y Reglas Financieras")
    with st.expander("🦅 Abrir Calculadora de Comisiones y Retenciones (Liverpool vs Walmart)", expanded=False):
        col_calc1, col_calc2, col_calc3, col_calc4 = st.columns(4)
        with col_calc1: mkt_simular = st.selectbox("Marketplace", ["LIVERPOOL", "WALMART"], key="sim_mkt")
        with col_calc2: costo_base_sim = st.number_input("Costo Odoo (Sin IVA)", min_value=0.0, value=100.0, step=10.0)
        with col_calc3: precio_venta_sim = st.number_input("Precio Propuesto", min_value=0.0, value=350.0, step=10.0)
            
        costo_con_iva = costo_base_sim * 1.16
        precio_neto_sin_iva = precio_venta_sim / 1.16
        retenciones_fiscales = precio_neto_sin_iva * (0.025 + 0.08)
        
        if mkt_simular == "LIVERPOOL":
            ingreso_bruto = (precio_venta_sim * 0.83) - 130
            comision_mkt = precio_venta_sim * 0.17 + 130
        else:
            ingreso_bruto = (precio_venta_sim * 0.85) - 76
            comision_mkt = precio_venta_sim * 0.15 + 76
            
        utilidad_neta = ingreso_bruto - costo_con_iva - retenciones_fiscales
        margen_porcentual = (utilidad_neta / costo_con_iva * 100) if costo_con_iva > 0 else 0.0
        
        with col_calc4:
            st.markdown(f"**Estatus de Operación**")
            if utilidad_neta > 0: st.success(f"🟢 RENTABLE ({margen_porcentual:.1f}%)")
            else: st.error(f"🔴 PÉRDIDA ({margen_porcentual:.1f}%)")
                
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("📦 Costo + IVA", f"${costo_con_iva:.2f}")
        mc2.metric("💸 Comis+Envío", f"${comision_mkt:.2f}")
        mc3.metric("🏛️ Retención SAT", f"${retenciones_fiscales:.2f}")
        mc4.metric("💰 Utilidad Neta", f"${utilidad_neta:.2f}")

    st.markdown("---")

    # ==========================================
    # 🔐 PANEL DE BÓVEDA (MULTI-TENANT)
    # ==========================================
    with st.expander("🔐 Panel de Administración: Bóveda VIP de Cuentas"):
        st.subheader("Configuración Centralizada en PostgreSQL")
        try:
            query_boveda = "SELECT id_cuenta, nombre_descriptivo, email_usuario, is_active, cookie_vip FROM cuentas_liverpool ORDER BY id_cuenta ASC"
            df_boveda = pd.read_sql(query_boveda, con=db._pool.getconn())
            
            st.markdown("💡 *Puedes activar/desactivar o modificar las cookies y presionar Guardar:*")
            df_editado = st.data_editor(
                df_boveda,
                column_config={
                    "id_cuenta": st.column_config.TextColumn("ID", disabled=True),
                    "nombre_descriptivo": "Nombre Comercial",
                    "email_usuario": "Email",
                    "is_active": st.column_config.CheckboxColumn("ON/OFF"),
                    "cookie_vip": "Cookie VIP"
                }, hide_index=True, use_container_width=True
            )
            
            if st.button("💾 Guardar Cambios en Bóveda"):
                for index, row in df_editado.iterrows():
                    up_q = "UPDATE cuentas_liverpool SET nombre_descriptivo = %s, email_usuario = %s, is_active = %s, cookie_vip = %s WHERE id_cuenta = %s"
                    db.execute_update(up_q, (row['nombre_descriptivo'], row['email_usuario'], row['is_active'], row['cookie_vip'], row['id_cuenta']))
                st.success("🚀 ¡Bóveda VIP actualizada!")
                time.sleep(1)
                st.rerun()
        except Exception as e:
            st.error(f"Error en Bóveda: {e}")

    st.markdown("---")
    
    # ==========================================
    # 📜 HISTORIAL DETALLADO (FILTRADO POR CUENTA)
    # ==========================================
    st.markdown("### 📜 HISTORIAL DE CAMBIOS (Últimos 7 días)")
    
    try:
        df_historial = get_historial_precios(days=7)
        
        if len(df_historial) > 0:
            
            # FILTRAMOS HISTORIAL BASADO EN LA BÓVEDA
            if id_cuenta_filtro != "TODAS":
                df_historial = df_historial[df_historial['id_cuenta'] == id_cuenta_filtro]
            
            col1, col2, col3 = st.columns(3)
            with col1: filter_sku = st.text_input("Buscar SKU:", placeholder="Ej: SKU_123")
            with col2: filter_resultado = st.selectbox("Filtrar por Resultado:", ["Todos", "EJECUTADO", "NO EJECUTADO"])
            with col3: max_rows = st.number_input("Mostrar N registros:", value=100, min_value=10, max_value=1000)
            
            if filter_sku: df_historial = df_historial[df_historial['sku_interno'].str.contains(filter_sku, case=False)]
            if filter_resultado != "Todos": df_historial = df_historial[df_historial['resultado'].astype(str).str.contains(filter_resultado, case=False, na=False)]
            
            def resaltar_regla_9(row):
                res = str(row['resultado'])
                if "Ruleta Rusa" in res: return ['background-color: #8B0000; color: white'] * len(row)
                elif "Trinquete" in res: return ['background-color: #B8860B; color: black'] * len(row)
                return [''] * len(row)

            df_estilizado = df_historial.head(max_rows).style.apply(resaltar_regla_9, axis=1)

            st.dataframe(
                df_estilizado,
                use_container_width=True, hide_index=True,
                column_config={
                    'created_at': st.column_config.TextColumn("Fecha"),
                    'id_cuenta': st.column_config.TextColumn("Cuenta"),
                    'sku_limpio': st.column_config.TextColumn("SKU Limpio"),
                    'precio_ant': st.column_config.NumberColumn("Precio Ant", format="$%.2f"),
                    'precio_nuv': st.column_config.NumberColumn("Precio Nuv", format="$%.2f")
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
    if st.session_state.get('public_view', False):
        show_public_dashboard()
    elif auth.is_authenticated():
        show_private_dashboard()
    else:
        show_login_page()

if __name__ == "__main__":
    main()
