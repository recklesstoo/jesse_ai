from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.database import get_db
from backend.services.ml_service import ml_service
from backend.state import _get_bot_state, _set_bot_state, bot_state, ws_bots, ws_live_clients

_queues: Dict[str, asyncio.Queue] = {}
cmd_log: Dict[str, List[Dict[str, Any]]] = {}
cmd_index: Dict[str, int] = {}
bars_store: Dict[str, List[Dict[str, Any]]] = {}
ai_signal_store: Dict[str, Dict[str, Any]] = {}
ai_signal_history: Dict[str, List[Dict[str, Any]]] = {}
auto_cal_state: Dict[str, Dict[str, Any]] = {}
wyckoff_config_store: Dict[str, Dict[str, Any]] = {}
auto_trade_config_store: Dict[str, Dict[str, Any]] = {}
bot_ws_connections = ws_bots
bots = bot_state
live_ws_connections = ws_live_clients

INSTRUMENT_MIN_CONFIDENCE: Dict[str, float] = {"MNQ": 0.72, "ES": 0.65, "GC": 0.78}
INSTRUMENT_BREAK_PCT: Dict[str, float] = {"MNQ": 0.0025, "ES": 0.0015, "GC": 0.002}


def default_wyckoff_config(instrument: str = "MNQ") -> Dict[str, Any]:
    return {
        "window": 20,
        "min_bars": 10,
        "vol_mult": 1.5,
        "break_pct": INSTRUMENT_BREAK_PCT.get(instrument, 0.001),
        "break_range_mult": 1.2,
        "sos_pct": 0.001,
        "sow_pct": 0.001,
        "range_window": 30,
    }


def default_auto_trade_config(instrument: str = "MNQ") -> Dict[str, Any]:
    return {
        "enabled": False,
        "min_confidence": INSTRUMENT_MIN_CONFIDENCE.get(instrument, 0.6),
        "max_per_hour": 0,
        "cooldown_seconds": 60,
        "max_qty": 1,
        "allowed_signals": ["SOS", "SOW", "SPRING", "UPTHRUST"],
    }


def update_bot_state(bot_id: str, **kwargs: Any) -> Dict[str, Any]:
    state = _get_bot_state(bot_id)
    state.setdefault("connected", True)
    instrument = kwargs.get("instrument") or state.get("instrument") or "MNQ"
    state["instrument"] = instrument
    state.update(kwargs)
    bars_store.setdefault(bot_id, [])
    ai_signal_store.setdefault(bot_id, {})
    ai_signal_history.setdefault(bot_id, [])
    auto_cal_state.setdefault(bot_id, {})
    wyckoff_config_store[bot_id] = default_wyckoff_config(instrument)
    auto_trade_config_store[bot_id] = default_auto_trade_config(instrument)
    _set_bot_state(bot_id, state)
    return state


def update_ai_signal(bot_id: str) -> None:
    bars = bars_store.get(bot_id, [])
    if not bars:
        return
    payload = bars[-1].copy()
    payload.setdefault("symbol", bars[-1].get("symbol", "MNQ"))
    payload.setdefault("timeframe", bars[-1].get("timeframe", "1 Minute"))
    payload["timestamp"] = payload.pop("ts", payload.get("timestamp"))
    payload["volume"] = payload.get("v", payload.get("volume"))
    db = next(get_db())
    try:
        result = ml_service.infer_signal(
            bot_id,
            payload,
            db,
            wyckoff_config=wyckoff_config_store.get(bot_id),
        )
    finally:
        db.close()

    ai_signal_store[bot_id] = result
    history = ai_signal_history.setdefault(bot_id, [])
    history.insert(0, result)
    auto_cal_state.setdefault(bot_id, {})["last_calibrated"] = len(bars)


def get_auto_trade_config(bot_id: str) -> Dict[str, Any]:
    return auto_trade_config_store.setdefault(bot_id, default_auto_trade_config())


def get_wyckoff_config(bot_id: str) -> Dict[str, Any]:
    return wyckoff_config_store.setdefault(bot_id, default_wyckoff_config())


def _build_bar_update(bot_id: str, bar: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "bar_update",
        "data": {
            "symbol": bar.get("symbol"),
            "price": bar.get("c"),
            "ohlc": {
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
            },
            "volume": bar.get("v"),
            "timestamp": bar.get("ts"),
        },
    }


def _build_bot_status(bot_id: str) -> Dict[str, Any]:
    state = _get_bot_state(bot_id)
    return {
        "type": "bot_status",
        "data": {
            "status": {
                "botId": bot_id,
                "connected": bool(state.get("connected")),
                "last_seen_utc": state.get("last_seen_utc"),
                "mode": state.get("mode"),
            }
        },
    }


async def _enqueue_command_payload(bot_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    queue = _queues.setdefault(bot_id, asyncio.Queue())
    index = cmd_index.setdefault(bot_id, 0) + 1
    cmd_index[bot_id] = index
    entry = {**payload, "id": f"compat-{bot_id}-{index}"}
    await queue.put(entry)
    cmd_log.setdefault(bot_id, []).append(entry)
    return entry


async def get_queue(bot_id: str) -> asyncio.Queue:
    return _queues.setdefault(bot_id, asyncio.Queue())


def retry_delay_ms(attempt: int, base_ms: int = 1000, max_ms: int = 30000) -> int:
    multiplier = 2 ** max(0, attempt)
    delay = base_ms * multiplier
    return min(delay, max_ms)
