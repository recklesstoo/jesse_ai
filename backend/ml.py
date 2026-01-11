import os
import joblib
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

from .models import Bar

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "trained_models")
os.makedirs(MODEL_DIR, exist_ok=True)

class MLService:
    def __init__(self):
        self.models = {} # Cache en memoria: bot_id -> model

    def _get_model_path(self, bot_id: str):
        return os.path.join(MODEL_DIR, f"{bot_id}.joblib")

    def _load_model(self, bot_id: str):
        if bot_id in self.models:
            return self.models[bot_id]
        
        path = self._get_model_path(bot_id)
        if os.path.exists(path):
            try:
                model = joblib.load(path)
                self.models[bot_id] = model
                return model
            except Exception as e:
                print(f"[ML] Error loading model for {bot_id}: {e}")
        return None

    def _extract_features(self, df: pd.DataFrame):
        """
        Feature Engineering simple para Wyckoff/Price Action.
        """
        df = df.copy().sort_values('ts_utc')
        
        # Evitar división por cero
        df['range'] = df['high'] - df['low']
        df['body'] = (df['close'] - df['open']).abs()
        
        # Features
        df['close_pct'] = df['close'].pct_change()
        df['vol_pct'] = df['volume'].pct_change()
        df['rel_range'] = df['range'] / (df['close'].rolling(10).mean() * 0.0001 + 1e-5)
        df['close_loc'] = (df['close'] - df['low']) / (df['range'] + 1e-5) # 0=low, 1=high
        
        # Lag features
        for lag in [1, 2, 3]:
            df[f'close_pct_lag_{lag}'] = df['close_pct'].shift(lag)
        
        df = df.dropna()
        return df

    def train_from_db(self, bot_id: str, db: Session):
        # 1. Fetch Data
        bars_query = db.query(Bar).filter(Bar.bot_id == bot_id).order_by(Bar.ts_utc.asc())
        bars = pd.read_sql(bars_query.statement, db.bind)
        
        if len(bars) < 50:
            return False, {"error": "Not enough data (<50 bars)"}

        # 2. Prepare Features
        df = self._extract_features(bars)
        
        if len(df) < 20:
            return False, {"error": "Not enough data after feature engineering"}

        # 3. Labeling (Simple: Next Close > Current Close = 1 (UP), else 0 (DOWN/FLAT))
        # Esto es un baseline. Wyckoff real requeriría detectar estructuras.
        df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
        df = df.iloc[:-1] # Drop last row (no target)

        features = ['close_pct', 'vol_pct', 'rel_range', 'close_loc', 'close_pct_lag_1']
        X = df[features]
        y = df['target']

        # 4. Train
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        
        clf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
        clf.fit(X_train, y_train)
        
        # 5. Evaluate
        y_pred = clf.predict(X_test)
        acc = accuracy_score(y_test, y_pred)

        # 6. Save
        path = self._get_model_path(bot_id)
        joblib.dump(clf, path)
        self.models[bot_id] = clf

        return True, {
            "accuracy": float(acc),
            "samples": len(df),
            "model_path": path,
            "features": features
        }

    def infer_signal(self, bot_id: str, current_bar_payload: dict, db: Session):
        model = self._load_model(bot_id)
        if not model:
            return {
                "signal": "NONE",
                "bias": "NEUTRAL",
                "confidence": 0.0,
                "explain": "No trained model found."
            }

        # Necesitamos contexto (últimas barras) para calcular features
        # Traemos las últimas 10 barras de DB + la actual
        last_bars = db.query(Bar).filter(Bar.bot_id == bot_id).order_by(Bar.ts_utc.desc()).limit(10)
        df_hist = pd.read_sql(last_bars.statement, db.bind).sort_values('ts_utc')
        
        # Feature Engineering on history
        df_feats = self._extract_features(df_hist)
        
        if len(df_feats) == 0:
             return {"signal": "NONE", "bias": "NEUTRAL", "confidence": 0.0, "explain": "Insufficient history for features."}

        last_row = df_feats.iloc[[-1]][['close_pct', 'vol_pct', 'rel_range', 'close_loc', 'close_pct_lag_1']]
        
        try:
            prediction = model.predict(last_row)[0]
            probs = model.predict_proba(last_row)
            confidence = float(np.max(probs))
            
            bias = "BULLISH" if prediction == 1 else "BEARISH"
            signal = "SOS" if prediction == 1 else "SOW" # Mapping simple para Wyckoff
            
            return {"signal": signal, "bias": bias, "confidence": confidence, "explain": f"ML Prediction (Acc: N/A)"}
        except Exception as e:
            return {"signal": "ERROR", "bias": "NEUTRAL", "confidence": 0.0, "explain": str(e)}

ml_service = MLService()