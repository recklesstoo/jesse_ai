from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.assistant.rag import DocIndex
from backend.assistant.tools import ToolCall, ToolFn, ToolResult, build_tool_registry


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _contains_order_intent(text: str) -> bool:
    t = (text or "").lower()
    keywords = ("buy", "sell", "enter", "order", "execute", "market", "limit", "flatten", "close position", "short", "long")
    return any(k in t for k in keywords)


def _wants_docs(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("how", "como", "cómo", "docs", "readme", "where", "donde", "¿", "explain", "architecture", "endpoint", "ws", "websocket"))


def _wants_web(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("web", "search", "google", "duckduckgo", "buscar"))


def _infer_language(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("¿", "cómo", "dónde", "por qué", "estado", "enjambre", "datos")):
        return "es"
    return "en"


def _suggestions(bot_id: str) -> List[Dict[str, Any]]:
    return [
        {"label": "Show bots", "message": "show bots"},
        {"label": "Bot status", "message": f"status {bot_id}"},
        {"label": "Why feed stale?", "message": f"why is feed stale for {bot_id}?"},
        {"label": "Data summary", "message": "data summary"},
        {"label": "Top swarm", "message": "swarm rank top 5"},
        {"label": "Search docs: WebSocket", "message": "docs websocket /ws/{botId} BAR_DATA"},
    ]


@dataclass
class AssistantConfig:
    repo_root: Path
    rag_include_paths: List[str]


