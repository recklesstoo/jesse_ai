from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.database import PROJECT_ROOT
from backend.state import compute_feed_status, state_lock


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_logs_dir() -> Path:
    p = Path(PROJECT_ROOT) / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _watchdog_path() -> Path:
    env = (os.getenv("WYCKOFF_WS_WATCHDOG_LOG") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _ensure_logs_dir() / "ws_watchdog.jsonl"


def _strategy_ws_state(state: Dict[str, Any]) -> Optional[str]:
    mon = state.get("strategyMonitor")
    if isinstance(mon, dict):
        ws_state = mon.get("wsState")
        if ws_state is not None:
            return str(ws_state)
    return None


def _signature(feed: Dict[str, Any], state: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        feed.get("ws_connected"),
        feed.get("feed_status"),
        feed.get("feed_reason"),
        round(float(feed.get("ws_age_sec") or 0.0), 1) if feed.get("ws_age_sec") is not None else None,
        round(float(feed.get("bar_age_sec") or 0.0), 1) if feed.get("bar_age_sec") is not None else None,
        _strategy_ws_state(state),
        int(feed.get("dropped_bar_count") or 0),
        int(feed.get("dropped_persist_bar_count") or 0),
        int(state.get("db_bar_errors") or 0),
    )


def _level(feed: Dict[str, Any], state: Dict[str, Any]) -> str:
    if int(state.get("db_bar_errors") or 0) > 0:
        return "ERROR"

    if not feed.get("ws_connected"):
        return "INFO"

    # If WS is connected but bars are missing/stale, this is actionable.
    if (feed.get("feed_status") or "").upper() in {"NO_LIVE", "STALE"}:
        return "WARN"

    ws_state = _strategy_ws_state(state)
    if ws_state and ws_state.strip().lower() != "open":
        return "WARN"

    return "INFO"


async def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=False)

    def _sync() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    await asyncio.to_thread(_sync)


@dataclass
class WatchdogConfig:
    interval_sec: float = float(os.getenv("WYCKOFF_WS_WATCHDOG_INTERVAL_SEC", "5.0"))
    emit_heartbeat_sec: float = float(os.getenv("WYCKOFF_WS_WATCHDOG_HEARTBEAT_SEC", "60.0"))


async def run_ws_watchdog(stop_event: asyncio.Event, *, cfg: Optional[WatchdogConfig] = None) -> None:
    """
    Periodically records WS/feed failure signals into logs/ws_watchdog.jsonl.

    This is intentionally side-effect-free: it does not disconnect clients or mutate feed logic.
    """
    cfg = cfg or WatchdogConfig()
    path = _watchdog_path()

    last_sig: Dict[str, Tuple[Any, ...]] = {}
    last_emit: Dict[str, datetime] = {}

    while not stop_event.is_set():
        now = _utc_now()

        # Capture botIds snapshot under lock (compute_feed_status reads bot_state).
        async with state_lock:
            # Import inside lock-scope to avoid circular deps at module import time.
            from backend.state import bot_state as _bot_state

            bot_ids = list(_bot_state.keys())
            states = {bid: dict(_bot_state.get(bid) or {}) for bid in bot_ids}

        for bot_id, st in states.items():
            feed = compute_feed_status(bot_id)
            lvl = _level(feed, st)

            sig = _signature(feed, st)
            prev = last_sig.get(bot_id)
            last_sig[bot_id] = sig

            due_heartbeat = False
            prev_emit = last_emit.get(bot_id)
            if prev_emit is None or (now - prev_emit).total_seconds() >= cfg.emit_heartbeat_sec:
                due_heartbeat = True

            should_emit = lvl != "INFO" or due_heartbeat or (prev is not None and prev != sig)
            if not should_emit:
                continue

            last_emit[bot_id] = now

            row = {
                "ts_utc": _iso_z(now),
                "level": lvl,
                "botId": bot_id,
                "ws_connected": feed.get("ws_connected"),
                "feed_status": feed.get("feed_status"),
                "feed_reason": feed.get("feed_reason"),
                "ws_age_sec": feed.get("ws_age_sec"),
                "bar_age_sec": feed.get("bar_age_sec"),
                "monitor_age_sec": feed.get("monitor_age_sec"),
                "ws_stale_sec": feed.get("ws_stale_sec"),
                "bar_stale_sec": 90.0 if str(st.get("timeframe") or "").lower() == "1m" else None,
                "strategy_wsState": _strategy_ws_state(st),
                "strategy_state": (st.get("strategyMonitor") or {}).get("strategyState") if isinstance(st.get("strategyMonitor"), dict) else None,
                "last_ws_rx_utc": st.get("last_ws_rx_utc"),
                "last_bar_rx_utc": st.get("last_bar_rx_utc"),
                "last_monitor_rx_utc": st.get("last_monitor_rx_utc"),
                "dropped_bar_count": feed.get("dropped_bar_count"),
                "dropped_persist_bar_count": feed.get("dropped_persist_bar_count"),
                "db_bar_errors": int(st.get("db_bar_errors") or 0),
                "last_db_bar_error_utc": st.get("last_db_bar_error_utc"),
            }

            try:
                await _append_jsonl(path, row)
            except Exception:
                # Never break the watchdog loop due to IO.
                pass

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.5, float(cfg.interval_sec)))
        except asyncio.TimeoutError:
            pass

