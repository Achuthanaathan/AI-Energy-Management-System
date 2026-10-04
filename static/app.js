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
// Lifecycle shown to the reviewer:
//   pending -> approved | overridden -> simulated -> savings verified (M&V)
async function loadRecommendations() {
  const status = document.getElementById("rec-filter").value;
  try {
    const [list, all, simulations] = await Promise.all([
      api("/recommendations?status=" + status),
      api("/recommendations"),
      api("/simulations"),
    ]);

    // Latest simulation per recommendation, so a simulated card can show its M&V result.
    const simsByRec = {};
    simulations.forEach((s) => {
      const current = simsByRec[s.recommendation_id];
      if (!current || current.id < s.id) simsByRec[s.recommendation_id] = s;
    });

    const counts = { pending: 0, approved: 0, overridden: 0, simulated: 0 };
    all.forEach((r) => { counts[r.status] = (counts[r.status] || 0) + 1; });
    document.getElementById("rec-summary").innerHTML =
      card("Step 1-2: pending decision", counts.pending, "Waiting for Approve or Override") +
      card("Step 3: approved, awaiting simulation", counts.approved, "Simulate is available") +
      card("Overridden by operator", counts.overridden, "Not part of the approved plan") +
      card("Step 4: simulated (M&V done)", counts.simulated, "Result shown on the card");

    if (!list.length) {
      document.getElementById("recommendation-list").innerHTML =
        "<p>No recommendations for this filter. Use 'Run rule engine' to create some.</p>";
      return;
    }
    document.getElementById("recommendation-list").innerHTML = list
      .map((r) => recommendationCard(r, simsByRec[r.id]))
      .join("");
  } catch (error) {
    showMessage("Recommendations failed: " + error.message, true);
  }
}

const REC_STEPS = [
  "AI recommendation",
  "Human decision (approve / override)",
  "Simulation (shadow mode)",
  "Savings verified (M&V)",
];

function showView(view) {
  const button = document.querySelector(`nav .tab[data-view="${view}"]`);
  if (button) button.click();
}

function lifecycleSteps(status) {
  const done = status === "simulated" ? [1, 2, 3, 4] : status === "pending" ? [1] : [1, 2];
  const current = status === "pending" ? 2 : status === "simulated" ? 0 : 3;
  const steps = REC_STEPS.map((label, index) => {
    const step = index + 1;
    const state = done.includes(step) ? "done" : step === current ? "current" : "";
    const mark = done.includes(step) ? "&#10003; " : step === current ? "&#9654; " : "";
    return `<div class="step ${state}"><span class="n">${step}</span>${mark}${label}</div>`;
  }).join("");
  return `<div class="steps">${steps}</div>`;
}

function statusLine(r) {
  const note = r.decision_note ? ` Operator note: "${r.decision_note}".` : "";
  if (r.status === "pending") {
    return "Status: PENDING - awaiting human decision. Approve to continue to the simulation step, or override to reject the suggestion.";
  }
  if (r.status === "approved") {
    return `Status: APPROVED - the operator accepted this action.${note} Next step: run the simulation to verify the savings.`;
  }
  if (r.status === "overridden") {
    return `Status: OVERRIDDEN by the operator - this action is NOT part of the approved plan.${note} The simulation can still be run as a counterfactual, if useful.`;
  }
  return `Status: SIMULATED - the action has moved from a recommendation to a simulated result.${note}`;
}

function simulationBox(sim) {
  if (!sim) {
    return `<div class="result-box"><h4>Step 4 - Simulation result</h4>
      <p class="result-note">No simulation result found for this recommendation yet. Press "Run simulation".</p></div>`;
  }
  return `<div class="result-box">
    <h4>Step 4 - Simulation completed (simulated Measurement &amp; Verification)</h4>
    <div class="mv">
      <div><div class="k">Baseline energy</div><div class="v">${num(sim.baseline_energy_kwh)} kWh</div></div>
      <div><div class="k">Simulated energy</div><div class="v">${num(sim.simulated_energy_kwh)} kWh</div></div>
      <div><div class="k">Energy saved</div><div class="v save">${num(sim.energy_saved_kwh)} kWh</div></div>
      <div><div class="k">Baseline cost</div><div class="v">${num(sim.baseline_cost)}</div></div>
      <div><div class="k">Simulated cost</div><div class="v">${num(sim.simulated_cost)}</div></div>
      <div><div class="k">Money saved</div><div class="v save">${num(sim.cost_saved)}</div></div>
      <div><div class="k">Peak before / after</div><div class="v">${num(sim.baseline_peak_kw)} / ${num(sim.simulated_peak_kw)} kW</div></div>
    </div>
    <p class="result-note">${sim.note}</p>
    <button onclick="showView('simulation')">Go to Savings / M&amp;V page</button>
  </div>`;
}

function recommendationCard(r, sim) {
  const hh = (hour) => String(hour).padStart(2, "0") + ":00";
  const canApprove = r.status === "pending";
  const canOverride = r.status !== "simulated";
  const canSimulate = r.status !== "pending";
  return `
  <div class="rec status-${r.status}">
    <div class="rec-head">
      <h3>Recommendation #${r.id}: ${r.title}</h3>
      <span class="badge ${r.status}">${r.status}</span>
    </div>
    <p class="rec-meta">Rule: <strong>${r.rule}</strong> &middot; Machine: <strong>${r.machine}</strong>
      &middot; Risk: <strong>${r.risk_level}</strong> &middot; Decision: <strong>${r.decision || "-"}</strong></p>

    ${lifecycleSteps(r.status)}
    <p class="status-line ${r.status}">${statusLine(r)}</p>

    <div class="rec-section"><span class="tag">Recommendation / suggested action</span>${r.action}</div>
    <div class="rec-section"><span class="tag">Reason</span>${r.reason}</div>

    <div class="impact">
      <div><div class="k">Estimated energy saved</div><div class="v good">${num(r.est_energy_impact_kwh)} kWh</div></div>
      <div><div class="k">Estimated money saved</div><div class="v good">${num(r.est_cost_impact)}</div></div>
      <div><div class="k">Load moved</div><div class="v">${num(r.shift_kwh)} kWh</div></div>
      <div><div class="k">Production impact</div><div class="v">${num(r.production_impact_pct, 1)}%</div></div>
      <div><div class="k">Risk</div><div class="v">${r.risk_level}</div></div>
      <div><div class="k">Shift window</div><div class="v">${hh(r.shift_from_hour)} &rarr; ${hh(r.shift_to_hour)}</div></div>
    </div>
    <p class="rec-meta">Estimates are model estimates, not measured values. Verified simulated figures appear after step 3.</p>

    ${sim ? simulationBox(sim) : ""}

    <div class="actions">
      <button onclick="decide(${r.id}, 'approve')" ${canApprove ? "" : 'disabled title="Only a pending recommendation can be approved"'}>Approve</button>
      <button onclick="decide(${r.id}, 'override')" ${canOverride ? "" : 'disabled title="Already simulated"'}>Override</button>
      <button onclick="simulate(${r.id})" ${canSimulate ? "" : 'disabled title="Approve or override the recommendation first"'}>Run simulation</button>
    </div>
  </div>`;
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
