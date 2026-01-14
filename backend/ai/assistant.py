from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
AI_LOG_PATH = LOG_DIR / "ai_assistant.log"
AI_WEB_LOG_PATH = LOG_DIR / "ai_web.log"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _log_line(path: Path, line: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass


def _contains_order_intent(text: str) -> bool:
    t = (text or "").lower()
    keywords = ("buy", "sell", "enter", "order", "execute", "market", "limit", "flatten", "close position", "short", "long")
    return any(k in t for k in keywords)


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    data: Any
    citations: Optional[List[Dict[str, Any]]] = None


ToolFn = Callable[[Dict[str, Any]], ToolResult]


class Assistant:
    """
    Natural-language assistant for observability/diagnostics/data management.

    Hard rule: never executes trading orders, never calls order execution endpoints.
    """

    def __init__(self, tools: Optional[Dict[str, ToolFn]] = None) -> None:
        self.tools = tools or {}

    def capabilities(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "name": "Wyckoff AI Advanced Assistant",
            "can": [
                "summarize system health and bot connectivity",
                "diagnose WS/feed staleness and missing timestamps",
                "rank bots (read-only) and explain readiness",
                "analyze events, trades, and data quality",
                "suggest actions to take in UI (no auto-exec)",
            ],
            "cannot": [
                "place, send, or execute trading orders",
                "call any order execution endpoints",
                "modify data without explicit user-triggered endpoints",
            ],
            "tools": sorted(list(self.tools.keys())),
            "web_tools": {
                "supported": True,
                "enabled_by_default": False,
                "configured": bool(os.getenv("WYCKOFF_WEB_SEARCH_PROVIDER")),
            },
        }

    def answer(
        self,
        query: str,
        context: Dict[str, Any],
        tools_enabled: bool,
        bot_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ts = _utc_iso()
        q = (query or "").strip()
        _log_line(AI_LOG_PATH, f"[{ts}] bot_id={bot_id or '-'} tools={bool(tools_enabled)} q={json.dumps(q, ensure_ascii=False)}")

        if not q:
            return {
                "answer": "Escribe una pregunta (estado, bots, swarm, eventos, data quality).",
                "actions": [],
                "citations": [],
                "status": {"ok": True, "ts_utc": ts},
            }

        if _contains_order_intent(q):
            return {
                "answer": "No puedo enviar ni ejecutar órdenes. Puedo ayudarte a diagnosticar el feed, el estado del bridge y la calidad de datos, y sugerir pasos manuales.",
                "actions": [
                    {"type": "INFO", "label": "Open Manual Trading panel", "details": "Use los controles manuales; el asistente no ejecuta órdenes."}
                ],
                "citations": [],
                "status": {"ok": True, "ts_utc": ts, "refused": True},
            }

        tool_results: List[ToolResult] = []
        citations: List[Dict[str, Any]] = []
        actions: List[Dict[str, Any]] = []

        def run_tool(name: str, params: Optional[Dict[str, Any]] = None) -> None:
            if not tools_enabled:
                return
            fn = self.tools.get(name)
            if not fn:
                return
            res = fn(params or {})
            tool_results.append(res)
            if res.citations:
                citations.extend(res.citations)

        # Minimal intent routing.
        ql = q.lower()
        if any(k in ql for k in ("health", "salud", "healthy")):
            run_tool("tool_get_health", {})
        if any(k in ql for k in ("bots", "registry", "conect", "connected")):
            run_tool("tool_get_bots", {})
        if bot_id and any(k in ql for k in ("state", "estado", "feed", "mode", "src", "source")):
            run_tool("tool_get_state", {"botId": bot_id})
        if bot_id and any(k in ql for k in ("metrics", "latency", "perf")):
            run_tool("tool_get_metrics", {"botId": bot_id})
        if any(k in ql for k in ("swarm", "rank", "ranking", "top")):
            run_tool("tool_get_swarm_rank", {"limit": 10})
        if any(k in ql for k in ("events", "timeline", "log")):
            run_tool("tool_get_events", {"limit": 50, "botId": bot_id})
        if any(k in ql for k in ("data", "days", "ingest", "clean")):
            run_tool("tool_data_summary", {})
            run_tool("tool_data_days_available", {"botId": bot_id})
            actions.append({"type": "NAVIGATE", "label": "Open Data Manager", "target": "data_manager"})

        if tools_enabled and ("web" in ql or "search" in ql):
            run_tool("tool_web_search", {"query": q})

        # Compose a concise answer.
        lines: List[str] = []
        if tool_results:
            lines.append("Resumen (read-only):")
            for res in tool_results:
                if not res.ok:
                    lines.append(f"- {res.name}: error")
                    continue
                # Heuristic summarization per tool.
                if res.name == "tool_get_health":
                    ok = bool(res.data.get("ok"))
                    shadow = res.data.get("shadow_mode")
                    lines.append(f"- Health: {'OK' if ok else 'NOT OK'} (shadow={shadow})")
                elif res.name == "tool_get_state":
                    lines.append(f"- State: feed={res.data.get('feed_status')} src={res.data.get('data_source')} nt_mode={res.data.get('nt_mode')} ws_connected={res.data.get('ws_connected')}")
                elif res.name == "tool_get_bots":
                    computed = (res.data.get("computed") or {})
                    connected = sum(1 for _, v in computed.items() if v.get("ws_connected"))
                    live = sum(1 for _, v in computed.items() if v.get("feed_status") == "LIVE" and v.get("data_source") == "LIVE_WS")
                    lines.append(f"- Bots: connected={connected} live_feed={live} total={len(computed)}")
                elif res.name == "tool_get_swarm_rank":
                    rank = res.data.get("rank") or []
                    top = ", ".join([f"{r.get('botId')}({r.get('score')})" for r in rank[:5]])
                    lines.append(f"- Swarm top: {top or '--'}")
                elif res.name == "tool_get_events":
                    lines.append(f"- Events: {res.data.get('count')} (latest first)")
                elif res.name == "tool_data_summary":
                    bars = (res.data.get("bars") or {})
                    lines.append(
                        f"- Data: bars LIVE_WS={bars.get('LIVE_WS')} IMPORT={bars.get('IMPORT')} CACHED={bars.get('CACHED')} SIMULATED={bars.get('SIMULATED')}"
                    )
                elif res.name == "tool_data_days_available":
                    days = res.data.get("days") or []
                    lines.append(f"- Days available: {len(days)}")
                elif res.name == "tool_web_search":
                    if res.ok and res.data.get("configured"):
                        lines.append(f"- Web: {len(res.data.get('results') or [])} results")
                    else:
                        lines.append("- Web: not configured")

        if not lines:
            lines.append("Puedo ayudarte con: health, bots, state/feed, swarm rank, events, data (days/quality).")

        # Suggestions (never execution).
        actions.append({"type": "SUGGESTION", "label": "Ask for 'status bots' or 'swarm rank'", "details": "Ej: 'status bots' / 'swarm rank' / 'data days MNQ 1m'."})

        return {
            "answer": "\n".join(lines),
            "actions": actions,
            "citations": citations,
            "status": {"ok": True, "ts_utc": ts, "tools_enabled": bool(tools_enabled)},
        }


assistant_singleton: Optional[Assistant] = None


def get_assistant(tools: Optional[Dict[str, ToolFn]] = None) -> Assistant:
    global assistant_singleton
    if assistant_singleton is None:
        assistant_singleton = Assistant(tools=tools)
    return assistant_singleton
