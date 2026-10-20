// Run with: node --test backend/test/test_dashboard_ui.cjs
// A minimal DOM harness checks the dashboard's refresh behavior without dependencies.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../dashboard/app.js"), "utf8");

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.checked = true; this.hidden = false; this.open = false; this.value = ""; this.dataset = {}; this.style = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(type, callback) { this.events[type] = callback; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  set innerHTML(value) { throw new Error("Unsafe HTML rendering"); }
}

function descendants(node) {
  return [node, ...node.children.flatMap(descendants)];
}

function texts(node) {
  return descendants(node).map((item) => item.textContent).filter(Boolean);
}

function fixture() {
  const counts = { total: 1, with_content: 0, missing_content: 1, awaiting_extraction: 1, extraction_disabled: 0, retry_limit_reached: 0, not_eligible: 0 };
  return {
    snapshot_at: "2026-10-18T12:00:00Z", daily_dates: ["2026-10-17", "2026-10-18"], summary: { ...counts, total_feeds: 1, active_feeds: 1 },
    feeds: [{ id: 1, name: '<img src=x onerror="alert(1)">', urls: ["javascript:alert(1)"],
      category: "Test", is_active: true, skip_extraction: false, articles: counts, daily_articles: [3, 1],
      latest_fetch: { status: "error", timestamp: null, entries_found: 0, valid_entries_submitted: 0, duration_ms: 0, error: "<script>alert(1)</script>" } }],
    scheduler: { enabled: false, scheduler_running: false, jobs: [] }, live_processing_count: null,
  };
}

function harness() {
  const nodes = new Map();
  const requests = [];
  let tick;
  const get = (id) => {
    for (const node of nodes.values()) {
      const found = descendants(node).find((item) => item.id === id);
      if (found) return found;
    }
    if (!nodes.has(id)) {
      const node = new Node("div");
      if (["add-feed", "feed-fields", "delete-feed", "confirm-delete", "scheduler-start", "scheduler-stop"].includes(id)) node.dataset.actionControl = "";
      nodes.set(id, node);
    }
    return nodes.get(id);
  };
  const document = { getElementById: get, createElement: (tag) => new Node(tag), activeElement: null,
    querySelectorAll: () => [...nodes.values()].flatMap(descendants).filter((node) => node.dataset.actionControl !== undefined),
  };
  vm.runInNewContext(source, {
    document,
    Intl, Date, AbortSignal,
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })),
    setInterval: (fn, delay) => { assert.equal(delay, 30000); tick = fn; },
  });
  return {
    get, requests, document, tick: () => tick(), click: () => get("refresh").events.click(),
    resolve: (index, body = fixture(), status = 200) => requests[index].resolve({ ok: status >= 200 && status < 300, status, json: async () => body }),
  };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

test("initial load, manual refresh, automatic toggle and no overlapping requests", async () => {
  const h = harness();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, "/api/news/dashboard?days=7");
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
  for (const root of [row, h.get("feed-cards")]) {
    const content = texts(root);
    assert.ok(content.includes(fixture().feeds[0].name));
    assert.ok(content.includes("javascript:alert(1)"));
    assert.ok(content.includes("<script>alert(1)</script>"));
    assert.ok(content.includes("0 ms"));
    assert.ok(descendants(root).every((node) => !["script", "img", "a"].includes(node.tag)));
  }
});

test("feed details and keyboard focus survive refresh in both layouts", async () => {
  const h = harness();
  h.resolve(0); await flush();
  const mobileDetails = h.get("feed-mobile-1");
  mobileDetails.open = true;
  mobileDetails.events.toggle();
  const desktopDetails = h.get("feed-desktop-1-urls");
  desktopDetails.open = true;
  desktopDetails.events.toggle();
  h.document.activeElement = h.get("feed-mobile-1-summary");
  h.tick(); h.resolve(1); await flush();
  assert.notEqual(h.get("feed-mobile-1"), mobileDetails);
  assert.equal(h.get("feed-mobile-1").open, true);
  assert.equal(h.get("feed-desktop-1-urls").open, true);
  assert.equal(h.get("feed-mobile-1-summary").focused, true);
  const current = h.get("feed-mobile-1");
  current.open = false;
  current.events.toggle();
  h.tick(); h.resolve(2); await flush();
  assert.equal(h.get("feed-mobile-1").open, false);
});

test("mobile cards show backlog and fetch problems, with complete secondary metrics", async () => {
  const h = harness();
  h.resolve(0); await flush();
  const card = h.get("feed-cards").children[0];
  assert.match(card.className, /has-error/);
  assert.match(h.get("fetch-issues").textContent, /1 feed has a fetch error/);
  const content = texts(card);
  for (const label of ["Stored", "With content", "Missing", "Fetch error", "Awaiting extraction", "Retry limit reached", "Extraction disabled", "Not eligible", "Valid entries submitted", "RSS URLs", "Full fetch error"]) {
    assert.ok(content.includes(label), label);
  }
  const data = fixture();
  data.feeds[0].latest_fetch = null;
  h.tick(); h.resolve(1, data); await flush();
  assert.match(h.get("feed-cards").children[0].className, /has-backlog/);
  assert.ok(texts(h.get("feed-cards")).includes("Never fetched"));
  assert.match(h.get("fetch-issues").textContent, /No fetch errors/);
});

