import React, { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "";

export default function AIAssistantPanel({ botId }) {
  const [opsMode, setOpsMode] = useState(true);
  const [includeWeb, setIncludeWeb] = useState(false);
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState([]);
  const [loading, setLoading] = useState(false);

  const sessionId = useMemo(() => {
    try {
      return crypto.randomUUID();
    } catch {
      return `sess_${Math.random().toString(16).slice(2)}`;
    }
  }, []);

  const send = async (text) => {
    const msg = (text || "").trim();
    if (!msg) return;
    setChat((prev) => [...prev, { role: "user", content: msg }]);
    setMessage("");
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, botId, opsMode: Boolean(opsMode), includeWeb: Boolean(includeWeb), sessionId })
      });
      const data = await res.json();
      setChat((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.reply || "(no reply)",
          tool_calls: Array.isArray(data.tool_calls) ? data.tool_calls : [],
          tool_results: Array.isArray(data.tool_results) ? data.tool_results : [],
          citations: Array.isArray(data.citations) ? data.citations : [],
          suggested_actions: Array.isArray(data.suggested_actions) ? data.suggested_actions : []
        }
      ]);
    } catch {
      setChat((prev) => [...prev, { role: "assistant", content: "AI endpoint unavailable." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="card">
      <div className="card-header">
        <span className="label">WYCKOFF AI ASSISTANT (NO ORDERS)</span>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <label className="muted" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="checkbox" checked={opsMode} onChange={(e) => setOpsMode(e.target.checked)} />
            Ops mode
          </label>
          <label className="muted" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="checkbox" checked={includeWeb} onChange={(e) => setIncludeWeb(e.target.checked)} />
            includeWeb
          </label>
        </div>
      </div>

      <div className="config-grid" style={{ gridTemplateColumns: "1fr auto" }}>
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Pregúntame lo que sea (diagnóstico, bots, feed, datos). No ejecuto órdenes."
        />
        <button className="pill pill-action" onClick={() => send(message)} disabled={loading}>
          {loading ? "..." : "SEND"}
        </button>
      </div>
      <div className="signal-hint" style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="pill pill-action" onClick={() => send("Explain what's happening now")} disabled={loading}>
          Explain now
        </button>
        <button className="pill" onClick={() => send("swarm rank top 5")} disabled={loading}>
          Swarm rank
        </button>
        <button className="pill" onClick={() => send("data summary + available days")} disabled={loading}>
          Data summary
        </button>
        <button className="pill" onClick={() => send("docs websocket /ws/{botId} BAR_DATA")} disabled={loading}>
          Search docs
        </button>
      </div>

      <div className="list" style={{ marginTop: 10, maxHeight: 260, overflow: "auto" }}>
        {chat.length === 0 && <div className="muted">No messages yet.</div>}
        {chat.slice(-30).map((row, idx) => (
          <div key={idx} className="list-item" style={{ whiteSpace: "pre-wrap", flexDirection: "column", alignItems: "stretch" }}>
            <span className="muted" style={{ width: 70 }}>{row.role}</span>
            <span style={{ flex: 1 }}>{row.content}</span>

            {row.role === "assistant" && Array.isArray(row.suggested_actions) && row.suggested_actions.length > 0 && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                {row.suggested_actions.slice(0, 8).map((a, i) => (
                  <button
                    key={`${a.label || "act"}-${i}`}
                    className="pill"
                    onClick={() => send(a.message || a.label || "")}
                    disabled={loading}
                  >
                    {String(a.label || a.message || "Action")}
                  </button>
                ))}
              </div>
            )}

            {row.role === "assistant" && Array.isArray(row.citations) && row.citations.length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary className="muted">Sources ({row.citations.length})</summary>
                <div className="muted" style={{ marginTop: 8, display: "grid", gap: 10 }}>
                  {row.citations.slice(0, 12).map((c, i) => {
                    const type = String(c.type || "");
                    if (type === "doc") {
                      return (
                        <div key={`c-${i}`}>
                          <div style={{ fontWeight: 700 }}>
                            DOC: {String(c.path)}:{String(c.start_line)}-{String(c.end_line)}
                          </div>
                          <pre style={{ whiteSpace: "pre-wrap" }}>{String(c.snippet || "")}</pre>
                        </div>
                      );
                    }
                    if (type === "endpoint") {
                      return (
                        <div key={`c-${i}`}>
                          <div style={{ fontWeight: 700 }}>API: {String(c.path)}</div>
                          {c.params && <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(c.params, null, 2)}</pre>}
                        </div>
                      );
                    }
                    if (type === "web") {
                      return (
                        <div key={`c-${i}`}>
                          <div style={{ fontWeight: 700 }}>WEB: {String(c.title || c.url || "")}</div>
                          {c.url && (
                            <a href={String(c.url)} target="_blank" rel="noreferrer" className="muted">
                              {String(c.url)}
                            </a>
                          )}
                        </div>
                      );
                    }
                    return (
                      <div key={`c-${i}`}>
                        <div style={{ fontWeight: 700 }}>SOURCE</div>
                        <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(c, null, 2)}</pre>
                      </div>
                    );
                  })}
                </div>
              </details>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
