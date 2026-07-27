"""
🤖 MEGAZORD - Webhook para guardar Bearer Token en DBeaver
Recibe token de la extensión Chrome y lo guarda en la BD
Método: POST /api/save-bearer-token
"""

from flask import Flask, request, jsonify
from datetime import datetime
import psycopg
import os
import sys

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════
# 🔐 CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════

WEBHOOK_SECRET = 'render_webhook_secret_fernando_2026_v2_safe'

# PostgreSQL Connection String
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://megazord_db_user:oruXN9EdtQ6Zfb7zhP0EB3HlrnHe8Nop@dpg-d7sdbol7vvec73d8uiug-a.oregon-postgres.render.com/megazord_db'
)

print('═══════════════════════════════════════════════════════════')
print('🤖 MEGAZORD - Webhook Bearer Token Saver')
print('═══════════════════════════════════════════════════════════')
print(f'✅ Database: {DATABASE_URL[:50]}...')
print(f'✅ Webhook Secret: {WEBHOOK_SECRET[:30]}...')

# ═══════════════════════════════════════════════════════════
# 🔗 ENDPOINT PRINCIPAL
# ═══════════════════════════════════════════════════════════

@app.route('/api/save-bearer-token', methods=['POST'])
def save_bearer_token():
    """
    Recibe el token bearer y lo guarda en la base de datos
    """
    try:
        print('═══════════════════════════════════════════════════════════')
        print('📨 SOLICITUD RECIBIDA - POST /api/save-bearer-token')
        
        # Verificar secret
        secret = request.headers.get('X-Webhook-Secret')
        if secret != WEBHOOK_SECRET:
            print('❌ Secret incorrecto')
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
        print('✅ Secret validado')
        
        # Obtener datos
        data = request.get_json()
        token = data.get('bearer_token')
        timestamp = data.get('timestamp')
        source = data.get('source', 'chrome_extension_bearer')
        account_id = data.get('account_id', 'LVP_01')
        
        print(f'📋 Datos recibidos:')
        print(f'   - Token: {token[:50] if token else "FALTA"}...')
        print(f'   - Timestamp: {timestamp}')
        print(f'   - Source: {source}')
        print(f'   - Account: {account_id}')
        
        # Validar
        if not token or len(token) < 100:
            print('❌ Token inválido')
            return jsonify({'success': False, 'error': 'Token inválido'}), 400
        
        print('✅ Token válido')
        
        # Guardar en BD
        print('💾 Guardando en base de datos...')
        result = save_to_database(token, timestamp, source, account_id)
        
        if result['success']:
            print(f"✅ Token guardado con ID: {result.get('id', 'N/A')}")
            return jsonify({
                'success': True,
                'message': 'Token guardado exitosamente',
                'id': result.get('id'),
                'timestamp': datetime.now().isoformat()
            }), 200
        else:
            print(f"❌ Error guardando: {result.get('error')}")
            return jsonify({
                'success': False,
                'error': result.get('error')
            }), 500
            
    except Exception as e:
        print(f'❌ Error: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        print('═══════════════════════════════════════════════════════════')

# ═══════════════════════════════════════════════════════════
# 💾 GUARDAR EN BASE DE DATOS
# ═══════════════════════════════════════════════════════════

def save_to_database(token, timestamp, source, account_id):
    """
    Guarda el bearer token en la tabla bearer_token_history
    """
    try:
        print('🌐 Conectando a PostgreSQL...')
        
        # Conectar
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                print('✅ Conexión exitosa')
                
                # Preparar datos
                captured_at = timestamp or datetime.now().isoformat()
                
                # SQL INSERT
                sql = """
                INSERT INTO bearer_token_history (
                    id_cuenta,
                    bearer_token,
                    captured_at,
                    source,
                    token_status
                ) VALUES (
                    %s, %s, %s, %s, 'active'
                )
                RETURNING id;
                """
                
                print(f'📝 SQL: INSERT INTO bearer_token_history')
                print(f'   - id_cuenta: {account_id}')
                print(f'   - token_length: {len(token)}')
                print(f'   - captured_at: {captured_at}')
                print(f'   - source: {source}')
                
                # Ejecutar
                cur.execute(sql, (account_id, token, captured_at, source))
                conn.commit()
                
                # Obtener ID
                token_id = cur.fetchone()[0]
                
                print(f'✅ Insertado con ID: {token_id}')
                
                return {
                    'success': True,
                    'id': token_id,
                    'message': f'Token guardado en BD con ID {token_id}'
                }
                
    except psycopg.Error as e:
        print(f'❌ Error PostgreSQL: {str(e)}')
        return {
            'success': False,
            'error': f'Database error: {str(e)}'
        }
    except Exception as e:
        print(f'❌ Error general: {str(e)}')
        return {
            'success': False,
            'error': f'Error: {str(e)}'
        }

# ═══════════════════════════════════════════════════════════
# 🏥 HEALTH CHECK
# ═══════════════════════════════════════════════════════════

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                return jsonify({
                    'status': 'OK',
                    'database': 'Connected',
                    'timestamp': datetime.now().isoformat()
                }), 200
    except Exception as e:
        return jsonify({
            'status': 'ERROR',
            'database': 'Disconnected',
            'error': str(e)
        }), 500

# ═══════════════════════════════════════════════════════════
# 🚀 INICIAR SERVIDOR
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    print('🚀 Iniciando servidor...')
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )