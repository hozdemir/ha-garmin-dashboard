// Measure real-time panel render in headless Chrome via the DevTools protocol.
// Usage: node dev/tools/render_probe.mjs <runs> <preview url without perf param>
// Needs Chrome on 127.0.0.1:9333 (--remote-debugging-port=9333). Reads #perf from the preview.
const [runs = "20", base] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function measure(url) {
  const target = await (await fetch(`http://127.0.0.1:9333/json/new?${encodeURIComponent(url)}`, { method: "PUT" })).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let id = 0;
  const call = (method, params = {}) =>
    new Promise((resolve) => {
      const mid = ++id;
      const onMsg = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.id === mid) {
          ws.removeEventListener("message", onMsg);
          resolve(msg.result);
        }
      };
      ws.addEventListener("message", onMsg);
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  let result = null;
  for (let i = 0; i < 100 && !result; i++) {
    const r = await call("Runtime.evaluate", { expression: "document.getElementById('perf')?.textContent ?? null", returnByValue: true });
    result = r?.result?.value ? JSON.parse(r.result.value) : null;
    if (!result) await sleep(50);
  }
  ws.close();
  await fetch(`http://127.0.0.1:9333/json/close/${target.id}`);
  return result;
}

const rows = [];
for (let i = 0; i < Number(runs); i++) {
  const r = await measure(`${base}&perf=1&v=${Date.now()}${i}`);
  if (r) rows.push(r);
}
const stat = (key) => {
  const v = rows.map((r) => r[key]).sort((a, b) => a - b);
  const p95 = v[Math.max(0, Math.round(0.95 * v.length) - 1)];
  return `median=${v[Math.floor(v.length / 2)].toFixed(0)} ms p95=${p95.toFixed(0)} ms max=${v[v.length - 1].toFixed(0)} ms`;
};
console.log(`runs=${rows.length} charts=${rows[0]?.chart_count}`);
console.log(`value tiles  ${stat("tiles")}`);
console.log(`all charts   ${stat("charts")}`);
