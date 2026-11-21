# ==========================================================
# MEGAZORD War Room v5 — Masivo y Altas (solo Liverpool)
#   1) Mínimos y máximos en masa: reglas sobre SKUs marcados/filtrados, o Excel/CSV
#   2) Alta de SKUs: formulario, Excel/CSV o tabla pegada (con par Full opcional)
#   3) Historial y reversión de cambios masivos
# Todo pasa por: vista previa -> validación -> confirmación -> una sola transacción + auditoría.
# Las escrituras de precios reutilizan guardar_cambios() del Editor Rápido (misma auditoría).
# ==========================================================
import io
import json
import re
import unicodedata
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

import pandas as pd
import streamlit as st
from sqlalchemy import text

from core.odoo import descomponer
from modulos.catalogo_rapido import (
    ESTATUS_VALIDOS, _cargar_catalogo, _guardar_cambios, _validar, utilidad_a_precio,
)

# Misma fórmula del bot: neto = p·(1 − 17 %) − 130 − (p/1.16)·10.5 %  ->  utilidad = neto − costo·1.16
K_NETO = 1 - 0.17 - 0.105 / 1.16
MAX_ALTAS = 300
SALTO_GRANDE_PCT = 30.0     # avisa si un mínimo/máximo se mueve más que esto


def _d(t):
    return str(t).replace("$", "\\$")


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t if t is not None else ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def es_full(sku_interno) -> bool:
    return str(sku_interno or "").strip().upper().endswith("-FBL")


def canal(sku_interno) -> str:
    return "Full" if es_full(sku_interno) else "Almacén"


# ---------------------------------------------------------- cálculo
def precio_por_utilidad(costo: float, utilidad: float):
    """Precio al que una pieza deja exactamente `utilidad` pesos (inversa de utilidad_a_precio)."""
    if not costo or costo <= 0:
        return None
    return (utilidad + 130.0 + 1.16 * costo) / K_NETO


def estilo_min(v: float) -> float:
    """Mínimo estilo WABU: hacia arriba, terminando en .01 (1131.004 -> 1131.01)."""
    d = Decimal(str(round(v, 2)))
    return float((d - Decimal("0.01")).to_integral_value(rounding=ROUND_CEILING) + Decimal("0.01"))


def estilo_max(v: float) -> float:
    """Máximo estilo WABU: hacia abajo, terminando en .99 (1599.00 -> 1598.99)."""
    d = Decimal(str(round(v, 2)))
    return float((d + Decimal("0.01")).to_integral_value(rounding=ROUND_FLOOR) - Decimal("0.01"))


OPS_MIN = {
    "sin": "Sin cambio",
    "pct": "Subir / bajar %",
    "suma": "Sumar / restar $",
    "fijo": "Fijar en $",
    "util": "Por utilidad objetivo ($ por pieza)",
    "costo": "Costo × factor",
}
OPS_MAX = {
    "sin": "Sin cambio",
    "pct": "Subir / bajar %",
    "suma": "Sumar / restar $",
    "fijo": "Fijar en $",
    "min": "Mínimo nuevo × factor",
    "costo": "Costo × factor",
}


def _aplicar(op, x, actual, costo, nuevo_min=None):
    if op == "sin":
        return actual
    if op == "pct":
        return actual * (1 + x / 100.0)
    if op == "suma":
        return actual + x
    if op == "fijo":
        return x
    if op == "util":
        return precio_por_utilidad(costo, x)
    if op == "costo":
        return costo * x if costo and costo > 0 else None
    if op == "min":
        return nuevo_min * x if nuevo_min else None
    return actual


def _cambio(r, nmin, nmax):
    """Estructura compatible con guardar_cambios() del Editor Rápido (estatus y regla no cambian)."""
    base = {"estatus": str(r["estatus"]), "regla": str(r["regla"])}
    antes = {**base, "precio_minimo": round(float(r["precio_minimo"]), 2), "precio_maximo": round(float(r["precio_maximo"]), 2)}
    despues = {**base, "precio_minimo": round(float(nmin), 2), "precio_maximo": round(float(nmax), 2)}
    if antes == despues:
        return None
    return {"id": int(r["id"]), "sku": f"{r['sku_limpio']} ({canal(r['sku_interno'])})", "canal": canal(r["sku_interno"]),
            "costo": float(r["costo_odoo"]), "antes": antes, "despues": despues}


def calcular_masivo(objetivo: pd.DataFrame, op_min, x_min, op_max, x_max, estilo: bool):
    """Devuelve (cambios, omitidos). Un SKU se omite si la regla no se puede calcular (p. ej. sin costo)."""
    cambios, omitidos = [], []
    for r in objetivo.to_dict("records"):
        actual_min, actual_max, costo = float(r["precio_minimo"]), float(r["precio_maximo"]), float(r["costo_odoo"])
        nmin = _aplicar(op_min, x_min, actual_min, costo)
        if nmin is None:
            omitidos.append(f"{r['sku_limpio']} ({canal(r['sku_interno'])}): sin costo en Odoo, no se puede calcular el mínimo")
            continue
        if op_min != "sin":
            nmin = estilo_min(nmin) if estilo else round(nmin, 2)
        nmax = _aplicar(op_max, x_max, actual_max, costo, nuevo_min=nmin)
        if nmax is None:
            omitidos.append(f"{r['sku_limpio']} ({canal(r['sku_interno'])}): no se puede calcular el máximo")
            continue
        if op_max != "sin":
            nmax = estilo_max(nmax) if estilo else round(nmax, 2)
        c = _cambio(r, max(nmin, 0.0), max(nmax, 0.0))
        if c:
            cambios.append(c)
    return cambios, omitidos


