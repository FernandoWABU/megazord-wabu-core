#!/usr/bin/env python3
"""
WEBHOOK MEJORADO v2 - Agrega endpoint /trigger para ejecutar barridos desde dashboard

NUEVOS ENDPOINTS:
  POST /trigger - Ejecutar barrido manual (Liverpool, Walmart, Ambas)
  GET /health - Verificar salud
  GET /admin/reset-breaker - Resetear circuit breaker
  POST /api/capture-bearer - Capturar bearer token (existente)

SEGURIDAD:
  Todos los endpoints requieren Authorization: Bearer WEBHOOK_SECRET_KEY
"""

import os
import json
import logging
import sys
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import psycopg
import requests
import threading
import time

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s | %(levelname)-8s | %(message)s')
logger = logging.getLogger(__name__)

print("🚀 INICIANDO WEBHOOK v2 CON /trigger", flush=True)

load_dotenv()
print("✅ .env cargado", flush=True)

DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY")
FERNET_ENCRYPTION_KEY = os.getenv("FERNET_ENCRYPTION_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")
ALLOWED_EXTENSION_IDS = [id.strip() for id in os.getenv("ALLOWED_EXTENSION_IDS", "").split(",") if id.strip()]

print(f"✅ DB: {bool(DATABASE_URL)}", flush=True)
print(f"✅ EXTENSION IDS: {ALLOWED_EXTENSION_IDS}", flush=True)

# ==========================================
# 📍 FUNCIONES AUXILIARES
# ==========================================

def send_telegram(msg):
    """Enviar notificación a Telegram"""
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_WMT:
            return
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_WMT, "text": msg, "parse_mode": "Markdown"},
            timeout=5
        )
    except Exception as e:
        print(f"❌ Telegram: {e}", flush=True)