class AssistantService:
    def __init__(self, config: AssistantConfig) -> None:
        self.config = config
        self.doc_index = DocIndex(config.repo_root, config.rag_include_paths)
        self.tools: Dict[str, ToolFn] = build_tool_registry(self.doc_index)
        self._sessions: Dict[str, List[Dict[str, str]]] = {}

    def build_index(self) -> Dict[str, Any]:
        return self.doc_index.build()

    def _session(self, session_id: str) -> List[Dict[str, str]]:
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        return self._sessions[session_id]

    def chat(
        self,
        *,
        bot_id: str,
        message: str,
        ops_mode: bool,
        include_web: bool,
        session_id: Optional[str],
    ) -> Dict[str, Any]:
        ts = _utc_iso()
        bot_id = bot_id or "bot-1"
        msg = (message or "").strip()
        lang = _infer_language(msg)
        session_key = session_id or f"anon:{bot_id}"

        # Hard rule: no orders, no execution toggles.
        if _contains_order_intent(msg):
            reply = (
                "No puedo enviar/ejecutar órdenes. Puedo ayudarte con estado del WS/feed, bots, swarm, eventos y datos."
                if lang == "es"
                else "I can’t place/execute orders. I can help with WS/feed status, bots, swarm, events, and data."
            )
            return {
                "reply": reply,
                "tool_calls": [],
                "tool_results": [],
                "citations": [],
                "suggested_actions": _suggestions(bot_id),
                "status": {"ok": True, "ts_utc": ts, "refused": True},
            }

        history = self._session(session_key)
        history.append({"role": "user", "content": msg})
        history[:] = history[-20:]

        tool_calls: List[ToolCall] = []
        tool_results: List[ToolResult] = []
        citations: List[Dict[str, Any]] = []

        def call_tool(name: str, params: Optional[Dict[str, Any]] = None) -> None:
            fn = self.tools.get(name)
            if not fn:
                return
            tool_calls.append(ToolCall(name=name, params=params or {}))
            res = fn(params or {})
            tool_results.append(res)
            if res.citations:
                citations.extend(res.citations)

        # Tool routing (deterministic).
        ql = msg.lower()
        if ops_mode:
            if any(k in ql for k in ("status", "estado", "health", "monitor", "ws", "feed", "execution")):
                call_tool("tool_get_status", {"botId": bot_id})
            if any(k in ql for k in ("bots", "list bots", "registry")):
                call_tool("tool_list_bots", {})
            if any(k in ql for k in ("swarm", "rank", "ranking", "top")):
                call_tool("tool_get_swarm_rank", {"limit": 10})
            if any(k in ql for k in ("events", "timeline", "logs")):
                call_tool("tool_get_recent_events", {"limit": 50, "botId": bot_id})
            if any(k in ql for k in ("data", "days", "ingest", "clean", "summary")):
                call_tool("tool_get_data_summary", {"botId": bot_id, "includeDays": ("days" in ql)})

        if _wants_docs(msg):
            call_tool("tool_search_docs", {"query": msg, "k": 5})

        if include_web and _wants_web(msg):
            # Delegate to the existing (optional) web tool, if present.
            try:
                from backend.ai.tools import tool_web_search

                tool_calls.append(ToolCall(name="tool_web_search", params={"query": msg}))
                res = tool_web_search({"query": msg})
                tool_results.append(ToolResult(name="tool_web_search", ok=res.ok, data=res.data, citations=res.citations))
                if res.citations:
                    for c in res.citations:
                        citations.append({"type": "web", **c})
            except Exception:
                tool_results.append(ToolResult(name="tool_web_search", ok=False, data={"configured": False, "error": "not_available"}, citations=[]))

        reply = self._compose_reply(msg=msg, lang=lang, bot_id=bot_id, ops_mode=ops_mode, include_web=include_web, tool_results=tool_results, citations=citations)

        history.append({"role": "assistant", "content": reply})
        history[:] = history[-20:]

        return {
            "reply": reply,
            "tool_calls": [tc.__dict__ for tc in tool_calls],
            "tool_results": [tr.__dict__ for tr in tool_results],
            "citations": citations,
            "suggested_actions": _suggestions(bot_id),
            "status": {"ok": True, "ts_utc": ts, "ops_mode": bool(ops_mode), "include_web": bool(include_web)},
        }

    def _compose_reply(
        self,
        *,
        msg: str,
        lang: str,
        bot_id: str,
        ops_mode: bool,
        include_web: bool,
        tool_results: List[ToolResult],
        citations: List[Dict[str, Any]],
    ) -> str:
        if not tool_results and not citations:
            return (
                "Puedo ayudar con: estado del bot, salud del monitor, ranking swarm, eventos recientes y búsqueda en docs."
                if lang == "es"
                else "I can help with: bot status, monitor health, swarm rank, recent events, and doc search."
            )

        lines: List[str] = []
        if lang == "es":
            lines.append("Resumen (read-only):")
        else:
            lines.append("Summary (read-only):")

        def add_line(s: str) -> None:
            if s:
                lines.append(s)

        for res in tool_results:
            if not res.ok:
                add_line(f"- {res.name}: error")
                continue
            if res.name == "tool_get_status":
                st = res.data.get("state") or {}
                computed = st.get("computed") or st  # tolerate different shapes
                execs = res.data.get("execution") or {}
                mon = res.data.get("monitor") or {}
                add_line(f"- Bot `{bot_id}`: ws_connected={computed.get('ws_connected')} feed={computed.get('feed_status')} src={computed.get('data_source')} nt_mode={computed.get('nt_mode')}")
                add_line(f"- Monitor: ok={mon.get('ok')} barAgeSec={mon.get('lastBarAgeSec')} monAgeSec={mon.get('strategyMonitorAgeSec')}")
                add_line(f"- Execution: mode={execs.get('execution_mode')} enabled={execs.get('enabled')} reason={execs.get('reason')}")
            elif res.name == "tool_list_bots":
                computed = (res.data.get("computed") or {})
                total = len(computed) if isinstance(computed, dict) else None
                connected = sum(1 for _, v in (computed or {}).items() if isinstance(v, dict) and v.get("ws_connected"))
                add_line(f"- Bots: connected={connected} total={total}")
            elif res.name == "tool_get_swarm_rank":
                rank = (res.data.get("rank") or [])
                top = ", ".join([f"{r.get('botId')}({r.get('score')})" for r in rank[:5]])
                add_line(f"- Swarm top: {top or '--'}")
            elif res.name == "tool_get_recent_events":
                add_line(f"- Events: {res.data.get('count')} (latest first)")
            elif res.name == "tool_get_data_summary":
                bars = res.data.get("bars") or {}
                trades = res.data.get("trades") or {}
                add_line(f"- Data bars: LIVE_WS={bars.get('LIVE_WS')} IMPORT={bars.get('IMPORT')} CACHED={bars.get('CACHED')} SIMULATED={bars.get('SIMULATED')}")
                add_line(f"- Trades: LIVE_WS={trades.get('LIVE_WS')} IMPORT={trades.get('IMPORT')} CACHED={trades.get('CACHED')} SIMULATED={trades.get('SIMULATED')}")
            elif res.name == "tool_search_docs":
                add_line(f"- Docs: {res.data.get('count')} matches")
            elif res.name == "tool_web_search":
                add_line("- Web: results added to Sources" if include_web else "- Web: disabled")

        if citations:
            if lang == "es":
                lines.append("")
                lines.append("Fuentes disponibles en ‘Sources’ (docs/endpoints/web).")
            else:
                lines.append("")
                lines.append("Sources available under ‘Sources’ (docs/endpoints/web).")

        return "\n".join(lines)


assistant_singleton: Optional[AssistantService] = None


def get_assistant_service(repo_root: Path) -> AssistantService:
    global assistant_singleton
    if assistant_singleton is None:
        include = [
            "README.md",
            "docs",
            "backend",
            "frontend/src",
            "scripts",
        ]
        extra = (os.getenv("WYCKOFF_RAG_INCLUDE") or "").strip()
        if extra:
            include.extend([p.strip() for p in extra.split(",") if p.strip()])
        assistant_singleton = AssistantService(AssistantConfig(repo_root=repo_root, rag_include_paths=include))
    return assistant_singleton
