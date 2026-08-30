"use strict";

const state = {
  overview: {},
  analytics: {},
  miners: [],
  blocks: [],
  node: {},
  config: {},
  history: [],
  historyHours: 1,
  chartPoints: [],
  query: "",
  refreshing: false,
};

const trNumber = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 2 });

function byId(id) { return document.getElementById(id); }

function text(id, value) {
  const element = byId(id);
  if (element) element.textContent = value;
}

function visible(id, show) {
  const element = byId(id);
  if (element) element.hidden = !show;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function finite(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number : 0;
}

function formatNumber(value, maximumFractionDigits = 0) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("tr-TR", { maximumFractionDigits }).format(finite(value));
}

function formatHashrate(value) {
  if (value === null || value === undefined) return "—";
  let number = finite(value);
  const units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s", "ZH/s"];
  let unit = 0;
  while (Math.abs(number) >= 1000 && unit < units.length - 1) {
    number /= 1000;
    unit += 1;
  }
  const digits = number >= 100 ? 0 : number >= 10 ? 1 : 2;
  return `${number.toLocaleString("tr-TR", { maximumFractionDigits: digits })} ${units[unit]}`;
}

function formatDifficulty(value) {
  if (value === null || value === undefined) return "—";
  let number = finite(value);
  const units = ["", "K", "M", "G", "T", "P", "E", "Z"];
  let unit = 0;
  while (Math.abs(number) >= 1000 && unit < units.length - 1) {
    number /= 1000;
    unit += 1;
  }
  const digits = number >= 100 ? 0 : number >= 10 ? 1 : 2;
  return `${number.toLocaleString("tr-TR", { maximumFractionDigits: digits })}${units[unit]}`;
}

function formatBytes(value) {
  let number = finite(value);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let unit = 0;
  while (number >= 1024 && unit < units.length - 1) {
    number /= 1024;
    unit += 1;
  }
  const digits = number >= 100 ? 0 : number >= 10 ? 1 : 2;
  return `${number.toLocaleString("tr-TR", { maximumFractionDigits: digits })} ${units[unit]}`;
}

function formatDuration(value) {
  if (value === null || value === undefined) return "—";
  let seconds = Math.max(0, Math.floor(finite(value)));
  const days = Math.floor(seconds / 86400);
  seconds %= 86400;
  const hours = Math.floor(seconds / 3600);
  seconds %= 3600;
  const minutes = Math.floor(seconds / 60);
  if (days) return `${days}g ${hours}s`;
  if (hours) return `${hours}s ${minutes}dk`;
  if (minutes) return `${minutes}dk`;
  return `${seconds}sn`;
}

function formatAgo(value) {
  if (!value) return "—";
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (seconds < 5) return "şimdi";
  if (seconds < 60) return `${seconds} sn önce`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} dk önce`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} sa önce`;
  return new Date(value).toLocaleString("tr-TR");
}

function shortHash(value, lead = 10, tail = 8) {
  const string = String(value || "");
  if (!string) return "—";
  return string.length > lead + tail + 3
    ? `${string.slice(0, lead)}…${string.slice(-tail)}`
    : string;
}

function initials(worker) {
  return String(worker || "W").replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() || "W";
}

