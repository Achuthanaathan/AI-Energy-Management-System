// Simple vanilla-JS frontend for AETHER — Industrial Energy Intelligence.
// Communicates only with real FastAPI endpoints. No fabricated data.

const API = "/api";

async function api(path, method = "GET", body = null) {
  const options = { method, headers: { "Content-Type": "application/json" } };
  if (body) options.body = JSON.stringify(body);
  const response = await fetch(API + path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : response.statusText;
    throw new Error(detail);
  }
  return data;
}

let messageTimer = null;
function showMessage(text, isError = false) {
  const box = document.getElementById("message");
  if (!box) return;
  if (messageTimer) clearTimeout(messageTimer);
  box.textContent = text;
  box.className = "message " + (isError ? "error" : "success");
  box.classList.remove("hidden");
  messageTimer = setTimeout(() => {
    box.classList.add("hidden");
  }, 5000);
}

async function withButtonFeedback(btn, runningText, action) {
  let buttonEl = btn instanceof HTMLElement ? btn : null;
  if (!buttonEl && window.event && window.event.target instanceof HTMLElement && window.event.target.tagName === "BUTTON") {
    buttonEl = window.event.target;
  }
  if (buttonEl && buttonEl.disabled) return;
  const originalText = buttonEl ? buttonEl.innerHTML : "";
  if (buttonEl) {
    buttonEl.disabled = true;
    if (runningText) {
      buttonEl.innerHTML = `<span style="display:inline-block; animation:spin 1s linear infinite; margin-right:6px;">⟳</span> ${runningText}`;
    }
  }
  try {
    await action(Boolean(buttonEl));
  } finally {
    if (buttonEl) {
      buttonEl.disabled = false;
      buttonEl.innerHTML = originalText;
    }
  }
}

function num(value, digits = 2) {
  if (value === null || value === undefined) return "-";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function shortTime(iso) {
  return iso ? String(iso).replace("T", " ").slice(0, 16) : "-";
}

function table(elId, headers, rows) {
  const el = document.getElementById(elId);
  if (!el) return;
  let html = "<thead><tr>" + headers.map((h) => `<th>${h}</th>`).join("") + "</tr></thead><tbody>";
  if (!rows.length) {
    html += `<tr><td colspan="${headers.length}" style="text-align:center; color:var(--text-muted); padding:20px;">No telemetry records found</td></tr>`;
  } else {
    html += rows.map((r) => "<tr>" + r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("");
  }
  el.innerHTML = html + "</tbody>";
}

function card(label, value, extra = "") {
  return `<div class="card spotlight-card">
    <div class="label">${label}</div>
    <div class="value">${value}</div>
    <div class="extra">${extra}</div>
  </div>`;
}

// --------------------------- Spotlight Card Effect ------------------------- //
document.addEventListener("mousemove", (e) => {
  const cards = document.querySelectorAll(".spotlight-card, .card");
  cards.forEach((card) => {
    const rect = card.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    card.style.setProperty("--mouse-x", `${x}px`);
    card.style.setProperty("--mouse-y", `${y}px`);
  });
});

// ---------------------------- Sidebar Collapse ---------------------------- //
const sidebar = document.getElementById("sidebar");
const toggleBtn = document.getElementById("sidebar-toggle-btn");
const mobileBtn = document.getElementById("mobile-menu-btn");

if (toggleBtn && sidebar) {
  toggleBtn.addEventListener("click", () => {
    sidebar.classList.toggle("collapsed");
    const isCollapsed = sidebar.classList.contains("collapsed");
    localStorage.setItem("aether_sidebar_collapsed", isCollapsed ? "1" : "0");
  });

  if (localStorage.getItem("aether_sidebar_collapsed") === "1") {
    sidebar.classList.add("collapsed");
  }
}

if (mobileBtn && sidebar) {
  mobileBtn.addEventListener("click", () => {
    sidebar.classList.toggle("mobile-open");
  });
}

// ------------------------------- Navigation ------------------------------- //
const viewTitles = {
  dashboard: "Dashboard",
  energy: "Energy Monitoring",
  forecast: "Energy Forecast",
  anomalies: "Anomaly Detection",
  recommendations: "Recommendations",
  simulation: "Simulation & Savings",
};

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const viewName = button.dataset.view;
    switchView(viewName);
  });
});

