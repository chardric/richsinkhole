"use strict";

// Sub-path prefix injected by the server (e.g. "/richsinkhole" when behind nginx).
// Falls back to "" for direct access on :8080.
const BASE = (window.BASE_PATH || "").replace(/\/$/, "");

// ============================================================
// API helper
// ============================================================
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, opts);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(data?.detail || `HTTP ${res.status}`);
  }
  return data;
}

// ============================================================
// Toast notifications
// ============================================================
function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  const colors = { success: "#238636", danger: "#da3633", warning: "#9e6a03", info: "#1f6feb" };
  const toast = document.createElement("div");
  toast.className = "toast show align-items-center border-0 mb-2";
  toast.style.background = colors[type] || colors.info;
  toast.innerHTML = `
    <div class="d-flex">
      <div class="toast-body text-white fw-semibold">${escHtml(message)}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
  toast.querySelector("button").addEventListener("click", () => toast.remove());
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ============================================================
// Stats
// ============================================================
let statsTimer = null;

async function loadStats() {
  try {
    const d = await api("GET", "/api/stats");
    document.getElementById("stat-total").textContent = d.total.toLocaleString();
    document.getElementById("stat-forwarded").textContent = d.forwarded.toLocaleString();
    document.getElementById("stat-blocked").textContent = d.blocked.toLocaleString();
    document.getElementById("stat-pct").textContent = d.block_pct + "%";
    document.getElementById("stat-redirected").textContent = d.redirected.toLocaleString();
    // Settings tab mirror
    document.getElementById("settings-bl-count").textContent = d.total_blocked_domains.toLocaleString();

    renderTopList("top-blocked-list", d.top_blocked_domains, "domain", "count", d.blocked || 1);
    renderTopList("top-clients-list", d.top_clients, "ip", "count", d.total || 1);

    document.getElementById("last-refreshed").textContent =
      "Updated " + new Date().toLocaleTimeString();
  } catch (e) {
    console.error("Stats error:", e);
  }
}

function renderTopList(elId, items, labelKey, countKey, maxVal) {
  const el = document.getElementById(elId);
  if (!items || !items.length) {
    el.innerHTML = '<div class="text-muted small text-center py-2">No data yet</div>';
    return;
  }
  const topCount = items[0][countKey] || 1;
  el.innerHTML = items.map((item, i) => `
    <div class="d-flex align-items-center gap-2 mb-2">
      <span class="text-muted small" style="width:16px;text-align:right">${i + 1}</span>
      <span class="font-monospace small text-truncate flex-grow-1" style="max-width:220px"
        title="${escHtml(item[labelKey])}">${escHtml(item[labelKey])}</span>
      <div class="progress flex-grow-1" style="min-width:60px">
        <div class="progress-bar bg-danger" style="width:${Math.round(item[countKey] / topCount * 100)}%"></div>
      </div>
      <span class="text-muted small" style="width:40px;text-align:right">${item[countKey]}</span>
    </div>`).join("");
}

// ============================================================
// Live log (SSE)
// ============================================================
const MAX_LOG_ROWS = 200;
let logPaused = false;
let logCount = 0;
let eventSource = null;

function connectSSE() {
  if (eventSource) eventSource.close();
  setSSEStatus(false);

  eventSource = new EventSource(BASE + "/api/logs/stream");

  eventSource.onopen = () => setSSEStatus(true);
  eventSource.onerror = () => {
    setSSEStatus(false);
    setTimeout(connectSSE, 3000);
  };
  eventSource.onmessage = (e) => {
    if (logPaused) return;
    try {
      prependLogRow(JSON.parse(e.data));
    } catch (_) {}
  };
}

function setSSEStatus(connected) {
  const dot = document.getElementById("sse-dot");
  dot.classList.toggle("disconnected", !connected);
}

async function preloadLog() {
  try {
    const rows = await api("GET", "/api/logs?limit=50");
    // rows are newest-first from the REST API
    rows.reverse(); // oldest first so prepend makes newest appear at top
    rows.forEach(prependLogRow);
  } catch (_) {}
}

function prependLogRow(entry) {
  const tbody = document.getElementById("log-tbody");
  const empty = document.getElementById("log-empty");
  empty.style.display = "none";

  const tr = document.createElement("tr");
  const badgeClass = { blocked: "badge-blocked", allowed: "badge-forwarded", forwarded: "badge-forwarded", redirected: "badge-redirected", failed: "badge-failed" }[entry.action] || "badge-forwarded";
  tr.innerHTML = `
    <td class="ps-3 text-muted small font-monospace">${escHtml(entry.ts.slice(11))}</td>
    <td class="font-monospace small">${escHtml(entry.client_ip)}</td>
    <td class="font-monospace small text-truncate" style="max-width:300px" title="${escHtml(entry.domain)}">${escHtml(entry.domain)}</td>
    <td class="small text-muted">${escHtml(entry.qtype)}</td>
    <td class="pe-3">
      <span class="badge ${badgeClass}">${escHtml(entry.action)}</span>
    </td>`;
  tbody.insertBefore(tr, tbody.firstChild);

  logCount++;
  document.getElementById("log-count").textContent = `${logCount} entries`;

  // Cap rows to avoid memory leak
  while (tbody.rows.length > MAX_LOG_ROWS) {
    tbody.deleteRow(tbody.rows.length - 1);
  }
}

// ============================================================
// Blocklist
// ============================================================
// Quick-block presets
// ============================================================
async function loadPresetStatus() {
  const toggles = document.querySelectorAll(".preset-toggle");
  const domains = [...toggles].map(t => t.dataset.domain);
  try {
    const status = await api("POST", "/api/blocklist/check", { domains });
    toggles.forEach(t => { t.checked = !!status[t.dataset.domain]; });
    updatePresetCounts();
  } catch (_) {}
}

function updatePresetCounts() {
  const groups = { ads: "qb-ads", tracking: "qb-tracking", telemetry: "qb-telemetry", social: "qb-social" };
  Object.entries(groups).forEach(([, collapseId]) => {
    const section = document.getElementById(collapseId);
    if (!section) return;
    const toggles = section.querySelectorAll(".preset-toggle");
    const blocked = [...toggles].filter(t => t.checked).length;
    const countEl = document.getElementById(collapseId + "-count");
    if (countEl) {
      countEl.textContent = `${blocked}/${toggles.length} blocked`;
      countEl.className = "badge ms-auto me-2 qb-count " + (blocked > 0 ? "bg-danger" : "bg-secondary");
    }
  });
}

async function togglePreset(toggle) {
  const domain = toggle.dataset.domain;
  const enabling = toggle.checked;
  toggle.disabled = true;
  try {
    if (enabling) {
      await api("POST", "/api/blocklist", { domain });
      showToast(`Blocked: ${domain}`, "success");
    } else {
      await api("DELETE", `/api/blocklist/${domain}`);
      showToast(`Unblocked: ${domain}`, "info");
    }
    updatePresetCounts();
  } catch (err) {
    toggle.checked = !enabling; // revert
    showToast(err.message, "danger");
  } finally {
    toggle.disabled = false;
  }
}

// ============================================================
// Updater
// ============================================================
let sourcesData = { sources: [], whitelist: [], update_interval_hours: 24 };

async function loadUpdaterStatus() {
  try {
    const s = await api("GET", "/api/updater/status");
    document.getElementById("upd-last-updated").textContent = s.last_updated || "Never";
    document.getElementById("upd-total-domains").textContent = (s.total_domains || 0).toLocaleString();
    document.getElementById("upd-added").textContent = "+" + (s.domains_added || 0).toLocaleString();
    const badgeColor = { ok: "bg-success", never_run: "bg-secondary" }[s.status] || "bg-danger";
    document.getElementById("upd-status").innerHTML =
      `<span class="badge ${badgeColor}">${escHtml(s.status || "unknown")}</span>`;
  } catch (_) {
    document.getElementById("upd-status").innerHTML =
      `<span class="badge bg-secondary">offline</span>`;
  }
}

async function loadSources() {
  try {
    sourcesData = await api("GET", "/api/updater/sources");
    renderSources();
  } catch (_) {
    document.getElementById("sources-list").innerHTML =
      `<div class="text-muted small">Updater not available</div>`;
  }
}

function renderSources() {
  const el = document.getElementById("sources-list");
  const urls = sourcesData.sources || [];
  if (!urls.length) {
    el.innerHTML = `<div class="text-muted small">No sources configured.</div>`;
    return;
  }
  el.innerHTML = urls.map(url => `
    <div class="d-flex align-items-center gap-2 mb-1">
      <span class="font-monospace small text-truncate flex-grow-1" title="${escHtml(url)}">${escHtml(url)}</span>
      <button class="btn btn-sm btn-outline-danger py-0 flex-shrink-0 btn-remove-source"
        data-url="${escHtml(url)}">&#x2715;</button>
    </div>`).join("");

  el.querySelectorAll(".btn-remove-source").forEach(btn => {
    btn.addEventListener("click", async () => {
      const url = btn.dataset.url;
      sourcesData.sources = sourcesData.sources.filter(s => s !== url);
      try {
        await api("POST", "/api/updater/sources", sourcesData);
        renderSources();
        showToast("Source removed", "success");
      } catch (e) {
        showToast("Remove failed: " + e.message, "danger");
      }
    });
  });
}

async function triggerUpdate() {
  try {
    await api("POST", "/api/updater/run", {});
    showToast("Update triggered — status refreshes in ~60s", "info");
  } catch (e) {
    showToast("Failed to trigger update: " + e.message, "danger");
  }
}

// ============================================================
// Settings
// ============================================================
async function loadSettings() {
  try {
    const cfg = await api("GET", "/api/settings");
    document.getElementById("yt-enabled").checked = cfg.youtube_redirect_enabled || false;
    document.getElementById("cp-enabled").checked = cfg.captive_portal_enabled || false;
    const serverIp = cfg.server_ip || "—";
    document.getElementById("yt-ip-display").textContent = serverIp;
    document.getElementById("info-server-ip").textContent = serverIp;
    const upstream = cfg.upstream_dns || "";
    const labels = { "unbound": "unbound (local)", "1.1.1.1": "1.1.1.1 (Cloudflare)", "8.8.8.8": "8.8.8.8 (Google)", "9.9.9.9": "9.9.9.9 (Quad9)" };
    document.getElementById("info-upstream-dns").textContent = labels[upstream] || upstream || "—";
  } catch (e) {
    showToast("Failed to load settings: " + e.message, "danger");
  }
}

async function saveSettings() {
  const btn = document.getElementById("btn-save-settings");
  const status = document.getElementById("settings-save-status");
  btn.disabled = true;
  status.textContent = "";
  try {
    await api("POST", "/api/settings", {
      youtube_redirect_enabled: document.getElementById("yt-enabled").checked,
      captive_portal_enabled: document.getElementById("cp-enabled").checked,
    });
    showToast("Settings saved — DNS server will reload within 30s", "success");
    status.textContent = "Saved ✓";
    setTimeout(() => { status.textContent = ""; }, 4000);
  } catch (e) {
    showToast("Save failed: " + e.message, "danger");
  } finally {
    btn.disabled = false;
  }
}

// ============================================================
// Health check
// ============================================================
async function loadHealth() {
  try {
    const d = await api("GET", "/health");
    const dot = document.getElementById("health-dot");
    const label = document.getElementById("health-label");
    const ok = d.status === "ok";
    dot.className = "health-dot" + (ok ? "" : " degraded");
    label.textContent = ok ? "healthy" : "degraded";

    // Build tooltip
    const details = Object.entries(d)
      .filter(([k]) => k !== "status")
      .map(([k, v]) => `${k}: ${v}`)
      .join("\n");
    document.getElementById("health-badge").title = details;
  } catch (_) {
    const dot = document.getElementById("health-dot");
    dot.className = "health-dot unknown";
    document.getElementById("health-label").textContent = "offline";
  }
}

// ============================================================
// Event bindings
// ============================================================
function bindEvents() {
  // Pause/resume log
  document.getElementById("btn-pause").addEventListener("click", function () {
    logPaused = !logPaused;
    this.textContent = logPaused ? "Resume" : "Pause";
    this.classList.toggle("btn-outline-secondary", !logPaused);
    this.classList.toggle("btn-warning", logPaused);
  });

  // Clear log
  document.getElementById("btn-clear-log").addEventListener("click", () => {
    document.getElementById("log-tbody").innerHTML = "";
    document.getElementById("log-empty").style.display = "";
    logCount = 0;
    document.getElementById("log-count").textContent = "0 entries";
  });

  // Preset domain toggles
  document.querySelectorAll(".preset-toggle").forEach(toggle => {
    toggle.addEventListener("change", () => togglePreset(toggle));
  });

  // Tab switch: load updater info + preset status when Blocklist tab is shown
  document.getElementById("tab-bl-btn").addEventListener("shown.bs.tab", () => {
    loadUpdaterStatus();
    loadSources();
    loadPresetStatus();
  });

  // Update Now button
  document.getElementById("btn-update-now").addEventListener("click", triggerUpdate);

  // Add source form — validate then save
  document.getElementById("form-add-source").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("input-source-url");
    const url = input.value.trim();
    if (!url) return;
    const btn = e.target.querySelector("button[type=submit]");
    btn.disabled = true;
    btn.textContent = "Validating…";
    try {
      const check = await api("POST", "/api/updater/sources/validate", { url });
      if (!check.valid) {
        showToast("Invalid source: " + check.error, "danger");
        return;
      }
      sourcesData.sources = [...(sourcesData.sources || []), url];
      try {
        await api("POST", "/api/updater/sources", sourcesData);
        input.value = "";
        renderSources();
        showToast(`Source added — ${check.domains_found.toLocaleString()} domains found`, "success");
      } catch (err) {
        sourcesData.sources = sourcesData.sources.filter(s => s !== url);
        showToast("Save failed: " + err.message, "danger");
      }
    } catch (err) {
      showToast("Validation failed: " + err.message, "danger");
    } finally {
      btn.disabled = false;
      btn.textContent = "Add";
    }
  });

  // Tab switch: load settings when Settings tab is shown
  document.getElementById("tab-settings-btn").addEventListener("shown.bs.tab", loadSettings);

  // Settings form save
  document.getElementById("form-settings").addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveSettings();
  });
}

// ============================================================
// Init
// ============================================================
document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await preloadLog();
  connectSSE();
  await loadStats();
  statsTimer = setInterval(loadStats, 30000);
  await loadHealth();
  setInterval(loadHealth, 30000);
});
