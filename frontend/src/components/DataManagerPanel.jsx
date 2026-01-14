import React, { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "";

export default function DataManagerPanel() {
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

  const loadDays = async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ symbol, timeframe });
      const res = await fetch(`${API_BASE}/api/v1/data/days?${qs.toString()}`);
      if (!res.ok) {
        setError(`HTTP ${res.status}`);
        return;
      }
      const data = await res.json();
      setDays(data.days || []);
      setCounts(data.counts || null);
      setError(null);
    } catch (e) {
      setError("API DOWN");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDays();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, timeframe]);

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
        {days.length === 0 && !error && <div className="muted">{loading ? "Loading..." : "No days found."}</div>}
        {days.slice(0, 120).map((d) => (
          <div key={d} className="list-item">
            <span className="muted">{d}</span>
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
