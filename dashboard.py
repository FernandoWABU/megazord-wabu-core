import streamlit as st
import gspread
import pandas as pd
import requests
import xmlrpc.client
import os
import html
import json
from datetime import datetime, timezone, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 1. CONFIGURACIÓN INICIAL Y ESTILOS
# ==========================================
st.set_page_config(page_title="Megazord OS | Centro de Comando", page_icon="🤖", layout="wide")

st.markdown("""
    <style>
    .card-activo { border-left: 10px solid #28a745; background-color: #f8fff9; padding: 20px; border-radius: 10px; margin-bottom: 15px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    .card-inactivo { border-left: 10px solid #dc3545; background-color: #fff8f8; padding: 20px; border-radius: 10px; margin-bottom: 15px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    .badge-stock { background-color: #007bff; color: white; padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-right: 5px; }
    .badge-pos { background-color: #6f42c1; color: white; padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-right: 5px; }
    .badge-bb { background-color: #e74c3c; color: white; padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-right: 5px; }
    .badge-fecha { background-color: #6c757d; color: white; padding: 4px 8px; border-radius: 12px; font-size: 12px; }
    .badge-regla { background-color: #f39c12; color: white; padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-right: 5px; }
    div[data-testid="metric-container"] { background-color: #f4f6f9; border-radius: 10px; padding: 15px; border-left: 5px solid #6f42c1; }
    
    /* 🚀 MAGIA PARA LA PANTALLA DE CARGA 🚀 */
    [data-testid="stStatusWidget"] label {
        display: none !important; /* Oculta el texto feo por defecto */
    }
    [data-testid="stStatusWidget"]::after {
        content: "⏳ Procesando datos..."; /* Tu nuevo letrero elegante */
        font-weight: bold;
        font-size: 16px;
        color: #6f42c1;
        padding: 5px;
    }
    /* Hace que la pantalla gris se vea un poco más limpia */
    .stApp > header {
        background-color: transparent !important;
    }
    </style>
    """, unsafe_allow_html=True)

GOOGLE_SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID")
RENDER_API_KEY = st.secrets.get("RENDER_API_KEY")
RENDER_SERVICE_ID = st.secrets.get("RENDER_SERVICE_ID")

ODOO_URL = "https://wabu.odoo.com"
ODOO_DB = "wabu" 
ODOO_USER = st.secrets.get("ODOO_USER")
ODOO_API_KEY = st.secrets.get("ODOO_API_KEY")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")

# 🔒 SISTEMA DE AUTENTICACIÓN
st.sidebar.markdown("### 🔐 Acceso de Comandante")
password_ingresada = st.sidebar.text_input("Contraseña:", type="password")

# Si la contraseña coincide con tu secreto de GitHub/Streamlit, se habilita la edición
if password_ingresada == st.secrets.get("DASHBOARD_PASSWORD"):
    ES_SOLO_VISTA = False
    st.sidebar.success("Acceso concedido.")
else:
    ES_SOLO_VISTA = True
    st.sidebar.warning("Modo solo lectura.")

# LISTA MAESTRA DE REGLAS
LISTA_REGLAS = [
    "1. Gladiador", 
    "2. Ancla Mínimo", 
    "3. Cosecha Máximo", 
    "4. Analista Histórico",
    "5. Depredador (1+3)",
    "6. Francotirador (1+4)",
    "7. Bomba de Tiempo (2+3)",
    "8. Liquidador Sabio (2+4)"
]

# INICIALIZACIÓN DE FILTROS GLOBALES
if 'f_rent_lvp' not in st.session_state: st.session_state.f_rent_lvp = "Todos"
if 'f_est_lvp' not in st.session_state: st.session_state.f_est_lvp = "Todos"
if 'f_bb_lvp' not in st.session_state: st.session_state.f_bb_lvp = "Todos"
if 'f_regla_lvp' not in st.session_state: st.session_state.f_regla_lvp = "Todos" 
if 'f_ord_lvp' not in st.session_state: st.session_state.f_ord_lvp = "Ninguno"
if 'f_busq_lvp' not in st.session_state: st.session_state.f_busq_lvp = ""
if 'f_cat_lvp' not in st.session_state: st.session_state.f_cat_lvp = ""

if 'f_rent_wmt' not in st.session_state: st.session_state.f_rent_wmt = "Todos"
if 'f_est_wmt' not in st.session_state: st.session_state.f_est_wmt = "Todos"
if 'f_bb_wmt' not in st.session_state: st.session_state.f_bb_wmt = "Todos"
if 'f_regla_wmt' not in st.session_state: st.session_state.f_regla_wmt = "Todos" 
if 'f_ord_wmt' not in st.session_state: st.session_state.f_ord_wmt = "Ninguno"
if 'f_busq_wmt' not in st.session_state: st.session_state.f_busq_wmt = ""

if 'f_busq_mat' not in st.session_state: st.session_state.f_busq_mat = ""

if 'modo_operativo' not in st.session_state: st.session_state.modo_operativo = "📊 Dashboard Operativo"
if 'sesion_ia_actual' not in st.session_state: 
    st.session_state.sesion_ia_actual = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime("Chat_%Y-%m-%d_%H:%M")

def limpiar_filtros_editor():
    st.session_state.f_rent_lvp = "Todos"
    st.session_state.f_est_lvp = "Todos"
    st.session_state.f_bb_lvp = "Todos"
    st.session_state.f_regla_lvp = "Todos"
    st.session_state.f_ord_lvp = "Ninguno"
    st.session_state.f_busq_lvp = ""
    st.session_state.f_rent_wmt = "Todos"
    st.session_state.f_est_wmt = "Todos"
    st.session_state.f_bb_wmt = "Todos"
    st.session_state.f_regla_wmt = "Todos"
    st.session_state.f_ord_wmt = "Ninguno"
    st.session_state.f_busq_wmt = ""
    st.session_state.f_busq_mat = ""

def limpiar_filtros_catalogo():
    st.session_state.f_cat_lvp = ""

def safe_float(valor):
    try:
        if pd.isna(valor): return 0.0
        if isinstance(valor, str): valor = valor.replace('$', '').replace(',', '').strip()
        return float(valor)
    except: return 0.0

def obtener_conexion_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    try:
        # 1. Intentamos leer el archivo físico (por si haces pruebas en tu compu local)
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    except FileNotFoundError:
        # 2. Leemos la cuenta de servicio directamente del formato nativo de Streamlit
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        
    return gspread.authorize(creds)

@st.cache_data(ttl=10) 
def cargar_inventario_maestro():
    gc = obtener_conexion_sheets()
    
    # 🎯 EL DISPARO EXACTO: Buscamos la pestaña por su nombre real
    hoja = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Hoja 1")
    
    # 🛡️ LECTURA BLINDADA ANTI-ERRORES DE EXCEL 🛡️
    valores = hoja.get_all_values()
    if len(valores) < 2:
        return pd.DataFrame()
        
    encabezados = valores[0]
    df = pd.DataFrame(valores[1:], columns=encabezados)
    
    # 🧼 MAGIA LIMPIADORA: Quitar espacios y poner todo en minúsculas 
    df.columns = df.columns.str.strip().str.lower()
    
    # Limpiar columnas duplicadas o sin título
    df = df.loc[:, ~df.columns.duplicated()]
    if "" in df.columns:
        df = df.drop(columns=[""])
        
    # 👻 EXORCISMO DE FILAS FANTASMAS 👻
    # Si la fila no tiene SKU, la borramos para no leer las filas vacías de abajo
    if 'sku_interno' in df.columns:
        df = df[df['sku_interno'].astype(str).str.strip() != '']
    elif 'sku_limpio' in df.columns:
        df = df[df['sku_limpio'].astype(str).str.strip() != '']
    else:
        df = df.dropna(how='all')
    
    # Si de plano no existe, la creamos para que no llore
    if 'estatus' not in df.columns: 
        df['estatus'] = 'INACTIVO'
        
    df['estatus'] = df['estatus'].astype(str).str.strip().str.upper()
    
    if 'regla_estrategia' not in df.columns: df['regla_estrategia'] = '1. Gladiador'
    if 'estatus_wmt' not in df.columns: df['estatus_wmt'] = 'INACTIVO'
    if 'regla_wmt' not in df.columns: df['regla_wmt'] = '1. Gladiador'
    if 'sku_walmart' not in df.columns: df['sku_walmart'] = ''
    
    for col in ['precio_minimo', 'precio_maximo', 'minimo_wmt', 'maximo_wmt', 'costo_odoo']:
        if col not in df.columns: df[col] = 0.0
        else: 
            # Quitamos los signos de dólar y comas antes de convertir a número
            df[col] = df[col].astype(str).str.replace(r'[\$,]', '', regex=True)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            
    return df

