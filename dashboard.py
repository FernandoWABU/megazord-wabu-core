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

st.set_page_config(
    page_title="🤖 MEGAZORD War Room",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 🎨 DARK MODE CSS (Corregido para visibilidad)
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
        /* FORZAR LETRAS NEGRAS EN BOTONES Y DESPLEGABLES */
        .stButton > button { color: #000000 !important; text-shadow: none !important; }
        .stButton > button p { color: #000000 !important; font-weight: 900 !important; }
        div[data-baseweb="select"] * { color: #000000 !important; }
    }
    .main { background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%); color: #ffffff; }
    
    /* FIX DE VISIBILIDAD DEL SIDEBAR */
    [data-testid="stSidebar"] { 
        background-color: #0f1428 !important; 
        border-right: 2px solid #00d9ff; 
    }
    [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] p, 
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
# 🔐 SEGURIDAD & BD POSTGRESQL
# ==========================================

class AuthManager:
    def __init__(self):
        self.password_hash = os.getenv("DASHBOARD_PASSWORD", "megazord2025")
        self.session_timeout = 3600
    def login(self, password: str) -> bool:
        if password == self.password_hash:
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
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool = None
        self._initialize_pool()
    def _initialize_pool(self):
        try:
            self._pool = psycopg2.pool.SimpleConnectionPool(1, 10, self.database_url, connect_timeout=5)
        except Exception:
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
        except Exception:
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

DATABASE_URL = os.getenv("DATABASE_URL")
db = PostgreSQLManager(DATABASE_URL)
auth = AuthManager()

# ==========================================
# 📊 DATA FETCHERS
# ==========================================

@st.cache_data(ttl=300)
def get_historial_precios(days: int = 7) -> pd.DataFrame:
    query = """
    SELECT h.fecha_hora AS created_at, h.fecha_hora, h.sku_interno, c.sku_limpio,
           h.precio_rival AS precio_ant, h.nuestro_precio AS precio_nuv,
           h.stock, h.posicion, h.buybox AS resultado, h.id_cuenta
    FROM historial_precios h LEFT JOIN catalogo_maestro_v3 c ON h.sku_interno = c.sku_interno
    WHERE h.fecha_hora >= %s ORDER BY h.fecha_hora DESC LIMIT 50000
    """
    return db.execute_query(query, (datetime.now() - timedelta(days=days),))

@st.cache_data(ttl=300)
def get_catalogo_maestro() -> pd.DataFrame:
    query = """
    SELECT id, sku_limpio, sku_limpio as sku, sku_interno, sku_liverpool, sku_walmart, sku_coppel,
           precio_minimo, precio_maximo, costo_odoo, estatus, id_cuenta,
           COALESCE(regla_estrategia, '1. Gladiador') AS regla
    FROM catalogo_maestro_v3 ORDER BY sku_limpio
    """
    return db.execute_query(query)

def get_cuentas_disponibles() -> list:
    df_ctas = db.execute_query("SELECT id_cuenta FROM cuentas_liverpool ORDER BY id_cuenta ASC")
    return df_ctas['id_cuenta'].tolist() if not df_ctas.empty else ['LVP_01', 'LVP_02']

# ==========================================
# 📱 LOGIN PAGE
# ==========================================

def show_login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br><br><div style='text-align: center;'><h1 style='color: #00d9ff;'>⚡ MEGAZORD WAR ROOM</h1></div><br><br>", unsafe_allow_html=True)
        password = st.text_input("🔐 Contraseña de Acceso", type="password")
        if st.button("🚀 ACCESO RESTRINGIDO", use_container_width=True):
            if auth.login(password): st.rerun()
            else: st.error("❌ Contraseña incorrecta")

# ==========================================
# 🔐 DASHBOARD PRIVADO
# ==========================================

def show_private_dashboard():
    
    # 📍 SIDEBAR FILTER
    with st.sidebar:
        st.markdown("---")
        st.subheader("📍 Selección de Tienda Global")
        query_cuentas = "SELECT id_cuenta, nombre_descriptivo, is_active FROM cuentas_liverpool ORDER BY id_cuenta ASC"
        res_ctas = db.execute_query(query_cuentas)
        opciones = ["🌍 TODAS LAS CUENTAS"]
        map_cuentas = {"🌍 TODAS LAS CUENTAS": "TODAS"}
        if not res_ctas.empty:
            for _, r in res_ctas.iterrows():
                lbl = f"{'✅' if r['is_active'] else '⏸️'} {r['nombre_descriptivo']} ({r['id_cuenta']})"
                opciones.append(lbl)
                map_cuentas[lbl] = r['id_cuenta']
        cta_label = st.selectbox("Filtrar Dashboard por:", opciones)
        id_cuenta_filtro = map_cuentas[cta_label]

        # ==========================================
        # 🚀 CENTRO DE OPERACIONES MULTI-CANAL
        # ==========================================
        st.markdown("---")
        st.subheader("⚡ Centro de Lanzamiento")

        # 🔐 Credenciales de GitHub (Debes ponerlas en tu .env o en los secrets de Streamlit)
        GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "tu_token_aqui") 
        GITHUB_USER = os.getenv("GITHUB_USER", "TuUsuarioDeGithub")
        GITHUB_REPO = os.getenv("GITHUB_REPO", "TuRepositorio")

        headers_github = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        col_btn1, col_btn2 = st.columns(2)

        # 🔵 PANEL COPPEL
        with col_btn1:
            st.markdown("**🔵 Coppel**")
            if st.button("🚀 Lanzar", key="btn_coppel", use_container_width=True):
                url_coppel = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/actions/workflows/megazord-coppel.yml/dispatches"
                try:
                    res = requests.post(url_coppel, headers=headers_github, json={"ref": "main"})
                    if res.status_code == 204:
                        st.success("✅ Misil Coppel en camino.")
                    else:
                        st.error(f"❌ Error {res.status_code}: Revisa tu Token de GitHub")
                except Exception as e:
                    st.error(f"❌ Error de conexión: {e}")

        # 🔴🟢 PANEL MULTI-TIENDA
        with col_btn2:
            st.markdown("**🔴🟢 Multi-Tienda**")
            objetivo = st.selectbox(
                "Objetivo:", 
                ["LIVERPOOL", "WALMART", "AMBAS"], 
                label_visibility="collapsed"
            )
            
            if st.button("🚀 Disparar", key="btn_multi", type="primary", use_container_width=True):
                url_main = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/actions/workflows/main.yml/dispatches"
                # Pasamos la orden en minúsculas para que haga match perfecto con tu main.yml
                payload = {
                    "ref": "main", 
                    "inputs": {"tienda": objetivo.lower()}
                }
                
                try:
                    res = requests.post(url_main, headers=headers_github, json=payload)
                    if res.status_code == 204:
                        st.success(f"✅ Misil {objetivo} lanzado con éxito.")
                    else:
                        st.error(f"❌ Error {res.status_code}: Revisa tu Token de GitHub")
                except Exception as e:
                    st.error(f"❌ Error de conexión: {e}")

    st.markdown("""<h1 style="color: #1db954;">🔐 SALA DE CONTROL EJECUTIVA - MODO COMANDANTE</h1>""", unsafe_allow_html=True)
    
    df_catalogo = get_catalogo_maestro()
    lista_cuentas = get_cuentas_disponibles()
    
    if id_cuenta_filtro != "TODAS" and not df_catalogo.empty:
        df_catalogo = df_catalogo[df_catalogo['id_cuenta'] == id_cuenta_filtro]
        
    if not df_catalogo.empty:
        
        # 1. SELECTOR DE CANAL
        st.markdown("### 🏬 1. Selecciona el Canal de Venta")
        tienda_activa = st.selectbox("¿Qué canal deseas inspeccionar o modificar?", ["TODOS", "LIVERPOOL", "WALMART", "COPPEL"], key="tienda_activa_selector")
        
        df_canal = df_catalogo.copy()
        if tienda_activa == "LIVERPOOL": df_canal = df_canal[df_canal['sku_liverpool'].notna() & (df_canal['sku_liverpool'] != '')]
        elif tienda_activa == "WALMART": df_canal = df_canal[df_canal['sku_walmart'].notna() & (df_canal['sku_walmart'] != '')]
        elif tienda_activa == "COPPEL": df_canal = df_canal[df_canal['sku_coppel'].notna() & (df_canal['sku_coppel'] != '')]

        st.markdown("---")
        
        # =========================================================================
        # 🎯 2. BUSCADOR PREDICTIVO Y EDITOR DE ESTRATEGIA (CON KILL-SWITCH POR TIENDA)
        # =========================================================================
        st.markdown("### 🎯 2. Buscador Predictivo y Editor de Estrategia")
        term = st.text_input(f"🔍 Buscar en {tienda_activa} (SKU Interno, Liverpool, Walmart, etc):", placeholder="Ej: HCK13.3atomizador...")
        
        df_filtrado = df_canal.copy()
        if term:
            df_filtrado = df_canal[
                df_canal['sku_limpio'].astype(str).str.contains(term, case=False, na=False) |
                df_canal['sku_interno'].astype(str).str.contains(term, case=False, na=False) |
                df_canal['sku_liverpool'].astype(str).str.contains(term, case=False, na=False) |
                df_canal['sku_walmart'].astype(str).str.contains(term, case=False, na=False) |
                df_canal['sku_coppel'].astype(str).str.contains(term, case=False, na=False)
            ]
        
        if not df_filtrado.empty:
            ops_fmt = df_filtrado.apply(
                lambda r: f"🆔 {r['id']} | 📦 {r['sku_limpio']} | Cta: {r.get('id_cuenta', 'N/A')} | LVP: {r.get('sku_liverpool', 'N/A')}", 
                axis=1
            ).tolist()
            
            sel_idx = st.selectbox(f"Coincidencias en {tienda_activa}:", range(len(df_filtrado)), format_func=lambda x: ops_fmt[x])
            
            sku_data = df_filtrado.iloc[sel_idx]
            row_id = sku_data['id']
            
            # Traemos los estatus actuales de la base de datos (manejamos por si Walmart/Coppel se llaman diferente en tu BD)
            estatus_lvp_actual = str(sku_data.get('estatus', 'ACTIVO')).strip() == 'ACTIVO'
            estatus_wmt_actual = str(sku_data.get('estatus_walmart', 'ACTIVO')).strip() == 'ACTIVO'
            estatus_cpp_actual = str(sku_data.get('estatus_coppel', 'ACTIVO')).strip() == 'ACTIVO'
            
            # DISEÑO DE FILAS DE EDICIÓN
            col_min, col_max, col_regla, col_cta, col_costo = st.columns(5)
            with col_min: new_min = st.number_input("P. Mínimo", value=float(sku_data['precio_minimo']), step=0.01)
            with col_max: new_max = st.number_input("P. Máximo", value=float(sku_data['precio_maximo']), step=0.01)
            with col_regla:
                r_list = ["1. Gladiador", "2. Ancla Mínimo", "3. Cosecha Máximo", "4. Analista Histórico", "5. Depredador", "6. Francotirador", "7. Bomba de Tiempo", "8. Liquidador Sabio", "9. Venta Especial"]
                r_act = str(sku_data['regla']).strip()
                if r_act not in r_list: r_act = r_list[0]
                new_rule = st.selectbox("Regla de Repricing", r_list, index=r_list.index(r_act))
            with col_cta:
                cta_act = str(sku_data.get('id_cuenta', 'LVP_01'))
                if cta_act not in lista_cuentas: lista_cuentas.append(cta_act)
                new_cta = st.selectbox("Tienda Asignada (Liverpool)", lista_cuentas, index=lista_cuentas.index(cta_act))
            with col_costo: st.metric("Costo Odoo Base", f"${float(sku_data['costo_odoo']):.2f}")
            
            # SECCIÓN NUEVA: INTERRUPTORES DE ENCENDIDO (ON/OFF) POR MARKETPLACE
            st.markdown("##### 🔌 Interruptores de Referencia (Estatus del SKU por Tienda)")
            col_sw_lvp, col_sw_wmt, col_sw_cpp, _ = st.columns([1, 1, 1, 1])
            
            with col_sw_lvp:
                new_status_lvp = st.toggle("Estatus LIVERPOOL", value=estatus_lvp_actual, help="Prende o apaga el repricer para esta referencia en Liverpool")
            with col_sw_wmt:
                new_status_wmt = st.toggle("Estatus WALMART", value=estatus_wmt_actual, help="Prende o apaga el repricer para esta referencia en Walmart")
            with col_sw_cpp:
                new_status_cpp = st.toggle("Estatus COPPEL", value=estatus_cpp_actual, help="Prende o apaga el repricer para esta referencia en Coppel")
            
            # Convertimos los booleanos de los switches al formato de texto 'ACTIVO'/'INACTIVO' que usa tu base de datos
            val_lvp = 'ACTIVO' if new_status_lvp else 'INACTIVO'
            val_wmt = 'ACTIVO' if new_status_wmt else 'INACTIVO'
            val_cpp = 'ACTIVO' if new_status_cpp else 'INACTIVO'

            if st.button("💾 Guardar Configuración de SKU", use_container_width=True):
                # ¡CORREGIDO! Usamos estatus_wmt exactamente como está en tu BD
                query_update_individual = """
                    UPDATE catalogo_maestro_v3 
                    SET precio_minimo=%s, precio_maximo=%s, regla_estrategia=%s, id_cuenta=%s,
                        estatus=%s, estatus_wmt=%s, estatus_coppel=%s 
                    WHERE id=%s
                """
                if db.execute_update(query_update_individual, (new_min, new_max, new_rule, new_cta, val_lvp, val_wmt, val_cpp, int(row_id))):
                    st.success(f"✅ ¡Configuración e Interruptores blindados para el ID {row_id}!")
                    st.cache_data.clear()
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("❌ Error al impactar los cambios en el servidor central de PostgreSQL.")

            # ACORDEÓN: RADAR DE PRECIOS
            with st.expander(f"📈 Radar de Precios (Histórico) - {tienda_activa}", expanded=False):
                try:
                    if tienda_activa in ["LIVERPOOL", "TODOS"]:
                        sku_int = f"%{str(sku_data.get('sku_interno') or '').strip()}%"
                        if id_cuenta_filtro == "TODAS":
                            q_lvp = "SELECT fecha_hora as created_at, nuestro_precio, precio_rival, id_cuenta FROM historial_precios WHERE sku_interno ILIKE %s AND fecha_hora >= NOW() - INTERVAL '30 days' ORDER BY fecha_hora ASC"
                            df_g = db.execute_query(q_lvp, (sku_int,))
                        else:
                            q_lvp = "SELECT fecha_hora as created_at, nuestro_precio, precio_rival, id_cuenta FROM historial_precios WHERE sku_interno ILIKE %s AND id_cuenta = %s AND fecha_hora >= NOW() - INTERVAL '30 days' ORDER BY fecha_hora ASC"
                            df_g = db.execute_query(q_lvp, (sku_int, id_cuenta_filtro))
                        
                        if not df_g.empty:
                            df_g['created_at'] = pd.to_datetime(df_g['created_at'])
                            fig = px.line(df_g, x='created_at', y='nuestro_precio', color='id_cuenta', markers=True, title="Nuestro Precio por Tienda")
                            fig.update_layout(plot_bgcolor='#0E1117', paper_bgcolor='#0E1117', font=dict(color='#FFFFFF'))
                            st.plotly_chart(fig, use_container_width=True)
                        else: st.info("Sin datos en los últimos 30 días.")
                except Exception as e: st.error(f"Error Gráfica: {e}")

    st.markdown("---")
    
    # ACORDEÓN: EDITOR MASIVO
    with st.expander("📊 3. Editor Masivo del Canal Activo", expanded=False):
        try:
            if len(df_canal) > 0:
                st.info("💡 Edita directamente en la tabla y presiona Guardar. ¡Ahora también puedes cambiar la cuenta de múltiples SKUs a la vez!")
                edited_df = st.data_editor(
                    df_canal[['id', 'sku_limpio', 'sku_interno', 'precio_minimo', 'precio_maximo', 'regla', 'id_cuenta', 'estatus']],
                    use_container_width=True, hide_index=True,
                    column_config={
                        'id': st.column_config.NumberColumn("ID", disabled=True),
                        'sku_limpio': st.column_config.TextColumn("SKU Limpio", disabled=True),
                        'id_cuenta': st.column_config.SelectboxColumn("Cuenta", options=lista_cuentas),
                        'regla': st.column_config.SelectboxColumn("Regla", options=r_list),
                        'estatus': st.column_config.SelectboxColumn("Estatus", options=['ACTIVO', 'INACTIVO'])
                    }
                )
                if st.button("💾 Guardar Cambios Masivos", use_container_width=True):
                    for idx, r in edited_df.iterrows():
                        orig = df_canal.iloc[idx]
                        if r['precio_minimo']!=orig['precio_minimo'] or r['id_cuenta']!=orig['id_cuenta'] or r['regla']!=orig['regla']:
                            db.execute_update(
                                "UPDATE catalogo_maestro_v3 SET precio_minimo=%s, precio_maximo=%s, regla_estrategia=%s, id_cuenta=%s, estatus=%s WHERE id=%s", 
                                (r['precio_minimo'], r['precio_maximo'], r['regla'], r['id_cuenta'], r['estatus'], int(r['id']))
                            )
                    st.success("✅ Cambios Masivos Guardados.")
                    st.cache_data.clear()
                    time.sleep(0.8)
                    st.rerun()
        except Exception as e: st.error(f"Error masivo: {e}")

    # ACORDEÓN: CALCULADORA COMPLETA (Corregida)
    with st.expander("🧮 Simulador de Utilidades y Reglas Financieras", expanded=False):
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

    # ACORDEÓN: BÓVEDA VIP
    with st.expander("🔐 Panel de Administración: Bóveda VIP (Tokens y Cookies)", expanded=False):
        # 1. Agregamos token_autorizacion al SELECT
        df_b = db.execute_query("SELECT id_cuenta, nombre_descriptivo, email_usuario, is_active, token_autorizacion, cookie_vip FROM cuentas_liverpool ORDER BY id_cuenta ASC")
        
        # 2. Mostramos el editor configurando los nombres de las columnas para que sea fácil de leer
        df_e = st.data_editor(
            df_b, 
            hide_index=True, 
            use_container_width=True,
            column_config={
                "id_cuenta": st.column_config.TextColumn("ID", disabled=True),
                "nombre_descriptivo": "Nombre Cuenta",
                "email_usuario": "Correo Login",
                "is_active": "Activa",
                "token_autorizacion": "Token (Bearer)",
                "cookie_vip": "Cookie VIP"
            }
        )
        
        if st.button("💾 Guardar Bóveda"):
            for _, r in df_e.iterrows():
                # 3. Agregamos token_autorizacion al UPDATE
                db.execute_update(
                    "UPDATE cuentas_liverpool SET nombre_descriptivo=%s, email_usuario=%s, is_active=%s, token_autorizacion=%s, cookie_vip=%s WHERE id_cuenta=%s", 
                    (r['nombre_descriptivo'], r['email_usuario'], r['is_active'], r['token_autorizacion'], r['cookie_vip'], r['id_cuenta'])
                )
            st.success("✅ Bóveda Actualizada con Éxito (Tokens y Cookies blindados)")
            time.sleep(1)
            st.rerun()

    # ACORDEÓN: HISTORIAL
    with st.expander("📜 HISTORIAL DE CAMBIOS (Últimos 7 días)", expanded=False):
        df_h = get_historial_precios(7)
        if len(df_h) > 0:
            if id_cuenta_filtro != "TODAS": df_h = df_h[df_h['id_cuenta'] == id_cuenta_filtro]
            
            hc1, hc2 = st.columns(2)
            with hc1: f_sku = st.text_input("Filtrar SKU:")
            with hc2: f_res = st.selectbox("Resultado:", ["Todos", "EJECUTADO", "NO EJECUTADO", "Ruleta Rusa"])
            
            if f_sku: df_h = df_h[df_h['sku_interno'].str.contains(f_sku, case=False, na=False)]
            if f_res != "Todos": df_h = df_h[df_h['resultado'].astype(str).str.contains(f_res, case=False, na=False)]
            
            st.dataframe(df_h.head(200), use_container_width=True, hide_index=True)

    st.markdown("---")
    if st.button("🚪 Cerrar Sesión"):
        st.session_state.clear()
        st.rerun()

def main():
    if auth.is_authenticated(): show_private_dashboard()
    else: show_login_page()

if __name__ == "__main__":
    main()
