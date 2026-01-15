import React from "react";
import { createRoot } from "react-dom/client";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import "./styles.css";

function renderBootstrapError(error) {
  const rootEl = document.getElementById("root");
  if (!rootEl) return;

  const isDev = Boolean(import.meta?.env?.DEV);
  const escapeHtml = (value) =>
    String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll("\"", "&quot;")
      .replaceAll("'", "&#39;");

  const message = escapeHtml(error?.message || String(error || "Unknown error"));
  const stack = escapeHtml(error?.stack || "");

  rootEl.innerHTML = `
    <div style="padding:20px;color:#ff6b6b;background:#0a0d14;min-height:100vh;font-family:monospace;">
      <h1>App failed to start.</h1>
      <div style="margin:10px 0;color:#cfd8ff">See console for details. ${isDev ? "" : "Copy diagnostics before reporting."}</div>
      <button id="wyckoff_reload_btn" style="margin:10px 0;padding:6px 10px;cursor:pointer;">Reload</button>
      <pre style="white-space:pre-wrap;margin-top:10px;">${message}</pre>
      ${isDev && stack ? `<pre style="white-space:pre-wrap;margin-top:10px;">${stack}</pre>` : ""}
    </div>
  `;

  const btn = document.getElementById("wyckoff_reload_btn");
  if (btn) btn.addEventListener("click", () => window.location.reload());
}

async function bootstrap() {
  const rootEl = document.getElementById("root");
  if (!rootEl) {
    renderBootstrapError(new Error("Missing #root element in index.html"));
    return;
  }

  try {
    const mod = await import("./App.jsx");
    const App = mod?.default;
    if (!App) throw new Error("App.jsx has no default export");

    createRoot(rootEl).render(
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    );
  } catch (error) {
    console.error("[bootstrap] failed to mount React app", error);
    renderBootstrapError(error);
  }
}

bootstrap();
