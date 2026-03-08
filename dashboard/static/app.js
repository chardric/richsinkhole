/*
 * Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
 * Developed by: Richard R. Ayuyang, PhD
 *               Professor II, CSU
 * All rights reserved.
 */

"use strict";

// Sub-path prefix injected by the server (e.g. "/richsinkhole" when behind nginx).
// Falls back to "" for direct access on :8080.
const BASE = (window.BASE_PATH || "").replace(/\/$/, "");

// ============================================================
// Generic sortable table
// ============================================================
function initSortable(thead) {
  thead.querySelectorAll("th[data-col]").forEach(th => {
    th.addEventListener("click", () => {
      const tbody = thead.closest("table").querySelector("tbody");
      const col   = parseInt(th.dataset.col);
      const asc   = !th.classList.contains("sort-asc");
      thead.querySelectorAll("th[data-col]").forEach(t => t.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(asc ? "sort-asc" : "sort-desc");
      Array.from(tbody.querySelectorAll("tr"))
        .sort((a, b) => {
          const av = a.cells[col]?.dataset.sort ?? a.cells[col]?.textContent.trim() ?? "";
          const bv = b.cells[col]?.dataset.sort ?? b.cells[col]?.textContent.trim() ?? "";
          const an = parseFloat(av), bn = parseFloat(bv);
          if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
          return asc ? av.localeCompare(bv) : bv.localeCompare(av);
        })
        .forEach(r => tbody.appendChild(r));
    });
  });
}

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
// Currency detection + live exchange rate
// ============================================================
const TZ_CURRENCY = {
  // Asia-Pacific
  "Asia/Manila":         "PHP", "Asia/Singapore":      "SGD",
  "Asia/Kuala_Lumpur":   "MYR", "Asia/Jakarta":        "IDR",
  "Asia/Makassar":       "IDR", "Asia/Jayapura":       "IDR",
  "Asia/Bangkok":        "THB", "Asia/Phnom_Penh":     "KHR",
  "Asia/Vientiane":      "LAK", "Asia/Rangoon":        "MMK",
  "Asia/Colombo":        "LKR", "Asia/Kolkata":        "INR",
  "Asia/Karachi":        "PKR", "Asia/Dhaka":          "BDT",
  "Asia/Kathmandu":      "NPR", "Asia/Thimphu":        "BTN",
  "Asia/Tokyo":          "JPY", "Asia/Seoul":          "KRW",
  "Asia/Shanghai":       "CNY", "Asia/Hong_Kong":      "HKD",
  "Asia/Taipei":         "TWD", "Asia/Macau":          "MOP",
  "Asia/Ho_Chi_Minh":    "VND", "Asia/Ulaanbaatar":    "MNT",
  "Asia/Dubai":          "AED", "Asia/Riyadh":         "SAR",
  "Asia/Tehran":         "IRR", "Asia/Baghdad":        "IQD",
  "Asia/Kuwait":         "KWD", "Asia/Qatar":          "QAR",
  "Asia/Bahrain":        "BHD", "Asia/Muscat":         "OMR",
  "Asia/Beirut":         "LBP", "Asia/Jerusalem":      "ILS",
  "Asia/Amman":          "JOD", "Asia/Nicosia":        "EUR",
  "Asia/Tbilisi":        "GEL", "Asia/Yerevan":        "AMD",
  "Asia/Baku":           "AZN", "Asia/Tashkent":       "UZS",
  "Asia/Almaty":         "KZT",
  // Australia / Pacific
  "Australia/Sydney":    "AUD", "Australia/Melbourne": "AUD",
  "Australia/Brisbane":  "AUD", "Australia/Perth":     "AUD",
  "Australia/Adelaide":  "AUD", "Australia/Darwin":    "AUD",
  "Pacific/Auckland":    "NZD", "Pacific/Fiji":        "FJD",
  "Pacific/Port_Moresby":"PGK", "Pacific/Honolulu":    "USD",
  // Europe
  "Europe/London":       "GBP", "Europe/Dublin":       "EUR",
  "Europe/Berlin":       "EUR", "Europe/Paris":        "EUR",
  "Europe/Rome":         "EUR", "Europe/Madrid":       "EUR",
  "Europe/Lisbon":       "EUR", "Europe/Amsterdam":    "EUR",
  "Europe/Brussels":     "EUR", "Europe/Vienna":       "EUR",
  "Europe/Athens":       "EUR", "Europe/Helsinki":     "EUR",
  "Europe/Tallinn":      "EUR", "Europe/Riga":         "EUR",
  "Europe/Vilnius":      "EUR", "Europe/Luxembourg":   "EUR",
  "Europe/Malta":        "EUR", "Europe/Ljubljana":    "EUR",
  "Europe/Bratislava":   "EUR", "Europe/Nicosia":      "EUR",
  "Europe/Warsaw":       "PLN", "Europe/Stockholm":    "SEK",
  "Europe/Oslo":         "NOK", "Europe/Copenhagen":   "DKK",
  "Europe/Zurich":       "CHF", "Europe/Prague":       "CZK",
  "Europe/Budapest":     "HUF", "Europe/Bucharest":    "RON",
  "Europe/Sofia":        "BGN", "Europe/Zagreb":       "EUR",
  "Europe/Belgrade":     "RSD", "Europe/Sarajevo":     "BAM",
  "Europe/Skopje":       "MKD", "Europe/Tirane":       "ALL",
  "Europe/Moscow":       "RUB", "Europe/Kyiv":         "UAH",
  "Europe/Minsk":        "BYN", "Europe/Chisinau":     "MDL",
  "Europe/Istanbul":     "TRY", "Europe/Reykjavik":    "ISK",
  // Americas
  "America/New_York":    "USD", "America/Chicago":     "USD",
  "America/Denver":      "USD", "America/Los_Angeles": "USD",
  "America/Phoenix":     "USD", "America/Anchorage":   "USD",
  "America/Toronto":     "CAD", "America/Vancouver":   "CAD",
  "America/Winnipeg":    "CAD", "America/Halifax":     "CAD",
  "America/Sao_Paulo":   "BRL", "America/Manaus":      "BRL",
  "America/Mexico_City": "MXN", "America/Buenos_Aires":"ARS",
  "America/Bogota":      "COP", "America/Lima":        "PEN",
  "America/Santiago":    "CLP", "America/Caracas":     "VES",
  "America/La_Paz":      "BOB", "America/Asuncion":    "PYG",
  "America/Montevideo":  "UYU", "America/Guayaquil":   "USD",
  "America/Panama":      "USD", "America/Costa_Rica":  "CRC",
  "America/Guatemala":   "GTQ", "America/Tegucigalpa": "HNL",
  "America/Managua":     "NIO", "America/El_Salvador":  "USD",
  "America/Santo_Domingo":"DOP","America/Port-au-Prince":"HTG",
  "America/Jamaica":     "JMD", "America/Nassau":      "BSD",
  "America/Havana":      "CUP", "America/Puerto_Rico": "USD",
  // Africa
  "Africa/Cairo":        "EGP", "Africa/Algiers":      "DZD",
  "Africa/Tunis":        "TND", "Africa/Casablanca":   "MAD",
  "Africa/Lagos":        "NGN", "Africa/Accra":        "GHS",
  "Africa/Abidjan":      "XOF", "Africa/Dakar":        "XOF",
  "Africa/Johannesburg": "ZAR", "Africa/Nairobi":      "KES",
  "Africa/Addis_Ababa":  "ETB", "Africa/Dar_es_Salaam":"TZS",
  "Africa/Kampala":      "UGX", "Africa/Kigali":       "RWF",
  "Africa/Kinshasa":     "CDF", "Africa/Luanda":       "AOA",
  "Africa/Lusaka":       "ZMW", "Africa/Harare":       "ZWL",
  "Africa/Maputo":       "MZN", "Africa/Antananarivo": "MGA",
};

let _localCurrency  = "USD";
let _exchangeRate   = 1.0;
let _currencyInited = false;

async function _initCurrency() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  _localCurrency = TZ_CURRENCY[tz] || "USD";
  if (_localCurrency === "USD") { _currencyInited = true; return; }

  const CACHE_KEY = "rs_fx_" + _localCurrency;
  const CACHE_TTL = 86400 * 1000;   // 24 hours
  try {
    const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
    if (cached && Date.now() - cached.ts < CACHE_TTL) {
      _exchangeRate = cached.rate;
      _currencyInited = true;
      return;
    }
  } catch (_) {}

  try {
    const res  = await fetch("https://open.er-api.com/v6/latest/USD");
    const data = await res.json();
    if (data.result === "success" && data.rates[_localCurrency]) {
      _exchangeRate = data.rates[_localCurrency];
      localStorage.setItem(CACHE_KEY, JSON.stringify({ rate: _exchangeRate, ts: Date.now() }));
    } else {
      _localCurrency = "USD"; _exchangeRate = 1.0;
    }
  } catch (_) {
    // Offline / API unreachable — stay in USD
    _localCurrency = "USD"; _exchangeRate = 1.0;
  }
  _currencyInited = true;
}

