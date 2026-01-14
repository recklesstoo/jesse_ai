from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
SHADOW_DB_PATH = PROJECT_ROOT / "shadow_decisions.db"

# Load project `.env` files early so other modules can rely on os.environ values.
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BASE_DIR / ".env", override=False)


def load_config() -> Dict[str, Any]:
    try:
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open("r", encoding="utf-8") as reader:
                return json.load(reader)
    except Exception as exc:
        print(f"[config] Error loading config.json: {exc}")
    return {}


def save_config(next_config: Dict[str, Any]) -> bool:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as writer:
            json.dump(next_config, writer, ensure_ascii=False, indent=2)
            writer.write("\n")
        tmp.replace(CONFIG_PATH)
        return True
    except Exception as exc:
        print(f"[config] Error saving config.json: {exc}")
        return False


def is_shadow_mode() -> bool:
    return bool(load_config().get("system", {}).get("shadow_mode", False))


EXECUTION_MODE_DISABLED = "DISABLED"
EXECUTION_MODE_MANUAL_ONLY = "MANUAL_ONLY"
EXECUTION_MODE_LIVE_ALLOWED = "LIVE_ALLOWED"


def _normalize_execution_mode(value: Any) -> str:
    raw = (str(value or "")).strip().upper()
    if raw in (EXECUTION_MODE_DISABLED, EXECUTION_MODE_MANUAL_ONLY, EXECUTION_MODE_LIVE_ALLOWED):
        return raw
    return EXECUTION_MODE_MANUAL_ONLY


def get_execution_mode() -> str:
    env = os.getenv("WYCKOFF_EXECUTION_MODE")
    if env:
        return _normalize_execution_mode(env)
    cfg = load_config()
    return _normalize_execution_mode(cfg.get("system", {}).get("execution_mode"))


def set_execution_mode(mode: str) -> tuple[bool, str]:
    normalized = _normalize_execution_mode(mode)
    cfg = load_config()
    cfg.setdefault("system", {})["execution_mode"] = normalized
    ok = save_config(cfg)
    return ok, normalized


def get_execution_token() -> Optional[str]:
    token = os.getenv("WYCKOFF_EXECUTION_TOKEN")
    token = token.strip() if token else None
    return token or None


def init_shadow_db() -> None:
    try:
        with sqlite3.connect(SHADOW_DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shadow_decisions (
                    id TEXT PRIMARY KEY,
                    bot_id TEXT,
                    action TEXT,
                    qty INTEGER,
                    symbol TEXT,
                    ts TEXT,
                    payload TEXT
                )
                """
            )
    except Exception as exc:
        print(f"[config] Error creating shadow table: {exc}")


def log_shadow_decision(bot_id: str, cmd: Dict[str, Any]) -> None:
    try:
        with sqlite3.connect(SHADOW_DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO shadow_decisions (id, bot_id, action, qty, symbol, ts, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    cmd.get("id"),
                    bot_id,
                    cmd.get("action"),
                    cmd.get("qty"),
                    cmd.get("symbol"),
                    cmd.get("queuedAt"),
                    json.dumps(cmd),
                ),
            )
    except Exception as exc:
        print(f"[config] Error logging shadow decision: {exc}")


def get_shadow_decisions(limit: int = 50) -> List[Dict[str, Any]]:
    decisions: List[Dict[str, Any]] = []
    try:
        if SHADOW_DB_PATH.exists():
            with sqlite3.connect(SHADOW_DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM shadow_decisions ORDER BY ts DESC LIMIT ?",
                    (limit,),
                )
                for row in cursor:
                    record = dict(row)
                    payload = record.get("payload")
                    if payload:
                        try:
                            record["payload"] = json.loads(payload)
                        except Exception:
                            pass
                    decisions.append(record)
    except Exception as exc:
        print(f"[config] Error reading shadow decisions: {exc}")
    return decisions
