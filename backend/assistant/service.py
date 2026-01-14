from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.assistant.rag import DocIndex
from backend.assistant.tools import ToolCall, ToolFn, ToolResult, build_tool_registry

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
SESSIONS_LOG = LOG_DIR / "doctor_assistant_sessions.jsonl"
SESSIONS_DIR = LOG_DIR / "doctor_sessions"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _contains_order_intent(text: str) -> bool:
    t = (text or "").lower()
    keywords = (
        "buy",
        "sell",
        "enter",
        "order",
        "execute",
        "market",
        "limit",
        "flatten",
        "close position",
        "short",
        "long",
        "compra",
        "vende",
        "vender",
        "comprar",
        "ejecuta",
        "ejecutar",
        "orden",
    )
    return any(k in t for k in keywords)


def _wants_docs(text: str) -> bool:
    t = (text or "").lower()
    return any(
        k in t
        for k in (
            "how",
            "como",
            "cómo",
            "docs",
            "readme",
            "where",
            "donde",
            "explain",
            "arquitectura",
            "endpoint",
            "ws",
            "websocket",
        )
    )


def _infer_language(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("¿", "cómo", "dónde", "por qué", "estado", "enjambre", "datos")):
        return "es"
    return "en"


def _suggestions(bot_id: str) -> List[Dict[str, Any]]:
    return [
        {"label": "Estado bot", "message": f"estado {bot_id}"},
        {"label": "Por qué STALE", "message": f"por qué está stale {bot_id}"},
        {"label": "Swarm top", "message": "swarm rank top 5"},
        {"label": "Data health", "message": "data summary + available days"},
        {"label": "Comandos/ACK", "message": f"commands log {bot_id}"},
        {"label": "Docs WS BAR_DATA", "message": "docs websocket /ws/{botId} BAR_DATA timestamp"},
    ]


def _log_session_line(payload: Dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with SESSIONS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_session(session_id: str) -> Dict[str, Any]:
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        p = (SESSIONS_DIR / f"{session_id}.json").resolve()
        if not p.exists():
            return {"summary": "", "turns": []}
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"summary": "", "turns": []}


