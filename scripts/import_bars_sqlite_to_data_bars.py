from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Tuple


def _parse_ts_utc(ts: str) -> Optional[datetime]:
    s = (ts or "").strip()
    if not s:
        return None
    # bars.sqlite3 uses a 7-digit fractional format like: 2026-01-02T00:01:00.0000000
    if "." in s:
        head, frac = s.split(".", 1)
        frac_digits = "".join(ch for ch in frac if ch.isdigit())
        frac_digits = (frac_digits + "000000")[:6]
        s = f"{head}.{frac_digits}"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iter_rows(src: sqlite3.Connection, *, symbol: str, tf: str) -> Iterable[Tuple[str, str, str, float, float, float, float, int]]:
    cur = src.cursor()
    cur.execute(
        "SELECT ts, symbol, timeframe, o, h, l, c, v FROM bars WHERE symbol=? AND timeframe=? ORDER BY ts ASC",
        (symbol, tf),
    )
    for ts, sym, timeframe, o, h, l, c, v in cur.fetchall():
        dt = _parse_ts_utc(str(ts))
        if dt is None:
            continue
        yield (
            sym,
            "1m",
            dt.isoformat().replace("+00:00", "Z"),
            float(o or 0.0),
            float(h or 0.0),
            float(l or 0.0),
            float(c or 0.0),
            int(float(v or 0.0)),
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Import legacy data/bars.sqlite3 (bars table) into main data_bars.")
    ap.add_argument("--src", default="data/bars.sqlite3", help="Source sqlite path (default: data/bars.sqlite3)")
    ap.add_argument("--dst", default="jesse_ai.db", help="Destination sqlite DB (default: jesse_ai.db)")
    ap.add_argument("--symbol", default="MNQ", help="Symbol to import (default: MNQ)")
    ap.add_argument("--timeframe", default="1 Minute", help="Source timeframe value in bars table (default: 1 Minute)")
    args = ap.parse_args()

    src_path = Path(args.src)
    dst_path = Path(args.dst)
    if not src_path.exists():
        raise SystemExit(f"missing src: {src_path}")
    if not dst_path.exists():
        raise SystemExit(f"missing dst: {dst_path}")

    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dst_path))
    try:
        dst.execute("PRAGMA journal_mode=WAL;")
        dst.execute("PRAGMA synchronous=NORMAL;")

        rows = list(_iter_rows(src, symbol=str(args.symbol).upper(), tf=str(args.timeframe)))
        if not rows:
            print("no rows to import")
            return 0

        # Ensure table exists (created by backend normally).
        dst.execute(
            """
            CREATE TABLE IF NOT EXISTS data_bars (
              id INTEGER PRIMARY KEY,
              symbol TEXT,
              timeframe TEXT,
              ts_utc DATETIME,
              open REAL,
              high REAL,
              low REAL,
              close REAL,
              volume INTEGER,
              source TEXT,
              is_simulated BOOLEAN,
              ingested_at_utc DATETIME
            )
            """
        )

        before = int(dst.execute("SELECT COUNT(*) FROM data_bars").fetchone()[0])
        dst.executemany(
            """
            INSERT OR IGNORE INTO data_bars(symbol, timeframe, ts_utc, open, high, low, close, volume, source, is_simulated, ingested_at_utc)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'BARS_SQLITE', 0, CURRENT_TIMESTAMP)
            """,
            rows,
        )
        dst.commit()
        after = int(dst.execute("SELECT COUNT(*) FROM data_bars").fetchone()[0])
        print(f"imported approx={len(rows)} inserted={after - before} total={after}")
        return 0
    finally:
        try:
            src.close()
        finally:
            dst.close()


if __name__ == "__main__":
    raise SystemExit(main())