async function getJson(url) {
  const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

async function safeJson(url, fallback) {
  try { return await getJson(url); }
  catch (error) { return fallback; }
}

function setBadge(element, label, tone = "muted") {
  if (!element) return;
  element.textContent = label;
  element.className = `status-badge ${tone}`;
}

function nodeDisplayName() {
  const name = String(state.node.node_name || "").trim();
  return ["Bitcoin Core", "Bitcoin Knots"].includes(name) ? name : "Bitcoin Node";
}

function setSystemStatus() {
  const poolOnline = Boolean(state.overview.online);
  const nodeOnline = Boolean(state.node.online);
  const nodeName = nodeDisplayName();
  const topDot = byId("top-status-dot");
  const sideDot = byId("side-health-dot");

  [topDot, sideDot].forEach((dot) => {
    if (!dot) return;
    dot.classList.remove("online", "warning");
  });

  if (poolOnline && nodeOnline && state.overview.metrics_available !== false) {
    topDot?.classList.add("online");
    sideDot?.classList.add("online");
    text("top-status-text", "Çevrimiçi");
    text("side-health-title", "Sistem sağlıklı");
    text("side-health-copy", `Havuz ve ${nodeName} çevrimiçi`);
  } else if (poolOnline || nodeOnline) {
    topDot?.classList.add("warning");
    sideDot?.classList.add("warning");
    text("top-status-text", "Kısmi erişim");
    text("side-health-title", "Kısmi bağlantı");
    text("side-health-copy", poolOnline && state.overview.metrics_available === false
      ? "Havuz çalışıyor; güncel istatistik bekleniyor"
      : poolOnline ? "Havuz çevrimiçi" : `${nodeName} çevrimiçi`);
  } else {
    text("top-status-text", "Çevrimdışı");
    text("side-health-title", "Bağlantı yok");
    text("side-health-copy", "Servisler kontrol ediliyor");
  }
}

function renderOverview() {
  const data = state.overview;
  text("pool-hashrate", formatHashrate(data.hashrate_1m));
  text("pool-hashrate-5m", formatHashrate(data.hashrate_5m));
  text("pool-uptime", formatDuration(data.uptime_seconds));
  text("active-workers", formatNumber(data.workers));
  text("connection-count", `${formatNumber(data.connections)} bağlantı`);
  text("best-share", formatDifficulty(data.best_share));
  text("block-count", formatNumber(data.blocks));
  text("pool-data-age", data.metrics_available === false ? "Güncel veri yok"
    : data.data_source === "status-files" ? `Dosya · ${formatDuration(data.stats_age_seconds)} önce`
    : data.data_source === "socket-api" ? "Canlı API" : "Veri bekleniyor");
  text("nav-worker-count", formatNumber(data.workers));
  text("miners-page-count", `${formatNumber(data.workers)} worker`);
  text("blocks-page-count", `${formatNumber(data.blocks)} blok`);
}

function renderAnalytics() {
  const data = state.analytics;
  text("average-hashrate", formatHashrate(data.avg_hashrate_6h));
  text("peak-hashrate", formatHashrate(data.peak_hashrate_6h));
  text("round-diff", formatDifficulty(data.round_diff));
  text("network-diff", formatDifficulty(data.network_difficulty));
  const effort = Math.max(0, finite(data.round_effort_pct));
  visible("round-effort-card", data.round_effort_pct != null);
  const effortLabel = effort < .01 ? effort.toFixed(5) : effort < 1 ? effort.toFixed(3) : effort.toFixed(2);
  text("round-effort", data.round_effort_pct == null ? "—" : `${effortLabel}%`);
  const effortDegrees = Math.min(effort, 100) * 3.6;
  byId("effort-ring")?.style.setProperty("background", `conic-gradient(var(--lime) ${effortDegrees}deg, #edf0ee ${effortDegrees}deg)`);

  visible("pool-totals-card", data.pool_totals_available === true);
  text("pool-accepted-diff", formatDifficulty(data.pool_accepted_diff));
  text("pool-rejected-diff", formatDifficulty(data.pool_rejected_diff));
  byId("pool-accepted-diff")?.setAttribute("title", `${formatNumber(data.pool_accepted_diff)} diff`);
  byId("pool-rejected-diff")?.setAttribute("title", `${formatNumber(data.pool_rejected_diff)} diff`);
  const rate = data.pool_acceptance_pct;
  text("pool-acceptance-rate", rate == null ? "—" : `${finite(rate).toFixed(3)}%`);
  byId("pool-accepted-bar")?.style.setProperty("width", `${Math.max(0, Math.min(100, finite(rate)))}%`);
  text("pool-totals-source", `${data.pool_totals_source === "status-files" ? "pool.status" : "CKPool API"} · CKPool sayaçlarının son sıfırlanmasından itibaren. Saatlik adet değildir.`);
}

function filteredMiners() {
  const onlineMiners = state.miners.filter((miner) => miner.status === "online");
  const query = state.query.trim().toLowerCase();
  if (!query) return onlineMiners;
  return onlineMiners.filter((miner) => [
    miner.worker_name,
    miner.btc_address,
  ].some((value) => String(value || "").toLowerCase().includes(query)));
}

function renderMiners() {
  const rows = filteredMiners();
  const table = byId("miners-table");
  const online = state.miners.filter((miner) => miner.status === "online").length;
  const activity = state.miners.some((miner) => miner.status_source === "recent-share") ? "aktif" : "çevrimiçi";
  text("miners-source-note", state.overview.data_source === "status-files" || activity === "aktif"
    ? "Son 3 dakikada share gönderen worker’lar · Dosyalar yaklaşık dakikada bir yenilenir"
    : "CKPool worker istatistikleri");
  setBadge(byId("miners-table-status"), `${online} ${activity}`, online ? "" : "muted");
  if (!table) return;

  if (!rows.length) {
    table.innerHTML = '<tr><td colspan="6"><div class="empty-state">Eşleşen aktif madenci bulunamadı.</div></td></tr>';
    return;
  }

  table.innerHTML = rows.map((miner) => {
    const onlineTone = miner.status === "online" ? "" : "muted";
    const inferred = miner.status_source === "recent-share";
    const status = inferred ? "AKTİF" : miner.status === "online" ? "ONLINE" : "OFFLINE";
    const agent = `<small title="${escapeHtml(miner.btc_address)}">${escapeHtml(shortHash(miner.btc_address, 16, 10))}</small>`;
    return `<tr>
      <td><div class="worker-cell"><span class="worker-avatar">${escapeHtml(initials(miner.worker_name))}</span><div><strong>${escapeHtml(miner.worker_name || "worker")}</strong>${agent}</div></div></td>
      <td><span class="status-badge ${onlineTone}" title="${inferred ? 'Son 3 dakikadaki paylaşım etkinliğine göre; anlık bağlantı listesi değil' : 'Canlı bağlantı'}">${status}</span></td>
      <td><strong>${formatHashrate(miner.hashrate)}</strong><div class="muted-text">5dk ${formatHashrate(miner.hashrate_5m)}</div></td>
      <td><strong>${formatDifficulty(miner.best_share_difficulty)}</strong></td>
      <td title="${formatNumber(miner.accepted_difficulty)} diff"><strong>${formatDifficulty(miner.accepted_difficulty)}</strong></td>
      <td><strong>${escapeHtml(formatAgo(miner.last_share_at))}</strong></td>
    </tr>`;
  }).join("");
}

function renderBlocks() {
  const table = byId("blocks-table");
  if (!table) return;
  if (!state.blocks.length) {
    table.innerHTML = '<tr><td colspan="6"><div class="empty-state">Henüz blok bulunmadı. İlk blok burada görünecek.</div></td></tr>';
    return;
  }
  table.innerHTML = state.blocks.map((block) => {
    const effort = block.net_difficulty > 0 ? finite(block.round_effort) / finite(block.net_difficulty) * 100 : 0;
    const reward = finite(block.reward_value) / 100000000;
    return `<tr>
      <td><strong>#${formatNumber(block.height)}</strong></td>
      <td class="mono" title="${escapeHtml(block.block_hash)}">${escapeHtml(shortHash(block.block_hash, 13, 10))}</td>
      <td><strong>${escapeHtml(block.worker_name || "—")}</strong><div class="muted-text">${escapeHtml(shortHash(block.btc_address, 11, 7))}</div></td>
      <td><strong>${reward.toLocaleString("tr-TR", { maximumFractionDigits: 8 })} BTC</strong></td>
      <td>${effort ? `${effort.toFixed(3)}%` : "—"}</td>
      <td>${escapeHtml(new Date(block.found_at).toLocaleString("tr-TR"))}</td>
    </tr>`;
  }).join("");
}

function renderNode() {
  const node = state.node;
  const nodeName = nodeDisplayName();
  const online = Boolean(node.online);
  const sync = Math.max(0, Math.min(100, finite(node.sync_percent)));
  const degrees = sync * 3.6;
  const nodePageStatus = byId("node-page-status");
  nodePageStatus?.classList.remove("online", "warning");
  if (online) nodePageStatus?.classList.add("online");
  const nodeStatusStrong = nodePageStatus?.querySelector("strong");
  if (nodeStatusStrong) nodeStatusStrong.textContent = online ? "Çevrimiçi" : "Bağlantı yok";

  text("nav-node-name", nodeName);
  text("mini-node-name", nodeName.toLocaleUpperCase("tr-TR"));
  text("node-page-name", nodeName);

  text("mini-sync", `${sync.toFixed(sync >= 99 ? 2 : 1)}%`);
  text("mini-node-height", online ? formatNumber(node.blocks) : "—");
  text("mini-peers", online ? formatNumber(node.connections) : "—");
  text("mini-mempool", online ? formatNumber(node.mempool?.transactions) : "—");
  text("mini-disk", online ? formatBytes(node.size_on_disk) : "—");
  setBadge(byId("mini-node-status"), online ? "ONLINE" : "OFFLINE", online ? "" : "danger");
  byId("mini-sync-ring")?.style.setProperty("background", `conic-gradient(var(--lime) ${degrees}deg, #edf0ee ${degrees}deg)`);

  text("node-sync-percent", `${sync.toFixed(sync >= 99 ? 3 : 1)}%`);
  byId("node-sync-ring")?.style.setProperty("background", `conic-gradient(var(--lime) ${degrees}deg, #edf0ee ${degrees}deg)`);
  setBadge(byId("node-chain-badge"), String(node.chain || "MAIN").toUpperCase(), online ? "" : "muted");
  text("node-blocks", online ? formatNumber(node.blocks) : "—");
  text("node-headers", online ? `${formatNumber(node.headers)} header` : "— header");
  text("node-tip-age", online ? `Son blok: ${formatDuration(node.tip_age_seconds)} önce` : "Son blok: —");
  text("node-version", node.subversion || "—");
  text("node-uptime", online ? formatDuration(node.uptime_seconds) : "—");
  text("node-protocol", node.protocol_version ? formatNumber(node.protocol_version) : "—");
  text("node-network-active", online ? (node.network_active ? "Aktif" : "Kapalı") : "—");
  text("node-connections", online ? formatNumber(node.connections) : "0");
  text("node-connections-in", online ? formatNumber(node.connections_in) : "0");
  text("node-connections-out", online ? formatNumber(node.connections_out) : "0");
  text("node-mempool-count", online ? formatNumber(node.mempool?.transactions) : "0");
  text("node-mempool-bytes", online ? formatBytes(node.mempool?.bytes) : "—");
  text("node-mempool-usage", online ? formatBytes(node.mempool?.usage) : "—");
  text("node-mempool-fee", online ? `${finite(node.mempool?.total_fee).toFixed(8)} BTC` : "—");
  text("node-disk-size", online ? formatBytes(node.size_on_disk) : "—");
  text("node-prune-state", online ? (node.pruned ? "Pruned node" : "Full node") : "—");
  text("node-prune-height", online && node.pruned ? formatNumber(node.prune_height) : "—");
  text("node-best-hash", online ? shortHash(node.bestblockhash, 9, 7) : "—");
  byId("node-best-hash")?.setAttribute("title", node.bestblockhash || "");
  text("node-difficulty", online ? formatDifficulty(node.difficulty) : "—");
  text("node-network-hashrate", online ? formatHashrate(node.network_hashrate) : "—");
  text("node-pooled-tx", online ? formatNumber(node.pooled_transactions) : "—");

  const indexes = node.indexes && typeof node.indexes === "object" ? Object.entries(node.indexes) : [];
  const indexList = byId("node-index-list");
  if (indexList) {
    indexList.innerHTML = indexes.length ? indexes.map(([name, value]) => `<div class="index-row"><span title="${escapeHtml(name)}">${escapeHtml(name)}</span><b class="status-badge ${value.synced ? "" : "warning"}">${value.synced ? "SENKRON" : "BEKLİYOR"} · ${formatNumber(value.best_block_height)}</b></div>`).join("") : '<div class="empty-state">Aktif indeks bulunamadı.</div>';
  }

  const tips = node.chain_tips && typeof node.chain_tips === "object" ? Object.entries(node.chain_tips) : [];
  const tipGrid = byId("chain-tips");
  if (tipGrid) tipGrid.innerHTML = tips.length ? tips.map(([status, count]) => `<div class="chain-tip"><span>${escapeHtml(status)}</span><strong>${formatNumber(count)}</strong></div>`).join("") : '<div class="empty-state">Zincir ucu bilgisi bulunamadı.</div>';
}

function renderConfig() {
  const config = state.config;
  text("config-sv1", `TCP :${config.sv1_port || 3333}`);
  text("config-sv2", config.sv2_enabled === false ? "Devre dışı" : `TCP :${config.sv2_port || 3336}`);
  visible("config-sv2-card", config.sv2_enabled === true);
  const difficultySettings = [["Başlangıç", config.starting_difficulty], ["Min", config.vardiff_min], ["Max", config.vardiff_max]]
    .filter(([, value]) => value != null);
  visible("config-difficulty-card", difficultySettings.length > 0);
  text("config-difficulty", difficultySettings.map(([label, value]) => `${label}: ${formatDifficulty(value)}`).join(" · "));
  visible("config-coinbase-card", Boolean(config.coinbase_signature));
  text("config-coinbase", config.coinbase_signature || "—");
  text("sv2-port-badge", config.sv2_enabled === false ? "KAPALI" : `TCP :${config.sv2_port || 3336}`);

  const publicKey = String(config.sv2_public_key || "");
  const fingerprint = String(config.sv2_public_key_fingerprint || "");
  const hasPublicKey = config.sv2_enabled === true && publicKey.length > 0;
  visible("sv2-key-card", hasPublicKey);
  byId("overview-top-grid")?.classList.toggle("single-column", !hasPublicKey);
  const keyElement = byId("sv2-public-key");
  const copyButton = byId("copy-sv2-key");
  if (keyElement) {
    keyElement.textContent = publicKey;
    keyElement.dataset.value = publicKey;
  }
  text(
    "sv2-key-fingerprint",
    fingerprint
      ? `Fingerprint: ${fingerprint.match(/.{1,4}/g).join(" ")}`
      : "Fingerprint: —",
  );
  if (copyButton) copyButton.disabled = !publicKey;
}

function renderAll() {
  renderOverview();
  renderAnalytics();
  renderMiners();
  renderBlocks();
  renderNode();
  renderConfig();
  setSystemStatus();
}

async function refreshMain({ manual = false } = {}) {
  if (state.refreshing) return;
  state.refreshing = true;
  const refreshButton = byId("refresh-button");
  refreshButton?.classList.add("loading");

  const endpoints = [
    ["overview", "/api/overview"],
    ["analytics", "/api/analytics"],
    ["miners", "/api/miners"],
    ["blocks", "/api/blocks"],
    ["node", "/api/node"],
    ["config", "/api/config"],
  ];

  const values = await Promise.all(
    endpoints.map(([key, url]) => safeJson(url, state[key])),
  );
  endpoints.forEach(([key], index) => { state[key] = values[index]; });
  renderAll();

  const now = new Date();
  text("last-refresh", `Güncellendi ${now.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`);
  refreshButton?.classList.remove("loading");
  state.refreshing = false;
  if (manual) showToast("Dashboard verileri yenilendi.");
}

async function refreshHistory() {
  state.history = await safeJson(
    `/api/history?hours=${state.historyHours}`,
    state.history,
  );
  drawChart();
}

function drawChart() {
  const canvas = byId("hashrate-chart");
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);

  const width = rect.width;
  const height = rect.height;
  const padding = { left: 12, right: 12, top: 15, bottom: 25 };
  const graphWidth = width - padding.left - padding.right;
  const graphHeight = height - padding.top - padding.bottom;
  context.clearRect(0, 0, width, height);

  context.strokeStyle = "#e7ece9";
  context.lineWidth = 1;
  context.setLineDash([4, 5]);
  for (let index = 0; index < 5; index += 1) {
    const y = padding.top + graphHeight * index / 4;
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();
  }
  context.setLineDash([]);

  if (!state.history.length) {
    context.fillStyle = "#94a099";
    context.font = "11px system-ui";
    context.textAlign = "center";
    context.fillText("Hashrate geçmişi oluşuyor…", width / 2, height / 2);
    state.chartPoints = [];
    return;
  }

  const maxValue = Math.max(...state.history.map((point) => finite(point.hashrate)), 1) * 1.12;
  state.chartPoints = state.history.map((point, index) => ({
    raw: point,
    x: padding.left + index / Math.max(state.history.length - 1, 1) * graphWidth,
    y: padding.top + graphHeight - finite(point.hashrate) / maxValue * graphHeight,
  }));

  const fill = context.createLinearGradient(0, padding.top, 0, height - padding.bottom);
  fill.addColorStop(0, "rgba(181,238,16,.30)");
  fill.addColorStop(.72, "rgba(181,238,16,.05)");
  fill.addColorStop(1, "rgba(181,238,16,0)");

  context.beginPath();
  context.moveTo(state.chartPoints[0].x, height - padding.bottom);
  state.chartPoints.forEach((point) => context.lineTo(point.x, point.y));
  context.lineTo(state.chartPoints.at(-1).x, height - padding.bottom);
  context.closePath();
  context.fillStyle = fill;
  context.fill();

  context.beginPath();
  state.chartPoints.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
  context.strokeStyle = "#0b3929";
  context.lineWidth = 2.5;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.stroke();

  const first = new Date(finite(state.history[0].time) * 1000);
  const last = new Date(finite(state.history.at(-1).time) * 1000);
  context.fillStyle = "#8a9891";
  context.font = "9px system-ui";
  context.textAlign = "left";
  context.fillText(first.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }), padding.left, height - 5);
  context.textAlign = "right";
  context.fillText(last.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }), width - padding.right, height - 5);
}

