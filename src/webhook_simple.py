#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 MEGAZORD - Railway Webhook MÍNIMO
Para recibir Bearer tokens de Chrome Extension
VERSIÓN NUCLEAR: SIN PostgreSQL (evita libpq error)
"""

import os
import json
import logging
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Flask
app = Flask(__name__)
CORS(app)

# Config
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET_KEY', 'render_webhook_secret_fernando_2026_v2_safe')

logger.info('✅ Webhook iniciado - VERSIÓN MÍNIMA (sin PostgreSQL)')
logger.info(f'🔐 Webhook Secret Key: {"*" * 40}')

# Storage en memoria (para esta sesión)
TOKEN_STORE = {
    'latest_token': None,
    'latest_timestamp': None,
    'captured_count': 0
}

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
            return jsonify({
                'status': 'error',
                'code': 401,
                'message': 'Missing X-Webhook-Secret header'
            }), 401
        
        if secret != WEBHOOK_SECRET:
            logger.warning(f'❌ Secret incorrecto: {secret[:20]}...')
            return jsonify({
                'status': 'error',
                'code': 403,
                'message': 'Invalid X-Webhook-Secret'
            }), 403
        
        logger.info('✅ Secret validado correctamente')
        return f(*args, **kwargs)
    
    return decorated_function

# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    logger.info('🏥 Health check')
    return jsonify({
        'status': 'ok',
        'message': 'MEGAZORD Webhook is running',
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/update-bearer', methods=['POST'])
@require_secret_key
def update_bearer():
    """Recibir y procesar Bearer token de Chrome Extension"""
    try:
        logger.info('═' * 60)
        logger.info('🔐 POST /update-bearer recibido')
        logger.info('═' * 60)
        
        # Obtener JSON
        data = request.get_json()
        
        if not data:
            logger.warning('❌ Request sin JSON payload')
            return jsonify({
                'status': 'error',
                'message': 'No JSON payload'
            }), 400
        
        if 'bearer_token' not in data:
            logger.warning('❌ Request sin bearer_token en payload')
            return jsonify({
                'status': 'error',
                'message': 'Missing bearer_token in payload'
            }), 400
        
        # Extraer datos
        token = data.get('bearer_token')
        timestamp = data.get('timestamp', datetime.now().isoformat())
        source = data.get('source', 'unknown')
        
        # Validar token
        if not token or len(token) < 10:
            logger.warning('❌ Token inválido o muy corto')
            return jsonify({
                'status': 'error',
                'message': 'Invalid token'
            }), 400
        
        # Guardar en memoria
        TOKEN_STORE['latest_token'] = token
        TOKEN_STORE['latest_timestamp'] = timestamp
        TOKEN_STORE['captured_count'] += 1
        
        # Log details
        logger.info(f'✅ Token recibido correctamente')
        logger.info(f'📋 Source: {source}')
        logger.info(f'⏰ Timestamp: {timestamp}')
        logger.info(f'🔐 Token (primeros 50 chars): {token[:50]}...')
        logger.info(f'🔐 Token largo total: {len(token)} caracteres')
        logger.info(f'📊 Total capturados en sesión: {TOKEN_STORE["captured_count"]}')
        logger.info('═' * 60)
        
        # Respuesta exitosa
        return jsonify({
            'status': 'success',
            'code': 200,
            'message': 'Bearer token received and stored',
            'token_id': TOKEN_STORE['captured_count'],
            'timestamp': datetime.now().isoformat(),
            'token_preview': token[:50] + '...'
        }), 200
    
    except Exception as e:
        logger.error(f'❌ Error en /update-bearer: {type(e).__name__}: {e}')
        return jsonify({
            'status': 'error',
            'code': 500,
            'message': f'Server error: {str(e)}'
        }), 500

@app.route('/get-latest-bearer', methods=['GET'])
@require_secret_key
def get_latest_bearer():
    """Obtener el Bearer token más reciente capturado"""
    try:
        logger.info('🔐 GET /get-latest-bearer recibido')
        
        if not TOKEN_STORE['latest_token']:
            logger.warning('⚠️ No hay token en memoria')
            return jsonify({
                'status': 'error',
                'message': 'No bearer token available'
            }), 404
        
        token = TOKEN_STORE['latest_token']
        logger.info(f'✅ Retornando token (primeros 50): {token[:50]}...')
        
        return jsonify({
            'status': 'success',
            'token': token,
            'captured_at': TOKEN_STORE['latest_timestamp'],
            'token_preview': token[:50] + '...',
            'total_captured': TOKEN_STORE['captured_count']
        }), 200
    
    except Exception as e:
        logger.error(f'❌ Error en /get-latest-bearer: {e}')
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/status', methods=['GET'])
def status():
    """Estado actual del webhook"""
    return jsonify({
        'status': 'running',
        'latest_token_available': TOKEN_STORE['latest_token'] is not None,
        'total_captured': TOKEN_STORE['captured_count'],
        'timestamp': datetime.now().isoformat()
    }), 200

# ═══════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ═══════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    logger.warning(f'❌ 404 - Endpoint no encontrado')
    return jsonify({
        'status': 'error',
        'code': 404,
        'message': 'Endpoint not found'
    }), 404

@app.errorhandler(500)
def server_error(error):
    logger.error(f'❌ 500 - Server error: {error}')
    return jsonify({
        'status': 'error',
        'code': 500,
        'message': 'Internal server error'
    }), 500

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    logger.info('═' * 60)
    logger.info(f'🚀 MEGAZORD Webhook iniciando en puerto {port}')
    logger.info('═' * 60)
    logger.info('✅ Ready to receive Bearer tokens')
    logger.info('✅ Endpoints disponibles:')
    logger.info('   POST /update-bearer (Recibir token)')
    logger.info('   GET /get-latest-bearer (Obtener token)')
    logger.info('   GET /health (Health check)')
    logger.info('   GET /status (Estado)')
    logger.info('═' * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False)
