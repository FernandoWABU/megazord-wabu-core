# Cálculos de rentabilidad: misma fórmula que calcular_rentabilidad() del bot.
COMISION = 0.17      # comisión Liverpool
ENVIO = 130.0        # envío fijo por pieza
RETENCION = 0.105    # sobre el precio sin IVA
IVA = 1.16


def economia(precio, costo):
    """Por pieza: (ingreso_neto, ganancia, margen_pct). Devuelve None en ganancia/margen si no hay costo."""
    try:
        precio, costo = float(precio), float(costo or 0)
    except (TypeError, ValueError):
        return None, None, None
    if precio <= 0:
        return None, None, None
    neto = precio - precio * COMISION - ENVIO - (precio / IVA) * RETENCION
    if costo <= 0:
        return round(neto, 2), None, None
    costo_iva = costo * IVA
    ganancia = neto - costo_iva
    return round(neto, 2), round(ganancia, 2), round(ganancia / costo_iva * 100, 1)


def escenario_baja(precio_actual, precio_rival, precio_minimo, max_baja=15.0):
    """Peor caso aceptado para competir: quedar hasta `max_baja` pesos por DEBAJO del BuyBox del rival.
    - piso: el precio más bajo que aceptaría (BuyBox - tope).
    - puede_ahora: el mínimo actual ya deja al bot ponerse por debajo del rival.
    - baja: cuánto bajaría mi precio actual para llegar al piso."""
    piso = round(max(float(precio_rival) - float(max_baja), 0.01), 2)
    puede_ahora = float(precio_minimo or 0) < float(precio_rival)
    return {"precio": piso, "baja": round(float(precio_actual) - piso, 2),
            "puede_ahora": puede_ahora, "minimo_actual": float(precio_minimo or 0)}
