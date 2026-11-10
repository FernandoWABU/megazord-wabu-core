#!/usr/bin/env python3
"""
PRUEBA: stock del vendedor con la BuyBox, por el método del carrito (sin sesión, como invitado).

Uso:
    python prueba_stock_buybox.py                    # usa los SKUs de prueba
    python prueba_stock_buybox.py 1190647591 1131319611

Qué hace por cada SKU:
  1) GET offerListing  -> toma las cookies de invitado y lee la oferta ganadora (bestOffer)
  2) POST /web-bff/cart/items  -> agrega 1 pieza de ESE vendedor
  3) PATCH /web-bff/cart/items/{id} {"quantity": N}  -> duplica hasta que Liverpool rechace
     ("CartInventoryNotAvailableRequestError") y luego afina (búsqueda binaria)
  4) DELETE de la línea  -> deja la bolsa vacía (se ejecuta SIEMPRE, aunque algo falle)

NO compra nada, NO llega a pago, NO usa cuenta ni contraseña.
Solo necesita:  pip install requests
"""
import json
import random
import re
import sys
import time

import requests

BASE = "https://www.liverpool.com.mx"
SKUS_PRUEBA = ["1190647591", "1131319611", "1114048565", "1193494401"]
TOPE = 2048          # por seguridad: no pasamos de aquí
PAUSA = 0.25         # segundos entre llamadas dentro de un SKU (se le suma un poco al azar)
PAUSA_ENTRE_SKU = (4, 9)   # segundos al azar entre un SKU y el siguiente
MAX_SKUS_POR_CORRIDA = 40  # tope duro por corrida
BLOQUEO_HTTP = (403, 429, 503)   # si aparece cualquiera de estos: ALTO TOTAL


class Bloqueo(Exception):
    """Liverpool nos está frenando (403/429/captcha). Se detiene TODO, sin reintentar."""


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
H_HTML = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9",
}
H_API = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-MX,es;q=0.9",
    "x-brand-id": "LP",
    "Origin": BASE,
}


# ---------------------------------------------------------------- parseo
_RE_OFERTA = re.compile(
    r'"offerId":"(\d+)","sellerId":"(\d+)","sellerName":"([^"]*)".*?"salePrice":([\d.]+)',
    re.S,
)


def leer_buybox(html: str):
    """Devuelve (offerId, sellerId, sellerName, precio) de la oferta ganadora, o None."""
    h = html.replace('\\"', '"').replace("\\\\", "\\")

    # 1) bestOffer explícito
    i = h.find('"bestOffer":{')
    if i != -1:
        m = _RE_OFERTA.search(h[i:i + 1500])
        if m:
            return m.group(1), m.group(2), m.group(3), float(m.group(4))

    # 2) si no hay bestOffer: la de menor precio entre las ofertas listadas
    j = h.find('"offers":[{"offerId"')
    if j != -1:
        bloque = h[j:j + 20000]
        trozos = bloque.split('{"offerId":"')[1:]
        ofertas = []
        for t in trozos:
            m = _RE_OFERTA.search('"offerId":"' + t[:1200])
            if m:
                ofertas.append((m.group(1), m.group(2), m.group(3), float(m.group(4))))
        if ofertas:
            return min(ofertas, key=lambda o: o[3])
    return None


