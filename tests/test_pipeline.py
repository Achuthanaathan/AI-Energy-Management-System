"""Unit and integration tests for the AETHER ETL pipeline and SQL analytics."""
from datetime import datetime, timedelta
import math
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analytics import (
    get_daily_energy_consumption,
    get_highest_consumption_readings,
    get_hourly_consumption_profile,
    get_machine_cost_summary,
    get_machine_energy_summary,
    get_peak_demand_periods,
    get_production_efficiency,
)
from app.database import Base
from app.models import EnergyReading, Recommendation, SimulationResult
from app.pipeline import (
    extract_energy_data,
    get_dataset_metadata,
    load_energy_data,
    run_pipeline,
    transform_reading,
    transform_records,
    validate_reading,
    validate_records,
)


@pytest.fixture
def isolated_db():
    """Create a completely isolated in-memory SQLite database for unit tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


# --------------------------------------------------------------------------- #
# 1. Dataset Generation and Reproducibility
# --------------------------------------------------------------------------- #
def test_dataset_reproducibility():
    """Same seed must produce identical telemetry; different seeds must differ."""
    start_ts = datetime(2026, 1, 1, 0, 0, 0)
    data_a1 = extract_energy_data(days=3, seed=42, start=start_ts)
    data_a2 = extract_energy_data(days=3, seed=42, start=start_ts)
    data_b = extract_energy_data(days=3, seed=99, start=start_ts)

    assert len(data_a1) == 3 * 24 * 4  # 3 days * 24h * 4 machines
    assert len(data_a1) == len(data_a2)
    assert data_a1 == data_a2, "Identical seed and start time must produce identical output."

    # Different seeds should produce different energy readings
    assert data_a1 != data_b, "Different seeds should produce different telemetry."


def test_dataset_invalid_days():
    """Extracting with invalid days should raise ValueError."""
    with pytest.raises(ValueError):
        extract_energy_data(days=0)


# --------------------------------------------------------------------------- #
# 2. Validation Stage Tests
# --------------------------------------------------------------------------- #
def test_validation_valid_record():
    valid = {
        "timestamp": datetime.now(),
        "machine": "CNC-Mill-01",
        "energy_kwh": 25.5,
        "production_units": 150.0,
        "tariff": 7.0,
        "peak_demand_kw": 25.5,
    }
    is_valid, errors = validate_reading(valid, index=0)
    assert is_valid is True
    assert len(errors) == 0


def test_validation_rejects_missing_fields():
    invalid = {
        "timestamp": datetime.now(),
        # machine missing
        "energy_kwh": 25.5,
        "production_units": 150.0,
        # tariff missing
    }
    is_valid, errors = validate_reading(invalid, index=0)
    assert is_valid is False
    error_fields = {e.field for e in errors}
    assert "machine" in error_fields
    assert "tariff" in error_fields


def test_validation_rejects_negative_and_nan():
    # Negative values
    invalid_neg = {
        "timestamp": datetime.now(),
        "machine": "Chiller-03",
        "energy_kwh": -10.0,
        "production_units": 100.0,
        "tariff": 7.0,
    }
    is_valid, errors = validate_reading(invalid_neg, index=1)
    assert is_valid is False
    assert any("cannot be negative" in e.reason for e in errors)

    # NaN / Inf values
    invalid_nan = {
        "timestamp": datetime.now(),
        "machine": "Chiller-03",
        "energy_kwh": float("nan"),
        "production_units": 100.0,
        "tariff": 7.0,
    }
    is_valid, errors = validate_reading(invalid_nan, index=2)
    assert is_valid is False
    assert any("NaN or Infinite" in e.reason for e in errors)


def test_validation_rejects_invalid_types_and_machines():
    # Boolean passed for float
    invalid_type = {
        "timestamp": datetime.now(),
        "machine": "Chiller-03",
        "energy_kwh": True,
        "production_units": 100.0,
        "tariff": 7.0,
    }
    is_valid, errors = validate_reading(invalid_type, index=3)
    assert is_valid is False
    assert any("must be numeric" in e.reason for e in errors)

    # Unknown machine with allowed_machines set
    invalid_machine = {
        "timestamp": datetime.now(),
        "machine": "Alien-Reactor-99",
        "energy_kwh": 50.0,
        "production_units": 100.0,
        "tariff": 7.0,
    }
    is_valid, errors = validate_reading(invalid_machine, index=4, allowed_machines={"CNC-Mill-01"})
    assert is_valid is False
    assert any("Unknown machine" in e.reason for e in errors)


def test_validate_records_batch():
    batch = [
        {"timestamp": datetime.now(), "machine": "CNC-Mill-01", "energy_kwh": 20.0, "production_units": 100.0, "tariff": 7.0},
        {"timestamp": datetime.now(), "machine": "", "energy_kwh": -5.0, "production_units": 0.0, "tariff": 7.0},
    ]
    valid, report = validate_records(batch)
    assert len(valid) == 1
    assert report.valid_count == 1
    assert report.invalid_count == 1
    assert report.is_valid is False


# --------------------------------------------------------------------------- #
# 3. Transform Stage Tests
# --------------------------------------------------------------------------- #
def test_transform_reading_metrics():
    now_str = "2026-10-15T18:00:00"
    raw = {
        "timestamp": now_str,
        "machine": "Compressor-02",
        "energy_kwh": 40.0,
        "production_units": 200.0,
        "tariff": 9.5,
    }
    transformed = transform_reading(raw)

    assert isinstance(transformed["timestamp"], datetime)
    assert transformed["timestamp"].hour == 18
    assert transformed["is_peak_tariff"] is True  # Hour 18 is peak tariff
    assert transformed["energy_cost"] == 380.0    # 40.0 * 9.5
    assert transformed["energy_per_unit"] == 0.2  # 40.0 / 200.0
    assert transformed["peak_demand_kw"] == 40.0


def test_transform_zero_production_units():
    """Verify division by zero is safely prevented when production_units is 0."""
    raw = {
        "timestamp": datetime.now(),
        "machine": "Chiller-03",
        "energy_kwh": 30.0,
        "production_units": 0.0,
        "tariff": 4.5,
    }
    transformed = transform_reading(raw)
    assert transformed["energy_per_unit"] == 0.0


# --------------------------------------------------------------------------- #
# 4. Load & Ingestion Safeguard Tests
# --------------------------------------------------------------------------- #
def test_load_and_duplicate_prevention(isolated_db):
    """Loading identical data twice must prevent duplicate rows when replace=False."""
    raw = extract_energy_data(days=2, seed=42)
    valid, _ = validate_records(raw)
    transformed = transform_records(valid)

    # First load
    inserted_1, skipped_1 = load_energy_data(isolated_db, transformed, replace=False)
    assert inserted_1 == len(transformed)
    assert skipped_1 == 0
    assert isolated_db.query(EnergyReading).count() == len(transformed)

    # Second load with identical data -> should skip all duplicates
    inserted_2, skipped_2 = load_energy_data(isolated_db, transformed, replace=False)
    assert inserted_2 == 0
    assert skipped_2 == len(transformed)
    assert isolated_db.query(EnergyReading).count() == len(transformed)


def test_dataset_replacement_safeguards_recommendations(isolated_db):
    """replace=True replaces energy readings while keeping recommendations intact."""
    # Seed recommendation and simulation records
    rec = Recommendation(
        code="TEST-REC-001",
        rule="peak_shift",
        machine="Compressor-02",
        title="Test Peak Shift",
        reason="Peak load detected",
        action="Shift load",
        shift_kwh=50.0,
        est_cost_impact=250.0,
        status="pending",
    )
    isolated_db.add(rec)
    isolated_db.commit()

    sim = SimulationResult(
        recommendation_id=rec.id,
        baseline_energy_kwh=100.0,
        simulated_energy_kwh=92.0,
        energy_saved_kwh=8.0,
        baseline_cost=950.0,
        simulated_cost=550.0,
        cost_saved=400.0,
        baseline_peak_kw=100.0,
        simulated_peak_kw=92.0,
        peak_reduction_kw=8.0,
        note="Verified test simulation",
    )
    isolated_db.add(sim)
    isolated_db.commit()

    # Ingest dataset with replace=True
    res = run_pipeline(isolated_db, days=2, seed=123, replace=True)
    assert res.status == "success"
    assert res.inserted_count == 2 * 24 * 4

    # Ensure recommendations and simulations were preserved
    assert isolated_db.query(Recommendation).count() == 1
    assert isolated_db.query(SimulationResult).count() == 1
    preserved_rec = isolated_db.query(Recommendation).filter_by(code="TEST-REC-001").first()
    assert preserved_rec is not None
    assert preserved_rec.machine == "Compressor-02"


# --------------------------------------------------------------------------- #
# 5. SQL Analytics Tests
# --------------------------------------------------------------------------- #
def test_sql_analytics_calculations(isolated_db):
    """Test SQL analytics calculations against known injected readings."""
    ts = datetime(2026, 5, 1, 12, 0, 0)
    readings = [
        EnergyReading(
            timestamp=ts,
            machine="CNC-Mill-01",
            energy_kwh=50.0,
            production_units=200.0,
            tariff=7.0,
            peak_demand_kw=50.0,
            is_peak_tariff=False,
            is_injected_anomaly=False,
        ),
        EnergyReading(
            timestamp=ts,
            machine="Compressor-02",
            energy_kwh=100.0,
            production_units=400.0,
            tariff=9.5,
            peak_demand_kw=100.0,
            is_peak_tariff=True,
            is_injected_anomaly=True,
        ),
    ]
    isolated_db.add_all(readings)
    isolated_db.commit()

    # 1. Machine energy summary
    energy_summary = get_machine_energy_summary(isolated_db)
    assert energy_summary["total_plant_energy_kwh"] == 150.0
    assert len(energy_summary["machines"]) == 2
    # Compressor-02: 100 kWh -> 66.67%
    comp = next(m for m in energy_summary["machines"] if m["machine"] == "Compressor-02")
    assert comp["total_energy_kwh"] == 100.0
    assert comp["percentage_of_total"] == pytest.approx(66.67, abs=0.01)

    # 2. Machine cost summary
    cost_summary = get_machine_cost_summary(isolated_db)
    # CNC-Mill-01 cost = 50 * 7 = 350; Compressor-02 cost = 100 * 9.5 = 950; Total = 1300
    assert cost_summary["total_plant_cost"] == 1300.0

    # 3. Peak demand periods
    peaks = get_peak_demand_periods(isolated_db, limit=5)
    assert len(peaks) == 1
    assert peaks[0]["demand_kw"] == 150.0

    # 4. Production efficiency
    eff = get_production_efficiency(isolated_db)
    # Total units = 600. Total kWh = 150. SEC = 150 / 600 = 0.25
    assert eff["overall_sec_kwh_per_unit"] == 0.25

    # 5. Top consumers
    top = get_highest_consumption_readings(isolated_db, limit=5)
    assert len(top) == 2
    assert top[0]["machine"] == "Compressor-02"
    assert top[0]["energy_kwh"] == 100.0
    assert top[0]["is_injected_anomaly"] is True


def test_sql_analytics_empty_db(isolated_db):
    """Empty database should return graceful structured empty metrics without throwing."""
    energy_summary = get_machine_energy_summary(isolated_db)
    assert energy_summary["total_plant_energy_kwh"] == 0.0
    assert energy_summary["machines"] == []

    cost_summary = get_machine_cost_summary(isolated_db)
    assert cost_summary["total_plant_cost"] == 0.0

    daily = get_daily_energy_consumption(isolated_db)
    assert daily == []

    profile = get_hourly_consumption_profile(isolated_db)
    assert profile == []

    peaks = get_peak_demand_periods(isolated_db)
    assert peaks == []

    eff = get_production_efficiency(isolated_db)
    assert eff["overall_sec_kwh_per_unit"] == 0.0

    meta = get_dataset_metadata(isolated_db)
    assert meta["total_readings"] == 0


# --------------------------------------------------------------------------- #
# 6. FastAPI Endpoints Integration Tests
# --------------------------------------------------------------------------- #
def test_pipeline_and_analytics_api_endpoints(client):
    """Verify that all new pipeline and analytics endpoints respond with valid schemas."""
    # 1. Pipeline status
    res = client.get("/api/pipeline/status")
    assert res.status_code == 200
    body = res.json()
    assert "total_readings" in body
    assert body["total_readings"] > 0
    assert "machine_count" in body

    # 2. Machine summary
    res_m = client.get("/api/analytics/machine-summary")
    assert res_m.status_code == 200
    body_m = res_m.json()
    assert "energy" in body_m and "cost" in body_m
    assert len(body_m["energy"]["machines"]) > 0

    # 3. Daily consumption
    res_d = client.get("/api/analytics/daily?days=7")
    assert res_d.status_code == 200
    assert isinstance(res_d.json(), list)

    # 4. Hourly profile
    res_h = client.get("/api/analytics/hourly-profile")
    assert res_h.status_code == 200
    profile = res_h.json()
    assert len(profile) == 24

    # 5. Peak demand
    res_p = client.get("/api/analytics/peak-demand?limit=5")
    assert res_p.status_code == 200
    assert len(res_p.json()) <= 5

    # 6. Efficiency
    res_e = client.get("/api/analytics/efficiency")
    assert res_e.status_code == 200
    assert "overall_sec_kwh_per_unit" in res_e.json()

    # 7. Top consumers
    res_t = client.get("/api/analytics/top-consumers?limit=5")
    assert res_t.status_code == 200
    assert len(res_t.json()) == 5

    # 8. Pipeline run endpoint (dry-run style: incremental load with seed=42)
    res_run = client.post("/api/pipeline/run?days=2&seed=42&replace=false")
    assert res_run.status_code == 200
    body_run = res_run.json()
    assert body_run["status"] in ("success", "partial_success")
    assert "extracted_count" in body_run


# --------------------------------------------------------------------------- #
# 7. Atomic Replacement & Transaction Rollback Tests
# --------------------------------------------------------------------------- #
def test_atomic_replacement_rollback_on_failure(isolated_db, monkeypatch):
    """When replace=True and an error occurs during insertion, rollback must preserve previous dataset."""
    ts = datetime(2026, 1, 1, 10, 0, 0)
    initial_readings = [
        EnergyReading(
            timestamp=ts + timedelta(hours=i),
            machine="CNC-Mill-01",
            energy_kwh=25.0 + i,
            production_units=150.0,
            tariff=7.0,
            peak_demand_kw=25.0 + i,
            is_peak_tariff=False,
            is_injected_anomaly=False,
        )
        for i in range(10)
    ]
    isolated_db.add_all(initial_readings)
    isolated_db.commit()

    assert isolated_db.query(EnergyReading).count() == 10

    # Simulate an unexpected failure during bulk insertion
    from sqlalchemy.exc import SQLAlchemyError

    def failing_bulk_insert(*args, **kwargs):
        raise SQLAlchemyError("Simulated database write error during bulk insert")

    monkeypatch.setattr(isolated_db, "bulk_insert_mappings", failing_bulk_insert)

    replacement_records = [
        {
            "timestamp": datetime(2026, 2, 1, 10, 0, 0),
            "machine": "Chiller-03",
            "energy_kwh": 99.0,
            "production_units": 500.0,
            "tariff": 9.5,
            "peak_demand_kw": 99.0,
            "is_peak_tariff": True,
            "is_injected_anomaly": False,
        }
    ]

    with pytest.raises(SQLAlchemyError, match="Simulated database write error"):
        load_energy_data(isolated_db, replacement_records, replace=True)

    # Rollback must leave all 10 initial records intact
    remaining = isolated_db.query(EnergyReading).all()
    assert len(remaining) == 10
    assert all(r.machine == "CNC-Mill-01" for r in remaining)


# --------------------------------------------------------------------------- #
# 8. Destructive Endpoints Security & Authorization Tests
# --------------------------------------------------------------------------- #
def test_unauthorized_destructive_endpoints_rejected(client, monkeypatch):
    """Verify authorization safeguards on POST /api/reset and POST /api/pipeline/run?replace=true."""
    # Test A: When AETHER_ADMIN_TOKEN is configured
    monkeypatch.setenv("AETHER_ADMIN_TOKEN", "secure-admin-pass-123")
    monkeypatch.delenv("AETHER_ENABLE_DESTRUCTIVE_OPS", raising=False)
    monkeypatch.delenv("AETHER_PUBLIC_DEPLOYMENT", raising=False)

    # 1. POST /api/reset without credentials -> 401
    res_reset_no_auth = client.post("/api/reset")
    assert res_reset_no_auth.status_code == 401
    assert "Unauthorized" in res_reset_no_auth.json()["detail"]

    # 2. POST /api/reset with invalid token -> 401
    res_reset_wrong_auth = client.post("/api/reset", headers={"X-Admin-Token": "wrong-token"})
    assert res_reset_wrong_auth.status_code == 401

    # 3. POST /api/pipeline/run?replace=true without credentials -> 401
    res_replace_no_auth = client.post("/api/pipeline/run?days=7&seed=42&replace=true")
    assert res_replace_no_auth.status_code == 401
    assert "Unauthorized" in res_replace_no_auth.json()["detail"]

    # 4. Non-destructive pipeline run without credentials remains permitted -> 200
    res_non_destructive = client.post("/api/pipeline/run?days=7&seed=42&replace=false")
    assert res_non_destructive.status_code == 200

    # 5. POST /api/reset with valid credentials -> 200
    res_reset_valid = client.post("/api/reset", headers={"X-Admin-Token": "secure-admin-pass-123"})
    assert res_reset_valid.status_code == 200
    assert res_reset_valid.json()["status"] == "reset"

    # Test B: When public deployment is active without an admin token
    monkeypatch.delenv("AETHER_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("AETHER_PUBLIC_DEPLOYMENT", "true")

    res_public_reset = client.post("/api/reset")
    assert res_public_reset.status_code == 403
    assert "disabled" in res_public_reset.json()["detail"]

    res_public_replace = client.post("/api/pipeline/run?days=7&seed=42&replace=true")
    assert res_public_replace.status_code == 403

    # Test C: Explicitly disabled destructive operations
    monkeypatch.setenv("AETHER_ENABLE_DESTRUCTIVE_OPS", "false")
    res_disabled = client.post("/api/reset")
    assert res_disabled.status_code == 403


# --------------------------------------------------------------------------- #
# 9. Server Error Sanitization & Masking Tests
# --------------------------------------------------------------------------- #
def test_pipeline_internal_server_error_sanitization(client, monkeypatch):
    """When pipeline raises an unhandled internal exception, API logs it and returns generic HTTP 500."""
    from app import main

    def broken_run_pipeline(*args, **kwargs):
        raise RuntimeError("Sensitive internal database path: /secret/dir/db.sqlite: syntax error")

    monkeypatch.setattr(main, "run_pipeline", broken_run_pipeline)

    res = client.post("/api/pipeline/run?days=1&seed=42&replace=false")
    assert res.status_code == 500
    # Must NOT leak internal exception message or file paths
    assert "Sensitive internal database path" not in res.json()["detail"]
    assert res.json()["detail"] == "Pipeline execution failed due to an internal server error."
