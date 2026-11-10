#!/usr/bin/env python3
"""
MÓDULO APARTE: stock del vendedor que tiene la BuyBox (método del carrito, como invitado).

NO toca el barrido de 12 minutos. Se ejecuta solo cuando alguien lo pide
(workflow "Medir stock BuyBox", disparado a mano o desde el botón del dashboard).

Qué mide:  solo SKUs donde el rival tiene la BuyBox y nosotros tenemos piezas
           (los de "Requiere atención"), y solo contra el vendedor que la tiene.
Qué NO hace: no compra, no llega a pago, no usa cuenta ni contraseña.

Variables de entorno:
  DATABASE_URL   (obligatoria)  base PostgreSQL
  SKUS           (opcional)     sku_liverpool separados por coma; vacío = automático (los que pierden BuyBox)
  LOTE           (opcional)     máximo de SKUs por corrida            [12]
  MIN_HORAS      (opcional)     no re-medir un SKU medido hace menos de estas horas   [2]
  FORZAR         (opcional)     "1" = ignora MIN_HORAS
  MODO_PRUEBA    (opcional)     "1" = no escribe en la base, solo imprime

Frenos para NO ser bloqueados:
  - 403 / 429 / 503 / captcha  -> ALTO TOTAL inmediato (no reintenta) y deja una marca de bloqueo en la base
  - si hay marca de bloqueo de hace menos de HORAS_BLOQUEO (3 h), la corrida ni siquiera empieza
  - pausas al azar entre llamadas y entre SKUs; tope de SKUs por corrida
"""
import json
import os
import random
import re
import sys
import time

import requests

BASE = "https://www.liverpool.com.mx"
TOPE_PIEZAS = 2048
PAUSA = 0.25
PAUSA_ENTRE_SKU = (4, 9)
BLOQUEO_HTTP = (403, 429, 503)
HORAS_BLOQUEO = 3
LOTE_MAX = 40
NOMBRES_PROPIOS = ("PRECIO GENIAL", "PRECIOS UNICOS", "WABU", "WABU SHOP")
MARCA_BLOQUEO = "__BLOQUEO__"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
H_HTML = {"User-Agent": UA,
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "Accept-Language": "es-MX,es;q=0.9"}
H_API = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
         "Accept-Language": "es-MX,es;q=0.9", "x-brand-id": "LP", "Origin": BASE}


class Bloqueo(Exception):
    """Liverpool nos está frenando. Se detiene TODO, sin reintentar."""


# ------------------------------------------------------------------ base de datos
def conectar():
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"])


DDL = """
CREATE TABLE IF NOT EXISTS stock_buybox (
    id            BIGSERIAL PRIMARY KEY,
    sku_liverpool TEXT NOT NULL,
    vendedor      TEXT,
    precio        NUMERIC(12,2),
    stock         INTEGER,
    estado        TEXT,
    llamadas      INTEGER,
    segundos      NUMERIC(6,1),
    medido_en     TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'America/Mexico_City')
);
CREATE INDEX IF NOT EXISTS ix_stock_buybox_sku_fecha ON stock_buybox (sku_liverpool, medido_en DESC);
"""


