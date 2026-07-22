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

# LOGGING EXHAUSTIVO
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

try:
    load_dotenv()
    logger.info("✅ .env cargado")
except Exception as e:
    logger.error(f"❌ Error cargando .env: {e}")

try:
    DATABASE_URL = os.getenv("DATABASE_URL")
    WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY")
    FERNET_ENCRYPTION_KEY = os.getenv("FERNET_ENCRYPTION_KEY")
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")
    ALLOWED_EXTENSION_IDS = [id.strip() for id in os.getenv("ALLOWED_EXTENSION_IDS", "").split(",") if id.strip()]
    
    logger.info(f"✅ DATABASE_URL: {'presente' if DATABASE_URL else 'FALTA'}")
    logger.info(f"✅ WEBHOOK_SECRET_KEY: {'presente' if WEBHOOK_SECRET_KEY else 'FALTA'}")
    logger.info(f"✅ FERNET_ENCRYPTION_KEY: {'presente' if FERNET_ENCRYPTION_KEY else 'FALTA'}")
    logger.info(f"✅ ALLOWED_EXTENSION_IDS: {ALLOWED_EXTENSION_IDS}")
except Exception as e:
    logger.error(f"❌ Error cargando variables: {e}")
    sys.exit(1)

def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_WMT:
            logger.warning("⚠️ Telegram no configurado")
            return
        logger.info("📤 Enviando a Telegram...")
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_WMT, "text": msg, "parse_mode": "Markdown"},
            timeout=5
        )
        logger.info("✅ Telegram enviado")
    except Exception as e:
        logger.error(f"❌ Error Telegram: {e}", exc_info=True)

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        logger.info("📍 OPTIONS request")
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Extension-ID')
        self.end_headers()
        logger.info("✅ OPTIONS respondido")

    def do_GET(self):
        logger.info(f"📍 GET {self.path}")
        if self.path == "/health":
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
            logger.info("✅ /health respondido")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            logger.info(f"📍 POST {self.path}")
            
            if self.path != "/api/capture-bearer":
                logger.warning(f"❌ Path incorrecto: {self.path}")
                self.send_response(404)
                self.end_headers()
                return

            auth = self.headers.get('Authorization')
            ext_id = self.headers.get('X-Extension-ID')
            
            logger.info(f"🆔 Extension ID: {ext_id}")
            logger.info(f"🔐 Auth Header presente: {bool(auth)}")
            
            # Validar Extension ID
            if not ext_id or ext_id not in ALLOWED_EXTENSION_IDS:
                logger.warning(f"❌ Extension NO autorizada: {ext_id}")
                logger.warning(f"   Permitidas: {ALLOWED_EXTENSION_IDS}")
                self._respond_json(403, {"detail": "Extension not authorized"})
                return

            # Validar Authorization
            expected_auth = f"Bearer {WEBHOOK_SECRET_KEY}"
            if auth != expected_auth:
                logger.warning(f"❌ Auth inválida")
                logger.warning(f"   Recibido: {auth[:30] if auth else 'None'}...")
                self._respond_json(401, {"detail": "Unauthorized"})
                return

            logger.info("✅ Auth validada correctamente")

            # Leer body
            try:
                length = int(self.headers.get('Content-Length', 0))
                logger.info(f"📦 Content-Length: {length}")
                
                body = self.rfile.read(length).decode('utf-8')
                logger.info(f"📖 Body leído: {body[:100]}")
                
                data = json.loads(body)
                logger.info(f"✅ JSON parseado: {list(data.keys())}")
            except Exception as e:
                logger.error(f"❌ Error parseando request: {e}", exc_info=True)
                self._respond_json(400, {"detail": f"Invalid request: {str(e)}"})
                return

            token = data.get("token")
            seller_id = data.get("seller_id", "LVP_01")

            logger.info(f"🔑 Token presente: {bool(token)}")
            logger.info(f"🏪 Seller ID: {seller_id}")

            if not token or len(token) < 50:
                logger.error(f"❌ Token inválido")
                self._respond_json(400, {"detail": "Invalid token"})
                return

            logger.info("🔄 Conectando a BD...")
            
            # Guardar en BD
            try:
                with psycopg.connect(DATABASE_URL) as conn:
                    logger.info("✅ Conexión a BD exitosa")
                    
                    with conn.cursor() as cur:
                        # Verificar cuenta
                        logger.info(f"🔍 Verificando cuenta: {seller_id}")
                        cur.execute("SELECT id_cuenta FROM cuentas_liverpool WHERE id_cuenta = %s", (seller_id,))
                        result = cur.fetchone()
                        
                        if not result:
                            logger.error(f"❌ Cuenta no encontrada: {seller_id}")
                            self._respond_json(404, {"detail": "Account not found"})
                            return
                        
                        logger.info(f"✅ Cuenta encontrada: {seller_id}")

                        # Encriptar
                        logger.info("🔐 Encriptando token...")
                        cipher = Fernet(FERNET_ENCRYPTION_KEY.encode())
                        token_enc = cipher.encrypt(token.encode()).decode()
                        logger.info("✅ Token encriptado")

                        # Actualizar
                        logger.info("📝 Actualizando cuentas_liverpool...")
                        cur.execute("""
                            UPDATE cuentas_liverpool 
                            SET token_autorizacion=%s, timestamp_token=NOW(), 
                                token_expira_en=NOW()+INTERVAL '24 hours',
                                fernet_encryption_key=%s
                            WHERE id_cuenta=%s
                        """, (token_enc, FERNET_ENCRYPTION_KEY, seller_id))
                        logger.info(f"✅ Actualizado: {cur.rowcount} filas")

                        # Limpiar histórico
                        logger.info("🧹 Limpiando histórico...")
                        cur.execute("""
                            DELETE FROM bearer_token_history 
                            WHERE id_cuenta = %s 
                            AND id NOT IN (
                                SELECT id FROM bearer_token_history 
                                WHERE id_cuenta = %s 
                                ORDER BY captured_at DESC LIMIT 4
                            )
                        """, (seller_id, seller_id))
                        logger.info(f"✅ Limpiado: {cur.rowcount} filas")

                        # Insertar nuevo
                        logger.info("➕ Insertando nuevo token...")
                        cur.execute("""
                            INSERT INTO bearer_token_history 
                            (id_cuenta, token_encriptado, captured_at, token_order, status)
                            VALUES (%s, %s, NOW(), 1, 'active')
                        """, (seller_id, token_enc))
                        logger.info(f"✅ Insertado: {cur.rowcount} filas")

                        # Auditoría
                        logger.info("📋 Insertando log de auditoría...")
                        cur.execute("""
                            INSERT INTO bearer_capture_log 
                            (id_cuenta, action, timestamp, details)
                            VALUES (%s, 'captured', NOW(), %s)
                        """, (seller_id, f"Extension: {ext_id}"))
                        logger.info(f"✅ Log insertado: {cur.rowcount} filas")

                        # Contar tokens
                        logger.info("📊 Contando tokens...")
                        cur.execute("SELECT COUNT(*) FROM bearer_token_history WHERE id_cuenta = %s", (seller_id,))
                        num_tokens = cur.fetchone()[0]
                        logger.info(f"✅ Tokens: {num_tokens}/5")

                        conn.commit()
                        logger.info("✅ BD commit exitoso")

                        # Telegram en thread
                        msg = f"""🔐 *Bearer capturado*
🆔 Extension: `{ext_id[-8:]}`
🏪 Cuenta: `{seller_id}`
📦 Tokens: `{num_tokens}/5`
⏰ Válido por: `24 horas`"""
                        threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()

                        logger.info(f"✅ ÉXITO TOTAL | Tokens: {num_tokens}/5")
                        self._respond_json(200, {"status": "success", "tokens_in_history": num_tokens})

            except Exception as e:
                logger.error(f"❌ Error BD: {e}", exc_info=True)
                self._respond_json(500, {"detail": f"BD error: {str(e)}"})

        except Exception as e:
            logger.error(f"❌ Error no capturado en do_POST: {e}", exc_info=True)
            self._respond_json(500, {"detail": f"Unhandled error: {str(e)}"})

    def _respond_json(self, code, data):
        try:
            logger.info(f"📤 Respondiendo: {code} {data}")
            self.send_response(code)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            logger.info("✅ Respuesta enviada")
        except Exception as e:
            logger.error(f"❌ Error enviando respuesta: {e}", exc_info=True)

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    logger.info(f"🚀 Iniciando servidor en puerto {port}")
    logger.info(f"✅ CORS enabled")
    
    server = HTTPServer(("0.0.0.0", port), Handler)
    logger.info(f"🎯 Servidor listo")
    
    try:
        server.serve_forever()
    except Exception as e:
        logger.error(f"❌ Error en serve_forever: {e}", exc_info=True)
        sys.exit(1)