function formatRevenue(usdAmount) {
  const local = usdAmount * _exchangeRate;
  const noDecimals = ["JPY", "KRW", "VND", "IDR", "UGX", "RWF", "MGA", "CLP", "PYG"];
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: _localCurrency,
    minimumFractionDigits: noDecimals.includes(_localCurrency) ? 0 : 2,
    maximumFractionDigits: noDecimals.includes(_localCurrency) ? 0 : 2,
  }).format(local);
}

// ============================================================
// Stats
// ============================================================
let statsTimer = null;

function _renderStats(d) {
  animateCounter(document.getElementById("stat-total"),     d.total);
  animateCounter(document.getElementById("stat-forwarded"),  d.forwarded);
  animateCounter(document.getElementById("stat-blocked"),    d.blocked);
  document.getElementById("stat-pct").textContent = d.block_pct + "%";
  animateCounter(document.getElementById("stat-redirected"), d.redirected);

  const bw = d.bandwidth_saved_mb || 0;
  document.getElementById("stat-bandwidth").textContent =
    bw >= 1024 ? (bw / 1024).toFixed(1) + " GB" : bw.toFixed(1) + " MB";
  const tm = d.time_saved_min || 0;
  document.getElementById("stat-timesaved").textContent =
    tm >= 60 ? (tm / 60).toFixed(1) + " hr" : tm.toFixed(1) + " min";

  document.getElementById("stat-ad-revenue").textContent = formatRevenue(d.ad_revenue_denied || 0);

  const blockedCard = document.getElementById("stat-blocked").closest(".stat-card");
  if (blockedCard) blockedCard.classList.toggle("stat-card--hot", d.blocked > 0);

  document.getElementById("settings-bl-count").textContent = d.total_blocked_domains.toLocaleString();
  renderTopList("top-blocked-list", d.top_blocked_domains, "domain", "count", d.blocked || 1);
  renderTopList("top-clients-list", d.top_clients, "ip", "count", d.total || 1);
  document.getElementById("last-refreshed").textContent = "Updated " + new Date().toLocaleTimeString();
}

async function loadStats() {
  // Show cached data instantly so the UI is never blank
  try {
    const cached = localStorage.getItem("rs_stats");
    if (cached) _renderStats(JSON.parse(cached));
  } catch (_) {}

  try {
    const d = await api("GET", "/api/stats");
    localStorage.setItem("rs_stats", JSON.stringify(d));
    _renderStats(d);
  } catch (e) {
    console.error("Stats error:", e);
  }
}

// ============================================================
// Animated counter
// ============================================================
function animateCounter(el, target, fmt) {
  const from = parseFloat(el.dataset.rawVal) || 0;
  el.dataset.rawVal = target;
  if (from === target) { el.textContent = fmt ? fmt(target) : Math.round(target).toLocaleString(); return; }
  const start = performance.now(), dur = 700;
  (function step(now) {
    const t = Math.min((now - start) / dur, 1);
    const ease = 1 - Math.pow(1 - t, 3);
    const cur = from + (target - from) * ease;
    el.textContent = fmt ? fmt(cur) : Math.round(cur).toLocaleString();
    if (t < 1) requestAnimationFrame(step);
  })(performance.now());
}

