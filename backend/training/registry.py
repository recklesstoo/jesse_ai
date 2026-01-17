from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any, Dict, Optional


@dataclass
class TrainingStatus:
    run_id: str
    bot_id: str
    symbol: str
    timeframe: str
    status: str = "RUNNING"  # RUNNING, DONE, ERROR, REFUSED
    started_at_utc: str = ""
    finished_at_utc: Optional[str] = None
    progress: float = 0.0
    message: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    artifact_path: Optional[str] = None


_lock = Lock()
_status_by_run_id: Dict[str, TrainingStatus] = {}


def set_status(status: TrainingStatus) -> None:
    with _lock:
        _status_by_run_id[status.run_id] = status


def get_status(run_id: str) -> Optional[TrainingStatus]:
    with _lock:
        return _status_by_run_id.get(run_id)


def list_statuses(*, bot_id: Optional[str] = None) -> Dict[str, TrainingStatus]:
    with _lock:
        if not bot_id:
            return dict(_status_by_run_id)
        return {k: v for k, v in _status_by_run_id.items() if v.bot_id == bot_id}


def utc_iso(dt: Optional[datetime] = None) -> str:
    from datetime import timezone

    x = dt or datetime.now(timezone.utc)
    return x.isoformat().replace("+00:00", "Z")

