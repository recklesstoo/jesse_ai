import { useCallback, useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "";

export function useMarketSnapshot({ symbol, timeframe, lookback = 500, mode = "summary", pollMs = 1000 }) {
  const [metrics, setMetrics] = useState(null);

  const poll = useCallback(async () => {
    const sym = String(symbol || "MNQ").toUpperCase().trim();
    const tf = String(timeframe || "1m").toLowerCase().trim();
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/market/metrics?symbol=${encodeURIComponent(sym)}&timeframe=${encodeURIComponent(tf)}&lookback=${encodeURIComponent(
          lookback
        )}&mode=${encodeURIComponent(mode)}`
      );
      if (!res.ok) return;
      const data = await res.json();
      setMetrics(data);
    } catch {
      // ignore
    }
  }, [symbol, timeframe, lookback, mode]);

  useEffect(() => {
    poll();
    const t = setInterval(poll, pollMs);
    return () => clearInterval(t);
  }, [poll, pollMs]);

  const updateFromWs = useCallback((next) => {
    if (!next || typeof next !== "object") return;
    setMetrics(next);
  }, []);

  const snapshot = useMemo(() => {
    const m = metrics || {};
    const base = m?.metrics?.base || {};
    const ohlc = base?.ohlc || {};
    return {
      raw: m,
      symbol: String(m.symbol || symbol || "MNQ").toUpperCase(),
      timeframe: String(m.timeframe || timeframe || "1m").toLowerCase(),
      source: m.source || "NO_LIVE",
      feed_status: m.feed_status || "NO_LIVE",
      confidence: m.confidence || "low",
      last_bar_ts_utc: base.bar_ts_utc || m.last_bar_ts_utc || null,
      ws_age_sec: m.ws_age_sec ?? null,
      bar_age_sec: m.bar_age_sec ?? null,
      ws_stale_sec: m.ws_stale_sec ?? 10,
      bar_stale_sec: m.bar_stale_sec ?? null,
      notes: Array.isArray(m.notes) ? m.notes : [],
      last_price: base.last_price ?? null,
      ohlc: {
        open: ohlc.open ?? null,
        high: ohlc.high ?? null,
        low: ohlc.low ?? null,
        close: ohlc.close ?? null
      },
      volume: base.volume ?? null
    };
  }, [metrics, symbol, timeframe]);

  return { metrics, snapshot, updateFromWs };
}

