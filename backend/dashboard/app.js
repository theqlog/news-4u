"use strict";

const byId = (id) => document.getElementById(id);
const number = (value) => new Intl.NumberFormat().format(value);
const date = (value) => value ? new Date(value).toLocaleString() : "Unavailable";
let refreshing = false;
let hasSnapshot = false;
const expandedDetails = new Set();

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function detailsBlock(key, label) {
  const details = element("details");
  details.id = key;
  details.open = expandedDetails.has(key);
  const summary = element("summary", label);
  summary.id = `${key}-summary`;
  details.append(summary);
  details.addEventListener("toggle", () => {
    if (details.open) expandedDetails.add(key);
    else expandedDetails.delete(key);
  });
  return details;
}

function fetchStatus(log) {
  const labels = { success: "Success", error: "Fetch error", partial: "Partial fetch", starting: "Fetch started" };
  const status = log?.status;
  const known = Object.hasOwn(labels, status);
  return element("span", log ? (known ? labels[status] : status) : "Never fetched", `status status-${known ? status : "unknown"}`);
}

function feedUrls(feed) {
  const urls = element("div", undefined, "feed-urls");
  for (const url of feed.urls) urls.append(element("span", url, "feed-url"));
  return urls;
}

function metric(label, value, attention = false) {
  const item = element("div", undefined, `feed-metric${attention && value > 0 ? " attention" : ""}${value === 0 ? " zero" : ""}`);
  item.append(element("dt", label), element("dd", number(value)));
  return item;
}

function mobileFeed(feed) {
  const log = feed.latest_fetch;
  const fetchError = log && (log.error || ["error", "partial"].includes(log.status));
  const card = element("article", undefined, `feed-card${fetchError ? " has-error" : feed.articles.missing_content > 0 ? " has-backlog" : ""}`);
  const header = element("div", undefined, "feed-card-heading");
  const identity = element("div");
  identity.append(element("h3", feed.name), element("span", feed.category || "Uncategorized", "category"));
  header.append(identity, element("span", feed.is_active ? "Active" : "Inactive", `pill${feed.is_active ? " active" : ""}`));
  const metrics = element("dl", undefined, "feed-primary-metrics");
  metrics.append(metric("Stored", feed.articles.total), metric("With content", feed.articles.with_content), metric("Missing", feed.articles.missing_content, true));
  const latest = element("div", undefined, "feed-latest");
  latest.append(fetchStatus(log));
  if (log) latest.append(element("span", date(log.timestamp), "fetch-time"));
  const details = detailsBlock(`feed-mobile-${feed.id}`, "Feed details");
  const secondary = element("dl", undefined, "feed-secondary-metrics");
  for (const [label, key] of [["Awaiting extraction", "awaiting_extraction"], ["Retry limit reached", "retry_limit_reached"], ["Extraction disabled", "extraction_disabled"], ["Not eligible", "not_eligible"]]) {
    secondary.append(metric(label, feed.articles[key], key === "awaiting_extraction" || key === "retry_limit_reached"));
  }
  const fetchMetrics = element("dl", undefined, "feed-secondary-metrics");
  for (const [label, value] of [["Entries found", log ? number(log.entries_found) : "—"], ["Valid entries submitted", log ? number(log.valid_entries_submitted) : "—"], ["Fetch duration", log?.duration_ms != null ? `${number(log.duration_ms)} ms` : "—"]]) {
    const item = element("div");
    item.append(element("dt", label), element("dd", value));
    fetchMetrics.append(item);
  }
  details.append(secondary, element("p", feed.skip_extraction ? "Content extraction disabled" : "Content extraction enabled", "muted"),
    element("h4", "Latest fetch"), fetchMetrics, element("h4", "RSS URLs"), feedUrls(feed));
  if (log?.error) details.append(element("h4", "Full fetch error"), element("p", log.error, "full-error"));
  card.append(header, metrics, latest);
  if (log?.error) card.append(element("p", log.error, "error-preview"));
  card.append(details);
  return card;
}

function render(data) {
  const focusedId = document.activeElement?.id;
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
    ["Awaiting extraction", "awaiting_extraction"], ["Retry limit reached", "retry_limit_reached"],
    ["Extraction disabled", "extraction_disabled"], ["Not eligible · missing feed / link", "not_eligible"],
  ].map(([label, key]) => {
    const attention = summary[key] > 0 && ["awaiting_extraction", "retry_limit_reached"].includes(key);
    const item = element("div", undefined, `backlog-item${attention ? " attention" : ""}`);
    item.append(element("strong", number(summary[key])), element("span", label));
    return item;
  });
  const rows = data.feeds.map((feed) => {
    const row = element("tr");
    const name = element("td");
    name.append(element("strong", feed.name, "feed-name"), element("span", feed.category || "Uncategorized", "category"));
    const urls = detailsBlock(`feed-desktop-${feed.id}-urls`, `RSS URLs (${feed.urls.length})`);
    urls.append(feedUrls(feed));
    name.append(urls);
    const settings = element("td", feed.is_active ? "Active" : "Inactive");
    settings.append(element("span", feed.skip_extraction ? "Extraction disabled" : "Extraction enabled", "subtext"));
    row.append(name, settings);
    for (const key of ["total", "with_content", "missing_content", "awaiting_extraction", "extraction_disabled", "retry_limit_reached", "not_eligible"]) {
      row.append(element("td", number(feed.articles[key]), feed.articles[key] === 0 ? "zero" : key === "missing_content" ? "attention" : ""));
    }
    const log = feed.latest_fetch;
    const fetchCell = element("td");
    if (log) {
      fetchCell.append(fetchStatus(log), element("span", date(log.timestamp), "fetch-time"));
    } else {
      fetchCell.append(element("span", "Never fetched", "muted"));
    }
    const errorCell = element("td", log?.error ? undefined : "—", "fetch-error");
    if (log?.error) {
      const error = detailsBlock(`feed-desktop-${feed.id}-error`, "View fetch error");
      error.append(element("p", log.error, "full-error"));
      errorCell.append(element("p", log.error, "error-preview"), error);
    }
    row.append(fetchCell,
      element("td", log ? number(log.entries_found) : "—"),
      element("td", log ? number(log.valid_entries_submitted) : "—"),
      element("td", log && log.duration_ms !== null ? `${number(log.duration_ms)} ms` : "—"),
      errorCell);
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
  byId("feed-cards").replaceChildren(...data.feeds.map(mobileFeed));
  const fetchErrors = data.feeds.filter((feed) => feed.latest_fetch && (feed.latest_fetch.error || ["error", "partial"].includes(feed.latest_fetch.status))).length;
  byId("fetch-issues").textContent = fetchErrors ? `${number(fetchErrors)} ${fetchErrors === 1 ? "feed has" : "feeds have"} a fetch error or partial result. See feed details below.` : "No fetch errors in the latest feed results.";
  byId("fetch-issues").className = `fetch-issues${fetchErrors ? " attention" : ""}`;
  byId("empty").hidden = data.feeds.length !== 0;
  byId("feed-count").textContent = `${number(data.feeds.length)} configured`;
  byId("scheduler-state").textContent = `Configured: ${data.scheduler.enabled ? "enabled" : "disabled"} · ${data.scheduler.scheduler_running ? "Running" : "Stopped"}`;
  byId("jobs").replaceChildren(...jobs);
  byId("updated").textContent = `Last successful refresh: ${date(data.snapshot_at)} · Times shown in your local timezone`;
  // Automatic refresh must not drop keyboard focus from an expanded feed summary.
  if (focusedId?.startsWith("feed-")) byId(focusedId)?.focus({ preventScroll: true });
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