function switchView(viewName) {
  document.querySelectorAll("[data-view]").forEach((b) => {
    if (b.dataset.view === viewName) {
      b.classList.add("active");
    } else {
      b.classList.remove("active");
    }
  });

  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const targetView = document.getElementById("view-" + viewName);
  if (targetView) targetView.classList.add("active");

  const breadcrumb = document.getElementById("header-breadcrumb");
  if (breadcrumb && viewTitles[viewName]) {
    breadcrumb.textContent = viewTitles[viewName];
  }

  // Close mobile sidebar on select
  if (sidebar) sidebar.classList.remove("mobile-open");

  reload(viewName);
}

function showView(view) {
  switchView(view);
}

function showRecommendation(id) {
  showView("recommendations");
  setTimeout(() => {
    const el = document.getElementById("recommendation-list");
    if (el) el.scrollIntoView({ behavior: "smooth" });
  }, 120);
}

function reload(view) {
  const loaders = {
    dashboard: loadDashboard,
    energy: loadEnergy,
    forecast: loadForecast,
    anomalies: loadAnomalies,
    recommendations: loadRecommendations,
    simulation: loadSimulations,
  };
  if (loaders[view]) loaders[view]();
}

// ----------------------------- Command Palette ---------------------------- //
function openCommandPalette() {
  const modal = document.getElementById("cmd-palette-modal");
  if (!modal) return;
  modal.classList.remove("hidden");
  const input = document.getElementById("cmd-search-input");
  if (input) {
    input.value = "";
    input.focus();
    filterCommandPalette("");
  }
}

function closeCommandPalette(e) {
  if (e && e.target && e.target.closest && e.target.closest(".cmd-palette-box") && !e.target.classList.contains("kbd-badge")) {
    return;
  }
  const modal = document.getElementById("cmd-palette-modal");
  if (modal) modal.classList.add("hidden");
}

function selectCommandView(view) {
  closeCommandPalette();
  showView(view);
}

function filterCommandPalette(query) {
  const q = (query || "").toLowerCase();
  const items = document.querySelectorAll("#cmd-options-list .cmd-item");
  items.forEach((item) => {
    const text = item.textContent.toLowerCase();
    item.style.display = text.includes(q) ? "flex" : "none";
  });
}

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    const modal = document.getElementById("cmd-palette-modal");
    if (modal && !modal.classList.contains("hidden")) {
      closeCommandPalette();
    } else {
      openCommandPalette();
    }
  } else if (e.key === "Escape") {
    closeCommandPalette();
  }
});

