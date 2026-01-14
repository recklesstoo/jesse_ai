from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from fastapi.testclient import TestClient

from backend.assistant.rag import DocIndex


@dataclass(frozen=True)
class ToolCall:
    name: str
    params: Dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    data: Any
    citations: Optional[List[Dict[str, Any]]] = None


ToolFn = Callable[[Dict[str, Any]], ToolResult]


def _get_app():
    from backend.app import app
    return app


def _call_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    client = TestClient(_get_app())
    res = client.get(path, params=params or {})
    try:
        data = res.json()
    except Exception:
        data = {"ok": False, "error": "non_json", "status_code": res.status_code, "text": res.text}
    data.setdefault("_meta", {})["endpoint"] = path
    data["_meta"]["status_code"] = res.status_code
    return data


def tool_list_bots(_: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        name="tool_list_bots",
        ok=True,
        data=_call_get("/api/v1/bots"),
        citations=[{"type": "endpoint", "path": "/api/v1/bots"}],
    )


def tool_get_swarm_rank(params: Dict[str, Any]) -> ToolResult:
    limit = int(params.get("limit") or 10)
    return ToolResult(
        name="tool_get_swarm_rank",
        ok=True,
        data=_call_get("/api/v1/swarm/rank", params={"limit": limit}),
        citations=[{"type": "endpoint", "path": "/api/v1/swarm/rank", "params": {"limit": limit}}],
    )


def tool_get_recent_events(params: Dict[str, Any]) -> ToolResult:
    limit = int(params.get("limit") or 100)
    bot_id = params.get("botId") or params.get("bot_id")
    q: Dict[str, Any] = {"limit": limit}
    if bot_id:
        q["botId"] = bot_id
    return ToolResult(
        name="tool_get_recent_events",
        ok=True,
        data=_call_get("/api/v1/events", params=q),
        citations=[{"type": "endpoint", "path": "/api/v1/events", "params": q}],
    )


def tool_get_data_summary(params: Dict[str, Any]) -> ToolResult:
    q: Dict[str, Any] = {}
    if params.get("botId"):
        q["botId"] = params["botId"]
    if params.get("symbol"):
        q["symbol"] = params["symbol"]
    if "includeDays" in params:
        q["includeDays"] = bool(params["includeDays"])
    if params.get("day"):
        q["day"] = params["day"]
    if params.get("source"):
        q["source"] = params["source"]
    return ToolResult(
        name="tool_get_data_summary",
        ok=True,
        data=_call_get("/api/v1/data/summary", params=q),
        citations=[{"type": "endpoint", "path": "/api/v1/data/summary", "params": q}],
    )


def tool_get_status(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    state = _call_get("/api/v1/state", params={"botId": bot_id})
    monitor = _call_get("/api/v1/monitor/status", params={"botId": bot_id})
    execution = _call_get("/api/v1/execution/status", params={"botId": bot_id})
    citations = [
        {"type": "endpoint", "path": "/api/v1/state", "params": {"botId": bot_id}},
        {"type": "endpoint", "path": "/api/v1/monitor/status", "params": {"botId": bot_id}},
        {"type": "endpoint", "path": "/api/v1/execution/status", "params": {"botId": bot_id}},
    ]
    return ToolResult(
        name="tool_get_status",
        ok=True,
        data={
            "botId": bot_id,
            "state": state,
            "monitor": monitor,
            "execution": execution,
        },
        citations=citations,
    )


def tool_search_docs(params: Dict[str, Any], *, index: DocIndex) -> ToolResult:
    query = str(params.get("query") or "").strip()
    k = int(params.get("k") or 5)
    citations = index.search(query, k=k)
    return ToolResult(name="tool_search_docs", ok=True, data={"query": query, "count": len(citations)}, citations=citations)


def build_tool_registry(doc_index: DocIndex) -> Dict[str, ToolFn]:
    return {
        "tool_get_status": tool_get_status,
        "tool_list_bots": tool_list_bots,
        "tool_get_swarm_rank": tool_get_swarm_rank,
        "tool_get_data_summary": tool_get_data_summary,
        "tool_get_recent_events": tool_get_recent_events,
        "tool_search_docs": lambda params: tool_search_docs(params, index=doc_index),
    }