@st.cache_data(ttl=10)
def cargar_bitacora_guerra(tienda="LVP"):
    gc = obtener_conexion_sheets()
    try:
        hoja_nombre = 'Historial' if tienda == "LVP" else 'Historial_WMT'
        hoja = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(hoja_nombre)
        
        # 🛡️ LECTURA BLINDADA PARA EL HISTORIAL 🛡️
        valores = hoja.get_all_values()
        if len(valores) < 2: 
            return pd.DataFrame()
            
        encabezados = valores[0]
        df_hist = pd.DataFrame(valores[1:], columns=encabezados)
        df_hist = df_hist.loc[:, ~df_hist.columns.duplicated()]
        
        col_fecha = next((col for col in df_hist.columns if 'fecha' in str(col).lower()), None)
        if col_fecha and not df_hist.empty: 
            df_hist['Fecha_Hora'] = pd.to_datetime(df_hist[col_fecha])
            
        return df_hist
    except: 
        return pd.DataFrame()

@st.cache_data(ttl=60)
def cargar_billetera_render():
    gc = obtener_conexion_sheets()
    try:
        hoja = gc.open_by_key(GOOGLE_SHEET_ID).worksheet('Config')
        presupuesto = safe_float(hoja.acell('D1').value)
        costo_barrido = safe_float(hoja.acell('D2').value)
        barridos = safe_float(hoja.acell('D3').value)
        gasto_total = barridos * costo_barrido
        saldo_restante = presupuesto - gasto_total
        return gasto_total, saldo_restante
    except: return 0.0, 0.0

@st.cache_data(ttl=300)
def obtener_ventas_hoy_odoo():
    try:
        common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(ODOO_URL))
        uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
        models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(ODOO_URL))
        hoy_str = datetime.now(timezone.utc).strftime('%Y-%m-%d 00:00:00')
        ventas = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'search_read', 
            [[['state', 'in', ['sale', 'done']], ['date_order', '>=', hoy_str]]], 
            {'fields': ['amount_total']})
        return sum([safe_float(v.get('amount_total', 0)) for v in ventas])
    except Exception as e: return 0.0

def guardar_cambios_en_sheets(df_completo):
    try:
        gc = obtener_conexion_sheets()
        hoja = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        hoja.clear()
        datos_a_subir = [df_completo.columns.values.tolist()] + df_completo.values.tolist()
        hoja.update(datos_a_subir)
        return True
    except Exception as e: return False

@st.cache_data(ttl=300) 
def obtener_diccionario_odoo():
    try:
        common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(ODOO_URL))
        uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
        models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(ODOO_URL))
        productos = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'product.product', 'search_read', [[]], {'fields': ['default_code', 'standard_price', 'name']})
        dicc_costos, dicc_nombres = {}, {}
        for p in productos:
            if p.get('default_code'): 
                code = p.get('default_code')
                dicc_costos[code] = safe_float(p.get('standard_price', 0.0))
                dicc_nombres[code] = p.get('name', 'Sin Nombre en Odoo')
        return dicc_costos, dicc_nombres
    except Exception as e: return {}, {}

def calcular_costo_compuesto(sku_limpio, dicc_costos):
    if not sku_limpio or pd.isna(sku_limpio): return 0.0
    sku_str = str(sku_limpio).strip().upper()
    partes = sku_str.split('/')
    costo_total = 0.0
    if len(partes) == 2 and partes[1].isdigit(): costo_total = dicc_costos.get(partes[0], 0.0) * int(partes[1])
    elif len(partes) > 1: 
        for p in partes: costo_total += dicc_costos.get(p, 0.0)
    else: costo_total = dicc_costos.get(sku_str, 0.0)
    return costo_total

def enriquecer_datos_tienda(df_base, df_hist, tienda="LVP"):
    dicc_costos, dicc_nombres = obtener_diccionario_odoo()
    nombres, costos, precios_act, stocks, fechas, pos, bbs, p_rivales = [], [], [], [], [], [], [], []
    util_m, util_p, proy_m, proy_p, alertas = [], [], [], [], []
    
    df_hist_sorted = df_hist.sort_values('Fecha_Hora', ascending=False) if not df_hist.empty and 'Fecha_Hora' in df_hist.columns else pd.DataFrame()
    
    if tienda == "WMT":
        col_minimo = 'minimo_wmt'
        costo_guia = 76.00
        factor_ingreso = 0.85
    else:
        col_minimo = 'precio_minimo'
        costo_guia = 130.00
        factor_ingreso = 0.83

    col_sku_hist = next((col for col in df_hist_sorted.columns if 'sku' in str(col).lower() and 'limpio' not in str(col).lower()), 'SKU_Interno')

    for _, row in df_base.iterrows():
        sku_interno = str(row.get('sku') or row.get('sku_interno') or row.get('SKU_Interno') or row.get('SKU') or '')
        sku_limpio = str(row.get('sku_limpio') or row.get('SKU_Limpio') or row.get('SKU Limpio') or row.get('sku limpio') or '')
        
        sku_base = sku_limpio.split('/')[0] if sku_limpio else ''
        nombre_odoo = dicc_nombres.get(sku_base, "No vinculado a Odoo")
        costo_s_iva = calcular_costo_compuesto(sku_limpio, dicc_costos)
        
        precio_final, stock_actual, ultima_fecha, ranking, ganador_bb, precio_bb = 0.0, "0", "Sin registro", "N/A", "N/A", 0.0
        
        if not df_hist_sorted.empty and sku_interno:
            hist_filtrado = df_hist_sorted[df_hist_sorted[col_sku_hist].astype(str) == sku_interno]
            if not hist_filtrado.empty:
                ultimo_registro = hist_filtrado.iloc[0]
                precio_final = safe_float(ultimo_registro.get('Nuestro_Precio') or ultimo_registro.get('nuestro_precio') or 0)
                precio_bb = safe_float(ultimo_registro.get('Precio_Rival') or ultimo_registro.get('precio_rival') or 0)
                stock_actual = str(ultimo_registro.get('Stock') or ultimo_registro.get('stock') or '0')
                ranking = str(ultimo_registro.get('Posicion') or ultimo_registro.get('posicion') or 'N/A')
                ganador_bb = str(ultimo_registro.get('BuyBox') or ultimo_registro.get('buybox') or 'N/A')
                fecha_val = ultimo_registro.get('Fecha_Hora')
                if pd.notnull(fecha_val):
                    try: ultima_fecha = fecha_val.strftime("%Y-%m-%d %H:%M")
                    except: ultima_fecha = str(fecha_val)
        
        if precio_final == 0.0: precio_final = safe_float(row.get(col_minimo, 0))

        nombres.append(nombre_odoo); costos.append(costo_s_iva); precios_act.append(precio_final)
        stocks.append(stock_actual); fechas.append(ultima_fecha); pos.append(ranking); bbs.append(ganador_bb); p_rivales.append(precio_bb)
        
        if costo_s_iva == 0 or precio_final == 0:
            util_m.append(0.0); util_p.append(0.0); proy_m.append(0.0); proy_p.append(0.0); alertas.append("⚪ Sin Datos")
            continue
            
        costo_c_iva = costo_s_iva * 1.16
        ingreso_bruto = (precio_final * factor_ingreso) - costo_guia
        base_impuestos = precio_final / 1.16
        suma_impuestos = (base_impuestos * 0.025) + (base_impuestos * 0.08)
        ingreso_neto = ingreso_bruto - suma_impuestos
        ganancia_neta = ingreso_neto - costo_c_iva
        margen = (ganancia_neta / costo_c_iva) * 100 if costo_c_iva > 0 else 0
        
        if precio_bb > 0 and ganador_bb != '¡Nosotros! 👑' and ganador_bb != 'N/A' and ganador_bb != 'Inactivo':
            ingreso_bruto_proy = (precio_bb * factor_ingreso) - costo_guia
            base_impuestos_proy = precio_bb / 1.16
            suma_impuestos_proy = (base_impuestos_proy * 0.025) + (base_impuestos_proy * 0.08)
            ingreso_neto_proy = ingreso_bruto_proy - suma_impuestos_proy
            ganancia_proy = ingreso_neto_proy - costo_c_iva
            margen_proy = (ganancia_proy / costo_c_iva) * 100 if costo_c_iva > 0 else 0
        else:
            ganancia_proy, margen_proy = 0.0, 0.0

        util_m.append(ganancia_neta); util_p.append(margen)
        proy_m.append(ganancia_proy); proy_p.append(margen_proy)
        alertas.append("🔴 Peligro (<10%)" if margen < 10 else "🟢 Saludable (>10%)")
            
    df_enriquecido = df_base.copy()
    cols_virtuales = ['nombre_odoo', 'precio_actual', 'stock_actual', 'posicion', 'buybox', 'precio_bb', 'ultima_rev', 'utilidad_$', 'utilidad_%', 'proyeccion_$', 'proyeccion_%', 'alerta']
    for c in cols_virtuales:
        if c in df_enriquecido.columns: df_enriquecido = df_enriquecido.drop(columns=[c])

    nombre_col_limpio = next((col for col in df_enriquecido.columns if 'limpio' in str(col).lower()), df_enriquecido.columns[0])
    df_enriquecido.insert(df_enriquecido.columns.get_loc(nombre_col_limpio)+1, 'nombre_odoo', nombres)
    df_enriquecido['costo_odoo'] = costos
    df_enriquecido['precio_actual'] = precios_act
    df_enriquecido['stock_actual'] = stocks
    df_enriquecido['posicion'] = pos
    df_enriquecido['buybox'] = bbs
    df_enriquecido['precio_bb'] = p_rivales
    df_enriquecido['ultima_rev'] = fechas
    df_enriquecido['utilidad_$'] = util_m
    df_enriquecido['utilidad_%'] = util_p
    df_enriquecido['proyeccion_$'] = proy_m
    df_enriquecido['proyeccion_%'] = proy_p
    df_enriquecido['alerta'] = alertas
    return df_enriquecido

