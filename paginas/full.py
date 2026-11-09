# Full: cuántas piezas conviene mandar a Fulfillment by Liverpool.
# Ventas reales del reporte de pedidos (tabla pedidos_liverpool) + stock en Liverpool Marketplace (lectura del bot)
# + piezas por almacén de Odoo (tabla odoo_stock).
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from core import auth, estilo
from core.db import get_db
from core.odoo import ALMACENES_CONTAR, ALMACENES_IGNORAR, cargar_nombres, cargar_stock, describir, descomponer, unidades_disponibles
from core.pedidos import cargar_pedidos, guardar_pedidos, parse_reporte

CDMX = ZoneInfo("America/Mexico_City")


@st.cache_data(ttl=600, show_spinner=False)
def _catalogo(_db) -> pd.DataFrame:
    df = _db.execute_query("""SELECT sku_interno, sku_liverpool, sku_limpio, costo_odoo, estatus, regla_estrategia AS regla
                              FROM catalogo_maestro_v3 WHERE COALESCE(sku_liverpool, '') <> ''""")
    df["costo_odoo"] = pd.to_numeric(df["costo_odoo"], errors="coerce").fillna(0.0)
    return df


@st.cache_data(ttl=600, show_spinner=False)
def _stock_liverpool(_db) -> pd.DataFrame:
    """Último stock leído por el bot en Liverpool Marketplace (últimos 3 días) por SKU de Liverpool."""
    df = _db.execute_query("""
        SELECT sku_liverpool, max(s) AS stock_lp, max(fecha_hora) AS lectura FROM (
            SELECT DISTINCT ON (sku_interno, sku_liverpool) sku_liverpool, stock::int AS s, fecha_hora
            FROM historial_precios
            WHERE stock ~ '^[0-9]+$' AND fecha_hora >= now() - interval '3 days'
            ORDER BY sku_interno, sku_liverpool, fecha_hora DESC) t
        GROUP BY sku_liverpool""")
    return df


def _ventas_por_sku(ped: pd.DataFrame, cat: pd.DataFrame) -> pd.DataFrame:
    """Unidades netas por SKU de Liverpool en 30/60/90/120 días (se ancla a la fecha del último pedido del reporte)."""
    fin = ped.fecha.max()
    validos = set(cat.sku_liverpool.astype(str))
    por_oferta = dict(zip(cat.sku_interno, cat.sku_liverpool.astype(str)))
    ped = ped.copy()
    ped["sku"] = ped.apply(lambda r: r.sku_liverpool if r.sku_liverpool in validos else por_oferta.get(r.sku_oferta, r.sku_liverpool), axis=1)
    out = pd.DataFrame(index=sorted(ped.sku.unique()))
    for d in (30, 60, 90, 120):
        w = ped[ped.fecha > fin - pd.Timedelta(days=d)]
        out[f"u{d}"] = w.groupby("sku").netas.sum()
    out = out.fillna(0).astype(int)
    out["ultima_venta"] = ped.groupby("sku").fecha.max()
    return out, fin


