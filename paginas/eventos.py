# Eventos (Buen Fin / Hot Sale): control del modo evento y seguimiento del piloto de Regla 9.
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from core import estilo
from core.db import get_db
from modulos.catalogo_rapido import cargar_catalogo, panel_panico

CDMX = ZoneInfo("America/Mexico_City")


@st.cache_data(ttl=60, show_spinner=False)
def _piloto_hoy(_db) -> pd.DataFrame:
    hoy = datetime.now(CDMX).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    df = _db.execute_query("""
        SELECT c.id AS cid, c.sku_limpio, c.precio_minimo, c.precio_maximo,
               h.fecha_hora, h.nuestro_precio, h.precio_rival, h.buybox
        FROM catalogo_maestro_v3 c
        JOIN historial_precios h ON h.id_cuenta = c.id_cuenta AND h.sku_interno = c.sku_interno
        WHERE c.estatus = 'ACTIVO' AND LEFT(c.regla_estrategia, 1) = '9' AND h.fecha_hora >= :hoy
        ORDER BY h.fecha_hora""", {"hoy": hoy})
    return df


def _resumen(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for c in ("nuestro_precio", "precio_rival", "precio_minimo", "precio_maximo"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    filas = []
    for (cid, sku), g in df.groupby(["cid", "sku_limpio"]):
        p = g.dropna(subset=["nuestro_precio"])
        if p.empty:
            continue
        ini, act = float(p.nuestro_precio.iloc[0]), float(p.nuestro_precio.iloc[-1])
        pmin = float(g.precio_minimo.iloc[0])
        b = g["buybox"].fillna("").astype(str)
        filas.append({
            "SKU": sku,
            "Inicio del día": ini, "Ahora": act,
            "Caída %": round((act - ini) / ini * 100, 2) if ini else 0.0,
            "Hachazos": int(b.str.contains("Hachazo").sum()),
            "Cambios": int((p.nuestro_precio.diff().fillna(0) != 0).sum()),
            "Ganando %": round(b.str.startswith("¡Nosotros").mean() * 100, 0),
            "Mínimo": pmin,
            "Sobre el piso %": round((act - pmin) / pmin * 100, 1) if pmin else None,
        })
    return pd.DataFrame(filas).sort_values("Caída %")


def render():
    db = get_db()
    estilo.titulo("🎯 Eventos · Buen Fin")
    ahora = datetime.now(CDMX)

    # ---- cuenta regresiva al corte (informativa; la hora real se configura en GitHub)
    c1, c2 = st.columns([1, 2])
    corte = c1.time_input("Hora de corte (CDMX)", value=datetime.strptime("17:50", "%H:%M").time(), key="ev_corte",
                          help="Debe coincidir con la variable REGLA9_HORA_CORTE en GitHub.")
    objetivo = ahora.replace(hour=corte.hour, minute=corte.minute, second=0, microsecond=0)
    if objetivo < ahora:
        objetivo += timedelta(days=1)
    falta = objetivo - ahora
    h, m = divmod(int(falta.total_seconds() // 60), 60)
    kk = c2.columns(2)
    estilo.kpi(kk[0], "Próximo corte", f"{h} h {m:02d} min", f"a las {corte.strftime('%H:%M')}", "warn" if falta < timedelta(hours=3) else "info")
    estilo.kpi(kk[1], "Hora actual (CDMX)", ahora.strftime("%H:%M"), ahora.strftime("%A %d/%m"), "info")

    with st.expander("⚙️ Cómo encender / apagar el modo evento"):
        st.markdown("En GitHub: **Settings → Secrets and variables → Actions → Variables**. No hace falta tocar código.")
        st.code("REGLA9_MODO_EVENTO = 1\nREGLA9_PASO_PCT    = 0.012\nREGLA9_DADO        = 9\nREGLA9_HORA_CORTE  = 17:50", language="text")
        st.caption("Para apagarlo: REGLA9_MODO_EVENTO = 0. El bot toma el cambio en la siguiente corrida.")

    # ---- piloto
    estilo.titulo("🎲 Piloto Regla 9 · hoy")
    res = _resumen(_piloto_hoy(db))
    if res.empty:
        st.info("Todavía no hay SKUs activos con Regla 9 con lecturas hoy. Asígnalos desde Catálogo.")
    else:
        k = st.columns(4)
        estilo.kpi(k[0], "SKUs piloto", len(res), "con Regla 9", "info")
        estilo.kpi(k[1], "Hachazos hoy", int(res["Hachazos"].sum()), "bajadas aleatorias", "warn")
        estilo.kpi(k[2], "Caída promedio", f"{res['Caída %'].mean():.2f}%", "vs. inicio del día", "info")
        cerca = int((res["Sobre el piso %"].fillna(99) < 5).sum())
        estilo.kpi(k[3], "Cerca del piso", cerca, "a menos de 5% del mínimo", "bad" if cerca else "ok")
        st.dataframe(res, hide_index=True, width="stretch", column_config={
            "Inicio del día": st.column_config.NumberColumn(format="$%.2f"),
            "Ahora": st.column_config.NumberColumn(format="$%.2f"),
            "Mínimo": st.column_config.NumberColumn(format="$%.2f"),
            "Caída %": st.column_config.NumberColumn(format="%.2f%%"),
            "Sobre el piso %": st.column_config.NumberColumn(format="%.1f%%"),
            "Ganando %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
        })
        st.caption("Si 'Cerca del piso' sube rápido, sube el mínimo de esos SKUs o regresa a Gladiador.")

    # ---- checklist
    estilo.titulo("✅ Antes del evento")
    for i, t in enumerate([
        "Mínimo y máximo definidos en cada SKU piloto (con utilidad positiva al mínimo)",
        "Bot actualizado en GitHub con la Regla 9 nueva (doble check y corte horario)",
        "Variables REGLA9_* cargadas en GitHub y probadas con 5 SKUs al menos 2 días",
        "Token de Liverpool capturado y con más de 12 h de vida el día del corte",
        "Telegram avisando (probar una alerta)",
        "Hora de corte real confirmada",
    ]):
        st.checkbox(t, key=f"ev_chk_{i}")

    # ---- pánico
    estilo.titulo("🛑 Emergencia")
    panel_panico(db, cargar_catalogo(db), "admin")
