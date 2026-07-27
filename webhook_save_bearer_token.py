"""
🤖 MEGAZORD - Webhook LIMPIO con Flask-CORS
SIN manejo manual de OPTIONS - Dejar que Flask-CORS haga su trabajo
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import psycopg
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ✅ ÚNICA forma correcta de manejar CORS con Flask-CORS
# SIN manejo manual de OPTIONS en las rutas
CORS(app, 
     origins="*",
     allow_headers=["Content-Type", "X-Webhook-Secret", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     supports_credentials=False,
     max_age=3600)

WEBHOOK_SECRET = 'render_webhook_secret_fernando_2026_v2_safe'
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://megazord_db_user:oruXN9EdtQ6Zfb7zhP0EB3HlrnHe8Nop@dpg-d7sdbol7vvec73d8uiug-a.oregon-postgres.render.com/megazord_db'
)

logger.info('═══════════════════════════════════════════════════════════')
logger.info('🤖 MEGAZORD - Webhook LIMPIO (Flask-CORS SOLO)')
logger.info('═══════════════════════════════════════════════════════════')
logger.info('✅ Flask-CORS habilitado globalmente')
logger.info('✅ SIN manejo manual de OPTIONS')
logger.info(f'✅ Base de datos: {DATABASE_URL[:50]}...')

# ═══════════════════════════════════════════════════════════
# 🔗 ENDPOINT - SOLO POST, SIN OPTIONS
# ═══════════════════════════════════════════════════════════

@app.route('/api/save-bearer-token', methods=['POST'])
def save_bearer_token():
    """
    Guarda token en BD
    Flask-CORS maneja OPTIONS automáticamente a nivel global
    """
    try:
        logger.info('═══════════════════════════════════════════════════════════')
        logger.info(f'📨 POST /api/save-bearer-token recibido')
        logger.info(f'   Origin: {request.origin}')
        
        # Validar secret
        secret = request.headers.get('X-Webhook-Secret')
        if not secret or secret != WEBHOOK_SECRET:
            logger.error('❌ Secret inválido o falta')
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
        logger.info('✅ Secret validado')
        
        # Obtener datos
        data = request.get_json()
        token = data.get('bearer_token')
        timestamp = data.get('timestamp', datetime.now().isoformat())
        account_id = data.get('account_id', 'LVP_01')
        
        logger.info(f'📋 Token: {token[:50] if token else "FALTA"}...')
        logger.info(f'   Account: {account_id}')
        
        # Validar
        if not token or len(token) < 100:
            logger.error('❌ Token inválido')
            return jsonify({'success': False, 'error': 'Token inválido'}), 400
        
        logger.info('✅ Token válido')
        
        # Guardar en BD
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
                
                logger.info(f'📝 Insertando token en tabla bearer_token_history')
                
                cur.execute(sql, (account_id, token, timestamp))
                conn.commit()
                
                result = cur.fetchone()
                token_id = result[0] if result else None
                
                logger.info(f'✅ ¡¡¡TOKEN GUARDADO!!! ID: {token_id}')
                
                response = {
                    'success': True,
                    'id': token_id,
                    'message': 'Token guardado exitosamente',
                    'timestamp': datetime.now().isoformat()
                }
                
                logger.info(f'📤 Respondiendo: {response}')
                logger.info('═══════════════════════════════════════════════════════════')
                
                return jsonify(response), 200
    
    except psycopg.Error as e:
        logger.error(f'❌ Error PostgreSQL: {str(e)}')
        logger.error('═══════════════════════════════════════════════════════════')
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500
    
    except Exception as e:
        logger.error(f'❌ Error: {str(e)}')
        logger.error('═══════════════════════════════════════════════════════════')
        return jsonify({'success': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════
# 🏥 HEALTH CHECK
# ═══════════════════════════════════════════════════════════

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
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
# 📊 GET ÚLTIMOS TOKENS
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
# 🚀 INICIAR
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    logger.info('🚀 Iniciando servidor Flask con CORS global (NO manual)...')
    logger.info('📍 Endpoints:')
    logger.info('   - POST /api/save-bearer-token')
    logger.info('   - GET /health')
    logger.info('   - GET /api/bearer-tokens/recent')
    logger.info('✅ Flask-CORS maneja TODOS los preflight OPTIONS automáticamente')
    
    app.run(host='0.0.0.0', port=5000, debug=True)
