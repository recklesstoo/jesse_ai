from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from backend.config import is_shadow_mode
from backend.state import _get_bot_state, _utc_now, bot_state, state_lock

router = APIRouter()


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
        last_bar_dt = state.get("last_bar_dt") or state.get("last_bar_ts")
        last_bar_age: Optional[float] = None
        if last_bar_dt:
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

        ok = bool(
            last_bar_age is not None
            and last_bar_age <= 1.5
            and monitor_age is not None
            and monitor_age <= 15
        )

        return {
            "ok": ok,
            "lastBarTs": state.get("last_bar_ts"),
            "lastBarAgeSec": last_bar_age,
            "lastBarReceivedAgeSec": last_bar_age,
            "strategyMonitorAgeSec": monitor_age,
            "strategyMonitor": state.get("strategyMonitor") or {},
        }
