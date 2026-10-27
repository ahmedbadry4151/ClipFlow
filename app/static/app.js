/* ClipFlow UI Controller — Positivus-Inspired Neo-Brutalist Downloader */
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const KEY_STORE = "tt_api_key";
const PREFS_STORE = "tt_prefs_v1";
const THEME_STORE = "clipflow_theme";
const MAX_ENTRIES = 200;

const state = {
  currentPage: "overview",
  theme: localStorage.getItem(THEME_STORE) || "light",
  jobs: new Map(),
  files: [],
  probe: null,
  probeUrl: "",
  selected: new Set(),
  entryFilter: "",
  showAll: false,
  quality: "best",
  queueFilter: "all",
  queueSearch: "",
  historyFilter: "all",
  historyFormat: "all",
  historySearch: "",
  filesSearch: "",
  system: null,
  apiKey: localStorage.getItem(KEY_STORE) || "",
  es: null,
  reconnect: 0,
  pollTimer: null,
  syncPromise: null,
  authPrompted: false,
};

function getThumbnail(job) {
  if (job && job.thumbnail) return job.thumbnail;
  const url = (job && job.url) || "";
  const match = url.match(/(?:v=|youtu\.be\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})/);
  if (match) {
    return `https://img.youtube.com/vi/${match[1]}/mqdefault.jpg`;
  }
  return "";
}

const STATUS_LABELS = {
  queued: "Queued",
  running: "Running",
  downloading: "Downloading",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  partial: "Partial",
  interrupted: "Interrupted",
};

const PREFS = [
  "audioOnly",
  "audioFormat",
  "container",
  "mode",
  "playlistItems",
  "reverse",
  "archive",
  "subtitles",
  "autoSubs",
  "subLangs",
  "sponsorblock",
  "embedSubs",
  "embedThumb",
  "embedMeta",
  "chapters",
  "useAria2",
  "fragments",
  "rateLimit",
  "proxy",
  "section",
  "browserCookies",
  "cookieFile",
  "resume",
  "pref-resume-partial",
  "pref-auto-resume",
];

/* ------------------------------------------------------------------ utils */
const esc = (value = "") =>
  String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));

function bytes(value) {
  const number = Number(value) || 0;
  if (number <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = number;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size >= 100 || index === 0 ? Math.round(size) : size.toFixed(1)} ${units[index]}`;
}

function duration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "";
  let total = Math.max(0, Math.round(Number(seconds)));
  const hours = Math.floor(total / 3600);
  total %= 3600;
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
               : `${minutes}:${String(secs).padStart(2, "0")}`;
}

function formatDate(timestamp) {
  if (!timestamp) return "—";
  const date = new Date(timestamp * 1000);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function baseName(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
}

function icon(name, className = "") {
  return `<svg class="${className}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

function toast(message, type = "ok") {
  const container = $("#toasts");
  if (!container) return;
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  const iconName = type === "ok" ? "check" : type === "warn" ? "alert" : "alert";
  node.innerHTML = `${icon(iconName)}<div>${esc(message)}</div>`;
  container.appendChild(node);
  setTimeout(() => {
    node.classList.add("leaving");
    setTimeout(() => node.remove(), 220);
  }, 4200);
}

function setLoading(button, loading, label) {
  if (!button) return;
  button.disabled = loading;
  button.classList.toggle("loading", loading);
  const span = button.querySelector("span");
  if (span && label) {
    if (!button.dataset.label) button.dataset.label = span.textContent;
    span.textContent = loading ? label : button.dataset.label;
  }
}

/* ----------------------------------------------------------- modal dialog */
function confirmModal(title, message, okText = "Confirm", isDanger = true) {
  return new Promise((resolve) => {
    const dialog = $("#confirm-modal");
    if (!dialog) {
      resolve(window.confirm(message));
      return;
    }
    $("#confirm-title").textContent = title;
    $("#confirm-msg").textContent = message;
    const okBtn = $("#confirm-ok");
    okBtn.textContent = okText;
    okBtn.className = isDanger ? "btn primary danger" : "btn primary";

    const cleanUp = () => {
      dialog.close();
      dialog.removeEventListener("close", onCancel);
      okBtn.removeEventListener("click", onOk);
      $("#confirm-cancel").removeEventListener("click", onCancel);
      $("#confirm-close").removeEventListener("click", onCancel);
    };

    const onOk = () => { cleanUp(); resolve(true); };
    const onCancel = () => { cleanUp(); resolve(false); };

    okBtn.addEventListener("click", onOk);
    $("#confirm-cancel").addEventListener("click", onCancel);
    $("#confirm-close").addEventListener("click", onCancel);
    dialog.addEventListener("close", onCancel);

    dialog.showModal();
  });
}

/* ------------------------------------------------------------------ theme */
function getEffectiveTheme(theme) {
  if (theme === "system") {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return theme;
}

function applyTheme(theme) {
  state.theme = theme;
  const effective = getEffectiveTheme(theme);
  document.documentElement.setAttribute("data-theme", effective);
  localStorage.setItem(THEME_STORE, theme);

  const toggleBtn = $("#theme-toggle");
  if (toggleBtn) {
    const label = toggleBtn.querySelector(".theme-label");
    if (label) {
      label.textContent = theme === "system"
        ? `Auto (${effective === "dark" ? "Dark" : "Light"})`
        : theme === "dark" ? "Dark Mode" : "Light Mode";
    }
  }

  $$(".theme-choice").forEach((choice) => {
    choice.classList.toggle("is-active", choice.dataset.setTheme === theme);
  });
}

function toggleTheme() {
  const next = state.theme === "light" ? "dark" : state.theme === "dark" ? "system" : "light";
  applyTheme(next);
}

if (typeof window !== "undefined" && window.matchMedia) {
  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (state.theme === "system") {
        applyTheme("system");
      }
    });
  } catch {
    /* older matchMedia fallback */
  }
}

/* ------------------------------------------------------------- navigation */
function switchPage(pageId) {
  state.currentPage = pageId;

  // Update tabs
  $$(".sidebar-nav .nav-item").forEach((btn) => {
    const active = btn.dataset.page === pageId;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", String(active));
  });

  // Update views
  $$(".page-view").forEach((view) => {
    view.classList.toggle("is-active", view.id === `view-${pageId}`);
  });

  // Update breadcrumbs
  const titleMap = {
    overview: "Overview",
    downloads: "Downloads",
    history: "History",
    files: "Files",
    settings: "Settings",
    help: "Help",
  };
  const title = titleMap[pageId] || "Overview";
  const crumb = $("#page-title-text");
  if (crumb) crumb.textContent = title;

  // Close mobile sidebar if open
  $("#sidebar")?.classList.remove("is-open");

  // Page-specific initializers
  if (pageId === "files") loadFiles();
  if (pageId === "history") renderHistory();
  if (pageId === "overview") updateOverviewWidgets();
}

/* -------------------------------------------------------------------- api */
async function api(path, options = {}, retried = false) {
  const headers = new Headers(options.headers || {});
  if (state.apiKey) headers.set("x-api-key", state.apiKey);
  const isForm = options.body instanceof FormData;
  if (options.body && !isForm) headers.set("content-type", "application/json");

  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && !retried) {
    const key = state.authPrompted ? "" : window.prompt("This server requires an API key:");
    state.authPrompted = false;
    if (key) {
      state.apiKey = key.trim();
      localStorage.setItem(KEY_STORE, state.apiKey);
      connectEvents();
      return api(path, options, true);
    }
    throw new Error("Unauthorized — set the API key to continue");
  }

  let payload = null;
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    payload = await response.json().catch(() => null);
  }
  if (!response.ok) {
    const detail = payload && (payload.detail || payload.message);
    throw new Error(typeof detail === "string" ? detail : `${response.status} ${response.statusText}`);
  }
  return payload;
}

