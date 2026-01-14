const BASE = process.env.UI_BASE || "http://localhost:3001";

const fail = (msg) => {
  console.error(`[FAIL] ${msg}`);
  process.exitCode = 1;
};

const ok = (msg) => console.log(`[OK] ${msg}`);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(path) {
  const url = `${BASE}${path}`;
  const res = await fetch(url);
  const ct = (res.headers.get("content-type") || "").toLowerCase();
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  if (!ct.includes("application/json")) throw new Error(`Non-JSON response for ${url} content-type=${ct}`);
  return res.json();
}

async function wsCheck() {
  const wsUrl = BASE.replace(/^http/i, "ws") + "/ws/live";
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let gotMessage = false;
    const timer = setTimeout(() => {
      ws.close();
      gotMessage ? resolve(true) : reject(new Error("No message within 5s"));
    }, 5000);

    ws.onopen = () => ok(`WS open ${wsUrl}`);
    ws.onmessage = () => {
      gotMessage = true;
    };
    ws.onerror = (e) => {
      clearTimeout(timer);
      reject(new Error(`WS error ${String(e?.message || e)}`));
    };
    ws.onclose = () => {
      clearTimeout(timer);
      if (gotMessage) resolve(true);
    };
  });
}

async function main() {
  console.log(`[doctor:ui] BASE=${BASE}`);

  try {
    const health = await fetchJson("/api/v1/health");
    if (!health.ok) throw new Error("health.ok is false");
    ok("GET /api/v1/health (proxied)");
  } catch (e) {
    fail(`health: ${e.message}`);
    return;
  }

  try {
    const bots = await fetchJson("/api/v1/bots");
    if (!bots.ok) throw new Error("bots.ok is false");
    ok("GET /api/v1/bots (proxied)");
  } catch (e) {
    fail(`bots: ${e.message}`);
  }

  try {
    await wsCheck();
    ok("WS /ws/live stable 5s");
  } catch (e) {
    fail(`ws: ${e.message}`);
  }

  // small grace period to flush logs
  await sleep(50);
}

await main();