// ============================================================
// Activity bar flash (SSE pulse)
// ============================================================
function flashActivityBar() {
  const bar = document.getElementById("activity-bar");
  if (!bar) return;
  bar.style.opacity = "1";
  bar.style.transform = "scaleX(1)";
  clearTimeout(bar._t);
  bar._t = setTimeout(() => { bar.style.opacity = "0"; bar.style.transform = "scaleX(0)"; }, 350);
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
  const ACTION_META = {
    blocked:   { cls: "badge-blocked",   label: "Blocked"         },
    forwarded: { cls: "badge-forwarded", label: "Forwarded"       },
    allowed:   { cls: "badge-forwarded", label: "Forwarded"       },
    cached:    { cls: "badge-cached",    label: "Cached"          },
    youtube:   { cls: "badge-youtube",   label: "YouTube"         },
    captive:   { cls: "badge-captive",   label: "Captive Portal"  },
    redirected:{ cls: "badge-captive",   label: "Redirected"      },
    failed:    { cls: "badge-failed",    label: "Failed"          },
    nxdomain:  { cls: "badge-failed",    label: "NXDOMAIN"        },
    ratelimited:{ cls: "badge-failed",   label: "Rate Limited"    },
    rebinding: { cls: "badge-blocked",   label: "Rebinding"       },
    scheduled: { cls: "badge-captive",   label: "Scheduled"       },
  };
  const meta = ACTION_META[entry.action] || { cls: "badge-forwarded", label: entry.action };
  const detail = (() => {
    const parts = [];
    if (entry.upstream) parts.push(escHtml(entry.upstream));
    if (entry.response_ms != null) parts.push(entry.response_ms + "ms");
    return parts.length ? `<div class="text-muted" style="font-size:0.68rem;margin-top:1px">${parts.join(" · ")}</div>` : "";
  })();
  tr.innerHTML = `
    <td class="ps-3 text-muted small font-monospace">${escHtml(entry.ts.slice(11))}</td>
    <td class="font-monospace small">${escHtml(entry.client_ip)}</td>
    <td class="font-monospace small text-truncate" style="max-width:300px" title="${escHtml(entry.domain)}">${escHtml(entry.domain)}</td>
    <td class="small text-muted">${escHtml(entry.qtype)}</td>
    <td class="pe-3"><span class="badge ${meta.cls}">${meta.label}</span>${detail}</td>`;
  tbody.insertBefore(tr, tbody.firstChild);
  flashActivityBar();

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
  const groups = { ads: "qb-ads", tracking: "qb-tracking", telemetry: "qb-telemetry", social: "qb-social", malware: "qb-malware", gambling: "qb-gambling" };
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
// YouTube auto-blocked CDN nodes
// ============================================================
async function loadYTAutoBlocked() {
  const body = document.getElementById("yt-autoblocked-body");
  try {
    const r = await api("GET", "/api/blocklist/yt-autoblocked");
    if (!r.domains.length) {
      body.innerHTML = '<div class="text-muted small text-center py-2">No YouTube ad CDN nodes detected yet. Browse YouTube on your network — ad delivery nodes will be identified and blocked automatically.</div>';
      return;
    }
    body.innerHTML = `
      <div class="text-muted small mb-2">${r.total} node${r.total !== 1 ? "s" : ""} auto-blocked</div>
      <div class="font-monospace small" style="max-height:160px;overflow-y:auto;background:#0d1117;border-radius:4px;padding:8px">
        ${r.domains.map(d => `<div class="text-muted">${escHtml(d.domain)}</div>`).join("")}
      </div>`;
  } catch (_) {
    body.innerHTML = '<div class="text-muted small text-center py-2">Could not load YouTube CDN nodes.</div>';
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
async function loadNtpStatus() {
  try {
    const d = await api("GET", "/api/ntp/status");
    document.getElementById("ntp-enabled").checked = d.running;
  } catch (_) {}
}

async function loadSettings() {
  try {
    const cfg = await api("GET", "/api/settings");
    document.getElementById("yt-enabled").checked = cfg.youtube_redirect_enabled || false;
    document.getElementById("cp-enabled").checked = cfg.captive_portal_enabled || false;
    loadNtpStatus();
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
  const status = document.getElementById("settings-save-status");
  status.textContent = "Saving…";
  try {
    await api("POST", "/api/settings", {
      youtube_redirect_enabled: document.getElementById("yt-enabled").checked,
      captive_portal_enabled:   document.getElementById("cp-enabled").checked,
    });
    status.textContent = "Saved ✓";
    setTimeout(() => { status.textContent = ""; }, 3000);
  } catch (e) {
    status.textContent = "Failed";
    showToast("Save failed: " + e.message, "danger");
    setTimeout(() => { status.textContent = ""; }, 4000);
  }
}

// ============================================================
// Email notifications settings
// ============================================================
async function loadEmailSettings() {
  try {
    const cfg = await api("GET", "/api/settings/email");
    document.getElementById("email-enabled").checked         = cfg.enabled;
    document.getElementById("email-host").value              = cfg.smtp_host;
    document.getElementById("email-port").value              = cfg.smtp_port;
    document.getElementById("email-tls").checked             = cfg.tls;
    document.getElementById("email-user").value              = cfg.smtp_user;
    document.getElementById("email-password").value          = cfg.smtp_password;
    document.getElementById("email-from").value              = cfg.from_addr;
    document.getElementById("email-to").value                = cfg.to_addr;
    document.getElementById("email-notify-security").checked = cfg.notify_security;
    document.getElementById("email-notify-update").checked   = cfg.notify_update;
    document.getElementById("email-notify-daily").checked    = cfg.notify_daily;
    document.getElementById("email-daily-hour").value        = cfg.daily_hour;
  } catch (e) {
    showToast("Failed to load email settings: " + e.message, "danger");
  }
}

async function saveEmailSettings() {
  const btn = document.querySelector("#form-email-settings button[type=submit]");
  const status = document.getElementById("email-save-status");
  btn.disabled = true;
  status.textContent = "";
  try {
    await api("POST", "/api/settings/email", {
      enabled:          document.getElementById("email-enabled").checked,
      smtp_host:        document.getElementById("email-host").value.trim(),
      smtp_port:        parseInt(document.getElementById("email-port").value, 10),
      tls:              document.getElementById("email-tls").checked,
      smtp_user:        document.getElementById("email-user").value.trim(),
      smtp_password:    document.getElementById("email-password").value,
      from_addr:        document.getElementById("email-from").value.trim(),
      to_addr:          document.getElementById("email-to").value.trim(),
      notify_security:  document.getElementById("email-notify-security").checked,
      notify_update:    document.getElementById("email-notify-update").checked,
      notify_daily:     document.getElementById("email-notify-daily").checked,
      daily_hour:       parseInt(document.getElementById("email-daily-hour").value, 10),
    });
    showToast("Email settings saved", "success");
    status.textContent = "Saved ✓";
    setTimeout(() => { status.textContent = ""; }, 4000);
  } catch (e) {
    showToast("Save failed: " + e.message, "danger");
  } finally {
    btn.disabled = false;
  }
}

// ============================================================
// Rate limit settings
// ============================================================
async function loadRateLimits() {
  try {
    const cfg = await api("GET", "/api/settings/rate-limits");
    document.getElementById("rl-rate-window").value   = cfg.rate_window;
    document.getElementById("rl-rate-max").value      = cfg.rate_max;
    document.getElementById("rl-block-duration").value = cfg.block_duration;
    document.getElementById("rl-burst-normal").value  = cfg.burst_max_normal;
    document.getElementById("rl-burst-iot").value     = cfg.burst_max_iot;
  } catch (e) {
    showToast("Failed to load rate limit settings: " + e.message, "danger");
  }
}

async function saveRateLimits() {
  const btn    = document.getElementById("btn-save-rate-limits");
  const status = document.getElementById("rl-save-status");
  btn.disabled = true;
  status.textContent = "Saving…";
  try {
    await api("POST", "/api/settings/rate-limits", {
      rate_window:      parseInt(document.getElementById("rl-rate-window").value, 10),
      rate_max:         parseInt(document.getElementById("rl-rate-max").value, 10),
      block_duration:   parseInt(document.getElementById("rl-block-duration").value, 10),
      burst_max_normal: parseInt(document.getElementById("rl-burst-normal").value, 10),
      burst_max_iot:    parseInt(document.getElementById("rl-burst-iot").value, 10),
    });
    status.textContent = "Saved ✓";
    setTimeout(() => { status.textContent = ""; }, 3000);
  } catch (e) {
    status.textContent = "Failed";
    showToast("Save failed: " + e.message, "danger");
    setTimeout(() => { status.textContent = ""; }, 4000);
  } finally {
    btn.disabled = false;
  }
}

// ============================================================
// Security
// ============================================================
async function loadSecurityStats() {
  try {
    const s = await api("GET", "/api/security/stats");
    document.getElementById("sec-active-blocks").textContent = s.active_blocks;
    document.getElementById("sec-ratelimited").textContent   = s.ratelimited_24h.toLocaleString();
    document.getElementById("sec-rebinding").textContent     = s.rebinding_24h.toLocaleString();
    document.getElementById("sec-anomaly").textContent       = s.anomaly_24h.toLocaleString();
    document.getElementById("sec-iot-flood").textContent     = (s.iot_flood_24h || 0).toLocaleString();
  } catch (_) {}
}

async function loadSecurityEvents() {
  const tbody = document.getElementById("sec-events-tbody");
  const empty = document.getElementById("sec-events-empty");
  const EVENT_META = {
    rebinding:      { cls: "bg-danger",            label: "DNS Rebinding"   },
    dga_suspect:    { cls: "bg-secondary",         label: "DGA Suspect"     },
    query_burst:    { cls: "bg-warning text-dark", label: "Query Burst"     },
    canary_trigger: { cls: "bg-warning text-dark", label: "Canary Triggered" },
    cname_cloaking: { cls: "bg-danger",            label: "CNAME Cloaking"  },
    iot_flood:      { cls: "bg-danger",            label: "IoT Burst"       },
  };
  try {
    const events = await api("GET", "/api/security/events?limit=100");
    if (!events.length) {
      tbody.innerHTML = "";
      empty.style.display = "";
      return;
    }
    empty.style.display = "none";
    tbody.innerHTML = events.map(e => {
      const m = EVENT_META[e.event_type] || { cls: "bg-secondary", label: e.event_type };
      return `<tr>
        <td class="ps-3 font-monospace small text-muted">${escHtml(e.ts.slice(11))}</td>
        <td><span class="badge ${m.cls}" style="font-size:.7rem">${m.label}</span></td>
        <td class="font-monospace small">${escHtml(e.client_ip)}</td>
        <td class="font-monospace small text-truncate" style="max-width:220px" title="${escHtml(e.domain)}">${escHtml(e.domain)}</td>
        <td class="small text-muted pe-3">${escHtml(e.detail)}</td>
      </tr>`;
    }).join("");
  } catch (_) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-muted small text-center py-3">Could not load events.</td></tr>`;
    empty.style.display = "none";
  }
}

async function loadThreatIntel() {
  try {
    const ti = await api("GET", "/api/security/threat-intel");
    const badge   = document.getElementById("ti-status-badge");
    const colors  = { ok: "bg-success", never_run: "bg-secondary", no_domains: "bg-warning" };
    badge.className = "badge " + (colors[ti.status] || "bg-danger");
    badge.textContent = ti.status || "—";
    document.getElementById("ti-total").textContent   = (ti.total_domains || 0).toLocaleString();
    document.getElementById("ti-updated").textContent = ti.last_updated || "Never";
    document.getElementById("ti-added").textContent   = "+" + (ti.domains_added || 0).toLocaleString();
    const feedsEl = document.getElementById("ti-feeds");
    if (ti.feeds && ti.feeds.length) {
      feedsEl.innerHTML = ti.feeds.map(f => `<div class="mb-1">&#8250; ${escHtml(f)}</div>`).join("");
    }
  } catch (_) {}
}

async function loadSecurityBlocks() {
  const tbody = document.getElementById("sec-blocks-tbody");
  const empty = document.getElementById("sec-blocks-empty");
  try {
    const blocks = await api("GET", "/api/security/blocks");
    if (!blocks.length) {
      tbody.innerHTML = "";
      empty.style.display = "";
      return;
    }
    empty.style.display = "none";
    tbody.innerHTML = blocks.map(b => `
      <tr>
        <td class="ps-3 font-monospace small">${escHtml(b.ip)}</td>
        <td><span class="badge bg-danger">${escHtml(b.reason_label)}</span></td>
        <td class="small text-muted">${b.query_count.toLocaleString()}</td>
        <td class="small text-muted font-monospace">${escHtml(b.blocked_at)}</td>
        <td class="small text-muted font-monospace">${escHtml(b.expires_at)}</td>
        <td class="pe-3 text-end">
          <button class="btn btn-sm btn-outline-secondary py-0 btn-unblock"
            data-ip="${escHtml(b.ip)}" style="font-size:0.7rem">Unblock</button>
        </td>
      </tr>`).join("");
    tbody.querySelectorAll(".btn-unblock").forEach(btn => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api("DELETE", `/api/security/blocks/${encodeURIComponent(btn.dataset.ip)}`);
          showToast(`Unblocked: ${btn.dataset.ip}`, "success");
          loadSecurityBlocks();
          loadSecurityStats();
        } catch (err) {
          btn.disabled = false;
          showToast("Unblock failed: " + err.message, "danger");
        }
      });
    });
  } catch (_) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted small text-center py-3">Could not load blocks.</td></tr>`;
    empty.style.display = "none";
  }
}

async function loadSecurity() {
  await Promise.all([loadSecurityStats(), loadSecurityBlocks(), loadSecurityEvents(), loadThreatIntel()]);
}

