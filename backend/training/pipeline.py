from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from backend.market.metrics import instrument_spec
from backend.models import DataBar, ModelRun
from backend.training.registry import TrainingStatus, set_status, utc_iso


@dataclass(frozen=True)
class TrainConfig:
    lookback_days: int = 60
    horizon_bars: int = 10
    min_real_bars: int = 10_000
    random_state: int = 42


def _models_root() -> Path:
    env = (os.getenv("WYCKOFF_MODELS_DIR") or "").strip()
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2] / "models"


def _as_market_rows(rows: List[DataBar]) -> Dict[str, Any]:
    # Ensure deterministic ordering by ts_utc asc.
    rows_sorted = sorted(rows, key=lambda r: r.ts_utc or datetime.min.replace(tzinfo=timezone.utc))
    ts = [r.ts_utc.astimezone(timezone.utc) for r in rows_sorted]
    o = np.array([float(r.open or 0.0) for r in rows_sorted], dtype=float)
    h = np.array([float(r.high or 0.0) for r in rows_sorted], dtype=float)
    l = np.array([float(r.low or 0.0) for r in rows_sorted], dtype=float)
    c = np.array([float(r.close or 0.0) for r in rows_sorted], dtype=float)
    v = np.array([float(r.volume or 0.0) for r in rows_sorted], dtype=float)
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    if window <= 0:
        return np.full_like(x, np.nan, dtype=float)
    out = np.full_like(x, np.nan, dtype=float)
    if len(x) < window:
        return out
    csum = np.cumsum(np.insert(x, 0, 0.0))
    out[window - 1 :] = (csum[window:] - csum[:-window]) / float(window)
    return out


def _rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    if len(x) < window:
        return out
    for i in range(window - 1, len(x)):
        w = x[i - window + 1 : i + 1]
        out[i] = float(np.std(w, ddof=0))
    return out


def _linreg_r2_slope_50(closes: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    r2 = np.full_like(closes, np.nan, dtype=float)
    slope = np.full_like(closes, np.nan, dtype=float)
    if len(closes) < 50:
        return r2, slope
    x = np.arange(50, dtype=float)
    x_mu = float(x.mean())
    x_var = float(np.sum((x - x_mu) ** 2))
    for i in range(49, len(closes)):
        y = closes[i - 49 : i + 1]
        y_mu = float(y.mean())
        cov = float(np.sum((x - x_mu) * (y - y_mu)))
        b = 0.0 if x_var <= 0 else cov / x_var
        a = y_mu - b * x_mu
        y_hat = a + b * x
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y_mu) ** 2))
        r2[i] = np.nan if ss_tot <= 0 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
        slope[i] = b
    return r2, slope


def _compute_fvg_features(high: np.ndarray, low: np.ndarray, close: np.ndarray, tick_size: float) -> Dict[str, np.ndarray]:
    nearest_above = np.full_like(close, np.nan, dtype=float)
    nearest_below = np.full_like(close, np.nan, dtype=float)
    unfilled_above = np.zeros_like(close, dtype=float)
    unfilled_below = np.zeros_like(close, dtype=float)

    # Maintain unfilled gaps as tuples: (dir, low, high)
    gaps: List[Tuple[str, float, float]] = []
    for i in range(len(close)):
        # Detect new FVG using i-2 and i (same rule as metrics.py).
        if i >= 2:
            if float(low[i]) > float(high[i - 2]):
                gaps.append(("UP", float(high[i - 2]), float(low[i])))
            elif float(high[i]) < float(low[i - 2]):
                gaps.append(("DOWN", float(high[i]), float(low[i - 2])))

        # Mark fills: any overlap with current bar range.
        survivors: List[Tuple[str, float, float]] = []
        for d, g_low, g_high in gaps:
            if float(low[i]) <= g_high and float(high[i]) >= g_low:
                continue
            survivors.append((d, g_low, g_high))
        gaps = survivors

        px = float(close[i])
        above = [g for g in gaps if g[1] > px]
        below = [g for g in gaps if g[2] < px]
        unfilled_above[i] = float(len(above))
        unfilled_below[i] = float(len(below))
        if above:
            g = min(above, key=lambda t: t[1] - px)
            nearest_above[i] = (g[1] - px) / float(tick_size)
        if below:
            g = min(below, key=lambda t: px - t[2])
            nearest_below[i] = (px - g[2]) / float(tick_size)

    return {
        "fvg_nearest_above_ticks": nearest_above,
        "fvg_nearest_below_ticks": nearest_below,
        "fvg_unfilled_above_count": unfilled_above,
        "fvg_unfilled_below_count": unfilled_below,
    }


