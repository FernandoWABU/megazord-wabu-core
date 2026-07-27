#!/usr/bin/env python3

"""
🤖 MEGAZORD - Bot Webhooks FastAPI
VERSIÓN COMPLETA: Captura Bearer tokens, actualiza cuentas_liverpool, rota 5 tokens
Endpoints:
  - POST /api/capture-bearer (original)
  - POST /api/save-bearer-token (Chrome Extension)
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
    version="2.0.0"
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
    bearer_token: str = None
    token: str = None
    seller_id: str = "LVP_01"
    account_id: str = "LVP_01"
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
# FUNCIÓN: PROCESAR BEARER TOKEN
# ==========================================

def procesar_bearer(token, seller_id, x_extension_id=None):
    """
    Lógica compartida para procesar bearer token:
    1. Valida y encripta
    2. Actualiza cuentas_liverpool
    3. Rota tokens en bearer_token_history (max 5)
    4. Audita en bearer_capture_log
    5. Envía Telegram
    """
    
    try:
        if not token or len(token) < 50:
            logger.error(f"❌ Token inválido: len={len(token) if token else 0}")
            raise ValueError("Token inválido")
        
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                
                # 1️⃣ VERIFICAR QUE LA CUENTA EXISTE
                cursor.execute(
                    """SELECT id_cuenta FROM cuentas_liverpool WHERE id_cuenta = %s""",
                    (seller_id,)
                )
                cuenta = cursor.fetchone()
                
                if not cuenta:
                    logger.error(f"❌ Cuenta {seller_id} no encontrada")
                    raise ValueError(f"Cuenta {seller_id} no existe")
                
                logger.info(f"✅ Cuenta encontrada: {seller_id}")
                
                # 2️⃣ ENCRIPTAR TOKEN
                cipher = Fernet(FERNET_ENCRYPTION_KEY.encode())
                token_encriptado = cipher.encrypt(token.encode()).decode()
                logger.info(f"✅ Token encriptado")
                
                # 3️⃣ ACTUALIZAR TABLA cuentas_liverpool
                cursor.execute("""
                    UPDATE cuentas_liverpool 
                    SET 
                        token_autorizacion = %s,
                        timestamp_token = NOW(),
                        token_expira_en = NOW() + INTERVAL '24 hours',
                        fernet_encryption_key = %s
                    WHERE id_cuenta = %s
                """, (token_encriptado, FERNET_ENCRYPTION_KEY, seller_id))
                
                logger.info(f"✅ Token actualizado en cuentas_liverpool")
                
                # 4️⃣ ROTAR EN HISTORIAL (MANTENER SOLO LOS ÚLTIMOS 5)
                # Primero: Borrar todos EXCEPTO los 4 más recientes
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
                
                # Segundo: Insertar el nuevo token
                cursor.execute("""
                    INSERT INTO bearer_token_history 
                    (id_cuenta, token_encriptado, captured_at, token_order, status)
                    VALUES (%s, %s, NOW(), 1, 'active')
                """, (seller_id, token_encriptado))
                
                logger.info(f"✅ Token rotado en historial")
                
                # 5️⃣ LOG DE AUDITORÍA
                cursor.execute("""
                    INSERT INTO bearer_capture_log 
                    (id_cuenta, action, timestamp, details)
                    VALUES (%s, 'captured', NOW(), %s)
                """, (seller_id, f"Extension ID: {x_extension_id or 'unknown'} | Token: {token[:30]}..."))
                
                logger.info(f"✅ Log de auditoría creado")
                
                # 6️⃣ CONTAR TOKENS ACTIVOS
                cursor.execute("""
                    SELECT COUNT(*) FROM bearer_token_history 
                    WHERE id_cuenta = %s AND status = 'active'
                """, (seller_id,))
                
                num_tokens = cursor.fetchone()[0]
                logger.info(f"📊 Tokens en historial: {num_tokens}/5")
                
                # 7️⃣ COMMIT
                conn.commit()
                logger.info(f"✅ BD actualizada")
                
                # 8️⃣ ENVIAR TELEGRAM
                msg = f"""🔐 *Bearer capturado*
🆔 Extension: `{x_extension_id[-8:] if x_extension_id else 'unknown'}`
🏪 Cuenta: `{seller_id}`
📦 Tokens: `{num_tokens}/5`
⏰ Válido por: `24 horas`"""
                
                enviar_telegram(msg)
                
                logger.info(f"✅ ÉXITO | Cuenta: {seller_id} | Tokens: {num_tokens}/5")
                
                return {
                    "status": "success",
                    "message": "Bearer guardado exitosamente",
                    "id": None,
                    "tokens_in_history": num_tokens,
                    "success": True
                }
    
    except Exception as e:
        logger.error(f"❌ Error procesando token: {e}")
        raise

# ==========================================
# ENDPOINT 1: CHROME EXTENSION - /api/save-bearer-token
# ==========================================

@app.post("/api/save-bearer-token")
async def save_bearer_token(
    request: BearerTokenRequest,
    x_webhook_secret: str = Header(None)
):
    """
    Endpoint para Chrome Extension
    Recibe Bearer token, actualiza cuentas_liverpool y rota en BD
    """
    
    logger.info('═' * 60)
    logger.info('📨 POST /api/save-bearer-token recibido (CHROME EXTENSION)')
    logger.info('═' * 60)
    
    # VALIDAR SECRET
    if not x_webhook_secret or x_webhook_secret != WEBHOOK_SECRET_KEY:
        logger.error('❌ Secret inválido o falta')
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    logger.info('✅ Secret validado')
    
    try:
        # Obtener token (acepta tanto 'bearer_token' como 'token')
        token = request.bearer_token or request.token
        account_id = request.account_id or request.seller_id or "LVP_01"
        
        result = procesar_bearer(token, account_id, x_extension_id="Chrome-Extension")
        
        logger.info('═' * 60)
        return result
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        logger.error('═' * 60)
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# ENDPOINT 2: BOT/MEGAZORD - /api/capture-bearer
# ==========================================

@app.post("/api/capture-bearer")
async def capture_bearer_token(
    request: BearerTokenRequest,
    authorization: str = Header(None),
    x_extension_id: str = Header(None)
):
    """
    Endpoint original para Bot/Megazord
    Valida Extension ID y Secret
    """
    
    logger.info('═' * 60)
    logger.info('📨 POST /api/capture-bearer recibido (BOT/MEGAZORD)')
    logger.info('═' * 60)
    
    # ✅ VALIDACIÓN 1: Verificar Extension ID
    ALLOWED_EXTENSION_IDS = os.getenv("ALLOWED_EXTENSION_IDS", "").split(",")
    ALLOWED_EXTENSION_IDS = [id.strip() for id in ALLOWED_EXTENSION_IDS if id.strip()]
    
    logger.info(f"🆔 Extension ID recibido: {x_extension_id}")
    
    if x_extension_id and x_extension_id not in ALLOWED_EXTENSION_IDS:
        logger.warning(f"🚨 Extension ID no autorizada: {x_extension_id}")
        raise HTTPException(status_code=403, detail="Extension not authorized")
    
    logger.info(f"✅ Extension ID válida: {x_extension_id}")
    
    # ✅ VALIDACIÓN 2: Verificar autorización (SECRET KEY)
    if authorization != f"Bearer {WEBHOOK_SECRET_KEY}":
        logger.warning(f"🚨 Intento no autorizado")
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    logger.info(f"✅ Authorization válido")
    
    try:
        # Obtener token (acepta tanto 'bearer_token' como 'token')
        token = request.bearer_token or request.token
        seller_id = request.seller_id or request.account_id or "LVP_01"
        
        result = procesar_bearer(token, seller_id, x_extension_id)
        
        logger.info('═' * 60)
        return result
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        logger.error('═' * 60)
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
        "service": "megazord-webhooks-v2",
        "endpoints": ["/api/save-bearer-token", "/api/capture-bearer"]
    }

# ==========================================
# RUN (LOCAL)
# ==========================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    
    logger.info('═' * 60)
    logger.info('🚀 Iniciando Megazord Bot Webhooks FastAPI v2.0...')
    logger.info('═' * 60)
    logger.info('✅ Endpoints disponibles:')
    logger.info('   POST /api/save-bearer-token (Chrome Extension)')
    logger.info('   POST /api/capture-bearer (Bot/Megazord)')
    logger.info('   GET /health (Health check)')
    logger.info('═' * 60)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
