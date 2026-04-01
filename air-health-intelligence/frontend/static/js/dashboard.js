/**
 * AirGuard Intelligence — Dashboard Controller
 * Handles: panel navigation, API calls, WebSocket, Chart.js, AI chat
 */
"use strict";

// ── State ────────────────────────────────────────────────────────────────────
const State = {
  city: "Delhi",
  sessionId: crypto.randomUUID(),
  alertCount: 0,
  ws: null,
  trendChart: null,
};

// ── DOM refs ─────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ══════════════ NAVIGATION ══════════════

document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    $("panel-" + btn.dataset.panel).classList.add("active");
    if (btn.dataset.panel === "alerts") loadAlerts();
  });
});

// ══════════════ AQI COLOUR HELPER ══════════════

function aqiColor(aqi) {
  if (aqi <= 50)  return "#22c55e";
  if (aqi <= 100) return "#eab308";
  if (aqi <= 150) return "#f97316";
  if (aqi <= 200) return "#ef4444";
  if (aqi <= 300) return "#a855f7";
  return "#dc2626";
}

function aqiClass(aqi) {
  if (aqi <= 50)  return "aqi-good";
  if (aqi <= 100) return "aqi-moderate";
  if (aqi <= 150) return "aqi-sensitive";
  if (aqi <= 200) return "aqi-unhealthy";
  if (aqi <= 300) return "aqi-very-un";
  return "aqi-hazardous";
}

// ══════════════ DASHBOARD ══════════════

