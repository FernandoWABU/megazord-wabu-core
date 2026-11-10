# Batalla: un SKU frente a sus rivales, hora por hora.
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import estilo
from core.db import get_db
from core.odoo import cargar_nombres, describir
from modulos.catalogo_rapido import utilidad_a_precio

CDMX = ZoneInfo("America/Mexico_City")


@st.cache_data(ttl=120, show_spinner=False)
def _lista(_db) -> pd.DataFrame:
    df = _db.execute_query("""SELECT id, sku_limpio, sku_interno, sku_liverpool, id_cuenta, regla_estrategia AS regla,
                                     precio_minimo, precio_maximo, costo_odoo
                              FROM catalogo_maestro_v3 WHERE estatus = 'ACTIVO' ORDER BY sku_limpio""")
    for c in ("precio_minimo", "precio_maximo", "costo_odoo"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


@st.cache_data(ttl=60, show_spinner=False)
def _serie(_db, cuenta: str, sku_interno: str, horas: int) -> pd.DataFrame:
    desde = datetime.now(CDMX).replace(tzinfo=None) - timedelta(hours=horas)
    df = _db.execute_query("""SELECT fecha_hora, precio_rival, nuestro_precio, buybox, posicion
                              FROM historial_precios
                              WHERE id_cuenta = :c AND sku_interno = :s AND fecha_hora >= :d
                              ORDER BY fecha_hora LIMIT 6000""", {"c": cuenta, "s": sku_interno, "d": desde})
    if df.empty:
        return df
    df["precio_rival"] = pd.to_numeric(df["precio_rival"], errors="coerce")
    df["nuestro_precio"] = pd.to_numeric(df["nuestro_precio"], errors="coerce")
    return df


@st.cache_data(ttl=60, show_spinner=False)
def _rivales(_db, catalogo_id: int) -> pd.DataFrame:
    df = _db.execute_query("""SELECT nombre_rival, precio_rival, posicion, created_at
                              FROM monitoreo_rivales
                              WHERE catalogo_id = :i AND created_at > NOW() - INTERVAL '1 day'
                              ORDER BY created_at DESC LIMIT 200""", {"i": int(catalogo_id)})
    if df.empty:
        return df
    ultimo = pd.to_datetime(df["created_at"]).max()
    df = df[pd.to_datetime(df["created_at"]) >= ultimo - pd.Timedelta(minutes=3)].copy()
    df["precio_rival"] = pd.to_numeric(df["precio_rival"], errors="coerce")
    return df.sort_values("posicion")


def render():
    db = get_db()
    estilo.titulo("⚔️ Batalla por SKU")
    lista = _lista(db)
    if lista.empty:
        st.warning("No hay SKUs activos.")
        return
    q = st.text_input("🔍 Buscar", placeholder="SKU limpio, SKU Liverpool o SKU interno (sucio)", key="bat_q").strip().lower()
    vis = lista
    if q:
        m = (lista.sku_limpio.astype(str).str.lower().str.contains(q, regex=False)
             | lista.sku_liverpool.astype(str).str.lower().str.contains(q, regex=False)
             | lista.sku_interno.astype(str).str.lower().str.contains(q, regex=False))
        vis = lista[m]
        if vis.empty:
            st.warning("No encontré ese SKU entre los activos.")
            return
    et = {int(r.id): f"{r.sku_limpio} · LP {r.sku_liverpool} · {'Full' if str(r.sku_interno).upper().endswith('-FBL') else 'Almacén'} · {r.sku_interno} · R{r.regla[:1]}" for r in vis.itertuples()}
    c1, c2 = st.columns([3, 2])
    elegido = c1.selectbox("SKU", list(et), format_func=lambda i: et[i], key="bat_sku")
    horas = c2.radio("Ventana", [6, 24, 48, 168], index=1, horizontal=True, key="bat_h",
                     format_func=lambda h: f"{h} h" if h < 168 else "7 días")
    r = lista[lista.id == elegido].iloc[0]

    # ---- etiqueta con el nombre real (Odoo)
    nombres = cargar_nombres(db)
    d = describir(r.sku_limpio, nombres)
    tipo_txt = {"simple": "Producto", "paquete": "Paquete", "combo": "Combo"}.get(d["tipo"], "Producto")
    st.markdown(estilo.chip(tipo_txt, "info") + f"<b>{d['titulo']}</b>", unsafe_allow_html=True)
    st.caption(f"{d['referencia']} · SKU limpio {r.sku_limpio} · SKU Liverpool {r.sku_liverpool}")
    if not nombres:
        st.caption("ℹ️ Los nombres se llenan cuando corre el sincronizador de Odoo (una vez actualizado, se verán aquí).")
    elif d["faltan"]:
        st.warning("No encontré en Odoo el código: " + ", ".join(d["faltan"]) + ". Revisa que exista y esté activo.")
    serie = _serie(db, r.id_cuenta, r.sku_interno, horas)
    num = serie.dropna(subset=["nuestro_precio", "precio_rival"]) if not serie.empty else serie

    # ---- tarjetas
    mi, bb, pos, estado = None, None, "—", "Sin lectura"
    if not num.empty:
        u = num.iloc[-1]
        mi, bb, pos = u.nuestro_precio, u.precio_rival, u.posicion
        estado = "Ganando" if str(u.buybox).startswith("¡Nosotros") else ("Perdiendo" if str(u.buybox).startswith("Rival") else "—")
    util = utilidad_a_precio(mi, r.costo_odoo) if mi else None
    k = st.columns(4)
    estilo.kpi(k[0], "Mi precio", f"${mi:,.2f}" if mi else "—", f"mín ${r.precio_minimo:,.2f} · máx ${r.precio_maximo:,.2f}")
    estilo.kpi(k[1], "BuyBox rival", f"${bb:,.2f}" if bb else "—", f"posición {pos}")
    estilo.kpi(k[2], "Estado", estado, r.regla, "ok" if estado == "Ganando" else ("bad" if estado == "Perdiendo" else "info"))
    estilo.kpi(k[3], "Utilidad por pieza", f"${util:,.2f}" if util is not None else "—", "a mi precio actual",
               "ok" if (util or 0) > 0 else "warn")

    # ---- gráfica
    estilo.titulo("📈 Precio en el tiempo")
    if num.empty:
        st.info("Sin lecturas con precio de rival en esta ventana.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=num.fecha_hora, y=num.nuestro_precio, name="Mi precio", mode="lines",
                                 line=dict(color="#38bdf8", width=3, shape="hv")))
        fig.add_trace(go.Scatter(x=num.fecha_hora, y=num.precio_rival, name="BuyBox rival", mode="lines",
                                 line=dict(color="#f59e0b", width=2, shape="hv")))
        if r.precio_minimo > 0:
            fig.add_hline(y=r.precio_minimo, line_dash="dot", line_color="#ef4444", annotation_text="mínimo")
        if r.precio_maximo > 0:
            fig.add_hline(y=r.precio_maximo, line_dash="dot", line_color="#22c55e", annotation_text="máximo")
        fig.update_layout(template="plotly_dark", height=380, margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=1.1), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch")

    # ---- rivales ahora
    estilo.titulo("🥊 Rivales en la última lectura")
    riv = _rivales(db, r.id)
    if riv.empty:
        st.caption("Sin lectura reciente de rivales.")
    else:
        st.dataframe(riv[["posicion", "nombre_rival", "precio_rival"]], hide_index=True, width="stretch",
                     column_config={"posicion": "Lugar", "nombre_rival": "Vendedor",
                                    "precio_rival": st.column_config.NumberColumn("Precio", format="dollar")})

    # ---- cambios de precio
    estilo.titulo("🕘 Cambios de precio propios")
    if not num.empty:
        ch = num.copy()
        ch["anterior"] = ch["nuestro_precio"].shift()
        ch = ch[(ch["anterior"].notna()) & (ch["anterior"] != ch["nuestro_precio"])].copy()
        if ch.empty:
            st.caption("No cambiaste el precio en esta ventana.")
        else:
            ch["motivo"] = ch["buybox"].astype(str).str.split("|").str[-1].str.strip()
            ch["cambio"] = ch["nuestro_precio"] - ch["anterior"]
            st.dataframe(ch.sort_values("fecha_hora", ascending=False)[["fecha_hora", "anterior", "nuestro_precio", "cambio", "motivo"]].head(60),
                         hide_index=True, width="stretch",
                         column_config={"fecha_hora": "Hora (CDMX)",
                                        "anterior": st.column_config.NumberColumn("Antes", format="dollar"),
                                        "nuestro_precio": st.column_config.NumberColumn("Después", format="dollar"),
                                        "cambio": st.column_config.NumberColumn("Cambio", format="dollar"),
                                        "motivo": "Qué pasó"})