# ---------------------------------------------------------------- carrito
def medir_stock(sku: str, sesion: requests.Session):
    t0 = time.time()
    res = {"sku": sku, "vendedor": None, "precio": None, "stock": None,
           "llamadas": 0, "segundos": None, "estado": None}
    linea_id = None

    def api(metodo, ruta, **kw):
        res["llamadas"] += 1
        time.sleep(PAUSA + random.random() * 0.25)
        rr = sesion.request(metodo, BASE + ruta, headers=kw.pop("headers", H_API), timeout=20, **kw)
        if rr.status_code in BLOQUEO_HTTP:
            raise Bloqueo(f"HTTP {rr.status_code} en {ruta.split('?')[0]}")
        return rr

    try:
        # 1) página de ofertas (cookies de invitado + oferta ganadora)
        url = f"{BASE}/tienda/mirakl/offerListing?productId={sku}&skuId={sku}"
        r = sesion.get(url, headers=H_HTML, timeout=25)
        if r.status_code in BLOQUEO_HTTP or "Access Denied" in r.text[:2000] or "captcha" in r.text[:5000].lower():
            raise Bloqueo(f"offerListing HTTP {r.status_code} / posible captcha")
        if r.status_code != 200:
            res["estado"] = f"offerListing HTTP {r.status_code}"
            return res
        bb = leer_buybox(r.text)
        if not bb:
            res["estado"] = "no se pudo leer la oferta ganadora"
            return res
        offer_id, seller_id, seller_name, precio = bb
        res["vendedor"], res["precio"] = seller_name, precio

        # 1b) token de invitado: Liverpool lo entrega como cookie (HttpOnly) en este endpoint
        api("GET", "/auth-service/v2/auth/anonymous?redirect=false")

        # 2) agregar 1 pieza de ese vendedor
        def agregar():
            return api("POST", "/web-bff/cart/items",
                       headers={**H_API, "content-type": "application/json"},
                       data=json.dumps({"id": sku, "sku": sku, "quantity": 1,
                                        "offerId": offer_id, "sellerId": seller_id}))

        r = agregar()
        if r.status_code == 401:      # token no tomado: pedir otro y reintentar una vez
            api("GET", "/auth-service/v2/auth/anonymous?redirect=false")
            r = agregar()
        if r.status_code not in (200, 201):
            try:
                code = r.json().get("code")
            except Exception:
                code = ""
            res["estado"] = f"NO MEDIBLE: no deja agregar (HTTP {r.status_code} {code})"
            return res
        for li in r.json().get("lineItems", []):
            if str(li.get("sku")) == sku:
                linea_id = li["id"]
        if not linea_id:
            res["estado"] = "agregó pero no se encontró la línea"
            return res

        # 3) cantidad aceptada?
        def acepta(q):
            rr = api("PATCH", f"/web-bff/cart/items/{linea_id}",
                     headers={**H_API, "content-type": "application/json"},
                     data=json.dumps({"quantity": q}))
            return rr.status_code == 200

        lo, hi = 1, 2
        while hi <= TOPE and acepta(hi):
            lo, hi = hi, hi * 2
        if hi > TOPE:
            res["stock"], res["estado"] = lo, f"OK (>= {lo}, tope de seguridad)"
        else:
            while hi - lo > 1:
                m = (lo + hi) // 2
                if acepta(m):
                    lo = m
                else:
                    hi = m
            res["stock"], res["estado"] = lo, "OK"
        return res

    except Bloqueo:
        raise
    except Exception as e:  # noqa: BLE001
        res["estado"] = f"error: {e}"
        return res
    finally:
        # 4) limpiar SIEMPRE (DELETE sin content-type: con él Liverpool responde 400)
        try:
            ids = []
            if linea_id:
                ids = [linea_id]
            else:
                c = sesion.get(BASE + "/web-bff/cart", headers=H_API, timeout=20).json()
                ids = [li["id"] for li in c.get("lineItems", [])]
            for i in ids:
                sesion.delete(BASE + f"/web-bff/cart/items?lineItemIds={i}", headers=H_API, timeout=20)
        except Exception:
            pass
        res["segundos"] = round(time.time() - t0, 1)


def main():
    import os
    skus = sys.argv[1:]
    if not skus and os.environ.get("SKUS"):
        skus = [x.strip() for x in re.split(r"[,\s]+", os.environ["SKUS"]) if x.strip()]
    skus = (skus or SKUS_PRUEBA)[:MAX_SKUS_POR_CORRIDA]
    print("%-12s%-26s%9s%8s%7s%7s  %s" % ("SKU", "Vendedor BuyBox", "Precio", "Stock", "Llam.", "Seg.", "Estado"))
    print("-" * 100)
    hechos = 0
    for n, sku in enumerate(skus):
        if n:
            time.sleep(random.uniform(*PAUSA_ENTRE_SKU))
        s = requests.Session()   # sesión de invitado nueva por SKU
        try:
            r = medir_stock(sku, s)
        except Bloqueo as e:
            print("-" * 100)
            print("ALTO TOTAL: Liverpool nos esta frenando (%s)." % e)
            print("Medidos antes del freno: %d de %d. No se reintenta; se espera a la siguiente corrida." % (hechos, len(skus)))
            sys.exit(2)
        hechos += 1
        precio = "%.2f" % r["precio"] if r["precio"] else "-"
        stock = str(r["stock"]) if r["stock"] is not None else "-"
        vend = (r["vendedor"] or "-")[:24]
        print("%-12s%-26s%9s%8s%7s%7s  %s" % (r["sku"], vend, precio, stock,
                                                r["llamadas"], r["segundos"] or 0, r["estado"]))
    print("-" * 100)
    print("Listo: %d SKUs medidos, sin bloqueo." % hechos)


if __name__ == "__main__":
    main()
