// Simple vanilla-JS frontend. Talks only to the real FastAPI endpoints.

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

function showMessage(text, isError = false) {
  const box = document.getElementById("message");
  box.textContent = text;
  box.className = "message" + (isError ? " error" : "");
  setTimeout(() => box.classList.add("hidden"), 6000);
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
  let html = "<thead><tr>" + headers.map((h) => `<th>${h}</th>`).join("") + "</tr></thead><tbody>";
  if (!rows.length) {
    html += `<tr><td colspan="${headers.length}">No data</td></tr>`;
  } else {
    html += rows.map((r) => "<tr>" + r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("");
  }
  el.innerHTML = html + "</tbody>";
}

function card(label, value, extra = "") {
  return `<div class="card"><div class="label">${label}</div><div class="value">${value}</div>
    <div class="extra">${extra}</div></div>`;
}

// ------------------------------- navigation ------------------------------- //
document.querySelectorAll("nav .tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("nav .tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    button.classList.add("active");
    document.getElementById("view-" + button.dataset.view).classList.add("active");
    reload(button.dataset.view);
  });
});

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

// -------------------------------- dashboard ------------------------------- //
async function loadDashboard() {
  try {
    const d = await api("/dashboard");
    document.getElementById("dashboard-cards").innerHTML =
      card("Current usage", num(d.current.total_kw) + " kW", shortTime(d.current.timestamp)) +
      card(
        "Forecast peak demand",
        num(d.forecast.peak_demand_kw) + " kW",
        "at " + shortTime(d.forecast.peak_timestamp) + " (threshold " + d.settings.peak_threshold_kw + " kW)"
      ) +
      card("Anomalies detected", d.anomalies.count, d.anomalies.injected_detected + " injected readings found") +
      card(
        "Estimated / verified savings",
        num(d.savings.verified_cost_saved) + " cost units",
        "pending potential " + num(d.savings.potential_cost_saved)
      ) +
      card("Last 24h energy", num(d.current.last_24h_energy_kwh) + " kWh", "cost " + num(d.current.last_24h_cost));

    const counts = d.recommendation_counts;
    document.getElementById("dashboard-status").innerHTML =
      card("Pending", counts.pending) +
      card("Approved", counts.approved) +
      card("Overridden", counts.overridden) +
      card("Simulated", counts.simulated);

    if (d.latest_recommendation) {
      const r = d.latest_recommendation;
      document.getElementById("dashboard-status").innerHTML += `
        <div class="card" style="flex:1 1 100%">
          <div class="label">Latest recommendation</div>
          <div class="value" style="font-size:15px">${r.title}</div>
          <div class="extra">${r.reason}</div>
          <div class="extra">Est. cost impact: ${num(r.est_cost_impact)} &middot;
            status: <span class="badge ${r.status}">${r.status}</span></div>
        </div>`;
    }
  } catch (error) {
    showMessage("Dashboard failed: " + error.message, true);
  }
}

// --------------------------------- energy --------------------------------- //
async function loadEnergy() {
  try {
    const current = await api("/energy/current");
    document.getElementById("energy-current").innerHTML =
      card("Plant load now", num(current.total_kw) + " kW", shortTime(current.timestamp)) +
      card("Tariff now", num(current.tariff) + " /kWh", current.is_peak_tariff ? "PEAK window" : "not peak window") +
      card("Last 24h energy", num(current.last_24h_energy_kwh) + " kWh", "cost " + num(current.last_24h_cost));

    const summary = await api("/energy/summary");
    table(
      "energy-summary",
      ["Machine", "Energy last 24h (kWh)", "Cost last 24h", "Peak (kW)"],
      summary.machines.map((m) => [m.machine, num(m.energy_kwh), num(m.cost), num(m.peak_kw)])
    );

    const machine = document.getElementById("history-machine").value;
    const hours = document.getElementById("history-hours").value;
    const history = await api(`/energy/history?machine=${encodeURIComponent(machine)}&hours=${hours}`);
    table(
      "energy-history",
      ["Timestamp", "Energy (kWh)", "Tariff", "Peak window"],
      history.series
        .slice()
        .reverse()
        .slice(0, 60)
        .map((p) => [shortTime(p.timestamp), num(p.energy_kwh), num(p.tariff), p.is_peak_tariff ? "yes" : "no"])
    );
  } catch (error) {
    showMessage("Energy data failed: " + error.message, true);
  }
}