// -------------------------------- Dashboard ------------------------------- //
async function loadDashboard(btn = null) {
  await withButtonFeedback(btn, "Refreshing...", async (isInteractive) => {
    try {
      const [d, fc] = await Promise.all([
        api("/dashboard"),
        api("/forecast?machine=ALL&horizon=24").catch(() => null),
      ]);

      // LEVEL 1 - AT A GLANCE (4 KPIs)
      const isPeakNow = d.current.is_peak_tariff;
      document.getElementById("dashboard-cards").innerHTML =
        card(
          "Current Plant Usage",
          num(d.current.total_kw) + " kW",
          `<span style="color:${isPeakNow ? 'var(--accent-rose)' : 'var(--accent-emerald)'}; font-weight:600;">●</span> ${shortTime(d.current.timestamp)} ${isPeakNow ? "(PEAK tariff)" : "(Normal tariff)"}`
        ) +
        card(
          "Last 24h Energy Cost",
          num(d.current.last_24h_cost) + " cost units",
          `<span style="color:var(--text-muted);">${num(d.current.last_24h_energy_kwh)} kWh total consumed</span>`
        ) +
        card(
          "Forecast 24h Peak",
          num(d.forecast.peak_demand_kw) + " kW",
          `<span style="color:var(--accent-amber); font-weight:600;">▲</span> Peak window at ${shortTime(d.forecast.peak_timestamp)}`
        ) +
        card(
          "Potential Cost Savings",
          num(d.savings.potential_cost_saved) + " cost units",
          `<span class="badge pending" style="margin-right:4px;">${d.recommendation_counts.pending} pending</span> approval`
        );

      // LEVEL 2 - RECHARTS-STYLE SVG AREA CHART (24-hour demand trend)
      const series = (fc && fc.series) || (d.forecast && d.forecast.series) || [];
      renderAreaChart("dashboard-chart", series);

      // Recommendation status summary & M&V savings
      const counts = d.recommendation_counts;
      const verifiedCost = d.savings && d.savings.verified_cost_saved != null ? d.savings.verified_cost_saved : 0;
      const verifiedKwh = d.savings && d.savings.verified_energy_saved_kwh != null ? d.savings.verified_energy_saved_kwh : 0;

      document.getElementById("dashboard-status").innerHTML =
        `<div class="chips" style="margin-bottom:8px;">
          <span class="chip pending">Pending <strong>${counts.pending}</strong></span>
          <span class="chip approved">Approved <strong>${counts.approved}</strong></span>
          <span class="chip overridden">Overridden <strong>${counts.overridden}</strong></span>
          <span class="chip simulated">Simulated <strong>${counts.simulated}</strong></span>
        </div>
        <div class="status-metric">
          <span class="label">Verified Savings (M&amp;V)</span>
          <strong class="good" style="font-size:18px; display:block; margin:2px 0;">${num(verifiedCost)} cost units</strong>
          <span class="sub" style="font-size:11px; color:var(--text-muted);">${num(verifiedKwh)} kWh verified across ${d.savings.simulation_count || 0} simulation runs</span>
        </div>`;

      // Update badge counts in sidebar
      const recBadge = document.getElementById("nav-rec-badge");
      const notifPing = document.getElementById("notif-ping");
      if (recBadge) {
        recBadge.textContent = counts.pending;
        recBadge.style.display = counts.pending > 0 ? "inline-block" : "none";
      }
      if (notifPing) {
        notifPing.style.display = counts.pending > 0 ? "block" : "none";
      }

      const configEl = document.getElementById("dashboard-config-details");
      if (configEl && d.settings) {
        configEl.innerHTML =
          `<p><span class="tag">Peak Threshold</span><strong>${d.settings.peak_threshold_kw} kW</strong></p>
           <p><span class="tag">Flexible Machine</span><strong>${d.settings.flexible_machine}</strong></p>
           <p><span class="tag">Model MAE</span><strong>${num(d.forecast.holdout_mae_kwh)} kWh</strong> (${d.forecast.model})</p>
           <p class="tech">${d.settings.note}</p>`;
      }

      // AI INSIGHT Banner
      if (d.latest_recommendation) {
        const r = d.latest_recommendation;
        const isPeakShift = r.rule === "peak_shift";
        const headline =
          isPeakShift
            ? `Shift ${r.machine} out of the ${String(r.shift_from_hour).padStart(2, "0")}:00 peak window`
            : `Investigate unusual energy spike on ${r.machine}`;
        const insightBody =
          isPeakShift
            ? `Peak load shifting on <strong>${r.machine}</strong>: transfer ${num(r.shift_kwh)} kWh of load from hour ${String(r.shift_from_hour).padStart(2, "0")}:00 to hour ${String(r.shift_to_hour).padStart(2, "0")}:00.`
            : `Anomaly detection flagged irregular energy consumption on <strong>${r.machine}</strong>.`;

        document.getElementById("insight-body").innerHTML =
          `${insightBody} <span class="tech">Reason: ${r.reason} &middot; Action: ${r.action}</span>`;

        document.getElementById("now-summary").innerHTML =
          `<span><strong>${headline}</strong> &middot; <span class="good">Est. saving: ${num(r.est_cost_impact)} cost units</span></span> ` +
          `<button class="text-link" style="margin-left:auto;" onclick="showRecommendation('${r.id}')">View recommendation &rarr;</button>`;
      } else {
        document.getElementById("now-summary").innerHTML =
          "All machines operating within normal thresholds. No active recommendations pending.";
        document.getElementById("insight-body").innerHTML =
          "No active recommendations generated. Run the rule engine from the Recommendations page.";
      }

      if (isInteractive) {
        showMessage("Dashboard refreshed successfully.");
      }
    } catch (error) {
      showMessage("Dashboard failed: " + error.message, true);
    }
  });
}

