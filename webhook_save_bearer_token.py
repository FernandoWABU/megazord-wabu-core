"""
🤖 MEGAZORD - Webhook Bearer Token - VERSIÓN DEFINITIVA CON FLASK-CORS
La versión más robusta posible con CORS habilitado correctamente
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import psycopg
import os
import logging

# ═══════════════════════════════════════════════════════════
# 🔧 CONFIGURACIÓN LOGGING
# ═══════════════════════════════════════════════════════════

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ✅ HABILITAR CORS - FORMA CORRECTA CON FLASK-CORS
CORS(app, 
     origins="*",
     allow_headers=["Content-Type", "X-Webhook-Secret", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     supports_credentials=True,
     max_age=3600)

logger.info('═══════════════════════════════════════════════════════════')
logger.info('🤖 MEGAZORD - Webhook Bearer Token (DEFINITIVO)')
logger.info('═══════════════════════════════════════════════════════════')

# ═══════════════════════════════════════════════════════════
# 🔐 CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════

WEBHOOK_SECRET = 'render_webhook_secret_fernando_2026_v2_safe'

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://megazord_db_user:oruXN9EdtQ6Zfb7zhP0EB3HlrnHe8Nop@dpg-d7sdbol7vvec73d8uiug-a.oregon-postgres.render.com/megazord_db'
)

logger.info(f'✅ Database: {DATABASE_URL[:60]}...')
logger.info(f'✅ CORS: Habilitado para todas las origins')
logger.info(f'✅ Flask-CORS cargado correctamente')

# ═══════════════════════════════════════════════════════════
# 🔗 ENDPOINT PRINCIPAL
# ═══════════════════════════════════════════════════════════

@app.route('/api/save-bearer-token', methods=['POST', 'OPTIONS'])
def save_bearer_token():
    """
    Recibe el token bearer y lo guarda en bearer_token_history
    """
    logger.debug('═══════════════════════════════════════════════════════════')
    logger.debug(f'📨 Recibido {request.method} /api/save-bearer-token')
    logger.debug(f'🌍 Origin: {request.origin}')
    logger.debug(f'📍 Remote: {request.remote_addr}')
    
    # Flask-CORS maneja OPTIONS automáticamente
    if request.method == "OPTIONS":
        logger.debug('✅ OPTIONS (preflight) manejado por Flask-CORS')
        return '', 204
    
    try:
        # Verificar secret
        secret = request.headers.get('X-Webhook-Secret')
        if not secret:
            logger.error('❌ X-Webhook-Secret NO está en headers')
            return jsonify({'success': False, 'error': 'Missing X-Webhook-Secret'}), 400
        
        if secret != WEBHOOK_SECRET:
            logger.error(f'❌ Secret incorrecto: {secret[:20]}...')
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
        logger.info('✅ Secret validado')
        
        # Obtener datos
        data = request.get_json()
        token = data.get('bearer_token')
        timestamp = data.get('timestamp')
        account_id = data.get('account_id', 'LVP_01')
        
        logger.info(f'📋 Token recibido: {token[:50] if token else "FALTA"}...')
        logger.info(f'   Timestamp: {timestamp}')
        logger.info(f'   Account: {account_id}')
        
        # Validar
        if not token or len(token) < 100:
            logger.error('❌ Token inválido')
            return jsonify({'success': False, 'error': 'Token inválido'}), 400
        
        logger.info('✅ Token válido')
        
        # Guardar en BD
        result = save_to_database(token, timestamp, account_id)
        
        if result['success']:
            logger.info(f"✅ Token guardado con ID: {result.get('id')}")
            response = {
                'success': True,
                'message': 'Token guardado exitosamente',
                'id': result.get('id'),
                'timestamp': datetime.now().isoformat()
            }
            return jsonify(response), 200
        else:
            logger.error(f"❌ Error BD: {result.get('error')}")
            return jsonify({
                'success': False,
                'error': result.get('error')
            }), 500
            
    except Exception as e:
        logger.error(f'❌ Error: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        logger.debug('═══════════════════════════════════════════════════════════')

# ═══════════════════════════════════════════════════════════
# 💾 GUARDAR EN BASE DE DATOS
# ═══════════════════════════════════════════════════════════

def save_to_database(token, timestamp, account_id):
    """Guarda en tabla bearer_token_history"""
    try:
        logger.info('🌐 Conectando a PostgreSQL...')
        
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                logger.info('✅ Conexión exitosa')
                
                captured_at = timestamp or datetime.now().isoformat()
                
                sql = """
                INSERT INTO bearer_token_history (
                    id_cuenta,
                    token_encriptado,
                    captured_at,
                    status
                ) VALUES (
                    %s, %s, %s, 'active'
                )
                RETURNING id;
                """
                
                logger.info(f'📝 Insertando en bearer_token_history')
                cur.execute(sql, (account_id, token, captured_at))
                conn.commit()
                
                result = cur.fetchone()
                token_id = result[0] if result else None
                
                logger.info(f'✅ INSERT exitoso con ID: {token_id}')
                
                return {
                    'success': True,
                    'id': token_id,
                    'message': f'Token guardado en ID {token_id}'
                }
                
    except psycopg.Error as e:
        logger.error(f'❌ Error PostgreSQL: {str(e)}', exc_info=True)
        return {'success': False, 'error': f'Database error: {str(e)}'}
    except Exception as e:
        logger.error(f'❌ Error: {str(e)}', exc_info=True)
        return {'success': False, 'error': f'Error: {str(e)}'}

# ═══════════════════════════════════════════════════════════
# 🏥 HEALTH CHECK
# ═══════════════════════════════════════════════════════════

@app.route('/health', methods=['GET', 'OPTIONS'])
def health():
    """Health check con CORS headers"""
    if request.method == "OPTIONS":
        return '', 204
    
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM bearer_token_history;")
                count = cur.fetchone()[0]
                return jsonify({
                    'status': 'OK',
                    'database': 'Connected',
                    'bearer_tokens_count': count,
                    'cors': 'Enabled',
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
# 📊 GET ÚLTIMOS TOKENS
# ═══════════════════════════════════════════════════════════

@app.route('/api/bearer-tokens/recent', methods=['GET', 'OPTIONS'])
def get_recent_tokens():
    """Obtiene últimos 10 tokens"""
    if request.method == "OPTIONS":
        return '', 204
    
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
        logger.error(f'Error: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════
# 🚀 INICIAR SERVIDOR
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    logger.info('🚀 Iniciando servidor Flask con CORS HABILITADO...')
    logger.info('📍 Endpoints:')
    logger.info('   - POST /api/save-bearer-token')
    logger.info('   - GET /health')
    logger.info('   - GET /api/bearer-tokens/recent')
    logger.info('🔓 CORS: Totalmente habilitado (flask-cors)')
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )
