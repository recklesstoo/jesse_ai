from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str = Field(default="bot-1", alias="botId")
    message: str
    ops_mode: bool = Field(default=True, alias="opsMode")
    include_web: bool = Field(default=False, alias="includeWeb")
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    ops_token: Optional[str] = Field(default=None, alias="opsToken")


class AssistantChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = True
    reply: str
    status: Optional[Dict[str, Any]] = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    tool_results: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_actions: List[Dict[str, Any]] = Field(default_factory=list)

