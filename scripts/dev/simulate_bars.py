import sys
import os
import random
from datetime import datetime, timedelta, timezone

# Asegurar que podemos importar el backend desde la raíz
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from backend.database import SessionLocal, engine, Base
    from backend.models import Bar
except ImportError as e:
    print(f"Error de importación: {e}")
    print("Asegúrate de ejecutar este script desde la carpeta raíz 'd:\\jesse_ai'")
    sys.exit(1)

def create_simulated_bars(bot_id="bot-1", count=100):
    print(f"--- Generando {count} barras simuladas para {bot_id} ---")
    
    # Crear sesión de DB
    db = SessionLocal()
    
    # Asegurar que las tablas existan
    Base.metadata.create_all(bind=engine)
    
    # Configuración de la simulación
    price = 15000.0
    start_time = datetime.now(timezone.utc) - timedelta(minutes=count)
    new_bars = []
    
    print("Generando datos...")
    for i in range(count):
        # Random walk simple
        move = (random.random() - 0.5) * 20  # Movimiento aleatorio +/- 10
        price += move
        
        # Generar OHLC consistente
        open_p = price
        close_p = price + (random.random() - 0.5) * 10
        high_p = max(open_p, close_p) + random.random() * 5
        low_p = min(open_p, close_p) - random.random() * 5
        volume = int(random.randint(100, 5000))
        
        ts = start_time + timedelta(minutes=i)
        
        bar = Bar(
            bot_id=bot_id,
            symbol="MNQ",
            timeframe="1m",
            ts_utc=ts,
            open=round(open_p, 2),
            high=round(high_p, 2),
            low=round(low_p, 2),
            close=round(close_p, 2),
            volume=volume,
            mode="SIMULATED"
        )
        new_bars.append(bar)
    
    try:
        db.bulk_save_objects(new_bars)
        db.commit()
        print(f"✅ Insertadas {len(new_bars)} barras correctamente en SQLite.")
    except Exception as e:
        print(f"❌ Error insertando barras: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_simulated_bars()