/* ------------------------------------------------------------------ prefs */
function loadPrefs() {
  let prefs = {};
  try {
    prefs = JSON.parse(localStorage.getItem(PREFS_STORE) || "{}");
  } catch {
    prefs = {};
  }
  for (const id of PREFS) {
    const element = document.getElementById(id);
    if (!element || !(id in prefs)) continue;
    if (element.type === "checkbox") element.checked = Boolean(prefs[id]);
    else element.value = prefs[id];
  }
  state.quality = prefs.quality || "best";
  applyQualityUI();
  syncAudioUI();

  // Settings page format defaults
  const prefQ = $("#pref-default-quality");
  if (prefQ && prefs.quality) prefQ.value = prefs.quality;
  const prefC = $("#pref-default-container");
  if (prefC && prefs.container) prefC.value = prefs.container;
  const prefA = $("#pref-default-audio");
  if (prefA && prefs.audioFormat) prefA.value = prefs.audioFormat;
  if (prefs["pref-resume-partial"] !== undefined) {
    const resumeEl = $("#resume");
    if (resumeEl) resumeEl.checked = Boolean(prefs["pref-resume-partial"]);
  }
}

function savePrefs() {
  const prefs = { quality: state.quality };
  for (const id of PREFS) {
    const element = document.getElementById(id);
    if (!element) continue;
    prefs[id] = element.type === "checkbox" ? element.checked : element.value;
  }
  try {
    localStorage.setItem(PREFS_STORE, JSON.stringify(prefs));
  } catch {
    /* storage unavailable */
  }
}

/* --------------------------------------------------------------- options */
function value(id) {
  const element = document.getElementById(id);
  return element ? element.value.trim() : "";
}

function checked(id) {
  const element = document.getElementById(id);
  return Boolean(element && element.checked);
}

function collectOptions() {
  const fragments = parseInt(value("fragments"), 10);
  return {
    mode: value("mode") || "auto",
    quality: state.quality,
    container: value("container") || "mp4",
    audio_only: checked("audioOnly"),
    audio_format: value("audioFormat") || "mp3",
    audio_quality: "0",
    playlist_items: value("playlistItems"),
    playlist_reverse: checked("reverse"),
    subtitles: checked("subtitles"),
    auto_subtitles: checked("autoSubs"),
    subtitle_langs: value("subLangs") || "en",
    embed_subtitles: checked("embedSubs"),
    embed_thumbnail: checked("embedThumb"),
    embed_metadata: checked("embedMeta"),
    chapters: checked("chapters"),
    sponsorblock: value("sponsorblock") || "off",
    cookies_file: value("cookieFile"),
    cookies_from_browser: value("browserCookies"),
    proxy: value("proxy"),
    rate_limit: value("rateLimit"),
    section: value("section"),
    archive: checked("archive"),
    use_aria2: checked("useAria2"),
    resume: document.getElementById("resume") ? checked("resume") : true,
    continuedl: document.getElementById("resume") ? checked("resume") : true,
    fragments: Number.isFinite(fragments) ? fragments : null,
    retries: null,
    output_template: "",
  };
}

function applyQualityUI() {
  $$("#quality-chips .chip").forEach((chip) => {
    chip.classList.toggle("is-active", chip.dataset.quality === state.quality);
    chip.setAttribute("aria-checked", String(chip.dataset.quality === state.quality));
  });
}

function syncAudioUI() {
  const audio = checked("audioOnly");
  $("#quality-chips")?.classList.toggle("disabled", audio);
  const container = $("#container");
  if (container) {
    container.disabled = audio;
    container.closest(".mini-field").style.opacity = audio ? "0.45" : "";
  }
}

function setQuality(quality) {
  state.quality = quality;
  applyQualityUI();
  savePrefs();
}

/* ---------------------------------------------------------------- system */
function renderSystem(system) {
  state.system = system;
  const transport = $("#pill-transport");
  const workers = system.max_concurrent_downloads;
  transport.className = "pill " + (system.aria2 ? "ok" : "warn");
  transport.innerHTML = `<span class="dot"></span>${system.aria2 ? `aria2c · ${workers}×` : `native · ${workers}×`}`;
  transport.title = system.aria2
    ? "aria2c multi-connection transport is active"
    : "aria2c not found — using yt-dlp's native transport";

  const ffmpeg = $("#pill-ffmpeg");
  ffmpeg.className = "pill subtle " + (system.ffmpeg ? "ok" : "err");
  ffmpeg.textContent = system.ffmpeg ? "ffmpeg ready" : "ffmpeg missing";

  const dir = $("#pill-dir");
  const folderName = baseName(system.download_dir) || "downloads";
  dir.querySelector("span").textContent = folderName;
  dir.title = `Saving to ${system.download_dir} (click to reveal)`;

  const storagePathCode = $("#settings-storage-path");
  if (storagePathCode) storagePathCode.textContent = system.download_dir;

  // Diagnostics in Settings
  if ($("#diag-ytdlp")) $("#diag-ytdlp").textContent = system.ytdlp || "v2026+";
  if ($("#diag-ffmpeg")) $("#diag-ffmpeg").textContent = system.ffmpeg ? "Available & Configured" : "Not Found";
  if ($("#diag-aria2")) $("#diag-aria2").textContent = system.aria2 ? "Active (Multi-Threaded)" : "Disabled";

  if (system.auth_required && !state.apiKey) {
    toast("This server requires an API key", "warn");
  }
}

async function loadSystem() {
  try {
    renderSystem(await api("/api/system"));
  } catch (error) {
    const transport = $("#pill-transport");
    if (transport) {
      transport.className = "pill err";
      transport.innerHTML = `<span class="dot"></span>offline`;
      transport.title = error.message;
    }
  }
}

/* ----------------------------------------------------------------- probe */
function renderProbeLoading() {
  const container = $("#probe");
  container.classList.remove("hidden");
  container.innerHTML = `
    <div class="probe-loading" style="display:flex; align-items:center; gap:12px; padding:16px;">
      <svg class="loading-spin" style="animation: spin 1s linear infinite;"><use href="#i-refresh"/></svg>
      <span>Analyzing media streams and permitted formats…</span>
    </div>`;
}

function renderProbeError(message) {
  const container = $("#probe");
  container.classList.remove("hidden");
  container.innerHTML = `
    <div class="probe-error" style="display:flex; align-items:center; gap:12px; padding:16px; color:var(--red);">
      ${icon("alert")}
      <div><strong>Could not analyze this URL</strong><p style="font-size:13px; margin-top:4px;">${esc(message)}</p></div>
    </div>`;
}

