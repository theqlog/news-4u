// Run with: node --test backend/test/test_dashboard_ui.cjs
// A minimal DOM harness checks the dashboard's refresh behavior without dependencies.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../dashboard/app.js"), "utf8");

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.checked = true; this.hidden = false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(type, callback) { this.events[type] = callback; }
  set innerHTML(value) { throw new Error("Unsafe HTML rendering"); }
}

function fixture() {
  const counts = { total: 1, with_content: 0, missing_content: 1, awaiting_extraction: 1, extraction_disabled: 0, retry_limit_reached: 0, not_eligible: 0 };
  return {
    snapshot_at: "2026-10-18T12:00:00Z", summary: { ...counts, total_feeds: 1, active_feeds: 1 },
    feeds: [{ id: 1, name: '<img src=x onerror="alert(1)">', urls: ["javascript:alert(1)"],
      category: "Test", is_active: true, skip_extraction: false, articles: counts,
      latest_fetch: { status: "error", timestamp: null, entries_found: 0, valid_entries_submitted: 0, duration_ms: 0, error: "<script>alert(1)</script>" } }],
    scheduler: { enabled: false, scheduler_running: false, jobs: [] }, live_processing_count: null,
  };
}

function harness() {
  const nodes = new Map();
  const requests = [];
  let tick;
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, new Node("div"));
    return nodes.get(id);
  };
  vm.runInNewContext(source, {
    document: { getElementById: get, createElement: (tag) => new Node(tag) },
    Intl, Date, AbortSignal,
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })),
    setInterval: (fn, delay) => { assert.equal(delay, 30000); tick = fn; },
  });
  return {
    get, requests, tick: () => tick(), click: () => get("refresh").events.click(),
    resolve: (index, body = fixture(), status = 200) => requests[index].resolve({ ok: status === 200, status, json: async () => body }),
  };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

test("initial load, manual refresh, automatic toggle and no overlapping requests", async () => {
  const h = harness();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, "/api/news/dashboard");
  assert.equal(h.requests[0].options.cache, "no-store");
  assert.equal(h.get("refresh").disabled, true);
  h.tick(); await h.click();
  assert.equal(h.requests.length, 1);
  h.resolve(0); await flush();
  assert.equal(h.get("refresh").disabled, false);
  assert.match(h.get("updated").textContent, /Last successful refresh/);
  h.get("auto-refresh").checked = false;
  h.tick();
  assert.equal(h.requests.length, 1);
  const clicked = h.click();
  assert.equal(h.requests.length, 2);
  h.resolve(1); await clicked;
  h.get("auto-refresh").checked = true;
  h.tick();
  assert.equal(h.requests.length, 3);
  h.resolve(2); await flush();
});

test("HTTP and network errors retain the last snapshot and recover", async () => {
  const h = harness();
  h.resolve(0); await flush();
  const previousRows = h.get("feeds").children;
  const previousTimestamp = h.get("updated").textContent;
  h.tick(); h.resolve(1, null, 500); await flush();
  assert.equal(h.get("error").hidden, false);
  assert.match(h.get("error").textContent, /Showing the last successful snapshot.*HTTP 500/);
  assert.equal(h.get("feeds").children, previousRows);
  assert.equal(h.get("updated").textContent, previousTimestamp);
  h.tick(); h.requests[2].reject(new Error("Network unavailable")); await flush();
  assert.match(h.get("error").textContent, /Network unavailable/);
  h.tick(); h.resolve(3); await flush();
  assert.equal(h.get("error").hidden, true);
  assert.equal(h.get("refresh").disabled, false);
});

test("initial failure can recover to an empty dashboard", async () => {
  const h = harness();
  h.requests[0].reject(new Error("Timeout")); await flush();
  assert.equal(h.get("updated").textContent, "No snapshot loaded yet.");
  const data = fixture();
  data.feeds = [];
  h.tick(); h.resolve(1, data); await flush();
  assert.equal(h.get("error").hidden, true);
  assert.equal(h.get("empty").hidden, false);
});

test("feed names, URLs and errors render as literal text", async () => {
  const h = harness();
  h.resolve(0); await flush();
  const row = h.get("feeds").children[0];
  assert.equal(row.children[0].children[0].textContent, fixture().feeds[0].name);
  assert.equal(row.children[0].children[2].textContent, "javascript:alert(1)");
  assert.equal(row.children.at(-1).textContent, "<script>alert(1)</script>");
  assert.equal(row.children.at(-2).textContent, "0 ms");
});
