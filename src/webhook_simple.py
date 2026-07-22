#!/usr/bin/env python3

"""
WEBHOOK SIMPLE - SIN FASTAPI NI PYDANTIC
Servidor HTTP básico para capturar Bearer tokens
"""

import os
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import psycopg
import requests
import threading

# CARGAR VARIABLES DE ENTORNO
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY")
FERNET_ENCRYPTION_KEY = os.getenv("FERNET_ENCRYPTION_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")
ALLOWED_EXTENSION_IDS = os.getenv("ALLOWED_EXTENSION_IDS", "").split(",")
ALLOWED_EXTENSION_IDS = [id.strip() for id in ALLOWED_EXTENSION_IDS if id.strip()]

# SETUP LOGGING
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==========================================
# FUNCIÓN: ENVIAR TELEGRAM
# ==========================================

def enviar_telegram(mensaje):
    """Envía mensaje a Telegram"""
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_WMT:
            logger.warning("⚠️ Telegram no configurado")
            return
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(
            url, 
            json={
                "chat_id": TELEGRAM_CHAT_WMT, 
                "text": mensaje, 
                "parse_mode": "Markdown"
            },
            timeout=5
        )
        logger.info("✅ Mensaje enviado a Telegram")
    except Exception as e:
        logger.error(f"❌ Error Telegram: {e}")

# ==========================================
# HANDLER HTTP
# ==========================================

class WebhookHandler(BaseHTTPRequestHandler):
    
    def do_OPTIONS(self):
        """Manejo de CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Extension-ID')
        self.end_headers()
    
    def do_POST(self):
        """Endpoint POST /api/capture-bearer"""
        
        if self.path == "/api/capture-bearer":
            self.handle_capture_bearer()
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_GET(self):
        """Health check"""
        if self.path == "/health":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def handle_capture_bearer(self):
        """Maneja captura de Bearer token"""
        
        # Leer headers
        auth_header = self.headers.get('Authorization')
        x_extension_id = self.headers.get('X-Extension-ID')
        content_length = int(self.headers.get('Content-Length', 0))
        
        logger.info(f"🔍 POST /api/capture-bearer recibido")
        logger.info(f"🆔 Extension ID: {x_extension_id}")
        
        # Validar Extension ID
        if not x_extension_id or x_extension_id not in ALLOWED_EXTENSION_IDS:
            logger.warning(f"🚨 Extension no autorizada: {x_extension_id}")
            self.send_json_response(403, {"detail": "Extension not authorized"})
            return
        
        # Validar Authorization
        if auth_header != f"Bearer {WEBHOOK_SECRET_KEY}":
            logger.warning(f"🚨 Autorización inválida")
            self.send_json_response(401, {"detail": "Unauthorized"})
            return
        
        # Leer body
        try:
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body)
        except Exception as e:
            logger.error(f"❌ Error parseando JSON: {e}")
            self.send_json_response(400, {"detail": "Invalid JSON"})
            return
        
        token = data.get("token")
        seller_id = data.get("seller_id", "LVP_01")
        
        # Validar token
        if not token or len(token) < 50:
            logger.error(f"❌ Token inválido")
            self.send_json_response(400, {"detail": "Invalid token"})
            return
        
        # Guardar en BD
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cursor:
                    
                    # Verificar cuenta
                    cursor.execute(
                        "SELECT id_cuenta FROM cuentas_liverpool WHERE id_cuenta = %s",
                        (seller_id,)
                    )
                    if not cursor.fetchone():
                        logger.error(f"❌ Cuenta no encontrada: {seller_id}")
                        self.send_json_response(404, {"detail": "Account not found"})
                        return
                    
                    # Encriptar token
                    cipher = Fernet(FERNET_ENCRYPTION_KEY.encode())
                    token_encriptado = cipher.encrypt(token.encode()).decode()
                    
                    # Actualizar cuentas_liverpool
                    cursor.execute("""
                        UPDATE cuentas_liverpool 
                        SET token_autorizacion=%s, timestamp_token=NOW(), 
                            token_expira_en=NOW()+INTERVAL '24 hours',
                            fernet_encryption_key=%s
                        WHERE id_cuenta=%s
                    """, (token_encriptado, FERNET_ENCRYPTION_KEY, seller_id))
                    
                    # Limpiar historial (mantener últimos 4)
                    cursor.execute("""
                        DELETE FROM bearer_token_history 
                        WHERE id_cuenta = %s 
                        AND id NOT IN (
                            SELECT id FROM bearer_token_history 
                            WHERE id_cuenta = %s 
                            ORDER BY captured_at DESC 
                            LIMIT 4
                        )
                    """, (seller_id, seller_id))
                    
                    # Insertar nuevo token
                    cursor.execute("""
                        INSERT INTO bearer_token_history 
                        (id_cuenta, token_encriptado, captured_at, token_order, status)
                        VALUES (%s, %s, NOW(), 1, 'active')
                    """, (seller_id, token_encriptado))
                    
                    # Log de auditoría
                    cursor.execute("""
                        INSERT INTO bearer_capture_log 
                        (id_cuenta, action, timestamp, details)
                        VALUES (%s, 'captured', NOW(), %s)
                    """, (seller_id, f"Extension: {x_extension_id}"))
                    
                    # Contar tokens
                    cursor.execute("""
                        SELECT COUNT(*) FROM bearer_token_history 
                        WHERE id_cuenta = %s
                    """, (seller_id,))
                    num_tokens = cursor.fetchone()[0]
                    
                    conn.commit()
                    
                    # Enviar Telegram en thread (no bloquear)
                    msg = f"""🔐 *Bearer capturado*
🆔 Extension: `{x_extension_id[-8:]}`
🏪 Cuenta: `{seller_id}`
📦 Tokens: `{num_tokens}/5`
⏰ Válido por: `24 horas`"""
                    threading.Thread(target=enviar_telegram, args=(msg,)).start()
                    
                    logger.info(f"✅ ÉXITO | Extension: {x_extension_id[-8:]} | Tokens: {num_tokens}/5")
                    
                    self.send_json_response(200, {
                        "status": "success",
                        "message": "Bearer guardado",
                        "tokens_in_history": num_tokens
                    })
        
        except Exception as e:
            logger.error(f"❌ Error BD: {e}")
            self.send_json_response(500, {"detail": str(e)})
    
    def send_json_response(self, status_code, data):
        """Envía respuesta JSON"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        """Silenciar logs de HTTP por defecto"""
        pass

# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    logger.info(f"🚀 Webhook iniciado en puerto {port}")
    logger.info(f"📍 POST http://localhost:{port}/api/capture-bearer")
    logger.info(f"❤️ GET http://localhost:{port}/health")
    
    server.serve_forever()