def _tabla(db, ped, dias_cob, factor, solo_activos):
    cat = _catalogo(db)
    ventas, fin = _ventas_por_sku(ped, cat)
    lp = _stock_liverpool(db).set_index("sku_liverpool") if not _stock_liverpool(db).empty else pd.DataFrame(columns=["stock_lp"])
    stk = cargar_stock(db)
    nombres = cargar_nombres(db)

    activos = cat[cat.estatus == "ACTIVO"].drop_duplicates("sku_liverpool").set_index("sku_liverpool")
    otros = cat.drop_duplicates("sku_liverpool").set_index("sku_liverpool")
    filas = []
    for sku, v in ventas.iterrows():
        fila_cat = activos.loc[sku] if sku in activos.index else (otros.loc[sku] if sku in otros.index else None)
        stock_lp = int(lp.stock_lp.get(sku, 0)) if sku in lp.index else 0
        es_activo = sku in activos.index
        if solo_activos and not (es_activo or stock_lp > 0):
            continue
        # velocidad ponderada: lo reciente pesa más
        vel = 0.5 * v.u30 / 30 + 0.3 * v.u60 / 60 + 0.2 * v.u120 / 120
        limpio = fila_cat.sku_limpio if fila_cat is not None else sku
        filas.append({"sku_liverpool": sku, "sku": limpio, "producto": describir(limpio, nombres)["titulo"] if nombres else "—",
                      "u30": v.u30, "u90": v.u90, "u120": v.u120, "vel": vel, "stock_lp": stock_lp,
                      "costo": float(fila_cat.costo_odoo) if fila_cat is not None else 0.0, "activo": es_activo,
                      "ultima_venta": v.ultima_venta})
    t = pd.DataFrame(filas)
    if t.empty:
        return t, fin
    t["demanda"] = t.vel * dias_cob * factor
    t["agregar"] = (t.demanda - t.stock_lp).apply(lambda x: max(0, math.ceil(x - 1e-9)))
    # tendencia: ritmo de los últimos 30 días contra el promedio de 120
    t["tendencia"] = t.apply(lambda r: (r.u30 / 30) / (r.u120 / 120) if r.u120 else None, axis=1)

    # Odoo: piezas por almacén y total contable
    contar = set(ALMACENES_CONTAR)
    por_cod = stk[stk.almacen.isin(contar)].groupby("default_code").cantidad.sum().to_dict() if not stk.empty else {}
    por_alm = {a: stk[stk.almacen == a].groupby("default_code").cantidad.sum().to_dict() for a in ALMACENES_CONTAR} if not stk.empty else {}
    for a in ALMACENES_CONTAR:
        t[f"alm_{a}"] = t.sku.apply(lambda s, a=a: unidades_disponibles(s, por_alm.get(a, {})))
    t["disponible"] = t.sku.apply(lambda s: unidades_disponibles(s, por_cod))
    t["enviar"] = t[["agregar", "disponible"]].min(axis=1).astype(int)
    t["conseguir"] = (t.agregar - t.enviar).astype(int)
    t["inversion"] = t.conseguir * t.costo
    return t, fin


def _cargar_reporte(db):
    with st.expander("📥 Cargar reporte de pedidos (Seller Center)", expanded=not len(cargar_pedidos(db))):
        st.caption("Sube el Excel «OrderReport» tal como lo descargas. Solo se guardan fecha, pedido, SKU, cantidad, precio, estado y fulfillment; "
                   "no se guardan nombre, dirección ni teléfono del cliente. Si repites pedidos, se actualizan sin duplicarse.")
        if not auth.es_admin():
            st.info("Solo el modo Admin puede cargar reportes.")
            return
        up = st.file_uploader("Reporte .xlsx", type=["xlsx"], key="fu_up")
        if up is not None:
            try:
                df = parse_reporte(up)
            except Exception as e:
                st.error(f"No pude leer el reporte: {e}")
                return
            st.write(f"Leí **{len(df):,}** líneas, del {df.fecha.min():%d/%m/%Y} al {df.fecha.max():%d/%m/%Y}.")
            if st.button("Guardar en la base", type="primary", key="fu_guardar"):
                ok, msg = guardar_pedidos(db, df)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.cache_data.clear()
                    st.rerun()


