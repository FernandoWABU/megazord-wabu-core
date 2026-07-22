#!/usr/bin/env python3
import os
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import psycopg
import requests
import threading

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY")
FERNET_ENCRYPTION_KEY = os.getenv("FERNET_ENCRYPTION_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")
ALLOWED_EXTENSION_IDS = [id.strip() for id in os.getenv("ALLOWED_EXTENSION_IDS", "").split(",") if id.strip()]

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

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
        logger.error(f"Telegram error: {e}")

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Extension-ID')
        self.end_headers()
        logger.info("✅ OPTIONS preflight OK")

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/api/capture-bearer":
            self.send_response(404)
            self.end_headers()
            return

        auth = self.headers.get('Authorization')
        ext_id = self.headers.get('X-Extension-ID')
        
        logger.info(f"🔍 POST recibido | Extension: {ext_id}")
        
        # Validar Extension ID
        if not ext_id or ext_id not in ALLOWED_EXTENSION_IDS:
            logger.warning(f"❌ Extension no autorizada: {ext_id}")
            logger.warning(f"   Permitidas: {ALLOWED_EXTENSION_IDS}")
            self._respond_json(403, {"detail": "Extension not authorized"})
            return

        # Validar Authorization
        if auth != f"Bearer {WEBHOOK_SECRET_KEY}":
            logger.warning(f"❌ Auth inválida")
            self._respond_json(401, {"detail": "Unauthorized"})
            return

        # Leer body
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
        except Exception as e:
            logger.error(f"❌ Parse error: {e}")
            self._respond_json(400, {"detail": "Invalid JSON"})
            return

        token = data.get("token")
        seller_id = data.get("seller_id", "LVP_01")

        if not token or len(token) < 50:
            logger.error(f"❌ Token inválido")
            self._respond_json(400, {"detail": "Invalid token"})
            return

        # Guardar en BD
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    # Verificar cuenta
                    cur.execute("SELECT id_cuenta FROM cuentas_liverpool WHERE id_cuenta = %s", (seller_id,))
                    if not cur.fetchone():
                        logger.error(f"❌ Cuenta no encontrada: {seller_id}")
                        self._respond_json(404, {"detail": "Account not found"})
                        return

                    # Encriptar
                    cipher = Fernet(FERNET_ENCRYPTION_KEY.encode())
                    token_enc = cipher.encrypt(token.encode()).decode()

                    # Actualizar
                    cur.execute("""
                        UPDATE cuentas_liverpool 
                        SET token_autorizacion=%s, timestamp_token=NOW(), 
                            token_expira_en=NOW()+INTERVAL '24 hours',
                            fernet_encryption_key=%s
                        WHERE id_cuenta=%s
                    """, (token_enc, FERNET_ENCRYPTION_KEY, seller_id))

                    # Limpiar histórico
                    cur.execute("""
                        DELETE FROM bearer_token_history 
                        WHERE id_cuenta = %s 
                        AND id NOT IN (
                            SELECT id FROM bearer_token_history 
                            WHERE id_cuenta = %s 
                            ORDER BY captured_at DESC LIMIT 4
                        )
                    """, (seller_id, seller_id))

                    # Insertar nuevo
                    cur.execute("""
                        INSERT INTO bearer_token_history 
                        (id_cuenta, token_encriptado, captured_at, token_order, status)
                        VALUES (%s, %s, NOW(), 1, 'active')
                    """, (seller_id, token_enc))

                    # Auditoría
                    cur.execute("""
                        INSERT INTO bearer_capture_log 
                        (id_cuenta, action, timestamp, details)
                        VALUES (%s, 'captured', NOW(), %s)
                    """, (seller_id, f"Extension: {ext_id}"))

                    # Contar tokens
                    cur.execute("SELECT COUNT(*) FROM bearer_token_history WHERE id_cuenta = %s", (seller_id,))
                    num_tokens = cur.fetchone()[0]

                    conn.commit()

                    # Telegram en thread
                    msg = f"""🔐 *Bearer capturado*
🆔 Extension: `{ext_id[-8:]}`
🏪 Cuenta: `{seller_id}`
📦 Tokens: `{num_tokens}/5`
⏰ Válido por: `24 horas`"""
                    threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()

                    logger.info(f"✅ ÉXITO | Tokens: {num_tokens}/5")
                    self._respond_json(200, {"status": "success", "tokens_in_history": num_tokens})

        except Exception as e:
            logger.error(f"❌ BD error: {e}")
            self._respond_json(500, {"detail": str(e)})

    def _respond_json(self, code, data):
        self.send_response(code)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    logger.info(f"🚀 Webhook en puerto {port}")
    logger.info(f"✅ CORS enabled")
    server.serve_forever()
