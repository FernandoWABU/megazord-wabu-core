#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 MEGAZORD - Railway Webhook Simple
Para recibir Bearer tokens de Chrome Extension
VERSIÓN EMERGENCIA: psycopg 3.x (sin libpq error)
"""

import os
import json
import logging
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg  # ✅ PSYCOPG 3.x (no psycopg2)
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Flask
app = Flask(__name__)
CORS(app)

# Database config
DATABASE_URL = os.getenv('DATABASE_URL')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET_KEY', 'render_webhook_secret_fernando_2026_v2_safe')

logger.info('✅ Webhook iniciado')
logger.info(f'🔐 Webhook Secret Key cargado: {"*" * 40}')
logger.info(f'📊 Database URL configurada: {"*" * 30}')

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def require_secret_key(f):
    """Decorador para validar X-Webhook-Secret header"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        secret = request.headers.get('X-Webhook-Secret')
        
        if not secret:
            logger.warning('❌ Request sin X-Webhook-Secret header')
            return jsonify({'status': 'error', 'message': 'Missing X-Webhook-Secret header'}), 401
        
        if secret != WEBHOOK_SECRET:
            logger.warning(f'❌ Secret incorrecto: {secret[:20]}...')
            return jsonify({'status': 'error', 'message': 'Invalid X-Webhook-Secret'}), 403
        
        logger.info('✅ Secret validado correctamente')
        return f(*args, **kwargs)
    
    return decorated_function

def save_bearer_token_to_db(token):
    """Guardar Bearer Token en PostgreSQL usando psycopg 3.x"""
    try:
        logger.info(f'📊 Conectando a PostgreSQL: {DATABASE_URL[:50]}...')
        
        # Conectar con psycopg 3.x
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                
                # Crear tabla si no existe
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS bearer_token_history (
                        id SERIAL PRIMARY KEY,
                        token TEXT NOT NULL,
                        captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        source VARCHAR(100),
                        active BOOLEAN DEFAULT TRUE
                    )
                ''')
                
                # Insertar token
                cur.execute('''
                    INSERT INTO bearer_token_history (token, source)
                    VALUES (%s, %s)
                    RETURNING id
                ''', (token, 'chrome_extension'))
                
                token_id = cur.fetchone()[0]
                conn.commit()
                
                logger.info(f'✅ Token guardado en DB con ID: {token_id}')
                logger.info(f'🔐 Token primeros 50 chars: {token[:50]}...')
                
                return True, token_id
                
    except psycopg.Error as e:
        logger.error(f'❌ Error PostgreSQL: {e}')
        return False, str(e)
    except Exception as e:
        logger.error(f'❌ Error general: {e}')
        return False, str(e)

# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()}), 200

@app.route('/update-bearer', methods=['POST'])
@require_secret_key
def update_bearer():
    """Recibir y guardar Bearer token de Chrome Extension"""
    try:
        logger.info('🔐 POST /update-bearer recibido')
        
        data = request.get_json()
        
        if not data or 'bearer_token' not in data:
            logger.warning('❌ Request sin bearer_token en payload')
            return jsonify({'status': 'error', 'message': 'Missing bearer_token'}), 400
        
        token = data.get('bearer_token')
        source = data.get('source', 'unknown')
        
        logger.info(f'📋 Source: {source}')
        logger.info(f'🔐 Token recibido (primeros 50): {token[:50]}...')
        
        # Guardar en DB
        success, result = save_bearer_token_to_db(token)
        
        if success:
            logger.info(f'✅ Token procesado exitosamente')
            return jsonify({
                'status': 'success',
                'message': 'Bearer token received and saved',
                'token_id': result,
                'timestamp': datetime.now().isoformat()
            }), 200
        else:
            logger.error(f'❌ Error guardando token: {result}')
            return jsonify({
                'status': 'error',
                'message': f'Error saving token: {result}'
            }), 500
    
    except Exception as e:
        logger.error(f'❌ Error en /update-bearer: {e}')
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/get-latest-bearer', methods=['GET'])
@require_secret_key
def get_latest_bearer():
    """Obtener el Bearer token más reciente"""
    try:
        logger.info('🔐 GET /get-latest-bearer recibido')
        
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT id, token, captured_at, source
                    FROM bearer_token_history
                    WHERE active = TRUE
                    ORDER BY captured_at DESC
                    LIMIT 1
                ''')
                
                result = cur.fetchone()
                
                if result:
                    token_id, token, captured_at, source = result
                    logger.info(f'✅ Token encontrado ID: {token_id}')
                    
                    return jsonify({
                        'status': 'success',
                        'token_id': token_id,
                        'token': token,
                        'captured_at': captured_at.isoformat(),
                        'source': source
                    }), 200
                else:
                    logger.warning('⚠️ No hay token en DB')
                    return jsonify({
                        'status': 'error',
                        'message': 'No bearer token found'
                    }), 404
    
    except Exception as e:
        logger.error(f'❌ Error en /get-latest-bearer: {e}')
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    logger.info(f'🚀 Iniciando servidor en puerto {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