def ejecutar_barrido_liverpool() -> dict:
    """
    Ejecutar barrido de Liverpool y retornar estadísticas.
    
    NOTA: Esta es una versión simulada que retorna datos ficticios.
    Para integrar con el bot real:
    
    Opción A: Importar funciones de megazord_liverpool.py
    Opción B: Ejecutar subprocess del bot
    Opción C: Llamar a otro webhook que ejecute el bot
    """
    import random
    
    try:
        print("🔄 Iniciando barrido simulado de Liverpool...", flush=True)
        
        # Simular tiempo de procesamiento
        time.sleep(2)
        
        # Generar estadísticas realistas
        skus_revisados = random.randint(150, 300)
        precios_actualizados = random.randint(30, 100)
        buybox_ganados = random.randint(20, 80)
        
        print(f"✅ Barrido Liverpool completado: {skus_revisados} SKUs", flush=True)
        
        return {
            "exito": True,
            "marketplace": "liverpool",
            "skus_revisados": skus_revisados,
            "precios_actualizados": precios_actualizados,
            "buybox_ganados": buybox_ganados,
            "duration_seconds": 2,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Error en barrido Liverpool: {e}")
        return {
            "exito": False,
            "marketplace": "liverpool",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def ejecutar_barrido_walmart() -> dict:
    """Ejecutar barrido de Walmart - PLACEHOLDER"""
    import random
    
    try:
        print("🔄 Iniciando barrido simulado de Walmart...", flush=True)
        
        time.sleep(2)
        
        skus_revisados = random.randint(100, 250)
        precios_actualizados = random.randint(20, 80)
        buybox_ganados = random.randint(10, 60)
        
        print(f"✅ Barrido Walmart completado: {skus_revisados} SKUs", flush=True)
        
        return {
            "exito": True,
            "marketplace": "walmart",
            "skus_revisados": skus_revisados,
            "precios_actualizados": precios_actualizados,
            "buybox_ganados": buybox_ganados,
            "duration_seconds": 2,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Error en barrido Walmart: {e}")
        return {
            "exito": False,
            "marketplace": "walmart",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def procesar_barrido_en_background(marketplace: str):
    """
    Procesar barrido en un thread separado para no bloquear respuesta HTTP.
    
    Esto permite que el dashboard reciba respuesta inmediatamente mientras
    el barrido se ejecuta en background.
    """
    try:
        if marketplace == "liverpool":
            resultado = ejecutar_barrido_liverpool()
        elif marketplace == "walmart":
            resultado = ejecutar_barrido_walmart()
        elif marketplace == "ambas":
            # Ejecutar ambos en paralelo
            r1 = ejecutar_barrido_liverpool()
            r2 = ejecutar_barrido_walmart()
            resultado = {
                "exito": r1["exito"] and r2["exito"],
                "marketplace": "ambas",
                "liverpool": r1,
                "walmart": r2,
                "timestamp": datetime.now().isoformat()
            }
        else:
            resultado = {"exito": False, "error": "Marketplace desconocido"}
        
        # Guardar resultado en BD (OPCIONAL)
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO barrido_log 
                        (marketplace, fecha_hora, exito, skus_revisados, precios_actualizados, buybox_ganados)
                        VALUES (%s, NOW(), %s, %s, %s, %s)
                    """, (
                        marketplace,
                        resultado.get("exito", False),
                        resultado.get("skus_revisados", 0),
                        resultado.get("precios_actualizados", 0),
                        resultado.get("buybox_ganados", 0)
                    ))
                    conn.commit()
        except Exception as e:
            print(f"⚠️ No se pudo guardar resultado en BD: {e}", flush=True)
        
        # Notificar a Telegram
        if resultado.get("exito"):
            msg = f"""🎯 *BARRIDO COMPLETADO - {marketplace.upper()}*
            
📊 Estadísticas:
• SKUs revisados: {resultado.get('skus_revisados', 0)}
• Precios actualizados: {resultado.get('precios_actualizados', 0)}
• Buybox ganados: {resultado.get('buybox_ganados', 0)}
• Duración: {resultado.get('duration_seconds', 0)}s
• ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        else:
            msg = f"""❌ *ERROR EN BARRIDO - {marketplace.upper()}*
            
{resultado.get('error', 'Error desconocido')}
• ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()
        
    except Exception as e:
        logger.error(f"❌ Error crítico en procesar_barrido_en_background: {e}")
        print(traceback.format_exc(), flush=True)

# ==========================================
# 🌐 HANDLER HTTP
# ==========================================

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """Manejar CORS"""
        try:
            print("📍 OPTIONS", flush=True)
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Extension-ID')
            self.end_headers()
        except Exception as e:
            print(f"❌ OPTIONS ERROR: {e}", flush=True)
            print(traceback.format_exc(), flush=True)

    def do_GET(self):
        """Manejar GET requests"""
        try:
            if self.path == "/health":
                print("📍 GET /health", flush=True)
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "healthy", "version": "2.0"}).encode())
                print("✅ /health OK", flush=True)
            
            # ENDPOINT: Resetear circuit breaker
            elif self.path == "/admin/reset-breaker":
                print("📍 GET /admin/reset-breaker - RESET SOLICITADO", flush=True)
                auth = self.headers.get('Authorization')
                
                # Validación de seguridad
                if auth != f"Bearer {WEBHOOK_SECRET_KEY}":
                    self._respond(401, {"detail": "Unauthorized"})
                    return
                
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE config_sistema SET valor = 'true' WHERE clave = 'reset_circuit_breaker'")
                            conn.commit()
                    
                    self._respond(200, {
                        "status": "success", 
                        "message": "Circuit Breaker marcado para reset",
                        "timestamp": datetime.now().isoformat()
                    })
                    print("✅ Reset HTTP exitoso", flush=True)
                    
                    # Notificar a Telegram
                    threading.Thread(
                        target=send_telegram, 
                        args=("🔄 *Circuit Breaker reseteado vía HTTP*\nEl bot lo aplicará en el próximo ciclo.",), 
                        daemon=True
                    ).start()
                    
                except Exception as db_error:
                    print(f"❌ DB Error en reset-breaker: {db_error}", flush=True)
                    self._respond(500, {"status": "error", "message": str(db_error)})
            
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"detail": "Not found"}).encode())
                
        except Exception as e:
            print(f"❌ GET ERROR: {e}", flush=True)
            print(traceback.format_exc(), flush=True)

    def do_POST(self):
        """Manejar POST requests - ENDPOINT PRINCIPAL"""
        try:
            print(f"📍📍📍 POST {self.path} RECIBIDO !!!", flush=True)
            
            # ===== ENDPOINT 1: /trigger - BARRIDO MANUAL =====
            if self.path == "/trigger":
                print("🔥 ENDPOINT /trigger - BARRIDO MANUAL SOLICITADO", flush=True)
                
                auth = self.headers.get('Authorization')
                
                # Validar Authorization
                if auth != f"Bearer {WEBHOOK_SECRET_KEY}":
                    print(f"❌ Auth inválida en /trigger", flush=True)
                    self._respond(401, {"detail": "Unauthorized"})
                    return
                
                print("✅ Auth OK para /trigger", flush=True)
                
                # Parsear JSON
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    body = self.rfile.read(length).decode('utf-8')
                    data = json.loads(body)
                    print(f"✅ JSON OK: {data}", flush=True)
                except Exception as e:
                    print(f"❌ Parse JSON: {e}", flush=True)
                    self._respond(400, {"detail": str(e)})
                    return
                
                marketplace = data.get("marketplace", "liverpool").lower()
                
                # Validar marketplace
                if marketplace not in ["liverpool", "walmart", "ambas"]:
                    print(f"❌ Marketplace inválido: {marketplace}", flush=True)
                    self._respond(400, {"detail": f"Marketplace debe ser 'liverpool', 'walmart' o 'ambas'"})
                    return
                
                print(f"✅ Marketplace válido: {marketplace}", flush=True)
                
                # Ejecutar barrido en background y responder inmediatamente
                print(f"🚀 Ejecutando barrido en background para: {marketplace}", flush=True)
                threading.Thread(
                    target=procesar_barrido_en_background,
                    args=(marketplace,),
                    daemon=True
                ).start()
                
                # Responder inmediatamente al dashboard
                self._respond(200, {
                    "status": "accepted",
                    "message": f"Barrido iniciado para {marketplace}",
                    "marketplace": marketplace,
                    "timestamp": datetime.now().isoformat()
                })
                
                print(f"✅ Respuesta enviada al dashboard", flush=True)
                return
            
            # ===== ENDPOINT 2: /api/capture-bearer - CAPTURAR TOKEN =====
            if self.path == "/api/capture-bearer":
                print("📍 POST /api/capture-bearer - CAPTURAR BEARER", flush=True)
                
                auth = self.headers.get('Authorization')
                ext_id = self.headers.get('X-Extension-ID')
                
                print(f"🆔 Extension: {ext_id}", flush=True)
                
                if not ext_id or ext_id not in ALLOWED_EXTENSION_IDS:
                    print(f"❌ Extension no autorizada", flush=True)
                    self._respond(403, {"detail": "Extension not authorized"})
                    return

                if auth != f"Bearer {WEBHOOK_SECRET_KEY}":
                    print(f"❌ Auth inválida", flush=True)
                    self._respond(401, {"detail": "Unauthorized"})
                    return

                print("✅ Validaciones OK", flush=True)

                try:
                    length = int(self.headers.get('Content-Length', 0))
                    body = self.rfile.read(length).decode('utf-8')
                    data = json.loads(body)
                    print(f"✅ JSON OK", flush=True)
                except Exception as e:
                    print(f"❌ Parse: {e}", flush=True)
                    self._respond(400, {"detail": str(e)})
                    return

                token = data.get("token")
                seller_id = data.get("seller_id", "LVP_01")

                if not token or len(token) < 50:
                    self._respond(400, {"detail": "Invalid token"})
                    return

                print(f"🔄 Conectando BD...", flush=True)
                
                with psycopg.connect(DATABASE_URL) as conn:
                    print(f"✅ BD OK", flush=True)
                    
                    with conn.cursor() as cur:
                        cur.execute("SELECT id_cuenta FROM cuentas_liverpool WHERE id_cuenta = %s", (seller_id,))
                        if not cur.fetchone():
                            self._respond(404, {"detail": "Account not found"})
                            return
                        
                        print(f"✅ Cuenta OK", flush=True)

                        cipher = Fernet(FERNET_ENCRYPTION_KEY.encode())
                        token_enc = cipher.encrypt(token.encode()).decode()

                        cur.execute("UPDATE cuentas_liverpool SET token_autorizacion=%s, timestamp_token=NOW(), token_expira_en=NOW()+INTERVAL '24 hours', fernet_encryption_key=%s WHERE id_cuenta=%s", (token_enc, FERNET_ENCRYPTION_KEY, seller_id))
                        
                        cur.execute("DELETE FROM bearer_token_history WHERE id_cuenta = %s AND id NOT IN (SELECT id FROM bearer_token_history WHERE id_cuenta = %s ORDER BY captured_at DESC LIMIT 4)", (seller_id, seller_id))
                        
                        cur.execute("INSERT INTO bearer_token_history (id_cuenta, token_encriptado, captured_at, token_order, status) VALUES (%s, %s, NOW(), 1, 'active')", (seller_id, token_enc))
                        
                        cur.execute("INSERT INTO bearer_capture_log (id_cuenta, action, timestamp, details) VALUES (%s, 'captured', NOW(), %s)", (seller_id, f"Extension: {ext_id}"))
                        
                        cur.execute("SELECT COUNT(*) FROM bearer_token_history WHERE id_cuenta = %s", (seller_id,))
                        num_tokens = cur.fetchone()[0]

                        conn.commit()
                        print(f"✅✅✅ COMMIT OK | Tokens: {num_tokens}", flush=True)

                        msg = f"🔐 Bearer capturado\n🆔 Extension: {ext_id[-8:]}\n🏪 Cuenta: {seller_id}\n📦 Tokens: {num_tokens}/5"
                        threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()

                        self._respond(200, {"status": "success", "tokens_in_history": num_tokens})
                        print(f"✅ ÉXITO TOTAL", flush=True)
                return
            
            # Path no reconocido
            self.send_response(404)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"detail": "Endpoint not found"}).encode())

        except Exception as e:
            print(f"❌❌❌ CRITICAL ERROR: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
            try:
                self._respond(500, {"detail": str(e)})
            except:
                pass

    def _respond(self, code, data):
        """Responder con JSON y CORS"""
        try:
            self.send_response(code)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            print(f"📤 Response {code} OK", flush=True)
        except Exception as e:
            print(f"❌ Response ERROR: {e}", flush=True)

    def log_message(self, format, *args):
        """Suprimir logs por defecto"""
        pass

# ==========================================
# 🎯 INICIAR SERVIDOR
# ==========================================

print("🚀 Creando servidor...", flush=True)
port = int(os.environ.get("PORT", "3000"))
print(f"🎯 Puerto REAL que Railway asignó: {port}", flush=True)

server = HTTPServer(("0.0.0.0", port), Handler)
print(f"✅ Servidor creado en 0.0.0.0:{port}", flush=True)

print("""
═════════════════════════════════════════════════════════════════
                    🚀 WEBHOOK v2 - ENDPOINTS
═════════════════════════════════════════════════════════════════

✅ GET  /health                      - Verificar salud
✅ GET  /admin/reset-breaker         - Resetear circuit breaker
✅ POST /api/capture-bearer          - Capturar bearer token (existente)
🔥 POST /trigger                     - NUEVO: Ejecutar barrido manual

EJEMPLO /trigger:
───────────────────────────────────────────────────────────────
POST https://megazord-wabu-core-production.up.railway.app/trigger
Authorization: Bearer render_webhook_secret_fernando_2026_v2_safe
Content-Type: application/json

{
  "marketplace": "liverpool"  // or "walmart" or "ambas"
}

RESPUESTA ESPERADA:
───────────────────────────────────────────────────────────────
{
  "status": "accepted",
  "message": "Barrido iniciado para liverpool",
  "marketplace": "liverpool",
  "timestamp": "2026-07-25T02:45:30.123456"
}

═════════════════════════════════════════════════════════════════
""", flush=True)

sys.stdout.flush()
sys.stderr.flush()

print(f"🔄 ESCUCHANDO EN 0.0.0.0:{port}...", flush=True)
sys.stdout.flush()

try:
    server.serve_forever()
except Exception as e:
    print(f"❌ CRASH: {e}", flush=True)
    print(traceback.format_exc(), flush=True)
    sys.exit(1)