// ============================================================
// Devices (fingerprinting)
// ============================================================
const DEVICE_META = {
  "Apple Device":     { svg: "apple",       bg: "#555",    fg: "#fff" },
  "Xbox":             { svg: "xbox",         bg: "#107c10", fg: "#fff" },
  "PlayStation":      { svg: "playstation",  bg: "#003087", fg: "#fff" },
  "Nintendo Switch":  { svg: "nintendo",     bg: "#e4000f", fg: "#fff" },
  "Roku":             { svg: "roku",         bg: "#6c3fa3", fg: "#fff" },
  "Samsung TV":       { svg: "samsung",      bg: "#1428a0", fg: "#fff" },
  "Amazon Fire TV":   { svg: "amazon",       bg: "#ff9900", fg: "#000" },
  "Amazon Echo":      { svg: "amazon",       bg: "#00a8cc", fg: "#fff" },
  "Amazon Device":    { svg: "amazon",       bg: "#ff9900", fg: "#000" },
  "Google Home":      { svg: "google",       bg: "#4285f4", fg: "#fff" },
  "Synology NAS":     { svg: "synology",     bg: "#b5a642", fg: "#000" },
  "MikroTik":         { svg: "mikrotik",     bg: "#293239", fg: "#fff" },
  "Ubiquiti":         { svg: "ubiquiti",     bg: "#0559c9", fg: "#fff" },
  "TP-Link":          { svg: "tplink",       bg: "#49aa00", fg: "#fff" },
  "D-Link":           { svg: "dlink",        bg: "#0033a0", fg: "#fff" },
  "Hikvision Camera": { svg: "hikvision",    bg: "#c0392b", fg: "#fff" },
  "Dahua Camera":     { svg: "dahua",        bg: "#e74c3c", fg: "#fff" },
  "Tuya IoT":         { svg: "tuya",         bg: "#ff6600", fg: "#fff" },
  "Windows":          { svg: "windows",      bg: "#0078d4", fg: "#fff" },
  "Android":          { svg: "android",      bg: "#3ddc84", fg: "#000" },
  "Linux":            { svg: "linux",        bg: "#333",    fg: "#fff" },
};

function deviceBadge(type) {
  const m = DEVICE_META[type];
  if (!m) return `<span class="badge bg-secondary" style="font-size:.72rem">${escHtml(type)}</span>`;
  const img = `<img src="/static/icons/${m.svg}.svg" width="13" height="13" style="filter:invert(${m.fg==='#fff'?1:0});margin-right:4px;vertical-align:middle;position:relative;top:-1px">`;
  return `<span class="badge d-inline-flex align-items-center gap-1" style="font-size:.72rem;background:${m.bg};color:${m.fg}">${img}${escHtml(type)}</span>`;
}

async function loadDevices() {
  const tbody = document.getElementById("devices-tbody");
  const empty = document.getElementById("devices-empty");
  try {
    const devices = await api("GET", "/api/devices");
    if (!devices.length) {
      tbody.innerHTML = "";
      empty.style.display = "";
      return;
    }
    empty.style.display = "none";
    tbody.innerHTML = devices.map(d => {
      const label = d.label
        ? `<span class="text-info small fw-semibold device-label" data-ip="${escHtml(d.ip)}" style="cursor:pointer" title="Click to edit">${escHtml(d.label)}</span>`
        : `<span class="text-muted small device-label" data-ip="${escHtml(d.ip)}" style="cursor:pointer;font-style:italic" title="Click to add label">Add label…</span>`;
      const confBar = `<div class="progress" style="height:5px;min-width:60px">
        <div class="progress-bar bg-info" style="width:${Math.min(100, d.confidence)}%"></div>
      </div>`;
      const profileSelect = `<select class="form-select form-select-sm py-0 profile-select" data-ip="${escHtml(d.ip)}"
        style="font-size:.7rem;width:auto;min-width:100px;background:#161b22;border-color:#30363d">
        <option value="normal"      ${d.profile === "normal"      ? "selected" : ""}>Normal</option>
        <option value="strict"      ${d.profile === "strict"      ? "selected" : ""}>Strict</option>
        <option value="passthrough" ${d.profile === "passthrough" ? "selected" : ""}>Passthrough</option>
      </select>`;
      const parentalBtn = d.parental_enabled
        ? `<button class="btn btn-sm btn-warning py-0 btn-parental" data-ip="${escHtml(d.ip)}" style="font-size:.7rem">🛡️ On</button>`
        : `<button class="btn btn-sm btn-outline-secondary py-0 btn-parental" data-ip="${escHtml(d.ip)}" style="font-size:.7rem">🛡️ Off</button>`;
      return `<tr>
        <td class="ps-3 font-monospace small">${escHtml(d.ip)}</td>
        <td class="small">${label}</td>
        <td>${deviceBadge(d.device_type)}</td>
        <td>${profileSelect}</td>
        <td>${parentalBtn}</td>
        <td style="min-width:80px" data-sort="${d.confidence}">${confBar}</td>
        <td class="small text-muted font-monospace">${escHtml((d.first_seen || "").slice(0, 16))}</td>
        <td class="small text-muted font-monospace">${escHtml((d.last_seen || "").slice(0, 16))}</td>
        <td class="pe-3 text-end"><button class="btn btn-sm btn-outline-info py-0 btn-device-stats" data-ip="${escHtml(d.ip)}" style="font-size:.7rem">Stats</button></td>
      </tr>`;
    }).join("");

    tbody.querySelectorAll(".btn-device-stats").forEach(btn => {
      btn.addEventListener("click", () => openDeviceStats(btn.dataset.ip));
    });

    // Profile change
    tbody.querySelectorAll(".profile-select").forEach(sel => {
      sel.addEventListener("change", async () => {
        const ip = sel.dataset.ip;
        const profile = sel.value;
        try {
          await api("PATCH", `/api/devices/${encodeURIComponent(ip)}/profile`, { profile });
          showToast(`${ip} profile set to ${profile}`, "success");
        } catch (e) {
          showToast("Profile update failed: " + e.message, "danger");
          loadDevices(); // revert UI
        }
      });
    });

    // Parental controls button
    tbody.querySelectorAll(".btn-parental").forEach(btn => {
      btn.addEventListener("click", () => openParentalModal(btn.dataset.ip));
    });

    // Inline label editing
    tbody.querySelectorAll(".device-label").forEach(el => {
      el.addEventListener("click", async () => {
        const ip    = el.dataset.ip;
        const current = el.dataset.label || "";
        const val   = prompt(`Label for ${ip}:`, current);
        if (val === null) return;
        try {
          await api("PATCH", `/api/devices/${encodeURIComponent(ip)}`, { label: val });
          loadDevices();
        } catch (e) {
          showToast("Label save failed: " + e.message, "danger");
        }
      });
    });
  } catch (_) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted small text-center py-3">Could not load devices.</td></tr>`;
    empty.style.display = "none";
  }
}

// ============================================================
// Parental controls modal
// ============================================================
let _parentalModalIp = null;

async function openParentalModal(ip) {
  _parentalModalIp = ip;
  document.getElementById("parental-modal-ip").textContent = ip;
  document.getElementById("parental-save-status").textContent = "";
  try {
    const s = await api("GET", `/api/parental/settings/${encodeURIComponent(ip)}`);
    document.getElementById("parental-enabled").checked      = s.parental_enabled;
    document.getElementById("parental-social").checked       = s.parental_block_social;
    document.getElementById("parental-gaming").checked       = s.parental_block_gaming;
    document.getElementById("parental-social-limit").value   = s.parental_social_limit ?? 500;
    document.getElementById("parental-gaming-limit").value   = s.parental_gaming_limit ?? 500;
    _updateParentalCategoryState(s.parental_enabled);
  } catch (e) {
    showToast("Could not load parental settings: " + e.message, "danger");
    return;
  }
  new bootstrap.Modal(document.getElementById("modal-parental")).show();
}

function _updateParentalCategoryState(enabled) {
  const cats = document.getElementById("parental-categories");
  cats.style.opacity       = enabled ? "1"    : "0.4";
  cats.style.pointerEvents = enabled ? "auto" : "none";
}

document.getElementById("parental-enabled").addEventListener("change", e => {
  _updateParentalCategoryState(e.target.checked);
});

document.getElementById("btn-save-parental").addEventListener("click", async () => {
  if (!_parentalModalIp) return;
  const status = document.getElementById("parental-save-status");
  status.textContent = "Saving…";
  try {
    await api("POST", `/api/parental/settings/${encodeURIComponent(_parentalModalIp)}`, {
      parental_enabled:      document.getElementById("parental-enabled").checked,
      parental_block_social: document.getElementById("parental-social").checked,
      parental_block_gaming: document.getElementById("parental-gaming").checked,
      parental_social_limit: parseInt(document.getElementById("parental-social-limit").value) || 0,
      parental_gaming_limit: parseInt(document.getElementById("parental-gaming-limit").value) || 0,
    });
    status.textContent = "Saved ✓";
    setTimeout(() => {
      bootstrap.Modal.getInstance(document.getElementById("modal-parental"))?.hide();
      loadDevices();
    }, 800);
  } catch (e) {
    status.textContent = "Failed";
    showToast("Save failed: " + e.message, "danger");
  }
});

// ============================================================
// Schedules
// ============================================================
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

