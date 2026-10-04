"""Focused end-to-end tests for the prototype (5 tests)."""
import pytest

from app.anomaly import detect_anomalies
from app.data_generator import tariff_for_hour
from app.forecasting import forecast
from app.recommendations import (
    FLEXIBLE_MACHINE,
    PEAK_THRESHOLD_KW,
    generate_recommendations,
    list_recommendations,
)
from app.simulation import compute_mv


# 1 ---------------------------------------------------------------- forecast
def test_forecast_returns_valid_output(db):
    result = forecast(db, machine="ALL", horizon=24)

    assert result["model"] == "LinearRegression"
    assert len(result["features"]) == 5
    assert len(result["series"]) == 24
    assert all(point["predicted_kwh"] >= 0 for point in result["series"])
    assert result["peak_demand_kw"] > 0
    assert result["predicted_total_kwh"] > 0
    assert result["holdout_mae_kwh"] >= 0
    assert result["trained_samples"] > 0


# 2 ------------------------------------------------------ anomaly detection
def test_injected_anomaly_is_detected(db):
    report = detect_anomalies(db, limit=200)

    assert report["model"] == "IsolationForest"
    assert report["anomaly_count"] > 0
    assert report["injected_readings"] > 0
    # The readings injected by the data generator must be found by the model.
    assert report["injected_detected"] > 0
    assert any(item["is_injected_anomaly"] for item in report["items"])


# 3 --------------------------------------------------- peak -> recommendation
def test_high_peak_demand_produces_recommendation(db):
    fc = forecast(db, machine="ALL", horizon=24)
    assert fc["peak_demand_kw"] >= PEAK_THRESHOLD_KW, "simulated peak event should exceed the threshold"

    generate_recommendations(db)
    peak_recs = [rec for rec in list_recommendations(db) if rec.rule == "peak_shift"]

    assert peak_recs, "no peak-shift recommendation was created"
    rec = peak_recs[0]
    assert rec.machine == FLEXIBLE_MACHINE
    assert rec.shift_kwh > 0
    assert rec.est_cost_impact > 0
    assert rec.status == "pending"
    # The load must move to a cheaper tariff window.
    assert tariff_for_hour(rec.shift_to_hour) < tariff_for_hour(rec.shift_from_hour)


# 4 -------------------------------------------------------- savings (M&V) math
def test_savings_calculation_is_correct():
    result = compute_mv(
        baseline_energy_kwh=200.0,
        baseline_cost=1900.0,     # 200 kWh at the 9.50 peak tariff
        shift_kwh=200.0,
        tariff_from=9.5,
        tariff_to=4.5,
        efficiency_gain=0.08,
    )

    assert result["energy_saved_kwh"] == pytest.approx(16.0)          # 200 * 0.08
    assert result["simulated_energy_kwh"] == pytest.approx(184.0)     # 200 - 16
    assert result["baseline_energy_kwh"] == pytest.approx(200.0)
    assert result["simulated_cost"] == pytest.approx(828.0)           # 184 * 4.5
    assert result["cost_saved"] == pytest.approx(1072.0)              # 1900 - 828
    assert result["cost_saved"] == pytest.approx(result["baseline_cost"] - result["simulated_cost"])


# 5 ------------------------------------------- approve / override -> simulation
def test_approve_and_override_change_status(client):
    pending = client.get("/api/recommendations?status=pending").json()
    assert len(pending) >= 2, "the demo dataset should create at least two pending recommendations"

    approved = client.post(f"/api/recommendations/{pending[0]['id']}/approve", json={"note": "approved for tonight"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["decision"] == "approved"

    overridden = client.post(f"/api/recommendations/{pending[1]['id']}/override", json={"note": "production needs it"})
    assert overridden.status_code == 200
    assert overridden.json()["status"] == "overridden"
    assert overridden.json()["decision"] == "overridden"

    # a decision cannot be applied twice
    assert client.post(f"/api/recommendations/{pending[0]['id']}/approve").status_code == 400

    # approved -> simulated, and the M&V figures are consistent
    simulation = client.post(f"/api/recommendations/{pending[0]['id']}/simulate")
    assert simulation.status_code == 200
    body = simulation.json()
    assert body["baseline_energy_kwh"] > body["simulated_energy_kwh"]
    assert body["cost_saved"] > 0
    assert body["energy_saved_kwh"] == pytest.approx(
        body["baseline_energy_kwh"] - body["simulated_energy_kwh"], abs=0.02
    )

    statuses = [rec["status"] for rec in client.get("/api/recommendations").json()]
    assert "simulated" in statuses