function renderProbe() {
  const container = $("#probe");
  if (!state.probe) {
    container.classList.add("hidden");
    container.innerHTML = "";
    return;
  }
  const probe = state.probe;
  const isPlaylist = probe.kind === "playlist";
  const thumb = probe.thumbnail
    ? `<img class="probe-thumb" src="${esc(probe.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<div style="display:grid; place-items:center; height:100%;">${icon("film")}</div>`;
  const durationBadge = probe.duration ? `<span class="probe-duration">${duration(probe.duration)}</span>` : "";

  const qualities = (probe.qualities || []).map((q) => {
    return `<button type="button" class="probe-pill" data-set-quality="${esc(String(q.height))}">${esc(q.label || `${q.height}p`)}</button>`;
  }).join("");

  let playlistPickerHTML = "";
  if (isPlaylist && probe.entries && probe.entries.length) {
    const selectedCount = state.selected.size;
    const totalCount = probe.entries.length;
    const filter = (state.entryFilter || "").toLowerCase();
    const visibleEntries = filter
      ? probe.entries.filter((e) => (e.title || "").toLowerCase().includes(filter) || String(e.index).includes(filter))
      : probe.entries;

    playlistPickerHTML = `
      <div class="probe-playlist-picker">
        <div class="probe-playlist-head">
          <div class="probe-playlist-title">Playlist Videos (<span id="probe-selected-count">${selectedCount}</span> of ${totalCount} selected)</div>
          <div class="probe-playlist-actions">
            <div class="probe-playlist-search">
              <svg><use href="#i-search"/></svg>
              <input type="search" id="probe-entry-search" placeholder="Search playlist…" value="${esc(state.entryFilter)}">
            </div>
            <button type="button" class="btn tiny ghost" id="probe-select-all">Select All</button>
            <button type="button" class="btn tiny ghost" id="probe-select-none">Clear</button>
          </div>
        </div>
        <div class="probe-playlist-list" id="probe-playlist-items">
          ${visibleEntries.map((e) => {
            const isSel = state.selected.has(e.url);
            return `
              <div class="probe-entry-row ${isSel ? "is-selected" : ""}" data-entry-url="${esc(e.url)}">
                <input type="checkbox" class="probe-entry-checkbox" ${isSel ? "checked" : ""} data-url="${esc(e.url)}">
                <span class="probe-entry-num">#${e.index}</span>
                <span class="probe-entry-title" title="${esc(e.title)}">${esc(e.title || "Item #" + e.index)}</span>
                <span class="probe-entry-duration">${duration(e.duration)}</span>
              </div>`;
          }).join("")}
        </div>
      </div>`;
  }

  container.classList.remove("hidden");
  container.innerHTML = `
    <div class="probe-layout">
      <div class="probe-thumb-box">
        ${thumb}
        ${durationBadge}
      </div>
      <div class="probe-details">
        <h3 class="probe-title">${esc(probe.title || "Untitled Media")}</h3>
        <p class="probe-uploader">${esc(probe.uploader || "Unknown author")} · ${isPlaylist ? `${probe.entry_count} items` : `${(probe.qualities || []).length} formats found`}</p>
        <div class="probe-qualities">
          ${qualities || '<span class="muted">Standard formats available</span>'}
        </div>
      </div>
    </div>
    ${playlistPickerHTML}`;
}

async function analyze() {
  const url = $("#url").value.trim();
  if (!url) {
    toast("Please enter a media URL first", "warn");
    $("#url").focus();
    return;
  }
  const button = $("#analyze");
  setLoading(button, true, "Analyzing…");
  renderProbeLoading();
  try {
    const result = await api("/api/probe", {
      method: "POST",
      body: JSON.stringify({
        url,
        mode: value("mode") || "auto",
        cookies_file: value("cookieFile"),
        cookies_from_browser: value("browserCookies"),
        proxy: value("proxy"),
      }),
    });
    state.probe = result;
    state.probeUrl = url;
    state.selected.clear();
    for (const entry of result.entries || []) {
      state.selected.add(entry.url);
    }
    renderProbe();
    toast(`Found: ${result.title || "Media stream"}`, "ok");
  } catch (error) {
    state.probe = null;
    renderProbeError(error.message);
    toast(error.message, "err");
  } finally {
    setLoading(button, false);
  }
}

async function submitDownload(event) {
  if (event) event.preventDefault();
  const url = $("#url").value.trim();
  if (!url) {
    toast("Please paste a media URL to download", "warn");
    $("#url").focus();
    return;
  }
  const options = collectOptions();
  let entries = null;
  if (state.probe && state.probe.kind === "playlist" && state.probeUrl === url) {
    entries = (state.probe.entries || [])
      .filter((entry) => state.selected.has(entry.url))
      .map((entry) => ({ url: entry.url, title: entry.title, index: entry.index, duration: entry.duration }));
    if (!entries.length) {
      toast("Select at least one video from the playlist", "warn");
      return;
    }
  }

  const button = $("#submit");
  setLoading(button, true, "Adding…");
  try {
    const job = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        url,
        options,
        entries,
        title: state.probeUrl === url && state.probe ? state.probe.title : "",
      }),
    });
    toast(`Queued ${job.total_items} item${job.total_items === 1 ? "" : "s"}`, "ok");
    upsertJob(job);
    $("#url").value = "";
    state.probe = null;
    state.probeUrl = "";
    state.selected.clear();
    renderProbe();
    savePrefs();
    updateOverviewWidgets();
  } catch (error) {
    toast(error.message, "err");
  } finally {
    setLoading(button, false);
  }
}

/* ------------------------------------------------------------------ jobs */
function statusBadge(status) {
  const label = STATUS_LABELS[status] || status;
  return `<span class="status-badge ${esc(status)}">${esc(label)}</span>`;
}

function getSmoothedSpeed(job) {
  if (!job.speed || job.speed <= 0) {
    if (state.smoothedSpeeds) state.smoothedSpeeds.delete(job.id);
    return 0;
  }
  if (!state.smoothedSpeeds) state.smoothedSpeeds = new Map();
  const entry = state.smoothedSpeeds.get(job.id);
  const now = Date.now();
  const current = Number(job.speed);
  if (!entry) {
    state.smoothedSpeeds.set(job.id, { val: current, t: now });
    return current;
  }
  if (now - entry.t < 60) {
    return entry.val;
  }
  const smoothed = entry.val + (current - entry.val) * 0.35;
  state.smoothedSpeeds.set(job.id, { val: smoothed, t: now });
  return smoothed;
}

function jobMetaText(job) {
  const parts = [`${job.completed_items || 0}/${job.total_items || 1} completed`];
  if (job.failed_items) parts.push(`${job.failed_items} failed`);
  const liveSpeed = getSmoothedSpeed(job);
  if (liveSpeed > 0) parts.push(`${bytes(liveSpeed)}/s`);
  if (job.eta) parts.push(`ETA ${duration(job.eta)}`);
  return parts.join(" · ");
}