async function loadSchedules() {
  const tbody = document.getElementById("schedules-tbody");
  const empty = document.getElementById("schedules-empty");
  try {
    const rules = await api("GET", "/api/schedules");
    if (!rules.length) {
      tbody.innerHTML = "";
      empty.style.display = "";
      return;
    }
    empty.style.display = "none";
    tbody.innerHTML = rules.map(r => {
      const statusBadge = r.enabled
        ? `<span class="badge bg-success">Active</span>`
        : `<span class="badge bg-secondary">Disabled</span>`;
      const ipLabel = r.client_ip === "*" ? '<span class="text-muted">All devices</span>' : `<span class="font-monospace">${escHtml(r.client_ip)}</span>`;
      return `<tr>
        <td class="ps-3 fw-semibold small">${escHtml(r.label || "Untitled")}</td>
        <td class="small">${ipLabel}</td>
        <td class="small text-muted">${escHtml(r.days_label)}</td>
        <td class="small font-monospace">${escHtml(r.start_time)} – ${escHtml(r.end_time)}</td>
        <td>${statusBadge}</td>
        <td class="pe-3 text-end">
          <button class="btn btn-sm btn-outline-secondary py-0 me-1 btn-edit-schedule" data-id="${r.id}" data-label="${escHtml(r.label)}" data-ip="${escHtml(r.client_ip)}" data-days="${escHtml(r.days)}" data-start="${escHtml(r.start_time)}" data-end="${escHtml(r.end_time)}" data-enabled="${r.enabled}">Edit</button>
          <button class="btn btn-sm btn-outline-danger py-0 btn-del-schedule" data-id="${r.id}">Delete</button>
        </td>
      </tr>`;
    }).join("");

    tbody.querySelectorAll(".btn-del-schedule").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this schedule rule?")) return;
        await api("DELETE", `/api/schedules/${btn.dataset.id}`);
        loadSchedules();
      });
    });

    tbody.querySelectorAll(".btn-edit-schedule").forEach(btn => {
      btn.addEventListener("click", () => openScheduleModal({
        id:      btn.dataset.id,
        label:   btn.dataset.label,
        ip:      btn.dataset.ip,
        days:    btn.dataset.days,
        start:   btn.dataset.start,
        end:     btn.dataset.end,
        enabled: btn.dataset.enabled === "true",
      }));
    });
  } catch (_) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted small text-center py-3">Could not load schedules.</td></tr>`;
    empty.style.display = "none";
  }
}

function openScheduleModal(rule = {}) {
  // Remove any existing modal
  document.getElementById("schedule-modal")?.remove();

  const isEdit = !!rule.id;
  const days = rule.days || "0123456";

  const dayCheckboxes = DAY_NAMES.map((name, i) =>
    `<div class="form-check form-check-inline">
      <input class="form-check-input" type="checkbox" id="sday-${i}" value="${i}" ${days.includes(String(i)) ? "checked" : ""}>
      <label class="form-check-label small" for="sday-${i}">${name}</label>
    </div>`
  ).join("");

  const modal = document.createElement("div");
  modal.id = "schedule-modal";
  modal.innerHTML = `
  <div class="modal fade show d-block" tabindex="-1" style="background:rgba(0,0,0,.6)">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content bg-dark border-secondary">
        <div class="modal-header border-secondary">
          <h6 class="modal-title">${isEdit ? "Edit" : "Add"} Schedule Rule</h6>
          <button type="button" class="btn-close btn-close-white" id="sched-close"></button>
        </div>
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label small text-muted">Label</label>
            <input type="text" class="form-control form-control-sm" id="sched-label" value="${escHtml(rule.label || "")}" placeholder="e.g. Bedtime">
          </div>
          <div class="mb-3">
            <label class="form-label small text-muted">Device IP <span class="text-muted fw-normal">(or * for all devices)</span></label>
            <input type="text" class="form-control form-control-sm font-monospace" id="sched-ip" value="${escHtml(rule.ip || "*")}">
          </div>
          <div class="mb-3">
            <label class="form-label small text-muted">Days</label>
            <div class="d-flex flex-wrap gap-1">${dayCheckboxes}</div>
          </div>
          <div class="row g-2 mb-3">
            <div class="col">
              <label class="form-label small text-muted">Start Time</label>
              <input type="time" class="form-control form-control-sm" id="sched-start" value="${escHtml(rule.start || "22:00")}">
            </div>
            <div class="col">
              <label class="form-label small text-muted">End Time</label>
              <input type="time" class="form-control form-control-sm" id="sched-end" value="${escHtml(rule.end || "07:00")}">
            </div>
          </div>
          <div class="form-check form-switch">
            <input class="form-check-input" type="checkbox" id="sched-enabled" ${rule.enabled !== false ? "checked" : ""}>
            <label class="form-check-label small" for="sched-enabled">Enabled</label>
          </div>
        </div>
        <div class="modal-footer border-secondary">
          <button class="btn btn-sm btn-secondary" id="sched-cancel">Cancel</button>
          <button class="btn btn-sm btn-success" id="sched-save">${isEdit ? "Save Changes" : "Add Rule"}</button>
        </div>
      </div>
    </div>
  </div>`;
  document.body.appendChild(modal);

  const close = () => modal.remove();
  document.getElementById("sched-close").addEventListener("click", close);
  document.getElementById("sched-cancel").addEventListener("click", close);

  document.getElementById("sched-save").addEventListener("click", async () => {
    const selectedDays = Array.from(document.querySelectorAll("[id^='sday-']:checked")).map(c => c.value).join("");
    if (!selectedDays) { showToast("Select at least one day", "warning"); return; }
    const body = {
      label:      document.getElementById("sched-label").value.trim(),
      client_ip:  document.getElementById("sched-ip").value.trim() || "*",
      days:       selectedDays,
      start_time: document.getElementById("sched-start").value,
      end_time:   document.getElementById("sched-end").value,
      enabled:    document.getElementById("sched-enabled").checked,
    };
    try {
      if (isEdit) {
        await api("PATCH", `/api/schedules/${rule.id}`, body);
      } else {
        await api("POST", "/api/schedules", body);
      }
      close();
      loadSchedules();
      showToast(isEdit ? "Schedule updated" : "Schedule rule added", "success");
    } catch (e) {
      showToast("Save failed: " + e.message, "danger");
    }
  });
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
// Custom Allowlist
// ============================================================
async function loadAllowlist() {
  const el = document.getElementById("allowlist-body");
  try {
    const items = await api("GET", "/api/allowlist");
    if (!items.length) {
      el.innerHTML = '<div class="text-muted small text-center py-2">No domains in the allowlist yet.</div>';
      return;
    }
    el.innerHTML = `<table class="table table-sm table-borderless mb-0 small">
      ${items.map(d => `<tr>
        <td class="font-monospace py-1">${escHtml(d.domain)}</td>
        <td class="text-muted py-1">${escHtml(d.note)}</td>
        <td class="text-end pe-0 py-1"><button class="btn btn-sm btn-outline-danger py-0 px-2 btn-remove-allow" data-domain="${escHtml(d.domain)}">Remove</button></td>
      </tr>`).join("")}
    </table>`;
    el.querySelectorAll(".btn-remove-allow").forEach(btn => {
      btn.addEventListener("click", async () => {
        await api("DELETE", `/api/allowlist/${encodeURIComponent(btn.dataset.domain)}`);
        loadAllowlist();
      });
    });
  } catch (_) {
    el.innerHTML = '<div class="text-muted small text-center py-2">Could not load allowlist.</div>';
  }
}

// ============================================================
// Local DNS Records
// ============================================================
async function loadDnsRecords() {
  const tbody = document.getElementById("dns-records-tbody");
  const empty = document.getElementById("dns-records-empty");
  try {
    const records = await api("GET", "/api/dns-records");
    if (!records.length) {
      tbody.innerHTML = "";
      empty.style.display = "";
      return;
    }
    empty.style.display = "none";
    tbody.innerHTML = records.map(r => {
      const status = r.enabled
        ? `<span class="badge bg-success">Active</span>`
        : `<span class="badge bg-secondary">Disabled</span>`;
      return `<tr>
        <td class="ps-3 font-monospace small">${escHtml(r.hostname)}</td>
        <td><span class="badge bg-secondary">${escHtml(r.type)}</span></td>
        <td class="font-monospace small">${escHtml(r.value)}</td>
        <td class="small text-muted">${r.ttl}s</td>
        <td>${status}</td>
        <td class="pe-3 text-end">
          <button class="btn btn-sm btn-outline-secondary py-0 me-1 btn-edit-record"
            data-id="${r.id}" data-hostname="${escHtml(r.hostname)}" data-type="${escHtml(r.type)}"
            data-value="${escHtml(r.value)}" data-ttl="${r.ttl}" data-enabled="${r.enabled}">Edit</button>
          <button class="btn btn-sm btn-outline-danger py-0 btn-del-record" data-id="${r.id}">Delete</button>
        </td>
      </tr>`;
    }).join("");
    tbody.querySelectorAll(".btn-del-record").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this DNS record?")) return;
        await api("DELETE", `/api/dns-records/${btn.dataset.id}`);
        loadDnsRecords();
      });
    });
    tbody.querySelectorAll(".btn-edit-record").forEach(btn => {
      btn.addEventListener("click", () => openDnsRecordModal({
        id: btn.dataset.id, hostname: btn.dataset.hostname, type: btn.dataset.type,
        value: btn.dataset.value, ttl: btn.dataset.ttl, enabled: btn.dataset.enabled === "true",
      }));
    });
  } catch (_) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted small text-center py-3">Could not load DNS records.</td></tr>`;
    empty.style.display = "none";
  }
}