async function loadDashboard(city) {
  State.city = city;
  try {
    const res  = await fetch(`/api/air-quality/current/${encodeURIComponent(city)}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    renderHero(data);
  } catch (e) {
    showToast("Failed to load data for " + city, "danger");
    console.error(e);
  }
  loadHeatmap();
}

function renderHero(data) {
  const r   = data.current;
  const aqi = r.aqi ?? 0;
  const col = aqiColor(aqi);

  // AQI ring: circumference = 2π×80 ≈ 502
  const pct    = Math.min(aqi / 500, 1);
  const offset = 502 - pct * 502;
  const ring   = $("ring-fill");
  ring.style.strokeDashoffset = offset;
  ring.style.stroke           = col;

  $("aqi-value").textContent    = Math.round(aqi);
  $("aqi-value").style.color    = col;
  $("city-name").textContent    = data.city;
  $("aqi-category").textContent = r.aqi_category ?? "—";
  $("aqi-advisory").textContent = data.health_advisory ?? "";

  // Tags
  const tagsEl = $("aqi-tags");
  tagsEl.innerHTML = "";
  if (r.pollutants?.pm25 > 35)  addTag(tagsEl, "PM2.5 ↑", "warn");
  if (r.pollutants?.no2  > 100) addTag(tagsEl, "NO₂ ↑",  "warn");
  if (aqi > 150)                addTag(tagsEl, "Mask Recommended", "danger");
  if (aqi > 200)                addTag(tagsEl, "Stay Indoors", "danger");

  // Pollutants
  const p = r.pollutants ?? {};
  setPCard("pc-pm25", p.pm25);
  setPCard("pc-pm10", p.pm10);
  setPCard("pc-no2",  p.no2);
  setPCard("pc-o3",   p.o3);
  setPCard("pc-co",   p.co);
  setPCard("pc-so2",  p.so2);

  // Weather
  const w = r.weather ?? {};
  $("w-temp").textContent = w.temperature != null ? w.temperature.toFixed(1) : "—";
  $("w-hum").textContent  = w.humidity    != null ? Math.round(w.humidity)   : "—";
  $("w-wind").textContent = w.wind_speed  != null ? w.wind_speed.toFixed(1)  : "—";
  $("w-vis").textContent  = w.visibility  != null ? w.visibility.toFixed(1)  : "—";
}

function setPCard(id, val) {
  const card = $(id);
  if (!card) return;
  card.querySelector(".p-val").textContent = val != null ? val.toFixed(1) : "—";
}

function addTag(container, text, cls) {
  const span = document.createElement("span");
  span.className = `tag ${cls}`;
  span.textContent = text;
  container.appendChild(span);
}

async function loadHeatmap() {
  try {
    const res  = await fetch("/api/air-quality/heatmap");
    const data = await res.json();
    const grid = $("heatmap-grid");
    grid.innerHTML = "";
    (data.cities ?? []).forEach(c => {
      const div = document.createElement("div");
      div.className = "hm-card";
      div.innerHTML = `
        <span class="hm-city">${c.city}</span>
        <div class="hm-right">
          <div class="hm-aqi ${aqiClass(c.aqi)}">${Math.round(c.aqi)}</div>
          <div class="hm-cat">${c.aqi_category}</div>
        </div>`;
      div.addEventListener("click", () => {
        $("city-select").value = c.city;
        loadDashboard(c.city);
      });
      grid.appendChild(div);
    });
  } catch (e) { console.error("Heatmap error:", e); }
}

$("city-select").addEventListener("change", e => loadDashboard(e.target.value));
$("refresh-btn").addEventListener("click", () => loadDashboard(State.city));

// ══════════════ ANALYTICS ══════════════

$("load-analytics").addEventListener("click", loadAnalytics);

async function loadAnalytics() {
  const city  = $("analytics-city").value;
  const hours = $("analytics-hours").value;
  try {
    const res  = await fetch(`/api/air-quality/history/${encodeURIComponent(city)}?hours=${hours}`);
    const data = await res.json();
    renderStats(data.stats ?? {});
    renderChart(data.data_points ?? []);
  } catch (e) {
    showToast("Analytics load failed", "danger");
    console.error(e);
  }
}

function renderStats(s) {
  $("s-mean").textContent  = s.mean  != null ? s.mean.toFixed(1)  : "—";
  $("s-max").textContent   = s.max   != null ? s.max.toFixed(1)   : "—";
  $("s-p95").textContent   = s.percentile_95 != null ? s.percentile_95.toFixed(1) : "—";
  $("s-trend").textContent = s.trend_label ?? "—";
  const trendEl = $("s-trend");
  trendEl.style.color =
    s.trend_label === "Improving"  ? "#22c55e" :
    s.trend_label === "Worsening"  ? "#ef4444" : "#eab308";
}

function renderChart(dataPoints) {
  const labels = dataPoints.map(d => {
    const dt = new Date(d.timestamp);
    return `${dt.getMonth()+1}/${dt.getDate()} ${dt.getHours()}:00`;
  });
  const values = dataPoints.map(d => d.aqi);

  if (State.trendChart) State.trendChart.destroy();

  const ctx = document.getElementById("trend-chart").getContext("2d");
  State.trendChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "AQI",
        data: values,
        borderColor: "#00e5ff",
        backgroundColor: "rgba(0,229,255,0.07)",
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        tension: 0.4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: "#5a6480", maxTicksLimit: 10, font: { family: "Space Mono", size: 10 } },
          grid: { color: "#1a1f2d" },
        },
        y: {
          ticks: { color: "#5a6480", font: { family: "Space Mono", size: 10 } },
          grid: { color: "#1a1f2d" },
        },
      },
    },
  });
}

// ══════════════ ALERTS ══════════════

async function loadAlerts() {
  try {
    const res  = await fetch("/api/alerts/?status=active&limit=50");
    const data = await res.json();
    renderAlerts(data.alerts ?? []);
    updateAlertBadge(data.total ?? 0);
  } catch (e) { console.error("Alerts error:", e); }
}

function renderAlerts(alerts) {
  const list = $("alert-list");
  if (!alerts.length) {
    list.innerHTML = '<div class="empty-state">No active alerts — air quality is within safe limits. ✓</div>';
    return;
  }
  list.innerHTML = alerts.map(a => `
    <div class="alert-card ${a.severity}" id="alert-${a._id}">
      <div>
        <div class="alert-msg">${a.message}</div>
        <div class="alert-meta">${a.city} · ${a.pollutant.toUpperCase()} = ${a.current_value.toFixed(1)} · ${new Date(a.created_at).toLocaleString()}</div>
      </div>
      <button class="alert-dismiss" onclick="dismissAlert('${a._id}')">Dismiss</button>
    </div>`).join("");
}

async function dismissAlert(id) {
  try {
    await fetch(`/api/alerts/${id}`, { method: "DELETE" });
    const card = $("alert-" + id);
    if (card) card.remove();
    updateAlertBadge(--State.alertCount);
  } catch (e) { showToast("Could not dismiss alert", "danger"); }
}

function updateAlertBadge(count) {
  State.alertCount = count;
  const badge = $("alert-badge");
  badge.textContent = count;
  badge.classList.toggle("visible", count > 0);
}

// ══════════════ AI CHAT ══════════════

async function sendMessage(text) {
  if (!text.trim()) return;
  appendMsg("user", text);
  $("chat-input").value = "";

  const thinking = appendThinking();

  try {
    const res = await fetch("/api/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: State.sessionId,
        message: text,
        city: $("chat-city").value || null,
      }),
    });
    const data = await res.json();
    thinking.remove();
    appendMsg("assistant", data.reply ?? "Sorry, I could not generate a response.");
  } catch (e) {
    thinking.remove();
    appendMsg("assistant", "⚠️ Connection error. Please check the server and try again.");
  }
}

function appendMsg(role, content) {
  const win  = $("chat-window");
  const div  = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.innerHTML = `
    <div class="chat-avatar">${role === "assistant" ? "◈" : "U"}</div>
    <div class="chat-bubble">${escapeHtml(content).replace(/\n/g, "<br>")}</div>`;
  win.appendChild(div);
  win.scrollTop = win.scrollHeight;
  return div;
}

function appendThinking() {
  const win = $("chat-window");
  const div = document.createElement("div");
  div.className = "chat-msg assistant";
  div.innerHTML = `
    <div class="chat-avatar">◈</div>
    <div class="chat-bubble thinking">
      <span class="dot-flashing"></span>
      <span class="dot-flashing"></span>
      <span class="dot-flashing"></span>
    </div>`;
  win.appendChild(div);
  win.scrollTop = win.scrollHeight;
  return div;
}

$("chat-send").addEventListener("click", () => sendMessage($("chat-input").value));
$("chat-input").addEventListener("keydown", e => { if (e.key === "Enter") sendMessage($("chat-input").value); });
window.sendQuick = text => { $("chat-input").value = text; sendMessage(text); };

// ══════════════ WEBSOCKET ══════════════

function initWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url   = `${proto}://${location.host}/ws/alerts`;

  State.ws = new WebSocket(url);

  State.ws.onopen = () => {
    setWsStatus("connected", "Live");
    // Send heartbeat every 30s
    State.wsHeartbeat = setInterval(() => {
      if (State.ws.readyState === WebSocket.OPEN)
        State.ws.send(JSON.stringify({ type: "ping" }));
    }, 30_000);
  };

  State.ws.onmessage = e => {
    try {
      const msg = JSON.parse(e.data);
      handleWsMessage(msg);
    } catch {}
  };

  State.ws.onclose = () => {
    setWsStatus("error", "Disconnected");
    clearInterval(State.wsHeartbeat);
    setTimeout(initWebSocket, 5000);
  };

  State.ws.onerror = () => setWsStatus("error", "Error");
}

function handleWsMessage(msg) {
  if (msg.type === "alert") {
    showToast(msg.message, msg.severity);
    updateAlertBadge(State.alertCount + 1);
    // Refresh alert list if panel is active
    if (document.querySelector(".nav-btn.active")?.dataset.panel === "alerts") loadAlerts();
  }
}

function setWsStatus(cls, label) {
  const dot = document.querySelector(".ws-dot");
  const lbl = document.querySelector(".ws-label");
  dot.className = `ws-dot ${cls}`;
  lbl.textContent = label;
}

// ══════════════ TOAST ══════════════

function showToast(msg, type = "info") {
  const container = $("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

// ══════════════ UTILS ══════════════

function escapeHtml(str) {
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ══════════════ INIT ══════════════

(async () => {
  await loadDashboard("Delhi");
  initWebSocket();
})();
