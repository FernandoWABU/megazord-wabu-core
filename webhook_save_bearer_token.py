"""
🤖 MEGAZORD - Webhook ULTRA SIMPLE - GARANTIZADO QUE FUNCIONA
Sin Flask-CORS, solo Flask puro con manejo manual robusto de CORS
"""

from flask import Flask, request, jsonify
from datetime import datetime
import psycopg
import os

app = Flask(__name__)

WEBHOOK_SECRET = 'render_webhook_secret_fernando_2026_v2_safe'
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://megazord_db_user:oruXN9EdtQ6Zfb7zhP0EB3HlrnHe8Nop@dpg-d7sdbol7vvec73d8uiug-a.oregon-postgres.render.com/megazord_db'
)

print('═══════════════════════════════════════════════════════════')
print('🤖 MEGAZORD - Webhook ULTRA SIMPLE')
print('═══════════════════════════════════════════════════════════')

# ═══════════════════════════════════════════════════════════
# 🔓 CORS - FORMA MANUAL SIMPLE Y ROBUSTA
# ═══════════════════════════════════════════════════════════

@app.before_request
def before_request():
    """Maneja OPTIONS request para preflight"""
    if request.method == 'OPTIONS':
        response = jsonify()
        response.status_code = 200
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, DELETE')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-Webhook-Secret, Authorization')
        response.headers.add('Access-Control-Max-Age', '3600')
        return response

@app.after_request
def after_request(response):
    """Agrega headers CORS a TODAS las respuestas"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, DELETE')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-Webhook-Secret, Authorization')
    response.headers.add('Access-Control-Max-Age', '3600')
    return response

# ═══════════════════════════════════════════════════════════
# 🔗 ENDPOINT PRINCIPAL - ULTRA SIMPLE
# ═══════════════════════════════════════════════════════════

@app.route('/api/save-bearer-token', methods=['POST', 'OPTIONS'])
def save_bearer_token():
    """Recibe token y lo guarda"""
    
    print('═══════════════════════════════════════════════════════════')
    print(f'📨 {request.method} /api/save-bearer-token')
    
    # Manejar OPTIONS
    if request.method == 'OPTIONS':
        print('✅ OPTIONS (preflight) respondido')
        return '', 200
    
    try:
        data = request.get_json()
        token = data.get('bearer_token')
        account_id = data.get('account_id', 'LVP_01')
        timestamp = data.get('timestamp', datetime.now().isoformat())
        
        print(f'📋 Token: {token[:50] if token else "FALTA"}...')
        print(f'   Account: {account_id}')
        
        if not token or len(token) < 100:
            print('❌ Token inválido')
            return jsonify({'success': False, 'error': 'Token inválido'}), 400
        
        print('✅ Token válido')
        print('💾 Guardando en BD...')
        
        # Conectar y guardar
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                sql = """
                INSERT INTO bearer_token_history (
                    id_cuenta,
                    token_encriptado,
                    captured_at,
                    status
                ) VALUES (%s, %s, %s, 'active')
                RETURNING id;
                """
                
                cur.execute(sql, (account_id, token, timestamp))
                conn.commit()
                
                result = cur.fetchone()
                token_id = result[0] if result else None
                
                print(f'✅ ¡¡¡GUARDADO!!! ID: {token_id}')
                
                response = {
                    'success': True,
                    'id': token_id,
                    'message': 'Token guardado exitosamente'
                }
                
                print(f'📤 Respondiendo: {response}')
                print('═══════════════════════════════════════════════════════════')
                
                return jsonify(response), 200
    
    except Exception as e:
        print(f'❌ ERROR: {str(e)}')
        print('═══════════════════════════════════════════════════════════')
        return jsonify({'success': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════
# 🏥 HEALTH CHECK
# ═══════════════════════════════════════════════════════════

@app.route('/health', methods=['GET', 'OPTIONS'])
def health():
    """Health check"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM bearer_token_history;")
                count = cur.fetchone()[0]
                return jsonify({
                    'status': 'OK',
                    'database': 'Connected',
                    'cors': 'Enabled',
                    'bearer_tokens': count
                }), 200
    except Exception as e:
        return jsonify({
            'status': 'ERROR',
            'error': str(e)
        }), 500

# ═══════════════════════════════════════════════════════════
# 🚀 INICIAR
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    print('🚀 Iniciando con CORS manual robusto...')
    app.run(host='0.0.0.0', port=5000, debug=True)