function openDnsRecordModal(rec = {}) {
  document.getElementById("dns-record-modal")?.remove();
  const isEdit = !!rec.id;
  const baseName = (rec.hostname || "").replace(/\.[^.]+$/, "");
  const modal = document.createElement("div");
  modal.id = "dns-record-modal";
  modal.innerHTML = `
  <div class="modal fade show d-block" tabindex="-1" style="background:rgba(0,0,0,.6)">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content bg-dark border-secondary">
        <div class="modal-header border-secondary">
          <h6 class="modal-title">${isEdit ? "Edit" : "Add"} DNS Record</h6>
          <button type="button" class="btn-close btn-close-white" id="dr-close"></button>
        </div>
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label small text-muted">Hostname</label>
            <div class="input-group input-group-sm">
              <input type="text" class="form-control font-monospace" id="dr-hostname"
                value="${escHtml(baseName)}" placeholder="nas">
              <span class="input-group-text text-muted font-monospace">.lan</span>
            </div>
          </div>
          <div class="mb-3">
            <label class="form-label small text-muted">Type</label>
            <select class="form-select form-select-sm" id="dr-type">
              <option value="A" ${rec.type !== "CNAME" ? "selected" : ""}>A (IPv4 address)</option>
              <option value="CNAME" ${rec.type === "CNAME" ? "selected" : ""}>CNAME (alias)</option>
            </select>
          </div>
          <div class="mb-3">
            <label class="form-label small text-muted">Value</label>
            <input type="text" class="form-control form-control-sm font-monospace" id="dr-value" value="${escHtml(rec.value || "")}" placeholder="10.0.0.5 or target.hostname">
          </div>
          <div class="mb-3">
            <label class="form-label small text-muted">TTL (seconds)</label>
            <input type="number" class="form-control form-control-sm" id="dr-ttl" value="${rec.ttl || 300}" min="0" max="86400">
          </div>
          <div class="form-check form-switch">
            <input class="form-check-input" type="checkbox" id="dr-enabled" ${rec.enabled !== false ? "checked" : ""}>
            <label class="form-check-label small" for="dr-enabled">Enabled</label>
          </div>
        </div>
        <div class="modal-footer border-secondary">
          <button class="btn btn-sm btn-secondary" id="dr-cancel">Cancel</button>
          <button class="btn btn-sm btn-success" id="dr-save">${isEdit ? "Save Changes" : "Add Record"}</button>
        </div>
      </div>
    </div>
  </div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  document.getElementById("dr-close").addEventListener("click", close);
  document.getElementById("dr-cancel").addEventListener("click", close);
  document.getElementById("dr-save").addEventListener("click", async () => {
    const drName = document.getElementById("dr-hostname").value.trim().toLowerCase().replace(/\..*$/, "");
    const body = {
      hostname: drName + ".lan",
      type:     document.getElementById("dr-type").value,
      value:    document.getElementById("dr-value").value.trim(),
      ttl:      parseInt(document.getElementById("dr-ttl").value) || 300,
      enabled:  document.getElementById("dr-enabled").checked,
    };
    try {
      if (isEdit) await api("PATCH", `/api/dns-records/${rec.id}`, body);
      else        await api("POST",  "/api/dns-records", body);
      close();
      loadDnsRecords();
      showToast(isEdit ? "Record updated" : "Record added", "success");
    } catch (e) { showToast("Save failed: " + e.message, "danger"); }
  });
}

// ============================================================
// Per-device stats modal
// ============================================================
function _dsDomainList(items, badgeCls) {
  if (!items?.length) return '<div class="text-muted small py-3 text-center">No data yet</div>';
  const max = items[0].count || 1;
  return items.map(x => `
    <div class="d-flex align-items-center gap-2 mb-2">
      <span class="font-monospace small text-truncate flex-grow-1" style="max-width:260px" title="${escHtml(x.domain)}">${escHtml(x.domain)}</span>
      <div class="progress flex-shrink-0" style="width:60px;height:5px">
        <div class="progress-bar ${badgeCls}" style="width:${Math.round(x.count/max*100)}%"></div>
      </div>
      <span class="text-muted small" style="width:36px;text-align:right">${x.count}</span>
    </div>`).join("");
}

async function openDeviceStats(ip) {
  document.getElementById("device-stats-modal")?.remove();
  const modal = document.createElement("div");
  modal.id = "device-stats-modal";
  modal.innerHTML = `
  <div class="modal fade show d-block" tabindex="-1" style="background:rgba(0,0,0,.6)">
    <div class="modal-dialog modal-dialog-centered modal-lg">
      <div class="modal-content bg-dark border-secondary">
        <div class="modal-header border-secondary py-2">
          <div>
            <h6 class="modal-title font-monospace mb-0" id="ds-title">${escHtml(ip)}</h6>
            <div class="text-muted small" id="ds-subtitle" style="font-size:.75rem"></div>
          </div>
          <button type="button" class="btn-close btn-close-white" id="ds-close"></button>
        </div>
        <div class="modal-body" id="ds-body">
          <div class="text-center text-muted py-4">Loading…</div>
        </div>
      </div>
    </div>
  </div>`;
  document.body.appendChild(modal);
  document.getElementById("ds-close").addEventListener("click", () => modal.remove());

  try {
    const d = await api("GET", `/api/devices/${encodeURIComponent(ip)}/stats`);

    // Header
    if (d.label) document.getElementById("ds-title").textContent = d.label;
    const parts = [ip];
    if (d.device_type) parts.push(d.device_type);
    document.getElementById("ds-subtitle").textContent = parts.join(" · ");

    // Stacked activity bar
    const blockedPct  = d.total ? Math.round(d.blocked  / d.total * 100) : 0;
    const fwdPct      = d.total ? Math.round(d.forwarded / d.total * 100) : 0;
    const otherPct    = Math.max(0, 100 - blockedPct - fwdPct);

    // Recent queries rows
    const BADGE = {blocked:"badge-blocked",forwarded:"badge-forwarded",allowed:"badge-forwarded",
                   cached:"badge-cached",scheduled:"badge-captive",ratelimited:"badge-failed",nxdomain:"badge-failed"};
    const recentRows = d.recent_queries.map(q => {
      const cls = BADGE[q.action] || "badge-forwarded";
      return `<tr>
        <td class="font-monospace small text-muted ps-2">${escHtml(q.ts.slice(11))}</td>
        <td class="font-monospace small text-truncate" style="max-width:240px" title="${escHtml(q.domain)}">${escHtml(q.domain)}</td>
        <td class="small text-muted">${escHtml(q.qtype)}</td>
        <td class="pe-2"><span class="badge ${cls}" style="font-size:.62rem">${escHtml(q.action)}</span></td>
      </tr>`;
    }).join("");

    document.getElementById("ds-body").innerHTML = `
      <!-- Stat cards -->
      <div class="row g-2 mb-3">
        <div class="col-3 text-center">
          <div class="fw-bold fs-5 text-info">${d.total.toLocaleString()}</div>
          <div class="text-muted" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.06em">Total</div>
        </div>
        <div class="col-3 text-center">
          <div class="fw-bold fs-5 text-success">${d.forwarded.toLocaleString()}</div>
          <div class="text-muted" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.06em">Forwarded</div>
        </div>
        <div class="col-3 text-center">
          <div class="fw-bold fs-5 text-danger">${d.blocked.toLocaleString()}</div>
          <div class="text-muted" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.06em">Blocked</div>
        </div>
        <div class="col-3 text-center">
          <div class="fw-bold fs-5 text-warning">${d.block_pct}%</div>
          <div class="text-muted" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.06em">Block Rate</div>
        </div>
      </div>

      <!-- Activity bar -->
      <div class="mb-3" title="Forwarded ${fwdPct}% · Blocked ${blockedPct}% · Other ${otherPct}%">
        <div class="progress" style="height:8px;border-radius:4px">
          <div class="progress-bar bg-success" style="width:${fwdPct}%" title="Forwarded"></div>
          <div class="progress-bar bg-danger"  style="width:${blockedPct}%" title="Blocked"></div>
          <div class="progress-bar bg-secondary" style="width:${otherPct}%" title="Other"></div>
        </div>
        <div class="d-flex gap-3 mt-1" style="font-size:.68rem">
          <span><span style="color:#238636">■</span> Forwarded</span>
          <span><span style="color:#da3633">■</span> Blocked</span>
          <span><span style="color:#6e7681">■</span> Other</span>
        </div>
      </div>

      <!-- Tabs -->
      <ul class="nav nav-tabs nav-tabs-sm border-secondary mb-3" id="ds-tabs">
        <li class="nav-item"><button class="nav-link active py-1 px-3 small" data-ds-tab="blocked">Top Blocked</button></li>
        <li class="nav-item"><button class="nav-link py-1 px-3 small" data-ds-tab="forwarded">Top Forwarded</button></li>
        <li class="nav-item"><button class="nav-link py-1 px-3 small" data-ds-tab="recent">Recent Queries</button></li>
      </ul>

      <div id="ds-tab-blocked" style="max-height:220px;overflow-y:auto">
        ${_dsDomainList(d.top_blocked_domains, "bg-danger")}
      </div>
      <div id="ds-tab-forwarded" style="max-height:220px;overflow-y:auto;display:none">
        ${_dsDomainList(d.top_forwarded_domains, "bg-success")}
      </div>
      <div id="ds-tab-recent" style="max-height:220px;overflow-y:auto;display:none">
        <table class="table table-sm table-borderless mb-0">
          <tbody>${recentRows}</tbody>
        </table>
      </div>`;

    // Tab switching
    modal.querySelectorAll("[data-ds-tab]").forEach(btn => {
      btn.addEventListener("click", () => {
        modal.querySelectorAll("[data-ds-tab]").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        ["blocked","forwarded","recent"].forEach(t => {
          document.getElementById(`ds-tab-${t}`).style.display = t === btn.dataset.dsTab ? "" : "none";
        });
      });
    });

  } catch (e) {
    document.getElementById("ds-body").innerHTML =
      `<div class="text-muted small text-center py-3">${e.message === "404" ? "No query data for this device yet." : "Failed to load stats."}</div>`;
  }
}

// ============================================================
// DNS Canary Tokens
// ============================================================
async function loadCanaryTokens() {
  const tbody = document.getElementById("canary-tbody");
  const empty = document.getElementById("canary-empty");
  try {
    const tokens = await api("GET", "/api/canary-tokens");
    if (!tokens.length) {
      tbody.innerHTML = "";
      empty.style.display = "";
      return;
    }
    empty.style.display = "none";
    tbody.innerHTML = tokens.map(t => {
      const triggered = t.trigger_count > 0
        ? `<span class="badge bg-danger">${t.trigger_count}</span>`
        : `<span class="text-muted small">0</span>`;
      return `<tr>
        <td class="ps-3 fw-semibold small">${escHtml(t.label || "Untitled")}</td>
        <td class="font-monospace small">${escHtml(t.domain)}</td>
        <td>${triggered}</td>
        <td class="small text-muted">${escHtml(t.last_triggered || "Never")}</td>
        <td class="small text-muted">${escHtml((t.created_at || "").slice(0, 16))}</td>
        <td class="pe-3 text-end">
          <button class="btn btn-sm btn-outline-danger py-0 btn-del-canary" data-id="${t.id}">Delete</button>
        </td>
      </tr>`;
    }).join("");
    tbody.querySelectorAll(".btn-del-canary").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this canary token?")) return;
        await api("DELETE", `/api/canary-tokens/${btn.dataset.id}`);
        showToast("Canary token deleted", "info");
        loadCanaryTokens();
      });
    });
  } catch (_) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted small text-center py-3">Could not load canary tokens.</td></tr>`;
    empty.style.display = "none";
  }
}

