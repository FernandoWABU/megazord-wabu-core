"""
🤖 MEGAZORD - Webhook COMPLETO
Soporta AMBOS: Liverpool (memoria) + Chrome Extension (PostgreSQL)
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
from functools import wraps
import psycopg
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Flask-CORS global
CORS(app, 
     origins="*",
     allow_headers=["Content-Type", "X-Webhook-Secret", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     supports_credentials=False,
     max_age=3600)

WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET_KEY', 'render_webhook_secret_fernando_2026_v2_safe')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://megazord_db_user:oruXN9EdtQ6Zfb7zhP0EB3HlrnHe8Nop@dpg-d7sdbol7vvec73d8uiug-a.oregon-postgres.render.com/megazord_db')

logger.info('═' * 60)
logger.info('🤖 MEGAZORD - Webhook COMPLETO FINAL')
logger.info('✅ Liverpool (memoria) + Chrome Extension (PostgreSQL)')
logger.info('═' * 60)

# Storage en memoria para Liverpool
TOKEN_STORE = {
    'latest_token': None,
    'latest_timestamp': None,
    'captured_count': 0
}

# Decorador para validar secret
def require_secret_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        secret = request.headers.get('X-Webhook-Secret')
        if not secret or secret != WEBHOOK_SECRET:
            return jsonify({'status': 'error', 'code': 401, 'message': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# ═══════════════════════════════════════════════════════════
# LIVERPOOL ENDPOINTS
# ═══════════════════════════════════════════════════════════

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
    """Recibir y procesar Bearer token de Liverpool"""
    try:
        logger.info('═' * 60)
        logger.info('🔐 POST /update-bearer recibido (LIVERPOOL)')
        logger.info('═' * 60)
        
        data = request.get_json() or {}
        token = data.get('bearer_token')
        
        if not token or len(token) < 10:
            logger.warning('❌ Token inválido')
            return jsonify({'status': 'error', 'message': 'Invalid token'}), 400
        
        TOKEN_STORE['latest_token'] = token
        TOKEN_STORE['latest_timestamp'] = data.get('timestamp', datetime.now().isoformat())
        TOKEN_STORE['captured_count'] += 1
        
        logger.info(f'✅ Token recibido: {len(token)} chars')
        logger.info(f'📊 Total capturados: {TOKEN_STORE["captured_count"]}')
        logger.info('═' * 60)
        
        return jsonify({
            'status': 'success',
            'code': 200,
            'message': 'Bearer token received and stored',
            'token_id': TOKEN_STORE['captured_count'],
            'timestamp': datetime.now().isoformat()
        }), 200
    
    except Exception as e:
        logger.error(f'❌ Error en /update-bearer: {str(e)}')
        return jsonify({'status': 'error', 'code': 500, 'message': str(e)}), 500

@app.route('/get-latest-bearer', methods=['GET'])
@require_secret_key
def get_latest_bearer():
    """Obtener Bearer token más reciente de Liverpool"""
    try:
        logger.info('🔐 GET /get-latest-bearer recibido')
        
        if not TOKEN_STORE['latest_token']:
            logger.warning('⚠️ No hay token en memoria')
            return jsonify({'status': 'error', 'message': 'No bearer token available'}), 404
        
        token = TOKEN_STORE['latest_token']
        logger.info(f'✅ Retornando token: {len(token)} chars')
        
        return jsonify({
            'status': 'success',
            'token': token,
            'captured_at': TOKEN_STORE['latest_timestamp'],
            'token_preview': token[:50] + '...',
            'total_captured': TOKEN_STORE['captured_count']
        }), 200
    
    except Exception as e:
        logger.error(f'❌ Error en /get-latest-bearer: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """Estado actual del webhook"""
    return jsonify({
        'status': 'running',
        'latest_token_available': TOKEN_STORE['latest_token'] is not None,
        'total_captured': TOKEN_STORE['captured_count'],
        'timestamp': datetime.now().isoformat()
    }), 200

# ═══════════════════════════════════════════════════════════
# CHROME EXTENSION ENDPOINT
# ═══════════════════════════════════════════════════════════

@app.route('/api/save-bearer-token', methods=['POST'])
@require_secret_key
def save_bearer_token():
    """Guarda token en PostgreSQL para Chrome Extension"""
    try:
        logger.info('═' * 60)
        logger.info('📨 POST /api/save-bearer-token recibido (CHROME EXTENSION)')
        logger.info('═' * 60)
        
        data = request.get_json() or {}
        token = data.get('bearer_token')
        
        if not token or len(token) < 100:
            logger.error('❌ Token inválido')
            return jsonify({'success': False, 'error': 'Token inválido'}), 400
        
        logger.info('✅ Token válido')
        logger.info('💾 Conectando a PostgreSQL...')
        
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                logger.info('✅ Conexión exitosa')
                
                sql = """
                INSERT INTO bearer_token_history (
                    id_cuenta,
                    token_encriptado,
                    captured_at,
                    status
                ) VALUES (%s, %s, %s, 'active')
                RETURNING id;
                """
                
                timestamp = data.get('timestamp', datetime.now().isoformat())
                account_id = data.get('account_id', 'LVP_01')
                
                cur.execute(sql, (account_id, token, timestamp))
                conn.commit()
                
                result = cur.fetchone()
                token_id = result[0] if result else None
                
                logger.info(f'✅ TOKEN GUARDADO!!! ID: {token_id}')
                logger.info('═' * 60)
                
                return jsonify({
                    'success': True,
                    'id': token_id,
                    'message': 'Token guardado exitosamente',
                    'timestamp': datetime.now().isoformat()
                }), 200
    
    except Exception as e:
        logger.error(f'❌ Error en /api/save-bearer-token: {str(e)}')
        logger.error('═' * 60)
        return jsonify({'success': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════
# HEALTH CHECK CON BD
# ═══════════════════════════════════════════════════════════

@app.route('/api/health', methods=['GET'])
def health_db():
    """Health check con verificación de BD"""
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM bearer_token_history;")
                count = cur.fetchone()[0]
                return jsonify({
                    'status': 'OK',
                    'database': 'Connected',
                    'cors': 'Enabled (Flask-CORS)',
                    'bearer_tokens': count,
                    'timestamp': datetime.now().isoformat()
                }), 200
    except Exception as e:
        logger.error(f'Health check error: {str(e)}')
        return jsonify({
            'status': 'ERROR',
            'database': 'Disconnected',
            'error': str(e)
        }), 500

# ═══════════════════════════════════════════════════════════
# GET ÚLTIMOS TOKENS
# ═══════════════════════════════════════════════════════════

@app.route('/api/bearer-tokens/recent', methods=['GET'])
def get_recent_tokens():
    """Obtiene últimos 10 tokens"""
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                sql = """
                SELECT id, id_cuenta, captured_at, status 
                FROM bearer_token_history 
                ORDER BY id DESC 
                LIMIT 10;
                """
                cur.execute(sql)
                rows = cur.fetchall()
                
                tokens = []
                for row in rows:
                    tokens.append({
                        'id': row[0],
                        'account_id': row[1],
                        'captured_at': row[2].isoformat() if row[2] else None,
                        'status': row[3]
                    })
                
                return jsonify({
                    'success': True,
                    'count': len(tokens),
                    'tokens': tokens
                }), 200
    except Exception as e:
        logger.error(f'Error: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════
# ERROR HANDLERS
# ═══════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    logger.warning('❌ 404 - Endpoint no encontrado')
    return jsonify({'status': 'error', 'code': 404, 'message': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(error):
    logger.error(f'❌ 500 - Server error: {error}')
    return jsonify({'status': 'error', 'code': 500, 'message': 'Internal server error'}), 500

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    logger.info('═' * 60)
    logger.info(f'🚀 MEGAZORD Webhook iniciando en puerto {port}')
    logger.info('═' * 60)
    logger.info('✅ Endpoints disponibles:')
    logger.info('   POST /update-bearer (Liverpool)')
    logger.info('   GET /get-latest-bearer (Liverpool)')
    logger.info('   GET /status (Estado)')
    logger.info('   GET /health (Health check)')
    logger.info('   POST /api/save-bearer-token (Chrome Extension)')
    logger.info('   GET /api/health (Health DB)')
    logger.info('   GET /api/bearer-tokens/recent (Últimos tokens)')
    logger.info('═' * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False)
