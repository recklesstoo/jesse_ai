from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.ai.assistant import get_assistant
from backend.ai.tools import default_tool_registry

router = APIRouter()


class AIChatIn(BaseModel):
    message: str
    botId: Optional[str] = None
    tools: bool = False


@router.get("/api/v1/ai/capabilities")
def ai_capabilities() -> Dict[str, Any]:
    assistant = get_assistant(tools=default_tool_registry())
    return assistant.capabilities()


@router.get("/api/v1/ai/context")
def ai_context(botId: Optional[str] = Query(None, alias="botId")) -> Dict[str, Any]:
    tools = default_tool_registry()
    # Build a compact snapshot using internal tools (read-only).
    health = tools["tool_get_health"]({}).data
    bots = tools["tool_get_bots"]({}).data
    state = tools["tool_get_state"]({"botId": botId}).data if botId else None
    swarm = tools["tool_get_swarm_rank"]({"limit": 10}).data
    data_summary = tools["tool_data_summary"]({}).data
    return {
        "ok": True,
        "health": health,
        "bots": bots,
        "state": state,
        "swarm_rank": swarm,
        "data_summary": data_summary,
    }


@router.post("/api/v1/ai/chat")
def ai_chat(payload: AIChatIn) -> Dict[str, Any]:
    tools = default_tool_registry()
    assistant = get_assistant(tools=tools)
    bot_id = payload.botId or None
    context = {"botId": bot_id}
    return assistant.answer(payload.message, context=context, tools_enabled=bool(payload.tools), bot_id=bot_id)

