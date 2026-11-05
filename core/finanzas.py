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


def escenario_baja(precio_actual, precio_rival, precio_minimo, max_baja=15.0, rebaja_vs_rival=1.50):
    """Precio al que bajaríamos para tomar el BuyBox, respetando el mínimo y un tope de baja.
    Devuelve dict(precio, baja, alcanza, limite) con limite en {'ok', 'tope', 'minimo'}."""
    ideal = round(precio_rival - rebaja_vs_rival, 2)
    piso_tope = round(precio_actual - max_baja, 2)
    precio = max(ideal, piso_tope, float(precio_minimo or 0))
    precio = round(min(precio, precio_actual), 2)
    alcanza = precio < precio_rival
    if alcanza:
        limite = "ok"
    elif ideal < float(precio_minimo or 0):
        limite = "minimo"   # ni sin tope de baja se podría ganar: el mínimo está por arriba
    else:
        limite = "tope"
    return {"precio": precio, "baja": round(precio_actual - precio, 2), "alcanza": alcanza, "limite": limite}