def render():
    estilo.titulo("📦 Forecast para Full")
    db = get_db()
    _cargar_reporte(db)
    ped = cargar_pedidos(db)
    if ped.empty:
        st.info("Todavía no hay pedidos cargados. Sube el reporte de arriba para calcular el forecast.")
        return

    c = st.columns(4)
    cob = c[0].selectbox("Cobertura deseada", [15, 21, 30, 45, 60], index=2, format_func=lambda d: f"{d} días", key="fu_cob")
    fac = c[1].selectbox("Factor de evento", [1.0, 1.5, 2.0, 3.0], index=0, format_func=lambda f: f"x{f:g}", key="fu_fac",
                         help="Multiplica la demanda (Buen Fin, Navidad).")
    solo_act = c[2].toggle("Solo activos o con stock en Liverpool", value=True, key="fu_act")
    solo_rep = c[3].toggle("Solo con piezas por agregar", value=True, key="fu_rep")

    t, fin = _tabla(db, ped, cob, fac, solo_act)
    if t.empty:
        st.info("Ningún SKU con ventas cumple el filtro.")
        return
    stk = cargar_stock(db)
    if stk.empty:
        st.warning("Todavía no hay stock de Odoo por almacén (tabla odoo_stock). Corre el sincronizador de Odoo; mientras tanto, "
                   "«Disponible» sale en 0 y «Enviar» no se calcula.")
    v = t[t.agregar > 0] if solo_rep else t
    v = v.sort_values(["agregar", "u30"], ascending=False)

    k = st.columns(5)
    estilo.kpi(k[0], "Pedidos en el reporte", f"{len(ped):,}", f"hasta {fin:%d/%m/%Y}", "info")
    estilo.kpi(k[1], "SKUs a reponer", int((t.agregar > 0).sum()), f"de {len(t)} con ventas", "warn")
    estilo.kpi(k[2], "Piezas por agregar", int(t.agregar.sum()), f"{cob} días x{fac:g}", "warn")
    estilo.kpi(k[3], "Salen de tus almacenes", int(t.enviar.sum()), "según Odoo", "ok")
    estilo.kpi(k[4], "Por conseguir", int(t.conseguir.sum()), f"inversión ${t.inversion.sum():,.0f}", "info")

    cols_alm = {f"alm_{a}": a for a in ALMACENES_CONTAR}
    out = pd.DataFrame({
        "SKU": v.sku, "SKU Liverpool": v.sku_liverpool, "Producto": v.producto,
        "30 d": v.u30, "90 d": v.u90, "120 d": v.u120, "Por día": v.vel.round(2),
        "Tendencia": v.tendencia.round(2), "Stock Liverpool": v.stock_lp,
        "Agregar a Full": v.agregar, **{name: v[col] for col, name in cols_alm.items()},
        "Disponible Odoo": v.disponible, "Enviar": v.enviar, "Por conseguir": v.conseguir,
        "Costo unit.": v.costo, "Inversión": v.inversion,
        "Última venta": v.ultima_venta.dt.strftime("%d/%m/%Y"),
        "Activo": v.activo.map({True: "Sí", False: "No"}),
    })
    dolar = lambda n: st.column_config.NumberColumn(n, format="dollar")
    st.dataframe(out, hide_index=True, width="stretch", column_config={
        "Costo unit.": dolar("Costo unit."), "Inversión": dolar("Inversión"),
        "Tendencia": st.column_config.NumberColumn("Tendencia", format="%.2fx", help="Ritmo de 30 días ÷ ritmo de 120 días. Arriba de 1 va subiendo.")})
    st.download_button("⬇️ Descargar CSV para Full", out.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"forecast_full_{datetime.now(CDMX):%Y%m%d}.csv", mime="text/csv")

    if not stk.empty:
        desconocidos = sorted(set(stk.almacen) - set(ALMACENES_CONTAR) - set(ALMACENES_IGNORAR))
        if desconocidos:
            st.caption("Ubicaciones de Odoo que no están en ninguna de tus dos listas (se ignoran): " + ", ".join(desconocidos[:15]))
    with st.expander("¿Cómo se calcula?"):
        st.markdown(
            "- **Ventas:** del reporte de pedidos, sin cancelados ni rechazados y restando piezas devueltas. "
            "Los periodos se cuentan hacia atrás desde el último pedido del reporte.\n"
            "- **Por día:** 50% ritmo de 30 días + 30% ritmo de 60 días + 20% ritmo de 120 días.\n"
            "- **Agregar a Full:** por día × cobertura × factor − stock que hoy tiene Liverpool Marketplace (última lectura del bot).\n"
            f"- **Almacenes que cuentan (Odoo, «/Existencias»):** {', '.join(ALMACENES_CONTAR)}. "
            f"**No cuentan:** {', '.join(ALMACENES_IGNORAR)}.\n"
            "- **Paquetes y combos:** «HNAU/2» usa 2 piezas de HNAU por paquete; un combo se limita a la pieza que menos hay.\n"
            "- **Límites:** si un SKU estuvo agotado, vendió menos de lo que pudo; la demanda real puede ser mayor.")
