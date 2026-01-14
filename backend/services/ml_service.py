from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sqlalchemy.orm import Session

from backend.models import Bar, DATA_SOURCE_ARCHIVED, DATA_SOURCE_IMPORT, DATA_SOURCE_LIVE_WS, DATA_SOURCE_SIMULATED

MODEL_DIR = Path(__file__).resolve().parents[1] / "trained_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


class MLService:
    def __init__(self) -> None:
        self.models: Dict[str, RandomForestClassifier] = {}

    def _model_path(self, bot_id: str) -> Path:
        return MODEL_DIR / f"{bot_id}.joblib"

    def _history_path(self, bot_id: str) -> Path:
        return MODEL_DIR / f"{bot_id}_history.json"

    def _load_model(self, bot_id: str) -> Optional[RandomForestClassifier]:
        if bot_id in self.models:
            return self.models[bot_id]

        path = self._model_path(bot_id)
        if path.exists():
            try:
                model = joblib.load(path)
                self.models[bot_id] = model
                return model
            except Exception as exc:
                print(f"[ml_service] Error loading model for {bot_id}: {exc}")
        return None

    def get_model_path(self, bot_id: str) -> str:
        return str(self._model_path(bot_id))

    def _ensure_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        working = df.copy().sort_values("ts_utc")
        working["range"] = working["high"] - working["low"]
        working["body"] = (working["close"] - working["open"]).abs()
        working["close_pct"] = working["close"].pct_change()
        working["vol_pct"] = working["volume"].pct_change()
        working["rel_range"] = working["range"] / (
            working["close"].rolling(10).mean() * 1e-4 + 1e-5
        )
        working["close_loc"] = (working["close"] - working["low"]) / (
            working["range"] + 1e-5
        )
        for lag in (1, 2, 3):
            working[f"close_pct_lag_{lag}"] = working["close_pct"].shift(lag)
        working = working.dropna()
        return working

    def train_from_db(
        self,
        bot_id: str,
        db: Session,
        hyperparams: Optional[Dict[str, Any]] = None,
        test_size: float = 0.2,
    ) -> tuple[bool, Dict[str, Any]]:
        try:
            query = (
                db.query(Bar)
                .filter(Bar.bot_id == bot_id)
                .filter(Bar.data_source.in_([DATA_SOURCE_LIVE_WS, DATA_SOURCE_IMPORT]))
                .filter(Bar.data_source != DATA_SOURCE_SIMULATED)
                .filter(Bar.data_source != DATA_SOURCE_ARCHIVED)
                .order_by(Bar.ts_utc.asc())
            )
            df = pd.read_sql(query.statement, db.bind)

            if len(df) < 200:
                return False, {"error": f"Not enough data to train ({len(df)} bars)."}

            df_features = self._ensure_dataframe(df)
            df_features["target"] = (
                df_features["close"].shift(-1) > df_features["close"]
            ).astype(int)
            df_features = df_features.dropna()

            if len(df_features) < 100:
                return False, {"error": "Not enough data after feature engineering."}

            drop_cols = [
                "id",
                "bot_id",
                "symbol",
                "ts_utc",
                "mode",
                "target",
                "timeframe",
            ]
            X = df_features.drop(columns=[c for c in drop_cols if c in df_features], errors="ignore")
            X = X.select_dtypes(include=[np.number])
            y = df_features["target"]

            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, shuffle=False
            )

            params = hyperparams or {}
            n_estimators = int(params.get("n_estimators", 100))
            max_depth = int(params.get("max_depth", 5))

            model = RandomForestClassifier(
                n_estimators=n_estimators, max_depth=max_depth, random_state=42
            )
            model.fit(X_train, y_train)

            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            cm = confusion_matrix(y_test, y_pred)

            joblib.dump(model, self._model_path(bot_id))
            self.models[bot_id] = model

            history_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "accuracy": float(accuracy),
                "samples": len(df_features),
                "confusion_matrix": cm.tolist(),
                "features": list(X.columns),
                "params": {"n_estimators": n_estimators, "max_depth": max_depth},
            }

            tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, 0)
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

            history_entry.update(
                {
                    "precision": float(precision),
                    "recall": float(recall),
                    "f1": float(f1),
                }
            )

            self._save_history_entry(bot_id, history_entry)
            return True, history_entry
        except Exception as exc:
            print(f"[ml_service] Training failed: {exc}")
            return False, {"error": str(exc)}

    def get_history(self, bot_id: str) -> List[Dict[str, Any]]:
        path = self._history_path(bot_id)
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as reader:
                return json.load(reader)
        except Exception:
            return []

    def _save_history_entry(self, bot_id: str, entry: Dict[str, Any]) -> None:
        path = self._history_path(bot_id)
        history = self.get_history(bot_id)
        history.append(entry)
        if len(history) > 50:
            history = history[-50:]
        with path.open("w", encoding="utf-8") as writer:
            json.dump(history, writer)

    def clear_history(self, bot_id: str) -> bool:
        path = self._history_path(bot_id)
        if path.exists():
            try:
                path.unlink()
                return True
            except Exception:
                return False
        return False

    def get_confusion_matrix(self, bot_id: str, limit: Optional[int] = None) -> Optional[List[List[float]]]:
        history = self.get_history(bot_id)
        if not history:
            return None
        subset = history if limit is None else history[-limit:]
        sum_cm = np.zeros((2, 2))
        count = 0
        for entry in subset:
            cm = entry.get("confusion_matrix")
            if cm and len(cm) == 2 and len(cm[0]) == 2:
                sum_cm += np.array(cm)
                count += 1
        if count == 0:
            return None
        return (sum_cm / count).tolist()

    def get_recommendation(self, bot_id: str) -> Dict[str, Any]:
        return {
            "status": "NOT_READY",
            "reason": "Wyckoff analysis and ML model are not implemented.",
            "ready": False,
        }

    def _wyckoff_phase_analysis(self, df: pd.DataFrame, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = config or {}
        window = int(cfg.get("window", 20))
        vol_mult = float(cfg.get("vol_mult", 1.5))
        if len(df) < 10:
            return {"phase": "NEUTRAL", "last_event": None, "confidence": 0.0, "sos_count": 0, "sow_count": 0}

        working = df.copy()
        working["range"] = working["high"] - working["low"]
        working["highest_high"] = working["high"].rolling(window=window).max()
        working["lowest_low"] = working["low"].rolling(window=window).min()
        working["volume_avg"] = working["volume"].rolling(max(5, window // 4)).mean()
        current_idx = len(working) - 1
        current = working.iloc[current_idx]
        prev = working.iloc[current_idx - 1] if current_idx > 0 else current
        events: List[str] = []
        confidence = 0.0

        if (
            current["low"] < prev["low"]
            and current["close"] > current["open"]
            and current["close"] > prev["high"]
        ):
            events.append("SPRING")
            confidence = max(confidence, 0.7)

        elif (
            current["close"] > prev["high"]
            and working["volume_avg"].iloc[current_idx - 1] is not None
            and current["volume"]
            > working["volume_avg"].iloc[current_idx - 1] * vol_mult
        ):
            events.append("SECONDARY_TEST")
            confidence = max(confidence, 0.6)

        elif (
            current["low"] < prev["low"]
            and current["close"] < current["open"]
            and current["close"] < prev["low"]
        ):
            events.append("DOWNTHRUST")
            confidence = max(confidence, 0.6)

        vol_spike = False
        vol_avg = working["volume_avg"].iloc[current_idx]
        if (
            current["volume"] > 0
            and vol_avg is not None
            and vol_avg > 0
            and current["volume"] > vol_avg * 2
        ):
            vol_spike = True
        range_mean = working["range"].rolling(5).mean().iloc[current_idx - 1] if current_idx > 0 else 0
        if vol_spike and current["range"] > (range_mean or 0) * 1.5:
            if current["close"] > current["open"]:
                events.append("BUYING_CLIMAX")
            else:
                events.append("SELLING_CLIMAX")
            confidence = max(confidence, 0.5)

        sos_count = sum(1 for ev in events if ev == "SPRING")
        sow_count = sum(1 for ev in events if ev == "DOWNTHRUST")
        phase = "NEUTRAL"
        if "SPRING" in events:
            phase = "ACCUMULATION"
        elif "DOWNTHRUST" in events:
            phase = "DISTRIBUTION"
        elif events:
            phase = "TRANSITION"

        return {
            "phase": phase,
            "last_event": events[-1] if events else None,
            "confidence": confidence,
            "sos_count": sos_count,
            "sow_count": sow_count,
            "range_high": (
                working["highest_high"].iloc[current_idx]
                if not pd.isna(working["highest_high"].iloc[current_idx])
                else current["high"]
            ),
            "range_low": (
                working["lowest_low"].iloc[current_idx]
                if not pd.isna(working["lowest_low"].iloc[current_idx])
                else current["low"]
            ),
        }

    def infer_signal(
        self,
        bot_id: str,
        current_bar_payload: Dict[str, Any],
        db: Session,
        wyckoff_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cfg = wyckoff_config or {}
        min_bars = int(cfg.get("min_bars", 20))
        limit = max(100, min_bars * 2)
        query = (
            db.query(Bar)
            .filter(Bar.bot_id == bot_id)
            .filter(or_(Bar.mode.is_(None), ~Bar.mode.ilike("SIM%")))
            .order_by(Bar.ts_utc.desc())
            .limit(limit)
        )
        df_hist = pd.read_sql(query.statement, db.bind).sort_values("ts_utc")

        if len(df_hist) < min_bars:
            return {
                "signal": "NONE",
                "bias": "NEUTRAL",
                "confidence": 0.0,
                "explain": f"Insufficient history ({len(df_hist)} bars).",
            }

        wyckoff = self._wyckoff_phase_analysis(df_hist, cfg)
        signal = "NONE"
        bias = "NEUTRAL"
        confidence = wyckoff.get("confidence", 0.0)
        explanation_parts: List[str] = []

        last_event = wyckoff.get("last_event")
        phase = wyckoff.get("phase", "NEUTRAL")

        if last_event == "SPRING":
            signal = "SOS"
            bias = "BULLISH"
            confidence = max(confidence, 0.7)
            explanation_parts.append("SPRING detected.")
        elif last_event == "DOWNTHRUST":
            signal = "SOW"
            bias = "BEARISH"
            confidence = max(confidence, 0.7)
            explanation_parts.append("DOWNTHRUST detected.")
        elif last_event == "SECONDARY_TEST":
            signal = "TEST"
            bias = "NEUTRAL"
            confidence = max(confidence, 0.6)
            explanation_parts.append("SECONDARY TEST detected.")
        elif last_event == "BUYING_CLIMAX":
            signal = "TOP_SIGNAL"
            bias = "BEARISH"
            confidence = max(confidence, 0.65)
            explanation_parts.append("BUYING CLIMAX detected.")
        elif last_event == "SELLING_CLIMAX":
            signal = "BOTTOM_SIGNAL"
            bias = "BULLISH"
            confidence = max(confidence, 0.65)
            explanation_parts.append("SELLING CLIMAX detected.")

        if phase == "ACCUMULATION":
            explanation_parts.append("Phase: ACCUMULATION.")
            if signal == "NONE":
                signal = "ACCUMULATION_ZONE"
                bias = "BULLISH"
                confidence = max(confidence, 0.55)
        elif phase == "DISTRIBUTION":
            explanation_parts.append("Phase: DISTRIBUTION.")
            if signal == "NONE":
                signal = "DISTRIBUTION_ZONE"
                bias = "BEARISH"
                confidence = max(confidence, 0.55)

        model = self._load_model(bot_id)
        if model is not None:
            try:
                df_features = self._ensure_dataframe(df_hist)
                if not df_features.empty:
                    latest = df_features.iloc[[-1]]
                    drop_cols = [
                        "id",
                        "bot_id",
                        "symbol",
                        "ts_utc",
                        "mode",
                        "target",
                        "timeframe",
                    ]
                    X_latest = latest.drop(columns=[c for c in drop_cols if c in latest], errors="ignore")
                    X_latest = X_latest.select_dtypes(include=[np.number])
                    if X_latest.shape[1] == model.n_features_in_:
                        pred = model.predict(X_latest)[0]
                        probs = model.predict_proba(X_latest)[0]
                        ml_signal = "BULLISH" if pred == 1 else "BEARISH"
                        ml_conf = max(probs)
                        explanation_parts.append(
                            f"[ML] Model predicts {ml_signal} ({ml_conf:.2f})."
                        )
                        if ml_signal == bias:
                            confidence = min(0.99, confidence + 0.15)
                            explanation_parts.append("ML confirms Wyckoff bias.")
                        elif bias != "NEUTRAL":
                            confidence = max(0.1, confidence - 0.2)
                            explanation_parts.append("ML contradicts Wyckoff bias.")
            except Exception as exc:
                print(f"[ml_service] Inference error: {exc}")

        explanation = " ".join(explanation_parts) if explanation_parts else "No clear signal."
        return {
            "signal": signal,
            "bias": bias,
            "confidence": round(float(confidence), 3),
            "explain": explanation,
            "phase": phase,
            "last_event": last_event,
        }


ml_service = MLService()
