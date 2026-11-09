# Nombres reales de productos desde la tabla odoo_productos (la llena sincronizar_odoo.py dos veces al día).
import pandas as pd
import streamlit as st


@st.cache_data(ttl=600, show_spinner=False)
def cargar_nombres(_db) -> dict:
    """{CODIGO_ODOO: nombre}. Vacío si la tabla todavía no existe."""
    df = _db.execute_query("SELECT default_code, nombre FROM odoo_productos", silencioso=True)
    if df is None or df.empty:
        return {}
    return {str(c).strip().upper(): str(n) for c, n in zip(df.default_code, df.nombre)}


def descomponer(sku_limpio: str):
    """'HNAU' -> ('simple', [('HNAU',1)]) · 'HNAU/2' -> ('paquete', [('HNAU',2)]) · 'A/B' -> ('combo', [('A',1),('B',1)])."""
    partes = [p.strip().upper() for p in str(sku_limpio or "").split("/") if p.strip()]
    if not partes:
        return "simple", []
    if len(partes) == 2 and partes[1].isdigit():
        return "paquete", [(partes[0], int(partes[1]))]
    if len(partes) == 1:
        return "simple", [(partes[0], 1)]
    return "combo", [(p, 1) for p in partes]


def describir(sku_limpio: str, nombres: dict) -> dict:
    """titulo: nombre legible · referencia: códigos Odoo reales · faltan: códigos que no están en Odoo."""
    tipo, items = descomponer(sku_limpio)
    if not items:
        return {"tipo": tipo, "titulo": "—", "referencia": "—", "faltan": []}
    faltan = [c for c, _ in items if c not in nombres]
    if not nombres:
        return {"tipo": tipo, "titulo": "Sin nombres cargados todavía", "referencia": _ref(tipo, items), "faltan": [c for c, _ in items]}
    if tipo == "paquete":
        c, n = items[0]
        titulo = f"{n} × {nombres.get(c, c + ' (no está en Odoo)')}"
    elif tipo == "combo":
        titulo = " + ".join(nombres.get(c, f"{c} (no está en Odoo)") for c, _ in items)
    else:
        c = items[0][0]
        titulo = nombres.get(c, f"{c} (no está en Odoo)")
    return {"tipo": tipo, "titulo": titulo, "referencia": _ref(tipo, items), "faltan": faltan}


def _ref(tipo, items):
    if tipo == "paquete":
        return f"Paquete de {items[0][1]} piezas del código Odoo {items[0][0]}"
    if tipo == "combo":
        return "Combo de los códigos Odoo " + " + ".join(c for c, _ in items)
    return f"Código Odoo {items[0][0]}"


# ---- Stock por almacén (tabla odoo_stock, la llena sincronizar_odoo.py) ----
ALMACENES_CONTAR = ["01", "COPPEL", "MELI", "PRIVALIA", "WALMART", "WEB"]                       # <nombre>/EXISTENCIAS
ALMACENES_IGNORAR = ["MALTRATADO", "MERMA", "VENCO", "MELIFULL", "LIVFULL"]


def _almacen(ubicacion: str) -> str:
    """'WH/MELI/Existencias' -> 'MELI' (toma el penúltimo tramo si el último es EXISTENCIAS)."""
    partes = [p.strip().upper() for p in str(ubicacion or "").split("/") if p.strip()]
    if len(partes) >= 2 and partes[-1] == "EXISTENCIAS":
        return partes[-2]
    return partes[-1] if partes else ""


@st.cache_data(ttl=600, show_spinner=False)
def cargar_stock(_db) -> pd.DataFrame:
    """Filas: default_code, almacen, cantidad (solo ubicaciones internas con nombre reconocible). Vacío si no existe la tabla."""
    df = _db.execute_query("SELECT default_code, ubicacion, cantidad FROM odoo_stock", silencioso=True)
    if df is None or df.empty:
        return pd.DataFrame(columns=["default_code", "almacen", "cantidad"])
    df["default_code"] = df.default_code.astype(str).str.strip().str.upper()
    df["almacen"] = df.ubicacion.apply(_almacen)
    df["cantidad"] = pd.to_numeric(df.cantidad, errors="coerce").fillna(0.0)
    return df[["default_code", "almacen", "cantidad"]]


def unidades_disponibles(sku_limpio: str, stock_codigo: dict) -> int:
    """Cuántas unidades vendibles del SKU salen de las piezas sueltas: HNAU/2 con 5 piezas = 2 paquetes; combo = mínimo de sus partes."""
    _, items = descomponer(sku_limpio)
    if not items:
        return 0
    return int(max(0, min(int(stock_codigo.get(c, 0) // n) for c, n in items)))