// -------------------------- Recharts-style SVG Area Chart ------------------- //
function renderAreaChart(containerId, series) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!series || !series.length) {
    container.innerHTML = '<div style="margin:auto; color:var(--text-muted); font-size:12px;">No forecast trend data available</div>';
    return;
  }

  const width = 800;
  const height = 220;
  const padLeft = 45;
  const padRight = 20;
  const padTop = 15;
  const padBottom = 25;
  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  const maxVal = Math.max(...series.map((p) => p.predicted_kwh), 1);
  const minVal = 0;
  const range = maxVal - minVal;

  const getX = (idx) => padLeft + (idx / (series.length - 1)) * chartW;
  const getY = (val) => padTop + chartH - ((val - minVal) / range) * chartH;

  const points = series.map((p, idx) => ({
    x: getX(idx),
    y: getY(p.predicted_kwh),
    val: p.predicted_kwh,
    ts: p.timestamp,
    hour: Number(p.timestamp.slice(11, 13)),
    isPeak: Number(p.timestamp.slice(11, 13)) >= 18 && Number(p.timestamp.slice(11, 13)) <= 21,
  }));

  // Build smooth bezier path
  let pathD = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const curr = points[i];
    const cpX1 = (prev.x + curr.x) / 2;
    const cpY1 = prev.y;
    const cpX2 = (prev.x + curr.x) / 2;
    const cpY2 = curr.y;
    pathD += ` C ${cpX1} ${cpY1}, ${cpX2} ${cpY2}, ${curr.x} ${curr.y}`;
  }

  const areaD = `${pathD} L ${points[points.length - 1].x} ${padTop + chartH} L ${points[0].x} ${padTop + chartH} Z`;

  // Grid lines (4 lines)
  let gridLines = "";
  for (let step = 0; step <= 4; step++) {
    const yVal = padTop + (chartH / 4) * step;
    const valLabel = Math.round(maxVal - (maxVal / 4) * step);
    gridLines += `<line x1="${padLeft}" y1="${yVal}" x2="${width - padRight}" y2="${yVal}" class="chart-grid-line" />
      <text x="${padLeft - 8}" y="${yVal + 3}" text-anchor="end" class="chart-axis-text">${valLabel}</text>`;
  }

  // Peak window band overlay (18:00–21:00)
  const peakStartIndex = series.findIndex((p) => Number(p.timestamp.slice(11, 13)) >= 18);
  const peakEndIndex = series.findLastIndex ? series.findLastIndex((p) => Number(p.timestamp.slice(11, 13)) <= 21) : series.findIndex((p) => Number(p.timestamp.slice(11, 13)) >= 21);
  let peakRect = "";
  if (peakStartIndex !== -1 && peakEndIndex !== -1 && peakEndIndex >= peakStartIndex) {
    const px1 = getX(peakStartIndex);
    const px2 = getX(peakEndIndex);
    peakRect = `<rect x="${px1}" y="${padTop}" width="${Math.max(px2 - px1, 24)}" height="${chartH}" class="peak-band-rect" />
      <text x="${px1 + 4}" y="${padTop + 14}" fill="var(--accent-rose)" font-size="9" font-weight="600" font-family="var(--font-mono)">PEAK TARIFF</text>`;
  }

  // X-axis time labels (sample every 3 or 4 points)
  let xLabels = "";
  const step = Math.max(Math.floor(series.length / 6), 1);
  for (let i = 0; i < series.length; i += step) {
    const pt = points[i];
    const hourLabel = pt.ts.slice(11, 16);
    xLabels += `<text x="${pt.x}" y="${height - 6}" text-anchor="middle" class="chart-axis-text">${hourLabel}</text>`;
  }

  container.innerHTML = `
    <div class="svg-chart-wrapper" id="${containerId}-wrapper">
      <div id="${containerId}-tooltip" class="chart-tooltip-box"></div>
      <svg class="svg-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
        <defs>
          <linearGradient id="aetherAreaGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#6366f1" stop-opacity="0.38"/>
            <stop offset="100%" stop-color="#6366f1" stop-opacity="0.0"/>
          </linearGradient>
        </defs>
        ${gridLines}
        ${peakRect}
        <path d="${areaD}" class="chart-area-path"/>
        <path d="${pathD}" class="chart-line-path"/>
        ${xLabels}
        <line id="${containerId}-cursor-line" x1="0" y1="${padTop}" x2="0" y2="${padTop + chartH}" stroke="rgba(255,255,255,0.2)" stroke-dasharray="3 3" style="display:none;" />
        <circle id="${containerId}-cursor-dot" r="4.5" fill="#fff" stroke="#6366f1" stroke-width="2.5" style="display:none;" />
      </svg>
    </div>
  `;

  // Attach hover interactions
  const wrapper = document.getElementById(`${containerId}-wrapper`);
  const tooltip = document.getElementById(`${containerId}-tooltip`);
  const cursorLine = document.getElementById(`${containerId}-cursor-line`);
  const cursorDot = document.getElementById(`${containerId}-cursor-dot`);

  if (!wrapper || !tooltip) return;

  wrapper.addEventListener("mousemove", (e) => {
    const rect = wrapper.getBoundingClientRect();
    const mouseX = ((e.clientX - rect.left) / rect.width) * width;

    // Find closest data point
    let closest = points[0];
    let minDist = Infinity;
    points.forEach((pt) => {
      const dist = Math.abs(pt.x - mouseX);
      if (dist < minDist) {
        minDist = dist;
        closest = pt;
      }
    });

    if (closest) {
      const screenX = ((closest.x) / width) * rect.width;
      const screenY = ((closest.y) / height) * rect.height;

      tooltip.style.display = "block";
      tooltip.style.left = `${screenX}px`;
      tooltip.style.top = `${screenY}px`;
      tooltip.innerHTML = `
        <div style="font-weight:700; color:#fff;">${num(closest.val)} kW</div>
        <div style="color:var(--text-muted); font-size:10px;">${shortTime(closest.ts)} ${closest.isPeak ? '<span style="color:var(--accent-rose); font-weight:600;">(PEAK)</span>' : ''}</div>
      `;

      if (cursorLine && cursorDot) {
        cursorLine.style.display = "block";
        cursorLine.setAttribute("x1", closest.x);
        cursorLine.setAttribute("x2", closest.x);
        cursorDot.style.display = "block";
        cursorDot.setAttribute("cx", closest.x);
        cursorDot.setAttribute("cy", closest.y);
        cursorDot.setAttribute("stroke", closest.isPeak ? "var(--accent-rose)" : "var(--accent-primary)");
      }
    }
  });

  wrapper.addEventListener("mouseleave", () => {
    tooltip.style.display = "none";
    if (cursorLine) cursorLine.style.display = "none";
    if (cursorDot) cursorDot.style.display = "none";
  });
}

