import React, { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "";

export default function AIAssistantPanel({ botId }) {
  const [tools, setTools] = useState(false);
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState([]);
  const [cap, setCap] = useState(null);
  const [loading, setLoading] = useState(false);

  const canTools = useMemo(() => Boolean(cap?.tools?.length), [cap]);

  useEffect(() => {
    const loadCap = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/ai/capabilities`);
        if (!res.ok) return;
        const data = await res.json();
        setCap(data);
      } catch {
        // ignore
      }
    };
    loadCap();
  }, []);

  const send = async (text, withTools) => {
    const msg = (text || "").trim();
    if (!msg) return;
    setChat((prev) => [...prev, { role: "user", content: msg }]);
    setMessage("");
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/ai/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, botId, tools: Boolean(withTools) })
      });
      const data = await res.json();
      setChat((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer || "(no answer)",
          actions: data.actions || [],
          citations: data.citations || []
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
        <span className="label">AI ASSISTANT (NO ORDERS)</span>
        <label className="muted" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={tools} onChange={(e) => setTools(e.target.checked)} disabled={!canTools} />
          Enable tools
        </label>
      </div>
      <div className="signal-hint" style={{ marginBottom: 10 }}>
        {cap ? (
          <div className="muted">
            Tools: {cap.tools?.join(", ") || "--"} | Web configured: {String(cap.web_tools?.configured)}
          </div>
        ) : (
          <div className="muted">Loading capabilities...</div>
        )}
      </div>

      <div className="config-grid" style={{ gridTemplateColumns: "1fr auto" }}>
        <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Ask about health, bots, swarm, events, data..." />
        <button className="pill pill-action" onClick={() => send(message, tools)} disabled={loading}>
          {loading ? "..." : "SEND"}
        </button>
      </div>
      <div className="signal-hint" style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="pill pill-action" onClick={() => send("Explain what's happening now", true)} disabled={loading}>
          Explain now
        </button>
        <button className="pill" onClick={() => send("swarm rank", true)} disabled={loading}>
          Swarm rank
        </button>
        <button className="pill" onClick={() => send("data summary + days", true)} disabled={loading}>
          Data summary
        </button>
      </div>

      <div className="list" style={{ marginTop: 10, maxHeight: 260, overflow: "auto" }}>
        {chat.length === 0 && <div className="muted">No messages yet.</div>}
        {chat.slice(-30).map((row, idx) => (
          <div key={idx} className="list-item" style={{ whiteSpace: "pre-wrap" }}>
            <span className="muted" style={{ width: 70 }}>{row.role}</span>
            <span style={{ flex: 1 }}>{row.content}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
