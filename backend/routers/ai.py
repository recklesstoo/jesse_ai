from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

import os

from backend.assistant.chat import get_openai_assistant
from backend.market.buffer import market_buffer
from backend.market.metrics import compute_market_metrics_v1
from backend.state import compute_feed_status, state_lock
from backend.database import PROJECT_ROOT

router = APIRouter()


class AIChatIn(BaseModel):
    message: str
    botId: Optional[str] = None
    tools: bool = False


@router.get("/api/v1/ai/capabilities")
def ai_capabilities() -> Dict[str, Any]:
    # Legacy endpoint retained for compatibility.
    return {
        "ok": True,
        "deprecated": True,
        "use": "/api/v1/assistant/chat",
        "note": "Use /api/v1/assistant/chat (opsMode=true) for read-only tool access and Market Metrics v1 facts.",
    }


@router.get("/api/v1/ai/context")
def ai_context(botId: Optional[str] = Query(None, alias="botId")) -> Dict[str, Any]:
    # Legacy endpoint retained for compatibility; use /api/v1/assistant/context for the stable snapshot.
    return {"ok": True, "deprecated": True, "use": "/api/v1/assistant/context", "botId": botId}


@router.post("/api/v1/ai/chat")
async def ai_chat(payload: AIChatIn) -> Dict[str, Any]:
    # Forward to the canonical assistant pipeline to avoid contract drift.
    bot_id = payload.botId or "bot-1"
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if api_key:
        assistant = get_openai_assistant(PROJECT_ROOT)
        res = assistant.chat(
            bot_id=bot_id,
            message=payload.message,
            ops_mode=bool(payload.tools),
            include_web=False,
            session_id=None,
        )
        # Legacy alias expected by older clients/tests.
        if isinstance(res, dict) and "reply" in res and "answer" not in res:
            res["answer"] = res.get("reply")
        res.setdefault("ok", True)
        res.setdefault("deprecated", True)
        res.setdefault("use", "/api/v1/assistant/chat")
        return res

    # No OpenAI key: return a deterministic, read-only snapshot (no invention).
    async with state_lock:
        st = compute_feed_status(bot_id)
    symbol = str((st.get("instrument") or st.get("last_symbol") or "MNQ")).upper()
    bars = market_buffer.get_bars(symbol=symbol, timeframe="1m", limit=500)
    resp, _ = compute_market_metrics_v1(
        bars=bars,
        symbol=symbol,
        timeframe="1m",
        ws_age_sec=st.get("ws_age_sec"),
        bar_age_sec_override=st.get("bar_age_sec"),
        last_ws_ts_utc=st.get("last_seen_utc"),
        ws_stale_sec=10.0,
        lookback=500,
        mode="summary",
    )
    answer = (
        f"AI (legacy) sin OPENAI_API_KEY. Estado bot={bot_id} feed_status={st.get('feed_status')} data_source={st.get('data_source')} "
        f"ws_age_sec={st.get('ws_age_sec')} bar_age_sec={st.get('bar_age_sec')}.\n"
        f"MarketMetrics 1m: feed_status={resp.get('feed_status')} confidence={resp.get('confidence')} last_bar_ts_utc={resp.get('last_bar_ts_utc')}."
    )
    return {"ok": True, "answer": answer, "deprecated": True, "use": "/api/v1/assistant/chat", "state": st, "market": resp}
