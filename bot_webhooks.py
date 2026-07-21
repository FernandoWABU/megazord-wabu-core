#!/usr/bin/env python3

"""
BOT WEBHOOKS - FASTAPI PARA CAPTURA DE BEARER TOKENS
Endpoint: POST /api/capture-bearer
Recibe: Bearer token de Chrome Extension → Guarda en BD
"""

import os
import logging
import psycopg2
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from pydantic import BaseModel

# CARGAR VARIABLES DE ENTORNO
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY")

if not WEBHOOK_SECRET_KEY:
    raise ValueError("❌ WEBHOOK_SECRET_KEY no configurada en variables de entorno")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")

# SETUP LOGGING
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# CREAR APP FASTAPI
app = FastAPI(
    title="Megazord Bot Webhooks",
    description="Webhooks para captura automática de Bearer tokens",
    version="1.0.0"
)

# ==========================================
# CORS MIDDLEWARE
# ==========================================
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# MODELO PYDANTIC
# ==========================================
class BearerTokenRequest(BaseModel):
    token: str
    seller_id: str = "68CAF9EE564AF52E6"
    timestamp: str = None

# ==========================================
# WEBHOOK ENDPOINT
# ==========================================
@app.post("/api/capture-bearer")
async def capture_bearer_token(
    request: BearerTokenRequest,
    authorization: str = Header(None)  ← CAMBIADO
):
    """
    🔐 WEBHOOK: Recibe Bearer token de Chrome Extension
    """
    
    token = request.token
    seller_id = request.seller_id
    
    # 1️⃣ VALIDAR SECRET KEY ← AQUÍ ESTÁ LA VALIDACIÓN
    if authorization != f"Bearer {WEBHOOK_SECRET_KEY}":
        logger.warning(f"🚨 Intento no autorizado desde {seller_id}")
        raise HTTPException(status_code=401, detail="Unauthorized - Invalid secret key")
    
    # 2️⃣ VALIDAR TOKEN
    if not token or len(token) < 50:
        logger.error(f"❌ Token inválido: len={len(token) if token else 0}")
        raise HTTPException(status_code=400, detail="Token inválido o muy corto")
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                
                # 3️⃣ VERIFICAR CUENTA
                cursor.execute("""
                    SELECT id_cuenta, google_encryption_key 
                    FROM cuentas_liverpool 
                    WHERE id_cuenta = %s
                """, (seller_id,))
                
                cuenta = cursor.fetchone()
                if not cuenta:
                    logger.error(f"❌ Cuenta {seller_id} no encontrada")
                    raise HTTPException(status_code=404, detail=f"Cuenta {seller_id} no existe")
                
                id_cuenta, encryption_key = cuenta
                
                # 4️⃣ ENCRIPTAR TOKEN
                cipher = Fernet(encryption_key.encode())
                token_encriptado = cipher.encrypt(token.encode()).decode()
                
                # 5️⃣ ACTUALIZAR TABLA PRINCIPAL
                cursor.execute("""
                    UPDATE cuentas_liverpool 
                    SET 
                        token_autorizacion = %s,
                        timestamp_token = NOW(),
                        token_expira_en = NOW() + INTERVAL '24 hours'
                    WHERE id_cuenta = %s
                """, (token_encriptado, id_cuenta))
                
                logger.info(f"✅ Token actualizado para {id_cuenta}")
                
                # 6️⃣ ROTAR EN HISTORIAL
                cursor.execute("""
                    UPDATE bearer_token_history 
                    SET token_order = token_order + 1 
                    WHERE id_cuenta = %s AND token_order < 5
                """, (id_cuenta,))
                
                cursor.execute("""
                    DELETE FROM bearer_token_history 
                    WHERE id_cuenta = %s AND token_order > 5
                """, (id_cuenta,))
                
                cursor.execute("""
                    INSERT INTO bearer_token_history 
                    (id_cuenta, token_encriptado, captured_at, token_order, status)
                    VALUES (%s, %s, NOW(), 1, 'active')
                """, (id_cuenta, token_encriptado))
                
                # 7️⃣ LOG DE AUDITORÍA
                cursor.execute("""
                    INSERT INTO bearer_capture_log 
                    (id_cuenta, action, timestamp, details)
                    VALUES (%s, 'captured', NOW(), %s)
                """, (id_cuenta, f"Chrome Extension: {token[:30]}..."))
                
                # 8️⃣ CONTAR TOKENS
                cursor.execute("""
                    SELECT COUNT(*) FROM bearer_token_history 
                    WHERE id_cuenta = %s AND status = 'active'
                """, (id_cuenta,))
                
                num_tokens = cursor.fetchone()[0]
                
                conn.commit()
                
                # 9️⃣ TELEGRAM
                msg = (
                    f"🔐 *Bearer capturado*\n\n"
                    f"🏪 Cuenta: `{id_cuenta}`\n"
                    f"📦 Tokens: `{num_tokens}/5`"
                )
                
                try:
                    enviar_telegram(msg)
                except Exception as e:
                    logger.warning(f"⚠️ Error Telegram: {e}")
                
                logger.info(f"✅ ÉXITO | {id_cuenta} | Tokens: {num_tokens}/5")
                
                return {
                    "status": "success",
                    "message": f"Bearer guardado",
                    "tokens_in_history": num_tokens
                }
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# HEALTH CHECK
# ==========================================

@app.get("/health")
async def health_check():
    """🟢 Verifica que el webhook está vivo"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "megazord-webhooks"
    }

# ==========================================
# RUN (LOCAL)
# ==========================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    
    logger.info(f"🚀 Iniciando Megazord Bot Webhooks en puerto {port}...")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