def generar_matriz_unificada(df_base, df_hist_lvp, df_hist_wmt):
    df_lvp = enriquecer_datos_tienda(df_base, df_hist_lvp, "LVP")
    df_wmt = enriquecer_datos_tienda(df_base, df_hist_wmt, "WMT")
    
    col_limpio = next((col for col in df_lvp.columns if 'limpio' in str(col).lower()), df_lvp.columns[0])
    
    df_l = df_lvp[[col_limpio, 'nombre_odoo', 'costo_odoo', 'stock_actual', 'estatus', 'precio_actual', 'utilidad_%']].rename(
        columns={'estatus': 'estatus_lvp', 'precio_actual': 'precio_lvp', 'utilidad_%': 'margen_lvp'}
    )
    df_w = df_wmt[[col_limpio, 'estatus_wmt', 'precio_actual', 'utilidad_%']].rename(
        columns={'precio_actual': 'precio_wmt', 'utilidad_%': 'margen_wmt'}
    )
    
    df_matriz = pd.merge(df_l, df_w, on=col_limpio, how='left')
    
    recomendaciones = []
    for _, row in df_matriz.iterrows():
        m_lvp = safe_float(row.get('margen_lvp', 0))
        m_wmt = safe_float(row.get('margen_wmt', 0))
        e_lvp = str(row.get('estatus_lvp', ''))
        e_wmt = str(row.get('estatus_wmt', ''))

        if e_lvp != 'ACTIVO' and e_wmt != 'ACTIVO': recomendaciones.append("⚫ Apagado")
        elif e_lvp == 'ACTIVO' and e_wmt != 'ACTIVO': recomendaciones.append("🟣 Solo LVP")
        elif e_wmt == 'ACTIVO' and e_lvp != 'ACTIVO': recomendaciones.append("🔵 Solo WMT")
        else:
            diff = m_lvp - m_wmt
            if abs(diff) < 1.0: recomendaciones.append("⚖️ Empate Técnico")
            elif diff > 0: recomendaciones.append(f"🟣 LVP gana por {diff:.1f}%")
            else: recomendaciones.append(f"🔵 WMT gana por {abs(diff):.1f}%")
            
    df_matriz['recomendacion'] = recomendaciones
    
    cols_ordenadas = [
        col_limpio, 'nombre_odoo', 'stock_actual', 'costo_odoo', 
        'precio_lvp', 'margen_lvp', 'estatus_lvp',
        'precio_wmt', 'margen_wmt', 'estatus_wmt',
        'recomendacion'
    ]
    return df_matriz[cols_ordenadas], col_limpio

@st.fragment
def renderizar_calculadora(tienda_activa="LVP"):
    st.markdown(f"### 🧮 Calculadora Táctica ({'Walmart' if tienda_activa == 'WMT' else 'Liverpool'})")
    con_iva_global = st.checkbox("✅ Marcar si los costos ingresados YA incluyen IVA", value=False, key=f"chk_iva_{tienda_activa}")
    
    comision = 0.15 if tienda_activa == "WMT" else 0.17
    costo_guia = 76.00 if tienda_activa == "WMT" else 130.00
    factor_ingreso = 1.0 - comision
    
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1:
        st.markdown("**Modo A: De Costo a Precio de Venta**")
        c_base_a = st.number_input("Costo Odoo", key=f'ca_{tienda_activa}', value=0.0)
        util_deseada = st.slider("Utilidad Neta Deseada %", 0, 50, key=f'ua_{tienda_activa}', value=15)
        costo_iva_a = c_base_a if con_iva_global else c_base_a * 1.16
        factor_div = (factor_ingreso - (0.08 / 1.16) - (0.025 / 1.16))
        precio_sug = ((costo_iva_a * (1 + (util_deseada/100))) + costo_guia) / factor_div if factor_div > 0 else 0
        ganancia_modo_a = costo_iva_a * (util_deseada/100)
        st.success(f"🎯 Precio Sugerido: **${precio_sug:,.2f}**")
        st.info(f"💵 Ganancia: **${ganancia_modo_a:,.2f}** | 📈 Margen: **{util_deseada}%**")
        
    with col_c2:
        st.markdown("**Modo B: De Precio a Costo Límite**")
        p_final_b = st.number_input("Precio Final", key=f'pb_{tienda_activa}', value=0.0)
        u_deseada_b = st.slider("Utilidad Mínima %", 0, 50, key=f'ub_{tienda_activa}', value=15)
        ing_bruto_b = (p_final_b * factor_ingreso) - costo_guia
        imp_b = (p_final_b/1.16) * 0.025 + (p_final_b/1.16) * 0.08
        ing_neto_b = ing_bruto_b - imp_b
        costo_limite_c_iva = ing_neto_b / (1 + (u_deseada_b/100)) if u_deseada_b > -100 else 0
        costo_limite_mostrar = costo_limite_c_iva if con_iva_global else costo_limite_c_iva / 1.16
        ganancia_modo_b = ing_neto_b - costo_limite_c_iva
        margen_real_b = (ganancia_modo_b / costo_limite_c_iva) * 100 if costo_limite_c_iva > 0 else 0
        st.warning(f"🛑 Costo Máximo: **${costo_limite_mostrar:,.2f}**")
        st.info(f"💵 Ganancia: **${ganancia_modo_b:,.2f}** | 📈 Margen: **{margen_real_b:.1f}%**")
        
    with col_c3:
        st.markdown("**Modo C: Simulador Libre**")
        c_base_c = st.number_input("Costo Odoo", key=f'cc_{tienda_activa}', value=0.0)
        p_final_c = st.number_input("Precio Final", key=f'pc_{tienda_activa}', value=0.0)
        costo_iva_c = c_base_c if con_iva_global else c_base_c * 1.16
        ing_bruto_c = (p_final_c * factor_ingreso) - costo_guia
        imp_c = (p_final_c/1.16) * 0.025 + (p_final_c/1.16) * 0.08
        ing_neto_c = ing_bruto_c - imp_c
        ganancia_modo_c = ing_neto_c - costo_iva_c
        margen_real_c = (ganancia_modo_c / costo_iva_c) * 100 if costo_iva_c > 0 else 0
        if margen_real_c > 10: st.success(f"✅ Sano")
        elif margen_real_c > 0: st.warning(f"⚠️ Bajo")
        else: st.error(f"🚨 Pérdida")
        st.info(f"💵 Ganancia: **${ganancia_modo_c:,.2f}** | 📈 Margen: **{margen_real_c:.1f}%**")