def preparar_tabla(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def bloqueo_reciente(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("""SELECT 1 FROM stock_buybox
                       WHERE sku_liverpool = %s
                         AND medido_en > (now() AT TIME ZONE 'America/Mexico_City') - (%s || ' hours')::interval
                       LIMIT 1""", (MARCA_BLOQUEO, str(HORAS_BLOQUEO)))
        return cur.fetchone() is not None


def elegir_skus(conn, lote: int, min_horas: float, forzar: bool, explicitos):
    """SKUs a medir. Automático = los que hoy pierden BuyBox y tienen piezas
    (misma lógica que la tabla 'Requiere atención'), los menos recientemente medidos primero."""
    with conn.cursor() as cur:
        if explicitos:
            cur.execute("""SELECT x.sku, m.ultima
                           FROM unnest(%s::text[]) AS x(sku)
                           LEFT JOIN (SELECT sku_liverpool, max(medido_en) AS ultima
                                      FROM stock_buybox GROUP BY 1) m ON m.sku_liverpool = x.sku""",
                        (list(dict.fromkeys(explicitos)),))
        else:
            cur.execute("""
                WITH ult AS (
                    SELECT DISTINCT ON (c.sku_liverpool) c.sku_liverpool AS sku
                    FROM catalogo_maestro_v3 c
                    JOIN LATERAL (
                        SELECT buybox, stock FROM historial_precios h
                        WHERE h.id_cuenta = c.id_cuenta AND h.sku_interno = c.sku_interno
                        ORDER BY fecha_hora DESC LIMIT 1
                    ) h ON TRUE
                    WHERE c.estatus = 'ACTIVO'
                      AND COALESCE(c.sku_liverpool, '') <> ''
                      AND COALESCE(h.buybox, '') LIKE 'Rival%'
                      AND COALESCE(NULLIF(regexp_replace(COALESCE(h.stock::text, ''), '[^0-9]', '', 'g'), '')::int,
                                   NULLIF(regexp_replace(COALESCE(c.stock::text, ''), '[^0-9]', '', 'g'), '')::int, 0) > 0
                )
                SELECT u.sku, m.ultima FROM ult u
                LEFT JOIN (SELECT sku_liverpool, max(medido_en) AS ultima
                           FROM stock_buybox GROUP BY 1) m ON m.sku_liverpool = u.sku""")
        filas = cur.fetchall()

    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    ahora = datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)
    umbral = ahora - timedelta(hours=min_horas)
    elegibles, saltados = [], []
    for sku, ultima in filas:
        if not forzar and ultima is not None and ultima > umbral:
            saltados.append(sku)
        else:
            elegibles.append((sku, ultima))
    # los nunca medidos primero, luego los más viejos
    elegibles.sort(key=lambda t: (t[1] is not None, t[1] or datetime.min))
    return [s for s, _ in elegibles[:lote]], saltados


def guardar(conn, r: dict):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO stock_buybox (sku_liverpool, vendedor, precio, stock, estado, llamadas, segundos, medido_en)
                       VALUES (%s,%s,%s,%s,%s,%s,%s, now() AT TIME ZONE 'America/Mexico_City')""",
                    (r["sku"], r["vendedor"], r["precio"], r["stock"], (r["estado"] or "")[:200], r["llamadas"], r["segundos"]))
    conn.commit()


# ------------------------------------------------------------------ lectura de la BuyBox
_RE_OFERTA = re.compile(r'"offerId":"(\d+)","sellerId":"(\d+)","sellerName":"([^"]*)".*?"salePrice":([\d.]+)', re.S)


def leer_buybox(html: str):
    """(offerId, sellerId, sellerName, precio) de la oferta ganadora, o None."""
    h = html.replace('\\"', '"').replace("\\\\", "\\")
    i = h.find('"bestOffer":{')
    if i != -1:
        m = _RE_OFERTA.search(h[i:i + 1500])
        if m:
            return m.group(1), m.group(2), m.group(3), float(m.group(4))
    j = h.find('"offers":[{"offerId"')
    if j != -1:
        ofertas = []
        for t in h[j:j + 20000].split('{"offerId":"')[1:]:
            m = _RE_OFERTA.search('"offerId":"' + t[:1200])
            if m:
                ofertas.append((m.group(1), m.group(2), m.group(3), float(m.group(4))))
        if ofertas:
            return min(ofertas, key=lambda o: o[3])
    return None


# ------------------------------------------------------------------ medición por carrito
def medir_stock(sku: str, sesion: requests.Session) -> dict:
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
        url = f"{BASE}/tienda/mirakl/offerListing?productId={sku}&skuId={sku}"
        r = sesion.get(url, headers=H_HTML, timeout=25)
        if r.status_code in BLOQUEO_HTTP or "Access Denied" in r.text[:2000] or "captcha" in r.text[:5000].lower():
            raise Bloqueo(f"offerListing HTTP {r.status_code} / posible captcha")
        if r.status_code == 404:
            res["estado"] = "NO MEDIBLE: página de ofertas no existe (404)"
            return res
        if r.status_code != 200:
            res["estado"] = f"offerListing HTTP {r.status_code}"
            return res
        bb = leer_buybox(r.text)
        if not bb:
            res["estado"] = "no se pudo leer la oferta ganadora"
            return res
        offer_id, seller_id, seller_name, precio = bb
        res["vendedor"], res["precio"] = seller_name, precio

        if seller_name.strip().upper() in NOMBRES_PROPIOS:
            res["estado"] = "La BuyBox ya es nuestra (no se mide)"
            return res

        api("GET", "/auth-service/v2/auth/anonymous?redirect=false")      # token de invitado (cookie)

        def agregar():
            return api("POST", "/web-bff/cart/items", headers={**H_API, "content-type": "application/json"},
                       data=json.dumps({"id": sku, "sku": sku, "quantity": 1,
                                        "offerId": offer_id, "sellerId": seller_id}))

        r = agregar()
        if r.status_code == 401:
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

        def acepta(q):
            rr = api("PATCH", f"/web-bff/cart/items/{linea_id}", headers={**H_API, "content-type": "application/json"},
                     data=json.dumps({"quantity": q}))
            return rr.status_code == 200

        lo, hi = 1, 2
        while hi <= TOPE_PIEZAS and acepta(hi):
            lo, hi = hi, hi * 2
        if hi > TOPE_PIEZAS:
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
        res["estado"] = f"error: {e}"[:200]
        return res
    finally:
        try:   # dejar la bolsa vacía SIEMPRE (DELETE sin content-type: con él Liverpool responde 400)
            if linea_id:
                sesion.delete(BASE + f"/web-bff/cart/items?lineItemIds={linea_id}", headers=H_API, timeout=20)
        except Exception:
            pass
        res["segundos"] = round(time.time() - t0, 1)


# ------------------------------------------------------------------ principal
def main():
    lote = min(int(os.getenv("LOTE") or 12), LOTE_MAX)
    min_horas = float(os.getenv("MIN_HORAS") or 2)
    forzar = (os.getenv("FORZAR") or "") == "1"
    prueba = (os.getenv("MODO_PRUEBA") or "") == "1"
    explicitos = [x for x in re.split(r"[,\s]+", os.getenv("SKUS") or "") if x]

    conn = None
    if not prueba:
        conn = conectar()
        preparar_tabla(conn)
        if bloqueo_reciente(conn):
            print(f"⛔ Hay una marca de bloqueo de hace menos de {HORAS_BLOQUEO} h. No se corre nada para cuidar la IP.")
            sys.exit(3)
        skus, saltados = elegir_skus(conn, lote, min_horas, forzar, explicitos)
    else:
        skus, saltados = explicitos[:lote], []

    print(f"SKUs a medir: {len(skus)} · saltados por medición reciente (<{min_horas:g} h): {len(saltados)}")
    if not skus:
        print("Nada que medir.")
        return
    print("%-12s%-26s%9s%8s%7s%7s  %s" % ("SKU", "Vendedor BuyBox", "Precio", "Stock", "Llam.", "Seg.", "Estado"))
    print("-" * 100)

    hechos = 0
    for n, sku in enumerate(skus):
        if n:
            time.sleep(random.uniform(*PAUSA_ENTRE_SKU))
        try:
            r = medir_stock(sku, requests.Session())
        except Bloqueo as e:
            print("-" * 100)
            print(f"ALTO TOTAL: Liverpool nos está frenando ({e}). Medidos antes del freno: {hechos} de {len(skus)}.")
            if conn:
                guardar(conn, {"sku": MARCA_BLOQUEO, "vendedor": None, "precio": None, "stock": None,
                               "estado": f"Bloqueo: {e}", "llamadas": 0, "segundos": 0})
            sys.exit(2)
        hechos += 1
        if conn:
            guardar(conn, r)
        print("%-12s%-26s%9s%8s%7s%7s  %s" % (
            r["sku"], (r["vendedor"] or "-")[:24], ("%.2f" % r["precio"]) if r["precio"] else "-",
            r["stock"] if r["stock"] is not None else "-", r["llamadas"], r["segundos"] or 0, r["estado"]))
    print("-" * 100)
    print(f"Listo: {hechos} SKUs medidos, sin bloqueo.")


if __name__ == "__main__":
    main()