function openCanaryModal() {
  document.getElementById("canary-modal")?.remove();
  const modal = document.createElement("div");
  modal.id = "canary-modal";
  modal.innerHTML = `
  <div class="modal fade show d-block" tabindex="-1" style="background:rgba(0,0,0,.6)">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content bg-dark border-secondary">
        <div class="modal-header border-secondary">
          <h6 class="modal-title">New Canary Token</h6>
          <button type="button" class="btn-close btn-close-white" id="ct-close"></button>
        </div>
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label small text-muted">Label <span class="fw-normal">(e.g. "Budget spreadsheet")</span></label>
            <input type="text" class="form-control form-control-sm" id="ct-label" placeholder="What file/resource contains this token?">
          </div>
          <div class="alert alert-secondary small mb-0" style="background:#161b22;border-color:#30363d">
            A unique domain like <code>a1b2c3d4.rscanary</code> will be generated. Embed it in a file, email, or script.
            If that domain is ever queried on your network, an alert will fire in Security Events.
          </div>
        </div>
        <div class="modal-footer border-secondary">
          <button class="btn btn-sm btn-secondary" id="ct-cancel">Cancel</button>
          <button class="btn btn-sm btn-warning" id="ct-save">Generate Token</button>
        </div>
      </div>
    </div>
  </div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  document.getElementById("ct-close").addEventListener("click", close);
  document.getElementById("ct-cancel").addEventListener("click", close);
  document.getElementById("ct-save").addEventListener("click", async () => {
    const label = document.getElementById("ct-label").value.trim();
    try {
      const result = await api("POST", "/api/canary-tokens", { label });
      close();
      loadCanaryTokens();
      showToast(`Token created: ${result.domain}`, "success");
    } catch (e) {
      showToast("Create failed: " + e.message, "danger");
    }
  });
}

// ============================================================
// Reverse Proxy Rules
// ============================================================
async function loadProxyRules() {
  const tbody = document.getElementById("proxy-tbody");
  const empty = document.getElementById("proxy-empty");
  try {
    const rules = await api("GET", "/api/proxy-rules");
    if (!rules.length) {
      tbody.innerHTML = "";
      empty.style.display = "";
      return;
    }
    empty.style.display = "none";
    tbody.innerHTML = rules.map(r => {
      const status = r.enabled
        ? `<span class="badge bg-success">Active</span>`
        : `<span class="badge bg-secondary">Disabled</span>`;
      const name = r.hostname.replace(/\.lan$/, "");
      return `<tr>
        <td class="ps-3 font-monospace fw-semibold small">
          <a href="http://${escHtml(r.hostname)}" target="_blank" rel="noopener"
             class="text-decoration-none">
            ${escHtml(name)}<span class="text-muted">.lan</span>
          </a>
        </td>
        <td class="font-monospace small text-info">${escHtml(r.target)}</td>
        <td>${status}</td>
        <td class="pe-3 text-end d-flex gap-1 justify-content-end">
          <button class="btn btn-sm btn-outline-secondary py-0 btn-edit-proxy"
            data-id="${r.id}" data-hostname="${escHtml(r.hostname)}"
            data-target="${escHtml(r.target)}" data-enabled="${r.enabled}">Edit</button>
          <button class="btn btn-sm btn-outline-danger py-0 btn-del-proxy"
            data-id="${r.id}">Delete</button>
        </td>
      </tr>`;
    }).join("");

    tbody.querySelectorAll(".btn-del-proxy").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm(`Delete proxy rule for ${btn.closest("tr").querySelector("td").textContent}?`)) return;
        try {
          await api("DELETE", `/api/proxy-rules/${btn.dataset.id}`);
          showToast("Proxy rule deleted", "info");
          loadProxyRules();
        } catch (e) { showToast(e.message, "danger"); }
      });
    });

    tbody.querySelectorAll(".btn-edit-proxy").forEach(btn => {
      btn.addEventListener("click", () => openProxyModal({
        id:       btn.dataset.id,
        hostname: btn.dataset.hostname,
        target:   btn.dataset.target,
        enabled:  btn.dataset.enabled === "true",
      }));
    });
  } catch (_) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-muted small text-center py-3">Could not load proxy rules.</td></tr>`;
    empty.style.display = "none";
  }
}