// --------------------------------- Energy --------------------------------- //
async function loadEnergy(btn = null) {
  await withButtonFeedback(btn, "Loading...", async (isInteractive) => {
    try {
      const current = await api("/energy/current");
      document.getElementById("energy-current").innerHTML =
        card("Plant Load Now", num(current.total_kw) + " kW", shortTime(current.timestamp)) +
        card("Tariff Window", num(current.tariff) + " /kWh", current.is_peak_tariff ? '<span class="bad">PEAK Tariff active</span>' : "Standard rate") +
        card("Last 24h Energy Consumed", num(current.last_24h_energy_kwh) + " kWh", "Cost: " + num(current.last_24h_cost));

      const summary = await api("/energy/summary");
      table(
        "energy-summary",
        ["Machine Name", "Energy Last 24h (kWh)", "Cost Last 24h", "Peak Load (kW)"],
        summary.machines.map((m) => [m.machine, num(m.energy_kwh), num(m.cost), num(m.peak_kw)])
      );

      const machine = document.getElementById("history-machine").value;
      const hours = document.getElementById("history-hours").value;
      const history = await api(`/energy/history?machine=${encodeURIComponent(machine)}&hours=${hours}`);
      table(
        "energy-history",
        ["Timestamp", "Energy (kWh)", "Tariff Rate", "Peak Window Flag"],
        history.series
          .slice()
          .reverse()
          .slice(0, 60)
          .map((p) => [
            shortTime(p.timestamp),
            num(p.energy_kwh),
            num(p.tariff),
            p.is_peak_tariff ? '<span class="badge overridden">PEAK</span>' : '<span class="badge approved">NORMAL</span>'
          ])
      );

      const count = history && history.series ? history.series.length : 0;
      if (isInteractive) {
        showMessage(`Loaded ${count} readings for ${machine} (last ${hours} hours).`);
      }
    } catch (error) {
      showMessage("Energy data failed: " + error.message, true);
    }
  });
}

// -------------------------------- Forecast -------------------------------- //
async function loadForecast(btn = null) {
  await withButtonFeedback(btn, "Refreshing...", async (isInteractive) => {
    try {
      const f = await api("/forecast?machine=ALL&horizon=24");
      document.getElementById("forecast-meta").innerHTML =
        card("Predictive Model", f.model, f.features.join(", ")) +
        card("Forecast Peak Load", num(f.peak_demand_kw) + " kW", shortTime(f.peak_timestamp)) +
        card("Predicted 24h Energy", num(f.predicted_total_kwh) + " kWh", "Trained on " + f.trained_samples + " data points") +
        card("Hold-out MAE", num(f.holdout_mae_kwh) + " kWh", "Generalization error on test set");

      renderAreaChart("forecast-bars", f.series);

      table(
        "forecast-table",
        ["Forecast Timestamp", "Predicted Average Demand (kW)"],
        f.series.map((p) => [shortTime(p.timestamp), num(p.predicted_kwh)])
      );

      if (isInteractive) {
        showMessage("Forecast refreshed successfully (24-hour horizon).");
      }
    } catch (error) {
      showMessage("Forecast failed: " + error.message, true);
    }
  });
}

