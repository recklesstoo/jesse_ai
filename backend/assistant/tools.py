from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from fastapi.testclient import TestClient

from backend.assistant.rag import DocIndex
from backend.compat import bars_store
from backend.database import SessionLocal
from backend.models import TradeEvent


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


def tool_get_state(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    data = _call_get("/api/v1/state", params={"botId": bot_id})
    return ToolResult(
        name="tool_get_state",
        ok=True,
        data=data,
        citations=[{"type": "endpoint", "path": "/api/v1/state", "params": {"botId": bot_id}}],
    )


def tool_get_monitor_status(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    data = _call_get("/api/v1/monitor/status", params={"botId": bot_id})
    return ToolResult(
        name="tool_get_monitor_status",
        ok=True,
        data=data,
        citations=[{"type": "endpoint", "path": "/api/v1/monitor/status", "params": {"botId": bot_id}}],
    )


def tool_get_commands_log(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    limit = int(params.get("limit") or 100)
    data = _call_get(f"/api/v1/commands/{bot_id}/log", params={"limit": limit})
    return ToolResult(
        name="tool_get_commands_log",
        ok=True,
        data={"botId": bot_id, "limit": limit, "log": data.get("log") or []},
        citations=[{"type": "endpoint", "path": f"/api/v1/commands/{bot_id}/log", "params": {"limit": limit}}],
    )


def tool_swarm_rank(params: Dict[str, Any]) -> ToolResult:
    limit = int(params.get("limit") or 10)
    return ToolResult(
        name="tool_swarm_rank",
        ok=True,
        data=_call_get("/api/v1/swarm/rank", params={"limit": limit}),
        citations=[{"type": "endpoint", "path": "/api/v1/swarm/rank", "params": {"limit": limit}}],
    )


def tool_get_recent_bars(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    n = int(params.get("n") or params.get("limit") or 50)
    n = max(1, min(500, n))
    recent = list(bars_store.get(bot_id) or [])
    items = recent[-n:]
    return ToolResult(
        name="tool_get_recent_bars",
        ok=True,
        data={"botId": bot_id, "count": len(items), "bars": items},
        citations=[{"type": "internal", "path": "backend.compat.bars_store", "note": "in-memory recent BAR_DATA cache"}],
    )


def tool_get_recent_trades(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    n = int(params.get("n") or params.get("limit") or 50)
    n = max(1, min(500, n))
    db = SessionLocal()
    try:
        rows = (
            db.query(TradeEvent)
            .filter(TradeEvent.bot_id == bot_id)
            .order_by(TradeEvent.ts_utc.desc())
            .limit(n)
            .all()
        )
        trades = [
            {
                "id": r.id,
                "ts_utc": r.ts_utc.isoformat().replace("+00:00", "Z") if r.ts_utc else None,
                "symbol": r.symbol,
                "action": r.action,
                "qty": r.qty,
                "price": r.price,
                "reason": r.reason,
                "market_position": r.market_position,
                "data_source": r.data_source,
            }
            for r in rows
        ]
        return ToolResult(
            name="tool_get_recent_trades",
            ok=True,
            data={"botId": bot_id, "count": len(trades), "trades": trades},
            citations=[{"type": "db", "table": "trade_events", "filter": {"bot_id": bot_id}, "limit": n}],
        )
    except Exception as exc:
        return ToolResult(name="tool_get_recent_trades", ok=False, data={"error": str(exc)}, citations=[])
    finally:
        db.close()


def tool_explain_feed_state(params: Dict[str, Any]) -> ToolResult:
    bot_id = params.get("botId") or params.get("bot_id") or "bot-1"
    st = _call_get("/api/v1/state", params={"botId": bot_id})
    feed_status = st.get("feed_status")
    src = st.get("data_source")
    ws_connected = st.get("ws_connected")
    nt_mode = st.get("nt_mode")
    bar_age = st.get("bar_age_sec")
    ws_age = st.get("ws_age_sec")
    reason = st.get("feed_reason") or "unknown"

    steps: List[str] = []
    if not ws_connected:
        steps.append("BridgePuppet no está conectado a `ws://127.0.0.1:8000/ws/{botId}`.")
        steps.append("Verifica NinjaTrader Strategy: BridgePuppet corriendo y conexión WS.")
    if src == "UNKNOWN_TS":
        steps.append("BAR_DATA llega sin timestamp válido; revisar payload de BridgePuppet.")
    if src == "CACHED":
        steps.append("La UI está mostrando valores cacheados: no hay feed LIVE_WS reciente.")
    if feed_status != "LIVE":
        steps.append("Espera BAR_DATA reciente o revisa thresholds de staleness.")

    return ToolResult(
        name="tool_explain_feed_state",
        ok=True,
        data={
            "botId": bot_id,
            "nt_mode": nt_mode,
            "ws_connected": ws_connected,
            "data_source": src,
            "feed_status": feed_status,
            "bar_age_sec": bar_age,
            "ws_age_sec": ws_age,
            "feed_reason": reason,
            "recommended_steps": steps[:6],
        },
        citations=[{"type": "endpoint", "path": "/api/v1/state", "params": {"botId": bot_id}}],
    )


def tool_search_docs(params: Dict[str, Any], *, index: DocIndex) -> ToolResult:
    query = str(params.get("query") or "").strip()
    k = int(params.get("k") or 5)
    citations = index.search(query, k=k)
    return ToolResult(name="tool_search_docs", ok=True, data={"query": query, "count": len(citations)}, citations=citations)


def build_tool_registry(doc_index: DocIndex) -> Dict[str, ToolFn]:
    return {
        "tool_get_status": tool_get_status,
        "tool_get_state": tool_get_state,
        "tool_get_monitor_status": tool_get_monitor_status,
        "tool_list_bots": tool_list_bots,
        "tool_get_swarm_rank": tool_get_swarm_rank,
        "tool_swarm_rank": tool_swarm_rank,
        "tool_get_data_summary": tool_get_data_summary,
        "tool_get_recent_events": tool_get_recent_events,
        "tool_get_recent_bars": tool_get_recent_bars,
        "tool_get_recent_trades": tool_get_recent_trades,
        "tool_get_commands_log": tool_get_commands_log,
        "tool_explain_feed_state": tool_explain_feed_state,
        "tool_search_docs": lambda params: tool_search_docs(params, index=doc_index),
    }
