# Centro de Mando: estado general y "qué necesita atención hoy".
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from core import auth, estilo
from core.db import get_db
from core.finanzas import economia, escenario_baja
from core.odoo import cargar_nombres, describir
from modulos.catalogo_rapido import guardar_cambios

CDMX = ZoneInfo("America/Mexico_City")


@st.cache_data(ttl=60, show_spinner=False)
def _estado_activos(_db) -> pd.DataFrame:
    """Última lectura de cada SKU ACTIVO (usa el índice cuenta+sku+fecha)."""
    df = _db.execute_query("""
        SELECT c.id, c.sku_limpio, c.sku_interno, c.sku_liverpool, c.id_cuenta, c.regla_estrategia AS regla,
               c.precio_minimo, c.precio_maximo, c.costo_odoo, c.stock AS stock_cat,
               h.fecha_hora, h.precio_rival, h.nuestro_precio, h.posicion, h.buybox, h.stock AS stock_lectura
        FROM catalogo_maestro_v3 c
        LEFT JOIN LATERAL (
            SELECT fecha_hora, precio_rival, nuestro_precio, posicion, buybox, stock
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
    df["piezas"] = pd.to_numeric(df["stock_lectura"], errors="coerce")
    df["piezas"] = df["piezas"].fillna(pd.to_numeric(df["stock_cat"], errors="coerce")).fillna(0).astype(int)
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


def _tabla_perdiendo(db, df):
    perdiendo = df[df.estado == "Perdiendo"].copy()
    if perdiendo.empty:
        st.markdown(estilo.chip("Sin SKUs perdiendo BuyBox", "ok"), unsafe_allow_html=True)
        return

    f1, f2 = st.columns([1, 1])
    max_baja = f1.number_input("Hasta cuánto por debajo del BuyBox aceptaría ($)", min_value=1.0, max_value=500.0, value=15.0, step=1.0, key="cm_maxbaja",
                               help="Peor caso: quedar este monto por debajo del precio actual del BuyBox del rival.")
    solo_pzas = f2.toggle("Solo SKUs con piezas", value=True, key="cm_pzas")
    if solo_pzas:
        perdiendo = perdiendo[perdiendo.piezas > 0]
    if perdiendo.empty:
        st.markdown(estilo.chip("Los SKUs que pierden BuyBox no tienen piezas", "info"), unsafe_allow_html=True)
        return

    nombres = cargar_nombres(db)
    filas = []
    for r in perdiendo.itertuples():
        esc = escenario_baja(r.nuestro_precio, r.precio_rival, r.precio_minimo, max_baja)
        neto, gan, mar = economia(esc["precio"], r.costo_odoo)
        filas.append({
            "SKU": r.sku_limpio, "SKU Liverpool": str(r.sku_liverpool or ""), "Producto": describir(r.sku_limpio, nombres)["titulo"] if nombres else "—",
            "Piezas": r.piezas, "Mi precio": r.nuestro_precio, "BuyBox rival": r.precio_rival,
            "Peor caso (BuyBox − tope)": esc["precio"], "Baja vs mi precio": esc["baja"],
            "¿Bot puede ganar ya?": "✅ Sí" if esc["puede_ahora"] else "❌ Mínimo lo impide",
            "Utilidad / pieza": gan, "Utilidad %": mar,
            "Total a recibir": round(neto * r.piezas, 2) if neto is not None else None,
            "Utilidad / pérdida total": round(gan * r.piezas, 2) if gan is not None else None,
            "Mínimo": r.precio_minimo, "_id": int(r.id), "_regla": r.regla, "_max": r.precio_maximo,
            "_esc": esc, "_costo": r.costo_odoo,
        })
    tabla = pd.DataFrame(filas).sort_values("Utilidad / pérdida total", ascending=False, na_position="last").reset_index(drop=True)

    st.markdown(estilo.chip(f"{len(tabla)} perdiendo BuyBox", "bad"), unsafe_allow_html=True)
    pesos = lambda t: st.column_config.NumberColumn(t, format="dollar")
    visible = tabla.drop(columns=[c for c in tabla.columns if c.startswith("_")])
    sel = st.dataframe(
        visible, hide_index=True, width="stretch", height=min(480, 40 + 35 * len(visible)),
        on_select="rerun", selection_mode="single-row", key="cm_tabla",
        column_config={
            "Producto": st.column_config.TextColumn(width="medium"),
            "Piezas": st.column_config.NumberColumn(format="%d"),
            "Mi precio": pesos("Mi precio"), "BuyBox rival": pesos("BuyBox rival"),
            "Peor caso (BuyBox − tope)": pesos("Peor caso (BuyBox − tope)"), "Baja vs mi precio": pesos("Baja vs mi precio"),
            "Utilidad / pieza": pesos("Utilidad / pieza"),
            "Utilidad %": st.column_config.NumberColumn("Utilidad %", format="%.1f%%"),
            "Total a recibir": pesos("Total a recibir"),
            "Utilidad / pérdida total": pesos("Utilidad / pérdida total"),
            "Mínimo": pesos("Mínimo"),
        })
    total_util = tabla["Utilidad / pérdida total"].sum(skipna=True)
    st.caption(estilo.d(f"Peor caso en los {len(tabla)} SKUs (quedando ${max_baja:,.0f} abajo del BuyBox): total a recibir "
                        f"${tabla['Total a recibir'].sum(skipna=True):,.2f} · utilidad/pérdida ${total_util:,.2f}. "
                        "Utilidad con la fórmula del bot (comisión 17%, envío $130, retenciones). "
                        "Selecciona una fila para evaluar."))

    filas_sel = sel.selection.rows if sel and sel.selection else []
    if filas_sel:
        fila = tabla.iloc[filas_sel[0]]
        if auth.es_admin():
            if st.button(f"🤝 ¿Puedo competir? · evaluar {fila['SKU']}", type="primary", key="cm_btn_comp"):
                _dialogo_competir(db, fila.to_dict(), max_baja)
        else:
            st.info("Solo el administrador puede aprobar bajas.")


@st.dialog("¿Estás de acuerdo con esta baja?")
def _dialogo_competir(db, f, max_baja):
    esc = f["_esc"]
    st.markdown(f"**{f['SKU']}** · {f['Producto']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Mi precio hoy", f"${f['Mi precio']:,.2f}")
    c2.metric("BuyBox rival", f"${f['BuyBox rival']:,.2f}")
    c3.metric("Peor caso", f"${esc['precio']:,.2f}", delta=f"-${max_baja:,.0f} vs BuyBox", delta_color="off")
    gan, mar, pzs = f["Utilidad / pieza"], f["Utilidad %"], int(f["Piezas"])
    pierde = False
    if gan is None or pd.isna(gan):
        st.warning("Este SKU no tiene costo en Odoo: no puedo calcular la utilidad.")
    elif gan < 0:
        pierde = True
        st.error(estilo.d(f"En el peor caso pierdes ${abs(gan):,.2f} por pieza ({mar:.1f}%). Con {pzs} piezas: pérdida de ${abs(f['Utilidad / pérdida total']):,.2f}."))
    else:
        st.success(estilo.d(f"En el peor caso ganas ${gan:,.2f} por pieza ({mar:.1f}%). Con {pzs} piezas: utilidad de ${f['Utilidad / pérdida total']:,.2f} "
                            f"y recibes ${f['Total a recibir']:,.2f}."))

    minimo = esc["minimo_actual"]
    necesita = not esc["puede_ahora"]
    if necesita:
        st.warning(estilo.d(f"Hoy tu mínimo (${minimo:,.2f}) está por arriba del rival y el bot no puede ganarle. "
                            f"Si apruebas, el mínimo pasa a ${esc['precio']:,.2f}: el bot podrá bajar hasta ahí, "
                            "aunque normalmente se queda cerca del precio del rival."))
    elif esc["precio"] < minimo:
        st.info(estilo.d(f"El bot ya puede ganar. Se detendrá en tu mínimo (${minimo:,.2f}), que está por arriba de este peor caso. "
                         "No hace falta cambiar nada."))
    else:
        st.info("El bot ya puede ganar y tu mínimo cubre este peor caso. No hace falta cambiar nada.")

    entiende = True
    if necesita and pierde:
        entiende = st.checkbox("Entiendo que podría vender con pérdida", key="cm_ok_perdida")
    a_, b_ = st.columns(2)
    if a_.button("✅ Sí, estoy de acuerdo", type="primary", disabled=(not necesita) or (not entiende), width="stretch"):
        antes = {"estatus": "ACTIVO", "regla": f["_regla"], "precio_minimo": round(minimo, 2), "precio_maximo": round(float(f["_max"]), 2)}
        despues = dict(antes, precio_minimo=round(float(esc["precio"]), 2))
        cambio = {"id": int(f["_id"]), "sku": f["SKU"], "costo": float(f["_costo"] or 0), "antes": antes, "despues": despues}
        ok, msg = guardar_cambios(db, [cambio], "admin (Centro de Mando: competir)")
        if ok:
            st.cache_data.clear()
            st.toast("✅ Mínimo actualizado. El bot competirá en su próxima corrida.")
            st.rerun()
        else:
            st.error(msg)
    if b_.button("Cancelar", width="stretch"):
        st.rerun()


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
    _tabla_perdiendo(db, df)

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