function jobCardHTML(job) {
  const percent = Math.max(0, Math.min(100, job.percent || 0));
  const canCancel = ["queued", "running", "downloading", "processing"].includes(job.status);
  const isInterrupted = ["interrupted", "cancelled", "partial"].includes(job.status);
  const isFailed = job.status === "failed" || (job.failed_items && job.failed_items > 0);
  const canResume = isInterrupted || isFailed;
  const isRunning = ["running", "downloading", "processing"].includes(job.status);

  const thumbUrl = getThumbnail(job);
  const thumbHTML = `
    <div class="job-thumb-wrap">
      ${thumbUrl ? `<img class="job-thumb" src="${esc(thumbUrl)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
      <svg><use href="#i-${job.options?.audio_only ? "music" : "film"}"/></svg>
    </div>`;

  const formatBadge = `
    <span class="job-format-badge">
      ${job.options?.audio_only ? `Audio · ${(job.options?.audio_format || "mp3").toUpperCase()}` : `${job.options?.quality || "best"} · ${(job.options?.container || "mp4").toUpperCase()}`}
    </span>`;

  const hasError = ["failed", "partial", "interrupted"].includes(job.status) && (job.error || (job.failed_items && job.failed_items > 0));
  const errorText = job.error || (job.failed_items ? `${job.failed_items} item(s) failed during download. Click Resume to resume or Restart to start over.` : "Download failed. Check URL or network access.");
  const errorHTML = hasError ? `
    <div class="job-error-banner">
      ${icon("alert")}
      <span>${esc(errorText)}</span>
    </div>` : "";

  let itemsAccordionHTML = "";
  if (job.items && job.items.length > 1) {
    itemsAccordionHTML = `
      <details class="job-items-accordion">
        <summary class="job-items-summary">
          <span>${job.completed_items || 0} of ${job.total_items} items detailed</span>
          <svg class="chev"><use href="#i-chevron"/></svg>
        </summary>
        <div class="job-items-list">
          ${job.items.map((item) => {
            const itemCanResume = ["interrupted", "cancelled", "failed"].includes(item.status);
            const itemPercent = Math.max(0, Math.min(100, item.percent || 0));
            return `
            <div class="job-item-row" data-item-id="${item.id}">
              <span class="job-item-title" title="${esc(item.title)}">#${item.index} ${esc(item.title || "Item")}</span>
              <div class="job-item-meta">
                ${item.status === "completed" ? `<span style="color:var(--green); font-weight:700;">${icon("check")} Done</span>` :
                  item.status === "failed" ? `<span style="color:var(--red); font-weight:700;" title="${esc(item.error)}">${icon("alert")} Failed</span>` :
                  item.status === "downloading" ? `<span style="color:var(--accent-text); font-weight:700;">${itemPercent.toFixed(0)}%</span>` :
                  item.status === "interrupted" ? `<span style="color:#D99B00; font-weight:700;">${itemPercent > 0 ? `${itemPercent.toFixed(0)}% (Paused)` : 'Paused'}</span>` :
                  `<span class="muted">${esc(item.status)}</span>`}
                ${item.filepath ? `<span class="muted">(${esc(baseName(item.filepath))})</span>` : ""}
                ${itemCanResume ? `<button type="button" class="btn micro primary" data-action="resume-item" data-job="${job.id}" data-item="${item.id}" title="Resume this item from partial progress">${icon("play")} Resume</button>` : ""}
              </div>
            </div>`;
          }).join("")}
        </div>
      </details>`;
  }

  const resumeBtnHTML = canResume
    ? `<button type="button" class="btn tiny primary resume-btn" data-action="resume" data-job="${job.id}" title="Resume download from partial progress">${icon("play")}<span>${percent > 0 ? `Resume (${percent.toFixed(0)}%)` : "Resume"}</span></button>`
    : "";
  const retryBtnHTML = canResume && (isFailed || isInterrupted)
    ? `<button type="button" class="btn tiny secondary" data-action="retry" data-job="${job.id}" title="Restart from beginning">${icon("retry")}<span>Restart</span></button>`
    : "";
  const cancelBtnHTML = canCancel
    ? `<button type="button" class="btn tiny danger" data-action="cancel" data-job="${job.id}">${icon("x")}<span>Cancel</span></button>`
    : "";

  const fillClasses = [
    "job-progress-fill",
    isRunning ? (job.status === "processing" ? "processing" : "is-active") : "",
    isRunning && percent === 0 ? "indeterminate" : "",
    job.status === "completed" ? "completed" : "",
  ].filter(Boolean).join(" ");

  return `
    <article class="job-card ${isRunning ? "is-active" : ""}" data-job="${job.id}" data-status="${job.status}">
      <div class="job-head">
        <div class="job-title-row">
          ${thumbHTML}
          <div style="min-width:0;">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px; flex-wrap:wrap;">
              ${statusBadge(job.status)}
              ${formatBadge}
            </div>
            <h3 class="job-title" title="${esc(job.title)}">${esc(job.title || "Media Download")}</h3>
          </div>
        </div>
        <div class="job-actions" data-last-status="${job.status}">
          ${resumeBtnHTML}
          ${retryBtnHTML}
          ${cancelBtnHTML}
          <button type="button" class="icon-btn" data-action="open" data-job="${job.id}" title="Open Folder">${icon("folder")}</button>
          <button type="button" class="icon-btn danger" data-action="delete" data-job="${job.id}" title="Delete Record">${icon("trash")}</button>
        </div>
      </div>
      <div class="job-progress-wrapper">
        <div class="job-progress-bar">
          <div class="${fillClasses}" style="width: ${percent}%;"></div>
        </div>
      </div>
      <div class="job-meta-row">
        <span>${job.status === "processing" ? "Processing streams (FFmpeg muxing/embedding)…" : jobMetaText(job)}</span>
        <span>${percent.toFixed(percent < 10 ? 1 : 0)}% (${bytes(job.downloaded)} / ${bytes(job.total_bytes)})</span>
      </div>
      ${errorHTML}
      ${itemsAccordionHTML}
    </article>`;
}

function patchJobCard(card, job) {
  const percent = Math.max(0, Math.min(100, job.percent || 0));
  const isRunning = ["running", "downloading", "processing"].includes(job.status);
  const isInterrupted = ["interrupted", "cancelled", "partial"].includes(job.status);
  const isFailed = job.status === "failed" || (job.failed_items && job.failed_items > 0);
  const canResume = isInterrupted || isFailed;

  card.classList.toggle("is-active", isRunning);
  card.dataset.status = job.status;

  // Status badge update
  const badgeWrap = card.querySelector(".job-head .status-badge");
  if (badgeWrap && !badgeWrap.classList.contains(job.status)) {
    badgeWrap.outerHTML = statusBadge(job.status);
  }

  // Progress fill update
  const fill = card.querySelector(".job-progress-fill");
  if (fill) {
    fill.style.width = `${percent}%`;
    fill.className = [
      "job-progress-fill",
      isRunning ? (job.status === "processing" ? "processing" : "is-active") : "",
      isRunning && percent === 0 ? "indeterminate" : "",
      job.status === "completed" ? "completed" : "",
    ].filter(Boolean).join(" ");
  }

  // Meta row update
  const metaRow = card.querySelector(".job-meta-row");
  if (metaRow) {
    const leftText = job.status === "processing" ? "Processing streams (FFmpeg muxing/embedding)…" : jobMetaText(job);
    const rightText = `${percent.toFixed(percent < 10 ? 1 : 0)}% (${bytes(job.downloaded)} / ${bytes(job.total_bytes)})`;
    const spans = metaRow.querySelectorAll("span");
    if (spans.length >= 2) {
      if (spans[0].textContent !== leftText) spans[0].textContent = leftText;
      if (spans[1].textContent !== rightText) spans[1].textContent = rightText;
    }
  }

  // Actions update when status transitions or percent changes
  const actionsWrap = card.querySelector(".job-actions");
  if (actionsWrap) {
    if (actionsWrap.dataset.lastStatus !== job.status) {
      actionsWrap.dataset.lastStatus = job.status;
      const canCancel = ["queued", "running", "downloading", "processing"].includes(job.status);

      const resumeBtn = canResume
        ? `<button type="button" class="btn tiny primary resume-btn" data-action="resume" data-job="${job.id}" title="Resume download from partial progress">${icon("play")}<span>${percent > 0 ? `Resume (${percent.toFixed(0)}%)` : "Resume"}</span></button>`
        : "";
      const retryBtn = canResume && (isFailed || isInterrupted)
        ? `<button type="button" class="btn tiny secondary" data-action="retry" data-job="${job.id}" title="Restart from beginning">${icon("retry")}<span>Restart</span></button>`
        : "";
      const cancelBtn = canCancel
        ? `<button type="button" class="btn tiny danger" data-action="cancel" data-job="${job.id}">${icon("x")}<span>Cancel</span></button>`
        : "";

      actionsWrap.innerHTML = `
        ${resumeBtn}
        ${retryBtn}
        ${cancelBtn}
        <button type="button" class="icon-btn" data-action="open" data-job="${job.id}" title="Open Folder">${icon("folder")}</button>
        <button type="button" class="icon-btn danger" data-action="delete" data-job="${job.id}" title="Delete Record">${icon("trash")}</button>
      `;
    } else if (canResume) {
      const resumeSpan = actionsWrap.querySelector(".resume-btn span");
      const resumeText = percent > 0 ? `Resume (${percent.toFixed(0)}%)` : "Resume";
      if (resumeSpan && resumeSpan.textContent !== resumeText) {
        resumeSpan.textContent = resumeText;
      }
    }
  }

  // Error banner update
  const hasError = ["failed", "partial", "interrupted"].includes(job.status) && (job.error || (job.failed_items && job.failed_items > 0));
  const errorText = job.error || (job.failed_items ? `${job.failed_items} item(s) failed during download. Click Resume to resume or Restart to start over.` : "Download failed. Check URL or network access.");
  let banner = card.querySelector(".job-error-banner");
  if (hasError) {
    if (!banner) {
      banner = document.createElement("div");
      banner.className = "job-error-banner";
      banner.innerHTML = `${icon("alert")}<span>${esc(errorText)}</span>`;
      if (metaRow) metaRow.after(banner);
      else card.appendChild(banner);
    } else {
      const span = banner.querySelector("span");
      if (span && span.textContent !== errorText) span.textContent = errorText;
    }
  } else if (banner) {
    banner.remove();
  }

  // Update accordion summary count if present
  const summarySpan = card.querySelector(".job-items-summary span");
  if (summarySpan) {
    const totalCount = job.total_items || (job.items ? job.items.length : 1);
    const summaryText = `${job.completed_items || 0} of ${totalCount} items detailed`;
    if (summarySpan.textContent !== summaryText) summarySpan.textContent = summaryText;
  }

  // Update items in accordion if present
  if (job.items && job.items.length > 1) {
    job.items.forEach((item) => {
      const row = card.querySelector(`.job-item-row[data-item-id="${item.id}"]`);
      if (row) {
        const meta = row.querySelector(".job-item-meta");
        if (meta) {
          const itemCanResume = ["interrupted", "cancelled", "failed"].includes(item.status);
          const itemPercent = Math.max(0, Math.min(100, item.percent || 0));
          meta.innerHTML = `
            ${item.status === "completed" ? `<span style="color:var(--green); font-weight:700;">${icon("check")} Done</span>` :
              item.status === "failed" ? `<span style="color:var(--red); font-weight:700;" title="${esc(item.error)}">${icon("alert")} Failed</span>` :
              item.status === "downloading" ? `<span style="color:var(--accent-text); font-weight:700;">${itemPercent.toFixed(0)}%</span>` :
              item.status === "interrupted" ? `<span style="color:#D99B00; font-weight:700;">${itemPercent > 0 ? `${itemPercent.toFixed(0)}% (Paused)` : 'Paused'}</span>` :
              `<span class="muted">${esc(item.status)}</span>`}
            ${item.filepath ? `<span class="muted">(${esc(baseName(item.filepath))})</span>` : ""}
            ${itemCanResume ? `<button type="button" class="btn micro primary" data-action="resume-item" data-job="${job.id}" data-item="${item.id}" title="Resume this item from partial progress">${icon("play")} Resume</button>` : ""}
          `;
        }
      }
    });
  }
}

function renderJobs() {
  const container = $("#jobs");
  if (!container) return;

  let jobs = Array.from(state.jobs.values()).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

  // Filter tab filter
  if (state.queueFilter !== "all") {
    if (state.queueFilter === "running") {
      jobs = jobs.filter((j) => ["running", "downloading", "processing"].includes(j.status));
    } else {
      jobs = jobs.filter((j) => j.status === state.queueFilter);
    }
  }

  // Search filter
  if (state.queueSearch) {
    const q = state.queueSearch.toLowerCase();
    jobs = jobs.filter((j) => (j.title || "").toLowerCase().includes(q) || j.id.includes(q));
  }

  const existingCards = new Map();
  container.querySelectorAll(".job-card[data-job]").forEach((el) => {
    existingCards.set(el.dataset.job, el);
  });

  const jobIds = new Set(jobs.map((j) => j.id));
  existingCards.forEach((card, id) => {
    if (!jobIds.has(id)) {
      card.remove();
    }
  });

  let previousNode = null;
  jobs.forEach((job) => {
    let card = existingCards.get(job.id);
    if (!card) {
      const temp = document.createElement("div");
      temp.innerHTML = jobCardHTML(job).trim();
      card = temp.firstElementChild;
      if (previousNode) {
        previousNode.after(card);
      } else {
        container.prepend(card);
      }
    } else {
      patchJobCard(card, job);
      if (previousNode) {
        if (previousNode.nextElementSibling !== card) {
          previousNode.after(card);
        }
      } else {
        if (container.firstElementChild !== card) {
          container.prepend(card);
        }
      }
    }
    previousNode = card;
  });

  $("#empty")?.classList.toggle("hidden", jobs.length > 0);
  updateQueueMeta();
}

function updateQueueMeta() {
  const allJobs = Array.from(state.jobs.values());
  const active = allJobs.filter((j) => ["queued", "running", "downloading", "processing"].includes(j.status)).length;
  const resumable = allJobs.filter((j) => ["interrupted", "failed", "cancelled", "partial"].includes(j.status)).length;

  const countBadge = $("#queue-count");
  if (countBadge) countBadge.textContent = String(allJobs.length);

  const navBadge = $("#nav-queue-count");
  if (navBadge) navBadge.textContent = String(active);

  const clearBtn = $("#clear-finished");
  if (clearBtn) {
    clearBtn.disabled = !allJobs.some((j) => ["completed", "failed", "cancelled"].includes(j.status));
  }

  const resumeAllBtn = $("#resume-all-btn");
  if (resumeAllBtn) {
    resumeAllBtn.disabled = resumable === 0;
  }
}

/* ----------------------------------------------------- overview widgets */
function updateOverviewWidgets() {
  const jobs = Array.from(state.jobs.values());
  const active = jobs.filter((j) => ["queued", "running", "downloading", "processing"].includes(j.status)).length;
  const completed = jobs.filter((j) => j.status === "completed").length;
  const failed = jobs.filter((j) => ["failed", "partial"].includes(j.status)).length;
  const total = jobs.length;

  if ($("#stat-active")) $("#stat-active").textContent = String(active);
  if ($("#stat-completed")) $("#stat-completed").textContent = String(completed);
  if ($("#stat-failed")) $("#stat-failed").textContent = String(failed);
  if ($("#stat-total")) $("#stat-total").textContent = String(total);

  // Active Spotlight
  const activeJob = jobs.find((j) => ["running", "downloading", "processing"].includes(j.status));
  const spotlightSection = $("#overview-spotlight");
  const spotlightBody = $("#spotlight-content");

  if (activeJob && spotlightSection && spotlightBody) {
    spotlightSection.classList.remove("hidden");
    const percent = Math.max(0, Math.min(100, activeJob.percent || 0));
    const smoothedSpd = getSmoothedSpeed(activeJob);
    const activeJobId = activeJob.id;
    const isSameJob = spotlightBody.dataset.jobId === activeJobId;
    spotlightBody.dataset.jobId = activeJobId;

    const existingFill = spotlightBody.querySelector(".job-progress-fill");
    if (existingFill && isSameJob) {
      existingFill.style.width = `${percent}%`;
      const titleEl = spotlightBody.querySelector("h4");
      const pctEl = spotlightBody.querySelector("[data-spotlight-pct]");
      const speedEl = spotlightBody.querySelector("[data-spotlight-speed]");
      const bytesEl = spotlightBody.querySelector("[data-spotlight-bytes]");
      if (titleEl && titleEl.textContent !== (activeJob.title || "Active Download")) {
        titleEl.textContent = activeJob.title || "Active Download";
      }
      if (pctEl) pctEl.textContent = `${percent.toFixed(0)}%`;
      if (speedEl) speedEl.textContent = `${bytes(smoothedSpd)}/s · ETA ${duration(activeJob.eta)}`;
      if (bytesEl) bytesEl.textContent = `${bytes(activeJob.downloaded)} of ${bytes(activeJob.total_bytes)}`;
    } else {
      spotlightBody.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <h4 style="font-family:var(--font-heading); font-size:16px; font-weight:800;">${esc(activeJob.title || "Active Download")}</h4>
          <span data-spotlight-pct style="font-family:var(--font-mono); font-size:13px; font-weight:700;">${percent.toFixed(0)}%</span>
        </div>
        <div class="job-progress-bar" style="margin-bottom:10px;">
          <div class="job-progress-fill is-active" style="width:${percent}%;"></div>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:12.5px; color:var(--text-secondary); font-family:var(--font-mono); font-variant-numeric:tabular-nums;">
          <span data-spotlight-speed>${bytes(smoothedSpd)}/s · ETA ${duration(activeJob.eta)}</span>
          <span data-spotlight-bytes>${bytes(activeJob.downloaded)} of ${bytes(activeJob.total_bytes)}</span>
        </div>`;
    }
  } else if (spotlightSection) {
    if (spotlightBody) delete spotlightBody.dataset.jobId;
    spotlightSection.classList.add("hidden");
  }

  // Recent downloads list
  const recentContainer = $("#overview-recent-list");
  if (recentContainer) {
    const recentJobs = jobs.slice(0, 5);
    if (!recentJobs.length) {
      recentContainer.innerHTML = `<div class="empty-state" style="padding:28px;"><p class="muted">No recent downloads yet.</p></div>`;
    } else {
      recentContainer.innerHTML = recentJobs.map((job) => `
        <div class="recent-row">
          <div class="recent-left">
            ${statusBadge(job.status)}
            <div>
              <div class="recent-title">${esc(job.title || "Media Download")}</div>
              <div class="recent-meta">${formatDate(job.created_at)} · ${job.total_items} items</div>
            </div>
          </div>
          <button type="button" class="btn tiny secondary" data-action="open" data-job="${job.id}">${icon("folder")}<span>Folder</span></button>
        </div>`).join("");
    }
  }
}

