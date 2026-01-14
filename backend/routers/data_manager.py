from __future__ import annotations

import csv
import io
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi import Query
from sqlalchemy import and_, func, text
from sqlalchemy.orm import Session

from backend.database import PROJECT_ROOT, get_db
from backend.models import DataBar, IngestEvent, IngestJob
from backend.ws.server import _parse_ts_utc

router = APIRouter()

LOG_DIR = PROJECT_ROOT / "logs"
DATA_LOG = LOG_DIR / "data_manager.log"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _log(line: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with DATA_LOG.open("a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass


def _job_event(db: Session, job_id: str, level: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    db.add(IngestEvent(job_id=job_id, level=level, message=message, data=data or {}))
    db.commit()


def _parse_csv_bytes(raw: bytes) -> List[Dict[str, Any]]:
    text_s = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text_s))
    rows: List[Dict[str, Any]] = []
    for r in reader:
        rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in (r or {}).items()})
    return rows


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _safe_int(v: Any) -> Optional[int]:
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except Exception:
        return None


@router.get("/api/v1/data/days")
def data_days(
    symbol: str = Query("MNQ"),
    timeframe: str = Query("1m"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    timeframe = (timeframe or "").strip()
    q = (
        db.query(func.date(DataBar.ts_utc).label("day"), func.count(DataBar.id).label("count"))
        .filter(and_(DataBar.symbol == symbol, DataBar.timeframe == timeframe))
        .group_by(func.date(DataBar.ts_utc))
        .order_by(func.date(DataBar.ts_utc).desc())
    )
    rows = q.all()
    days = [str(r.day) for r in rows if r.day]
    total = int(sum(int(r.count or 0) for r in rows))
    by_source = {
        r.source: int(r.cnt or 0)
        for r in db.query(DataBar.source.label("source"), func.count(DataBar.id).label("cnt"))
        .filter(and_(DataBar.symbol == symbol, DataBar.timeframe == timeframe))
        .group_by(DataBar.source)
        .all()
    }
    sim = int(
        db.query(func.count(DataBar.id))
        .filter(and_(DataBar.symbol == symbol, DataBar.timeframe == timeframe, DataBar.is_simulated.is_(True)))
        .scalar()
        or 0
    )
    counts = {
        "total": total,
        "by_source": by_source,
        "simulated": sim,
        "simulated_pct": round((sim / total) * 100, 4) if total else 0.0,
    }
    return {"ok": True, "symbol": symbol, "timeframe": timeframe, "days": days, "counts": counts}


@router.post("/api/v1/data/ingest")
async def data_ingest(
    symbol: str = Form(...),
    timeframe: str = Form(...),
    source: str = Form("CSV_INGEST"),
    is_simulated: bool = Form(False),
    file: UploadFile = File(None),
    path: Optional[str] = Form(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    job_id = f"ing_{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    job = IngestJob(id=job_id, created_at_utc=now, status="RUNNING", params={"symbol": symbol, "timeframe": timeframe, "source": source, "is_simulated": is_simulated})
    db.add(job)
    db.commit()

    _log(f"[{now.isoformat()}] job={job_id} ingest symbol={symbol} tf={timeframe} source={source} sim={is_simulated}")
    _job_event(db, job_id, "INFO", "INGEST_START", {"symbol": symbol, "timeframe": timeframe, "source": source})

    raw: Optional[bytes] = None
    if file is not None:
        raw = await file.read()
    elif path:
        allow = str(os.getenv("WYCKOFF_ALLOW_LOCAL_INGEST_PATH", "")).strip().lower() in ("1", "true", "yes", "on")
        if not allow:
            db.query(IngestJob).filter(IngestJob.id == job_id).update({"status": "ERROR", "finished_at_utc": _utc_now(), "result": {"error": "local_path_ingest_disabled"}})
            db.commit()
            return {"ok": False, "job_id": job_id, "error": "local_path_ingest_disabled"}
        p = Path(path)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        else:
            p = p.resolve()
        data_root = (PROJECT_ROOT / "data").resolve()
        if data_root not in p.parents:
            db.query(IngestJob).filter(IngestJob.id == job_id).update({"status": "ERROR", "finished_at_utc": _utc_now(), "result": {"error": "path_not_allowed"}})
            db.commit()
            return {"ok": False, "job_id": job_id, "error": "path_not_allowed"}
        raw = p.read_bytes()
    else:
        db.query(IngestJob).filter(IngestJob.id == job_id).update({"status": "ERROR", "finished_at_utc": _utc_now(), "result": {"error": "missing_file_or_path"}})
        db.commit()
        return {"ok": False, "job_id": job_id, "error": "missing_file_or_path"}

    rows = _parse_csv_bytes(raw or b"")
    inserted = 0
    skipped = 0
    bad = 0

    for r in rows:
        ts = _parse_ts_utc(r)
        if ts is None:
            bad += 1
            continue
        try:
            bar = DataBar(
                symbol=symbol.strip().upper(),
                timeframe=timeframe.strip(),
                ts_utc=ts,
                open=_safe_float(r.get("open") or r.get("o")),
                high=_safe_float(r.get("high") or r.get("h")),
                low=_safe_float(r.get("low") or r.get("l")),
                close=_safe_float(r.get("close") or r.get("c")),
                volume=_safe_int(r.get("volume") or r.get("v") or 0) or 0,
                source=source.strip().upper(),
                is_simulated=bool(is_simulated),
                ingested_at_utc=_utc_now(),
            )
            db.add(bar)
            db.commit()
            inserted += 1
        except Exception:
            db.rollback()
            # likely duplicate unique key
            skipped += 1

    finished = _utc_now()
    result = {"inserted": inserted, "skipped": skipped, "bad_rows": bad}
    db.query(IngestJob).filter(IngestJob.id == job_id).update({"status": "DONE", "finished_at_utc": finished, "result": result})
    db.commit()
    _job_event(db, job_id, "INFO", "INGEST_DONE", result)
    _log(f"[{finished.isoformat()}] job={job_id} done inserted={inserted} skipped={skipped} bad={bad}")
    return {"ok": True, "job_id": job_id, **result}


@router.post("/api/v1/data/clean")
def data_clean(payload: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    dry_run = bool(payload.get("dryRun", True))
    rules = payload.get("rules") or {}
    symbol = (rules.get("symbol") or "").strip().upper() or None
    timeframe = (rules.get("timeframe") or "").strip() or None
    purge_simulated = bool(rules.get("purge_simulated", False))

    filters = []
    if symbol:
        filters.append(DataBar.symbol == symbol)
    if timeframe:
        filters.append(DataBar.timeframe == timeframe)

    base = db.query(DataBar).filter(and_(*filters)) if filters else db.query(DataBar)

    before = {
        "total": int(base.count()),
        "simulated": int(base.filter(DataBar.is_simulated.is_(True)).count()),
    }

    # Outliers: invalid prices/volume.
    outliers_q = base.filter((DataBar.close <= 0) | (DataBar.open <= 0) | (DataBar.high <= 0) | (DataBar.low <= 0) | (DataBar.volume < 0))
    outliers = int(outliers_q.count())

    # Duplicates: keep smallest id per unique key.
    dup_sql = """
    SELECT COALESCE(SUM(c - 1), 0) AS dup_rows
    FROM (
      SELECT COUNT(*) AS c
      FROM data_bars
      WHERE 1=1
      {where}
      GROUP BY symbol, timeframe, ts_utc
      HAVING c > 1
    ) t
    """
    where_parts: List[str] = []
    params: Dict[str, Any] = {}
    if symbol:
        where_parts.append("AND symbol = :symbol")
        params["symbol"] = symbol
    if timeframe:
        where_parts.append("AND timeframe = :timeframe")
        params["timeframe"] = timeframe
    dupes = int(db.execute(text(dup_sql.format(where="\n".join(where_parts))), params).scalar() or 0)

    simulated = before["simulated"]

    plan = {"outliers": outliers, "duplicates": dupes, "simulated": simulated, "purge_simulated": purge_simulated}
    if dry_run:
        _log(f"[{_utc_now().isoformat()}] clean dry_run={dry_run} plan={plan}")
        return {"ok": True, "dryRun": True, "before": before, "plan": plan, "after": None}

    changed = {"outliers_deleted": 0, "duplicates_deleted": 0, "simulated_deleted": 0}

    changed["outliers_deleted"] = int(outliers_q.delete(synchronize_session=False) or 0)
    db.commit()

    # Delete duplicates by key, keep smallest id.
    del_sql = """
    DELETE FROM data_bars
    WHERE id IN (
      SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                 PARTITION BY symbol, timeframe, ts_utc
                 ORDER BY id ASC
               ) AS rn
        FROM data_bars
        WHERE 1=1
        {where}
      ) x
      WHERE x.rn > 1
    )
    """
    result = db.execute(text(del_sql.format(where="\n".join(where_parts))), params)
    db.commit()
    changed["duplicates_deleted"] = int(getattr(result, "rowcount", 0) or 0)

    if purge_simulated:
        sim_q = base.filter(DataBar.is_simulated.is_(True))
        changed["simulated_deleted"] = int(sim_q.delete(synchronize_session=False) or 0)
        db.commit()

    after_q = db.query(DataBar).filter(and_(*filters)) if filters else db.query(DataBar)
    after = {"total": int(after_q.count()), "simulated": int(after_q.filter(DataBar.is_simulated.is_(True)).count())}

    _log(f"[{_utc_now().isoformat()}] clean applied changed={changed} rules={rules}")
    return {"ok": True, "dryRun": False, "before": before, "plan": plan, "changed": changed, "after": after}

