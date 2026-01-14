from __future__ import annotations

import csv
import io
import json
import secrets
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import and_, func, text
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend.models import (
    AISignal,
    Bar,
    SystemEvent,
    TradeEvent,
    DATA_SOURCE_ARCHIVED,
    DATA_SOURCE_IMPORT,
    DATA_SOURCE_LIVE_WS,
    DATA_SOURCE_SIMULATED,
)
from backend.state import _get_bot_state, compute_feed_status, state_lock

router = APIRouter()

_cleanup_tokens: Dict[str, Dict[str, Any]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _to_z(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event(db: Session, bot_id: Optional[str], event_type: str, data: Dict[str, Any], data_source: str = DATA_SOURCE_LIVE_WS) -> None:
    row = SystemEvent(bot_id=bot_id, event_type=event_type, data=data, data_source=data_source, ts_utc=_utc_now())
    db.add(row)
    db.commit()


@router.get("/api/v1/bots/registry")
async def bots_registry() -> Dict[str, Any]:
    async with state_lock:
        bot_ids = list(_get_bot_state_map().keys())
        snapshot = {bot_id: dict(_get_bot_state(bot_id)) for bot_id in bot_ids}
        computed = {bot_id: compute_feed_status(bot_id) for bot_id in bot_ids}
    return {"ok": True, "bots": snapshot, "computed": computed}


def _get_bot_state_map() -> Dict[str, Dict[str, Any]]:
    # Import inside to avoid circular.
    from backend.state import bot_state
    return bot_state


@router.get("/api/v1/events")
def events(
    bot_id: Optional[str] = Query(None, alias="botId"),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    query = db.query(SystemEvent)
    if bot_id:
        query = query.filter(SystemEvent.bot_id == bot_id)
    rows = query.order_by(SystemEvent.ts_utc.desc()).limit(limit).all()
    items = [
        {
            "id": r.id,
            "ts_utc": _to_z(r.ts_utc),
            "botId": r.bot_id,
            "event_type": r.event_type,
            "data": r.data or {},
            "data_source": r.data_source,
        }
        for r in rows
    ]
    return {"ok": True, "events": items, "count": len(items)}


def _score_bot(computed: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    readiness = 1.0 if computed.get("ws_connected") and computed.get("feed_status") == "LIVE" else 0.0
    sig = state.get("ai_signal") or {}
    signal = float(sig.get("confidence") or 0.0)
    stability = 0.0
    try:
        ws_age = computed.get("ws_age_sec")
        bar_age = computed.get("bar_age_sec")
        if ws_age is not None and ws_age <= 2:
            stability += 0.5
        if bar_age is not None and computed.get("feed_status") == "LIVE":
            stability += 0.5
    except Exception:
        stability = 0.0
    performance = 0.0
    risk = 1.0
    score = 0.25 * readiness + 0.25 * signal + 0.25 * performance + 0.15 * stability + 0.10 * risk
    return {
        "score": round(score, 4),
        "readiness": readiness,
        "signal": signal,
        "performance": performance,
        "stability": stability,
        "risk": risk,
    }


@router.get("/api/v1/swarm/summary")
async def swarm_summary() -> Dict[str, Any]:
    async with state_lock:
        bot_ids = list(_get_bot_state_map().keys())
        computed = {bot_id: compute_feed_status(bot_id) for bot_id in bot_ids}
        states = {bot_id: dict(_get_bot_state(bot_id)) for bot_id in bot_ids}
    scored = {bot_id: _score_bot(computed[bot_id], states[bot_id]) for bot_id in bot_ids}
    best = max(scored.items(), key=lambda kv: kv[1]["score"], default=(None, None))
    return {
        "ok": True,
        "bots": len(bot_ids),
        "best_bot": best[0],
        "scores": scored,
    }


@router.get("/api/v1/swarm/rank")
async def swarm_rank(limit: int = Query(10, ge=1, le=100)) -> Dict[str, Any]:
    async with state_lock:
        bot_ids = list(_get_bot_state_map().keys())
        computed = {bot_id: compute_feed_status(bot_id) for bot_id in bot_ids}
        states = {bot_id: dict(_get_bot_state(bot_id)) for bot_id in bot_ids}
    ranked = []
    for bot_id in bot_ids:
        score = _score_bot(computed[bot_id], states[bot_id])
        ranked.append(
            {
                "botId": bot_id,
                "score": score["score"],
                "components": score,
                "nt_mode": computed[bot_id].get("nt_mode"),
                "feed_status": computed[bot_id].get("feed_status"),
                "ws_connected": computed[bot_id].get("ws_connected"),
                "instrument": computed[bot_id].get("last_symbol") or states[bot_id].get("instrument"),
            }
        )
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return {"ok": True, "rank": ranked[:limit], "count": len(ranked)}


@router.post("/api/v1/swarm/plan")
async def swarm_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produces a recommendation plan only (NO execution). Intended for UI display.
    """
    limit = int(payload.get("limit") or 5)
    rank = await swarm_rank(limit=limit)
    plan = []
    for entry in rank.get("rank", [])[:limit]:
        plan.append(
            {
                "botId": entry["botId"],
                "recommendation": "OBSERVE",
                "reason": "Orchestrator is read-only. Review signals and stability; execute manually if desired.",
                "score": entry["score"],
            }
        )
    return {"ok": True, "plan": plan}


@router.post("/api/v1/assistant/chat")
async def assistant_chat(payload: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Ops assistant (read-only). Uses registry/timeline/swarm and never sends orders.
    """
    bot_id = payload.get("botId") or "bot-1"
    message = (payload.get("message") or "").strip().lower()
    include_web = bool(payload.get("includeWeb") or False)
    if include_web:
        # Placeholder: web is intentionally off by default and not implemented.
        pass

    computed = compute_feed_status(bot_id)
    state = _get_bot_state(bot_id)

    if "days" in message or "días" in message or "datos" in message:
        summary = data_summary(db=db)
        return {"ok": True, "reply": f"Data summary: {json.dumps(summary, ensure_ascii=False)}"}
    if "rank" in message or "swarm" in message or "enjambre" in message:
        rank = await swarm_rank(limit=10)
        return {"ok": True, "reply": f"Swarm rank: {json.dumps(rank, ensure_ascii=False)[:2000]}"}
    if "status" in message or "estado" in message:
        return {"ok": True, "reply": f"Bot {bot_id}: {json.dumps(computed, ensure_ascii=False)}"}

    return {"ok": True, "reply": "AI Ops Assistant (read-only). Ask about 'status', 'swarm rank', or 'data summary'."}


@router.get("/api/v1/data/summary")
def data_summary(db: Session = Depends(get_db)) -> Dict[str, Any]:
    def _count(model, source: str) -> int:
        return int(db.query(func.count(model.id)).filter(model.data_source == source).scalar() or 0)

    bars = {
        "LIVE_WS": _count(Bar, DATA_SOURCE_LIVE_WS),
        "IMPORT": _count(Bar, DATA_SOURCE_IMPORT),
        "SIMULATED": _count(Bar, DATA_SOURCE_SIMULATED),
        "ARCHIVED": _count(Bar, DATA_SOURCE_ARCHIVED),
    }
    trades = {
        "LIVE_WS": _count(TradeEvent, DATA_SOURCE_LIVE_WS),
        "IMPORT": _count(TradeEvent, DATA_SOURCE_IMPORT),
        "SIMULATED": _count(TradeEvent, DATA_SOURCE_SIMULATED),
        "ARCHIVED": _count(TradeEvent, DATA_SOURCE_ARCHIVED),
    }
    return {"ok": True, "bars": bars, "trades": trades, "ts_utc": _utc_now().isoformat().replace("+00:00", "Z")}


@router.get("/api/v1/data/days")
def data_days(
    symbol: Optional[str] = None,
    botId: Optional[str] = Query(None, alias="botId"),
    source: str = Query("LIVE_WS,IMPORT", description="Comma separated: LIVE_WS,IMPORT,SIMULATED,ARCHIVED,ALL"),
    limit: int = Query(3650, ge=1, le=20000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    sources: Optional[List[str]] = None
    if source and source.upper() != "ALL":
        sources = [s.strip().upper() for s in source.split(",") if s.strip()]

    def _base_filters(model) -> List[Any]:
        filters = []
        if symbol:
            filters.append(model.symbol == symbol)
        if botId:
            filters.append(model.bot_id == botId)
        if sources:
            filters.append(model.data_source.in_(sources))
        return filters

    bars_q = (
        db.query(
            func.date(Bar.ts_utc).label("day"),
            Bar.bot_id.label("bot_id"),
            Bar.symbol.label("symbol"),
            Bar.data_source.label("data_source"),
            func.count(Bar.id).label("bars_count"),
            func.min(Bar.ts_utc).label("first_ts"),
            func.max(Bar.ts_utc).label("last_ts"),
        )
        .filter(and_(*_base_filters(Bar)))
        .group_by(func.date(Bar.ts_utc), Bar.bot_id, Bar.symbol, Bar.data_source)
        .order_by(func.date(Bar.ts_utc).desc())
        .limit(limit)
    )
    bars_rows = bars_q.all()

    trades_q = (
        db.query(
            func.date(TradeEvent.ts_utc).label("day"),
            TradeEvent.bot_id.label("bot_id"),
            TradeEvent.symbol.label("symbol"),
            TradeEvent.data_source.label("data_source"),
            func.count(TradeEvent.id).label("trades_count"),
        )
        .filter(and_(*_base_filters(TradeEvent)))
        .group_by(func.date(TradeEvent.ts_utc), TradeEvent.bot_id, TradeEvent.symbol, TradeEvent.data_source)
    )
    trades_rows = trades_q.all()

    trade_map: Dict[Tuple[str, str, str, str], int] = {}
    for r in trades_rows:
        key = (str(r.day), str(r.bot_id), str(r.symbol), str(r.data_source))
        trade_map[key] = int(r.trades_count or 0)

    items = []
    for r in bars_rows:
        day_str = str(r.day)
        key = (day_str, str(r.bot_id), str(r.symbol), str(r.data_source))
        items.append(
            {
                "day": day_str,
                "symbol": r.symbol,
                "botId": r.bot_id,
                "source": r.data_source,
                "bars_count": int(r.bars_count or 0),
                "trades_count": trade_map.get(key, 0),
                "first_ts_utc": _to_z(r.first_ts),
                "last_ts_utc": _to_z(r.last_ts),
                "gaps_count": None,
                "notes": "",
            }
        )

    return {"ok": True, "days": items, "count": len(items)}


@router.post("/api/v1/data/import")
async def data_import(
    file: UploadFile = File(...),
    symbol: str = Form(...),
    timeframe: str = Form(...),
    botId: str = Form("import"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    raw = await file.read()
    name = (file.filename or "").lower()
    now = _utc_now()

    if name.endswith(".json"):
        data = json.loads(raw.decode("utf-8"))
        df = pd.DataFrame(data)
    else:
        df = pd.read_csv(io.BytesIO(raw))

    # Normalize columns
    rename = {
        "timestamp": "ts",
        "ts_utc": "ts",
        "time": "ts",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "ts" not in df.columns:
        return {"ok": False, "error": "Missing timestamp column (timestamp/ts_utc/time)."}

    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"])

    required = ["open", "high", "low", "close"]
    for col in required:
        if col not in df.columns:
            return {"ok": False, "error": f"Missing column '{col}'."}
    if "volume" not in df.columns:
        df["volume"] = 0

    df = df[(df["close"] > 0) & (df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0)]
    df = df[df["volume"].fillna(0) >= 0]
    df = df.sort_values("ts")

    rows_ok = 0
    rows_bad = 0
    first_ts = None
    last_ts = None

    for _, row in df.iterrows():
        try:
            ts = row["ts"].to_pydatetime().astimezone(timezone.utc)
            bar = Bar(
                bot_id=botId,
                symbol=symbol,
                timeframe=timeframe,
                ts_utc=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row.get("volume") or 0),
                mode="IMPORTED",
                data_source=DATA_SOURCE_IMPORT,
                ingested_at_utc=now,
            )
            db.add(bar)
            rows_ok += 1
            first_ts = first_ts or ts
            last_ts = ts
        except Exception:
            rows_bad += 1

    db.commit()
    _event(
        db,
        botId,
        "DATA_IMPORT",
        {"file": file.filename, "rows_ok": rows_ok, "rows_bad": rows_bad, "symbol": symbol, "timeframe": timeframe},
        data_source=DATA_SOURCE_IMPORT,
    )
    return {
        "ok": True,
        "rows_ok": rows_ok,
        "rows_rejected": rows_bad,
        "first_ts_utc": first_ts.isoformat().replace("+00:00", "Z") if first_ts else None,
        "last_ts_utc": last_ts.isoformat().replace("+00:00", "Z") if last_ts else None,
    }


@router.post("/api/v1/data/cleanup/preview")
def cleanup_preview(payload: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    scope = payload.get("scope") or {}
    rules = payload.get("rules") or {}

    symbol = scope.get("symbol")
    bot_id = scope.get("botId") or scope.get("bot_id")
    date_from = scope.get("date_from")
    date_to = scope.get("date_to")

    def _dt_bounds() -> Tuple[Optional[datetime], Optional[datetime]]:
        start = None
        end = None
        try:
            if date_from:
                start = datetime.fromisoformat(str(date_from)).replace(tzinfo=timezone.utc)
        except Exception:
            start = None
        try:
            if date_to:
                end = datetime.fromisoformat(str(date_to)).replace(tzinfo=timezone.utc)
        except Exception:
            end = None
        return start, end

    start_dt, end_dt = _dt_bounds()

    def _filters(model) -> List[Any]:
        f = []
        if symbol:
            f.append(model.symbol == symbol)
        if bot_id:
            f.append(model.bot_id == bot_id)
        if start_dt is not None:
            f.append(model.ts_utc >= start_dt)
        if end_dt is not None:
            f.append(model.ts_utc <= end_dt)
        return f

    plan: Dict[str, Any] = {"tables": {}, "rules": rules, "scope": scope}

    delete_simulated = bool(rules.get("delete_simulated", True))
    archive_simulated = bool(rules.get("archive_simulated", False))
    delete_duplicates = bool(rules.get("delete_duplicates", True))
    drop_outliers = bool(rules.get("drop_outliers", True))

    # Bars: simulated
    bars_sim_q = db.query(func.count(Bar.id)).filter(and_(*_filters(Bar), Bar.data_source == DATA_SOURCE_SIMULATED))
    bars_sim = int(bars_sim_q.scalar() or 0)
    plan["tables"]["bars"] = {"simulated": bars_sim}

    # Bars: outliers
    bars_out = 0
    if drop_outliers:
        bars_out = int(
            db.query(func.count(Bar.id))
            .filter(and_(*_filters(Bar)))
            .filter((Bar.close <= 0) | (Bar.open <= 0) | (Bar.high <= 0) | (Bar.low <= 0) | (Bar.volume < 0))
            .scalar()
            or 0
        )
    plan["tables"]["bars"]["outliers"] = bars_out

    bars_dupes = 0
    if delete_duplicates:
        # Count groups with duplicates (not rows), plus approximate duplicate rows.
        sql = """
        SELECT COALESCE(SUM(c - 1), 0) AS dup_rows
        FROM (
          SELECT COUNT(*) AS c
          FROM bars
          WHERE 1=1
          {where}
          GROUP BY bot_id, symbol, timeframe, ts_utc, data_source
          HAVING c > 1
        ) t
        """
        where_parts = []
        params: Dict[str, Any] = {}
        if symbol:
            where_parts.append("AND symbol = :symbol")
            params["symbol"] = symbol
        if bot_id:
            where_parts.append("AND bot_id = :bot_id")
            params["bot_id"] = bot_id
        if start_dt is not None:
            where_parts.append("AND ts_utc >= :start_dt")
            params["start_dt"] = start_dt
        if end_dt is not None:
            where_parts.append("AND ts_utc <= :end_dt")
            params["end_dt"] = end_dt
        bars_dupes = int(db.execute(text(sql.format(where="\n".join(where_parts))), params).scalar() or 0)
    plan["tables"]["bars"]["duplicate_rows"] = bars_dupes

    # Trades: simulated
    trades_sim = int(
        db.query(func.count(TradeEvent.id))
        .filter(and_(*_filters(TradeEvent), TradeEvent.data_source == DATA_SOURCE_SIMULATED))
        .scalar()
        or 0
    )
    plan["tables"]["trades"] = {"simulated": trades_sim}

    token = secrets.token_urlsafe(16)
    _cleanup_tokens[token] = {"plan": plan, "created_at": _utc_now().isoformat()}

    return {
        "ok": True,
        "confirm_token": token,
        "plan": plan,
        "note": "Preview only: no changes applied until /cleanup/apply with confirm_token.",
    }


@router.post("/api/v1/data/cleanup/apply")
def cleanup_apply(payload: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    token = payload.get("confirm_token")
    if not token or token not in _cleanup_tokens:
        return {"ok": False, "error": "Invalid or missing confirm_token."}

    plan = _cleanup_tokens.pop(token)["plan"]
    rules = plan.get("rules") or {}
    scope = plan.get("scope") or {}

    symbol = scope.get("symbol")
    bot_id = scope.get("botId") or scope.get("bot_id")

    delete_simulated = bool(rules.get("delete_simulated", True))
    archive_simulated = bool(rules.get("archive_simulated", False))
    delete_duplicates = bool(rules.get("delete_duplicates", True))
    drop_outliers = bool(rules.get("drop_outliers", True))

    def _filters(model) -> List[Any]:
        f = []
        if symbol:
            f.append(model.symbol == symbol)
        if bot_id:
            f.append(model.bot_id == bot_id)
        return f

    changed = {"bars": 0, "trades": 0, "bars_deduped": 0, "bars_outliers": 0}
    if archive_simulated:
        changed["bars"] = int(
            db.query(Bar)
            .filter(and_(*_filters(Bar), Bar.data_source == DATA_SOURCE_SIMULATED))
            .update({Bar.data_source: DATA_SOURCE_ARCHIVED}, synchronize_session=False)
        )
        changed["trades"] = int(
            db.query(TradeEvent)
            .filter(and_(*_filters(TradeEvent), TradeEvent.data_source == DATA_SOURCE_SIMULATED))
            .update({TradeEvent.data_source: DATA_SOURCE_ARCHIVED}, synchronize_session=False)
        )
    elif delete_simulated:
        changed["bars"] = int(
            db.query(Bar).filter(and_(*_filters(Bar), Bar.data_source == DATA_SOURCE_SIMULATED)).delete(synchronize_session=False)
        )
        changed["trades"] = int(
            db.query(TradeEvent).filter(and_(*_filters(TradeEvent), TradeEvent.data_source == DATA_SOURCE_SIMULATED)).delete(synchronize_session=False)
        )

    db.commit()

    if delete_duplicates:
        # Delete duplicate bar rows while keeping the smallest id per key.
        sql = """
        DELETE FROM bars
        WHERE id IN (
          SELECT id FROM (
            SELECT id,
                   ROW_NUMBER() OVER (
                     PARTITION BY bot_id, symbol, timeframe, ts_utc, data_source
                     ORDER BY id ASC
                   ) AS rn
            FROM bars
            WHERE 1=1
            {where}
          ) x
          WHERE x.rn > 1
        )
        """
        where_parts = []
        params: Dict[str, Any] = {}
        if symbol:
            where_parts.append("AND symbol = :symbol")
            params["symbol"] = symbol
        if bot_id:
            where_parts.append("AND bot_id = :bot_id")
            params["bot_id"] = bot_id
        result = db.execute(text(sql.format(where="\n".join(where_parts))), params)
        db.commit()
        changed["bars_deduped"] = int(getattr(result, "rowcount", 0) or 0)

    if drop_outliers:
        # Safety: only clean outliers from SIMULATED/ARCHIVED by default.
        out_q = (
            db.query(Bar)
            .filter(and_(*_filters(Bar)))
            .filter(Bar.data_source.in_([DATA_SOURCE_SIMULATED, DATA_SOURCE_ARCHIVED]))
            .filter((Bar.close <= 0) | (Bar.open <= 0) | (Bar.high <= 0) | (Bar.low <= 0) | (Bar.volume < 0))
        )
        changed["bars_outliers"] = int(out_q.delete(synchronize_session=False) or 0)
        db.commit()

    _event(db, bot_id, "DATA_CLEANUP_APPLIED", {"changed": changed, "rules": rules, "scope": scope}, data_source=DATA_SOURCE_ARCHIVED)
    return {"ok": True, "changed": changed}
