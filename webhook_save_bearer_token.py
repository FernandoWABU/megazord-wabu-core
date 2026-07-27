"""
🤖 MEGAZORD - Webhook para guardar Bearer Token en DBeaver
AJUSTADO para tabla existente: bearer_token_history
Estructura de tabla:
  - id (serial4)
  - id_cuenta (varchar)
  - token_encriptado (varchar)
  - captured_at (timestamp)
  - token_order (int4)
  - status (varchar) default 'active'
"""

from flask import Flask, request, jsonify
from datetime import datetime
import psycopg
import os

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════
# 🔐 CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════

WEBHOOK_SECRET = 'render_webhook_secret_fernando_2026_v2_safe'

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://megazord_db_user:oruXN9EdtQ6Zfb7zhP0EB3HlrnHe8Nop@dpg-d7sdbol7vvec73d8uiug-a.oregon-postgres.render.com/megazord_db'
)

print('═══════════════════════════════════════════════════════════')
print('🤖 MEGAZORD - Webhook Bearer Token (AJUSTADO)')
print('═══════════════════════════════════════════════════════════')
print(f'✅ Database: {DATABASE_URL[:50]}...')
print(f'✅ Tabla: bearer_token_history')
print(f'✅ Columnas: id_cuenta, token_encriptado, captured_at, status')

# ═══════════════════════════════════════════════════════════
# 🔗 ENDPOINT PRINCIPAL
# ═══════════════════════════════════════════════════════════

@app.route('/api/save-bearer-token', methods=['POST'])
def save_bearer_token():
    """
    Recibe el token bearer y lo guarda en bearer_token_history
    """
    try:
        print('═══════════════════════════════════════════════════════════')
        print('📨 POST /api/save-bearer-token')
        
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
        account_id = data.get('account_id', 'LVP_01')
        
        print(f'📋 Datos recibidos:')
        print(f'   - Token: {token[:50] if token else "FALTA"}...')
        print(f'   - Timestamp: {timestamp}')
        print(f'   - Account: {account_id}')
        
        # Validar token
        if not token or len(token) < 100:
            print('❌ Token inválido')
            return jsonify({'success': False, 'error': 'Token inválido'}), 400
        
        print('✅ Token válido')
        
        # Guardar en BD
        print('💾 Guardando en base de datos...')
        result = save_to_database(token, timestamp, account_id)
        
        if result['success']:
            print(f"✅ Token guardado con ID: {result.get('id', 'N/A')}")
            return jsonify({
                'success': True,
                'message': 'Token guardado exitosamente',
                'id': result.get('id'),
                'timestamp': datetime.now().isoformat()
            }), 200
        else:
            print(f"❌ Error: {result.get('error')}")
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

def save_to_database(token, timestamp, account_id):
    """
    Guarda el bearer token en tabla bearer_token_history
    Estructura existente:
      - id_cuenta (varchar)
      - token_encriptado (varchar) 
      - captured_at (timestamp)
      - status (varchar) default 'active'
    """
    try:
        print('🌐 Conectando a PostgreSQL...')
        
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                print('✅ Conexión exitosa')
                
                # Preparar datos
                captured_at = timestamp or datetime.now().isoformat()
                
                # ✅ SQL AJUSTADO para tabla existente
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
                
                print(f'📝 INSERT en bearer_token_history')
                print(f'   - id_cuenta: {account_id}')
                print(f'   - token_encriptado: {token[:30]}...')
                print(f'   - captured_at: {captured_at}')
                print(f'   - status: active')
                
                # Ejecutar INSERT
                cur.execute(sql, (account_id, token, captured_at))
                conn.commit()
                
                # Obtener ID
                result = cur.fetchone()
                token_id = result[0] if result else None
                
                print(f'✅ Insertado exitosamente con ID: {token_id}')
                
                return {
                    'success': True,
                    'id': token_id,
                    'message': f'Token guardado en ID {token_id}'
                }
                
    except psycopg.Error as e:
        print(f'❌ Error PostgreSQL: {str(e)}')
        return {
            'success': False,
            'error': f'Database error: {str(e)}'
        }
    except Exception as e:
        print(f'❌ Error: {str(e)}')
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
                cur.execute("SELECT COUNT(*) FROM bearer_token_history;")
                count = cur.fetchone()[0]
                return jsonify({
                    'status': 'OK',
                    'database': 'Connected',
                    'bearer_tokens_count': count,
                    'timestamp': datetime.now().isoformat()
                }), 200
    except Exception as e:
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
    """Obtiene los últimos 10 tokens capturados"""
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ═══════════════════════════════════════════════════════════
# 🚀 INICIAR SERVIDOR
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    print('🚀 Iniciando servidor Flask...')
    print('📍 Endpoints disponibles:')
    print('   - POST /api/save-bearer-token (guarda token)')
    print('   - GET /health (verifica salud)')
    print('   - GET /api/bearer-tokens/recent (últimos 10)')
    print('')
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )
