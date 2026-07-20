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

# CARGAR VARIABLES DE ENTORNO
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY", "tu-clave-super-segura")
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
# TELEGRAM
# ==========================================

def enviar_telegram(mensaje):
    """Envía mensaje a Telegram"""
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_WMT:
            logger.warning("⚠️ Telegram no configurado, saltando notificación")
            return
        
        import requests
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
    except Exception as e:
        logger.error(f"❌ Error enviando Telegram: {e}")

# ==========================================
# WEBHOOK: CAPTURA DE BEARER TOKEN
# ==========================================

@app.post("/api/capture-bearer")
async def capture_bearer_token(
    token: str,
    seller_id: str = "68CAF9EE564AF52E6",
    auth_header: str = Header(None)
):
    """
    🔐 WEBHOOK: Recibe Bearer token de Chrome Extension
    
    Pasos:
    1. Valida Secret Key
    2. Valida token (mínimo 50 chars)
    3. Busca cuenta en cuentas_liverpool
    4. Encripta token con Fernet
    5. Guarda en tabla principal (actualiza)
    6. Rota en historial (últimos 5 tokens)
    7. Log de auditoría
    8. Notificación Telegram
    
    Args:
        token: Bearer token extraído de Authorization header
        seller_id: ID de la tienda
        auth_header: Secret key para validar que viene de Chrome Extension
    """
    
    # 1️⃣ VALIDAR SECRET KEY
    if auth_header != f"Bearer {WEBHOOK_SECRET_KEY}":
        logger.warning(f"🚨 Intento no autorizado desde {seller_id}")
        raise HTTPException(status_code=401, detail="Unauthorized - Invalid secret key")
    
    # 2️⃣ VALIDAR TOKEN
    if not token or len(token) < 50:
        logger.error(f"❌ Token inválido: len={len(token) if token else 0}")
        raise HTTPException(status_code=400, detail="Token inválido o muy corto")
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                
                # 3️⃣ VERIFICAR QUE LA CUENTA EXISTE
                cursor.execute("""
                    SELECT id_cuenta, google_encryption_key 
                    FROM cuentas_liverpool 
                    WHERE id_cuenta = %s
                """, (seller_id,))
                
                cuenta = cursor.fetchone()
                if not cuenta:
                    logger.error(f"❌ Cuenta {seller_id} no encontrada en cuentas_liverpool")
                    raise HTTPException(status_code=404, detail=f"Cuenta {seller_id} no existe")
                
                id_cuenta, encryption_key = cuenta
                
                # 4️⃣ ENCRIPTAR TOKEN
                try:
                    cipher = Fernet(encryption_key.encode())
                    token_encriptado = cipher.encrypt(token.encode()).decode()
                except Exception as e:
                    logger.error(f"❌ Error encriptando token: {e}")
                    raise HTTPException(status_code=500, detail="Error encriptando token")
                
                # 5️⃣ ACTUALIZAR TOKEN EN TABLA PRINCIPAL
                cursor.execute("""
                    UPDATE cuentas_liverpool 
                    SET 
                        token_autorizacion = %s,
                        timestamp_token = NOW(),
                        token_expira_en = NOW() + INTERVAL '24 hours'
                    WHERE id_cuenta = %s
                """, (token_encriptado, id_cuenta))
                
                logger.info(f"✅ Token actualizado en cuentas_liverpool para {id_cuenta}")
                
                # 6️⃣ ROTAR EN BEARER_TOKEN_HISTORY
                # Desplazar órdenes
                cursor.execute("""
                    UPDATE bearer_token_history 
                    SET token_order = token_order + 1 
                    WHERE id_cuenta = %s AND token_order < 5
                """, (id_cuenta,))
                
                # Eliminar más viejos
                cursor.execute("""
                    DELETE FROM bearer_token_history 
                    WHERE id_cuenta = %s AND token_order > 5
                """, (id_cuenta,))
                
                # Insertar nuevo como order=1
                cursor.execute("""
                    INSERT INTO bearer_token_history 
                    (id_cuenta, token_encriptado, captured_at, token_order, status)
                    VALUES (%s, %s, NOW(), 1, 'active')
                """, (id_cuenta, token_encriptado))
                
                logger.info(f"✅ Token guardado en historial (order=1)")
                
                # 7️⃣ LOG DE AUDITORÍA
                cursor.execute("""
                    INSERT INTO bearer_capture_log 
                    (id_cuenta, action, timestamp, details)
                    VALUES (%s, 'captured', NOW(), %s)
                """, (id_cuenta, f"Chrome Extension capturó Bearer. Primeros 30 chars: {token[:30]}..."))
                
                # 8️⃣ CONTAR TOKENS EN HISTORIAL
                cursor.execute("""
                    SELECT COUNT(*) FROM bearer_token_history 
                    WHERE id_cuenta = %s AND status = 'active'
                """, (id_cuenta,))
                
                num_tokens = cursor.fetchone()[0]
                
                conn.commit()
                
                # 9️⃣ NOTIFICACIÓN TELEGRAM
                timestamp_expira = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
                
                msg = (
                    f"🔐 *Bearer token capturado*\n\n"
                    f"🏪 Cuenta: `{id_cuenta}`\n"
                    f"⏰ Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"📦 Tokens en historial: `{num_tokens}/5`\n"
                    f"✅ Válido por: `24 horas`\n"
                    f"🔄 Expira: `{timestamp_expira}`"
                )
                
                enviar_telegram(msg)
                
                logger.info(f"✅ WEBHOOK EXITOSO | Cuenta: {id_cuenta} | Tokens: {num_tokens}/5")
                
                return {
                    "status": "success",
                    "message": f"Bearer capturado y guardado para {id_cuenta}",
                    "tokens_in_history": num_tokens,
                    "expires_at": timestamp_expira,
                    "captured_at": datetime.now().isoformat()
                }
    
    except psycopg2.Error as e:
        logger.error(f"❌ Error de BD: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}")
        enviar_telegram(f"🚨 *ERROR CRÍTICO en webhook*\n{str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ==========================================
# DEBUG ENDPOINT: VER TOKENS GUARDADOS
# ==========================================

@app.get("/api/bearer-history/{id_cuenta}")
async def get_bearer_history(id_cuenta: str):
    """
    🔍 DEBUG: Ver los últimos 5 tokens capturados (sin exponer los tokens reales)
    
    Uso: GET /api/bearer-history/68CAF9EE564AF52E6
    """
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                
                cursor.execute("""
                    SELECT 
                        id,
                        token_order,
                        captured_at,
                        status,
                        LENGTH(token_encriptado) as token_size
                    FROM bearer_token_history 
                    WHERE id_cuenta = %s 
                    ORDER BY token_order ASC
                    LIMIT 5
                """, (id_cuenta,))
                
                tokens = cursor.fetchall()
                
                if not tokens:
                    return {
                        "status": "empty",
                        "message": "No hay tokens guardados aún",
                        "id_cuenta": id_cuenta
                    }
                
                return {
                    "status": "success",
                    "id_cuenta": id_cuenta,
                    "total_tokens": len(tokens),
                    "tokens": [
                        {
                            "order": row[1],
                            "captured_at": row[2].isoformat() if row[2] else None,
                            "status": row[3],
                            "encrypted_size_bytes": row[4]
                        }
                        for row in tokens
                    ]
                }
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return {"status": "error", "message": str(e)}

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