// ------------------------------- Anomalies -------------------------------- //
async function loadAnomalies(btn = null) {
  await withButtonFeedback(btn, "Refreshing...", async (isInteractive) => {
    try {
      const a = await api("/anomalies?limit=25");
      document.getElementById("anomaly-meta").innerHTML =
        card("Anomaly Model", a.model, a.features.join(", ")) +
        card("Flagged Power Events", a.anomaly_count, "out of " + a.total_readings + " readings") +
        card("Injected Tests Detected", a.injected_detected + " / " + a.injected_readings, "Detector validation") +
        card("Contamination Level", a.contamination, "Isolation Forest sensitivity");

      table(
        "anomaly-table",
        ["Timestamp", "Machine", "Energy (kWh)", "Typical (kWh)", "Excess (kWh)", "kWh/unit", "Severity Score", "Injected Test"],
        a.items.map((i) => [
          shortTime(i.timestamp),
          `<strong>${i.machine}</strong>`,
          num(i.energy_kwh),
          num(i.typical_energy_kwh),
          `<span class="bad">+${num(i.excess_kwh)}</span>`,
          i.energy_per_unit === null ? "-" : num(i.energy_per_unit, 3),
          `<span class="badge overridden">${num(i.anomaly_score, 3)}</span>`,
          i.is_injected_anomaly ? '<span class="badge pending">TEST</span>' : '<span style="color:var(--text-dim);">No</span>',
        ])
      );

      // Update sidebar badge
      const anomBadge = document.getElementById("nav-anomaly-badge");
      if (anomBadge) {
        anomBadge.textContent = a.anomaly_count;
        anomBadge.style.display = a.anomaly_count > 0 ? "inline-block" : "none";
      }

      if (isInteractive) {
        showMessage(`Anomaly detection refreshed: flagged ${a.anomaly_count} anomalous readings.`);
      }
    } catch (error) {
      showMessage("Anomaly detection failed: " + error.message, true);
    }
  });
}

// ----------------------------- Recommendations ---------------------------- //
async function loadRecommendations() {
  const filterEl = document.getElementById("rec-filter");
  const status = filterEl ? filterEl.value : "all";
  try {
    const [list, all, simulations] = await Promise.all([
      api("/recommendations?status=" + status),
      api("/recommendations"),
      api("/simulations"),
    ]);

    const simsByRec = {};
    simulations.forEach((s) => {
      const current = simsByRec[s.recommendation_id];
      if (!current || current.id < s.id) simsByRec[s.recommendation_id] = s;
    });

    const counts = { pending: 0, approved: 0, overridden: 0, simulated: 0 };
    all.forEach((r) => { counts[r.status] = (counts[r.status] || 0) + 1; });

    document.getElementById("rec-summary").innerHTML =
      `<span class="chip pending">Pending <strong>${counts.pending}</strong></span>` +
      `<span class="chip approved">Approved <strong>${counts.approved}</strong></span>` +
      `<span class="chip overridden">Overridden <strong>${counts.overridden}</strong></span>` +
      `<span class="chip simulated">Simulated <strong>${counts.simulated}</strong></span>`;

    // Update nav badge
    const recBadge = document.getElementById("nav-rec-badge");
    const notifPing = document.getElementById("notif-ping");
    if (recBadge) {
      recBadge.textContent = counts.pending;
      recBadge.style.display = counts.pending > 0 ? "inline-block" : "none";
    }
    if (notifPing) {
      notifPing.style.display = counts.pending > 0 ? "block" : "none";
    }

    if (!list.length) {
      document.getElementById("recommendation-list").innerHTML =
        '<div class="card spotlight-card" style="padding:24px; text-align:center; color:var(--text-muted);">' +
        'No recommendations for this filter. Click <strong>"Run Rule Engine"</strong> to analyze demand and generate actions.' +
        '</div>';
      return;
    }
    document.getElementById("recommendation-list").innerHTML = list
      .map((r) => recommendationCard(r, simsByRec[r.id]))
      .join("");
  } catch (error) {
    showMessage("Recommendations failed: " + error.message, true);
  }
}

const REC_STEPS = ["Recommendation", "Human Decision", "M&V Simulation", "Verified Savings"];