def build_features(
    *,
    symbol: str,
    timeframe: str,
    rows: List[DataBar],
    horizon_bars: int,
) -> Tuple[np.ndarray, np.ndarray, List[str], List[datetime]]:
    spec = instrument_spec(symbol)
    tick_size = float(spec.tick_size or 0.25)

    arr = _as_market_rows(rows)
    ts: List[datetime] = arr["ts"]
    o = arr["open"]
    h = arr["high"]
    l = arr["low"]
    c = arr["close"]
    vol = arr["volume"]

    n = len(c)
    if n == 0:
        return np.zeros((0, 0), dtype=float), np.zeros((0,), dtype=int), [], []

    # True range ticks (uses prev close).
    prev_close = np.roll(c, 1)
    prev_close[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_close), np.abs(l - prev_close)))
    tr_ticks = tr / tick_size
    atr14 = _rolling_mean(tr_ticks, 14)

    spread_ticks = (h - l) / tick_size
    vol_sma20 = _rolling_mean(vol, 20)
    rvol20 = np.where(vol_sma20 > 0, vol / vol_sma20, np.nan)
    vol_mu50 = _rolling_mean(vol, 50)
    vol_sd50 = _rolling_std(vol, 50)
    vol_z50 = np.where(vol_sd50 > 0, (vol - vol_mu50) / vol_sd50, np.nan)
    effort_result = np.where(tr_ticks >= 1.0, vol / np.maximum(tr_ticks, 1.0), np.nan)

    # Climax flag: vol_z>=2.5 and spread >= p80 of last 50 spreads.
    climax = np.zeros(n, dtype=float)
    for i in range(49, n):
        window = spread_ticks[max(0, i - 49) : i + 1]
        p80 = float(np.percentile(window, 80))
        if np.isfinite(vol_z50[i]) and float(vol_z50[i]) >= 2.5 and float(spread_ticks[i]) >= p80:
            climax[i] = 1.0

    # Trend/pullback
    r2_50, slope_50 = _linreg_r2_slope_50(c)
    atr_price = atr14 * tick_size
    slope_atr_norm = np.where(atr_price > 0, slope_50 / atr_price, np.nan)

    # Sessions (simple): RTH if 09:30-16:00 ET at bar timestamp.
    is_rth = np.zeros(n, dtype=float)
    session_open = np.full(n, np.nan, dtype=float)
    session_high = np.full(n, np.nan, dtype=float)
    session_low = np.full(n, np.nan, dtype=float)

    # Daily context.
    prev_day_high = np.full(n, np.nan, dtype=float)
    prev_day_low = np.full(n, np.nan, dtype=float)
    prev_day_close = np.full(n, np.nan, dtype=float)
    or15_high = np.full(n, np.nan, dtype=float)
    or15_low = np.full(n, np.nan, dtype=float)

    import zoneinfo

    ny = zoneinfo.ZoneInfo("America/New_York")
    day_key = np.array([dt.astimezone(ny).date().isoformat() for dt in ts])
    # Session key: day + RTH/ETH
    session_key = []
    for dt_utc in ts:
        dt = dt_utc.astimezone(ny)
        is_r = (dt.hour > 9 or (dt.hour == 9 and dt.minute >= 30)) and (dt.hour < 16 or (dt.hour == 16 and dt.minute == 0))
        session_key.append(f"{dt.date().isoformat()}|{'RTH' if is_r else 'ETH'}")
    session_key = np.array(session_key)

    # Build running session OHLC and OR15 for RTH.
    last_session = None
    sess_o = sess_h = sess_l = np.nan
    sess_start_dt: Optional[datetime] = None
    rth_start_dt: Optional[datetime] = None
    rth_or_h = rth_or_l = np.nan

    # Precompute per-day stats for prev_day.
    unique_days = list(dict.fromkeys(day_key.tolist()))
    day_stats: Dict[str, Dict[str, float]] = {}
    for d in unique_days:
        idx = np.where(day_key == d)[0]
        if len(idx) == 0:
            continue
        day_stats[d] = {"high": float(np.max(h[idx])), "low": float(np.min(l[idx])), "close": float(c[idx][-1])}

    for i in range(n):
        dt = ts[i].astimezone(ny)
        sk = session_key[i]
        is_r = sk.endswith("|RTH")
        is_rth[i] = 1.0 if is_r else 0.0

        if sk != last_session:
            last_session = sk
            sess_o = float(o[i])
            sess_h = float(h[i])
            sess_l = float(l[i])
            sess_start_dt = dt
            rth_start_dt = dt if is_r else None
            rth_or_h = float(h[i]) if is_r else np.nan
            rth_or_l = float(l[i]) if is_r else np.nan
        else:
            sess_h = float(max(sess_h, float(h[i])))
            sess_l = float(min(sess_l, float(l[i])))
            if is_r and rth_start_dt is not None:
                if (dt - rth_start_dt) <= timedelta(minutes=15):
                    rth_or_h = float(max(rth_or_h, float(h[i])))
                    rth_or_l = float(min(rth_or_l, float(l[i])))

        session_open[i] = sess_o
        session_high[i] = sess_h
        session_low[i] = sess_l
        if is_r and rth_start_dt is not None and (dt - rth_start_dt) <= timedelta(minutes=15):
            or15_high[i] = rth_or_h
            or15_low[i] = rth_or_l
        else:
            or15_high[i] = rth_or_h
            or15_low[i] = rth_or_l

        # Prev day stats
        prev_day = (dt.date() - timedelta(days=1)).isoformat()
        if prev_day in day_stats:
            prev_day_high[i] = day_stats[prev_day]["high"]
            prev_day_low[i] = day_stats[prev_day]["low"]
            prev_day_close[i] = day_stats[prev_day]["close"]

    # FVG
    fvg = _compute_fvg_features(h, l, c, tick_size)

    feature_names = [
        "tr_last_ticks",
        "atr14_ticks",
        "effort_result",
        "rvol20",
        "vol_zscore50",
        "spread_ticks",
        "climax_flag",
        "linreg_r2_50",
        "linreg_slope_50_atr_norm",
        "is_rth",
        "session_open_ticks",
        "session_range_ticks",
        "prev_day_range_ticks",
        "or15_range_ticks",
        "fvg_nearest_above_ticks",
        "fvg_nearest_below_ticks",
        "fvg_unfilled_above_count",
        "fvg_unfilled_below_count",
    ]

    X = np.column_stack(
        [
            tr_ticks,
            atr14,
            effort_result,
            rvol20,
            vol_z50,
            spread_ticks,
            climax,
            r2_50,
            slope_atr_norm,
            is_rth,
            (c - session_open) / tick_size,
            (session_high - session_low) / tick_size,
            (prev_day_high - prev_day_low) / tick_size,
            (or15_high - or15_low) / tick_size,
            fvg["fvg_nearest_above_ticks"],
            fvg["fvg_nearest_below_ticks"],
            fvg["fvg_unfilled_above_count"],
            fvg["fvg_unfilled_below_count"],
        ]
    )

    # Label: next horizon close up/down (deterministic).
    horizon = int(max(1, horizon_bars))
    y = np.full(n, -1, dtype=int)
    if horizon < n:
        future = np.roll(c, -horizon)
        y[: n - horizon] = (future[: n - horizon] > c[: n - horizon]).astype(int)

    # Keep only rows with core rolling features and labels; optional context features can be missing (impute to 0).
    core_ok = np.isfinite(atr14) & np.isfinite(rvol20) & np.isfinite(vol_z50) & np.isfinite(r2_50) & np.isfinite(slope_atr_norm)
    valid = core_ok & (y >= 0)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)[valid]
    y = y[valid]
    valid_idx = np.where(valid)[0].tolist()
    ts_out = [ts[i] for i in valid_idx]
    return X, y, feature_names, ts_out


