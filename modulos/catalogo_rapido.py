# ==========================================================
# MEGAZORD WAR ROOM - Editor Rápido de Catálogo (v1)
# Pensado para: ser rápido (un solo viaje a la BD), usable desde el celular
# y seguro (valida, confirma, audita y permite volver atrás).
# Se usa desde dashboard.py:  render_catalogo_rapido(db, REGLAS)
# ==========================================================
import json
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import text

ESTATUS_VALIDOS = ["ACTIVO", "INACTIVO"]

# Misma fórmula que calcular_rentabilidad() del bot (comisión 17%, envío 130, retenciones 10.5% sobre base sin IVA)
def utilidad_a_precio(precio, costo):
    try:
        precio = float(precio or 0)
        costo = float(costo or 0)
    except (TypeError, ValueError):
        return None
    if precio <= 0 or costo <= 0:
        return None
    neto = precio - precio * 0.17 - 130.0 - (precio / 1.16) * 0.105
    return round(neto - costo * 1.16, 2)


def _rerun():
    """Recarga solo el fragmento (rápido) si existe; si no, toda la página."""
    if hasattr(st, "fragment"):
        try:
            st.rerun(scope="fragment")
            return
        except Exception:
            pass
    st.rerun()


def _fragment(fn):
    """st.fragment evita recargar TODO el dashboard en cada clic (si la versión de Streamlit lo soporta)."""
    frag = getattr(st, "fragment", None)
    return frag(fn) if frag else fn