// -------------------------------- forecast -------------------------------- //
async function loadForecast() {
  try {
    const f = await api("/forecast?machine=ALL&horizon=24");
    document.getElementById("forecast-meta").innerHTML =
      card("Model", f.model, f.features.join(", ")) +
      card("Predicted peak", num(f.peak_demand_kw) + " kW", shortTime(f.peak_timestamp)) +
      card("Predicted 24h energy", num(f.predicted_total_kwh) + " kWh", "trained on " + f.trained_samples + " points") +
      card("Hold-out MAE", num(f.holdout_mae_kwh) + " kWh", "error on the last held-out hours");

    const max = Math.max(...f.series.map((p) => p.predicted_kwh), 1);
    document.getElementById("forecast-bars").innerHTML = f.series
      .map((p) => {
        const height = Math.max(4, (p.predicted_kwh / max) * 100);
        const hour = Number(p.timestamp.slice(11, 13));
        const isPeakHour = hour >= 18 && hour <= 21;
        return `<div class="bar ${isPeakHour ? "peak" : ""}" style="height:${height}%">
          <span>${shortTime(p.timestamp)} - ${num(p.predicted_kwh)} kWh</span></div>`;
      })
      .join("");

    table(
      "forecast-table",
      ["Timestamp", "Predicted demand (kW average per hour)"],
      f.series.map((p) => [shortTime(p.timestamp), num(p.predicted_kwh)])
    );
  } catch (error) {
    showMessage("Forecast failed: " + error.message, true);
  }
}

// ------------------------------- anomalies -------------------------------- //
async function loadAnomalies() {
  try {
    const a = await api("/anomalies?limit=25");
    document.getElementById("anomaly-meta").innerHTML =
      card("Model", a.model, a.features.join(", ")) +
      card("Anomalies flagged", a.anomaly_count, "out of " + a.total_readings + " readings") +
      card("Injected readings found", a.injected_detected + " / " + a.injected_readings, "detector verification") +
      card("Contamination", a.contamination, "Isolation Forest setting");

    table(
      "anomaly-table",
      ["Timestamp", "Machine", "Energy (kWh)", "Typical (kWh)", "Excess (kWh)", "kWh/unit", "Score", "Injected"],
      a.items.map((i) => [
        shortTime(i.timestamp),
        i.machine,
        num(i.energy_kwh),
        num(i.typical_energy_kwh),
        num(i.excess_kwh),
        i.energy_per_unit === null ? "-" : num(i.energy_per_unit, 3),
        num(i.anomaly_score, 3),
        i.is_injected_anomaly ? "yes" : "no",
      ])
    );
  } catch (error) {
    showMessage("Anomaly detection failed: " + error.message, true);
  }
}

