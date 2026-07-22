#!/usr/bin/env python3
"""
Script standalone para resetear Circuit Breaker desde terminal local.
Uso: python reset_breaker.py
"""
import os
import psycopg2
from dotenv import load_dotenv

def forzar_reinicio_breaker():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print("❌ Falla: DATABASE_URL no encontrada en .env")
        return False
    
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Verificar que tabla existe
                cur.execute("""
                    SELECT EXISTS(
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_name='config_sistema'
                    )
                """)
                if not cur.fetchone()[0]:
                    print("❌ Tabla config_sistema no existe. Crear primero con SQL.")
                    return False
                
                # Actualizar bandera
                cur.execute("UPDATE config_sistema SET valor = 'true' WHERE clave = 'reset_circuit_breaker'")
                conn.commit()
        
        print("✅ ¡ÉXITO! Circuit Breaker marcado para reinicio.")
        print("📌 En el próximo ciclo (12 min), Megazord leerá la bandera y se reseteará.")
        return True
        
    except Exception as e:
        print(f"❌ Error conectando a BD: {e}")
        return False

if __name__ == "__main__":
    success = forzar_reinicio_breaker()
    exit(0 if success else 1)
