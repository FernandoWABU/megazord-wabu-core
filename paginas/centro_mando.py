# Centro de Mando: estado general y "qué necesita atención hoy".
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from core import estilo
from core.db import get_db

CDMX = ZoneInfo("America/Mexico_City")


@st.cache_data(ttl=60, show_spinner=False)
def _estado_activos(_db) -> pd.DataFrame:
    """Última lectura de cada SKU ACTIVO (usa el índice cuenta+sku+fecha)."""
    df = _db.execute_query("""
        SELECT c.id, c.sku_limpio, c.sku_interno, c.id_cuenta, c.regla_estrategia AS regla,
               c.precio_minimo, c.precio_maximo, c.costo_odoo, c.stock AS stock_cat,
               h.fecha_hora, h.precio_rival, h.nuestro_precio, h.posicion, h.buybox
        FROM catalogo_maestro_v3 c
        LEFT JOIN LATERAL (
            SELECT fecha_hora, precio_rival, nuestro_precio, posicion, buybox
            FROM historial_precios h
            WHERE h.id_cuenta = c.id_cuenta AND h.sku_interno = c.sku_interno
            ORDER BY fecha_hora DESC LIMIT 1
        ) h ON TRUE
        WHERE c.estatus = 'ACTIVO'
    """)
    if df.empty:
        return df
    for col in ("precio_rival", "nuestro_precio", "precio_minimo", "precio_maximo", "costo_odoo"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    b = df["buybox"].fillna("").astype(str)
    df["estado"] = "Sin lectura"
    df.loc[b.str.startswith("¡Nosotros"), "estado"] = "Ganando"
    df.loc[b.str.startswith("Rival"), "estado"] = "Perdiendo"
    # fecha_hora se guarda en hora de CDMX (sin zona)
    ahora = datetime.now(CDMX).replace(tzinfo=None)
    df["edad_min"] = (ahora - pd.to_datetime(df["fecha_hora"])).dt.total_seconds() / 60
    return df


@st.cache_data(ttl=60, show_spinner=False)
def _tokens(_db) -> pd.DataFrame:
    return _db.execute_query("""SELECT id_cuenta, is_active, timestamp_token, token_expira_en
                                FROM cuentas_liverpool WHERE is_active = TRUE ORDER BY id_cuenta""")


def _humano(minutos: float) -> str:
    if minutos is None or pd.isna(minutos):
        return "—"
    if minutos < 60:
        return f"hace {int(minutos)} min"
    if minutos < 1440:
        return f"hace {minutos / 60:.1f} h"
    return f"hace {minutos / 1440:.1f} días"


def render():
    db = get_db()
    estilo.titulo("🏠 Centro de Mando")
    df = _estado_activos(db)
    if df.empty:
        st.warning("Sin datos de SKUs activos.")
        return

    activos = len(df)
    gan = int((df.estado == "Ganando").sum())
    per = int((df.estado == "Perdiendo").sum())
    sin = int((df.estado == "Sin lectura").sum())
    lecturas = gan + per
    pct = f"{gan / lecturas * 100:.0f}%" if lecturas else "—"
    ultima = df["edad_min"].min()
    salud_barrido = "ok" if ultima < 25 else ("warn" if ultima < 60 else "bad")

    # token (columnas en UTC)
    tk = _tokens(db)
    tok_val, tok_sub, tok_tono = "—", "", "info"
    if not tk.empty:
        exp = pd.to_datetime(tk["token_expira_en"]).min()
        if pd.notna(exp):
            restante = (exp - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() / 3600
            if restante <= 0:
                tok_val, tok_sub, tok_tono = "Vencido", "Captura un token nuevo", "bad"
            else:
                tok_val, tok_sub = f"{restante:.1f} h", "restantes del token"
                tok_tono = "ok" if restante > 6 else ("warn" if restante > 2 else "bad")

    c = st.columns(5)
    estilo.kpi(c[0], "SKUs activos", activos, f"{sin} sin lectura reciente", "info")
    estilo.kpi(c[1], "BuyBox ganado", pct, f"{gan} ganando · {per} perdiendo", "ok" if lecturas and gan / lecturas >= .6 else "warn")
    estilo.kpi(c[2], "Último barrido", _humano(ultima), "", salud_barrido)
    estilo.kpi(c[3], "Token Liverpool", tok_val, tok_sub, tok_tono)
    r9 = int(df["regla"].fillna("").str.startswith("9").sum())
    estilo.kpi(c[4], "Regla 9 activa", r9, "SKUs en Ruleta Rusa", "warn" if r9 else "info")

    # ---------------- atención
    estilo.titulo("⚠️ Requiere atención")
    perdiendo = df[df.estado == "Perdiendo"].copy()
    if not perdiendo.empty:
        perdiendo["diferencia"] = perdiendo["nuestro_precio"] - perdiendo["precio_rival"]
        perdiendo["se_puede_igualar"] = perdiendo["precio_rival"] >= perdiendo["precio_minimo"]
        perdiendo = perdiendo.sort_values("diferencia", ascending=False)
        st.markdown(estilo.chip(f"{len(perdiendo)} perdiendo BuyBox", "bad"), unsafe_allow_html=True)
        st.dataframe(
            perdiendo[["sku_limpio", "regla", "nuestro_precio", "precio_rival", "diferencia", "precio_minimo", "se_puede_igualar"]],
            hide_index=True, width="stretch", height=min(420, 40 + 35 * len(perdiendo)),
            column_config={
                "sku_limpio": "SKU", "regla": "Regla",
                "nuestro_precio": st.column_config.NumberColumn("Mi precio", format="$%.2f"),
                "precio_rival": st.column_config.NumberColumn("BuyBox rival", format="$%.2f"),
                "diferencia": st.column_config.NumberColumn("Me falta bajar", format="$%.2f"),
                "precio_minimo": st.column_config.NumberColumn("Mi mínimo", format="$%.2f"),
                "se_puede_igualar": st.column_config.CheckboxColumn("¿Puedo competir?", help="El rival está por arriba de mi mínimo"),
            })
    else:
        st.markdown(estilo.chip("Sin SKUs perdiendo BuyBox", "ok"), unsafe_allow_html=True)

    problemas = []
    sin_costo = df[(df.costo_odoo.fillna(0) <= 0)]
    if len(sin_costo):
        problemas.append(("warn", f"{len(sin_costo)} activos sin costo en Odoo: " + ", ".join(sin_costo.sku_limpio.astype(str).head(8))))
    viejos = df[(df.edad_min > 120) & (df.estado != "Sin lectura")]
    if len(viejos):
        problemas.append(("warn", f"{len(viejos)} SKUs sin lectura nueva en más de 2 horas"))
    sin_dato = df[df.estado == "Sin lectura"]
    if len(sin_dato):
        problemas.append(("info", f"{len(sin_dato)} SKUs sin lectura de BuyBox (ocultos, agotados o sin rivales)"))
    if ultima >= 60:
        problemas.append(("bad", "El bot lleva más de 1 hora sin escribir. Revisa GitHub Actions y el token."))
    for tono, msg in problemas:
        st.markdown(estilo.chip("Aviso", tono) + msg, unsafe_allow_html=True)

    # ---------------- reparto por regla
    estilo.titulo("🧭 SKUs activos por regla")
    por_regla = df.groupby("regla").agg(skus=("id", "count"),
                                        ganando=("estado", lambda s: int((s == "Ganando").sum())),
                                        perdiendo=("estado", lambda s: int((s == "Perdiendo").sum()))).reset_index()
    st.dataframe(por_regla, hide_index=True, width="stretch",
                 column_config={"regla": "Regla", "skus": "SKUs", "ganando": "Ganando", "perdiendo": "Perdiendo"})
    st.caption("Datos de las últimas lecturas del bot · se actualiza cada minuto.")
    if st.button("🔄 Actualizar ahora"):
        st.cache_data.clear()
        st.rerun()