/* ------------------------------------------------------------- history */
function renderHistory() {
  const tbody = $("#history-tbody");
  const empty = $("#history-empty");
  const table = $("#history-table");
  if (!tbody) return;

  let jobs = Array.from(state.jobs.values()).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

  if (state.historyFilter === "completed") {
    jobs = jobs.filter((j) => j.status === "completed");
  } else if (state.historyFilter === "failed") {
    jobs = jobs.filter((j) => ["failed", "partial", "cancelled"].includes(j.status));
  }

  if (state.historyFormat === "video") {
    jobs = jobs.filter((j) => !j.options?.audio_only);
  } else if (state.historyFormat === "audio") {
    jobs = jobs.filter((j) => j.options?.audio_only);
  }

  if (state.historySearch) {
    const q = state.historySearch.toLowerCase();
    jobs = jobs.filter((j) => (j.title || "").toLowerCase().includes(q));
  }

  if (!jobs.length) {
    tbody.innerHTML = "";
    table?.classList.add("hidden");
    empty?.classList.remove("hidden");
    return;
  }

  table?.classList.remove("hidden");
  empty?.classList.add("hidden");

  tbody.innerHTML = jobs.map((job) => {
    const thumbUrl = getThumbnail(job);
    const thumbHTML = `
      <div class="job-thumb-wrap" style="width:46px; height:32px;">
        ${thumbUrl ? `<img class="job-thumb" src="${esc(thumbUrl)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
        <svg style="width:14px; height:14px;"><use href="#i-${job.options?.audio_only ? "music" : "film"}"/></svg>
      </div>`;
    const formatLabel = job.options?.audio_only
      ? `Audio · ${(job.options?.audio_format || "mp3").toUpperCase()}`
      : `${job.options?.quality || "best"} · ${(job.options?.container || "mp4").toUpperCase()}`;

    return `
      <tr>
        <td data-label="Video">
          <div class="history-video-cell">
            ${thumbHTML}
            <div class="history-video-title" title="${esc(job.title)}">${esc(job.title || "Media Download")}</div>
          </div>
        </td>
        <td data-label="Format"><span class="probe-pill">${esc(formatLabel)}</span></td>
        <td data-label="Size">${bytes(job.total_bytes || job.downloaded)}</td>
        <td data-label="Date">${formatDate(job.created_at)}</td>
        <td data-label="Status">${statusBadge(job.status)}</td>
        <td data-label="Actions">
          <div class="history-actions-cell">
            <button type="button" class="icon-btn" data-action="open" data-job="${job.id}" title="Open Folder">${icon("folder")}</button>
            <button type="button" class="icon-btn danger" data-action="delete" data-job="${job.id}" title="Remove Record">${icon("trash")}</button>
          </div>
        </td>
      </tr>`;
  }).join("");
}

/* --------------------------------------------------------------- files */
async function loadFiles() {
  const grid = $("#files-grid");
  const empty = $("#files-empty");
  const countBadge = $("#files-count-badge");
  if (!grid) return;

  try {
    const query = state.filesSearch ? `?search=${encodeURIComponent(state.filesSearch)}` : "";
    const files = await api(`/api/files${query}`);
    state.files = files || [];

    const totalBytes = state.files.reduce((acc, f) => acc + (f.size || 0), 0);
    if (countBadge) {
      countBadge.textContent = `${state.files.length} file${state.files.length === 1 ? "" : "s"} · ${bytes(totalBytes)} total`;
    }

    if (!state.files.length) {
      grid.innerHTML = "";
      empty?.classList.remove("hidden");
      return;
    }

    empty?.classList.add("hidden");
    grid.innerHTML = state.files.map((file) => `
      <div class="file-card">
        <div class="file-top">
          <span class="file-ext-badge">${esc(file.extension || "bin")}</span>
          <div class="file-name" title="${esc(file.name)}">${esc(file.name)}</div>
        </div>
        <div class="file-details">
          <span>${bytes(file.size)}</span>
          <span>${formatDate(file.modified)}</span>
        </div>
        <div class="file-card-actions">
          <button type="button" class="btn tiny secondary" data-file-action="open" data-name="${esc(file.name)}" title="Open file">${icon("film")}<span>Open</span></button>
          <button type="button" class="btn tiny secondary" data-file-action="copy" data-path="${esc(file.path)}">${icon("copy")}<span>Copy Path</span></button>
          <button type="button" class="btn tiny danger" data-file-action="delete" data-name="${esc(file.name)}" title="Delete file from disk">${icon("trash")}</button>
        </div>
      </div>`).join("");
  } catch (error) {
    toast(`Could not load files: ${error.message}`, "err");
  }
}

async function cleanTempFiles() {
  const confirmed = await confirmModal(
    "Clean Incomplete Files",
    "Delete leftover .part and .ytdl download fragments from disk? This frees space from interrupted jobs.",
    "Clean Files",
    false
  );
  if (!confirmed) return;
  try {
    const result = await api("/api/files/clean-temp", { method: "POST" });
    toast(`Cleaned ${result.cleaned} temp file(s), freed ${bytes(result.bytes_freed)}`, "ok");
    loadFiles();
  } catch (error) {
    toast(`Could not clean temp files: ${error.message}`, "err");
  }
}

/* ------------------------------------------------------------------ sync */
function upsertJob(job) {
  state.jobs.set(job.id, job);
  renderJobs();
  if (state.currentPage === "overview") updateOverviewWidgets();
  if (state.currentPage === "history") renderHistory();
}

async function syncJobs() {
  if (state.syncPromise) return state.syncPromise;
  state.syncPromise = api("/api/jobs")
    .then((payload) => {
      state.jobs = new Map((payload.jobs || []).map((j) => [j.id, j]));
      renderJobs();
      if (state.currentPage === "overview") updateOverviewWidgets();
      if (state.currentPage === "history") renderHistory();
    })
    .catch(() => null)
    .finally(() => { state.syncPromise = null; });
  return state.syncPromise;
}

/* ----------------------------------------------------------- job actions */
async function handleJobAction(event) {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  const jobId = target.dataset.job;

  try {
    if (action === "cancel") {
      const confirmed = await confirmModal("Cancel Download", "Stop this active download job?", "Cancel Job", true);
      if (!confirmed) return;
      await api(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      toast("Cancellation requested", "warn");
    } else if (action === "resume") {
      await api(`/api/jobs/${jobId}/resume`, { method: "POST" });
      toast("Resuming download from partial progress…", "ok");
    } else if (action === "resume-item") {
      const itemId = target.dataset.item;
      await api(`/api/jobs/${jobId}/items/${itemId}/resume`, { method: "POST" });
      toast("Resuming item from partial progress…", "ok");
    } else if (action === "retry") {
      await api(`/api/jobs/${jobId}/retry`, { method: "POST" });
      toast("Restarting download…", "ok");
    } else if (action === "open") {
      await api(`/api/jobs/${jobId}/open`, { method: "POST" });
    } else if (action === "delete") {
      const confirmed = await confirmModal(
        "Remove Record",
        "Remove this download record from ClipFlow history? The downloaded file on disk will NOT be deleted.",
        "Remove",
        true
      );
      if (!confirmed) return;
      await api(`/api/jobs/${jobId}?delete_files=false`, { method: "DELETE" });
      state.jobs.delete(jobId);
      renderJobs();
      if (state.currentPage === "overview") updateOverviewWidgets();
      if (state.currentPage === "history") renderHistory();
      toast("Record removed", "ok");
      return;
    }
    setTimeout(syncJobs, 250);
  } catch (error) {
    toast(error.message, "err");
  }
}

async function handleFileAction(event) {
  const target = event.target.closest("[data-file-action]");
  if (!target) return;
  const action = target.dataset.fileAction;

  if (action === "open") {
    const fileName = target.dataset.name;
    try {
      await api(`/api/files/${encodeURIComponent(fileName)}/open`, { method: "POST" });
      toast(`Opened ${fileName}`, "ok");
    } catch (error) {
      toast(`Could not open file: ${error.message}`, "err");
    }
  } else if (action === "copy") {
    const path = target.dataset.path;
    await copyText(path);
  } else if (action === "delete") {
    const fileName = target.dataset.name;
    const confirmed = await confirmModal(
      "Delete File",
      `Are you sure you want to permanently delete "${fileName}" from disk?`,
      "Delete Permanently",
      true
    );
    if (!confirmed) return;
    try {
      await api(`/api/files/${encodeURIComponent(fileName)}`, { method: "DELETE" });
      toast(`Deleted ${fileName}`, "ok");
      loadFiles();
    } catch (error) {
      toast(`Could not delete file: ${error.message}`, "err");
    }
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  toast("File path copied to clipboard", "ok");
}

async function clearFinished() {
  const finished = Array.from(state.jobs.values()).filter((job) =>
    ["completed", "failed", "cancelled", "partial", "interrupted"].includes(job.status));
  if (!finished.length) return;

  const confirmed = await confirmModal(
    "Clear Finished",
    `Remove ${finished.length} finished download records? Output files on disk remain safe.`,
    "Clear",
    false
  );
  if (!confirmed) return;

  const button = $("#clear-finished");
  setLoading(button, true, "Clearing…");
  try {
    await Promise.all(finished.map((job) => api(`/api/jobs/${job.id}`, { method: "DELETE" }).catch(() => null)));
    await syncJobs();
    toast("Finished jobs cleared", "ok");
  } finally {
    setLoading(button, false);
  }
}

async function uploadCookies(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    toast("Uploading cookies…", "warn");
    const result = await api("/api/cookies", { method: "POST", body: form });
    $("#cookieFile").value = result.id;
    savePrefs();
    toast("Cookie file stored", "ok");
  } catch (error) {
    toast(error.message, "err");
  } finally {
    $("#cookieUpload").value = "";
  }
}

/* ------------------------------------------------------------------- sse */
function connectEvents() {
  if (state.es) {
    state.es.close();
    state.es = null;
  }
  const query = state.apiKey ? `?key=${encodeURIComponent(state.apiKey)}` : "";
  const source = new EventSource(`/api/events${query}`);
  state.es = source;

  source.onopen = () => {
    state.reconnect = 0;
    setConnection(true);
    stopPolling();
    syncJobs();
  };

  source.onerror = () => {
    setConnection(false);
    source.close();
    if (state.es === source) state.es = null;
    startPolling();
    const delay = Math.min(15000, 1000 * Math.pow(1.6, Math.min(state.reconnect, 6)));
    state.reconnect += 1;
    setTimeout(connectEvents, delay);
  };

  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "snapshot") {
        state.jobs = new Map((data.jobs || []).map((j) => [j.id, j]));
        renderJobs();
        if (state.currentPage === "overview") updateOverviewWidgets();
        if (state.currentPage === "history") renderHistory();
      } else if (data.type === "job") {
        upsertJob(data.job);
      }
    } catch {
      /* ignore malformed frame */
    }
  };
}

function setConnection(online) {
  const node = $("#conn");
  if (node) {
    node.classList.toggle("on", online);
    node.classList.toggle("off", !online);
    node.title = online ? "Live progress connected" : "Reconnecting to live progress…";
  }
}

function startPolling() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(syncJobs, 10000);
}

function stopPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

/* ------------------------------------------------------------------ init */
function bindEvents() {
  // Navigation tabs
  $$(".sidebar-nav .nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchPage(btn.dataset.page));
  });

  // Mobile nav toggle
  $("#mobile-nav-toggle")?.addEventListener("click", () => {
    $("#sidebar")?.classList.toggle("is-open");
  });

  // Theme switchers
  $("#theme-toggle")?.addEventListener("click", toggleTheme);
  $$(".theme-choice").forEach((choice) => {
    choice.addEventListener("click", () => applyTheme(choice.dataset.setTheme));
  });

  // Quick Action Buttons & Overview Quick Links
  $("#quick-new-btn")?.addEventListener("click", () => {
    switchPage("overview");
    $("#url")?.focus();
  });
  $("#spotlight-view-queue")?.addEventListener("click", () => switchPage("downloads"));
  $("#recent-view-all")?.addEventListener("click", () => switchPage("downloads"));
  $("#empty-new-btn")?.addEventListener("click", () => {
    switchPage("overview");
    $("#url")?.focus();
  });

  // Overview Quick Navigation Cards (Spec Section 4.1)
  $("#quick-to-downloads")?.addEventListener("click", () => switchPage("downloads"));
  $("#quick-to-history")?.addEventListener("click", () => switchPage("history"));
  $("#quick-to-files")?.addEventListener("click", () => switchPage("files"));

  // Topbar open directory
  $("#pill-dir")?.addEventListener("click", async () => {
    try {
      await api("/api/folder/open", { method: "POST" });
    } catch (e) {
      toast("Could not open folder: " + e.message, "err");
    }
  });

  // Files page actions
  $("#btn-open-dir")?.addEventListener("click", async () => {
    try {
      await api("/api/folder/open", { method: "POST" });
    } catch (e) {
      toast("Could not open folder: " + e.message, "err");
    }
  });
  $("#btn-refresh-files")?.addEventListener("click", loadFiles);
  $("#btn-clean-temp-files")?.addEventListener("click", cleanTempFiles);
  $("#settings-btn-clean-temp")?.addEventListener("click", cleanTempFiles);
  $("#files-search")?.addEventListener("input", (e) => {
    state.filesSearch = e.target.value.trim();
    loadFiles();
  });
  $("#files-grid")?.addEventListener("click", handleFileAction);

  // Settings page folder button
  $("#settings-btn-open-folder")?.addEventListener("click", async () => {
    try {
      await api("/api/folder/open", { method: "POST" });
    } catch (e) {
      toast("Could not open folder: " + e.message, "err");
    }
  });

  // Settings API key & data clear
  $("#btn-save-api-key")?.addEventListener("click", () => {
    const key = $("#settings-api-key").value.trim();
    state.apiKey = key;
    localStorage.setItem(KEY_STORE, key);
    toast("API key saved", "ok");
    connectEvents();
  });

  $("#btn-clear-local-data")?.addEventListener("click", async () => {
    const confirmed = await confirmModal("Clear Local Cache", "Reset local preferences and stored API key?", "Clear Cache", true);
    if (!confirmed) return;
    localStorage.removeItem(PREFS_STORE);
    localStorage.removeItem(KEY_STORE);
    state.apiKey = "";
    toast("Local cache cleared", "ok");
  });

  // Queue Filters
  $$("#queue-filters .filter-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$("#queue-filters .filter-tab").forEach((t) => t.classList.remove("is-active"));
      tab.classList.add("is-active");
      state.queueFilter = tab.dataset.filter;
      renderJobs();
    });
  });

  $("#queue-search")?.addEventListener("input", (e) => {
    state.queueSearch = e.target.value.trim();
    renderJobs();
  });

  // History Filters
  $$("#history-filters .filter-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$("#history-filters .filter-tab").forEach((t) => t.classList.remove("is-active"));
      tab.classList.add("is-active");
      state.historyFilter = tab.dataset.historyFilter;
      renderHistory();
    });
  });

  $$("#history-format-filters .filter-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$("#history-format-filters .filter-tab").forEach((t) => t.classList.remove("is-active"));
      tab.classList.add("is-active");
      state.historyFormat = tab.dataset.historyFormat;
      renderHistory();
    });
  });

  $("#history-search")?.addEventListener("input", (e) => {
    state.historySearch = e.target.value.trim();
    renderHistory();
  });

  // Overview / Composer Form
  $("#form")?.addEventListener("submit", submitDownload);
  $("#analyze")?.addEventListener("click", analyze);

  const urlInput = $("#url");
  const clearBtn = $("#clear-url");

  urlInput?.addEventListener("input", () => {
    const current = urlInput.value.trim();
    clearBtn?.classList.toggle("hidden", !current);
    if (state.probe && current !== state.probeUrl) {
      state.probe = null;
      state.probeUrl = "";
      state.selected.clear();
      state.entryFilter = "";
      renderProbe();
    }
  });

  clearBtn?.addEventListener("click", () => {
    urlInput.value = "";
    clearBtn.classList.add("hidden");
    state.probe = null;
    state.probeUrl = "";
    state.selected.clear();
    state.entryFilter = "";
    renderProbe();
    urlInput.focus();
  });

  urlInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      analyze();
    }
  });

  $("#paste")?.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text.trim()) return;
      urlInput.value = text.trim();
      clearBtn?.classList.remove("hidden");
      analyze();
    } catch {
      toast("Clipboard access was blocked — paste manually", "warn");
      urlInput?.focus();
    }
  });

  $("#quality-chips")?.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) return;
    setQuality(chip.dataset.quality);
  });

  $("#audioOnly")?.addEventListener("change", syncAudioUI);
  $("#cookieUpload")?.addEventListener("change", (e) => uploadCookies(e.target.files[0]));
  $("#clear-finished")?.addEventListener("click", clearFinished);
  $("#pref-resume-partial")?.addEventListener("change", (e) => {
    const resumeEl = $("#resume");
    if (resumeEl) resumeEl.checked = e.target.checked;
    savePrefs();
  });
  $("#resume")?.addEventListener("change", (e) => {
    const prefEl = $("#pref-resume-partial");
    if (prefEl) prefEl.checked = e.target.checked;
    savePrefs();
  });
  $("#resume-all-btn")?.addEventListener("click", async () => {
    try {
      const res = await api("/api/jobs/resume-all", { method: "POST" });
      const count = res.resumed || 0;
      toast(count > 0 ? `Resumed ${count} download(s)` : "No unfinished downloads to resume", "ok");
      setTimeout(syncJobs, 250);
    } catch (e) {
      toast("Could not resume downloads: " + e.message, "err");
    }
  });

  $("#form")?.addEventListener("input", savePrefs);
  $("#form")?.addEventListener("change", savePrefs);

  // Probe interaction: Qualities, Playlist search, selection toggle
  const probeContainer = $("#probe");
  probeContainer?.addEventListener("click", (event) => {
    const quality = event.target.closest("[data-set-quality]");
    if (quality) {
      const height = quality.dataset.setQuality;
      const known = ["best", "2160", "1440", "1080", "720", "480", "360", "worst"];
      setQuality(known.includes(height) ? height : "best");
      return;
    }

    if (event.target.closest("#probe-select-all")) {
      if (state.probe && state.probe.entries) {
        state.probe.entries.forEach((e) => state.selected.add(e.url));
        renderProbe();
      }
      return;
    }

    if (event.target.closest("#probe-select-none")) {
      state.selected.clear();
      renderProbe();
      return;
    }

    const entryRow = event.target.closest(".probe-entry-row");
    if (entryRow) {
      const url = entryRow.dataset.entryUrl;
      const checkbox = entryRow.querySelector(".probe-entry-checkbox");
      if (state.selected.has(url)) {
        state.selected.delete(url);
        entryRow.classList.remove("is-selected");
        if (checkbox) checkbox.checked = false;
      } else {
        state.selected.add(url);
        entryRow.classList.add("is-selected");
        if (checkbox) checkbox.checked = true;
      }
      const countEl = $("#probe-selected-count");
      if (countEl) countEl.textContent = String(state.selected.size);
    }
  });

  probeContainer?.addEventListener("input", (event) => {
    if (event.target.id === "probe-entry-search") {
      state.entryFilter = event.target.value.trim();
      renderProbe();
      const input = $("#probe-entry-search");
      if (input) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
    }
  });

  // Job Cards list click delegation
  $("#jobs")?.addEventListener("click", handleJobAction);
  $("#history-tbody")?.addEventListener("click", handleJobAction);

  // Global Shortcuts
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      $("#form")?.requestSubmit();
    }
    if (event.key === "/" && document.activeElement !== urlInput && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
      event.preventDefault();
      switchPage("overview");
      urlInput?.focus();
    }
  });
}

async function init() {
  applyTheme(state.theme);
  loadPrefs();
  bindEvents();
  renderProbe();
  renderJobs();
  setConnection(false);
  await loadSystem();
  connectEvents();
  startPolling();
  setInterval(loadSystem, 60000);
}

init();