def train_from_db(
    *,
    db: Session,
    bot_id: str,
    symbol: str,
    timeframe: str,
    config: TrainConfig,
    run_id: Optional[str] = None,
) -> TrainingStatus:
    run_id = run_id or f"mr_{uuid.uuid4().hex}"
    started = datetime.now(timezone.utc)
    status = TrainingStatus(run_id=run_id, bot_id=bot_id, symbol=symbol, timeframe=timeframe, status="RUNNING", started_at_utc=utc_iso(started))
    set_status(status)

    def _update_run_row(*, status_s: str, metrics: Optional[Dict[str, Any]], artifact_path: Optional[str], error: Optional[str]) -> None:
        row = db.query(ModelRun).filter(ModelRun.id == run_id).first()
        if row is None:
            row = ModelRun(
                id=run_id,
                bot_id=bot_id,
                symbol=symbol,
                timeframe=timeframe,
                started_at_utc=started,
            )
            db.add(row)
        row.finished_at_utc = datetime.now(timezone.utc) if status_s in {"DONE", "ERROR", "REFUSED"} else None
        row.status = status_s
        row.metrics = metrics
        row.train_config = asdict(config)
        row.artifact_path = artifact_path
        row.error = error
        db.commit()

    try:
        # Count real data (guardrail).
        q = db.query(DataBar).filter(DataBar.symbol == symbol, DataBar.timeframe == timeframe, DataBar.is_simulated.is_(False))
        total = int(q.count() or 0)
        if total < int(config.min_real_bars):
            status.status = "REFUSED"
            status.finished_at_utc = utc_iso()
            status.message = f"insufficient real data_bars: have={total} need>={config.min_real_bars}"
            status.metrics = {"have_bars": total, "min_real_bars": config.min_real_bars}
            set_status(status)
            _update_run_row(status_s="REFUSED", metrics=status.metrics, artifact_path=None, error=status.message)
            return status

        since = datetime.now(timezone.utc) - timedelta(days=int(config.lookback_days))
        rows = (
            q.filter(DataBar.ts_utc >= since)
            .order_by(DataBar.ts_utc.asc())
            .limit(1_000_000)
            .all()
        )
        if len(rows) < int(config.min_real_bars):
            status.status = "REFUSED"
            status.finished_at_utc = utc_iso()
            status.message = f"insufficient bars in lookback window: have={len(rows)} need>={config.min_real_bars} (lookback_days={config.lookback_days})"
            status.metrics = {"have_bars": len(rows), "min_real_bars": config.min_real_bars, "lookback_days": config.lookback_days}
            set_status(status)
            _update_run_row(status_s="REFUSED", metrics=status.metrics, artifact_path=None, error=status.message)
            return status

        status.progress = 0.2
        status.message = f"building features from {len(rows)} bars"
        set_status(status)

        X, y, feature_names, ts = build_features(symbol=symbol, timeframe=timeframe, rows=rows, horizon_bars=config.horizon_bars)
        if len(y) < 500:
            status.status = "REFUSED"
            status.finished_at_utc = utc_iso()
            status.message = f"insufficient feature rows after rolling windows: have={len(y)} need>=500"
            status.metrics = {"feature_rows": int(len(y))}
            set_status(status)
            _update_run_row(status_s="REFUSED", metrics=status.metrics, artifact_path=None, error=status.message)
            return status

        # Time-based split.
        split = int(0.8 * len(y))
        X_train, y_train = X[:split], y[:split]
        X_test, y_test = X[split:], y[split:]

        status.progress = 0.6
        status.message = f"training model (train={len(y_train)} test={len(y_test)})"
        set_status(status)

        clf = Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(max_iter=2000, random_state=int(config.random_state))),
            ]
        )
        clf.fit(X_train, y_train)

        status.progress = 0.85
        status.message = "evaluating"
        set_status(status)

        y_pred = clf.predict(X_test)
        try:
            proba = clf.predict_proba(X_test)[:, 1]
            auc = float(roc_auc_score(y_test, proba))
        except Exception:
            auc = float("nan")
        acc = float(accuracy_score(y_test, y_pred))

        # Save artifacts.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        artifact_dir = _models_root() / bot_id / symbol / timeframe / stamp
        artifact_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(clf, artifact_dir / "model.pkl")
        (artifact_dir / "feature_schema.json").write_text(json.dumps(feature_names, indent=2), encoding="utf-8")
        metrics = {"accuracy": acc, "roc_auc": auc, "train_rows": int(len(y_train)), "test_rows": int(len(y_test))}
        (artifact_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (artifact_dir / "train_config.json").write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")

        status.progress = 1.0
        status.status = "DONE"
        status.finished_at_utc = utc_iso()
        status.message = "done"
        status.metrics = metrics
        status.artifact_path = str(artifact_dir)
        set_status(status)
        _update_run_row(status_s="DONE", metrics=metrics, artifact_path=str(artifact_dir), error=None)
        return status
    except Exception as exc:
        status.status = "ERROR"
        status.finished_at_utc = utc_iso()
        status.message = f"training error: {exc}"
        set_status(status)
        _update_run_row(status_s="ERROR", metrics=None, artifact_path=None, error=status.message)
        return status