def _save_session(session_id: str, summary: str, turns: List[Dict[str, str]]) -> None:
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        p = (SESSIONS_DIR / f"{session_id}.json").resolve()
        p.write_text(json.dumps({"summary": summary, "turns": turns[-20:]}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


@dataclass
class AssistantConfig:
    repo_root: Path
    rag_include_paths: List[str]


class AssistantService:
    def __init__(self, config: AssistantConfig) -> None:
        self.config = config
        self.doc_index = DocIndex(config.repo_root, config.rag_include_paths)
        self.tools: Dict[str, ToolFn] = build_tool_registry(self.doc_index)

    def build_index(self) -> Dict[str, Any]:
        return self.doc_index.build()

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

        if _contains_order_intent(msg):
            reply = (
                "Doctor: no ejecuto órdenes. Si quieres operar, te doy setup+riesgo+invalidación y tú ejecutas."
                if lang == "es"
                else "Doctor: I don’t execute orders. I’ll give you setup+risk+invalidation, you execute."
            )
            return {
                "reply": reply,
                "tool_calls": [],
                "tool_results": [],
                "citations": [],
                "suggested_actions": _suggestions(bot_id),
                "system_state_snapshot": {"botId": bot_id, "note": "order intent refused"},
                "status": {"ok": True, "ts_utc": ts, "refused": True},
            }

        persisted = _load_session(session_key)
        summary = str(persisted.get("summary") or "").strip()
        turns: List[Dict[str, str]] = list(persisted.get("turns") or [])
        turns.append({"role": "user", "content": msg})
        turns = turns[-20:]

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

        ql = msg.lower()
        wants_ops_data = any(
            k in ql
            for k in (
                "estado",
                "status",
                "feed",
                "ws",
                "monitor",
                "lat",
                "enjambre",
                "swarm",
                "bots",
                "datos",
                "data",
                "db",
                "bar",
                "barras",
                "bars",
                "trade",
                "trades",
                "operaciones",
                "fills",
                "comandos",
                "ack",
            )
        )

        if wants_ops_data and not ops_mode:
            reply = (
                "Doctor: me pediste diagnóstico con datos reales, pero `opsMode=false`.\n"
                "Activa `opsMode=true` y repite la pregunta. Sin datos, no invento."
                if lang == "es"
                else "Doctor: you asked for real diagnostics, but `opsMode=false`. Enable it and ask again. I won’t guess."
            )
            turns.append({"role": "assistant", "content": reply})
            _save_session(session_key, summary, turns)
            _log_session_line({"ts_utc": ts, "session_id": session_key, "bot_id": bot_id, "opsMode": False, "msg": msg, "reply": reply})
            return {
                "reply": reply,
                "tool_calls": [],
                "tool_results": [],
                "citations": [],
                "suggested_actions": _suggestions(bot_id),
                "system_state_snapshot": {"botId": bot_id, "note": "opsMode disabled; no tools used"},
                "status": {"ok": True, "ts_utc": ts, "ops_mode": False, "include_web": bool(include_web)},
            }

        if ops_mode:
            call_tool("tool_get_status", {"botId": bot_id})

            if any(k in ql for k in ("por qué", "porque", "stale", "unknown_ts")):
                call_tool("tool_explain_feed_state", {"botId": bot_id})
            if any(k in ql for k in ("bots", "registry", "lista")):
                call_tool("tool_list_bots", {})
            if any(k in ql for k in ("swarm", "enjambre", "rank", "ranking", "top", "ready")):
                call_tool("tool_get_swarm_rank", {"limit": 10})
            if any(k in ql for k in ("events", "timeline", "log", "logs", "eventos")):
                call_tool("tool_get_recent_events", {"limit": 80, "botId": bot_id})
            if any(k in ql for k in ("data", "datos", "db", "summary", "days", "días", "ingest", "clean")):
                call_tool("tool_get_data_summary", {"botId": bot_id, "includeDays": True})
            if any(k in ql for k in ("bars", "barras", "precio", "volumen", "ohlc")):
                call_tool("tool_get_recent_bars", {"botId": bot_id, "n": 80})
            if any(k in ql for k in ("trades", "operaciones", "fills")):
                call_tool("tool_get_recent_trades", {"botId": bot_id, "n": 50})
            if any(k in ql for k in ("commands", "comandos", "ack")):
                call_tool("tool_get_commands_log", {"botId": bot_id, "limit": 80})

        if _wants_docs(msg):
            call_tool("tool_search_docs", {"query": msg, "k": 6})

        if include_web and any(k in ql for k in ("web", "buscar", "search", "duckduckgo")):
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

        reply, snapshot = self._compose_doctor_reply(bot_id=bot_id, msg=msg, tool_results=tool_results)

        if not summary:
            summary = f"Bot={bot_id}. Último tema: {msg[:120]}"
        else:
            summary = (summary[:800] + f" | {msg[:80]}").strip()

        turns.append({"role": "assistant", "content": reply})
        turns = turns[-20:]
        _save_session(session_key, summary, turns)
        _log_session_line(
            {
                "ts_utc": ts,
                "session_id": session_key,
                "bot_id": bot_id,
                "opsMode": bool(ops_mode),
                "includeWeb": bool(include_web),
                "msg": msg,
                "tools": [tc.name for tc in tool_calls],
            }
        )

        return {
            "reply": reply,
            "tool_calls": [tc.__dict__ for tc in tool_calls],
            "tool_results": [tr.__dict__ for tr in tool_results],
            "citations": citations,
            "suggested_actions": _suggestions(bot_id),
            "system_state_snapshot": snapshot,
            "status": {"ok": True, "ts_utc": ts, "ops_mode": bool(ops_mode), "include_web": bool(include_web)},
        }

    def _compose_doctor_reply(self, *, bot_id: str, msg: str, tool_results: List[ToolResult]) -> Tuple[str, Dict[str, Any]]:
        status = next((r for r in tool_results if r.name == "tool_get_status" and r.ok), None)
        explain = next((r for r in tool_results if r.name == "tool_explain_feed_state" and r.ok), None)
        data_sum = next((r for r in tool_results if r.name == "tool_get_data_summary" and r.ok), None)
        swarm = next((r for r in tool_results if r.name == "tool_get_swarm_rank" and r.ok), None)
        bars = next((r for r in tool_results if r.name == "tool_get_recent_bars" and r.ok), None)
        trades = next((r for r in tool_results if r.name == "tool_get_recent_trades" and r.ok), None)

        snap: Dict[str, Any] = {"botId": bot_id}

        lines: List[str] = []
        lines.append("DOCTOR TRADER — diagnóstico sin humo (NO ejecuto órdenes).")
        lines.append(f"Pregunta: {msg}")

        if status:
            st = status.data.get("state") or {}
            mon = status.data.get("monitor") or {}
            exe = status.data.get("execution") or {}
            snap["state"] = st
            snap["monitor"] = mon
            snap["execution"] = exe

            lines.append("")
            lines.append("Estado operativo (real):")
            lines.append(f"- nt_mode={st.get('nt_mode')} mode={st.get('mode')} transport_connected={st.get('transport_connected')}")
            lines.append(f"- feed_status={st.get('feed_status')} data_source={st.get('data_source')} ws_age_sec={st.get('ws_age_sec')} bar_age_sec={st.get('bar_age_sec')}")
            if st.get("feed_reason"):
                lines.append(f"- por qué: {st.get('feed_reason')}")
            lines.append(f"- execution_mode={exe.get('execution_mode')} enabled={exe.get('enabled')} reason={exe.get('reason')}")
            lines.append(f"- monitor_ok={mon.get('ok')} monitor_age={mon.get('strategyMonitorAgeSec')}")

        if explain:
            ex = explain.data or {}
            steps = ex.get("recommended_steps") or []
            if steps:
                lines.append("")
                lines.append("Si estás STALE, aquí está la receta:")
                for s in steps[:6]:
                    lines.append(f"- {s}")

        if bars:
            b = bars.data.get("bars") or []
            last = b[-1] if b else None
            if last:
                lines.append("")
                lines.append("Mercado (última barra recibida):")
                lines.append(f"- symbol={last.get('symbol')} tf={last.get('timeframe')}")
                lines.append(f"- ts={last.get('ts') or last.get('timestamp')}")
                lines.append(f"- ohlc={last.get('open')},{last.get('high')},{last.get('low')},{last.get('close')} vol={last.get('volume')}")

        if trades:
            lines.append("")
            lines.append(f"Trades recientes (DB): count={trades.data.get('count')}")

        if data_sum:
            ds = data_sum.data or {}
            breakdown = ds.get("breakdown") or {}
            days = ds.get("available_days") or []
            lines.append("")
            lines.append("Data health (DB):")
            lines.append(f"- available_days={len(days)} (último={days[0] if days else '--'})")
            lines.append(f"- breakdown REAL={breakdown.get('REAL')} SIMULATED={breakdown.get('SIMULATED')}")

        if swarm:
            rank = swarm.data.get("rank") or []
            top = ", ".join([f"{r.get('botId')}({r.get('score')})" for r in rank[:5]])
            lines.append("")
            lines.append("Enjambre (top):")
            lines.append(f"- {top or '--'}")
            if status:
                st = status.data.get("state") or {}
                if st.get("feed_status") != "LIVE" or st.get("data_source") != "LIVE_WS":
                    lines.append("- Nota: no marco bots como READY si el feed no es LIVE_WS reciente.")

        lines.append("")
        lines.append("Plan de ataque (manual, sin auto-ejecución):")
        lines.append("- 1) Confirma feed LIVE_WS reciente (ws_age/bar_age bajo umbral).")
        lines.append("- 2) Si está STALE/UNKNOWN_TS: arregla BridgePuppet antes de operar.")
        lines.append("- 3) Si está OK: define setup Wyckoff (fase, nivel clave, invalidación) y riesgo por trade.")

        return "\n".join(lines), snap


assistant_singleton: Optional[AssistantService] = None


def get_assistant_service(repo_root: Path) -> AssistantService:
    global assistant_singleton
    if assistant_singleton is None:
        include = ["README.md", "docs", "backend", "frontend/src", "scripts"]
        extra = (os.getenv("WYCKOFF_RAG_INCLUDE") or "").strip()
        if extra:
            include.extend([p.strip() for p in extra.split(",") if p.strip()])
        assistant_singleton = AssistantService(AssistantConfig(repo_root=repo_root, rag_include_paths=include))
    return assistant_singleton