function stepTrail(status) {
  const done = status === "simulated" ? [1, 2, 3, 4] : status === "pending" ? [1] : [1, 2];
  const current = status === "pending" ? 2 : status === "simulated" ? 0 : 3;
  const steps = REC_STEPS.map((label, index) => {
    const step = index + 1;
    const cls = done.includes(step) ? "s done" : step === current ? "s current" : "s";
    return `<span class="${cls}">${step}. ${label}</span>`;
  }).join('<span class="sep">&rarr;</span>');
  return `<div class="trail">${steps}</div>`;
}

function shortTrigger(r) {
  if (r.rule === "peak_shift") {
    const from = String(r.shift_from_hour).padStart(2, "0") + ":00";
    return `Forecast peak ${num(r.forecast_peak_kw, 0)} kW in the ${from} peak window`;
  }
  return "Unusual energy consumption detected by Isolation Forest";
}

function statusPhrase(r) {
  if (r.status === "pending") return "Awaiting operator review and decision";
  if (r.status === "approved") return "Approved — ready to run M&V simulation";
  if (r.status === "overridden") return "Overridden by operator";
  return "Simulated — M&V savings mathematically verified";
}

function mvStrip(sim) {
  return `<div class="mvstrip">
    <span><span class="k">Energy Saved</span> <strong class="good">${num(sim.energy_saved_kwh)} kWh</strong></span>
    <span><span class="k">Cost Saved</span> <strong class="good">${num(sim.cost_saved)} units</strong></span>
    <span><span class="k">Peak Load</span> <strong>${num(sim.baseline_peak_kw, 0)} &rarr; ${num(sim.simulated_peak_kw, 0)} kW</strong></span>
    <button class="text-link" style="margin-left:auto;" onclick="showView('simulation')">View in Savings &rarr;</button>
  </div>`;
}

function detailsBox(r, sim) {
  const hh = (hour) => String(hour).padStart(2, "0") + ":00";
  return `<details class="details-accordion">
    <summary class="details-summary">
      <span>View Technical Details &amp; Mathematical Parameters</span>
      <svg class="chevron-rot" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="6 9 12 15 18 9"></polyline>
      </svg>
    </summary>
    <div class="detail-body">
      <p><span class="tag">Suggested Action</span>${r.action}</p>
      <p><span class="tag">Engineering Reason</span>${r.reason}</p>
      ${r.decision_note ? `<p><span class="tag">Operator Decision Note</span>${r.decision_note}</p>` : ""}
      <p class="tech">Recommendation #${r.id} &middot; rule: ${r.rule} &middot; created: ${shortTime(r.created_at)} &middot;
        decision: ${r.decision || "pending"}${r.decided_at ? " (" + shortTime(r.decided_at) + ")" : ""} &middot;
        shift window: ${hh(r.shift_from_hour)} &rarr; ${hh(r.shift_to_hour)} &middot;
        load moved: ${num(r.shift_kwh)} kWh &middot; est. energy saved: ${num(r.est_energy_impact_kwh)} kWh &middot;
        forecast peak: ${num(r.forecast_peak_kw)} kW</p>
      ${sim ? `<p class="tech">Baseline: ${num(sim.baseline_energy_kwh)} kWh / ${num(sim.baseline_cost)} &middot;
        simulated: ${num(sim.simulated_energy_kwh)} kWh / ${num(sim.simulated_cost)} &middot;
        peak: ${num(sim.baseline_peak_kw)} &rarr; ${num(sim.simulated_peak_kw)} kW</p>
        <p class="tech" style="color:var(--accent-emerald);">${sim.note}</p>` : ""}
      <p class="tech" style="color:var(--text-dim);">Estimated values are calculated from algorithm models prior to physical simulation.</p>
    </div>
  </details>`;
}

