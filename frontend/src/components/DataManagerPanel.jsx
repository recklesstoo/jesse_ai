import React, { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "";

function isPlainObject(v) {
  return Boolean(v) && typeof v === "object" && !Array.isArray(v);
}

function safeText(v) {
  return typeof v === "string" || typeof v === "number" ? String(v) : "";
}

function normalizeDayRows(response, fallbackSymbol, fallbackTimeframe) {
  const rows = [];
  const dev = Boolean(import.meta?.env?.DEV);

  const toRow = (item) => {
    if (!item) return null;
    if (typeof item === "string") return { day: item, symbol: fallbackSymbol, timeframe: fallbackTimeframe };
    if (!isPlainObject(item)) return null;

    const day = item.day || item.date || item.day_utc;
    if (!day) return { day: "", symbol: fallbackSymbol, timeframe: fallbackTimeframe };

    const barsRaw = item.bars ?? item.bars_count ?? item.count ?? null;
    const tradesRaw = item.trades ?? item.trades_count ?? null;

    const sumMaybe = (v) => {
      if (typeof v === "number") return v;
      if (isPlainObject(v)) return Object.values(v).reduce((acc, x) => acc + (typeof x === "number" ? x : 0), 0);
      return null;
    };

    return {
      day: String(day),
      symbol: safeText(item.symbol) || fallbackSymbol,
      botId: safeText(item.botId) || safeText(item.bot_id),
      timeframe: safeText(item.timeframe) || fallbackTimeframe,
      bars: sumMaybe(barsRaw),
      trades: sumMaybe(tradesRaw),
      first_ts_utc: safeText(item.first_ts_utc) || safeText(item.first_ts) || "",
      last_ts_utc: safeText(item.last_ts_utc) || safeText(item.last_ts) || "",
    };
  };

  if (Array.isArray(response)) {
    for (const item of response) {
      const r = toRow(item);
      if (r) rows.push(r);
    }
    return { ok: true, rows, warning: null };
  }

  if (isPlainObject(response)) {
    const list = Array.isArray(response.days)
      ? response.days
      : Array.isArray(response.items)
        ? response.items
        : null;

    if (list) {
      for (const item of list) {
        const r = toRow(item);
        if (r) rows.push(r);
      }
      return { ok: true, rows, warning: null };
    }
  }

  if (dev) {
    return { ok: false, rows: [], warning: { message: "Unexpected data shape", raw: response } };
  }
  return { ok: false, rows: [], warning: null };
}

export default function DataManagerPanel({ items, disableFetch = false }) {
  const [symbol, setSymbol] = useState("MNQ");
  const [timeframe, setTimeframe] = useState("1m");
  const [days, setDays] = useState([]);
  const [counts, setCounts] = useState(null);
  const [loading, setLoading] = useState(false);
  const [cleanLoading, setCleanLoading] = useState(false);
  const [cleanPreview, setCleanPreview] = useState(null);
  const [cleanApply, setCleanApply] = useState(null);
  const [purgeSim, setPurgeSim] = useState(false);
  const fileRef = useRef(null);
  const [ingestResult, setIngestResult] = useState(null);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);

  const itemsNormalized = useMemo(() => {
    if (!items) return null;
    return normalizeDayRows(items, symbol, timeframe);
  }, [items, symbol, timeframe]);

  const effectiveDays = itemsNormalized ? itemsNormalized.rows : days;
  const effectiveWarning = itemsNormalized ? itemsNormalized.warning : warning;

  const loadDays = async () => {
    if (disableFetch) return;
    setLoading(true);
    try {
      const qs = new URLSearchParams({ symbol, timeframe });
      const res = await fetch(`${API_BASE}/api/v1/data/days?${qs.toString()}`);
      if (!res.ok) {
        setError(`HTTP ${res.status}`);
        return;
      }
      const data = await res.json();
      if (import.meta?.env?.DEV) {
        console.debug("[DataManagerPanel] /api/v1/data/days response", data);
      }
      const normalized = normalizeDayRows(data, symbol, timeframe);
      setWarning(normalized.warning || null);
      setDays(normalized.rows);
      setCounts(data.counts || null);
      setError(null);
    } catch (e) {
      setError("API DOWN");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!items) loadDays();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, timeframe, items, disableFetch]);

  useEffect(() => {
    if (!items) return;
    const normalized = normalizeDayRows(items, symbol, timeframe);
    setWarning(normalized.warning || null);
    setDays(normalized.rows);
  }, [items, symbol, timeframe]);

  const dryRunClean = async () => {
    setCleanLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/data/clean`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dryRun: true, rules: { symbol, timeframe, purge_simulated: purgeSim } })
      });
      const data = await res.json();
      setCleanPreview(data);
      setCleanApply(null);
    } finally {
      setCleanLoading(false);
    }
  };

  const applyClean = async () => {
    setCleanLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/data/clean`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dryRun: false, rules: { symbol, timeframe, purge_simulated: purgeSim } })
      });
      const data = await res.json();
      setCleanApply(data);
      await loadDays();
    } finally {
      setCleanLoading(false);
    }
  };

  const ingestCsv = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setIngestResult(null);
    const fd = new FormData();
    fd.append("symbol", symbol);
    fd.append("timeframe", timeframe);
    fd.append("source", "CSV_INGEST");
    fd.append("is_simulated", "false");
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/api/v1/data/ingest`, { method: "POST", body: fd });
    const data = await res.json();
    setIngestResult(data);
    await loadDays();
  };

  const stats = useMemo(() => {
    const total = counts?.total ?? 0;
    const simPct = counts?.simulated_pct ?? 0;
    return { total, simPct };
  }, [counts]);

  return (
    <section className="card">
      <div className="card-header">
        <span className="label">DATA MANAGER</span>
      </div>

      <div className="config-grid" style={{ marginTop: 10 }}>
        <label>
          Symbol
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        </label>
        <label>
          Timeframe
          <input value={timeframe} onChange={(e) => setTimeframe(e.target.value)} />
        </label>
        <div>
          <div className="label">Rows</div>
          <div className="value">{loading ? "..." : stats.total}</div>
        </div>
        <div>
          <div className="label">Simulated %</div>
          <div className="value">{loading ? "..." : `${stats.simPct}%`}</div>
        </div>
      </div>

      <div className="list" style={{ marginTop: 10, maxHeight: 200, overflow: "auto" }}>
        {error && <div className="muted">ERROR: {error}</div>}
        {effectiveWarning && (
          <div className="muted" style={{ marginBottom: 8 }}>
            <div style={{ fontWeight: 700 }}>Unexpected data shape</div>
            <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(effectiveWarning.raw, null, 2)}</pre>
          </div>
        )}
        {effectiveDays.length === 0 && !error && <div className="muted">{loading ? "Loading..." : "No days found."}</div>}
        {effectiveDays.length > 0 && (
          <div className="list-item" style={{ fontWeight: 700 }}>
            <span className="muted" style={{ width: 110 }}>Day</span>
            <span className="muted" style={{ width: 70 }}>Symbol</span>
            <span className="muted" style={{ width: 90 }}>Bot</span>
            <span className="muted" style={{ width: 70 }}>Bars</span>
            <span className="muted" style={{ width: 70 }}>Trades</span>
            <span className="muted" style={{ width: 170 }}>First</span>
            <span className="muted" style={{ width: 170 }}>Last</span>
          </div>
        )}
        {effectiveDays.slice(0, 120).map((row, idx) => (
          <div key={`${row.day || "day"}-${row.symbol || "sym"}-${row.botId || "bot"}-${idx}`} className="list-item">
            <span className="muted" style={{ width: 110 }}>{safeText(row.day) || "--"}</span>
            <span className="muted" style={{ width: 70 }}>{safeText(row.symbol) || "--"}</span>
            <span className="muted" style={{ width: 90 }}>{safeText(row.botId) || "--"}</span>
            <span className="muted" style={{ width: 70 }}>{typeof row.bars === "number" ? row.bars : "--"}</span>
            <span className="muted" style={{ width: 70 }}>{typeof row.trades === "number" ? row.trades : "--"}</span>
            <span className="muted" style={{ width: 170 }}>{safeText(row.first_ts_utc) || "--"}</span>
            <span className="muted" style={{ width: 170 }}>{safeText(row.last_ts_utc) || "--"}</span>
          </div>
        ))}
      </div>

      <div className="signal-hint" style={{ marginTop: 10 }}>
        <div style={{ fontWeight: 700, marginBottom: 6 }}>Ingest CSV</div>
        <input type="file" ref={fileRef} />
        <button className="pill pill-action" onClick={ingestCsv} style={{ marginTop: 8 }}>
          INGEST
        </button>
        {ingestResult && (
          <div className="muted" style={{ marginTop: 6 }}>
            {JSON.stringify(ingestResult)}
          </div>
        )}
      </div>

      <div className="signal-hint" style={{ marginTop: 10 }}>
        <div style={{ fontWeight: 700, marginBottom: 6 }}>Clean (explicit)</div>
        <label className="muted" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={purgeSim} onChange={(e) => setPurgeSim(e.target.checked)} />
          Purge simulated
        </label>
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button className="pill pill-action" onClick={dryRunClean} disabled={cleanLoading}>
            DRY-RUN
          </button>
          <button className="pill pill-warn" onClick={applyClean} disabled={cleanLoading}>
            APPLY
          </button>
        </div>
        {cleanPreview && (
          <div className="muted" style={{ marginTop: 6 }}>
            preview: {JSON.stringify(cleanPreview.plan || cleanPreview)}
          </div>
        )}
        {cleanApply && (
          <div className="muted" style={{ marginTop: 6 }}>
            applied: {JSON.stringify(cleanApply.changed || cleanApply)}
          </div>
        )}
      </div>
    </section>
  );
}
