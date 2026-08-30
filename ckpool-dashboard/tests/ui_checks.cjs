// Run the shipped frontend with real service/API fixtures and a minimal DOM.
// This is not a browser layout test; it checks field wiring, units and visibility.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..", "yumtech_dashboard", "static");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
const script = fs.readFileSync(path.join(root, "app.js"), "utf8");
const fixture = JSON.parse(fs.readFileSync(0, "utf8"));
const elements = new Map();
for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) {
  assert.equal(elements.has(id), false, `duplicate element id: ${id}`);
  const classes = new Set();
  elements.set(id, {
    textContent: "", innerHTML: "", hidden: false, dataset: {}, attributes: {},
    style: { setProperty(key, value) { this[key] = value; } },
    classList: { add(...names) { names.forEach(name => classes.add(name)); },
      remove(...names) { names.forEach(name => classes.delete(name)); },
      toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
      contains(name) { return classes.has(name); } },
    setAttribute(key, value) { this.attributes[key] = value; },
    querySelector() { return null; },
  });
}
const get = id => {
  assert.ok(elements.has(id), `expected element: ${id}`);
  return elements.get(id);
};
const fetched = [];
const context = vm.createContext({
  Intl, Date, console, fixture,
  document: { getElementById: id => elements.get(id) || null,
    addEventListener() {}, querySelectorAll() { return []; } },
  window: {},
  fetch: async url => {
    fetched.push(url);
    const key = url.split("/api/")[1].split("?")[0];
    return { ok: true, json: async () => fixture[key] || (key === "blocks" ? [] : {}) };
  },
});
vm.runInContext(script, context);
const run = code => vm.runInContext(code, context);

(async () => {
  assert.match(html, /<h1 class="dashboard-title">CKPOOL DASHBOARD<\/h1>/);
  assert.doesNotMatch(html + css, /marquee|HOŞ GELDİNİZ|YUMTECH MADENCİLİK A\.Ş/);
  assert.doesNotMatch(html, /data-view(?:-panel|-jump)?="shares"|overview-share-feed|shares-table|Son Paylaşımlar|SHARE QUALITY/);
  assert.doesNotMatch(script, /\/api\/shares|renderShares|shares_accepted|shares_rejected|connected_seconds|miner\.protocol|miner\.difficulty|best_share_hash/);
  for (const id of ["config-version-mask", "config-engine", "template-height", "node-storage-fill"]) {
    assert.equal(elements.has(id), false, `unsupported card/field remained: ${id}`);
  }
  assert.match(css, /\[hidden\]\s*\{\s*display:\s*none\s*!important/);
  for (const view of ["overview", "miners", "blocks", "node", "settings"]) {
    assert.ok(html.includes(`data-view-panel="${view}"`));
  }
  const minerTable = html.slice(html.indexOf('data-view-panel="miners"'), html.indexOf('data-view-panel="blocks"'));
  assert.equal((minerTable.match(/<th[ >]/g) || []).length, 6);

  await run("refreshMain()");
  assert.equal(fetched.some(url => url.includes("/api/shares")), false);
  assert.equal(get("pool-totals-card").hidden, false);
  assert.equal(get("pool-accepted-diff").textContent, run("formatDifficulty(49152)"));
  assert.equal(get("pool-rejected-diff").textContent, run("formatDifficulty(32768)"));
  assert.equal(get("pool-acceptance-rate").textContent, "60.000%");
  assert.equal(get("pool-accepted-bar").style.width, "60%");
  assert.match(get("pool-totals-source").textContent, /pool\.status/);
  assert.equal(get("pool-hashrate").textContent, run("formatHashrate(142e12)"));
  assert.match(get("pool-data-age").textContent, /Dosya/);
  assert.equal((get("miners-table").innerHTML.match(/<td[ >]/g) || []).length, 12);
  assert.match(get("miners-table").innerHTML, /s19/);
  assert.match(get("miners-table").innerHTML, /nerd/);
  assert.ok(get("miners-table").innerHTML.includes(run("formatDifficulty(983040)")));
  assert.equal(get("config-difficulty-card").hidden, true);
  assert.equal(get("config-coinbase-card").hidden, true);
  assert.equal(get("sv2-key-card").hidden, true);
  assert.equal(get("overview-top-grid").classList.contains("single-column"), true);

  run("state.analytics = fixture.updated_analytics; renderAnalytics();");
  assert.equal(get("pool-accepted-diff").textContent, run("formatDifficulty(98304)"));
  assert.equal(get("pool-acceptance-rate").textContent, "75.000%");
  run("state.analytics = {pool_totals_available: false}; renderAnalytics();");
  assert.equal(get("pool-totals-card").hidden, true);
  assert.equal(get("round-effort-card").hidden, true);
  assert.equal(get("pool-accepted-diff").textContent, "—");
  run("state.analytics = {pool_totals_available: true, pool_accepted_diff: 0, pool_rejected_diff: 0, pool_acceptance_pct: null}; renderAnalytics();");
  assert.equal(get("pool-totals-card").hidden, false);
  assert.equal(get("pool-accepted-diff").textContent, "0");
  assert.equal(get("pool-acceptance-rate").textContent, "—");

  run("state.config = {sv2_enabled: true, sv2_public_key: 'abc123', starting_difficulty: 16384, coinbase_signature: '/CKPool/'}; renderConfig();");
  assert.equal(get("sv2-key-card").hidden, false);
  assert.equal(get("config-difficulty-card").hidden, false);
  assert.equal(get("config-coinbase").textContent, "/CKPool/");
  run("state.query = 'no-such-worker'; renderMiners();");
  assert.match(get("miners-table").innerHTML, /colspan="6"/);
  console.log("CKPool file → HTTP API → UI field and visibility checks passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