# ---------------------------------------------------------- datos
@st.cache_data(ttl=60, show_spinner=False)
def _cargar_catalogo(_db) -> pd.DataFrame:
    df = _db.execute_query("""
        SELECT id, sku_limpio, sku_interno, sku_liverpool, id_cuenta,
               COALESCE(NULLIF(TRIM(estatus), ''), 'INACTIVO')                 AS estatus,
               COALESCE(NULLIF(TRIM(regla_estrategia), ''), '1. Gladiador')    AS regla,
               precio_minimo, precio_maximo, costo_odoo, stock
        FROM catalogo_maestro_v3
        ORDER BY (estatus = 'ACTIVO') DESC, sku_limpio
    """)
    if df.empty:
        return df
    for c in ("precio_minimo", "precio_maximo", "costo_odoo"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
    df["estatus"] = df["estatus"].str.upper()
    return df


@st.cache_data(ttl=120, show_spinner=False)
def _cargar_mercado(_db) -> pd.DataFrame:
    """Último precio numérico (nuestro y del BuyBox) de los SKUs ACTIVOS. Usa el índice (cuenta, sku, fecha)."""
    return _db.execute_query("""
        SELECT c.id,
               h.nuestro_precio::numeric AS precio_actual,
               h.precio_rival::numeric   AS buybox,
               h.fecha_hora              AS visto
        FROM catalogo_maestro_v3 c
        LEFT JOIN LATERAL (
            SELECT nuestro_precio, precio_rival, fecha_hora
            FROM historial_precios h
            WHERE h.id_cuenta = c.id_cuenta AND h.sku_interno = c.sku_interno
              AND h.precio_rival ~ '^[0-9]+(\\.[0-9]+)?$'
              AND h.nuestro_precio ~ '^[0-9]+(\\.[0-9]+)?$'
            ORDER BY h.fecha_hora DESC LIMIT 1
        ) h ON TRUE
        WHERE c.estatus = 'ACTIVO'
    """)


# ---------------------------------------------------------- escritura segura
def _guardar_cambios(db, cambios: list, usuario: str) -> tuple:
    """cambios = [{'id', 'sku', 'antes': {...}, 'despues': {...}}]. Una sola transacción + auditoría."""
    if db.engine is None:
        return False, "Sin conexión a la base de datos"
    try:
        with db.engine.begin() as conn:
            for c in cambios:
                d = c["despues"]
                conn.execute(
                    text("""UPDATE catalogo_maestro_v3
                            SET estatus = :estatus, regla_estrategia = :regla,
                                precio_minimo = :pmin, precio_maximo = :pmax, updated_at = NOW()
                            WHERE id = :id"""),
                    {"estatus": d["estatus"], "regla": d["regla"], "pmin": d["precio_minimo"],
                     "pmax": d["precio_maximo"], "id": c["id"]},
                )
            conn.execute(
                text("INSERT INTO logs_auditoria (usuario, accion, detalles) VALUES (:u, :a, :d)"),
                {"u": usuario, "a": f"EDITOR_RAPIDO ({len(cambios)} SKUs)",
                 "d": json.dumps(cambios, default=str, ensure_ascii=False)},
            )
        return True, f"{len(cambios)} SKU(s) actualizados"
    except Exception as e:
        return False, f"No se guardó nada: {str(e)[:160]}"


def _validar(cambios: list) -> tuple:
    """Devuelve (errores, avisos). Los errores bloquean el guardado."""
    errores, avisos = [], []
    for c in cambios:
        d, sku = c["despues"], c["sku"]
        pmin, pmax = d["precio_minimo"], d["precio_maximo"]
        if d["estatus"] not in ESTATUS_VALIDOS:
            errores.append(f"{sku}: estatus inválido")
        if pmin < 0 or pmax < 0:
            errores.append(f"{sku}: precios negativos")
        if d["estatus"] == "ACTIVO":
            if pmin <= 0 or pmax <= 0:
                errores.append(f"{sku}: no se puede ACTIVAR sin mínimo y máximo")
            elif pmin >= pmax:
                errores.append(f"{sku}: el mínimo (${pmin:,.2f}) debe ser menor que el máximo (${pmax:,.2f})")
            else:
                u = utilidad_a_precio(pmin, c.get("costo", 0))
                if u is None:
                    avisos.append(f"{sku}: sin costo Odoo, no se puede validar el margen")
                elif u < 0:
                    avisos.append(f"{sku}: al mínimo (${pmin:,.2f}) pierdes ${abs(u):,.2f} por pieza")
    return errores, avisos


# ---------------------------------------------------------- pantalla
@_fragment
def render_catalogo_rapido(db, reglas: list, usuario: str = "admin"):
    st.markdown("### ⚡ Editor Rápido de Catálogo")

    base = _cargar_catalogo(db)
    if base.empty:
        st.warning("No se pudo cargar el catálogo.")
        return

    # --- estado de sesión: copia de trabajo + versión del editor
    if "cr_work" not in st.session_state or st.session_state.get("cr_base_len") != len(base):
        st.session_state.cr_work = base.copy()
        st.session_state.cr_base_len = len(base)
        st.session_state.cr_ver = 0
    work = st.session_state.cr_work

    # --- KPIs compactos
    act = base[base.estatus == "ACTIVO"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Activos", len(act))
    k2.metric("Inactivos", len(base) - len(act))
    k3.metric("Con Regla 9", int((base.regla.str.startswith("9")).sum()))
    k4.metric("Activos sin costo", int((act.costo_odoo <= 0).sum()))

    # --- filtros
    f1, f2, f3 = st.columns([2, 1, 2])
    q = f1.text_input("🔍 Buscar", placeholder="SKU limpio, interno o Liverpool", key="cr_q").strip()
    vista = f2.radio("Ver", ["Activos", "Inactivos", "Todos"], horizontal=True, key="cr_vista")
    reglas_sel = f3.multiselect("Regla", reglas, key="cr_reglas", placeholder="Todas")
    mercado_on = st.toggle("📡 Mostrar precio actual y BuyBox (activos)", key="cr_mercado",
                           help="Hace una consulta extra al historial; apágalo si quieres máxima velocidad.")
    modo_cel = st.toggle("📱 Modo celular (un SKU a la vez)", key="cr_cel")

    vis = work.copy()
    if vista == "Activos":
        vis = vis[vis.estatus == "ACTIVO"]
    elif vista == "Inactivos":
        vis = vis[vis.estatus != "ACTIVO"]
    if reglas_sel:
        vis = vis[vis.regla.isin(reglas_sel)]
    if q:
        m = (vis.sku_limpio.astype(str).str.contains(q, case=False, na=False, regex=False)
             | vis.sku_interno.astype(str).str.contains(q, case=False, na=False, regex=False)
             | vis.sku_liverpool.astype(str).str.contains(q, case=False, na=False, regex=False))
        vis = vis[m]

    # --- columnas calculadas
    vis = vis.copy()
    vis["util_min"] = [utilidad_a_precio(a, b) for a, b in zip(vis.precio_minimo, vis.costo_odoo)]
    if mercado_on:
        mk = _cargar_mercado(db)
        if not mk.empty:
            mk = mk.assign(**{c: pd.to_numeric(mk[c], errors="coerce") for c in ("precio_actual", "buybox")})
            vis = vis.merge(mk[["id", "precio_actual", "buybox"]], on="id", how="left")

    # ---------------- MODO CELULAR
    if modo_cel:
        _modo_celular(db, vis, base, reglas, usuario)
        return

    # ---------------- GRID
    st.caption(f"{len(vis)} SKUs en pantalla · edita directo en la tabla, revisa los cambios y guarda una sola vez.")
    vis.insert(0, "sel", False)
    cols = ["sel", "sku_limpio", "estatus", "regla", "precio_minimo", "precio_maximo", "util_min", "costo_odoo"]
    if mercado_on and "buybox" in vis.columns:
        cols += ["precio_actual", "buybox"]
    cols += ["stock", "sku_interno", "sku_liverpool", "id", "id_cuenta"]
    vis = vis[[c for c in cols if c in vis.columns]]

    firma = abs(hash((vista, q, tuple(reglas_sel), mercado_on))) % 10**8
    editado = st.data_editor(
        vis,
        key=f"cr_editor_{st.session_state.cr_ver}_{firma}",
        hide_index=True,
        width="stretch",
        height=460,
        disabled=[c for c in vis.columns if c not in ("sel", "estatus", "regla", "precio_minimo", "precio_maximo")],
        column_config={
            "sel": st.column_config.CheckboxColumn("☑", width="small", help="Marca SKUs para acciones en lote"),
            "sku_limpio": st.column_config.TextColumn("SKU", width="medium"),
            "estatus": st.column_config.SelectboxColumn("Estatus", options=ESTATUS_VALIDOS, required=True, width="small"),
            "regla": st.column_config.SelectboxColumn("Regla", options=reglas, required=True, width="medium"),
            "precio_minimo": st.column_config.NumberColumn("Mínimo", format="$%.2f", min_value=0.0, step=0.01),
            "precio_maximo": st.column_config.NumberColumn("Máximo", format="$%.2f", min_value=0.0, step=0.01),
            "util_min": st.column_config.NumberColumn("Utilidad al mín.", format="$%.2f", help="Ganancia por pieza si vendes al precio mínimo"),
            "costo_odoo": st.column_config.NumberColumn("Costo", format="$%.2f"),
            "precio_actual": st.column_config.NumberColumn("Mi precio", format="$%.2f"),
            "buybox": st.column_config.NumberColumn("BuyBox", format="$%.2f"),
            "id": None, "id_cuenta": st.column_config.TextColumn("Cuenta", width="small"),
        },
    )

    # --- acciones en lote sobre lo marcado
    marcados = editado[editado["sel"]]
    with st.expander(f"🧰 Acciones en lote ({len(marcados)} marcados)", expanded=len(marcados) > 0):
        b1, b2, b3 = st.columns([2, 2, 1])
        nueva_regla = b1.selectbox("Cambiar regla a", ["(sin cambio)"] + reglas, key="cr_b_regla")
        nuevo_est = b2.selectbox("Cambiar estatus a", ["(sin cambio)"] + ESTATUS_VALIDOS, key="cr_b_est")
        if b3.button("Aplicar", disabled=marcados.empty, width="stretch"):
            _volcar_ediciones(work, editado)  # conserva lo que ya editaste en la tabla
            idx = work.index[work.id.isin(marcados["id"])]
            if nueva_regla != "(sin cambio)":
                work.loc[idx, "regla"] = nueva_regla
            if nuevo_est != "(sin cambio)":
                work.loc[idx, "estatus"] = nuevo_est
            st.session_state.cr_ver += 1
            _rerun()

    # --- diff contra la base
    _volcar_ediciones(work, editado)
    cambios = _calcular_cambios(base, work)

    if not cambios:
        st.info("Sin cambios pendientes.")
    else:
        errores, avisos = _validar(cambios)
        st.markdown(f"#### 📝 {len(cambios)} cambio(s) pendiente(s)")
        resumen = pd.DataFrame([{
            "SKU": c["sku"],
            "Estatus": _flecha(c["antes"]["estatus"], c["despues"]["estatus"]),
            "Regla": _flecha(c["antes"]["regla"], c["despues"]["regla"]),
            "Mínimo": _flecha(c["antes"]["precio_minimo"], c["despues"]["precio_minimo"], "$"),
            "Máximo": _flecha(c["antes"]["precio_maximo"], c["despues"]["precio_maximo"], "$"),
        } for c in cambios])
        st.dataframe(resumen, hide_index=True, width="stretch")
        for e in errores:
            st.error(e)
        for a in avisos:
            st.warning(a)
        if any(c["despues"]["regla"].startswith("9") and not c["antes"]["regla"].startswith("9") for c in cambios):
            st.info("🎲 Vas a activar la Regla 9. Verifica que el mínimo de cada SKU sea un piso con el que aceptes vender.")

        g1, g2 = st.columns(2)
        if g1.button("💾 Guardar cambios", type="primary", disabled=bool(errores), width="stretch"):
            ok, msg = _guardar_cambios(db, cambios, usuario)
            if ok:
                st.cache_data.clear()
                for k in ("cr_work", "cr_base_len"):
                    st.session_state.pop(k, None)
                st.session_state.cr_ver = st.session_state.get("cr_ver", 0) + 1
                st.toast(f"✅ {msg}")
                _rerun()
            else:
                st.error(msg)
        if g2.button("↩️ Descartar", width="stretch"):
            st.session_state.cr_work = base.copy()
            st.session_state.cr_ver += 1
            _rerun()

    _panel_panico(db, base, usuario)
    _historial_cambios(db)


# ---------------------------------------------------------- piezas
def _flecha(a, b, pref=""):
    if a == b:
        return "—"
    if pref == "$":
        return f"${float(a):,.2f} → ${float(b):,.2f}"
    return f"{a} → {b}"


def _volcar_ediciones(work: pd.DataFrame, editado: pd.DataFrame):
    """Copia a la tabla de trabajo lo que se editó en la rejilla (por id)."""
    if editado is None or editado.empty:
        return
    e = editado.set_index("id")
    for col in ("estatus", "regla", "precio_minimo", "precio_maximo"):
        s = e[col]
        mask = work["id"].isin(s.index)
        work.loc[mask, col] = work.loc[mask, "id"].map(s).values
    work["estatus"] = work["estatus"].astype(str).str.upper()


def _calcular_cambios(base: pd.DataFrame, work: pd.DataFrame) -> list:
    b = base.set_index("id")
    w = work.set_index("id")
    cambios = []
    for i in w.index:
        antes = {"estatus": b.at[i, "estatus"], "regla": b.at[i, "regla"],
                 "precio_minimo": round(float(b.at[i, "precio_minimo"]), 2),
                 "precio_maximo": round(float(b.at[i, "precio_maximo"]), 2)}
        despues = {"estatus": w.at[i, "estatus"], "regla": w.at[i, "regla"],
                   "precio_minimo": round(float(w.at[i, "precio_minimo"]), 2),
                   "precio_maximo": round(float(w.at[i, "precio_maximo"]), 2)}
        if antes != despues:
            cambios.append({"id": int(i), "sku": str(w.at[i, "sku_limpio"]),
                            "costo": float(w.at[i, "costo_odoo"]), "antes": antes, "despues": despues})
    return cambios


def _modo_celular(db, vis, base, reglas, usuario):
    if vis.empty:
        st.info("No hay SKUs con ese filtro.")
        return
    etiquetas = {int(r.id): f"{r.sku_limpio}  ·  {r.estatus}  ·  {r.regla[:1]}" for r in vis.itertuples()}
    elegido = st.selectbox("SKU", list(etiquetas), format_func=lambda i: etiquetas[i], key="cr_cel_sku")
    r = base[base.id == elegido].iloc[0]
    st.markdown(f"**{r.sku_limpio}** · costo ${r.costo_odoo:,.2f} · stock {r.stock if pd.notna(r.stock) else '—'}")
    estatus = st.radio("Estatus", ESTATUS_VALIDOS, index=ESTATUS_VALIDOS.index(r.estatus) if r.estatus in ESTATUS_VALIDOS else 1,
                       horizontal=True, key=f"cr_cel_e_{elegido}")
    regla = st.selectbox("Regla", reglas, index=reglas.index(r.regla) if r.regla in reglas else 0, key=f"cr_cel_r_{elegido}")
    c1, c2 = st.columns(2)
    pmin = c1.number_input("Mínimo", value=float(r.precio_minimo), min_value=0.0, step=1.0, format="%.2f", key=f"cr_cel_n_{elegido}")
    pmax = c2.number_input("Máximo", value=float(r.precio_maximo), min_value=0.0, step=1.0, format="%.2f", key=f"cr_cel_x_{elegido}")
    u = utilidad_a_precio(pmin, r.costo_odoo)
    if u is not None:
        (st.success if u >= 0 else st.error)(f"Utilidad al mínimo: ${u:,.2f} por pieza")
    cambio = {"id": int(r.id), "sku": r.sku_limpio, "costo": float(r.costo_odoo),
              "antes": {"estatus": r.estatus, "regla": r.regla, "precio_minimo": round(float(r.precio_minimo), 2), "precio_maximo": round(float(r.precio_maximo), 2)},
              "despues": {"estatus": estatus, "regla": regla, "precio_minimo": round(pmin, 2), "precio_maximo": round(pmax, 2)}}
    hay = cambio["antes"] != cambio["despues"]
    errores, avisos = _validar([cambio]) if hay else ([], [])
    for e in errores:
        st.error(e)
    for a in avisos:
        st.warning(a)
    if st.button("💾 Guardar", type="primary", disabled=(not hay) or bool(errores), width="stretch", key="cr_cel_save"):
        ok, msg = _guardar_cambios(db, [cambio], usuario)
        if ok:
            st.cache_data.clear()
            st.session_state.pop("cr_work", None)
            st.toast(f"✅ {msg}")
            _rerun()
        else:
            st.error(msg)


def _panel_panico(db, base, usuario):
    n9 = base[base.regla.str.startswith("9")]
    with st.expander(f"🛑 Botón de pánico — Regla 9 → Gladiador ({len(n9)} SKUs con Regla 9)"):
        st.caption("Regresa de inmediato todos los SKUs con Regla 9 a '1. Gladiador'. No cambia precios ni estatus.")
        ok = st.checkbox("Sí, quiero regresar todos a Gladiador", key="cr_panico_ok")
        if st.button("Ejecutar", disabled=(not ok) or n9.empty, key="cr_panico"):
            cambios = [{"id": int(r.id), "sku": r.sku_limpio, "costo": float(r.costo_odoo),
                        "antes": {"estatus": r.estatus, "regla": r.regla, "precio_minimo": float(r.precio_minimo), "precio_maximo": float(r.precio_maximo)},
                        "despues": {"estatus": r.estatus, "regla": "1. Gladiador", "precio_minimo": float(r.precio_minimo), "precio_maximo": float(r.precio_maximo)}}
                       for r in n9.itertuples()]
            good, msg = _guardar_cambios(db, cambios, usuario + " (PANICO)")
            if good:
                st.cache_data.clear()
                st.session_state.pop("cr_work", None)
                st.toast(f"✅ {msg}")
                _rerun()
            else:
                st.error(msg)


def _historial_cambios(db):
    with st.expander("🕘 Últimos cambios hechos desde aquí"):
        h = db.execute_query("""SELECT fecha, usuario, accion FROM logs_auditoria
                                WHERE accion LIKE 'EDITOR_RAPIDO%' ORDER BY fecha DESC LIMIT 15""")
        if h.empty:
            st.caption("Todavía no hay cambios registrados.")
        else:
            st.dataframe(h, hide_index=True, width="stretch")
            st.caption("El detalle (antes y después de cada SKU) queda en logs_auditoria.detalles por si necesitas revertir.")