test("daily range and selected UTC day update without losing the selected day on refresh", async () => {
  const h = harness();
  h.resolve(0); await flush();
  assert.equal(h.get("daily-day").value, "2026-10-18");
  assert.ok(texts(h.get("daily-bars")).includes("1"));
  h.get("daily-day").value = "2026-10-17";
  h.get("daily-day").events.change();
  assert.ok(texts(h.get("daily-bars")).includes("3"));
  h.get("daily-range").value = "30";
  const changed = h.get("daily-range").events.change();
  assert.equal(h.requests[1].url, "/api/news/dashboard?days=30");
  h.resolve(1); await changed;
  assert.equal(h.get("daily-day").value, "2026-10-17");
  assert.ok(texts(h.get("daily-body")).includes("4")); // Period total.
});

test("feed form validates through the API and preserves inputs on failure", async () => {
  const h = harness();
  h.resolve(0); await flush();
  h.get("add-feed").events.click();
  assert.equal(h.get("feed-dialog").open, true);
  h.get("feed-name").value = " My source ";
  h.get("feed-urls").value = "https://example.com/rss\n\nhttps://example.com/tech";
  h.get("feed-extraction").checked = false;
  const rejected = h.get("feed-form").events.submit({preventDefault() {}});
  assert.equal(h.requests[1].options.method, "POST");
  assert.equal(JSON.parse(h.requests[1].options.body).skip_extraction, true);
  assert.equal(h.get("add-feed").disabled, true);
  h.resolve(1, {detail: "Name already exists"}, 409); await rejected;
  assert.equal(h.get("feed-dialog").open, true);
  assert.equal(h.get("feed-name").value, " My source ");
  assert.equal(h.get("feed-form-error").textContent, "Name already exists");
  const saved = h.get("feed-form").events.submit({preventDefault() {}});
  h.resolve(2, {id: 2}, 201); await flush();
  h.resolve(3); await saved;
  assert.equal(h.get("feed-dialog").open, false);
  assert.equal(h.get("add-feed").disabled, false);
  assert.equal(h.get("action-status").textContent, "My source saved.");
});

test("editing uses stable IDs and deleting requires a separate confirmation", async () => {
  const h = harness();
  h.resolve(0); await flush();
  const edit = descendants(h.get("feed-cards")).find((node) => node.tag === "button" && node.textContent === "Edit");
  edit.events.click();
  h.get("feed-name").value = "Renamed / source";
  const save = h.get("feed-form").events.submit({preventDefault() {}});
  assert.equal(h.requests[1].url, "/api/news/dashboard/feeds/1");
  assert.equal(h.requests[1].options.method, "PUT");
  h.resolve(1, {}); await flush(); h.resolve(2); await save;
  edit.events.click();
  h.get("delete-feed").events.click();
  assert.equal(h.get("delete-dialog").open, true);
  assert.equal(h.requests.length, 3); // Opening a confirmation sends no delete.
  h.get("cancel-delete").events.click();
  assert.equal(h.get("delete-dialog").open, false);
  h.get("delete-feed").events.click();
  const deletion = h.get("confirm-delete").events.click();
  assert.equal(h.requests[3].options.method, "DELETE");
  assert.equal(h.requests[3].url, "/api/news/dashboard/feeds/1");
  h.resolve(3, {message:"Removed; articles retained"}); await flush(); h.resolve(4); await deletion;
  assert.equal(h.get("feed-dialog").open, false);
});

test("feed refresh reports partial errors, prevents duplicate actions and refreshes metrics", async () => {
  const h = harness();
  h.resolve(0); await flush();
  const button = descendants(h.get("feed-cards")).find((node) => node.tag === "button" && node.textContent === "Refresh feed");
  const action = button.events.click();
  await button.events.click();
  assert.equal(h.requests.length, 2);
  assert.equal(h.requests[1].url, "/api/news/dashboard/feeds/1/refresh");
  h.resolve(1, {status:"partial",articles_found:5,articles_processed:3,error:"<script>Offline</script>"}); await flush();
  h.resolve(2); await action;
  assert.match(h.get("action-status").textContent, /5 entries found/);
  assert.equal(h.get("action-error").textContent, "<script>Offline</script>");
});

test("scheduler start and stop reflect actual refreshed state", async () => {
  const h = harness();
  h.resolve(0); await flush();
  assert.equal(h.get("scheduler-start").disabled, false);
  assert.equal(h.get("scheduler-stop").disabled, true);
  const start = h.get("scheduler-start").events.click();
  assert.equal(h.requests[1].url, "/api/news/scheduler/start");
  h.resolve(1, {}); await flush();
  const running = fixture(); running.scheduler.scheduler_running = true;
  h.resolve(2, running); await start;
  assert.equal(h.get("scheduler-start").disabled, true);
  assert.equal(h.get("scheduler-stop").disabled, false);
  const stop = h.get("scheduler-stop").events.click();
  assert.equal(h.requests[3].url, "/api/news/scheduler/stop");
  h.resolve(3, {}); await flush(); h.resolve(4); await stop;
  assert.equal(h.get("scheduler-start").disabled, false);
});
