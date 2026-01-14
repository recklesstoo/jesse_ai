import React from "react";

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    const href = typeof window !== "undefined" ? window.location.href : "<no-window>";
    console.error("ErrorBoundary caught an error", { href, error, errorInfo });
    this.setState({ error, errorInfo });
  }

  render() {
    if (this.state.hasError) {
      const isDev = Boolean(import.meta?.env?.DEV);
      const error = this.state.error;
      const errorInfo = this.state.errorInfo;
      const message = error?.message || String(error || "Unknown error");
      const stack = error?.stack || "";
      const componentStack = errorInfo?.componentStack || "";

      const diagnostic = JSON.stringify(
        {
          href: typeof window !== "undefined" ? window.location.href : "<no-window>",
          message,
          stack,
          componentStack,
        },
        null,
        2
      );

      const copy = async () => {
        try {
          if (navigator?.clipboard?.writeText) {
            await navigator.clipboard.writeText(diagnostic);
          }
        } catch {
          // ignore
        }
      };

      return (
        <div style={{ padding: 20, color: "#ff6b6b", background: "#0a0d14", minHeight: "100vh", fontFamily: "monospace" }}>
          <h1>Something went wrong.</h1>
          {!isDev && <div style={{ marginBottom: 10, color: "#cfd8ff" }}>Open “Details” to copy diagnostics.</div>}
          <button onClick={copy} style={{ marginBottom: 10, padding: "6px 10px", cursor: "pointer" }}>
            Copy diagnostic
          </button>
          <details open={isDev} style={{ whiteSpace: "pre-wrap" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Message</div>
            <pre style={{ whiteSpace: "pre-wrap" }}>{message}</pre>
            {isDev && stack && (
              <>
                <div style={{ fontWeight: 700, marginTop: 12, marginBottom: 8 }}>Stack</div>
                <pre style={{ whiteSpace: "pre-wrap" }}>{stack}</pre>
              </>
            )}
            {componentStack && (
              <>
                <div style={{ fontWeight: 700, marginTop: 12, marginBottom: 8 }}>Component stack</div>
                <pre style={{ whiteSpace: "pre-wrap" }}>{componentStack}</pre>
              </>
            )}
          </details>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