# ==========================================
# CEREBRO DE LA IA
# ==========================================
def cargar_historial_completo_ia():
    try:
        gc = obtener_conexion_sheets()
        hoja = gc.open_by_key(GOOGLE_SHEET_ID).worksheet('Memoria_AI')
        df = pd.DataFrame(hoja.get_all_records())
        return df
    except: return pd.DataFrame()

def guardar_mensaje_ia(id_sesion, rol, mensaje):
    try:
        gc = obtener_conexion_sheets()
        hoja = gc.open_by_key(GOOGLE_SHEET_ID).worksheet('Memoria_AI')
        fecha_str = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        hoja.append_row([str(id_sesion), fecha_str, str(rol), str(mensaje)])
    except: pass


# ==========================================
# 3. INTERFAZ PRINCIPAL 
# ==========================================
if os.path.exists("logo_wabu.jpeg"):
    st.sidebar.image("logo_wabu.jpeg", use_column_width=True)

modo_app = st.sidebar.radio("Cambiar de Interfaz:", ["📊 Dashboard Operativo", "🌐 Matriz Unificada", "🧠 Megazord AI (Copiloto)"])
st.session_state.modo_operativo = modo_app
st.sidebar.markdown("---")

df_base = cargar_inventario_maestro()

# ==========================
# NIVEL A: DASHBOARD OPERATIVO
# ==========================
if st.session_state.modo_operativo == "📊 Dashboard Operativo":
    st.sidebar.title("🤖 Megazord OS")
    if ES_SOLO_VISTA:
        st.sidebar.warning("👁️ MODO INVITADO: Solo visualización.")
    
    tienda_seleccionada = st.sidebar.radio("Base Operativa:", ["🟣 Liverpool", "🔵 Walmart", "🟡 Mercado Libre", "🟡 Coppel"])
    
    if st.sidebar.button("🔄 Forzar Conexión Odoo", use_container_width=True):
        obtener_diccionario_odoo.clear()
        st.sidebar.success("Conexión reiniciada...")
    
    # --- LÓGICA LIVERPOOL ---
    if tienda_seleccionada == "🟣 Liverpool":
        st.title("🟣 Radar Táctico: Liverpool")
        df_hist = cargar_bitacora_guerra(tienda="LVP")
        df_enriquecido = enriquecer_datos_tienda(df_base, df_hist, tienda="LVP")

        # ==========================================
        # SECCIÓN 1: TARJETAS DE KPIs (PARTE SUPERIOR)
        # ==========================================
        st.subheader("📊 Resumen Ejecutivo")

        # Calcular KPIs principales
        total_skus = len(df_enriquecido[df_enriquecido['estatus'] == 'ACTIVO'])
        buybox_ganadas = len(df_enriquecido[(df_enriquecido['estatus'] == 'ACTIVO') & (df_enriquecido['buybox'] == '¡Nosotros! 👑')])
        skus_sin_rival = len(df_enriquecido[(df_enriquecido['estatus'] == 'ACTIVO') & (df_enriquecido['buybox'].astype(str).str.contains('SIN RIVAL|Sin Rival', na=False))])

        # Fila de tarjetas KPI
        kpi_col1, kpi_col2, kpi_col3 = st.columns(3)

        with kpi_col1:
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 15px; color: white; text-align: center;">
                <h3 style="margin: 0; font-size: 2.5rem;">{total_skus}</h3>
                <p style="margin: 5px 0 0 0; font-size: 0.9rem; opacity: 0.9;">📦 SKUs Activos</p>
            </div>
            """, unsafe_allow_html=True)

        with kpi_col2:
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); padding: 20px; border-radius: 15px; color: white; text-align: center;">
                <h3 style="margin: 0; font-size: 2.5rem;">{buybox_ganadas}</h3>
                <p style="margin: 5px 0 0 0; font-size: 0.9rem; opacity: 0.9;">👑 BuyBoxes Ganadas</p>
            </div>
            """, unsafe_allow_html=True)

        with kpi_col3:
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); padding: 20px; border-radius: 15px; color: white; text-align: center;">
                <h3 style="margin: 0; font-size: 2.5rem;">{skus_sin_rival}</h3>
                <p style="margin: 5px 0 0 0; font-size: 0.9rem; opacity: 0.9;">🎯 SKUs Sin Rival</p>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        # ==========================================
        # SECCIÓN 2: GRÁFICA CIRCULAR DE DISTRIBUCIÓN BUYBOX
        # ==========================================
        st.subheader("🥧 Distribución del Estatus BuyBox")

        # Calcular distribución
        buybox_perdidas = len(df_enriquecido[(df_enriquecido['estatus'] == 'ACTIVO') & (df_enriquecido['buybox'] != '¡Nosotros! 👑') & (~df_enriquecido['buybox'].astype(str).str.contains('SIN RIVAL|Sin Rival|N/A', na=False))])

        datos_distribucion = pd.DataFrame({
            'Estatus': ['👑 Ganada', '🎯 Sin Rival', '⚔️ Competencia'],
            'Cantidad': [buybox_ganadas, skus_sin_rival, buybox_perdidas]
        })

        # Crear gráfica con Altair (nativo de Streamlit)
        import altair as alt

        source = alt.Data(values=[
            {"Estatus": "👑 Ganada", "Cantidad": buybox_ganadas},
            {"Estatus": "🎯 Sin Rival", "Cantidad": skus_sin_rival},
            {"Estatus": "⚔️ Competencia", "Cantidad": buybox_perdidas}
        ])

        pie_chart = alt.Chart(source).mark_arc().encode(
            theta=alt.Theta(field="Cantidad", type="quantitative"),
            color=alt.Color(
                field="Estatus",
                type="nominal",
                scale=alt.Scale(
                    domain=["👑 Ganada", "🎯 Sin Rival", "⚔️ Competencia"],
                    range=["#28a745", "#17a2b8", "#dc3545"]
                )
            ),
            tooltip=[alt.Tooltip("Estatus:N"), alt.Tooltip("Cantidad:Q")]
        ).properties(
            width=400,
            height=300,
            title="Distribución BuyBox - Liverpool"
        )

        st.altair_chart(pie_chart, use_container_width=False)

        st.markdown("---")

        # ==========================================
        # SECCIÓN 3: TABLA FILTRABLE CON BUSCADOR POR SKU
        # ==========================================
        st.subheader("🔍 Buscar Producto por SKU")

        # Input de búsqueda
        sku_busqueda = st.text_input(
            "Ingresa el SKU Interno o nombre del producto:",
            placeholder="Ej: PERFUME-001 o Dior",
            help="Escribe para filtrar los resultados en tiempo real"
        )

        # Filtrar datos por búsqueda
        if sku_busqueda:
            df_filtrado = df_enriquecido[
                df_enriquecido['sku_limpio'].astype(str).str.contains(sku_busqueda.upper(), na=False, case=False) |
                df_enriquecido['nombre_odoo'].astype(str).str.contains(sku_busqueda, na=False, case=False)
            ]
        else:
            df_filtrado = df_enriquecido[df_enriquecido['estatus'] == 'ACTIVO']

        # Mostrar contador de resultados
        st.caption(f"Mostrando {len(df_filtrado)} productos")

        # Columnas a mostrar
        columnas_mostrar = [
            'sku_limpio', 'nombre_odoo', 'precio_actual', 'precio_bb',
            'stock_actual', 'posicion', 'buybox', 'utilidad_%', 'alerta'
        ]

        # Mostrar tabla
        if len(df_filtrado) > 0:
            st.dataframe(
                df_filtrado[columnas_mostrar],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "sku_limpio": st.column_config.TextColumn("SKU", width="medium"),
                    "nombre_odoo": st.column_config.TextColumn("Producto", width="large"),
                    "precio_actual": st.column_config.NumberColumn("Nuestro Precio", format="$%.2f"),
                    "precio_bb": st.column_config.NumberColumn("Precio Rival", format="$%.2f"),
                    "stock_actual": st.column_config.NumberColumn("Stock", format="%d"),
                    "posicion": st.column_config.TextColumn("Posición", width="small"),
                    "buybox": st.column_config.TextColumn("BuyBox", width="small"),
                    "utilidad_%": st.column_config.NumberColumn("Margen %", format="%.2f%%"),
                    "alerta": st.column_config.TextColumn("Rentabilidad", width="small")
                }
            )
        else:
            st.info("🔍 No se encontraron productos que coincidan con tu búsqueda.")

        st.markdown("---")

        # ==========================================
        # BOTONES DE ACCIÓN RÁPIDA (ACTUALIZADOS PARA GITHUB)
        # ==========================================
        c1, c2, c3 = st.columns(3)
        with c1:
            if not ES_SOLO_VISTA:
                if st.button("🚀 Forzar Barrido Ahora", use_container_width=True, type="primary"):
                    url = "https://api.github.com/repos/FernandoWABU/bot-liverpool/actions/workflows/main.yml/dispatches"
                    headers = {
                        "Accept": "application/vnd.github.v3+json",
                        "Authorization": f"Bearer {st.secrets['GITHUB_PAT']}", 
                        "X-GitHub-Api-Version": "2022-11-28"
                    }
                    # Enviamos la petición POST
                    res = requests.post(url, headers=headers, json={"ref": "main"})
                    if res.status_code == 204:
                        st.success("¡Megazord disparado en GitHub! ☁️🤖")
                    else:
                        st.error(f"Error al disparar: {res.status_code}")
        with c2: st.link_button("📝 Abrir Base (Excel)", f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit", use_container_width=True)
        with c3: st.link_button("📊 Ver Consola (GitHub)", "https://github.com/FernandoWABU/bot-liverpool/actions", use_container_width=True)
        
        st.markdown("---")

        tab1, tab2, tab3, tab4 = st.tabs(["📊 Editor Financiero", "🗂️ Catálogo Visual", "🧮 Calculadora Táctica", "📜 Reglas"])

        with tab1:
            st.markdown("### 🎛️ Editor Maestro Multiverso")
            
            # 1. EL SELECTOR DE MAGIA (El radio button que pediste)
            vista_tienda = st.radio(
                "👁️ Selecciona qué tienda operar:", 
                ["🟣 Modo Liverpool", "🔵 Modo Walmart", "🌐 Ver Todo (Scroll)"], 
                horizontal=True
            )
            st.markdown("---")

            # 2. LOS FILTROS ACTUALES (Mantenemos los tuyos intactos)
            f_col1, f_col2, f_col3, f_col4, f_col5, f_col6, f_col7 = st.columns([1, 1, 1, 1.5, 1, 1.5, 0.8])
            with f_col1: st.selectbox("BuyBox:", ["Todos", "👑 Ganando", "❌ Perdiendo"], key='f_bb_lvp')
            with f_col2: st.selectbox("Rentabilidad:", ["Todos", "🟢 Saludable (>10%)", "🔴 Peligro (<10%)"], key='f_rent_lvp')
            with f_col3: st.selectbox("Estatus:", ["Todos", "ACTIVO", "INACTIVO"], key='f_est_lvp')
            with f_col4: st.selectbox("Regla LVP:", ["Todos"] + LISTA_REGLAS, key='f_regla_lvp')
            with f_col5: st.selectbox("Ordenar:", ["Ninguno", "Mayor Utilidad", "Mayor Margen"], key='f_ord_lvp')
            with f_col6: st.text_input("🔍 Buscar:", key='f_busq_lvp')
            with f_col7: 
                st.write("") 
                st.button("🧹 Limpiar", on_click=limpiar_filtros_editor, use_container_width=True, key="btn_limpiar_editor_lvp")
                
            # 3. APLICAR FILTROS DE BÚSQUEDA
            df_mostrar = df_enriquecido.copy()
            if st.session_state.f_bb_lvp == "👑 Ganando": df_mostrar = df_mostrar[df_mostrar['buybox'] == '¡Nosotros! 👑']
            elif st.session_state.f_bb_lvp == "❌ Perdiendo": df_mostrar = df_mostrar[(df_mostrar['buybox'] != '¡Nosotros! 👑') & (df_mostrar['buybox'] != 'N/A') & (df_mostrar['buybox'] != 'Inactivo')]
            if st.session_state.f_rent_lvp != "Todos": df_mostrar = df_mostrar[df_mostrar['alerta'] == st.session_state.f_rent_lvp]
            if st.session_state.f_est_lvp != "Todos": df_mostrar = df_mostrar[df_mostrar['estatus'] == st.session_state.f_est_lvp]
            if st.session_state.f_regla_lvp != "Todos": df_mostrar = df_mostrar[df_mostrar['regla_estrategia'] == st.session_state.f_regla_lvp]
            if st.session_state.f_busq_lvp: df_mostrar = df_mostrar[df_mostrar.astype(str).apply(lambda x: x.str.contains(st.session_state.f_busq_lvp, case=False)).any(axis=1)]
            
            if st.session_state.f_ord_lvp == "Mayor Utilidad": df_mostrar = df_mostrar.sort_values('utilidad_$', ascending=False)
            elif st.session_state.f_ord_lvp == "Mayor Margen": df_mostrar = df_mostrar.sort_values('utilidad_%', ascending=False)
            
            # 4. LA MAGIA DE LAS COLUMNAS DINÁMICAS (PIEZAS DE LEGO)
            nombre_col_limpio = next((col for col in df_mostrar.columns if 'limpio' in str(col).lower()), 'sku_limpio')
            
            # Agregamos el Stock a las columnas fijas
            cols_fijas = [nombre_col_limpio, "nombre_odoo", "stock_actual", "costo_odoo"]
            
            # 🚀 ¡AQUÍ ESTÁ LA MAGIA! Agregamos BuyBox y Proyecciones a la vista de LVP
            cols_liverpool = [
                "sku_interno", 
                "buybox",         # Status BuyBox (Nosotros o Rival)
                "precio_bb",      # El precio del que va ganando
                "precio_actual",  # A qué precio estamos nosotros ahorita
                "utilidad_$",     # Cuánto estamos ganando ahorita
                "utilidad_%",     # Qué margen tenemos ahorita
                "proyeccion_$",   # ¿Cuánto ganaríamos si bajamos a empatar la BuyBox?
                "proyeccion_%",   # ¿Qué margen nos quedaría si empatamos?
                "alerta",         # Semáforo de salud
                "precio_minimo", 
                "precio_maximo", 
                "estatus", 
                "regla_estrategia"
            ]
            
            # Las de Walmart (mantenemos las de edición por ahora)
            cols_walmart = ["sku_walmart", "minimo_wmt", "maximo_wmt", "estatus_wmt", "regla_wmt"]
            
            # Armamos el orden exacto que Streamlit debe dibujar según el botón
            if vista_tienda == "🟣 Modo Liverpool":
                orden_columnas = cols_fijas + cols_liverpool
            elif vista_tienda == "🔵 Modo Walmart":
                orden_columnas = cols_fijas + cols_walmart
            else:
                orden_columnas = cols_fijas + cols_liverpool + cols_walmart

            # 5. EL DATA EDITOR MAESTRO
            df_editado = st.data_editor(
                df_mostrar,
                use_container_width=True, hide_index=True, num_rows="dynamic", disabled=ES_SOLO_VISTA,
                column_order=orden_columnas,
                column_config={
                    nombre_col_limpio: "SKU Limpio", 
                    "nombre_odoo": st.column_config.TextColumn("Producto", disabled=True),
                    "costo_odoo": st.column_config.NumberColumn("Costo Odoo🏢", format="$%.2f", disabled=True),
                    "stock_actual": st.column_config.NumberColumn("Stock📦", disabled=True),
                    
                    # --- Nombres Liverpool (Lectura / Radar) ---
                    "sku_interno": st.column_config.TextColumn("SKU LVP", disabled=True),
                    "buybox": st.column_config.TextColumn("Status BuyBox👑", disabled=True),
                    "precio_bb": st.column_config.NumberColumn("Precio a Vencer⚔️", format="$%.2f", disabled=True),
                    "precio_actual": st.column_config.NumberColumn("Nuestro Precio🤖", format="$%.2f", disabled=True),
                    "utilidad_$": st.column_config.NumberColumn("Ganancia Actual", format="$%.2f", disabled=True),
                    "utilidad_%": st.column_config.NumberColumn("Margen Actual", format="%.2f%%", disabled=True),
                    "proyeccion_$": st.column_config.NumberColumn("Proy. Ganancia ($)", format="$%.2f", disabled=True, help="Lo que ganarías si igualas el precio del rival"),
                    "proyeccion_%": st.column_config.NumberColumn("Proy. Margen (%)", format="%.2f%%", disabled=True, help="Tu margen si igualas el precio del rival"),
                    "alerta": st.column_config.TextColumn("Salud", disabled=True),
                    
                    # --- Nombres Liverpool (Escritura / Tácticos) ---
                    "precio_minimo": st.column_config.NumberColumn("Mínimo LVP📉", format="$%.2f"),
                    "precio_maximo": st.column_config.NumberColumn("Máximo LVP📈", format="$%.2f"),
                    "estatus": st.column_config.SelectboxColumn("Operación LVP", options=["ACTIVO", "INACTIVO"]),
                    "regla_estrategia": st.column_config.SelectboxColumn("Regla LVP", options=LISTA_REGLAS),
                    
                    # --- Nombres Walmart ---
                    "sku_walmart": st.column_config.TextColumn("SKU Feo WMT"),
                    "minimo_wmt": st.column_config.NumberColumn("Mínimo WMT📉", format="$%.2f"),
                    "maximo_wmt": st.column_config.NumberColumn("Máximo WMT📈", format="$%.2f"),
                    "estatus_wmt": st.column_config.SelectboxColumn("Operación WMT", options=["ACTIVO", "INACTIVO"]),
                    "regla_wmt": st.column_config.SelectboxColumn("Regla WMT", options=LISTA_REGLAS)
                }
            )

            # 6. BOTÓN DE GUARDADO UNIVERSAL
            if not ES_SOLO_VISTA:
                if st.button("💾 Guardar Estrategia Global", use_container_width=True, type="secondary"):
                    with st.spinner("Tatuando datos en Excel..."):
                        df_listo_guardar = df_base.copy()
                        for idx, row in df_editado.iterrows():
                            if idx in df_listo_guardar.index:
                                # Actualiza todo de golpe, importando poco qué vista estabas viendo
                                df_listo_guardar.at[idx, 'precio_minimo'] = row.get('precio_minimo', 0)
                                df_listo_guardar.at[idx, 'precio_maximo'] = row.get('precio_maximo', 0)
                                df_listo_guardar.at[idx, 'estatus'] = row.get('estatus', 'INACTIVO')
                                df_listo_guardar.at[idx, 'regla_estrategia'] = row.get('regla_estrategia', '1. Gladiador')
                                df_listo_guardar.at[idx, 'costo_odoo'] = row.get('costo_odoo', 0)
                                
                                if 'sku_walmart' in row: df_listo_guardar.at[idx, 'sku_walmart'] = row['sku_walmart']
                                if 'minimo_wmt' in row: df_listo_guardar.at[idx, 'minimo_wmt'] = row.get('minimo_wmt', 0)
                                if 'maximo_wmt' in row: df_listo_guardar.at[idx, 'maximo_wmt'] = row.get('maximo_wmt', 0)
                                if 'estatus_wmt' in row: df_listo_guardar.at[idx, 'estatus_wmt'] = row.get('estatus_wmt', 'INACTIVO')
                                if 'regla_wmt' in row: df_listo_guardar.at[idx, 'regla_wmt'] = row.get('regla_wmt', '1. Gladiador')

                        if guardar_cambios_en_sheets(df_listo_guardar):
                            st.success("¡Sincronización Multiverso completa! ✅")
                            st.cache_data.clear()
                            st.rerun()

        with tab2:
            cat_c1, cat_c2 = st.columns([5, 1])
            with cat_c1: st.text_input("🔍 Buscar en Catálogo:", key='f_cat_lvp')
            with cat_c2: 
                st.write("")
                st.button("🧹 Limpiar", on_click=limpiar_filtros_catalogo, use_container_width=True, key="btn_limpiar_catalogo_lvp")
                
            df_cat = df_mostrar.copy() 
            if st.session_state.f_cat_lvp: df_cat = df_cat[df_cat.astype(str).apply(lambda x: x.str.contains(st.session_state.f_cat_lvp, case=False)).any(axis=1)]

            for _, row in df_cat.iterrows():
                estatus = row.get('estatus', 'INACTIVO')
                clase_css = "card-activo" if estatus == "ACTIVO" else "card-inactivo"
                sku_sucio = str(row.get('sku', row.get('sku_interno', 'Sin SKU')))
                col_limpio_cat = next((col for col in row.keys() if 'limpio' in str(col).lower()), None)
                sku_limpio_real = str(row.get(col_limpio_cat, '')) if col_limpio_cat else ''
                nombre_producto = str(row.get('nombre_odoo', ''))
                regla_actual = str(row.get('regla_estrategia', '1. Gladiador'))
                
                st.markdown(f"""
                    <div class="{clase_css}">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin:0; font-size: 1.2rem; color: #2c3e50;">{sku_limpio_real} - {nombre_producto}</h3>
                            <div><span class='badge-regla'>🧠 {regla_actual}</span> <span class='badge-stock'>📦 Stock: {row.get('stock_actual', '0')}</span> <span class='badge-pos'>🏆 Rank: {row.get('posicion', 'N/A')}</span></div>
                        </div>
                        <hr style="margin: 10px 0;">
                        <div style="display: flex; flex-wrap: wrap; gap: 20px; font-size: 0.95rem;">
                            <div><b>SKU Sucio LVP:</b> {sku_sucio}</div>
                            <div><b>Estatus:</b> {estatus}</div>
                            <div><b>BuyBox Actual:</b> <span style="color:#e74c3c; font-weight:bold;">{row.get('buybox', 'N/A')}</span></div>
                            <div><b>Mínimo LVP:</b> ${safe_float(row.get('precio_minimo', 0)):,.2f}</div>
                            <div><b>Máximo LVP:</b> ${safe_float(row.get('precio_maximo', 0)):,.2f}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

        with tab3:
            renderizar_calculadora(tienda_activa="LVP")
            
        with tab4:
            st.markdown("""
            ### 📜 Manual de Operaciones Automáticas (Arsenal Híbrido)
            Elige la táctica de combate que Megazord ejecutará para cada producto:
            
            **REGLAS BÁSICAS (Comportamiento Fijo):**
            * ⚔️ **1. Gladiador:** Pelea el 1er lugar bajando centavos hasta tu precio mínimo.
            * ⚓ **2. Ancla Mínimo:** Ignora a la competencia y se clava siempre en tu precio mínimo (Liquidación).
            * 🌾 **3. Cosecha Máximo:** Ignora a la competencia y sube tu precio al tope máximo (Venta cara).
            * 🕵️‍♂️ **4. Analista Histórico:** Se coloca en el precio promedio donde tú lograste vender en el pasado.
            
            **REGLAS HÍBRIDAS (Reacción Automática):**
            * 🦅 **5. Depredador (1+3):** Pelea a muerte bajando centavos (1) peeeero... si el rival se queda sin stock, infla el precio de golpe a tu Máximo (3).
            * 🎯 **6. Francotirador (1+4):** Pelea a muerte bajando centavos (1) peeeero... si el rival se queda sin stock, regresa a tu Precio Histórico seguro (4) para no asustar al cliente.
            * ⏱️ **7. Bomba de Tiempo (2+3):** Clava el precio en el mínimo para asfixiar al rival (2) peeeero... en cuanto el rival se queda en ceros, explota hacia tu Precio Máximo (3).
            * 🧠 **8. Liquidador Sabio (2+4):** Clava el precio en el mínimo por volumen (2) peeeero... si te quedas solo en el listado, regresa a un Precio Histórico moderado (4).
            """)

    # --- LÓGICA WALMART ---
    elif tienda_seleccionada == "🔵 Walmart":
        st.title("🔵 Radar Táctico: Walmart")
        df_hist_wmt = cargar_bitacora_guerra(tienda="WMT")
        df_enriquecido = enriquecer_datos_tienda(df_base, df_hist_wmt, tienda="WMT")
        
        try:
            total_activos = len(df_enriquecido[df_enriquecido['estatus_wmt'] == 'ACTIVO'])
            buybox_ganadas = len(df_enriquecido[df_enriquecido['buybox'] == '¡Nosotros! 👑'])
            col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
            col_kpi1.metric("SKUs Activos WMT", f"{total_activos}")
            col_kpi2.metric("BuyBox WMT 👑", f"{buybox_ganadas}")
        except: pass
        st.markdown("---")

        tab1, tab2, tab3 = st.tabs(["📊 Editor Financiero", "🧮 Calculadora Táctica", "📜 Reglas"])

        with tab1:
            f_col1, f_col2, f_col3, f_col4, f_col5, f_col6, f_col7 = st.columns([1, 1, 1, 1.5, 1, 1.5, 0.8])
            with f_col1: st.selectbox("BuyBox:", ["Todos", "👑 Ganando", "❌ Perdiendo"], key='f_bb_wmt')
            with f_col2: st.selectbox("Rentabilidad:", ["Todos", "🟢 Saludable (>10%)", "🔴 Peligro (<10%)"], key='f_rent_wmt')
            with f_col3: st.selectbox("Estatus:", ["Todos", "ACTIVO", "INACTIVO"], key='f_est_wmt')
            with f_col4: st.selectbox("Regla WMT:", ["Todos"] + LISTA_REGLAS, key='f_regla_wmt')
            with f_col5: st.selectbox("Ordenar:", ["Ninguno", "Mayor Utilidad", "Mayor Margen"], key='f_ord_wmt')
            with f_col6: st.text_input("🔍 Buscar:", key='f_busq_wmt')
            with f_col7: 
                st.write("") 
                st.button("🧹 Limpiar", on_click=limpiar_filtros_editor, use_container_width=True, key="btn_limpiar_editor_wmt")
                
            df_mostrar = df_enriquecido.copy()
            if st.session_state.f_bb_wmt == "👑 Ganando": df_mostrar = df_mostrar[df_mostrar['buybox'] == '¡Nosotros! 👑']
            elif st.session_state.f_bb_wmt == "❌ Perdiendo": df_mostrar = df_mostrar[(df_mostrar['buybox'] != '¡Nosotros! 👑') & (df_mostrar['buybox'] != 'N/A') & (df_mostrar['buybox'] != 'Inactivo')]
            if st.session_state.f_rent_wmt != "Todos": df_mostrar = df_mostrar[df_mostrar['alerta'] == st.session_state.f_rent_wmt]
            if st.session_state.f_est_wmt != "Todos": df_mostrar = df_mostrar[df_mostrar['estatus_wmt'] == st.session_state.f_est_wmt]
            if st.session_state.f_regla_wmt != "Todos": df_mostrar = df_mostrar[df_mostrar['regla_wmt'] == st.session_state.f_regla_wmt]
            if st.session_state.f_busq_wmt: df_mostrar = df_mostrar[df_mostrar.astype(str).apply(lambda x: x.str.contains(st.session_state.f_busq_wmt, case=False)).any(axis=1)]
            
            if st.session_state.f_ord_wmt == "Mayor Utilidad": df_mostrar = df_mostrar.sort_values('utilidad_$', ascending=False)
            elif st.session_state.f_ord_wmt == "Mayor Margen": df_mostrar = df_mostrar.sort_values('utilidad_%', ascending=False)
            
            cols_lvp = ['sku', 'sku_interno', 'sku_liverpool', 'estatus', 'precio_minimo', 'precio_maximo', 'regla_estrategia']
            df_wmt_ui = df_mostrar.drop(columns=[c for c in cols_lvp if c in df_mostrar.columns], errors='ignore')
            nombre_col_limpio = next((col for col in df_wmt_ui.columns if 'limpio' in str(col).lower()), df_wmt_ui.columns[0])

            df_editado_wmt = st.data_editor(
                df_wmt_ui,
                use_container_width=True, hide_index=True, num_rows="dynamic", disabled=ES_SOLO_VISTA,
                column_config={
                    nombre_col_limpio: "SKU Limpio", 
                    "nombre_odoo": st.column_config.TextColumn("Producto", disabled=True),
                    "costo_odoo": st.column_config.NumberColumn("Costo Odoo🏢", format="$%.2f", disabled=True),
                    "precio_actual": st.column_config.NumberColumn("Precio WMT🤖", format="$%.2f", disabled=True),
                    "utilidad_$": st.column_config.NumberColumn("Ganancia WMT💵", format="$%.2f", disabled=True),
                    "utilidad_%": st.column_config.NumberColumn("Margen WMT%", format="%.2f%%", disabled=True),
                    "proyeccion_$": st.column_config.NumberColumn("Proy. Ganancia ($)", format="$%.2f", disabled=True),
                    "proyeccion_%": st.column_config.NumberColumn("Proy. Margen (%)", format="%.2f%%", disabled=True),
                    "alerta": "Rentabilidad",
                    "sku_walmart": st.column_config.TextColumn("SKU Feo Walmart"),
                    "minimo_wmt": st.column_config.NumberColumn("Mínimo WMT📉", format="$%.2f"),
                    "maximo_wmt": st.column_config.NumberColumn("Máximo WMT📈", format="$%.2f"),
                    "estatus_wmt": st.column_config.SelectboxColumn("Operación WMT", options=["ACTIVO", "INACTIVO"]),
                    "regla_wmt": st.column_config.SelectboxColumn("Regla WMT", options=LISTA_REGLAS)
                }
            )

            if not ES_SOLO_VISTA:
                if st.button("💾 Guardar Estrategia (Walmart)", use_container_width=True, type="primary"):
                    with st.spinner("Tatuando datos de Walmart..."):
                        df_final_a_guardar = df_base.copy()
                        for idx, row in df_editado_wmt.iterrows():
                            if idx in df_final_a_guardar.index:
                                if 'sku_walmart' in row: df_final_a_guardar.at[idx, 'sku_walmart'] = row['sku_walmart']
                                df_final_a_guardar.at[idx, 'minimo_wmt'] = row['minimo_wmt']
                                df_final_a_guardar.at[idx, 'maximo_wmt'] = row['maximo_wmt']
                                df_final_a_guardar.at[idx, 'estatus_wmt'] = row['estatus_wmt']
                                df_final_a_guardar.at[idx, 'regla_wmt'] = row['regla_wmt']
                                df_final_a_guardar.at[idx, 'costo_odoo'] = row['costo_odoo']

                        if guardar_cambios_en_sheets(df_final_a_guardar):
                            st.success("¡Walmart actualizado! ✅")
                            st.cache_data.clear()
                            st.rerun()

        with tab2:
            renderizar_calculadora(tienda_activa="WMT")
            
        with tab3:
            st.markdown("""
            ### 📜 Manual de Operaciones Automáticas (Arsenal Híbrido)
            Elige la táctica de combate que Megazord ejecutará para cada producto:
            
            **REGLAS BÁSICAS (Comportamiento Fijo):**
            * ⚔️ **1. Gladiador:** Pelea el 1er lugar bajando centavos hasta tu precio mínimo.
            * ⚓ **2. Ancla Mínimo:** Ignora a la competencia y se clava siempre en tu precio mínimo (Liquidación).
            * 🌾 **3. Cosecha Máximo:** Ignora a la competencia y sube tu precio al tope máximo (Venta cara).
            * 🕵️‍♂️ **4. Analista Histórico:** Se coloca en el precio promedio donde tú lograste vender en el pasado.
            
            **REGLAS HÍBRIDAS (Reacción Automática):**
            * 🦅 **5. Depredador (1+3):** Pelea a muerte bajando centavos (1) peeeero... si el rival se queda sin stock, infla el precio de golpe a tu Máximo (3).
            * 🎯 **6. Francotirador (1+4):** Pelea a muerte bajando centavos (1) peeeero... si el rival se queda sin stock, regresa a tu Precio Histórico seguro (4) para no asustar al cliente.
            * ⏱️ **7. Bomba de Tiempo (2+3):** Clava el precio en el mínimo para asfixiar al rival (2) peeeero... en cuanto el rival se queda en ceros, explota hacia tu Precio Máximo (3).
            * 🧠 **8. Liquidador Sabio (2+4):** Clava el precio en el mínimo por volumen (2) peeeero... si te quedas solo en el listado, regresa a un Precio Histórico moderado (4).
            """)

    else: st.info("Módulo en construcción.")


# ==========================
# NIVEL B: MATRIZ UNIFICADA
# ==========================
elif st.session_state.modo_operativo == "🌐 Matriz Unificada":
    st.title("🌐 Matriz Multiverso (Visión CTO)")
    st.info("Compara en tiempo real la rentabilidad y precios de tu inventario en todos los Marketplaces.")
    
    with st.spinner("Sincronizando universos de datos..."):
        df_hist_lvp = cargar_bitacora_guerra(tienda="LVP")
        df_hist_wmt = cargar_bitacora_guerra(tienda="WMT")
        df_matriz, col_limpio = generar_matriz_unificada(df_base, df_hist_lvp, df_hist_wmt)
        
    m_c1, m_c2, m_c3 = st.columns([3, 1, 1])
    with m_c1: st.text_input("🔍 Buscar SKU/Producto:", key='f_busq_mat')
    with m_c2: 
        st.write("")
        st.button("🧹 Limpiar Búsqueda", on_click=limpiar_filtros_editor, use_container_width=True)
        
    if st.session_state.f_busq_mat:
        df_matriz = df_matriz[df_matriz.astype(str).apply(lambda x: x.str.contains(st.session_state.f_busq_mat, case=False)).any(axis=1)]

    st.dataframe(
        df_matriz,
        use_container_width=True, hide_index=True,
        column_config={
            col_limpio: "SKU Limpio",
            "nombre_odoo": "Producto",
            "stock_actual": "Stock 📦",
            "costo_odoo": st.column_config.NumberColumn("Costo Odoo🏢", format="$%.2f"),
            "precio_lvp": st.column_config.NumberColumn("Precio LVP🟣", format="$%.2f"),
            "margen_lvp": st.column_config.NumberColumn("Margen LVP%", format="%.2f%%"),
            "estatus_lvp": "Estado LVP",
            "precio_wmt": st.column_config.NumberColumn("Precio WMT🔵", format="$%.2f"),
            "margen_wmt": st.column_config.NumberColumn("Margen WMT%", format="%.2f%%"),
            "estatus_wmt": "Estado WMT",
            "recomendacion": "🏆 Recomendación AI"
        }
    )

# ==========================================
# NIVEL C: MEGAZORD AI COPILOT
# ==========================================
elif st.session_state.modo_operativo == "🧠 Megazord AI (Copiloto)":
    
    if st.sidebar.button("➕ Nuevo Chat", type="primary", use_container_width=True):
        st.session_state.sesion_ia_actual = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime("Chat_%Y-%m-%d_%H:%M")
        st.rerun()
        
    st.sidebar.markdown("### 🗂️ Historial")
    df_memoria = cargar_historial_completo_ia()
    if not df_memoria.empty and 'ID_Sesion' in df_memoria.columns:
        sesiones_unicas = df_memoria['ID_Sesion'].unique().tolist()
        for sesion in reversed(sesiones_unicas):
            if st.sidebar.button(f"💬 {sesion}", use_container_width=True, key=f"btn_{sesion}"):
                st.session_state.sesion_ia_actual = str(sesion)
                st.rerun()

    st.title("🧠 Megazord AI Copilot")
    st.caption(f"Sesión: {st.session_state.sesion_ia_actual}")
    
    mensajes_esta_sesion = []
    if not df_memoria.empty and 'ID_Sesion' in df_memoria.columns:
        df_f = df_memoria[df_memoria['ID_Sesion'].astype(str) == str(st.session_state.sesion_ia_actual)]
        for _, row in df_f.iterrows():
            mensajes_esta_sesion.append({"role": str(row['Rol']), "content": str(row['Mensaje'])})
            
    if not mensajes_esta_sesion:
        msg_bienvenida = "¡Hola Kike! Sistemas en línea. Conozco tus costos de Odoo y las reglas financieras de Walmart y Liverpool. ¿En qué te ayudo hoy?"
        mensajes_esta_sesion.append({"role": "assistant", "content": msg_bienvenida})
        guardar_mensaje_ia(st.session_state.sesion_ia_actual, "assistant", msg_bienvenida)
        
    for msg in mensajes_esta_sesion:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    if prompt_usuario := st.chat_input("Escribe tu consulta financiera..."):
        with st.chat_message("user"):
            st.markdown(prompt_usuario)
        guardar_mensaje_ia(st.session_state.sesion_ia_actual, "user", prompt_usuario)
        mensajes_esta_sesion.append({"role": "user", "content": prompt_usuario})
            
        with st.spinner("Analizando datos de la base central..."):
            try:
                import google.generativeai as genai
                genai.configure(api_key=GEMINI_API_KEY)
                modelo_ia = genai.GenerativeModel('gemini-flash-latest')
                
                hist_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in mensajes_esta_sesion[-6:]])
                
                df_hist_lvp = cargar_bitacora_guerra(tienda="LVP")
                df_enriquecido = enriquecer_datos_tienda(df_base, df_hist_lvp, tienda="LVP")
                df_resumen = df_enriquecido[['nombre_odoo', 'estatus', 'stock_actual', 'precio_actual', 'utilidad_%', 'alerta']]

                # 🛡️ VACUNA ANTI-HACKERS (Prompt Injection)
                df_resumen['nombre_odoo'] = df_resumen['nombre_odoo'].apply(lambda x: html.escape(str(x)))

                contexto_datos = f"""
                Eres 'Megazord AI', analista experto de WABU. Tu jefe es Kike.
                
                REGLAS LIVERPOOL: Costo+IVA (1.16), Ingreso Bruto = (Precio*0.83)-130
                REGLAS WALMART: Costo+IVA (1.16), Ingreso Bruto = (Precio*0.85)-76
                IMPUESTOS (Para ambas): 2.5% ISR + 8% IVA sobre (Precio/1.16)
                
                MUESTRA DE INVENTARIO ACTUAL:
                {df_resumen.head(20).to_markdown(index=False)}
                
                HISTORIAL:
                {hist_str}
                
                CONSULTA DE KIKE: {prompt_usuario}
                """
                respuesta = modelo_ia.generate_content(contexto_datos)
                with st.chat_message("assistant"):
                    st.markdown(respuesta.text)
                guardar_mensaje_ia(st.session_state.sesion_ia_actual, "assistant", respuesta.text)
            except Exception as e:
                st.error("Error neuronal: Verifica tu API Key de Gemini.")
