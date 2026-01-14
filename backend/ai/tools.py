from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi.testclient import TestClient

from backend.ai.assistant import AI_WEB_LOG_PATH, ToolResult


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_app():
    # Lazy import to avoid circular imports during app startup.
    from backend.app import app
    return app


def _call_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    client = TestClient(_get_app())
    res = client.get(path, params=params or {})
    try:
        return res.json()
    except Exception:
        return {"ok": False, "error": "non_json", "status_code": res.status_code, "text": res.text}


def _call_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    client = TestClient(_get_app())
    res = client.post(path, json=payload)
    try:
        return res.json()
    except Exception:
        return {"ok": False, "error": "non_json", "status_code": res.status_code, "text": res.text}


def tool_get_health(_: Dict[str, Any]) -> ToolResult:
    return ToolResult(name="tool_get_health", ok=True, data=_call_get("/api/v1/health"))


def tool_get_bots(_: Dict[str, Any]) -> ToolResult:
    return ToolResult(name="tool_get_bots", ok=True, data=_call_get("/api/v1/bots"))


def tool_get_state(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    return ToolResult(name="tool_get_state", ok=True, data=_call_get("/api/v1/state", params={"botId": bot_id}))


def tool_get_metrics(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    return ToolResult(name="tool_get_metrics", ok=True, data=_call_get("/api/v1/metrics", params={"botId": bot_id}))


def tool_get_swarm_rank(params: Dict[str, Any]) -> ToolResult:
    limit = int(params.get("limit") or 10)
    return ToolResult(name="tool_get_swarm_rank", ok=True, data=_call_get("/api/v1/swarm/rank", params={"limit": limit}))


def tool_get_events(params: Dict[str, Any]) -> ToolResult:
    limit = int(params.get("limit") or 200)
    bot_id = params.get("botId") or params.get("bot_id")
    q = {"limit": limit}
    if bot_id:
        q["botId"] = bot_id
    return ToolResult(name="tool_get_events", ok=True, data=_call_get("/api/v1/events", params=q))


def tool_get_ai_signals_history(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    limit = int(params.get("limit") or 10)
    return ToolResult(
        name="tool_get_ai_signals_history",
        ok=True,
        data=_call_get(f"/api/v1/ai-signals/{bot_id}/history", params={"limit": limit}),
    )


def tool_data_summary(_: Dict[str, Any]) -> ToolResult:
    return ToolResult(name="tool_data_summary", ok=True, data=_call_get("/api/v1/data/summary"))


def tool_data_days_available(params: Dict[str, Any]) -> ToolResult:
    symbol = params.get("symbol") or "MNQ"
    timeframe = params.get("timeframe") or params.get("tf") or "1m"
    return ToolResult(
        name="tool_data_days_available",
        ok=True,
        data=_call_get("/api/v1/data/days", params={"symbol": symbol, "timeframe": timeframe}),
    )


_web_last_ts = 0.0


def tool_web_search(params: Dict[str, Any]) -> ToolResult:
    global _web_last_ts
    query = (params.get("query") or "").strip()
    provider = (os.getenv("WYCKOFF_WEB_SEARCH_PROVIDER") or "").strip().lower()
    rate_limit_sec = float(os.getenv("WYCKOFF_WEB_RATE_LIMIT_SEC", "5"))

    now = time.time()
    if now - _web_last_ts < rate_limit_sec:
        return ToolResult(
            name="tool_web_search",
            ok=False,
            data={"configured": bool(provider), "error": "rate_limited"},
            citations=[],
        )
    _web_last_ts = now

    Path(AI_WEB_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    with AI_WEB_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{_utc_iso()}] q={json.dumps(query, ensure_ascii=False)}\n")

    if not provider:
        return ToolResult(name="tool_web_search", ok=True, data={"configured": False, "note": "Not configured"}, citations=[])

    # Simple provider support: duckduckgo_html (best-effort, no scraping guarantees).
    if provider != "duckduckgo_html":
        return ToolResult(name="tool_web_search", ok=False, data={"configured": True, "error": "unsupported_provider"}, citations=[])

    try:
        r = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=10,
            headers={"User-Agent": "WyckoffAI/1.0"},
        )
        text = r.text or ""
        # Extremely lightweight extraction to avoid dependencies.
        results: List[Dict[str, Any]] = []
        for line in text.splitlines():
            if 'class="result__a"' in line and "href=" in line:
                href = line.split("href=", 1)[1].split('"', 2)[1]
                title = line.split(">", 1)[1].split("<", 1)[0]
                results.append({"title": title, "url": href})
                if len(results) >= 5:
                    break
        citations = [{"url": r["url"], "title": r["title"]} for r in results if r.get("url")]
        return ToolResult(name="tool_web_search", ok=True, data={"configured": True, "results": results}, citations=citations)
    except Exception as exc:
        return ToolResult(name="tool_web_search", ok=False, data={"configured": True, "error": str(exc)}, citations=[])


def default_tool_registry() -> Dict[str, Any]:
    return {
        "tool_get_health": tool_get_health,
        "tool_get_bots": tool_get_bots,
        "tool_get_state": tool_get_state,
        "tool_get_metrics": tool_get_metrics,
        "tool_get_swarm_rank": tool_get_swarm_rank,
        "tool_get_events": tool_get_events,
        "tool_get_ai_signals_history": tool_get_ai_signals_history,
        "tool_data_summary": tool_data_summary,
        "tool_data_days_available": tool_data_days_available,
        "tool_web_search": tool_web_search,
    }
