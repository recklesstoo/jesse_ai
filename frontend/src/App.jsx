import React, { useEffect, useMemo, useRef, useState } from "react";
import MLTrainingPanel from "./components/MLTrainingPanel";
import ModelManager from "./components/ModelManager";
import TrainingHistoryChart from "./components/TrainingHistoryChart";
import ConfusionMatrixHeatmap from "./components/ConfusionMatrixHeatmap";
import AIAssistantPanel from "./components/AIAssistantPanel";
import DataManagerPanel from "./components/DataManagerPanel";

const API_BASE = import.meta.env.VITE_API_BASE || "";
const WS_BASE =
  import.meta.env.VITE_WS_BASE ||
  (API_BASE
    ? API_BASE.replace(/^http/i, "ws")
    : (typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:3001").replace(/^http/i, "ws"));
const BOT_ID = import.meta.env.VITE_BOT_ID || "bot-1";
const PRICE_REFRESH_MS = Number(import.meta.env.VITE_PRICE_REFRESH_MS || 200);
const EXEC_TOKEN_STORAGE_KEY = "wyckoff_exec_token";

const formatNum = (value, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return Number(value).toFixed(digits);
};

const formatTime = (iso) => {
  if (!iso) return "--";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--";
  return d.toLocaleTimeString();
};

const nowClock = () => new Date().toLocaleTimeString();

const formatDateTime = (value) => {
  if (!value) return "--";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
};

const extractCommandPayload = (row) => {
  const payload = row?.payload || {};
  const queued = payload.queued || {};
  const ack = payload.ack || {};
  return {
    action: queued.action || ack.action,
    qty: queued.qty || ack.qty,
    tag: queued.tag || ack.tag,
    symbol: queued.symbol || ack.symbol
  };
};

const statusClassFor = (event) => {
  if (!event) return "neutral";
  if (event.startsWith("ACK_")) {
    if (event.includes("REJECT") || event.includes("IGNORE")) return "warn";
    return "ok";
  }
  if (event === "DELIVERED") return "ok";
  if (event.includes("ERROR") || event.includes("IGNORED")) return "warn";
  return "neutral";
};

function WyckoffConfigModal({ open, onClose, config, onSave, saving }) {
  const [form, setForm] = useState(config || {});

  useEffect(() => {
    setForm(config || {});
  }, [config]);

  if (!open) return null;

  const updateField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="modal">
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal-panel">
        <div className="modal-header">
          <div className="label">WYCKOFF CONFIG</div>
          <button onClick={onClose}>CLOSE</button>
        </div>
        <div className="config-grid">
          <label>
            Window
            <input
              type="number"
              min="5"
              value={form.window ?? ""}
              onChange={(e) => updateField("window", Number(e.target.value))}
            />
          </label>
          <label>
            Min Bars
            <input
              type="number"
              min="5"
              value={form.min_bars ?? ""}
              onChange={(e) => updateField("min_bars", Number(e.target.value))}
            />
          </label>
          <label>
            Vol Mult
            <input
              type="number"
              step="0.1"
              min="0.1"
              value={form.vol_mult ?? ""}
              onChange={(e) => updateField("vol_mult", Number(e.target.value))}
            />
          </label>
          <label>
            Break Pct
            <input
              type="number"
              step="0.0001"
              min="0"
              value={form.break_pct ?? ""}
              onChange={(e) => updateField("break_pct", Number(e.target.value))}
            />
          </label>
          <label>
            Break Range Mult
            <input
              type="number"
              step="0.1"
              min="0"
              value={form.break_range_mult ?? ""}
              onChange={(e) => updateField("break_range_mult", Number(e.target.value))}
            />
          </label>
          <label>
            SOS Pct
            <input
              type="number"
              step="0.0001"
              min="0"
              value={form.sos_pct ?? ""}
              onChange={(e) => updateField("sos_pct", Number(e.target.value))}
            />
          </label>
          <label>
            SOW Pct
            <input
              type="number"
              step="0.0001"
              min="0"
              value={form.sow_pct ?? ""}
              onChange={(e) => updateField("sow_pct", Number(e.target.value))}
            />
          </label>
          <label>
            Range Window
            <input
              type="number"
              min="5"
              value={form.range_window ?? ""}
              onChange={(e) => updateField("range_window", Number(e.target.value))}
            />
          </label>
        </div>
        <div className="config-actions">
          <button className="btn ai" onClick={() => onSave(form)} disabled={saving}>
            {saving ? "SAVING..." : "SAVE CONFIG"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AutoTradeModal({ open, onClose, config, onSave, saving }) {
  const [form, setForm] = useState(config || {});
  const [signalsText, setSignalsText] = useState("");

  useEffect(() => {
    setForm(config || {});
    setSignalsText((config?.allowed_signals || []).join(", "));
  }, [config]);

  if (!open) return null;

  const updateField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = () => {
    const allowed = signalsText
      .split(",")
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    onSave({ ...form, allowed_signals: allowed });
  };

  return (
    <div className="modal">
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal-panel">
        <div className="modal-header">
          <div className="label">AUTO ROUTE</div>
          <button onClick={onClose}>CLOSE</button>
        </div>
        <div className="config-grid">
          <label className="toggle-row">
            Enabled
            <input
              type="checkbox"
              checked={Boolean(form.enabled)}
              onChange={(e) => updateField("enabled", e.target.checked)}
            />
          </label>
          <label>
            Min Confidence
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              value={form.min_confidence ?? ""}
              onChange={(e) => updateField("min_confidence", Number(e.target.value))}
            />
          </label>
          <label>
            Max per Hour
            <input
              type="number"
              min="0"
              value={form.max_per_hour ?? ""}
              onChange={(e) => updateField("max_per_hour", Number(e.target.value))}
            />
          </label>
          <label>
            Cooldown (sec)
            <input
              type="number"
              min="0"
              value={form.cooldown_seconds ?? ""}
              onChange={(e) => updateField("cooldown_seconds", Number(e.target.value))}
            />
          </label>
          <label>
            Max Qty
            <input
              type="number"
              min="1"
              value={form.max_qty ?? ""}
              onChange={(e) => updateField("max_qty", Number(e.target.value))}
            />
          </label>
          <label className="span-2">
            Allowed Signals
            <input
              type="text"
              value={signalsText}
              onChange={(e) => setSignalsText(e.target.value)}
              placeholder="SPRING, UPTHRUST, SOS, SOW"
            />
          </label>
        </div>
        <div className="config-actions">
          <button className="btn ai" onClick={handleSave} disabled={saving}>
            {saving ? "SAVING..." : "SAVE AUTO"}
          </button>
        </div>
      </div>
    </div>
  );
}

function CommandLogModal({ open, onClose, entries }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("ALL");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter((row) => {
      const event = String(row.event || "").toUpperCase();
      if (filter === "ACK" && !event.startsWith("ACK")) return false;
      if (filter === "QUEUED" && event !== "QUEUED") return false;
      if (filter === "DELIVERED" && event !== "DELIVERED") return false;
      if (filter === "ERROR" && !event.includes("ERROR")) return false;
      if (!q) return true;
      const hay = JSON.stringify({ id: row.id, event: row.event, payload: row.payload || {} }).toLowerCase();
      return hay.includes(q);
    });
  }, [entries, filter, query]);

  if (!open) return null;

  return (
    <div className="modal">
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal-panel">
        <div className="modal-header">
          <div className="label">COMMAND LOG</div>
          <button onClick={onClose}>CLOSE</button>
        </div>
        <div className="log-controls">
          <input
            className="log-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search id, event, payload..."
          />
          <select className="log-filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="ALL">All</option>
            <option value="ACK">ACK</option>
            <option value="QUEUED">Queued</option>
            <option value="DELIVERED">Delivered</option>
            <option value="ERROR">Error</option>
          </select>
          <div className="log-count">{filtered.length} entries</div>
        </div>
        <div className="modal-body">
          {filtered.length === 0 && <div className="muted">No log entries.</div>}
          {filtered.map((row) => {
            const info = extractCommandPayload(row);
            const summary = [
              info.action,
              info.qty ? `x${info.qty}` : null,
              info.symbol,
              info.tag ? `#${info.tag}` : null
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <div key={`${row.id}-${row.ts}`} className="log-row">
                <div className="log-meta">
                  <span className="log-time">{formatTime(row.ts)}</span>
                  <span className="log-id">{row.id}</span>
                </div>
                <div className="log-event">
                  <span className={`status-chip ${statusClassFor(row.event)}`}>{row.event}</span>
                  {summary && <span className="log-summary">{summary}</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function ToastContainer({ toasts }) {
  if (!toasts || toasts.length === 0) return null;
  return (
    <>
      <style>{`
        .toast-container {
          position: fixed;
          bottom: 20px;
          right: 20px;
          z-index: 9999;
          display: flex;
          flex-direction: column;
          gap: 10px;
          pointer-events: none;
        }
        .toast {
          padding: 12px 20px;
          border-radius: 4px;
          color: #fff;
          font-weight: bold;
          box-shadow: 0 4px 6px rgba(0,0,0,0.3);
          animation: slideIn 0.3s ease-out;
          pointer-events: auto;
          min-width: 250px;
          font-size: 0.9rem;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        .toast-info { background: #3b82f6; border: 1px solid #2563eb; }
        .toast-success { background: #10b981; border: 1px solid #059669; }
        .toast-error { background: #ef4444; border: 1px solid #dc2626; }
        @keyframes slideIn {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
      `}</style>
      <div className="toast-container">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`}>
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </>
  );
}

export default function App() {
  const [connected, setConnected] = useState(false);
  const [feedState, setFeedState] = useState({
    feed_status: "NO_FEED",
    ws_connected: false,
    ws_age_sec: null,
    last_bar_ts_utc: null,
    bar_age_sec: null,
    monitor_status: "NO_MONITOR",
    monitor_age_sec: null,
    nt_mode: "UNKNOWN"
  });
  const [healthOk, setHealthOk] = useState(false);
  const [shadowMode, setShadowMode] = useState(false);
  const [shadowDecisions, setShadowDecisions] = useState([]);
  const [snapshotAge, setSnapshotAge] = useState(null);
  const [positionState, setPositionState] = useState(null);
  const [latencyMs, setLatencyMs] = useState("--");
  const [sessionStart] = useState(Date.now());
  const [clock, setClock] = useState(nowClock());
  const [metrics, setMetrics] = useState(null);

  const [bar, setBar] = useState({
    symbol: "MNQ",
    price: null,
    ohlc: { open: null, high: null, low: null, close: null },
    volume: null,
    timestamp: null
  });
  const [botStatus, setBotStatus] = useState({});
  const [instrumentChoice, setInstrumentChoice] = useState("");

  const [qty, setQty] = useState(1);
  const [orderType, setOrderType] = useState("Market");
  const [limitPrice, setLimitPrice] = useState("");
  const [slTicks, setSlTicks] = useState(0);
  const [tpTicks, setTpTicks] = useState(0);

  const [execs, setExecs] = useState([]);
  const [pendingLimits, setPendingLimits] = useState([]);
  const [logOpen, setLogOpen] = useState(false);
  const [logEntries, setLogEntries] = useState([]);
  const [configOpen, setConfigOpen] = useState(false);
  const [wyckoffConfig, setWyckoffConfig] = useState(null);
  const [configSaving, setConfigSaving] = useState(false);
  const [autoOpen, setAutoOpen] = useState(false);
  const [autoConfig, setAutoConfig] = useState(null);
  const [autoSaving, setAutoSaving] = useState(false);
  const [aiSignal, setAiSignal] = useState(null);
  const [aiHistory, setAiHistory] = useState([]);
  const [calendarEvents, setCalendarEvents] = useState([]);
  const [calendarStatus, setCalendarStatus] = useState(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [errors, setErrors] = useState({
    ws: null,
    health: null,
    log: null,
    command: null,
    metrics: null,
    calendar: null,
    monitor: null
  });
  const [monitorStatus, setMonitorStatus] = useState(null);
  const [executionStatus, setExecutionStatus] = useState(null);
  const [execModeOpen, setExecModeOpen] = useState(false);
  const [execModeDraft, setExecModeDraft] = useState("MANUAL_ONLY");
  const [execToken, setExecToken] = useState(() => {
    try {
      return localStorage.getItem(EXEC_TOKEN_STORAGE_KEY) || "";
    } catch {
      return "";
    }
  });

  const [opsAssistantEnabled, setOpsAssistantEnabled] = useState(false);
  const [opsAssistantIncludeWeb, setOpsAssistantIncludeWeb] = useState(false);

  const [botsRegistry, setBotsRegistry] = useState(null);
  const [eventTimeline, setEventTimeline] = useState([]);
  const [swarmRank, setSwarmRank] = useState([]);
  const [swarmPlan, setSwarmPlan] = useState([]);

  const [dataSummary, setDataSummary] = useState(null);
  const [dataDays, setDataDays] = useState([]);
  const [selectedDay, setSelectedDay] = useState("");
  const [selectedDaySummary, setSelectedDaySummary] = useState(null);
  const [dataFilters, setDataFilters] = useState({
    symbol: "MNQ",
    botId: BOT_ID,
    source: "LIVE_WS,IMPORT"
  });
  const [cleanupRules, setCleanupRules] = useState({
    delete_simulated: true,
    archive_simulated: false,
    delete_cached: false,
    archive_cached: false,
    delete_duplicates: true,
    drop_outliers: true
  });
  const [cleanupPreview, setCleanupPreview] = useState(null);
  const [cleanupConfirm, setCleanupConfirm] = useState("");
  const [importMeta, setImportMeta] = useState({ symbol: "MNQ", timeframe: "1min", botId: "import" });
  const [importResult, setImportResult] = useState(null);
  const importFileRef = useRef(null);

  const [toasts, setToasts] = useState([]);
  const addToast = (msg, type = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, msg, type }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  };

  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState([
    { role: "assistant", content: "Wyckoff AI listo. Preguntame por estado, ejecuciones o riesgo." }
  ]);

  const wsRef = useRef(null);
  const wsRetryRef = useRef(0);
  const wsTimerRef = useRef(null);
  const barBufferRef = useRef(null);
  const barFlushRef = useRef(null);
  const logTimerRef = useRef(null);
  const healthTimerRef = useRef(null);
  const metricsTimerRef = useRef(null);
  const signalTimerRef = useRef(null);
  const signalHistoryTimerRef = useRef(null);
  const clockTimerRef = useRef(null);
  const calendarTimerRef = useRef(null);

  const lastEventById = useMemo(() => {
    const map = {};
    for (const row of logEntries) {
      map[row.id] = row.event;
    }
    return map;
  }, [logEntries]);
  const activeError = useMemo(
    () => errors.ws || errors.health || errors.command || errors.log || errors.metrics,
    [errors]
  );
  const errorItems = useMemo(
    () => [
      {
        key: "ws",
        label: "UI WS (/ws/live)",
        value: errors.ws || (connected ? "OK" : "DISCONNECTED")
      },
      {
        key: "health",
        label: "Health",
        value: errors.health || (healthOk ? "OK" : "UNAVAILABLE")
      },
      {
        key: "command",
        label: "Commands",
        value: errors.command || "OK"
      },
      {
        key: "log",
        label: "Command Log",
        value: errors.log || "OK"
      },
      {
        key: "metrics",
        label: "Metrics",
        value: errors.metrics || "OK"
      },
      {
        key: "calendar",
        label: "Calendar",
        value: errors.calendar || "OK"
      },
      {
        key: "monitor",
        label: "Monitor",
        value: errors.monitor || "OK"
      }
    ],
    [errors, connected, healthOk]
  );

  const setError = (key, message) => {
    setErrors((prev) => ({ ...prev, [key]: message }));
  };

  useEffect(() => {
    if (botStatus.instrument) {
      setInstrumentChoice(botStatus.instrument);
    } else if (bar.symbol) {
      setInstrumentChoice(bar.symbol);
    }
  }, [botStatus.instrument, bar.symbol]);

  useEffect(() => {
    const updateClock = () => setClock(nowClock());
    clockTimerRef.current = setInterval(updateClock, 1000);
    return () => clearInterval(clockTimerRef.current);
  }, []);

  useEffect(() => {
    const flushBar = () => {
      if (barBufferRef.current) {
        const next = barBufferRef.current;
        barBufferRef.current = null;
        setBar((prev) => ({
          ...prev,
          symbol: next.symbol || prev.symbol,
          price: next.price,
          ohlc: next.ohlc || prev.ohlc,
          volume: next.volume,
          timestamp: next.timestamp
        }));
      }
    };
    barFlushRef.current = setInterval(flushBar, PRICE_REFRESH_MS);
    return () => clearInterval(barFlushRef.current);
  }, []);

  useEffect(() => {
    const pollState = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/state?botId=${BOT_ID}`);
        if (!res.ok) return;
        const data = await res.json();
        setFeedState(data);

        setBar((prev) => {
          const nextTs = data.last_bar_ts_utc;
          if (!nextTs) {
            if (data.feed_status === "NO_FEED" && !prev.timestamp) {
              return {
                ...prev,
                price: null,
                ohlc: { open: null, high: null, low: null, close: null },
                volume: null,
                timestamp: null
              };
            }
            return prev;
          }

          const prevTime = prev.timestamp ? new Date(prev.timestamp).getTime() : 0;
          const nextTime = new Date(nextTs).getTime();
          if (!Number.isFinite(nextTime) || nextTime <= prevTime) return prev;

          return {
            ...prev,
            symbol: data.last_symbol || prev.symbol,
            price: data.last_price ?? prev.price,
            ohlc: data.last_ohlc || prev.ohlc,
            volume: data.last_volume ?? prev.volume,
            timestamp: nextTs
          };
        });
      } catch (err) {
        // Ignore state polling failures.
      }
    };

    pollState();
    const timer = setInterval(pollState, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(`${WS_BASE}/ws/live`);
      wsRef.current = ws;

      ws.addEventListener("open", () => {
        setConnected(true);
        wsRetryRef.current = 0;
        setError("ws", null);
      });
      ws.addEventListener("close", () => {
        setConnected(false);
        if (wsTimerRef.current) clearTimeout(wsTimerRef.current);
        wsRetryRef.current += 1;
        const attempt = Math.min(wsRetryRef.current, 6);
        const delay = Math.min(30000, 1000 * 2 ** attempt);
        setError("ws", `WS closed. retrying in ${Math.round(delay / 1000)}s`);
        wsTimerRef.current = setTimeout(connect, delay);
      });
      ws.addEventListener("error", () => {
        setConnected(false);
        if (wsTimerRef.current) clearTimeout(wsTimerRef.current);
        wsRetryRef.current += 1;
        const attempt = Math.min(wsRetryRef.current, 6);
        const delay = Math.min(30000, 1000 * 2 ** attempt);
        setError("ws", `WS error. retrying in ${Math.round(delay / 1000)}s`);
        wsTimerRef.current = setTimeout(connect, delay);
      });

      ws.addEventListener("message", (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "bar_update") {
            const msgBotId = msg?.data?.botId || msg?.data?.bot_id;
            if (msgBotId && msgBotId !== BOT_ID) return;
            barBufferRef.current = {
              symbol: msg.data.symbol,
              price: msg.data.price,
              ohlc: msg.data.ohlc,
              volume: msg.data.volume,
              timestamp: msg.data.timestamp
            };
          }
          if (msg.type === "bot_status") {
            const statusBotId = msg?.data?.status?.botId || msg?.data?.status?.bot_id;
            if (statusBotId && statusBotId !== BOT_ID) return;
            setBotStatus(msg.data.status || {});
          }
          if (msg.type === "connection_status") {
            setConnected(Boolean(msg.data.connected));
          }
        } catch (err) {
          // Ignore malformed WS data.
        }
      });
    };

    connect();
    return () => {
      if (wsTimerRef.current) clearTimeout(wsTimerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  useEffect(() => {
    const poll = async () => {
      const start = performance.now();
      try {
        const res = await fetch(`${API_BASE}/api/v1/health`);
        const ok = res.ok;
        setHealthOk(ok);

        if (ok) {
          const data = await res.json();
          setShadowMode(Boolean(data.shadow_mode));

          // Update snapshot age for current bot
          const botSnapshotAge = data.lastSnapshotAgeSec?.[BOT_ID];
          setSnapshotAge(botSnapshotAge);

          // Update position state for current bot
          const botPosition = data.positionState?.[BOT_ID];
          setPositionState(botPosition);
        }

        const ms = Math.round(performance.now() - start);
        setLatencyMs(ok ? ms : "--");
        setError("health", ok ? null : "Health check failed");
      } catch (err) {
        setHealthOk(false);
        setLatencyMs("--");
        setError("health", "Health check failed");
      }
    };

    poll();
    healthTimerRef.current = setInterval(poll, 5000);
    return () => clearInterval(healthTimerRef.current);
  }, []);

  useEffect(() => {
    const pollMetrics = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/metrics?botId=${BOT_ID}`);
        if (!res.ok) {
          setError("metrics", "Metrics unavailable");
          return;
        }
        const data = await res.json();
        setMetrics(data);
        setError("metrics", null);
      } catch (err) {
        setError("metrics", "Metrics unavailable");
      }
    };

    pollMetrics();
    metricsTimerRef.current = setInterval(pollMetrics, 3000);
    return () => clearInterval(metricsTimerRef.current);
  }, []);

  useEffect(() => {
    const pollBots = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/bots`);
        if (!res.ok) return;
        const data = await res.json();
        setBotsRegistry(data);
      } catch (err) {
        // ignore
      }
    };
    pollBots();
    const timer = setInterval(pollBots, 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const pollEvents = async () => {
      try {
        const qs = new URLSearchParams({ limit: "200" });
        const res = await fetch(`${API_BASE}/api/v1/events?${qs.toString()}`);
        if (!res.ok) return;
        const data = await res.json();
        const items = (data.events || []).filter((ev) => !BOT_ID || ev.botId === BOT_ID);
        setEventTimeline(items);
      } catch (err) {
        // ignore
      }
    };
    pollEvents();
    const timer = setInterval(pollEvents, 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const pollSwarm = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/swarm/rank?limit=10`);
        if (!res.ok) return;
        const data = await res.json();
        setSwarmRank(data.rank || []);
      } catch (err) {
        // ignore
      }
    };
    pollSwarm();
    const timer = setInterval(pollSwarm, 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const pollDataSummary = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/data/summary`);
        if (!res.ok) return;
        const data = await res.json();
        setDataSummary(data);
      } catch (err) {
        // ignore
      }
    };
    pollDataSummary();
    const timer = setInterval(pollDataSummary, 10000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const loadDays = async () => {
      try {
        const qs = new URLSearchParams({
          symbol: dataFilters.symbol || "",
          botId: dataFilters.botId || "",
          source: dataFilters.source || "LIVE_WS,IMPORT"
        });
        const res = await fetch(`${API_BASE}/api/v1/data/days_legacy?${qs.toString()}`);
        if (!res.ok) return;
        const data = await res.json();
        setDataDays(data.days || []);
      } catch (err) {
        // ignore
      }
    };
    loadDays();
  }, [dataFilters.symbol, dataFilters.botId, dataFilters.source]);

  useEffect(() => {
    if (!selectedDay && dataDays.length > 0) setSelectedDay(dataDays[0].day);
  }, [dataDays, selectedDay]);

  useEffect(() => {
    const loadSelectedDay = async () => {
      if (!selectedDay) return;
      try {
        const qs = new URLSearchParams({
          day: selectedDay,
          symbol: dataFilters.symbol || "",
          botId: dataFilters.botId || "",
          source: dataFilters.source || "LIVE_WS,IMPORT"
        });
        const res = await fetch(`${API_BASE}/api/v1/data/summary?${qs.toString()}`);
        if (!res.ok) return;
        const data = await res.json();
        setSelectedDaySummary(data);
      } catch (err) {
        // ignore
      }
    };
    loadSelectedDay();
  }, [selectedDay, dataFilters.symbol, dataFilters.botId, dataFilters.source]);

  useEffect(() => {
    const pollMonitor = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/monitor/status?botId=${BOT_ID}`);
        if (!res.ok) {
          setError("monitor", "Monitor unavailable");
          return;
        }
        const data = await res.json();
        setMonitorStatus(data);
        setError("monitor", null);
      } catch (err) {
        setError("monitor", "Monitor unavailable");
      }
    };

    pollMonitor();
    const timer = setInterval(pollMonitor, 2000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const pollExecution = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/execution/status?botId=${BOT_ID}`);
        if (!res.ok) return;
        const data = await res.json();
        setExecutionStatus(data);
        setExecModeDraft((data.execution_mode || "MANUAL_ONLY").toUpperCase());
      } catch (err) {
        // ignore
      }
    };

    pollExecution();
    const timer = setInterval(pollExecution, 3000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const pollLogs = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/commands/${BOT_ID}/log?limit=200`);
        if (!res.ok) {
          setError("log", "Command log unavailable");
          return;
        }
        const data = await res.json();
        setLogEntries(data.log || []);
        setError("log", null);
      } catch (err) {
        setError("log", "Command log unavailable");
      }
    };

    pollLogs();
    logTimerRef.current = setInterval(pollLogs, 3000);
    return () => clearInterval(logTimerRef.current);
  }, []);

  // Poll shadow decisions if shadow mode is enabled
  useEffect(() => {
    if (!shadowMode) {
      setShadowDecisions([]);
      return;
    }

    const pollShadow = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/shadow/recent?limit=50`);
        if (!res.ok) return;
        const data = await res.json();
        setShadowDecisions(data.decisions || []);
      } catch (err) {
        // Ignore shadow fetch errors
      }
    };

    pollShadow();
    const timer = setInterval(pollShadow, 3000);
    return () => clearInterval(timer);
  }, [shadowMode]);

  useEffect(() => {
    const pollSignal = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/ai-signals?botId=${BOT_ID}`);
        if (!res.ok) return;
        const data = await res.json();
        setAiSignal(data);
      } catch (err) {
        // Ignore signal fetch issues.
      }
    };

    pollSignal();
    signalTimerRef.current = setInterval(pollSignal, 2000);
    return () => clearInterval(signalTimerRef.current);
  }, []);

  useEffect(() => {
    const pollHistory = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/ai-signals/${BOT_ID}/history?limit=10`);
        if (!res.ok) return;
        const data = await res.json();
        setAiHistory(data.history || []);
      } catch (err) {
        // Ignore history fetch issues.
      }
    };

    pollHistory();
    signalHistoryTimerRef.current = setInterval(pollHistory, 5000);
    return () => clearInterval(signalHistoryTimerRef.current);
  }, []);

  useEffect(() => {
    const pollCalendar = async () => {
      setCalendarLoading(true);
      try {
        const [statusRes, upcomingRes] = await Promise.all([
          fetch(`${API_BASE}/api/v1/calendar/ff/status`),
          fetch(`${API_BASE}/api/v1/calendar/ff/upcoming?days=7&limit=200`)
        ]);
        if (statusRes.ok) {
          const statusData = await statusRes.json();
          setCalendarStatus(statusData);
        }
        if (!upcomingRes.ok) {
          setError("calendar", "Calendar unavailable");
          return;
        }
        const data = await upcomingRes.json();
        setCalendarEvents(data.events || []);
        setError("calendar", null);
      } catch (err) {
        setError("calendar", "Calendar unavailable");
      } finally {
        setCalendarLoading(false);
      }
    };

    pollCalendar();
    calendarTimerRef.current = setInterval(pollCalendar, 60000);
    return () => clearInterval(calendarTimerRef.current);
  }, []);

  const refreshCalendar = async () => {
    setCalendarLoading(true);
    try {
      await fetch(`${API_BASE}/api/v1/calendar/ff/refresh?days=7`, { method: "POST" });
    } catch (err) {
      // Ignore refresh errors, upcoming fetch will handle status.
    } finally {
      setCalendarLoading(false);
    }
  };

  const loadWyckoffConfig = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/wyckoff/config?botId=${BOT_ID}`);
      if (!res.ok) return;
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setWyckoffConfig(data.config || null);
    } catch (err) {
      // Ignore config fetch issues.
    }
  };

  const loadAutoConfig = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/ai/auto-config?botId=${BOT_ID}`);
      if (!res.ok) return;
      const data = await res.json();
      setAutoConfig(data.config || null);
    } catch (err) {
      // Ignore auto config fetch issues.
    }
  };

  useEffect(() => {
    loadWyckoffConfig();
  }, []);

  useEffect(() => {
    loadAutoConfig();
  }, []);

  useEffect(() => {
    if (!bar.price || pendingLimits.length === 0) return;
    const price = Number(bar.price);
    const ready = [];
    const remaining = [];

    for (const lim of pendingLimits) {
      if (lim.side === "BUY" && price <= lim.price) {
        ready.push(lim);
      } else if (lim.side === "SELL" && price >= lim.price) {
        ready.push(lim);
      } else {
        remaining.push(lim);
      }
    }

    if (ready.length > 0) {
      setPendingLimits(remaining);
      for (const order of ready) {
        sendCommand(order.side, order.qty, order.slTicks, order.tpTicks, order.tag, order.symbol);
      }
    }
  }, [bar.price, pendingLimits]);

  const sendCommand = async (action, size, sl, tp, tag, symbol) => {
    const payload = {
      action,
      qty: Number(size) || 0,
      slTicks: Number(sl) || 0,
      tpTicks: Number(tp) || 0,
      tag: tag || "manual",
      symbol: symbol || bar.symbol || "MNQ"
    };

    try {
      const res = await fetch(`${API_BASE}/api/v1/commands/${BOT_ID}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data?.ok === false && data?.ack?.status) {
        setError("command", `ACK_${data.ack.status}: ${data.ack.reject_reason || data.ack.reason || ""}`.trim());
        addToast(`Command ${data.ack.status}: ${data.ack.reject_reason || data.ack.reason || ""}`.trim(), "error");
      } else {
        setError("command", null);
      }
      const queuedId = data.queued?.id || `cmd_${Date.now()}`;
      setExecs((prev) => [
        {
          id: queuedId,
          action,
          qty: payload.qty,
          ts: data.ts || new Date().toISOString(),
          ack: data.ack || null
        },
        ...prev.slice(0, 12)
      ]);
    } catch (err) {
      setError("command", "Command send failed");
      setExecs((prev) => [
        {
          id: `err_${Date.now()}`,
          action,
          qty: payload.qty,
          ts: new Date().toISOString(),
          error: true
        },
        ...prev.slice(0, 12)
      ]);
    }
  };

  const handleSubmit = (action) => {
    if (orderType === "Limit") {
      if (action === "FLATTEN" || action === "CLOSE") {
        sendCommand(action, qty, slTicks, tpTicks, "manual", bar.symbol);
        return;
      }
      const price = Number(limitPrice);
      if (!price) return;
      setPendingLimits((prev) => [
        {
          id: `lim_${Date.now()}`,
          side: action,
          price,
          qty: Number(qty) || 1,
          slTicks: Number(slTicks) || 0,
          tpTicks: Number(tpTicks) || 0,
          tag: "limit",
          symbol: bar.symbol || "MNQ"
        },
        ...prev
      ]);
      return;
    }
    sendCommand(action, qty, slTicks, tpTicks, "manual", bar.symbol);
  };

  const sessionUptime = useMemo(() => {
    const seconds = Math.floor((Date.now() - sessionStart) / 1000);
    const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
    const ss = String(seconds % 60).padStart(2, "0");
    return `${mm}:${ss}`;
  }, [clock, sessionStart]);

  const feedAgeSec = useMemo(() => {
    const stateAge = feedState?.bar_age_sec;
    if (stateAge !== null && stateAge !== undefined) return Math.max(0, Math.round(Number(stateAge)));
    return null;
  }, [feedState?.bar_age_sec]);

  const dataSource = (feedState?.data_source || "NONE").toUpperCase();
  const feedOk = dataSource === "LIVE_WS" && feedState?.feed_status === "LIVE";
  const monitorOk = feedState?.monitor_status === "OK";
  const monitorAgeSec = useMemo(() => {
    const value = feedState?.monitor_age_sec;
    if (value === null || value === undefined) return null;
    return Math.max(0, Math.round(Number(value)));
  }, [feedState?.monitor_age_sec]);
  const bridgeConnected = Boolean(feedState?.ws_connected);
  const ntMode = (feedState?.nt_mode || "UNKNOWN").toUpperCase();
  const backendMode = (feedState?.mode || "UNKNOWN").toUpperCase();
  const platformMode = useMemo(() => {
    if (backendMode && backendMode !== "UNKNOWN") return backendMode;
    if (feedOk) return "LIVE";
    if (ntMode === "BACKTEST") return "BACKTEST";
    return "UNKNOWN";
  }, [backendMode, feedOk, ntMode]);
  const wsStaleSec = useMemo(() => {
    const value = feedState?.ws_stale_sec;
    if (value === null || value === undefined) return 2;
    return Math.max(1, Math.round(Number(value)));
  }, [feedState?.ws_stale_sec]);
  const wsAgeSec = useMemo(() => {
    const value = feedState?.ws_age_sec;
    if (value === null || value === undefined) return null;
    return Math.max(0, Math.round(Number(value)));
  }, [feedState?.ws_age_sec]);

  const execMode = (executionStatus?.execution_mode || "MANUAL_ONLY").toUpperCase();
  const execModeClass = execMode === "DISABLED" ? "pill-warn" : execMode === "LIVE_ALLOWED" ? "pill-ok" : "pill-warn";

  const lastExec = execs[0];
  const lastExecEvent = lastExec ? lastEventById[lastExec.id] || (lastExec.error ? "ERROR" : "SENT") : null;

  const chatContext = useMemo(() => {
    const parts = [];
    if (botStatus.mode) parts.push(`Mode ${botStatus.mode}`);
    if (bar.symbol) parts.push(bar.symbol);
    if (bar.price !== null && bar.price !== undefined) parts.push(`Last ${formatNum(bar.price, 2)}`);
    if (bar.timestamp) parts.push(`@ ${formatTime(bar.timestamp)}`);
    return parts.join(" | ");
  }, [bar.price, bar.symbol, bar.timestamp, botStatus.mode]);

  const sendChat = async () => {
    const messageText = chatInput.trim();
    if (!messageText) return;
    const next = [...chatMessages, { role: "user", content: messageText }];
    setChatMessages(next);
    setChatInput("");

    try {
      if (opsAssistantEnabled) {
        const res = await fetch(`${API_BASE}/api/v1/assistant/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ botId: BOT_ID, message: messageText, includeWeb: opsAssistantIncludeWeb })
        });
        const data = await res.json();
        setChatMessages((prev) => [...prev, { role: "assistant", content: data.reply || "Sin respuesta." }]);
      } else {
        const res = await fetch(`${API_BASE}/api/v1/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ botId: BOT_ID, messages: next.slice(-10) })
        });
        const data = await res.json();
        setChatMessages((prev) => [...prev, { role: "assistant", content: data.reply || "Sin respuesta." }]);
      }
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "No se pudo contactar al chat." }
      ]);
    }
  };

  const generateSwarmPlan = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/swarm/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 5 })
      });
      const data = await res.json();
      setSwarmPlan(data.plan || []);
      addToast("Swarm plan updated", "success");
    } catch (err) {
      addToast("Swarm plan failed", "error");
    }
  };

  const updateExecutionMode = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/execution/enable`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(execToken ? { "x-execution-token": execToken } : {})
        },
        body: JSON.stringify({ mode: execModeDraft })
      });
      const data = await res.json();
      if (data.ok) {
        try {
          localStorage.setItem(EXEC_TOKEN_STORAGE_KEY, execToken || "");
        } catch {
          // ignore
        }
        addToast(`Execution mode: ${data.execution_mode}`, "success");
        setExecModeOpen(false);
      } else {
        addToast(`Execution mode update failed: ${data.reason || data.error || "unknown"}`, "error");
      }
    } catch (err) {
      addToast("Execution mode update failed", "error");
    }
  };

  const previewCleanup = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/data/cleanup/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: { symbol: dataFilters.symbol || null, botId: dataFilters.botId || null },
          rules: cleanupRules
        })
      });
      const data = await res.json();
      setCleanupPreview(data);
      setCleanupConfirm("");
      addToast("Cleanup preview ready", "success");
    } catch (err) {
      addToast("Cleanup preview failed", "error");
    }
  };

  const applyCleanup = async () => {
    const token = cleanupPreview?.confirm_token;
    if (!token) return;
    if (cleanupConfirm.trim() !== token) {
      addToast("Confirmation token mismatch", "error");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/v1/data/cleanup/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_token: token })
      });
      const data = await res.json();
      if (data.ok) {
        addToast("Cleanup applied", "success");
        setCleanupPreview(null);
        setCleanupConfirm("");
      } else {
        addToast(`Cleanup failed: ${data.error || "unknown"}`, "error");
      }
    } catch (err) {
      addToast("Cleanup apply failed", "error");
    }
  };

  const importData = async () => {
    const file = importFileRef.current?.files?.[0];
    if (!file) return;
    setImportResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("symbol", importMeta.symbol);
      fd.append("timeframe", importMeta.timeframe);
      fd.append("botId", importMeta.botId);
      const res = await fetch(`${API_BASE}/api/v1/data/import`, { method: "POST", body: fd });
      const data = await res.json();
      setImportResult(data);
      addToast(data.ok ? "Import completed" : "Import failed", data.ok ? "success" : "error");
    } catch (err) {
      addToast("Import failed", "error");
    }
  };

  const updateInstrument = async () => {
    const next = (instrumentChoice || "").trim();
    if (!next) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/bots/instrument`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ botId: BOT_ID, instrument: next })
      });
      if (res.ok) {
        setBotStatus((prev) => ({ ...prev, instrument: next }));
        await loadWyckoffConfig();
        await loadAutoConfig();
      }
    } catch (err) {
      setError("health", "Instrument update failed");
    }
  };

  const saveWyckoffConfig = async (next) => {
    setConfigSaving(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/wyckoff/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ botId: BOT_ID, ...next })
      });
      if (res.ok) {
        const data = await res.json();
        setWyckoffConfig(data.config || next);
      }
    } finally {
      setConfigSaving(false);
      setConfigOpen(false);
    }
  };

  const saveAutoConfig = async (next) => {
    setAutoSaving(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/ai/auto-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ botId: BOT_ID, ...next })
      });
      if (res.ok) {
        const data = await res.json();
        setAutoConfig(data.config || next);
      }
    } finally {
      setAutoSaving(false);
      setAutoOpen(false);
    }
  };

  return (
    <div className="app">
      <div className="bg-glow" />
      <header className="topbar">
        <div className="brand">
          <div className="brand-title">WYCKOFF AI LAB</div>
          <div className="brand-sub">BRIDGEPUPPET CONTROL SURFACE</div>
        </div>
        <div className="status-pills">
          <span className={`pill ${bridgeConnected ? "pill-ok" : "pill-warn"}`}>
            {bridgeConnected ? "CONNECTED" : "DISCONNECTED"}
          </span>
          <span
            className={`pill ${
              dataSource === "LIVE_WS"
                ? "pill-ok"
                : dataSource === "CACHED" || dataSource === "UNKNOWN_TS" || dataSource === "SIMULATED"
                  ? "pill-warn"
                  : ""
            }`}
            title={feedState?.data_source_kind ? `source=${feedState.data_source_kind}` : ""}
          >
            {dataSource === "CACHED" ? "DATA CACHED" : `SRC ${dataSource}`}
          </span>
          <span className={`pill ${healthOk ? "pill-ok" : "pill-warn"}`}>
            HEALTH {healthOk ? "OK" : "--"}
          </span>
          {shadowMode && (
            <span className="pill pill-warn">
              SHADOW
            </span>
          )}
          <span className={`pill ${ntMode === "LIVE" ? "pill-ok" : ntMode === "BACKTEST" ? "pill-warn" : ""}`}>
            NT MODE {ntMode}
          </span>
          <span className={`pill ${platformMode === "LIVE" ? "pill-ok" : platformMode === "BACKTEST" ? "pill-warn" : "pill-warn"}`}>
            MODE {platformMode}
          </span>
          <span className="pill">LAT {latencyMs} MS</span>
          <button className={`pill ${execModeClass}`} onClick={() => setExecModeOpen(true)}>
            EXEC {execMode}
          </button>
          <span className={`pill ${wsAgeSec !== null && wsAgeSec <= wsStaleSec ? "pill-ok" : "pill-warn"}`}>
            WS AGE {wsAgeSec === null ? "--" : `${wsAgeSec}s`}
          </span>
          <span className={`pill ${feedOk ? "pill-ok" : "pill-warn"}`}>
            BAR AGE {feedAgeSec === null ? "--" : `${feedAgeSec}s`}
          </span>
          <span className={`pill ${feedOk ? "pill-ok" : "pill-warn"}`} title={feedState?.feed_reason || ""}>
            FEED {feedOk ? "OK" : feedState.feed_status === "NO_FEED" ? "NO FEED" : "STALE"}
          </span>
          <span className={`pill ${monitorOk ? "pill-ok" : "pill-warn"}`}>
            MON AGE {monitorAgeSec === null ? "--" : `${monitorAgeSec}s`}
          </span>
          <span className={`pill ${monitorOk ? "pill-ok" : "pill-warn"}`}>
            MONITOR {monitorOk ? "OK" : feedState.monitor_status === "NO_MONITOR" ? "NO MONITOR" : "STALE"}
          </span>
          <span className="pill">TIME {clock}</span>
          <span className="pill">SESSION {sessionUptime}</span>
          <button className="pill pill-action" onClick={() => setLogOpen(true)}>
            LOG
          </button>
        </div>
      </header>
      {feedState.feed_status !== "LIVE" && !bar.timestamp && (
        <div className="error-banner">WAITING FOR NINJATRADER DATA (BridgePuppet)</div>
      )}
      {activeError && <div className="error-banner">{activeError}</div>}
      {activeError && (
        <div className="error-panel">
          {errorItems.map((item) => (
            <div key={item.key} className="error-item">
              <span className="label">{item.label}</span>
              <span className={`status-chip ${statusClassFor(item.value)}`}>{item.value}</span>
            </div>
          ))}
        </div>
      )}

      <main className="grid">
        {execModeOpen && (
          <div className="modal">
            <div className="modal-backdrop" onClick={() => setExecModeOpen(false)} />
            <div className="modal-panel">
              <div className="modal-header">
                <div className="label">EXECUTION MODE</div>
                <button onClick={() => setExecModeOpen(false)}>CLOSE</button>
              </div>
              <div className="config-grid">
                <label>
                  Mode
                  <select value={execModeDraft} onChange={(e) => setExecModeDraft(e.target.value)}>
                    <option value="DISABLED">DISABLED</option>
                    <option value="MANUAL_ONLY">MANUAL_ONLY</option>
                    <option value="LIVE_ALLOWED">LIVE_ALLOWED</option>
                  </select>
                </label>
                <label>
                  Token (optional)
                  <input value={execToken} onChange={(e) => setExecToken(e.target.value)} placeholder="x-execution-token" />
                </label>
              </div>
              <div className="signal-hint" style={{ marginTop: 10 }}>
                {executionStatus?.token_required ? "Token required." : "Token not required (set WYCKOFF_EXECUTION_TOKEN to protect)."}
              </div>
              <button className="pill pill-action" onClick={updateExecutionMode} style={{ marginTop: 10 }}>
                APPLY
              </button>
            </div>
          </div>
        )}
        <section className="card price-card">
          <div className="card-header">
            <span className="label">SYMBOL</span>
            <span className={`status-dot ${feedOk ? "ok" : "warn"}`}>
              {feedOk ? "LIVE" : dataSource === "CACHED" ? "DATA CACHED" : bar.timestamp ? "STALE" : "WAITING FOR NINJA"}
            </span>
          </div>
          <div className="price-row">
            <div className="symbol">{bar.symbol || "MNQ"}</div>
            <div className="price">{formatNum(bar.price, 2)}</div>
            <div className="price-ccy">USD</div>
          </div>
          <div className="ohlc-grid">
            <div>
              <div className="label">OPEN</div>
              <div className="value">{formatNum(bar.ohlc.open, 2)}</div>
            </div>
            <div>
              <div className="label">HIGH</div>
              <div className="value">{formatNum(bar.ohlc.high, 2)}</div>
            </div>
            <div>
              <div className="label">LOW</div>
              <div className="value">{formatNum(bar.ohlc.low, 2)}</div>
            </div>
            <div>
              <div className="label">CLOSE</div>
              <div className="value">{formatNum(bar.ohlc.close, 2)}</div>
            </div>
            <div>
              <div className="label">VOLUME</div>
              <div className="value">{formatNum(bar.volume, 0)}</div>
            </div>
            <div>
              <div className="label">LAST BAR</div>
              <div className="value">{formatTime(bar.timestamp)}</div>
            </div>
          </div>
        </section>

        <section className="card trade-card">
          <div className="card-header">
            <span className="label">MANUAL TRADING</span>
          </div>
          <div className="field">
            <label>Quantity</label>
            <input type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} />
          </div>
          <div className="field">
            <label>Order Type</label>
            <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
              <option>Market</option>
              <option>Limit</option>
            </select>
          </div>
          {orderType === "Limit" && (
            <div className="field">
              <label>Limit Price</label>
              <input
                type="number"
                step="0.25"
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)}
              />
            </div>
          )}
          <div className="field-grid">
            <div className="field">
              <label>SL Ticks</label>
              <input type="number" min="0" value={slTicks} onChange={(e) => setSlTicks(e.target.value)} />
            </div>
            <div className="field">
              <label>TP Ticks</label>
              <input type="number" min="0" value={tpTicks} onChange={(e) => setTpTicks(e.target.value)} />
            </div>
          </div>
          <div className="button-row">
            <button className="btn buy" onClick={() => handleSubmit("BUY")}>
              BUY
            </button>
            <button className="btn sell" onClick={() => handleSubmit("SELL")}>
              SELL
            </button>
            <button className="btn flat" onClick={() => handleSubmit("FLATTEN")}>
              FLATTEN
            </button>
          </div>
          <div className="command-status">
            <div className="command-status-row">
              <span className="label">LAST COMMAND</span>
              <span className="value">
                {lastExec ? `${lastExec.action} x${lastExec.qty}` : "--"}
              </span>
            </div>
            <div className="command-status-row">
              <span className="label">ACK STATUS</span>
              <span className={`status-chip ${statusClassFor(lastExecEvent)}`}>
                {lastExecEvent || "--"}
              </span>
            </div>
          </div>
          <div className="hint">Limit orders are simulated client-side and trigger when price crosses.</div>
        </section>

        <section className="card status-card">
          <div className="card-header">
            <span className="label">BOT STATUS</span>
          </div>
          <div className="status-grid">
            <div>
              <div className="label">BOT ID</div>
              <div className="value">{BOT_ID}</div>
            </div>
            <div>
              <div className="label">MODE</div>
              <div className="value">{botStatus.mode || "UNKNOWN"}</div>
            </div>
            <div>
              <div className="label">LAST SEEN</div>
              <div className="value">{formatTime(botStatus.last_seen_utc)}</div>
            </div>
            <div>
              <div className="label">LAST SNAPSHOT</div>
              <div className={`value ${snapshotAge !== null && snapshotAge > 60 ? "warn" : ""}`}>
                {snapshotAge === null ? "--" : `${Math.round(snapshotAge)}s ago`}
              </div>
            </div>
            {positionState && (
              <div>
                <div className="label">POSITION</div>
                <div className="value">
                  {positionState.symbol} x{positionState.qty} @ {formatNum(positionState.avgPrice, 2)}
                </div>
              </div>
            )}
            <div>
              <div className="label">LAST BAR TS</div>
              <div className="value">{formatTime(monitorStatus?.lastBarTs)}</div>
            </div>
            <div>
              <div className="label">STRATEGY MONITOR</div>
              <div className="value">{formatTime(monitorStatus?.strategyMonitor?.ts)}</div>
            </div>
            {monitorStatus?.strategyMonitor && (
              <>
                <div>
                  <div className="label">WS STATE (NT8)</div>
                  <div className="value">{monitorStatus.strategyMonitor.wsState || "--"}</div>
                </div>
                <div>
                  <div className="label">BARS SENT (NT8)</div>
                  <div className="value">
                    {monitorStatus.strategyMonitor.sendCount} (Sk: {monitorStatus.strategyMonitor.skipCount})
                  </div>
                </div>
                <div>
                  <div className="label">MODE (NT8)</div>
                  <div className="value">{monitorStatus.strategyMonitor.mode}</div>
                </div>
              </>
            )}
            <div>
              <div className="label">INSTRUMENT</div>
              <div className="value">{botStatus.instrument || bar.symbol}</div>
            </div>
            <div>
              <div className="label">INSTRUMENT SELECT</div>
              <div className="inline-field">
                <select
                  value={instrumentChoice || ""}
                  onChange={(e) => setInstrumentChoice(e.target.value)}
                >
                  <option value="">--</option>
                  <option>MNQ</option>
                  <option>NQ</option>
                  <option>ES</option>
                  <option>GC</option>
                </select>
                <button className="pill pill-action" onClick={updateInstrument}>
                  SET
                </button>
              </div>
            </div>
            <div>
              <div className="label">ORDERS SENT</div>
              <div className="value">{execs.length}</div>
            </div>
            <div>
              <div className="label">ACK</div>
              <div className="value">{Object.keys(lastEventById).length}</div>
            </div>
          </div>
        </section>

        <section className="card exec-card">
          <div className="card-header">
            <span className="label">EXECUTION MONITOR</span>
          </div>
          <div className="list">
            {execs.length === 0 && <div className="muted">No manual executions yet.</div>}
            {execs.map((exe) => (
              <div key={exe.id} className="list-item">
                <span className={`tag ${exe.action === "BUY" ? "buy" : exe.action === "SELL" ? "sell" : "flat"}`}>
                  {exe.action}
                </span>
                <span className="muted">x{exe.qty}</span>
                <span className="muted">{formatTime(exe.ts)}</span>
                <span className="status">
                  {lastEventById[exe.id] || (exe.ack?.status ? `ACK_${exe.ack.status}` : "SENT")}
                  {(exe.ack?.reject_reason || exe.ack?.reason) ? ` (${exe.ack.reject_reason || exe.ack.reason})` : ""}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="card signal-card">
          <div className="card-header">
            <span className="label">WYCKOFF SIGNAL</span>
            <div className="signal-actions">
              <button className="pill pill-action" onClick={() => setConfigOpen(true)}>
                CONFIG
              </button>
              <button className="pill pill-action" onClick={() => setAutoOpen(true)}>
                AUTO
              </button>
            </div>
          </div>
          {!aiSignal && <div className="muted">No signal yet.</div>}
          {aiSignal && (
            <>
              <div className="signal-row">
                <span className={`tag ${aiSignal.bias === "BULLISH" ? "buy" : aiSignal.bias === "BEARISH" ? "sell" : "flat"}`}>
                  {aiSignal.signal}
                </span>
                <span className="muted">{aiSignal.bias || "NEUTRAL"}</span>
                <span className="muted">{Math.round((aiSignal.confidence || 0) * 100)}%</span>
                <span className="muted">{formatTime(aiSignal.updatedAt)}</span>
              </div>
              <div className="signal-explain">{aiSignal.explain || "--"}</div>
              {autoConfig && (
                <div className="signal-hint">
                  Auto route: {autoConfig.enabled ? "ON" : "OFF"} - min conf{" "}
                  {Math.round((autoConfig.min_confidence || 0) * 100)}% - max/hr{" "}
                  {autoConfig.max_per_hour}
                </div>
              )}
              {aiSignal.signal === "NONE" && aiSignal.explain?.includes("Insufficient") && (
                <div className="signal-hint">Esperando 10+ barras para senales Wyckoff.</div>
              )}
              <div className="signal-hint">
                Execution disabled: AI/Swarm only recommends. Use Manual Trade to execute.
              </div>
            </>
          )}
        </section>

        <section className="card signal-history-card">
          <div className="card-header">
            <span className="label">SIGNAL HISTORY</span>
          </div>
          {aiHistory.length === 0 && <div className="muted">No signal history yet.</div>}
          <div className="list">
            {aiHistory.map((row, idx) => (
              <div key={`${row.updatedAt}-${idx}`} className="list-item">
                <span className={`tag ${row.bias === "BULLISH" ? "buy" : row.bias === "BEARISH" ? "sell" : "flat"}`}>
                  {row.signal}
                </span>
                <span className="muted">{Math.round((row.confidence || 0) * 100)}%</span>
                <span className="muted">{formatTime(row.barTs)}</span>
                {row.explain && <span className="muted signal-note">{row.explain}</span>}
              </div>
            ))}
          </div>
        </section>

        <section className="card ml-card">
          <MLTrainingPanel botId={BOT_ID} onToast={addToast} />
          <ModelManager botId={BOT_ID} onToast={addToast} />
          <TrainingHistoryChart botId={BOT_ID} />
          <ConfusionMatrixHeatmap botId={BOT_ID} />
        </section>

        <section className="card limits-card">
          <div className="card-header">
            <span className="label">PENDING LIMIT ORDERS</span>
          </div>
          <div className="list">
            {pendingLimits.length === 0 && <div className="muted">No pending limits.</div>}
            {pendingLimits.map((lim) => (
              <div key={lim.id} className="list-item">
                <span className={`tag ${lim.side === "BUY" ? "buy" : "sell"}`}>{lim.side}</span>
                <span className="muted">@ {formatNum(lim.price, 2)}</span>
                <span className="muted">x{lim.qty}</span>
              </div>
            ))}
          </div>
        </section>

        {shadowMode && (
          <section className="card shadow-card">
            <div className="card-header">
              <span className="label">SHADOW DECISIONS</span>
              <span className="pill pill-warn">SHADOW MODE</span>
            </div>
            <div className="list">
              {shadowDecisions.length === 0 && <div className="muted">No shadow decisions yet.</div>}
              {shadowDecisions.slice(0, 10).map((decision) => (
                <div key={decision.id} className="list-item">
                  <span className={`tag ${decision.signal === "BUY" ? "buy" : decision.signal === "SELL" ? "sell" : "flat"}`}>
                    {decision.signal}
                  </span>
                  <span className="muted">x{decision.payloadOriginal?.qty || 0}</span>
                  <span className="muted">{decision.instrument}</span>
                  <span className="muted">{formatTime(decision.ts)}</span>
                  <span className="status shadow">LOGGED</span>
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="card">
          <div className="card-header">
            <span className="label">SWARM CONTROL (READ-ONLY)</span>
            <button className="pill pill-action" onClick={generateSwarmPlan}>PLAN</button>
          </div>
          <div className="list">
            {swarmRank.length === 0 && <div className="muted">No swarm data yet.</div>}
            {swarmRank.slice(0, 10).map((row) => (
              <div key={row.botId} className="list-item">
                <span className="muted">{row.botId}</span>
                <span className="muted">{row.instrument || "--"}</span>
                <span className={`status ${row.feed_status === "LIVE" ? "ok" : "warn"}`}>{row.feed_status}</span>
                <span className="muted">MODE {row.nt_mode || "UNKNOWN"}</span>
                <span className="muted">SCORE {formatNum(row.score, 3)}</span>
              </div>
            ))}
          </div>
          {swarmPlan.length > 0 && (
            <div className="signal-hint" style={{ marginTop: 10 }}>
              {swarmPlan.map((p) => (
                <div key={p.botId}>
                  {p.botId}: {p.recommendation} ({p.reason})
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <span className="label">BOTS REGISTRY</span>
          </div>
          {!botsRegistry && <div className="muted">Loading...</div>}
          {botsRegistry && (
            <div className="list">
              {Object.keys(botsRegistry.computed || {}).length === 0 && <div className="muted">No bots yet.</div>}
              {Object.entries(botsRegistry.computed || {}).map(([botId, st]) => (
                <div key={botId} className="list-item">
                  <span className="muted">{botId}</span>
                  <span className={`status ${st.ws_connected ? "ok" : "warn"}`}>{st.ws_connected ? "CONNECTED" : "OFF"}</span>
                  <span className={`status ${st.feed_status === "LIVE" ? "ok" : "warn"}`}>{st.feed_status}</span>
                  <span className="muted">WS {st.ws_age_sec === null || st.ws_age_sec === undefined ? "--" : `${Math.round(st.ws_age_sec)}s`}</span>
                  <span className="muted">BAR {st.bar_age_sec === null || st.bar_age_sec === undefined ? "--" : `${Math.round(st.bar_age_sec)}s`}</span>
                  <span className="muted">SRC {st.data_source || "--"}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <span className="label">TIMELINE</span>
          </div>
          <div className="list">
            {eventTimeline.length === 0 && <div className="muted">No events yet.</div>}
            {eventTimeline.slice(0, 30).map((ev) => (
              <div key={ev.id} className="list-item">
                <span className="muted">{formatTime(ev.ts_utc)}</span>
                <span className="muted">{ev.event_type}</span>
                <span className="muted">{ev.data?.symbol || ev.data?.mode || ""}</span>
              </div>
            ))}
          </div>
        </section>

        <DataManagerPanel />

        <AIAssistantPanel botId={BOT_ID} />

        <section className="card chat-card">
          <div className="card-header">
            <span className="label">WYCKOFF AI ASSISTANT</span>
            <span className="pill pill-mini">BETA</span>
          </div>
          <div className="signal-hint">
            <label style={{ marginRight: 12 }}>
              <input type="checkbox" checked={opsAssistantEnabled} onChange={(e) => setOpsAssistantEnabled(e.target.checked)} /> Ops mode
            </label>
            <label>
              <input type="checkbox" checked={opsAssistantIncludeWeb} onChange={(e) => setOpsAssistantIncludeWeb(e.target.checked)} /> includeWeb
            </label>
          </div>
          {chatContext && <div className="chat-context">{chatContext}</div>}
          <div className="chat-body">
            {chatMessages.map((m, idx) => (
              <div key={idx} className={`chat-msg ${m.role}`}>
                <div className="chat-role">{m.role}</div>
                <div className="chat-text">{m.content}</div>
              </div>
            ))}
          </div>
          <div className="chat-input">
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder="Ask about execution, risk, or market context..."
            />
            <button onClick={sendChat}>SEND</button>
          </div>
        </section>

        <section className="card calendar-card">
          <div className="card-header">
            <span className="label">ECONOMIC CALENDAR</span>
            <div className="calendar-actions">
              <span className="pill pill-mini">FOREX FACTORY</span>
              <button className="pill pill-action" onClick={refreshCalendar} disabled={calendarLoading}>
                {calendarLoading ? "REFRESHING" : "REFRESH"}
              </button>
            </div>
          </div>
          <div className="calendar-meta">
            <div>
              <div className="label">TIMEZONE</div>
              <div className="value">{calendarStatus?.timezone || "UTC"}</div>
            </div>
            <div>
              <div className="label">LAST REFRESH</div>
              <div className="value">{formatDateTime(calendarStatus?.last_refresh)}</div>
            </div>
          </div>
          <div className="list calendar-list">
            {calendarEvents.length === 0 && <div className="muted">No upcoming events.</div>}
            {calendarEvents.map((event) => (
              <div key={event.event_id} className="calendar-row">
                <div className="calendar-time">
                  {event.event_ts ? formatDateTime(event.event_ts) : event.event_date}
                </div>
                <div className="calendar-main">
                  <div className="calendar-title">{event.event_name}</div>
                  <div className="calendar-sub">
                    {event.currency && <span className="calendar-chip">{event.currency}</span>}
                    {event.impact && (
                      <span className={`calendar-chip impact-${event.impact.toLowerCase()}`}>
                        {event.impact}
                      </span>
                    )}
                    {event.forecast && <span className="calendar-chip">F {event.forecast}</span>}
                    {event.previous && <span className="calendar-chip">P {event.previous}</span>}
                    {event.actual && <span className="calendar-chip">A {event.actual}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </main>

      <CommandLogModal open={logOpen} onClose={() => setLogOpen(false)} entries={logEntries} />
      <WyckoffConfigModal
        open={configOpen}
        onClose={() => setConfigOpen(false)}
        config={wyckoffConfig}
        onSave={saveWyckoffConfig}
        saving={configSaving}
      />
      <AutoTradeModal
        open={autoOpen}
        onClose={() => setAutoOpen(false)}
        config={autoConfig}
        onSave={saveAutoConfig}
        saving={autoSaving}
      />
      <ToastContainer toasts={toasts} />
    </div>
  );
}
