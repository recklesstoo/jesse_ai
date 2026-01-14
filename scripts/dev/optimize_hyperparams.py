import sys
import os
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit

# Añadir el directorio raíz al path para poder importar el backend
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from backend.database import SessionLocal
    from backend.models import Bar
    from backend.services.ml_service import ml_service
except ImportError as e:
    print(f"Error crítico de importación: {e}")
    print("Ejecuta este script desde la raíz del proyecto: python optimize_hyperparams.py")
    sys.exit(1)

def optimize_hyperparams(bot_id="bot-1"):
    print(f"🔍 Iniciando optimización de hiperparámetros para {bot_id}...")
    
    db = SessionLocal()
    try:
        # 1. Obtener datos
        print("📥 Cargando datos históricos...")
        bars_query = db.query(Bar).filter(Bar.bot_id == bot_id).order_by(Bar.ts_utc.asc())
        bars = pd.read_sql(bars_query.statement, db.bind)
        
        if len(bars) < 100:
            print(f"⚠️  Datos insuficientes ({len(bars)} barras). Se recomiendan >100 para optimizar.")
            return

        # 2. Feature Engineering (Reutilizando lógica del backend)
        print("⚙️  Generando features...")
        df = ml_service._ensure_dataframe(bars)
        
        if df is None or len(df) < 50:
            print("⚠️  Datos insuficientes tras feature engineering.")
            return

        # 3. Preparar Targets (Misma lógica que entrenamiento)
        # Target: 1 si el cierre siguiente es mayor al actual, 0 si no
        df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
        df = df.iloc[:-1] # Eliminar última fila sin target

        features = ['close_pct', 'vol_pct', 'rel_range', 'close_loc', 'close_pct_lag_1']
        X = df[features]
        y = df['target']

        print(f"📊 Dataset: {len(X)} muestras, {len(features)} features.")

        # 4. Configurar Grid Search
        # Definimos el espacio de búsqueda
        param_grid = {
            'n_estimators': [50, 100, 200],
            'max_depth': [3, 5, 10, None],
            'min_samples_split': [2, 5, 10],
            'min_samples_leaf': [1, 2, 4],
            'criterion': ['gini', 'entropy']
        }

        print("🚀 Ejecutando GridSearchCV con TimeSeriesSplit (5 splits)...")
        # TimeSeriesSplit es crucial para datos financieros para evitar look-ahead bias
        tscv = TimeSeriesSplit(n_splits=5)
        
        rf = RandomForestClassifier(random_state=42)
        grid_search = GridSearchCV(
            estimator=rf, 
            param_grid=param_grid, 
            cv=tscv, 
            n_jobs=-1, # Usar todos los cores
            scoring='accuracy', 
            verbose=1
        )
        
        grid_search.fit(X, y)

        # 5. Resultados
        print("\n✅ Optimización Finalizada")
        print("=" * 30)
        print(f"🏆 Mejor Accuracy (CV): {grid_search.best_score_:.2%}")
        print("🔧 Mejores Parámetros:")
        for param, value in grid_search.best_params_.items():
            print(f"   - {param}: {value}")
        print("=" * 30)
        
        print("\nSugerencia: Usa estos valores en el panel de entrenamiento 'ML Training'.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    # Permite pasar bot_id como argumento
    target_bot = sys.argv[1] if len(sys.argv) > 1 else "bot-1"
    optimize_hyperparams(target_bot)
