from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, Query

from backend.config import (
    EXECUTION_MODE_DISABLED,
    get_execution_mode,
    get_execution_token,
    set_execution_mode,
)
from backend.state import _get_bot_state, state_lock

router = APIRouter()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/api/v1/execution/status")
async def execution_status(botId: Optional[str] = Query(None, alias="botId")) -> Dict[str, Any]:
    mode = get_execution_mode()
    token_required = bool(get_execution_token())
    reason = "ok"
    if mode == EXECUTION_MODE_DISABLED:
        reason = "execution disabled by policy"
    payload: Dict[str, Any] = {
        "ok": True,
        "execution_mode": mode,
        "enabled": mode != EXECUTION_MODE_DISABLED,
        "reason": reason,
        "token_required": token_required,
        "ts_utc": _utc_iso(),
    }
    if botId:
        async with state_lock:
            state = dict(_get_bot_state(botId))
        payload["botId"] = botId
        payload["ws_connected"] = bool(state.get("connected"))
        payload["last_ws_rx_utc"] = state.get("last_ws_rx_utc")
        payload["last_mode"] = state.get("last_mode")
    return payload


@router.post("/api/v1/execution/enable")
async def execution_enable(
    payload: Dict[str, Any],
    x_execution_token: Optional[str] = Header(None, alias="x-execution-token"),
) -> Dict[str, Any]:
    required = get_execution_token()
    provided = (x_execution_token or payload.get("token") or "").strip()
    if required and provided != required:
        return {
            "ok": False,
            "error": "unauthorized",
            "reason": "missing/invalid execution token",
            "ts_utc": _utc_iso(),
        }

    requested_mode = payload.get("mode") or payload.get("execution_mode")
    ok, normalized = set_execution_mode(str(requested_mode or ""))
    return {
        "ok": bool(ok),
        "execution_mode": normalized,
        "enabled": normalized != EXECUTION_MODE_DISABLED,
        "ts_utc": _utc_iso(),
        "warning": None if required else "No WYCKOFF_EXECUTION_TOKEN set; endpoint is not protected.",
    }
