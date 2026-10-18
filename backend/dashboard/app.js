"use strict";

const byId = (id) => document.getElementById(id);
const number = (value) => new Intl.NumberFormat().format(value);
const date = (value) => value ? new Date(value).toLocaleString() : "Unavailable";
let refreshing = false;
let hasSnapshot = false;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function render(data) {
  const summary = data.summary;
  const cards = [
    ["Stored articles", summary.total], ["With extracted content", summary.with_content],
    ["Missing content", summary.missing_content], ["RSS feeds", summary.total_feeds],
    ["Active feeds", summary.active_feeds],
  ].map(([label, value]) => {
    const card = element("div", undefined, "card");
    card.append(element("p", label, "card-label"), element("p", number(value), "card-value"));
    return card;
  });
  const backlog = [
    ["Awaiting extraction", "awaiting_extraction"], ["Extraction disabled", "extraction_disabled"],
    ["Retry limit reached", "retry_limit_reached"], ["Not eligible · missing feed / link", "not_eligible"],
  ].map(([label, key]) => {
    const item = element("div", undefined, "backlog-item");
    item.append(element("strong", number(summary[key])), element("span", label));
    return item;
  });
  const rows = data.feeds.map((feed) => {
    const row = element("tr");
    const name = element("td");
    name.append(element("strong", feed.name, "feed-name"), element("span", feed.category || "Uncategorized", "category"));
    for (const url of feed.urls) {
      // Render stored URLs as text to avoid unsafe schemes and accidental navigation.
      name.append(element("span", url, "feed-url"));
    }
    const settings = element("td", feed.is_active ? "Active" : "Inactive");
    settings.append(element("span", feed.skip_extraction ? "Extraction disabled" : "Extraction enabled", "subtext"));
    row.append(name, settings);
    for (const key of ["total", "with_content", "missing_content", "awaiting_extraction", "extraction_disabled", "retry_limit_reached", "not_eligible"]) {
      row.append(element("td", number(feed.articles[key])));
    }
    const log = feed.latest_fetch;
    const fetchCell = element("td");
    if (log) {
      const knownStatus = ["success", "error", "partial", "starting"].includes(log.status) ? log.status : "unknown";
      fetchCell.append(element("span", log.status, `status status-${knownStatus}`), element("span", date(log.timestamp), "fetch-time"));
    } else {
      fetchCell.append(element("span", "Never fetched", "muted"));
    }
    row.append(fetchCell,
      element("td", log ? number(log.entries_found) : "—"),
      element("td", log ? number(log.valid_entries_submitted) : "—"),
      element("td", log && log.duration_ms !== null ? `${number(log.duration_ms)} ms` : "—"),
      element("td", log?.error || "—", "fetch-error"));
    return row;
  });
  const jobs = data.scheduler.jobs.map((job) => {
    const item = element("div", undefined, "job");
    item.append(element("strong", job.name), element("span", `Next run: ${date(job.next_run_time)}`, "muted"));
    return item;
  });
  if (!jobs.length) jobs.push(element("p", "No scheduled jobs registered.", "muted"));

  byId("summary").replaceChildren(...cards);
  byId("backlog").replaceChildren(...backlog);
  byId("feeds").replaceChildren(...rows);
  byId("empty").hidden = data.feeds.length !== 0;
  byId("feed-count").textContent = `${number(data.feeds.length)} configured`;
  byId("scheduler-state").textContent = `Configured: ${data.scheduler.enabled ? "enabled" : "disabled"} · ${data.scheduler.scheduler_running ? "Running" : "Stopped"}`;
  byId("jobs").replaceChildren(...jobs);
  byId("updated").textContent = `Last successful refresh: ${date(data.snapshot_at)} · Times shown in your local timezone`;
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  byId("refresh").disabled = true;
  byId("refresh").textContent = "Refreshing…";
  try {
    const response = await fetch("/api/news/dashboard", { cache: "no-store", signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error(`Server returned HTTP ${response.status}`);
    render(await response.json());
    hasSnapshot = true;
    byId("error").hidden = true;
  } catch (error) {
    byId("error").textContent = `Refresh failed. ${hasSnapshot ? "Showing the last successful snapshot. " : ""}${error.message}`;
    byId("error").hidden = false;
    if (!hasSnapshot) byId("updated").textContent = "No snapshot loaded yet.";
  } finally {
    refreshing = false;
    byId("refresh").disabled = false;
    byId("refresh").textContent = "Refresh now";
  }
}

byId("refresh").addEventListener("click", refresh);
setInterval(() => { if (byId("auto-refresh").checked) refresh(); }, 30000);
refresh();