function recommendationCard(r, sim) {
  const canApprove = r.status === "pending";
  const canOverride = r.status !== "simulated";
  const canSimulate = r.status !== "pending";
  return `
  <div class="rec status-${r.status} spotlight-card">
    <div class="rec-head">
      <h3>${r.title}</h3>
      <span class="badge ${r.status}">${r.status}</span>
    </div>
    <p class="rec-meta">Machine asset: <strong>${r.machine}</strong> &middot; ${shortTrigger(r)}</p>

    <div class="rec-metrics">
      <div><span class="k">Est. Cost Saving</span><strong class="good">${num(r.est_cost_impact)}</strong></div>
      <div><span class="k">Risk Classification</span><strong>${r.risk_level}</strong></div>
      <div><span class="k">Production Impact</span><strong>${num(r.production_impact_pct, 1)}%</strong></div>
    </div>

    ${sim ? mvStrip(sim) : ""}

    ${stepTrail(r.status)}
    <p class="status-line ${r.status}">${statusPhrase(r)}</p>

    <div class="actions">
      <button class="btn btn-secondary" onclick="decide(${r.id}, 'approve', this)" ${canApprove ? "" : 'disabled title="Only a pending recommendation can be approved"'}>Approve Recommendation</button>
      <button class="btn btn-secondary" onclick="decide(${r.id}, 'override', this)" ${canOverride ? "" : 'disabled title="Already simulated"'}>Override</button>
      <button class="btn btn-primary" onclick="simulate(${r.id}, this)" ${canSimulate ? "" : 'disabled title="Approve or override first"'}>Run M&amp;V Simulation</button>
    </div>

    ${detailsBox(r, sim)}
  </div>`;
}

async function generateRecommendations(btn = null) {
  await withButtonFeedback(btn, "Running rule engine...", async () => {
    try {
      const created = await api("/recommendations/generate", "POST");
      if (created && created.length > 0) {
        showMessage(`Rule engine finished: generated ${created.length} new recommendation(s).`);
      } else {
        showMessage("Rule engine finished: all current peak events and anomalies already evaluated.");
      }
      await loadRecommendations();
      loadDashboard().catch(() => null);
    } catch (error) {
      showMessage("Rule engine failed: " + error.message, true);
    }
  });
}

async function decide(id, action, btn = null) {
  const note = prompt(action === "approve" ? "Optional approval note:" : "Reason for override (optional):");
  if (note === null) return;
  await withButtonFeedback(btn, "Saving...", async () => {
    try {
      const updated = await api(`/recommendations/${id}/${action}`, "POST", { note });
      showMessage(`Recommendation #${id} updated to '${updated.status}'.`);
      await loadRecommendations();
      loadDashboard().catch(() => null);
    } catch (error) {
      showMessage("Decision failed: " + error.message, true);
    }
  });
}

async function simulate(id, btn = null) {
  await withButtonFeedback(btn, "Simulating...", async () => {
    try {
      await api(`/recommendations/${id}/simulate`, "POST");
      showMessage(`Recommendation #${id} simulated. M&V results updated.`);
      await loadRecommendations();
      loadDashboard().catch(() => null);
    } catch (error) {
      showMessage("Simulation failed: " + error.message, true);
    }
  });
}

// --------------------------- Simulations / Savings ------------------------ //
async function loadSimulations(btn = null) {
  await withButtonFeedback(btn, "Refreshing...", async (isInteractive) => {
    try {
      const list = await api("/simulations");
      const energySaved = list.reduce((sum, s) => sum + s.energy_saved_kwh, 0);
      const costSaved = list.reduce((sum, s) => sum + s.cost_saved, 0);
      const peakCut = list.reduce((sum, s) => sum + s.peak_reduction_kw, 0);

      document.getElementById("savings-totals").innerHTML =
        card("Simulations Completed", list.length, "Approved / overridden recommendations") +
        card("Cumulative Energy Saved", num(energySaved) + " kWh", "Baseline minus simulated load") +
        card("Total Cost Saved", num(costSaved) + " cost units", "Mathematical model savings") +
        card("Peak Demand Shaved", num(peakCut) + " kW", "Sum of peak load reductions");

      table(
        "simulation-table",
        ["Sim #", "Rec #", "Baseline kWh", "Simulated kWh", "Energy Saved", "Baseline Cost",
         "Simulated Cost", "Cost Saved", "Peak Load (Before / After)"],
        list.map((s) => [
          `#${s.id}`,
          `#${s.recommendation_id}`,
          num(s.baseline_energy_kwh),
          num(s.simulated_energy_kwh),
          `<strong class="good">${num(s.energy_saved_kwh)} kWh</strong>`,
          num(s.baseline_cost),
          num(s.simulated_cost),
          `<strong class="good">${num(s.cost_saved)}</strong>`,
          `${num(s.baseline_peak_kw, 0)} kW &rarr; ${num(s.simulated_peak_kw, 0)} kW`,
        ])
      );

      if (isInteractive) {
        showMessage(`Simulation results refreshed: ${list.length} simulations loaded.`);
      }
    } catch (error) {
      showMessage("Simulation results failed: " + error.message, true);
    }
  });
}

// --------------------------------- Initialize ------------------------------ //
loadDashboard();