function chartMove(event) {
  if (!state.chartPoints.length) return;
  const canvas = byId("hashrate-chart");
  const tooltip = byId("chart-tooltip");
  if (!canvas || !tooltip) return;
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  let nearest = state.chartPoints[0];
  state.chartPoints.forEach((point) => {
    if (Math.abs(point.x - x) < Math.abs(nearest.x - x)) nearest = point;
  });
  text("chart-tooltip-time", new Date(finite(nearest.raw.time) * 1000).toLocaleString("tr-TR"));
  text("chart-tooltip-value", formatHashrate(nearest.raw.hashrate));
  tooltip.style.display = "block";
  tooltip.style.left = `${Math.max(5, Math.min(nearest.x + 11, rect.width - tooltip.offsetWidth - 6))}px`;
  tooltip.style.top = `${Math.max(5, nearest.y - 49)}px`;
}

let toastTimer;

async function copyText(value) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const area = document.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(area);
  if (!copied) throw new Error("Copy failed");
}

function showToast(message) {
  const toast = byId("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("show"), 2300);
}

function showView(name) {
  document.querySelectorAll("[data-view-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === name));
  document.querySelectorAll(".nav-link[data-view]").forEach((link) => link.classList.toggle("active", link.dataset.view === name));
  byId("sidebar")?.classList.remove("show");
  byId("sidebar-overlay")?.classList.remove("show");
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (name === "overview") window.setTimeout(drawChart, 80);
}

function bindEvents() {
  document.querySelectorAll(".nav-link[data-view]").forEach((link) => link.addEventListener("click", () => showView(link.dataset.view)));
  document.querySelectorAll("[data-view-jump]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.viewJump)));
  byId("menu-toggle")?.addEventListener("click", () => {
    byId("sidebar")?.classList.toggle("show");
    byId("sidebar-overlay")?.classList.toggle("show");
  });
  byId("sidebar-overlay")?.addEventListener("click", () => {
    byId("sidebar")?.classList.remove("show");
    byId("sidebar-overlay")?.classList.remove("show");
  });
  byId("refresh-button")?.addEventListener("click", async () => {
    await Promise.all([refreshMain({ manual: true }), refreshHistory()]);
  });
  byId("global-search")?.addEventListener("input", (event) => {
    state.query = event.target.value;
    renderMiners();
  });
  byId("copy-sv2-key")?.addEventListener("click", async () => {
    const value = byId("sv2-public-key")?.dataset.value || "";
    if (!value) return;
    try {
      await copyText(value);
      showToast("SV2 public key kopyalandı.");
    } catch (error) {
      showToast("Public key kopyalanamadı.");
    }
  });
  document.querySelectorAll("#history-range button").forEach((button) => button.addEventListener("click", async () => {
    document.querySelectorAll("#history-range button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.historyHours = Number(button.dataset.hours || 1);
    await refreshHistory();
  }));
  const chart = byId("hashrate-chart");
  chart?.addEventListener("mousemove", chartMove);
  chart?.addEventListener("mouseleave", () => { if (byId("chart-tooltip")) byId("chart-tooltip").style.display = "none"; });
  window.addEventListener("resize", drawChart);
}

function updateClock() {
  text("footer-clock", new Date().toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "medium" }));
}

async function start() {
  bindEvents();
  updateClock();
  await Promise.all([refreshMain(), refreshHistory()]);
  window.setInterval(refreshMain, 5000);
  window.setInterval(refreshHistory, 30000);
  window.setInterval(updateClock, 1000);
}

document.addEventListener("DOMContentLoaded", start);