// ----------------------------- recommendations ---------------------------- //
async function loadRecommendations() {
  const status = document.getElementById("rec-filter").value;
  try {
    const list = await api("/recommendations?status=" + status);
    if (!list.length) {
      document.getElementById("recommendation-list").innerHTML =
        "<p>No recommendations for this filter. Use 'Run rule engine'.</p>";
      return;
    }
    document.getElementById("recommendation-list").innerHTML = list
      .map(
        (r) => `
      <div class="rec">
        <h3>${r.title} <span class="badge ${r.status}">${r.status}</span></h3>
        <p><strong>Rule:</strong> ${r.rule} &middot; <strong>Machine:</strong> ${r.machine} &middot;
           <strong>Risk:</strong> ${r.risk_level} &middot; <strong>Decision:</strong> ${r.decision || "-"}</p>
        <p><strong>Reason:</strong> ${r.reason}</p>
        <p><strong>Action:</strong> ${r.action}</p>
        <p><strong>Estimated impact:</strong> ${num(r.est_energy_impact_kwh)} kWh,
           cost ${num(r.est_cost_impact)}, production impact ${num(r.production_impact_pct)}%
           (load moved: ${num(r.shift_kwh)} kWh, window ${String(r.shift_from_hour).padStart(2, "0")}:00 to
           ${String(r.shift_to_hour).padStart(2, "0")}:00)</p>
        ${r.decision_note ? `<p><strong>Operator note:</strong> ${r.decision_note}</p>` : ""}
        <div class="actions">
          <button onclick="decide(${r.id}, 'approve')" ${r.status !== "pending" ? "disabled" : ""}>Approve</button>
          <button onclick="decide(${r.id}, 'override')" ${r.status === "simulated" ? "disabled" : ""}>Override</button>
          <button onclick="simulate(${r.id})" ${r.status === "pending" ? "disabled" : ""}>Simulate</button>
        </div>
      </div>`
      )
      .join("");
  } catch (error) {
    showMessage("Recommendations failed: " + error.message, true);
  }
}

async function generateRecommendations() {
  try {
    const created = await api("/recommendations/generate", "POST");
    showMessage(`Rule engine finished. New recommendations: ${created.length}`);
    loadRecommendations();
  } catch (error) {
    showMessage("Rule engine failed: " + error.message, true);
  }
}

async function decide(id, action) {
  const note = prompt(action === "approve" ? "Optional approval note:" : "Reason for override (optional):");
  if (note === null) return;
  try {
    const updated = await api(`/recommendations/${id}/${action}`, "POST", { note });
    showMessage(`Recommendation ${id} is now '${updated.status}'.`);
    loadRecommendations();
  } catch (error) {
    showMessage("Decision failed: " + error.message, true);
  }
}

async function simulate(id) {
  try {
    await api(`/recommendations/${id}/simulate`, "POST");
    showMessage(`Recommendation ${id} simulated. See Simulation / Savings.`);
    loadRecommendations();
  } catch (error) {
    showMessage("Simulation failed: " + error.message, true);
  }
}

// --------------------------- simulations / savings ------------------------ //
async function loadSimulations() {
  try {
    const list = await api("/simulations");
    const energySaved = list.reduce((sum, s) => sum + s.energy_saved_kwh, 0);
    const costSaved = list.reduce((sum, s) => sum + s.cost_saved, 0);
    const peakCut = list.reduce((sum, s) => sum + s.peak_reduction_kw, 0);
    document.getElementById("savings-totals").innerHTML =
      card("Simulations run", list.length, "approved / overridden recommendations") +
      card("Energy saved", num(energySaved) + " kWh", "baseline minus simulated") +
      card("Money saved", num(costSaved), "simulated figures only") +
      card("Peak reduction", num(peakCut) + " kW", "sum over simulations");

    table(
      "simulation-table",
      ["Sim #", "Rec #", "Baseline kWh", "Simulated kWh", "Energy saved", "Baseline cost",
       "Simulated cost", "Cost saved", "Peak before / after"],
      list.map((s) => [
        s.id,
        s.recommendation_id,
        num(s.baseline_energy_kwh),
        num(s.simulated_energy_kwh),
        num(s.energy_saved_kwh),
        num(s.baseline_cost),
        num(s.simulated_cost),
        num(s.cost_saved),
        num(s.baseline_peak_kw) + " / " + num(s.simulated_peak_kw),
      ])
    );
  } catch (error) {
    showMessage("Simulation results failed: " + error.message, true);
  }
}

// --------------------------------- start ---------------------------------- //
loadDashboard();
