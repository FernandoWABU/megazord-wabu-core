#!/usr/bin/env python3
import os
import json
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import psycopg
import requests
import threading

# LOGGING EXHAUSTIVO - STDERR Y STDOUT
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Force flush
def log_and_flush(msg):
    print(msg)
    sys.stdout.flush()
    logger.info(msg)

log_and_flush("🚀 INICIANDO WEBHOOK")

load_dotenv()
log_and_flush("✅ .env cargado")

DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY")
FERNET_ENCRYPTION_KEY = os.getenv("FERNET_ENCRYPTION_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")
ALLOWED_EXTENSION_IDS = [id.strip() for id in os.getenv("ALLOWED_EXTENSION_IDS", "").split(",") if id.strip()]

log_and_flush(f"✅ DB: {bool(DATABASE_URL)}")
log_and_flush(f"✅ SECRET: {bool(WEBHOOK_SECRET_KEY)}")
log_and_flush(f"✅ FERNET: {bool(FERNET_ENCRYPTION_KEY)}")
log_and_flush(f"✅ EXTENSION IDS: {ALLOWED_EXTENSION_IDS}")

def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_WMT:
            return
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_WMT, "text": msg, "parse_mode": "Markdown"},
            timeout=5
        )
        log_and_flush("✅ Telegram sent")
    except Exception as e:
        log_and_flush(f"❌ Telegram error: {e}")

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        log_and_flush("📍 OPTIONS recibido")
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Extension-ID')
        self.end_headers()
        log_and_flush("✅ OPTIONS respondido")

    def do_GET(self):
        log_and_flush(f"📍 GET {self.path}")
        if self.path == "/health":
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
            log_and_flush("✅ /health respondido")

    def do_POST(self):
        log_and_flush(f"📍 POST {self.path} RECIBIDO!!!!!!")
        sys.stdout.flush()
        
        try:
            if self.path != "/api/capture-bearer":
                log_and_flush(f"❌ Path incorrecto: {self.path}")
                self.send_response(404)
                self.end_headers()
                return

            auth = self.headers.get('Authorization')
            ext_id = self.headers.get('X-Extension-ID')
            
            log_and_flush(f"🆔 Extension: {ext_id}")
            
            if not ext_id or ext_id not in ALLOWED_EXTENSION_IDS:
                log_and_flush(f"❌ Extension no autorizada")
                self._respond(403, {"detail": "Extension not authorized"})
                return

            if auth != f"Bearer {WEBHOOK_SECRET_KEY}":
                log_and_flush(f"❌ Auth inválida")
                self._respond(401, {"detail": "Unauthorized"})
                return

            log_and_flush("✅ Validaciones pasadas")

            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                data = json.loads(body)
                log_and_flush(f"✅ JSON parseado")
            except Exception as e:
                log_and_flush(f"❌ Parse error: {e}")
                self._respond(400, {"detail": str(e)})
                return

            token = data.get("token")
            seller_id = data.get("seller_id", "LVP_01")

            if not token or len(token) < 50:
                log_and_flush(f"❌ Token inválido")
                self._respond(400, {"detail": "Invalid token"})
                return

            log_and_flush(f"🔄 Conectando a BD: {DATABASE_URL[:30]}...")
            
            with psycopg.connect(DATABASE_URL) as conn:
                log_and_flush("✅ Conexión BD OK")
                
                with conn.cursor() as cur:
                    cur.execute("SELECT id_cuenta FROM cuentas_liverpool WHERE id_cuenta = %s", (seller_id,))
                    if not cur.fetchone():
                        log_and_flush(f"❌ Cuenta no existe: {seller_id}")
                        self._respond(404, {"detail": "Account not found"})
                        return
                    
                    log_and_flush(f"✅ Cuenta OK")

                    cipher = Fernet(FERNET_ENCRYPTION_KEY.encode())
                    token_enc = cipher.encrypt(token.encode()).decode()
                    log_and_flush(f"✅ Token encriptado")

                    cur.execute("UPDATE cuentas_liverpool SET token_autorizacion=%s, timestamp_token=NOW(), token_expira_en=NOW()+INTERVAL '24 hours', fernet_encryption_key=%s WHERE id_cuenta=%s", (token_enc, FERNET_ENCRYPTION_KEY, seller_id))
                    log_and_flush(f"✅ Update OK")

                    cur.execute("DELETE FROM bearer_token_history WHERE id_cuenta = %s AND id NOT IN (SELECT id FROM bearer_token_history WHERE id_cuenta = %s ORDER BY captured_at DESC LIMIT 4)", (seller_id, seller_id))
                    log_and_flush(f"✅ Cleanup OK")

                    cur.execute("INSERT INTO bearer_token_history (id_cuenta, token_encriptado, captured_at, token_order, status) VALUES (%s, %s, NOW(), 1, 'active')", (seller_id, token_enc))
                    log_and_flush(f"✅ Insert OK")

                    cur.execute("INSERT INTO bearer_capture_log (id_cuenta, action, timestamp, details) VALUES (%s, 'captured', NOW(), %s)", (seller_id, f"Extension: {ext_id}"))
                    
                    cur.execute("SELECT COUNT(*) FROM bearer_token_history WHERE id_cuenta = %s", (seller_id,))
                    num_tokens = cur.fetchone()[0]

                    conn.commit()
                    log_and_flush(f"✅ COMMIT OK | Tokens: {num_tokens}")

                    msg = f"🔐 *Bearer capturado*\n🆔 Extension: `{ext_id[-8:]}`\n🏪 Cuenta: `{seller_id}`\n📦 Tokens: `{num_tokens}/5`"
                    threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()

                    log_and_flush(f"✅✅✅ ÉXITO TOTAL")
                    self._respond(200, {"status": "success", "tokens_in_history": num_tokens})

        except Exception as e:
            log_and_flush(f"❌ ERROR: {e}")
            import traceback
            log_and_flush(traceback.format_exc())
            self._respond(500, {"detail": str(e)})

    def _respond(self, code, data):
        try:
            self.send_response(code)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            log_and_flush(f"✅ Response {code} enviada")
        except Exception as e:
            log_and_flush(f"❌ Error enviando response: {e}")

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    try:
        port = int(os.getenv("PORT", 8000))  # ✅ CORRECTO
        log_and_flush(f"🚀 Servidor en puerto {port}")
        
        server = HTTPServer(("0.0.0.0", port), Handler)
        log_and_flush(f"✅ HTTPServer creado")
        log_and_flush(f"🎯 Escuchando en 0.0.0.0:{port}")
        
        sys.stdout.flush()
        sys.stderr.flush()
        
        log_and_flush("🔄 Iniciando serve_forever()...")
        server.serve_forever()
        
    except Exception as e:
        log_and_flush(f"❌❌❌ CRASH: {e}")
        import traceback
        log_and_flush(traceback.format_exc())
        sys.exit(1)
