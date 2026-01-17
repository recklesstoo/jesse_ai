from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Request

from backend.config import is_shadow_mode
from backend.state import _get_bot_state, _utc_now, bot_state, state_lock

router = APIRouter()

@router.get("/api/v1/debug/pid")
async def debug_pid() -> Dict[str, Any]:
    return {"ok": True, "pid": os.getpid(), "ppid": os.getppid()}


@router.get("/api/v1/debug/routes")
async def debug_routes(request: Request) -> Dict[str, Any]:
    paths = sorted({getattr(r, "path", None) for r in request.app.routes if getattr(r, "path", None)})
    return {
        "ok": True,
        "path_count": len(paths),
        "has_market_metrics": "/api/v1/market/metrics" in paths,
        "has_bots_train": "/api/v1/bots/train" in paths,
        "paths": paths,
    }


@router.get("/api/v1/health")
async def health() -> Dict[str, Any]:
    async with state_lock:
        ages: Dict[str, Optional[float]] = {}
        position_state: Dict[str, Any] = {}
        for bot_id, state in bot_state.items():
            last_snapshot = state.get("last_bar_dt") or state.get("last_bar_ts")
            if last_snapshot:
                try:
                    ts = datetime.fromisoformat(str(last_snapshot).replace("Z", "+00:00"))
                    ages[bot_id] = (_utc_now() - ts).total_seconds()
                except Exception:
                    ages[bot_id] = None
            else:
                ages[bot_id] = None
            if state.get("positionState"):
                position_state[bot_id] = state["positionState"]

        return {
            "ok": True,
            "shadow_mode": is_shadow_mode(),
            "lastSnapshotAgeSec": ages,
            "positionState": position_state,
        }


@router.get("/api/v1/metrics")
async def metrics(botId: str = Query(..., alias="botId")) -> Dict[str, Any]:
    async with state_lock:
        state = _get_bot_state(botId)
        last_bar_dt = state.get("last_bar_dt") or state.get("last_bar_ts")
        last_age: Optional[int] = None
        if last_bar_dt:
            try:
                parsed = datetime.fromisoformat(str(last_bar_dt).replace("Z", "+00:00"))
                last_age = int(max(0, (_utc_now() - parsed).total_seconds() * 1000))
            except Exception:
                last_age = None

        return {
            "bots": {
                botId: {
                    "last_bar_age_ms": last_age,
                    "bar_interval_ms": state.get("bar_interval_ms"),
                }
            }
        }


@router.get("/api/v1/monitor/status")
async def monitor_status(botId: str = Query(..., alias="botId")) -> Dict[str, Any]:
    async with state_lock:
        state = _get_bot_state(botId)
        last_seen_utc = state.get("last_seen_utc")
        # Prefer server receive time for bar age (payload clocks can drift / BACKTEST).
        last_bar_rx = state.get("last_bar_rx_utc")
        last_bar_dt = state.get("last_bar_dt") or state.get("last_bar_ts")
        last_bar_age: Optional[float] = None
        if last_bar_rx:
            try:
                parsed = datetime.fromisoformat(str(last_bar_rx).replace("Z", "+00:00"))
                last_bar_age = (_utc_now() - parsed).total_seconds()
            except Exception:
                last_bar_age = None
        elif last_bar_dt:
            try:
                parsed = datetime.fromisoformat(str(last_bar_dt).replace("Z", "+00:00"))
                last_bar_age = (_utc_now() - parsed).total_seconds()
            except Exception:
                last_bar_age = None

        monitor_ts = state.get("strategyMonitor_ts")
        monitor_age: Optional[float] = None
        if monitor_ts:
            try:
                parsed = datetime.fromisoformat(monitor_ts.replace("Z", "+00:00"))
                monitor_age = (_utc_now() - parsed).total_seconds()
            except Exception:
                monitor_age = None

        interval_ms = state.get("bar_interval_ms")
        bar_threshold = 3.0
        if interval_ms is not None:
            try:
                interval_sec = max(0.0, float(interval_ms) / 1000.0)
                if interval_sec > 0:
                    bar_threshold = max(bar_threshold, interval_sec * 1.5 + 1.0)
            except Exception:
                pass

        ok = bool(
            last_bar_age is not None
            and last_bar_age <= bar_threshold
            and monitor_age is not None
            and monitor_age <= 30
        )

        return {
            "ok": ok,
            "ws_open": bool(state.get("connected")),
            "last_seen_utc": last_seen_utc,
            "lastBarTs": state.get("last_bar_ts"),
            "lastBarAgeSec": last_bar_age,
            "lastBarReceivedAgeSec": last_bar_age,
            "strategyMonitorAgeSec": monitor_age,
            "strategyMonitor": state.get("strategyMonitor") or {},
        }