function openProxyModal(rule = {}) {
  document.getElementById("proxy-modal")?.remove();
  const isEdit = !!rule.id;
  // Strip any TLD to show just the base name in the input
  const baseName = (rule.hostname || "").replace(/\.[^.]+$/, "");
  const modal = document.createElement("div");
  modal.id = "proxy-modal";
  modal.innerHTML = `
  <div class="modal fade show d-block" tabindex="-1" style="background:rgba(0,0,0,.6)">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content bg-dark border-secondary">
        <div class="modal-header border-secondary">
          <h6 class="modal-title">${isEdit ? "Edit" : "Add"} Proxy Rule</h6>
          <button type="button" class="btn-close btn-close-white" id="pr-close"></button>
        </div>
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label small text-muted">Hostname</label>
            <div class="input-group input-group-sm">
              <input type="text" class="form-control font-monospace" id="pr-hostname"
                value="${escHtml(baseName)}" placeholder="smartscreen">
              <span class="input-group-text text-muted font-monospace">.lan</span>
            </div>
            <div class="form-text">Just the name — <code>.lan</code> is added automatically. Open in browser as <code>http://name.lan</code></div>
          </div>
          <div class="mb-3">
            <label class="form-label small text-muted">Target URL</label>
            <input type="text" class="form-control form-control-sm font-monospace" id="pr-target"
              value="${escHtml(rule.target || "")}" placeholder="http://10.0.0.5:8080">
            <div class="form-text">Full URL including protocol and port of the internal service.</div>
          </div>
          <div class="form-check form-switch">
            <input class="form-check-input" type="checkbox" id="pr-enabled" ${rule.enabled !== false ? "checked" : ""}>
            <label class="form-check-label small" for="pr-enabled">Enabled</label>
          </div>
        </div>
        <div class="modal-footer border-secondary">
          <button class="btn btn-sm btn-secondary" id="pr-cancel">Cancel</button>
          <button class="btn btn-sm btn-success" id="pr-save">${isEdit ? "Save Changes" : "Add Rule"}</button>
        </div>
      </div>
    </div>
  </div>`;
  document.body.appendChild(modal);

  const close = () => modal.remove();
  document.getElementById("pr-close").addEventListener("click", close);
  document.getElementById("pr-cancel").addEventListener("click", close);
  document.getElementById("pr-save").addEventListener("click", async () => {
    const name = document.getElementById("pr-hostname").value.trim().toLowerCase().replace(/\..*$/, "");
    const body = {
      hostname: name + ".lan",
      target:   document.getElementById("pr-target").value.trim(),
      enabled:  document.getElementById("pr-enabled").checked,
    };
    if (!name || !body.target) {
      showToast("Hostname and target are required", "warning");
      return;
    }
    try {
      if (isEdit) await api("PATCH", `/api/proxy-rules/${rule.id}`, body);
      else        await api("POST",  "/api/proxy-rules", body);
      close();
      loadProxyRules();
      showToast(isEdit ? "Proxy rule updated" : `Proxy rule added — open http://${body.hostname}`, "success");
    } catch (e) { showToast(e.message, "danger"); }
  });
}

// ============================================================
// Privacy Report
// ============================================================
async function loadPrivacyReport() {
  const el = document.getElementById("privacy-report-body");
  try {
    const devices = await api("GET", "/api/privacy-report");
    if (!devices.length) {
      el.innerHTML = '<div class="text-muted small text-center py-4">No forwarded query data yet — browse the internet on your devices first.</div>';
      return;
    }

    const COMPANY_COLORS = {
      "Google": "#4285f4", "Meta": "#0082fb", "Amazon": "#ff9900",
      "Apple": "#888", "Microsoft": "#0078d4", "Samsung": "#1428a0",
      "ByteDance": "#010101", "Netflix": "#e50914", "Cloudflare": "#f48120",
      "Akamai": "#009bde", "Alibaba": "#ff6a00", "X (Twitter)": "#1da1f2",
      "Snap": "#fffc00", "Spotify": "#1db954", "MikroTik": "#293239",
      "Tuya": "#ff6600", "Fastly": "#ff282d", "Amazon CDN": "#ff9900",
    };

    el.innerHTML = devices.map(d => {
      const bars = d.companies.slice(0, 8).map(c => {
        const color = COMPANY_COLORS[c.company] || "#6e7681";
        return `<div class="d-flex align-items-center gap-2 mb-1">
          <span class="small text-muted" style="width:110px;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${escHtml(c.company)}">${escHtml(c.company)}</span>
          <div class="progress flex-grow-1" style="height:12px">
            <div class="progress-bar" style="width:${c.pct}%;background:${color}"
              title="${escHtml(c.company)}: ${c.count} queries (${c.pct}%)"></div>
          </div>
          <span class="small text-muted" style="width:36px;text-align:right">${c.pct}%</span>
        </div>`;
      }).join("");
      return `<div class="mb-4 pb-3 border-bottom border-secondary">
        <div class="d-flex justify-content-between align-items-baseline mb-2">
          <span class="font-monospace fw-semibold">${escHtml(d.ip)}</span>
          <span class="text-muted small">${d.total_forwarded.toLocaleString()} forwarded queries</span>
        </div>
        ${bars}
      </div>`;
    }).join("");
  } catch (_) {
    el.innerHTML = '<div class="text-muted small text-center py-4">Could not load privacy report.</div>';
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

  // Tab switch: load updater info + preset status + YT auto-blocked when Blocklist tab is shown
  document.getElementById("tab-bl-btn").addEventListener("shown.bs.tab", () => {
    loadUpdaterStatus();
    loadSources();
    loadPresetStatus();
    loadYTAutoBlocked();
    loadAllowlist();
  });

  document.getElementById("btn-refresh-yt").addEventListener("click", loadYTAutoBlocked);

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

  // Security tab
  document.getElementById("tab-security-btn").addEventListener("shown.bs.tab", () => {
    loadSecurity();
    loadCanaryTokens();
  });
  document.getElementById("btn-refresh-security").addEventListener("click", () => {
    loadSecurity();
    loadCanaryTokens();
  });

  // Devices tab
  document.getElementById("tab-devices-btn").addEventListener("shown.bs.tab", loadDevices);
  document.getElementById("btn-refresh-devices").addEventListener("click", loadDevices);

  // Proxy tab
  document.getElementById("tab-dns-records-btn").addEventListener("shown.bs.tab", loadProxyRules);
  document.getElementById("btn-refresh-proxy").addEventListener("click", loadProxyRules);
  document.getElementById("btn-add-proxy").addEventListener("click", () => openProxyModal());

  // Schedules tab
  document.getElementById("tab-schedules-btn").addEventListener("shown.bs.tab", loadSchedules);
  document.getElementById("btn-refresh-schedules").addEventListener("click", loadSchedules);
  document.getElementById("btn-add-schedule").addEventListener("click", () => openScheduleModal());

  // Allowlist (in Blocklist tab)
  document.getElementById("form-add-allow").addEventListener("submit", async (e) => {
    e.preventDefault();
    const domain = document.getElementById("input-allow-domain").value.trim();
    const note   = document.getElementById("input-allow-note").value.trim();
    if (!domain) return;
    try {
      await api("POST", "/api/allowlist", { domain, note });
      document.getElementById("input-allow-domain").value = "";
      document.getElementById("input-allow-note").value = "";
      loadAllowlist();
      showToast(`${domain} added to allowlist`, "success");
    } catch (e) { showToast(e.message, "danger"); }
  });

  // Canary tokens (in Security tab)
  document.getElementById("btn-refresh-canary").addEventListener("click", loadCanaryTokens);
  document.getElementById("btn-add-canary").addEventListener("click", openCanaryModal);

  // Privacy tab
  document.getElementById("tab-privacy-btn").addEventListener("shown.bs.tab", loadPrivacyReport);
  document.getElementById("btn-refresh-privacy").addEventListener("click", loadPrivacyReport);

  // Tab switch: load settings when Settings tab is shown
  document.getElementById("tab-settings-btn").addEventListener("shown.bs.tab", () => {
    loadSettings();
    loadEmailSettings();
    loadRateLimits();
  });
  document.getElementById("btn-save-rate-limits").addEventListener("click", saveRateLimits);

  // Auto-save proxy/captive toggles on change
  document.getElementById("yt-enabled").addEventListener("change", saveSettings);
  document.getElementById("cp-enabled").addEventListener("change", saveSettings);

  // NTP enable/disable toggle
  document.getElementById("ntp-enabled").addEventListener("change", async function () {
    const enabled = this.checked;
    this.disabled = true;
    try {
      await api("POST", "/api/ntp/enabled", { enabled });
      showToast(`NTP server ${enabled ? "started" : "stopped"}`, "success");
    } catch (e) {
      this.checked = !enabled; // revert on failure
      showToast("NTP toggle failed: " + e.message, "danger");
    } finally {
      this.disabled = false;
    }
  });

  // Email settings form save
  document.getElementById("form-email-settings").addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveEmailSettings();
  });

  // Clear saved SMTP password
  document.getElementById("btn-clear-email-password").addEventListener("click", async () => {
    const btn = document.getElementById("btn-clear-email-password");
    btn.disabled = true;
    try {
      await api("POST", "/api/settings/email/clear-password");
      document.getElementById("email-password").value = "";
      showToast("Password cleared — enter a new one and save", "info");
    } catch (e) {
      showToast("Clear failed: " + e.message, "danger");
    } finally {
      btn.disabled = false;
    }
  });

  // Send test email
  document.getElementById("btn-test-email").addEventListener("click", async () => {
    const btn = document.getElementById("btn-test-email");
    btn.disabled = true;
    btn.textContent = "Sending…";
    try {
      await api("POST", "/api/settings/email/test");
      showToast("Test email sent — check your inbox", "success");
    } catch (e) {
      showToast("Test failed: " + e.message, "danger");
    } finally {
      btn.disabled = false;
      btn.textContent = "Send Test Email";
    }
  });
}

// ============================================================
// Init
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("thead").forEach(initSortable);
  bindEvents();
  connectSSE();

  // Fire all startup fetches in parallel — nothing blocks anything else
  Promise.all([
    loadStats(),
    loadHealth(),
    preloadLog(),
    _initCurrency().then(() => loadStats()), // re-render stats with local currency once rate is ready
  ]);

  statsTimer = setInterval(loadStats, 30000);
  setInterval(loadHealth, 30000);
});