# ---------------------------------------------------------- lectura de Excel / CSV
ALIAS = {
    "id": "id",
    "sku_interno": "sku_interno", "sku_sucio": "sku_interno",
    "sku_liverpool": "sku_liverpool", "sku_oferta": "sku_liverpool", "sku_de_la_oferta": "sku_liverpool",
    "sku_limpio": "sku_limpio", "sku": "sku_limpio",
    "id_cuenta": "id_cuenta", "cuenta": "id_cuenta",
    "precio_minimo": "precio_minimo", "minimo": "precio_minimo", "min": "precio_minimo",
    "precio_maximo": "precio_maximo", "maximo": "precio_maximo", "max": "precio_maximo",
    "costo_odoo": "costo_odoo", "costo": "costo_odoo",
    "regla_estrategia": "regla_estrategia", "regla": "regla_estrategia",
    "estatus": "estatus",
    "sku_liverpool_product_id": "sku_liverpool_product_id", "product_id": "sku_liverpool_product_id", "id_producto": "sku_liverpool_product_id",
    "crear_full": "crear_full", "full": "crear_full", "crear_par_full": "crear_full",
}


def leer_archivo(archivo) -> pd.DataFrame:
    """Lee .xlsx/.xls/.csv TODO como texto (los SKU no deben perder ceros ni volverse notación científica)."""
    nombre = (archivo.name or "").lower()
    if nombre.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(archivo, dtype=str)
    else:
        crudo = archivo.getvalue()
        try:
            txt = crudo.decode("utf-8-sig")
        except UnicodeDecodeError:
            txt = crudo.decode("latin-1")
        df = pd.read_csv(io.StringIO(txt), dtype=str, sep=None, engine="python")
    df.columns = [ALIAS.get(re.sub(r"\s+", "_", _norm(c)), re.sub(r"\s+", "_", _norm(c))) for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    return df.dropna(how="all")


def _num(v):
    """'$1,234.50' -> 1234.5 ; vacío -> None ; basura -> ValueError."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not pd.isna(v):
        return float(v)
    s = str(v).strip().replace("$", "").replace(",", "").replace(" ", "")
    if s == "" or s.lower() in ("nan", "none", "nat"):
        return None
    return float(s)


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s.lower() in ("nan", "none", "nat"):
        return ""
    if re.fullmatch(r"\d+\.0", s):          # 1190647591.0 por culpa de Excel
        s = s[:-2]
    return s


def cambios_desde_archivo(df: pd.DataFrame, catalogo: pd.DataFrame, aplicar_a_todas: bool):
    """Cruza el archivo con el catálogo. Devuelve (cambios, errores, avisos)."""
    errores, avisos, cambios = [], [], []
    if "precio_minimo" not in df.columns and "precio_maximo" not in df.columns:
        return [], ["El archivo necesita al menos una columna de mínimo o máximo (precio_minimo / precio_maximo)."], []
    if not any(c in df.columns for c in ("id", "sku_interno", "sku_liverpool", "sku_limpio")):
        return [], ["El archivo necesita una columna para identificar el SKU: id, sku_interno, sku_liverpool o sku_limpio."], []

    cat = catalogo.copy()
    cat["_i"] = cat["sku_interno"].astype(str).str.strip().str.upper()
    cat["_l"] = cat["sku_liverpool"].astype(str).str.strip()
    cat["_c"] = cat["sku_limpio"].astype(str).str.strip().str.upper()
    cat["_cu"] = cat["id_cuenta"].astype(str).str.strip().str.upper()
    por_id = cat.set_index("id", drop=False)
    vistos = set()

    for n, fila in enumerate(df.to_dict("records"), start=2):      # fila 1 = encabezados
        et = f"Fila {n}"
        try:
            nmin, nmax = _num(fila.get("precio_minimo")), _num(fila.get("precio_maximo"))
        except ValueError:
            errores.append(f"{et}: mínimo o máximo no es un número")
            continue
        if nmin is None and nmax is None:
            continue
        ident = _txt(fila.get("id"))
        coinc = None
        if ident:
            try:
                coinc = por_id.loc[[int(float(ident))]]
            except (KeyError, ValueError):
                errores.append(f"{et}: el id {ident} no existe en el catálogo")
                continue
        else:
            cu = _txt(fila.get("id_cuenta")).upper()
            for col, key in (("_i", "sku_interno"), ("_l", "sku_liverpool"), ("_c", "sku_limpio")):
                val = _txt(fila.get(key))
                if not val:
                    continue
                val = val.upper() if col != "_l" else val
                m = cat[cat[col] == val]
                if cu:
                    m = m[m["_cu"] == cu]
                coinc = m
                break
            if coinc is None or coinc.empty:
                errores.append(f"{et}: no encontré ese SKU en el catálogo")
                continue
            if len(coinc) > 1 and not aplicar_a_todas:
                lista = ", ".join(f"{r.sku_interno} (id {r.id})" for r in coinc.itertuples())
                errores.append(f"{et}: coincide con varias filas ({lista}). Usa la columna id o sku_interno, o activa «aplicar a todas las coincidencias».")
                continue
        for r in coinc.to_dict("records"):
            if r["id"] in vistos:
                errores.append(f"{et}: el SKU {r['sku_interno']} (id {r['id']}) aparece más de una vez en el archivo")
                continue
            vistos.add(r["id"])
            c = _cambio(r, nmin if nmin is not None else r["precio_minimo"], nmax if nmax is not None else r["precio_maximo"])
            if c:
                cambios.append(c)
    return cambios, errores, avisos


# ---------------------------------------------------------- vista previa y guardado
def _ver(nombre):
    """Número de versión para las llaves de confirmación: al subirlo, la casilla vuelve a quedar sin marcar."""
    return st.session_state.get(f"_v_{nombre}", 0)


def _subir_ver(nombre):
    st.session_state[f"_v_{nombre}"] = _ver(nombre) + 1


def _salto_pct(a, b):
    a, b = float(a), float(b)
    return abs(b - a) / a * 100.0 if a > 0 else (100.0 if b > 0 else 0.0)


def _tabla_vista_previa(cambios):
    def f(a, b):
        return "—" if a == b else f"${a:,.2f} → ${b:,.2f}"
    filas = []
    for c in cambios:
        u = utilidad_a_precio(c["despues"]["precio_minimo"], c.get("costo", 0))
        filas.append({"SKU": c["sku"], "Estatus": c["despues"]["estatus"],
                      "Mínimo": f(c["antes"]["precio_minimo"], c["despues"]["precio_minimo"]),
                      "Máximo": f(c["antes"]["precio_maximo"], c["despues"]["precio_maximo"]),
                      "Utilidad al mínimo nuevo": None if u is None else round(u, 2)})
    return pd.DataFrame(filas)


def _revisar_y_guardar(db, cambios, usuario, clave, omitidos=(), errores_previos=(), avisos_previos=()):
    """Vista previa + validación + confirmación + guardado. Nada se escribe sin la casilla de confirmación."""
    for e in errores_previos:
        st.error(_d(e))
    for a in avisos_previos:
        st.warning(_d(a))
    if omitidos:
        with st.expander(f"⚠️ {len(omitidos)} SKU(s) omitidos (no se tocan)"):
            for o in omitidos:
                st.write(_d(o))
    if not cambios:
        st.info("No hay cambios que aplicar con esta configuración.")
        return

    errores, avisos = _validar(cambios)
    for c in cambios:
        for nombre, k in (("mínimo", "precio_minimo"), ("máximo", "precio_maximo")):
            s = _salto_pct(c["antes"][k], c["despues"][k])
            if s >= SALTO_GRANDE_PCT and c["antes"][k] > 0:
                avisos.append(f"{c['sku']}: el {nombre} se mueve {s:.0f} % (${c['antes'][k]:,.2f} → ${c['despues'][k]:,.2f})")
    activos = sum(1 for c in cambios if c["despues"]["estatus"] == "ACTIVO")
    r9 = sum(1 for c in cambios if str(c["despues"]["regla"]).startswith("9"))

    st.markdown(f"#### 📝 {len(cambios)} cambio(s) listos para revisar")
    st.dataframe(_tabla_vista_previa(cambios), hide_index=True, width="stretch", height=min(420, 60 + 35 * len(cambios)),
                 column_config={"Utilidad al mínimo nuevo": st.column_config.NumberColumn(format="dollar")})
    for e in errores:
        st.error(_d(e))
    with st.expander(f"⚠️ {len(avisos)} aviso(s)", expanded=bool(avisos) and len(avisos) <= 8) if avisos else st.container():
        for a in avisos:
            st.warning(_d(a))
    if r9:
        st.info(f"🎲 {r9} de estos SKUs usan la Regla 9: su mínimo es el piso real de la ruleta.")

    ok = st.checkbox(f"Confirmo aplicar {len(cambios)} cambio(s). {activos} están en SKUs ACTIVOS: el bot usará los nuevos precios desde el siguiente barrido (~12 min).",
                     key=f"ms_ok_{clave}_{_ver(clave)}")
    if st.button(f"💾 Aplicar {len(cambios)} cambio(s)", type="primary", disabled=bool(errores) or not ok, key=f"ms_go_{clave}_{_ver(clave)}"):
        good, msg = _guardar_cambios(db, cambios, usuario + " (MASIVO)")
        if good:
            st.cache_data.clear()
            _subir_ver(clave)
            st.toast(f"✅ {msg}")
            st.rerun()
        else:
            st.error(msg)


# ---------------------------------------------------------- 1) mínimos y máximos en masa
def _filtros(base: pd.DataFrame, reglas: list, pref: str) -> pd.DataFrame:
    f1, f2, f3, f4 = st.columns([2, 1, 1, 2])
    q = f1.text_input("🔎 Buscar", key=f"{pref}_q", placeholder="SKU limpio, sucio, Liverpool o varias palabras").strip()
    vista = f2.radio("Ver", ["Activos", "Inactivos", "Todos"], key=f"{pref}_vista", horizontal=False)
    cn = f3.radio("Canal", ["Todos", "Almacén", "Full"], key=f"{pref}_canal", horizontal=False)
    reglas_sel = f4.multiselect("Regla", reglas, key=f"{pref}_reglas", placeholder="Todas")
    vis = base.copy()
    vis["canal"] = vis["sku_interno"].map(canal)
    if vista == "Activos":
        vis = vis[vis.estatus == "ACTIVO"]
    elif vista == "Inactivos":
        vis = vis[vis.estatus != "ACTIVO"]
    if cn != "Todos":
        vis = vis[vis.canal == cn]
    if reglas_sel:
        vis = vis[vis.regla.isin(reglas_sel)]
    terminos = [_norm(t) for t in q.split() if t.strip()]
    if terminos:
        pajar = (vis.sku_limpio.map(_norm) + " " + vis.sku_interno.map(_norm) + " " + vis.sku_liverpool.map(_norm))
        vis = vis[pajar.map(lambda t: all(x in t for x in terminos))]
    return vis.reset_index(drop=True)


def _excel_bytes(df: pd.DataFrame, hoja="Hoja1") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=hoja)
    return buf.getvalue()


def _tab_minmax(db, base, reglas, usuario):
    st.caption("Solo Liverpool: se cambian `precio_minimo` y `precio_maximo`. Walmart y Coppel no se tocan. Nada se guarda hasta que revises y confirmes.")
    modo = st.radio("¿Cómo quieres cambiarlos?", ["🧮 Con reglas (sobre SKUs marcados o filtrados)", "📄 Con un Excel / CSV"], key="ms_modo", horizontal=True)
    vis = _filtros(base, reglas, "ms")

    if modo.startswith("🧮"):
        st.caption(f"{len(vis)} SKUs con este filtro.")
        grid = vis[["sku_limpio", "canal", "estatus", "regla", "precio_minimo", "precio_maximo", "costo_odoo", "sku_interno", "sku_liverpool", "id"]].copy()
        grid.insert(0, "sel", False)
        firma = abs(hash((len(vis), tuple(vis["id"].head(30)), st.session_state.get("ms_q", ""), st.session_state.get("ms_vista", "")))) % 10**8
        ed = st.data_editor(
            grid, key=f"ms_grid_{firma}", hide_index=True, width="stretch", height=340,
            disabled=[c for c in grid.columns if c != "sel"],
            column_config={"sel": st.column_config.CheckboxColumn("☑", width="small"),
                           "sku_limpio": st.column_config.TextColumn("SKU", width="medium"),
                           "precio_minimo": st.column_config.NumberColumn("Mínimo", format="dollar"),
                           "precio_maximo": st.column_config.NumberColumn("Máximo", format="dollar"),
                           "costo_odoo": st.column_config.NumberColumn("Costo", format="dollar"),
                           "id": None})
        marcados = ed[ed["sel"]]
        alcance = st.radio("Aplicar a", [f"Solo los marcados ({len(marcados)})", f"Todos los filtrados ({len(vis)})"], key="ms_alcance", horizontal=True)
        objetivo = vis[vis["id"].isin(marcados["id"])] if alcance.startswith("Solo") else vis

        st.markdown("**Qué cambiar**")
        c1, c2 = st.columns(2)
        with c1:
            op_min = st.selectbox("Mínimo", list(OPS_MIN), format_func=OPS_MIN.get, key="ms_op_min")
            x_min = _valor_op(op_min, "ms_x_min", es_min=True)
        with c2:
            op_max = st.selectbox("Máximo", list(OPS_MAX), format_func=OPS_MAX.get, key="ms_op_max")
            x_max = _valor_op(op_max, "ms_x_max", es_min=False)
        estilo = st.toggle("Redondeo estilo WABU (mínimo termina en .01 hacia arriba, máximo en .99 hacia abajo)", value=True, key="ms_estilo")

        if objetivo.empty:
            st.info("Marca SKUs en la tabla (o elige «Todos los filtrados») para empezar.")
            return
        if op_min == "sin" and op_max == "sin":
            st.info("Elige qué quieres hacer con el mínimo, el máximo o ambos.")
            return
        cambios, omitidos = calcular_masivo(objetivo, op_min, x_min, op_max, x_max, estilo)
        _revisar_y_guardar(db, cambios, usuario, "reglas", omitidos=omitidos)
        return

    # ---- Excel / CSV
    st.markdown("**1 · Descarga la plantilla** con los SKUs del filtro de arriba, cambia los mínimos y máximos en Excel y súbela.")
    plantilla = vis[["id", "sku_limpio", "sku_interno", "sku_liverpool", "id_cuenta", "estatus", "regla", "costo_odoo", "precio_minimo", "precio_maximo"]]
    st.download_button(f"⬇️ Plantilla con {len(plantilla)} SKUs (Excel)", data=_excel_bytes(plantilla, "minimos_maximos"),
                       file_name="plantilla_minimos_maximos.xlsx", disabled=plantilla.empty,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="ms_dl_plantilla")
    st.caption("Solo se leen las columnas de mínimo y máximo (y se identifica el SKU por `id`, `sku_interno`, `sku_liverpool` o `sku_limpio`). Una celda vacía = no cambiar.")
    todas = st.checkbox("Si un SKU Liverpool / limpio coincide con varias filas (Full y Almacén), aplicar a todas las coincidencias", key="ms_todas")
    st.markdown("**2 · Sube el archivo**")
    arch = st.file_uploader("Excel (.xlsx) o CSV", type=["xlsx", "xls", "csv"], key="ms_archivo")
    if not arch:
        return
    try:
        df = leer_archivo(arch)
    except Exception as e:  # noqa: BLE001
        st.error(f"No pude leer el archivo: {str(e)[:160]}")
        return
    st.caption(f"{len(df)} filas leídas · columnas: {', '.join(map(str, df.columns))}")
    cambios, errores, avisos = cambios_desde_archivo(df, base, todas)
    _revisar_y_guardar(db, cambios, usuario, "archivo", errores_previos=errores, avisos_previos=avisos)


def _valor_op(op, key, es_min):
    if op == "sin":
        return 0.0
    if op == "pct":
        return st.number_input("Porcentaje (negativo = bajar)", value=5.0, step=1.0, format="%.1f", key=key)
    if op == "suma":
        return st.number_input("Pesos (negativo = restar)", value=10.0, step=1.0, format="%.2f", key=key)
    if op == "fijo":
        return st.number_input("Valor en $", value=0.0, min_value=0.0, step=1.0, format="%.2f", key=key)
    if op == "util":
        return st.number_input("Utilidad por pieza al mínimo ($)", value=100.0, step=10.0, format="%.2f", key=key,
                               help="Calcula el precio con la misma fórmula del bot (comisión, envío y retenciones). Requiere costo en Odoo.")
    if op == "costo":
        return st.number_input("Factor sobre el costo (p. ej. 1.9)", value=2.0 if es_min else 4.0, min_value=0.1, step=0.1, format="%.2f", key=key)
    if op == "min":
        return st.number_input("Factor sobre el mínimo nuevo (p. ej. 1.6)", value=1.6, min_value=1.0, step=0.1, format="%.2f", key=key)
    return 0.0


# ---------------------------------------------------------- 2) alta de SKUs
@st.cache_data(ttl=300, show_spinner=False)
def _costos_odoo(_db) -> dict:
    df = _db.execute_query("SELECT default_code, costo FROM odoo_productos", silencioso=True)
    if df is None or df.empty:
        return {}
    return {str(c).strip().upper(): float(v or 0) for c, v in zip(df.default_code, df.costo)}


@st.cache_data(ttl=120, show_spinner=False)
def _cuentas_activas(_db) -> pd.DataFrame:
    return _db.execute_query("SELECT id_cuenta, nombre_descriptivo FROM cuentas_liverpool WHERE is_active = TRUE ORDER BY id_cuenta", silencioso=True)


def costo_desde_odoo(sku_limpio: str, costos: dict):
    """Simple = costo · paquete 'A/2' = 2×costo · combo 'A/B' = suma. Devuelve (costo, códigos que no están en Odoo)."""
    tipo, items = descomponer(sku_limpio)
    if not items or not costos:
        return 0.0, [c for c, _ in items] or [sku_limpio]
    faltan = [c for c, _ in items if c not in costos]
    if faltan:
        return 0.0, faltan
    return round(sum(costos[c] * n for c, n in items), 2), []


def sku_limpio_desde_interno(sku_interno: str) -> str:
    s = str(sku_interno or "").strip()
    s = re.sub(r"-FBL$", "", s, flags=re.I)
    return s.upper()


_TRUE = {"1", "si", "sí", "true", "x", "yes", "verdadero", "s"}


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return _norm(v) in {_norm(t) for t in _TRUE}


def preparar_altas(df: pd.DataFrame, catalogo: pd.DataFrame, costos: dict, cuentas: list, reglas: list,
                   cuenta_def: str, estatus_def: str, regla_def: str, estatus_full: str):
    """Valida y normaliza. Devuelve (registros, errores, avisos). Un solo error bloquea todo el lote."""
    registros, errores, avisos = [], [], []
    cat = catalogo
    existentes = {(str(r.id_cuenta).strip().upper(), str(r.sku_interno).strip().upper()) for r in cat.itertuples()}
    por_lp = {}
    for r in cat.itertuples():
        por_lp.setdefault(str(r.sku_liverpool).strip(), []).append((str(r.sku_interno), str(r.estatus), str(r.id_cuenta)))
    vistos = set()

    def validar_y_agregar(et, reg):
        sku = reg["sku_interno"]
        clave = (reg["id_cuenta"].upper(), sku.upper())
        nerr = len(errores)
        if clave in existentes:
            errores.append(f"{et}: ya existe {sku} en la cuenta {reg['id_cuenta']}")
        if clave in vistos:
            errores.append(f"{et}: {sku} está repetido en esta carga")
        if len(sku) > 50 or not re.fullmatch(r"[A-Za-z0-9._/\-]+", sku):
            errores.append(f"{et}: sku_interno «{sku}» inválido (solo letras, números y . _ / -, máximo 50)")
        if not re.fullmatch(r"\d{6,12}", reg["sku_liverpool"]):
            errores.append(f"{et}: sku_liverpool «{reg['sku_liverpool']}» debe ser solo números (6 a 12 dígitos)")
        if reg["sku_liverpool_product_id"] and not re.fullmatch(r"\d{1,50}", reg["sku_liverpool_product_id"]):
            errores.append(f"{et}: el product id debe ser solo números")
        if len(reg["sku_limpio"]) > 50 or not reg["sku_limpio"]:
            errores.append(f"{et}: sku_limpio vacío o de más de 50 caracteres")
        if reg["id_cuenta"] not in cuentas:
            errores.append(f"{et}: la cuenta {reg['id_cuenta']} no está activa")
        if reg["regla_estrategia"] not in reglas:
            errores.append(f"{et}: regla «{reg['regla_estrategia']}» no válida")
        if reg["estatus"] not in ESTATUS_VALIDOS:
            errores.append(f"{et}: estatus «{reg['estatus']}» no válido")
        pmin, pmax, costo = reg["precio_minimo"], reg["precio_maximo"], reg["costo_odoo"]
        if pmin < 0 or pmax < 0 or costo < 0:
            errores.append(f"{et}: no puede haber precios ni costos negativos")
        if pmin > 0 and pmax > 0 and pmin >= pmax:
            errores.append(f"{et}: el mínimo (${pmin:,.2f}) debe ser menor que el máximo (${pmax:,.2f})")
        if reg["estatus"] == "ACTIVO":
            if pmin <= 0 or pmax <= 0:
                errores.append(f"{et}: no se puede dar de alta como ACTIVO sin mínimo y máximo. Usa INACTIVO y actívalo después.")
            if costo <= 0:
                errores.append(f"{et}: no se puede dar de alta como ACTIVO sin costo (no se podría cuidar el margen). Usa INACTIVO hasta que exista en Odoo.")
        if costo > 0 and pmin > 0:
            u = utilidad_a_precio(pmin, costo)
            if u is not None and u < 0:
                avisos.append(f"{et}: al mínimo (${pmin:,.2f}) pierdes ${abs(u):,.2f} por pieza")
        otros = por_lp.get(reg["sku_liverpool"], [])
        if otros:
            lista = ", ".join(f"{s} ({e})" for s, e, _c in otros)
            if (reg["canal"] == "Full") != all(es_full(s) for s, _e, _c in otros) or any(es_full(s) != es_full(sku) for s, _e, _c in otros):
                avisos.append(f"{et}: el sku_liverpool {reg['sku_liverpool']} ya existe como {lista}. Full y Almacén comparten publicación: el bot reprecia primero Full y luego Almacén.")
            else:
                avisos.append(f"{et}: el sku_liverpool {reg['sku_liverpool']} ya existe como {lista}. ¿Seguro que no es un duplicado?")
        if es_full(sku) and sku.upper() != f"{reg['sku_liverpool']}-FBL":
            avisos.append(f"{et}: los Full del catálogo se llaman «sku_liverpool-FBL» (aquí sería {reg['sku_liverpool']}-FBL).")
        if reg["regla_estrategia"].startswith("9") and reg["estatus"] == "ACTIVO":
            avisos.append(f"{et}: Regla 9 activa desde el alta; verifica que el mínimo sea un piso con el que aceptes vender.")
        if len(errores) == nerr:
            vistos.add(clave)
            registros.append(reg)

    n_filas = 0
    for i, f in enumerate(df.to_dict("records"), start=1):
        crudo = {k: _txt(v) for k, v in f.items() if k != "crear_full"}
        if not any(crudo.values()):
            continue
        n_filas += 1
        et = f"Fila {i}"
        sku_i = _txt(f.get("sku_interno"))
        sku_lp = _txt(f.get("sku_liverpool"))
        if not sku_i:
            errores.append(f"{et}: falta sku_interno")
            continue
        if not sku_lp:
            errores.append(f"{et} ({sku_i}): falta sku_liverpool")
            continue
        try:
            pmin, pmax, costo_in = _num(f.get("precio_minimo")), _num(f.get("precio_maximo")), _num(f.get("costo_odoo"))
        except ValueError:
            errores.append(f"{et} ({sku_i}): mínimo, máximo o costo no es un número")
            continue
        limpio = (_txt(f.get("sku_limpio")) or sku_limpio_desde_interno(sku_i)).upper()
        if costo_in and costo_in > 0:
            costo = round(costo_in, 2)
        else:
            costo, faltan = costo_desde_odoo(limpio, costos)
            if faltan:
                avisos.append(f"{et} ({sku_i}): {', '.join(faltan)} no está en Odoo (costo 0; no se podrá activar hasta que exista)")
        reg = {"sku_interno": sku_i, "sku_liverpool": sku_lp, "sku_limpio": limpio,
               "sku_liverpool_product_id": _txt(f.get("sku_liverpool_product_id")) or None,
               "id_cuenta": (_txt(f.get("id_cuenta")) or cuenta_def).upper() if _txt(f.get("id_cuenta")) else cuenta_def,
               "precio_minimo": round(pmin or 0.0, 2), "precio_maximo": round(pmax or 0.0, 2), "costo_odoo": costo,
               "estatus": (_txt(f.get("estatus")) or estatus_def).upper(),
               "regla_estrategia": _txt(f.get("regla_estrategia")) or regla_def,
               "canal": canal(sku_i)}
        validar_y_agregar(f"{et} ({sku_i})", reg)
        if _bool(f.get("crear_full")) and not es_full(sku_i):
            full = {**reg, "sku_interno": f"{sku_lp}-FBL", "estatus": estatus_full, "canal": "Full"}
            validar_y_agregar(f"{et} ({sku_i}) · par Full", full)
    if n_filas == 0:
        errores.append("No hay filas para dar de alta.")
    if n_filas > MAX_ALTAS:
        errores.append(f"Máximo {MAX_ALTAS} filas por carga (hay {n_filas}).")
    return registros, errores, avisos


def _insertar_altas(db, registros: list, usuario: str):
    if db.engine is None:
        return False, "Sin conexión a la base de datos"
    try:
        with db.engine.begin() as conn:
            # El contador de ids (serial) puede quedar atrasado si hubo cargas directas desde DBeaver:
            # lo alineamos con el id más alto antes de insertar.
            conn.execute(text("SELECT setval(pg_get_serial_sequence('catalogo_maestro_v3','id'), "
                              "GREATEST((SELECT COALESCE(MAX(id),0) FROM catalogo_maestro_v3), 1))"))
            for r in registros:
                dup = conn.execute(text("SELECT 1 FROM catalogo_maestro_v3 WHERE id_cuenta = :c AND UPPER(sku_interno) = UPPER(:s) LIMIT 1"),
                                   {"c": r["id_cuenta"], "s": r["sku_interno"]}).first()
                if dup:
                    raise ValueError(f"{r['sku_interno']} ya existe en {r['id_cuenta']} (alguien lo dio de alta mientras revisabas)")
                conn.execute(text("""INSERT INTO catalogo_maestro_v3
                                     (sku_interno, sku_liverpool, sku_limpio, sku_liverpool_product_id, id_cuenta,
                                      precio_minimo, precio_maximo, costo_odoo, estatus, regla_estrategia, stock)
                                     VALUES (:sku_interno, :sku_liverpool, :sku_limpio, :sku_liverpool_product_id, :id_cuenta,
                                             :precio_minimo, :precio_maximo, :costo_odoo, :estatus, :regla_estrategia, 0)"""), r)
            conn.execute(text("INSERT INTO logs_auditoria (usuario, accion, detalles) VALUES (:u, :a, :d)"),
                         {"u": usuario, "a": f"ALTA_SKU ({len(registros)} filas)", "d": json.dumps(registros, default=str, ensure_ascii=False)})
        return True, f"{len(registros)} fila(s) dadas de alta"
    except Exception as e:  # noqa: BLE001
        return False, f"No se guardó nada: {str(e)[:200]}"


PLANTILLA_ALTA = ["sku_interno", "sku_liverpool", "sku_limpio", "sku_liverpool_product_id", "precio_minimo", "precio_maximo",
                  "costo_odoo", "regla_estrategia", "estatus", "id_cuenta", "crear_full"]


def _tab_altas(db, base, reglas, usuario):
    cuentas_df = _cuentas_activas(db)
    if cuentas_df is None or cuentas_df.empty:
        st.error("No encontré cuentas Liverpool activas.")
        return
    cuentas = list(cuentas_df.id_cuenta)
    costos = _costos_odoo(db)
    st.caption("Por seguridad, lo nuevo entra como **INACTIVO** a menos que elijas lo contrario. El costo se completa solo desde Odoo (paquetes y combos suman sus partes).")

    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    cuenta = c1.selectbox("Cuenta", cuentas, key="ms_a_cuenta")
    regla = c2.selectbox("Regla", reglas, key="ms_a_regla")
    estatus = c3.radio("Estatus al crear", ESTATUS_VALIDOS[::-1], key="ms_a_estatus", horizontal=True)
    estatus_full = c4.radio("Si creas el par Full", ESTATUS_VALIDOS[::-1], key="ms_a_estatus_full", horizontal=True)

    modo = st.radio("¿Cómo los das de alta?", ["✍️ Uno (formulario)", "📄 Varios (Excel / CSV)", "📋 Varios (pegar tabla)"], key="ms_a_modo", horizontal=True)
    df = None
    if modo.startswith("✍️"):
        a1, a2, a3 = st.columns(3)
        sku_i = a1.text_input("SKU interno *", key="ms_a_si", placeholder="p. ej. HNAU").strip()
        sku_lp = a2.text_input("SKU Liverpool (oferta) *", key="ms_a_slp", placeholder="solo números").strip()
        pid = a3.text_input("Product ID (opcional)", key="ms_a_pid", help="Solo si la página de ofertas usa un productId distinto al SKU.").strip()
        b1, b2, b3 = st.columns(3)
        limpio = b1.text_input("SKU limpio", key="ms_a_sl", placeholder="vacío = igual al interno (sin -FBL)").strip()
        pmin = b2.number_input("Mínimo", min_value=0.0, step=1.0, format="%.2f", key="ms_a_min")
        pmax = b3.number_input("Máximo", min_value=0.0, step=1.0, format="%.2f", key="ms_a_max")
        costo = st.number_input("Costo (0 = tomarlo de Odoo)", min_value=0.0, step=1.0, format="%.2f", key="ms_a_costo")
        full = st.checkbox("Crear también su fila Full (-FBL) con la misma publicación", key="ms_a_full")
        lim = (limpio or sku_limpio_desde_interno(sku_i)).upper()
        if lim:
            auto, faltan = costo_desde_odoo(lim, costos)
            if costo <= 0:
                st.caption(_d(f"Costo desde Odoo para {lim}: ${auto:,.2f}" if not faltan else f"⚠️ {', '.join(faltan)} no está en Odoo"))
        df = pd.DataFrame([{"sku_interno": sku_i, "sku_liverpool": sku_lp, "sku_limpio": limpio, "sku_liverpool_product_id": pid,
                            "precio_minimo": pmin, "precio_maximo": pmax, "costo_odoo": costo, "crear_full": full}])
    elif modo.startswith("📄"):
        st.download_button("⬇️ Plantilla de altas (Excel)", data=_excel_bytes(pd.DataFrame(columns=PLANTILLA_ALTA), "altas"),
                           file_name="plantilla_altas_liverpool.xlsx", key="ms_a_dl",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("Obligatorias: `sku_interno` y `sku_liverpool`. Las demás son opcionales (`crear_full`: sí/no). Lo que dejes vacío toma los valores de arriba.")
        arch = st.file_uploader("Excel (.xlsx) o CSV", type=["xlsx", "xls", "csv"], key="ms_a_archivo")
        if arch:
            try:
                df = leer_archivo(arch)
            except Exception as e:  # noqa: BLE001
                st.error(f"No pude leer el archivo: {str(e)[:160]}")
                return
            st.caption(f"{len(df)} filas leídas · columnas: {', '.join(map(str, df.columns))}")
    else:
        st.caption("Pega desde Excel directo en la tabla (Ctrl+V) con estas columnas, o escribe fila por fila.")
        vacio = pd.DataFrame({"sku_interno": pd.Series([""] * 5, dtype="object"), "sku_liverpool": pd.Series([""] * 5, dtype="object"),
                              "sku_limpio": pd.Series([""] * 5, dtype="object"), "precio_minimo": pd.Series([None] * 5, dtype="float64"),
                              "precio_maximo": pd.Series([None] * 5, dtype="float64"), "crear_full": pd.Series([False] * 5, dtype="bool")})
        df = st.data_editor(vacio, num_rows="dynamic", hide_index=True, width="stretch", key="ms_a_grid",
                            column_config={"precio_minimo": st.column_config.NumberColumn("Mínimo", format="dollar", min_value=0.0),
                                           "precio_maximo": st.column_config.NumberColumn("Máximo", format="dollar", min_value=0.0),
                                           "crear_full": st.column_config.CheckboxColumn("¿Par Full?")})
    if df is None or df.empty:
        return

    registros, errores, avisos = preparar_altas(df, base, costos, cuentas, reglas, cuenta, estatus, regla, estatus_full)
    for e in errores:
        st.error(_d(e))
    for a in avisos:
        st.warning(_d(a))
    if not registros:
        return
    st.markdown(f"#### 📝 {len(registros)} fila(s) listas para dar de alta")
    vista = pd.DataFrame([{"SKU interno": r["sku_interno"], "Canal": r["canal"], "SKU limpio": r["sku_limpio"], "SKU Liverpool": r["sku_liverpool"],
                           "Cuenta": r["id_cuenta"], "Estatus": r["estatus"], "Regla": r["regla_estrategia"], "Mínimo": r["precio_minimo"],
                           "Máximo": r["precio_maximo"], "Costo": r["costo_odoo"]} for r in registros])
    st.dataframe(vista, hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="dollar") for k in ("Mínimo", "Máximo", "Costo")})
    act = sum(1 for r in registros if r["estatus"] == "ACTIVO")
    ok = st.checkbox(f"Confirmo dar de alta {len(registros)} fila(s)" + (f" ({act} ACTIVAS: el bot las reprecia desde el siguiente barrido)." if act else " (todas INACTIVAS: no se reprecian hasta que las actives)."), key=f"ms_a_ok_{_ver('alta')}")
    if errores:
        st.info("Hay errores arriba: corrige esas filas o quítalas; mientras haya errores no se da de alta nada.")
    if st.button(f"➕ Dar de alta {len(registros)} fila(s)", type="primary", disabled=bool(errores) or not ok, key="ms_a_go"):
        good, msg = _insertar_altas(db, registros, usuario + " (ALTA)")
        if good:
            st.cache_data.clear()
            _subir_ver("alta")
            st.toast(f"✅ {msg}")
            st.rerun()
        else:
            st.error(msg)


# ---------------------------------------------------------- 3) historial y reversión
def _tab_historial(db, usuario):
    h = db.execute_query("""SELECT id, fecha, usuario, accion, detalles FROM logs_auditoria
                            WHERE usuario LIKE '%(MASIVO)%' OR usuario LIKE '%(ALTA)%' OR usuario LIKE '%(REVERSION)%'
                            ORDER BY fecha DESC LIMIT 15""", silencioso=True)
    if h is None or h.empty:
        st.info("Todavía no hay cambios masivos ni altas registrados.")
        return
    st.dataframe(h[["fecha", "usuario", "accion"]], hide_index=True, width="stretch")

    masivos = h[h["usuario"].astype(str).str.contains(r"\(MASIVO\)", regex=True)]
    if masivos.empty:
        return
    st.markdown("##### ↩️ Revertir un cambio masivo de precios")
    etiquetas = {int(r.id): f"#{int(r.id)} · {r.fecha:%d/%m %H:%M:%S} · {r.accion}" for r in masivos.itertuples()}
    elegido = st.selectbox("Cambio", list(etiquetas), format_func=etiquetas.get, key=f"ms_h_sel_{int(masivos.id.iloc[0])}")
    detalle = json.loads(masivos[masivos["id"] == elegido].iloc[0]["detalles"])
    ids = [int(c["id"]) for c in detalle]
    actual = db.execute_query("SELECT id, precio_minimo, precio_maximo FROM catalogo_maestro_v3 WHERE id = ANY(:ids)", {"ids": ids}, silencioso=True)
    act = {int(r.id): (round(float(r.precio_minimo), 2), round(float(r.precio_maximo), 2)) for r in actual.itertuples()} if actual is not None and not actual.empty else {}
    revertibles, cambiados = [], []
    for c in detalle:
        ahora = act.get(int(c["id"]))
        esperado = (round(float(c["despues"]["precio_minimo"]), 2), round(float(c["despues"]["precio_maximo"]), 2))
        if ahora == esperado:
            revertibles.append({**c, "antes": c["despues"], "despues": c["antes"]})
        else:
            cambiados.append(c["sku"])
    st.caption(f"{len(revertibles)} SKU(s) se pueden revertir; {len(cambiados)} ya cambiaron después y se dejan como están.")
    if cambiados:
        with st.expander("SKUs que ya cambiaron después (no se tocan)"):
            st.write(_d(", ".join(cambiados)))
    if revertibles:
        ok = st.checkbox(f"Confirmo revertir {len(revertibles)} SKU(s) a sus valores anteriores", key=f"ms_h_ok_{_ver('hist')}")
        if st.button("↩️ Revertir", disabled=not ok, key="ms_h_go"):
            good, msg = _guardar_cambios(db, revertibles, usuario + " (REVERSION)")
            if good:
                st.cache_data.clear()
                _subir_ver("hist")
                st.toast(f"✅ {msg}")
                st.rerun()
            else:
                st.error(msg)


# ---------------------------------------------------------- pantalla
def render_masivo(db, reglas: list, usuario: str = "admin"):
    st.markdown("### 🧮 Masivo y Altas · Liverpool")
    base = _cargar_catalogo(db)
    if base is None or base.empty:
        st.warning("No se pudo cargar el catálogo.")
        return
    t1, t2, t3 = st.tabs(["💲 Mínimos y máximos en masa", "➕ Dar de alta SKUs", "🕘 Historial y reversión"])
    with t1:
        _tab_minmax(db, base, reglas, usuario)
    with t2:
        _tab_altas(db, base, reglas, usuario)
    with t3:
        _tab_historial(db, usuario)
