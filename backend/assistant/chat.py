from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from backend.assistant.tools import ToolCall, ToolFn, ToolResult
from backend.assistant.tools import (
    tool_get_commands_log,
    tool_get_data_summary,
    tool_get_monitor_status,
    tool_get_state,
    tool_swarm_rank,
)

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
SESSIONS_DIR = LOG_DIR / "assistant_sessions_openai"
SESSIONS_LOG = LOG_DIR / "assistant_openai_sessions.jsonl"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_json(obj: Any, *, max_len: int = 120_000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        s = json.dumps({"error": "json_encode_failed"}, ensure_ascii=False, indent=2)
    if len(s) > max_len:
        return s[:max_len] + "\n...<truncated>..."
    return s


def _load_session(session_id: str) -> List[Dict[str, str]]:
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        p = (SESSIONS_DIR / f"{session_id}.json").resolve()
        if not p.exists():
            return []
        data = json.loads(p.read_text(encoding="utf-8"))
        turns = data.get("turns") or []
        if isinstance(turns, list):
            return [t for t in turns if isinstance(t, dict) and t.get("role") and t.get("content")]
        return []
    except Exception:
        return []


def _save_session(session_id: str, turns: List[Dict[str, str]]) -> None:
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        p = (SESSIONS_DIR / f"{session_id}.json").resolve()
        p.write_text(_safe_json({"turns": turns[-30:]}), encoding="utf-8")
    except Exception:
        pass


def _log_line(payload: Dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with SESSIONS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _contains_order_intent(text: str) -> bool:
    t = (text or "").lower()
    # Keep this conservative: we should refuse only when the user is clearly asking to execute,
    # not when they are discussing historical events.
    patterns = (
        r"\b(buy|sell|long|short|enter|exit|flatten)\b",
        r"\b(orden|órden|ordenes|órdenes|ejecuta|ejecutar|manda|enviar)\b",
        r"\b(compra|comprar|vende|vender|cierra|cerrar|salir)\b",
        r"\bmarket\b|\blimit\b|\bstop\b",
        r"\bqty\b|\bcontracts?\b",
    )
    if not any(re.search(p, t, flags=re.IGNORECASE) for p in patterns):
        return False
    # Require an action verb to reduce false positives.
    action_verbs = ("ejecuta", "ejecutar", "manda", "enviar", "haz", "dispara", "place", "send")
    return any(v in t for v in action_verbs) or "buy " in t or "sell " in t


def _system_prompt() -> str:
    return (
        "Eres Wyckoff Doctor Trader: español natural, directo, sin humo, mentalidad de trader profesional.\n"
        "Prioridad: diagnóstico operativo + gestión de riesgo.\n"
        "Regla de oro: NO ejecutas órdenes, NO envías comandos, NO cambias execution mode.\n"
        "Si el usuario pide ejecutar/operar: responde que no ejecutas órdenes y entrega pasos manuales concretos.\n"
        "Nunca inventes datos. Si falta info, pide usar herramientas (tools) o dilo explícitamente.\n"
        "Cuando el usuario pregunte “qué pasa”, primero resume el estado operativo basado en el snapshot/tools:\n"
        "nt_mode, mode, feed_status, data_source, ws_age, bar_age, última barra (ts), posición/órdenes si están disponibles.\n"
        "Luego: (1) diagnóstico, (2) causa probable, (3) próximos pasos concretos.\n"
    )


def _tool_registry() -> Dict[str, ToolFn]:
    return {
        "tool_get_state": tool_get_state,
        "tool_get_monitor_status": tool_get_monitor_status,
        "tool_get_commands_log": tool_get_commands_log,
        "tool_get_data_summary": tool_get_data_summary,
        "tool_swarm_rank": tool_swarm_rank,
    }


def _tool_schemas() -> List[Dict[str, Any]]:
    # Chat Completions "tools" schema.
    return [
        {
            "type": "function",
            "function": {
                "name": "tool_get_state",
                "description": "Fetch bot state snapshot (read-only).",
                "parameters": {
                    "type": "object",
                    "properties": {"botId": {"type": "string"}},
                    "required": ["botId"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_get_monitor_status",
                "description": "Fetch monitor/status for a bot (read-only).",
                "parameters": {
                    "type": "object",
                    "properties": {"botId": {"type": "string"}},
                    "required": ["botId"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_get_commands_log",
                "description": "Fetch recent commands/ACK log for a bot (read-only).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "botId": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "required": ["botId"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_get_data_summary",
                "description": "Fetch data/DB summary (read-only). Can include per-day items.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "botId": {"type": "string"},
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string"},
                        "includeDays": {"type": "boolean"},
                        "day": {"type": "string", "description": "YYYY-MM-DD"},
                        "source": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_swarm_rank",
                "description": "Fetch swarm rank (read-only).",
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
                },
            },
        },
    ]


def _build_snapshot(*, bot_id: str) -> Tuple[Dict[str, Any], List[ToolResult], List[Dict[str, Any]]]:
    tools = _tool_registry()
    tool_results: List[ToolResult] = []
    citations: List[Dict[str, Any]] = []

    def run(name: str, params: Dict[str, Any]) -> Any:
        fn = tools.get(name)
        if not fn:
            return None
        res = fn(params)
        tool_results.append(res)
        if res.citations:
            citations.extend(res.citations)
        return res.data

    state = run("tool_get_state", {"botId": bot_id})
    monitor = run("tool_get_monitor_status", {"botId": bot_id})
    commands = run("tool_get_commands_log", {"botId": bot_id, "limit": 20})
    data_summary = run("tool_get_data_summary", {"includeDays": True})
    swarm = run("tool_swarm_rank", {"limit": 10})

    # Keep snapshot compact and stable: only include key fields + recent log lines.
    snapshot: Dict[str, Any] = {"botId": bot_id, "ts_utc": _utc_iso()}
    if isinstance(state, dict):
        snapshot["state"] = {
            "nt_mode": state.get("nt_mode"),
            "mode": state.get("mode"),
            "feed_status": state.get("feed_status"),
            "data_source": state.get("data_source"),
            "ws_open": state.get("ws_open"),
            "ws_connected": state.get("ws_connected"),
            "ws_age_sec": state.get("ws_age_sec"),
            "bar_age_sec": state.get("bar_age_sec"),
            "last_seen_utc": (state.get("state") or {}).get("last_seen_utc") if isinstance(state.get("state"), dict) else state.get("last_seen_utc"),
            "last_bar_ts_utc": state.get("last_bar_ts_utc") or state.get("last_bar_ts"),
            "last_price": state.get("last_price"),
            "instrument": state.get("instrument"),
            "feed_reason": state.get("feed_reason"),
        }
        # Optional: position/orders if present.
        nested = state.get("state") if isinstance(state.get("state"), dict) else {}
        if isinstance(nested, dict):
            for k in ("position", "orders", "open_orders", "market_position"):
                if k in nested:
                    snapshot["state"][k] = nested.get(k)

    if isinstance(monitor, dict):
        snapshot["monitor"] = {
            "ok": monitor.get("ok"),
            "strategyMonitorAgeSec": monitor.get("strategyMonitorAgeSec"),
            "strategyMonitor": monitor.get("strategyMonitor"),
        }

    if isinstance(commands, dict):
        snapshot["recent_commands"] = list(commands.get("log") or [])[-20:]

    if isinstance(data_summary, dict):
        snapshot["data_summary"] = {
            "bars": data_summary.get("bars"),
            "trades": data_summary.get("trades"),
            "breakdown": data_summary.get("breakdown"),
            "available_days": data_summary.get("available_days"),
        }

    if isinstance(swarm, dict):
        snapshot["swarm_top"] = (swarm.get("rank") or [])[:10]

    return snapshot, tool_results, citations


@dataclass(frozen=True)
class OpenAIAssistantConfig:
    repo_root: Path
    model: str


class OpenAIAssistant:
    def __init__(self, config: OpenAIAssistantConfig) -> None:
        self.config = config
        self.tools = _tool_registry()

    def _openai_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")

        url = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1/chat/completions").strip()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        timeout = float(os.getenv("OPENAI_TIMEOUT_SEC") or 20)
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
        try:
            data = r.json()
        except Exception:
            raise RuntimeError(f"OpenAI non-JSON response status={r.status_code} text={r.text[:500]}")
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI HTTP {r.status_code}: {data}")
        return data

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
        session_key = session_id or f"anon:{bot_id}"

        if _contains_order_intent(msg):
            reply = (
                "No ejecuto órdenes ni envío comandos. Te puedo dar el plan exacto (setup, riesgo, invalidación) y tú lo ejecutas desde la UI/Ninja.\n"
                "Si quieres, dime: símbolo, timeframe, si estás LIVE/BACKTEST, y tu nivel de invalidación."
            )
            return {
                "ok": True,
                "reply": reply,
                "tool_calls": [],
                "tool_results": [],
                "citations": [],
                "suggested_actions": [
                    {"label": "Explain now", "message": "Explain what's happening now"},
                    {"label": "Commands log", "message": f"commands log {bot_id}"},
                ],
                "system_state_snapshot": {"botId": bot_id, "note": "order intent refused"},
                "status": {"ok": True, "ts_utc": ts, "refused": True},
            }

        if include_web:
            # Intentionally disabled here; web browsing is handled elsewhere (and must be opt-in).
            include_web = False

        turns = _load_session(session_key)
        turns.append({"role": "user", "content": msg})
        turns = turns[-30:]

        tool_calls_out: List[ToolCall] = []
        tool_results_out: List[ToolResult] = []
        citations: List[Dict[str, Any]] = []

        snapshot: Dict[str, Any] = {"botId": bot_id, "note": "opsMode=false; no live snapshot fetched", "ts_utc": ts}
        if ops_mode:
            snapshot, snap_tool_results, snap_citations = _build_snapshot(bot_id=bot_id)
            tool_results_out.extend(snap_tool_results)
            citations.extend(snap_citations)

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": _system_prompt()},
            {"role": "system", "content": f"System snapshot (JSON):\n{_safe_json(snapshot)}"},
        ]
        messages.extend(turns[-30:])

        tools_schema = _tool_schemas() if ops_mode else []

        def run_tool(name: str, params: Dict[str, Any]) -> ToolResult:
            fn = self.tools.get(name)
            if not fn:
                return ToolResult(name=name, ok=False, data={"error": "unknown_tool"}, citations=[])
            return fn(params)

        # Tool-calling loop (max 3 rounds).
        rounds = 0
        last_model_msg: Optional[Dict[str, Any]] = None
        while True:
            rounds += 1
            if rounds > 3:
                break

            payload = {
                "model": self.config.model,
                "messages": messages,
                "temperature": 0.2,
            }
            if tools_schema:
                payload["tools"] = tools_schema
                payload["tool_choice"] = "auto"

            try:
                data = self._openai_request(payload)
            except Exception as exc:
                reply = f"AI (OpenAI) no disponible: {exc}"
                turns.append({"role": "assistant", "content": reply})
                _save_session(session_key, turns)
                _log_line({"ts_utc": ts, "session_id": session_key, "bot_id": bot_id, "error": str(exc)})
                return {
                    "ok": False,
                    "reply": reply,
                    "tool_calls": [tc.__dict__ for tc in tool_calls_out],
                    "tool_results": [tr.__dict__ for tr in tool_results_out],
                    "citations": citations,
                    "suggested_actions": [],
                    "system_state_snapshot": snapshot,
                    "status": {"ok": False, "ts_utc": ts, "error": "openai_unavailable"},
                }

            choice = (data.get("choices") or [{}])[0]
            model_msg = choice.get("message") or {}
            last_model_msg = model_msg
            messages.append(model_msg)

            tool_calls = model_msg.get("tool_calls") or []
            if not tool_calls:
                break

            for tc in tool_calls:
                fn = (tc.get("function") or {})
                name = fn.get("name")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except Exception:
                    args = {}

                if name == "tool_get_state" and "botId" not in args:
                    args["botId"] = bot_id
                if name == "tool_get_monitor_status" and "botId" not in args:
                    args["botId"] = bot_id
                if name == "tool_get_commands_log" and "botId" not in args:
                    args["botId"] = bot_id

                tool_calls_out.append(ToolCall(name=name or "unknown", params=args))
                res = run_tool(name or "unknown", args)
                tool_results_out.append(res)
                if res.citations:
                    citations.extend(res.citations)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": _safe_json({"ok": res.ok, "data": res.data}),
                    }
                )

        reply_text = (last_model_msg or {}).get("content") or ""
        if not reply_text:
            reply_text = "No response."

        turns.append({"role": "assistant", "content": reply_text})
        _save_session(session_key, turns)
        _log_line(
            {
                "ts_utc": ts,
                "session_id": session_key,
                "bot_id": bot_id,
                "model": self.config.model,
                "opsMode": ops_mode,
                "msg": msg,
                "tool_calls": [tc.__dict__ for tc in tool_calls_out],
            }
        )

        return {
            "ok": True,
            "reply": reply_text,
            "tool_calls": [tc.__dict__ for tc in tool_calls_out],
            "tool_results": [tr.__dict__ for tr in tool_results_out],
            "citations": citations,
            "suggested_actions": [
                {"label": "Explain now", "message": "Explain what's happening now"},
                {"label": "Swarm rank", "message": "swarm rank top 5"},
                {"label": "Data summary", "message": "data summary + available days"},
            ],
            "system_state_snapshot": snapshot,
            "status": {"ok": True, "ts_utc": ts, "rounds": rounds},
        }


openai_assistant_singleton: Optional[OpenAIAssistant] = None


def get_openai_assistant(repo_root: Path) -> OpenAIAssistant:
    global openai_assistant_singleton
    if openai_assistant_singleton is None:
        model = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
        openai_assistant_singleton = OpenAIAssistant(OpenAIAssistantConfig(repo_root=repo_root, model=model))
    return openai_assistant_singleton

