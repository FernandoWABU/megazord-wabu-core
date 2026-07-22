#!/usr/bin/env python3
import os
import json
import logging
import sys
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import psycopg
import requests
import threading

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s | %(levelname)-8s | %(message)s')
logger = logging.getLogger(__name__)

print("🚀 INICIANDO WEBHOOK", flush=True)

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

def send_telegram(msg):
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

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
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
        try:
            if self.path == "/health":
                print("📍 GET /health", flush=True)
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "healthy"}).encode())
                print("✅ /health OK", flush=True)
            
            # 🆕 NUEVO ENDPOINT PARA RESETEAR DESDE DASHBOARD
            elif self.path == "/admin/reset-breaker":
                print("📍 GET /admin/reset-breaker - RESET SOLICITADO", flush=True)
                auth = self.headers.get('Authorization')
                
                # Validación de seguridad (opcional, pero recomendado)
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
                self.end_headers()
                
        except Exception as e:
            print(f"❌ GET ERROR: {e}", flush=True)
            print(traceback.format_exc(), flush=True)

    def do_POST(self):
        try:
            print(f"📍📍📍 POST {self.path} RECIBIDO !!!", flush=True)
            
            if self.path != "/api/capture-bearer":
                self.send_response(404)
                self.end_headers()
                return

            auth = self.headers.get('Authorization')
            ext_id = self.headers.get('X-Extension-ID')
            
            print(f"🆔 Extension: {ext_id}", flush=True)
            
            if not ext_id or ext_id not in ALLOWED_EXTENSION_IDS:
                print(f"❌ No autorizada", flush=True)
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

        except Exception as e:
            print(f"❌❌❌ CRITICAL ERROR: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
            try:
                self._respond(500, {"detail": str(e)})
            except:
                pass

    def _respond(self, code, data):
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
        pass

print("🚀 Creando servidor...", flush=True)
port = int(os.environ.get("PORT", "3000"))
print(f"🎯 Puerto REAL que Railway asignó: {port}", flush=True)
print(f"🎯 Puerto: {port}", flush=True)

server = HTTPServer(("0.0.0.0", port), Handler)
print(f"✅ Servidor creado en 0.0.0.0:{port}", flush=True)

sys.stdout.flush()
sys.stderr.flush()

print(f"🔄 ESCUCHANDO...", flush=True)
sys.stdout.flush()

try:
    server.serve_forever()
except Exception as e:
    print(f"❌ CRASH: {e}", flush=True)
    print(traceback.format_exc(), flush=True)
    sys.exit(1)
elif self.path == "/admin/reset-breaker":
    print("📍 GET /admin/reset-breaker", flush=True)
    auth = self.headers.get('Authorization')
    
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
            "message": "Circuit Breaker reseteado"
        })
        print("✅ Reset HTTP exitoso", flush=True)
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        self._respond(500, {"status": "error", "message": str(e)})
