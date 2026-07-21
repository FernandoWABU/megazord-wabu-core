#!/usr/bin/env python3

"""
BOT WEBHOOKS - FASTAPI PARA CAPTURA DE BEARER TOKENS
Endpoint: POST /api/capture-bearer
Recibe: Bearer token de Chrome Extension → Guarda en BD
"""

import os
import logging
import psycopg2
import requests
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from cryptography.fernet import Fernet
from pydantic import BaseModel
from dotenv import load_dotenv

# CARGAR VARIABLES DE ENTORNO
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY")
FERNET_ENCRYPTION_KEY = os.getenv("FERNET_ENCRYPTION_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_WMT = os.getenv("TELEGRAM_CHAT_WMT")

if not WEBHOOK_SECRET_KEY:
    raise ValueError("❌ WEBHOOK_SECRET_KEY no configurada")

if not FERNET_ENCRYPTION_KEY:
    raise ValueError("❌ FERNET_ENCRYPTION_KEY no configurada")

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

# CORS MIDDLEWARE
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MODELO PYDANTIC
class BearerTokenRequest(BaseModel):
    token: str
    seller_id: str = "LVP_01"
    timestamp: str = None

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
        response = requests.post(
            url, 
            json={
                "chat_id": TELEGRAM_CHAT_WMT, 
                "text": mensaje, 
                "parse_mode": "Markdown"
            },
            timeout=5
        )
        
        if response.status_code == 200:
            logger.info("✅ Mensaje enviado a Telegram")
        else:
            logger.error(f"❌ Error Telegram: {response.status_code}")
            
    except Exception as e:
        logger.error(f"❌ Error enviando Telegram: {e}")

# ==========================================
# WEBHOOK ENDPOINT: CAPTURAR BEARER TOKEN
# ==========================================

@app.post("/api/capture-bearer")
async def capture_bearer_token(
    request: BearerTokenRequest,
    authorization: str = Header(None),
    x_extension_id: str = Header(None)
):
    """
    Recibe Bearer token de Chrome Extension, valida Extension ID, lo encripta y guarda en BD
    """
    
    # ✅ VALIDACIÓN 1: Verificar Extension ID
    ALLOWED_EXTENSION_IDS = os.getenv("ALLOWED_EXTENSION_IDS", "").split(",")
    ALLOWED_EXTENSION_IDS = [id.strip() for id in ALLOWED_EXTENSION_IDS if id.strip()]
    
    logger.info(f"🆔 Extension ID recibido: {x_extension_id}")
    
    if not x_extension_id or x_extension_id not in ALLOWED_EXTENSION_IDS:
        logger.warning(f"🚨 Extension ID no autorizada: {x_extension_id}")
        raise HTTPException(status_code=403, detail="Extension not authorized")
    
    logger.info(f"✅ Extension ID válida: {x_extension_id}")
    
    # ✅ VALIDACIÓN 2: Verificar autorización (SECRET KEY)
    if authorization != f"Bearer {WEBHOOK_SECRET_KEY}":
        logger.warning(f"🚨 Intento no autorizado")
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    logger.info(f"✅ Authorization válido")
    
    # ✅ VALIDACIÓN 3: Verificar token
    if not request.token or len(request.token) < 50:
        logger.error(f"❌ Token inválido: len={len(request.token) if request.token else 0}")
        raise HTTPException(status_code=400, detail="Token inválido")
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                
                # 1️⃣ VERIFICAR QUE LA CUENTA EXISTE
                cursor.execute(
                    """SELECT id_cuenta FROM cuentas_liverpool WHERE id_cuenta = %s""",
                    (request.seller_id,)
                )
                cuenta = cursor.fetchone()
                
                if not cuenta:
                    logger.error(f"❌ Cuenta {request.seller_id} no encontrada")
                    raise HTTPException(status_code=404, detail="Cuenta no existe")
                
                logger.info(f"✅ Cuenta encontrada: {request.seller_id}")
                
                # 2️⃣ ENCRIPTAR TOKEN
                cipher = Fernet(FERNET_ENCRYPTION_KEY.encode())
                token_encriptado = cipher.encrypt(request.token.encode()).decode()
                logger.info(f"✅ Token encriptado")
                
                # 3️⃣ ACTUALIZAR TABLA PRINCIPAL
                cursor.execute("""
                    UPDATE cuentas_liverpool 
                    SET 
                        token_autorizacion = %s,
                        timestamp_token = NOW(),
                        token_expira_en = NOW() + INTERVAL '24 hours',
                        fernet_encryption_key = %s
                    WHERE id_cuenta = %s
                """, (token_encriptado, FERNET_ENCRYPTION_KEY, request.seller_id))
                
                logger.info(f"✅ Token actualizado en cuentas_liverpool")
                
                # 4️⃣ ROTAR EN HISTORIAL (ÚLTIMOS 5 TOKENS)
                cursor.execute("""
                    UPDATE bearer_token_history 
                    SET token_order = token_order + 1 
                    WHERE id_cuenta = %s AND token_order < 5
                """, (request.seller_id,))
                
                cursor.execute("""
                    DELETE FROM bearer_token_history 
                    WHERE id_cuenta = %s AND token_order > 5
                """, (request.seller_id,))
                
                cursor.execute("""
                    INSERT INTO bearer_token_history 
                    (id_cuenta, token_encriptado, captured_at, token_order, status)
                    VALUES (%s, %s, NOW(), 1, 'active')
                """, (request.seller_id, token_encriptado))
                
                logger.info(f"✅ Token rotado en historial")
                
                # 5️⃣ LOG DE AUDITORÍA
                cursor.execute("""
                    INSERT INTO bearer_capture_log 
                    (id_cuenta, action, timestamp, details)
                    VALUES (%s, 'captured', NOW(), %s)
                """, (request.seller_id, f"Extension ID: {x_extension_id} | Token: {request.token[:30]}..."))
                
                logger.info(f"✅ Log de auditoría creado")
                
                # 6️⃣ CONTAR TOKENS ACTIVOS
                cursor.execute("""
                    SELECT COUNT(*) FROM bearer_token_history 
                    WHERE id_cuenta = %s AND status = 'active'
                """, (request.seller_id,))
                
                num_tokens = cursor.fetchone()[0]
                logger.info(f"📊 Tokens en historial: {num_tokens}/5")
                
                # 7️⃣ COMMIT
                conn.commit()
                logger.info(f"✅ BD actualizada")
                
                # 8️⃣ ENVIAR TELEGRAM
                msg = f"""🔐 *Bearer capturado*
🆔 Extension: `{x_extension_id[-8:]}`
🏪 Cuenta: `{request.seller_id}`
📦 Tokens: `{num_tokens}/5`
⏰ Válido por: `24 horas`"""
                
                enviar_telegram(msg)
                
                logger.info(f"✅ ÉXITO | Extension: {x_extension_id[-8:]} | Cuenta: {request.seller_id} | Tokens: {num_tokens}/5")
                
                return {
                    "status": "success",
                    "message": "Bearer guardado",
                    "tokens_in_history": num_tokens,
                    "extension_id_validated": x_extension_id[:8] + "..."
                }
    
    except HTTPException:
        raise
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
    
    port = int(os.getenv("PORT", 10000))
    
    logger.info(f"🚀 Iniciando Megazord Bot Webhooks en puerto {port}...")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
