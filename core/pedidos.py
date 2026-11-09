# Pedidos de Liverpool (reporte "OrderReport" del Seller Center) -> tabla pedidos_liverpool.
# Solo se guardan columnas de venta; NO se guardan datos del cliente (nombre, dirección, teléfono).
import pandas as pd
import streamlit as st
from sqlalchemy import text

COLUMNAS = {
    "Fecha de creación": "fecha", "Id del pedido": "id_pedido", "Estado": "estado", "No de SKU": "sku_liverpool",
    "SKU de la oferta": "sku_oferta", "Cantidad": "cantidad", "Precio por unidad": "precio_unit",
    "Fulfillment (Si/No)": "fulfillment", "Piezas devueltas por indicador": "piezas_dev", "Nombre del producto": "producto",
}
ESTADOS_SIN_VENTA = ("Cancelado", "Rechazado")

DDL = """CREATE TABLE IF NOT EXISTS pedidos_liverpool (
    id_pedido TEXT NOT NULL, sku_liverpool TEXT NOT NULL, sku_oferta TEXT NOT NULL DEFAULT '',
    fecha TIMESTAMP, estado TEXT, cantidad INT, precio_unit NUMERIC, fulfillment TEXT, piezas_dev INT DEFAULT 0, producto TEXT,
    cargado TIMESTAMP DEFAULT NOW(), PRIMARY KEY (id_pedido, sku_liverpool, sku_oferta))"""


def parse_reporte(archivo) -> pd.DataFrame:
    """Lee el .xlsx del reporte y devuelve solo las columnas de venta, ya limpias."""
    raw = pd.read_excel(archivo, dtype={"No de SKU": str, "Id del pedido": str})
    faltan = [c for c in COLUMNAS if c not in raw.columns]
    if faltan:
        raise ValueError("Al reporte le faltan columnas: " + ", ".join(faltan))
    df = raw[list(COLUMNAS)].rename(columns=COLUMNAS).copy()
    f = df["fecha"].astype(str).str.replace(" - ", " ", regex=False).str.replace(r"(?i)\s*a\.?\s*m\.?", " AM", regex=True) \
        .str.replace(r"(?i)\s*p\.?\s*m\.?", " PM", regex=True)
    df["fecha"] = pd.to_datetime(f, format="%d/%m/%Y %I:%M %p", errors="coerce")
    df["sku_liverpool"] = df["sku_liverpool"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    df["sku_oferta"] = df["sku_oferta"].fillna("").astype(str).str.strip()
    df["id_pedido"] = df["id_pedido"].astype(str).str.strip()
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0).astype(int)
    df["piezas_dev"] = pd.to_numeric(df["piezas_dev"], errors="coerce").fillna(0).astype(int)
    df["precio_unit"] = pd.to_numeric(df["precio_unit"], errors="coerce")
    df["fulfillment"] = df["fulfillment"].fillna("").astype(str)
    df = df[df.fecha.notna() & (df.id_pedido != "") & (df.sku_liverpool != "")]
    return df.drop_duplicates(["id_pedido", "sku_liverpool", "sku_oferta"])


def guardar_pedidos(db, df: pd.DataFrame):
    """Inserta/actualiza (por pedido+SKU). Devuelve (ok, mensaje)."""
    if db.engine is None:
        return False, "Sin conexión a la base."
    filas = [{**r, "fecha": r["fecha"].to_pydatetime(), "precio_unit": None if pd.isna(r["precio_unit"]) else float(r["precio_unit"])}
             for r in df.to_dict("records")]
    try:
        with db.engine.begin() as conn:
            conn.execute(text(DDL))
            conn.execute(text("""INSERT INTO pedidos_liverpool
                (id_pedido, sku_liverpool, sku_oferta, fecha, estado, cantidad, precio_unit, fulfillment, piezas_dev, producto)
                VALUES (:id_pedido, :sku_liverpool, :sku_oferta, :fecha, :estado, :cantidad, :precio_unit, :fulfillment, :piezas_dev, :producto)
                ON CONFLICT (id_pedido, sku_liverpool, sku_oferta) DO UPDATE SET
                  fecha = EXCLUDED.fecha, estado = EXCLUDED.estado, cantidad = EXCLUDED.cantidad, precio_unit = EXCLUDED.precio_unit,
                  fulfillment = EXCLUDED.fulfillment, piezas_dev = EXCLUDED.piezas_dev, producto = EXCLUDED.producto, cargado = NOW()"""),
                filas)
        return True, f"{len(filas)} líneas de pedido guardadas ({df.fecha.min():%d/%m/%Y} a {df.fecha.max():%d/%m/%Y})."
    except Exception as e:
        return False, f"No se pudo guardar: {str(e)[:160]}"


@st.cache_data(ttl=300, show_spinner=False)
def cargar_pedidos(_db) -> pd.DataFrame:
    """Líneas de pedido sin cancelados; unidades netas = cantidad - devueltas."""
    df = _db.execute_query("""SELECT fecha, sku_liverpool, sku_oferta, estado, cantidad, piezas_dev, precio_unit, fulfillment
                              FROM pedidos_liverpool""", silencioso=True)
    if df is None or df.empty:
        return pd.DataFrame()
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df[~df.estado.isin(ESTADOS_SIN_VENTA)].copy()
    df["netas"] = (pd.to_numeric(df.cantidad) - pd.to_numeric(df.piezas_dev)).clip(lower=0)
    return df
