import React, { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "";

export default function BotTrainingPanel({ botId = "bot-1" }) {
  const [symbol, setSymbol] = useState("MNQ");
  const [timeframes, setTimeframes] = useState({ "1m": true, "5m": true });
  const [lookbackDays, setLookbackDays] = useState(60);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const pollStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/bots/train/status?botId=${encodeURIComponent(botId)}`);
      if (!res.ok) return;
      const data = await res.json();
      setStatus(data);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    pollStatus();
    const t = setInterval(pollStatus, 3000);
    return () => clearInterval(t);
  }, [botId]);

  const startTraining = async () => {
    setLoading(true);
    setError(null);
    try {
      const tfs = Object.entries(timeframes)
        .filter(([, v]) => Boolean(v))
        .map(([k]) => k);
      const res = await fetch(`${API_BASE}/api/v1/bots/train`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          botId,
          symbol: String(symbol || "MNQ").toUpperCase(),
          timeframes: tfs,
          lookback_days: Number(lookbackDays) || 60,
          config: {}
        })
      });
      const data = await res.json();
      if (!res.ok || data.ok === false) {
        setError(data.detail || data.error || "Training request failed");
      } else {
        await pollStatus();
      }
    } catch (e) {
      setError(String(e?.message || e || "Training request failed"));
    } finally {
      setLoading(false);
    }
  };

  const latestRuns = Array.isArray(status?.runs) ? status.runs.slice(0, 8) : [];

  return (
    <section className="card">
      <div className="card-header">
        <span className="label">BOT TRAINING (DETERMINISTIC, NO EXECUTION)</span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="config-grid" style={{ gridTemplateColumns: "1fr 1fr 1fr auto" }}>
        <label>
          Symbol
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        </label>
        <label>
          Lookback days
          <input type="number" value={lookbackDays} onChange={(e) => setLookbackDays(e.target.value)} />
        </label>
        <label>
          Timeframes
          <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 6 }}>
            <label className="muted" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={Boolean(timeframes["1m"])}
                onChange={(e) => setTimeframes((p) => ({ ...p, "1m": e.target.checked }))}
              />
              1m
            </label>
            <label className="muted" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={Boolean(timeframes["5m"])}
                onChange={(e) => setTimeframes((p) => ({ ...p, "5m": e.target.checked }))}
              />
              5m
            </label>
          </div>
        </label>
        <button className="pill pill-action" onClick={startTraining} disabled={loading}>
          {loading ? "..." : "START TRAINING"}
        </button>
      </div>

      <div className="list" style={{ marginTop: 10 }}>
        {latestRuns.length === 0 && <div className="muted">No runs yet.</div>}
        {latestRuns.map((r) => (
          <div key={r.id} className="list-item">
            <span className="muted">{r.id.slice(0, 10)}</span>
            <span className="muted">{r.symbol}</span>
            <span className="muted">{r.timeframe}</span>
            <span className={`status ${r.status === "DONE" ? "ok" : r.status === "RUNNING" ? "warn" : "warn"}`}>{r.status}</span>
            <span className="muted">{r.metrics?.accuracy !== undefined ? `acc=${Number(r.metrics.accuracy).toFixed(3)}` : "--"}</span>
            <span className="muted" title={r.artifact_path || ""}>
              {r.artifact_path ? "artifact: ok" : "--"}
            </span>
          </div>
        ))}
      </div>
      <div className="muted" style={{ marginTop: 10 }}>
        Guardrail: training refuses if real `data_bars` &lt; 10k (per timeframe).
      </div>
    </section>
  );
}

