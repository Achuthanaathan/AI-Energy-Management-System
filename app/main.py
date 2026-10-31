"""FastAPI application: APIs + static frontend for the local prototype.

Run with:  python -m uvicorn app.main:app --reload
"""
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.anomaly import detect_anomalies
from app.analytics import (
    get_daily_energy_consumption,
    get_highest_consumption_readings,
    get_hourly_consumption_profile,
    get_machine_cost_summary,
    get_machine_energy_summary,
    get_peak_demand_periods,
    get_production_efficiency,
)
from app.pipeline import get_dataset_metadata, run_pipeline
from app.data_generator import PEAK_TARIFF_HOURS, generate_dataset, tariff_for_hour
from app.database import SessionLocal, get_db, init_db
from app.forecasting import forecast
from app.models import EnergyReading, Recommendation, SimulationResult
from app.recommendations import (
    FLEXIBLE_MACHINE,
    PEAK_THRESHOLD_KW,
    generate_recommendations,
    list_recommendations,
)
from app.schemas import DecisionIn, RecommendationOut, SimulationOut
from app.simulation import list_simulations, simulate_recommendation

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def seed_demo_data(db: Session) -> int:
    """Generate the simulated dataset and the first recommendations."""
    rows = generate_dataset()
    db.bulk_insert_mappings(EnergyReading, rows)
    db.commit()
    generate_recommendations(db)
    return len(rows)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        if db.query(EnergyReading).count() == 0:
            seed_demo_data(db)
    yield


logger = logging.getLogger("aether.api")

ADMIN_TOKEN_ENV_VAR = "AETHER_ADMIN_TOKEN"
ENABLE_DESTRUCTIVE_ENV_VAR = "AETHER_ENABLE_DESTRUCTIVE_OPS"
PUBLIC_DEPLOYMENT_ENV_VAR = "AETHER_PUBLIC_DEPLOYMENT"


def verify_destructive_access(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_token: Optional[str] = Query(None, alias="admin_token"),
) -> None:
    """Security guard for destructive operations (reset and dataset replacement).

    Policy:
    1. If AETHER_ENABLE_DESTRUCTIVE_OPS is 'false'/'0'/'disabled'/'no',
       destructive operations are disabled -> HTTP 403 Forbidden.
    2. If AETHER_ADMIN_TOKEN is configured in the environment:
       A matching 'X-Admin-Token' header or 'admin_token' query parameter is required.
       Missing or invalid token -> HTTP 401 Unauthorized.
    3. If AETHER_PUBLIC_DEPLOYMENT is 'true'/'1'/'yes' (or ENVIRONMENT='production')
       and no AETHER_ADMIN_TOKEN is configured:
       Destructive operations are disabled to protect public deployments -> HTTP 403 Forbidden.
    4. Otherwise (default local development and testing):
       Permitted without credentials so local workflows remain frictionless.
    """
    enable_flag = os.environ.get(ENABLE_DESTRUCTIVE_ENV_VAR, "").strip().lower()
    if enable_flag in ("false", "0", "disabled", "no"):
        raise HTTPException(
            status_code=403,
            detail="Destructive operations are disabled in this environment.",
        )

    configured_token = os.environ.get(ADMIN_TOKEN_ENV_VAR, "").strip()
    is_public = (
        os.environ.get(PUBLIC_DEPLOYMENT_ENV_VAR, "").strip().lower() in ("true", "1", "yes")
        or os.environ.get("ENVIRONMENT", "").strip().lower() in ("production", "public")
    )

    if configured_token:
        provided_token = x_admin_token or admin_token
        if not provided_token or provided_token != configured_token:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Valid administrator token required for destructive operations.",
            )
    elif is_public:
        raise HTTPException(
            status_code=403,
            detail="Destructive operations are disabled in public deployment when no administrator token is configured.",
        )


app = FastAPI(title="AI-Powered Energy Management System (prototype)", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Energy data
# --------------------------------------------------------------------------- #
def current_energy(db: Session) -> dict:
    last_ts = db.query(func.max(EnergyReading.timestamp)).scalar()
    if last_ts is None:
        raise HTTPException(status_code=404, detail="No energy data available.")
    rows = db.query(EnergyReading).filter(EnergyReading.timestamp == last_ts).all()
    last_24h = db.query(EnergyReading).filter(EnergyReading.timestamp > last_ts - timedelta(hours=24)).all()
    return {
        "timestamp": last_ts,
        "total_kw": round(sum(r.energy_kwh for r in rows), 2),
        "tariff": tariff_for_hour(last_ts.hour),
        "is_peak_tariff": last_ts.hour in PEAK_TARIFF_HOURS,
        "last_24h_energy_kwh": round(sum(r.energy_kwh for r in last_24h), 2),
        "last_24h_cost": round(sum(r.energy_kwh * r.tariff for r in last_24h), 2),
        "machines": [
            {
                "machine": r.machine,
                "energy_kwh": r.energy_kwh,
                "production_units": r.production_units,
                "energy_per_unit": round(r.energy_kwh / r.production_units, 4) if r.production_units else None,
                "peak_demand_kw": r.peak_demand_kw,
            }
            for r in sorted(rows, key=lambda r: r.machine)
        ],
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/energy/current")
def api_current_energy(db: Session = Depends(get_db)):
    return current_energy(db)


@app.get("/api/energy/history")
def api_history(machine: str = "ALL", hours: int = Query(72, ge=1, le=720), db: Session = Depends(get_db)):
    last_ts = db.query(func.max(EnergyReading.timestamp)).scalar()
    if last_ts is None:
        raise HTTPException(status_code=404, detail="No energy data available.")
    query = db.query(EnergyReading).filter(EnergyReading.timestamp > last_ts - timedelta(hours=hours))
    if machine.upper() != "ALL":
        query = query.filter(EnergyReading.machine == machine)
    rows = query.order_by(EnergyReading.timestamp).all()

    buckets: dict = {}
    for row in rows:
        buckets.setdefault(row.timestamp, []).append(row)
    series = [
        {
            "timestamp": ts,
            "energy_kwh": round(sum(r.energy_kwh for r in group), 2),
            "tariff": group[0].tariff,
            "is_peak_tariff": group[0].is_peak_tariff,
        }
        for ts, group in sorted(buckets.items())
    ]
    return {"machine": machine.upper(), "hours": hours, "series": series}


@app.get("/api/energy/summary")
def api_summary(db: Session = Depends(get_db)):
    last_ts = db.query(func.max(EnergyReading.timestamp)).scalar()
    if last_ts is None:
        raise HTTPException(status_code=404, detail="No energy data available.")
    all_rows = db.query(EnergyReading).order_by(EnergyReading.timestamp).all()
    recent = [r for r in all_rows if r.timestamp > last_ts - timedelta(hours=24)]

    per_machine: dict = {}
    for row in recent:
        entry = per_machine.setdefault(row.machine, {"energy_kwh": 0.0, "cost": 0.0, "peak_kw": 0.0})
        entry["energy_kwh"] += row.energy_kwh
        entry["cost"] += row.energy_kwh * row.tariff
        entry["peak_kw"] = max(entry["peak_kw"], row.peak_demand_kw)

    hourly_totals: dict = {}
    for row in recent:
        hourly_totals[row.timestamp] = hourly_totals.get(row.timestamp, 0.0) + row.energy_kwh
    peak_ts = max(hourly_totals, key=hourly_totals.get) if hourly_totals else last_ts

    days = (all_rows[-1].timestamp - all_rows[0].timestamp).total_seconds() / 86400
    return {
        "period_days": round(days, 2),
        "total_readings": len(all_rows),
        "last_24h_energy_kwh": round(sum(v["energy_kwh"] for v in per_machine.values()), 2),
        "last_24h_cost": round(sum(v["cost"] for v in per_machine.values()), 2),
        "last_24h_peak_kw": round(hourly_totals.get(peak_ts, 0.0), 2),
        "last_24h_peak_timestamp": peak_ts,
        "machines": [
            {
                "machine": name,
                "energy_kwh": round(v["energy_kwh"], 2),
                "cost": round(v["cost"], 2),
                "peak_kw": round(v["peak_kw"], 2),
            }
            for name, v in sorted(per_machine.items())
        ],
        "tariffs": {"off_peak": 4.5, "normal": 7.0, "peak": 9.5, "peak_hours": list(PEAK_TARIFF_HOURS)},
    }


# --------------------------------------------------------------------------- #
# Forecast + anomaly detection
# --------------------------------------------------------------------------- #
@app.get("/api/forecast")
def api_forecast(machine: str = "ALL", horizon: int = Query(24, ge=1, le=72), db: Session = Depends(get_db)):
    try:
        return forecast(db, machine=machine, horizon=horizon)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/anomalies")
def api_anomalies(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    return detect_anomalies(db, limit=limit)


# --------------------------------------------------------------------------- #
# Recommendations + human approval
# --------------------------------------------------------------------------- #
@app.get("/api/recommendations", response_model=List[RecommendationOut])
def api_recommendations(status: Optional[str] = None, db: Session = Depends(get_db)):
    return list_recommendations(db, status=status)


@app.post("/api/recommendations/generate", response_model=List[RecommendationOut])
def api_generate_recommendations(db: Session = Depends(get_db)):
    return generate_recommendations(db)


def _get_recommendation(db: Session, rec_id: int) -> Recommendation:
    recommendation = db.query(Recommendation).filter(Recommendation.id == rec_id).first()
    if recommendation is None:
        raise HTTPException(status_code=404, detail=f"Recommendation {rec_id} not found.")
    return recommendation


@app.post("/api/recommendations/{rec_id}/approve", response_model=RecommendationOut)
def api_approve(rec_id: int, body: Optional[DecisionIn] = None, db: Session = Depends(get_db)):
    recommendation = _get_recommendation(db, rec_id)
    if recommendation.status != "pending":
        raise HTTPException(status_code=400, detail=f"Recommendation is already '{recommendation.status}'.")
    recommendation.status = "approved"
    recommendation.decision = "approved"
    recommendation.decision_note = body.note if body else None
    recommendation.decided_at = datetime.now()
    db.commit()
    db.refresh(recommendation)
    return recommendation


@app.post("/api/recommendations/{rec_id}/override", response_model=RecommendationOut)
def api_override(rec_id: int, body: Optional[DecisionIn] = None, db: Session = Depends(get_db)):
    recommendation = _get_recommendation(db, rec_id)
    if recommendation.status == "simulated":
        raise HTTPException(status_code=400, detail="Recommendation has already been simulated.")
    recommendation.status = "overridden"
    recommendation.decision = "overridden"
    recommendation.decision_note = body.note if body else None
    recommendation.decided_at = datetime.now()
    db.commit()
    db.refresh(recommendation)
    return recommendation


# --------------------------------------------------------------------------- #
# Simulation + simulated Measurement & Verification
# --------------------------------------------------------------------------- #
@app.post("/api/recommendations/{rec_id}/simulate", response_model=SimulationOut)
def api_simulate(rec_id: int, db: Session = Depends(get_db)):
    recommendation = _get_recommendation(db, rec_id)
    if recommendation.status == "pending":
        raise HTTPException(
            status_code=400,
            detail="Approve or override the recommendation before simulating it.",
        )
    if recommendation.status == "simulated":
        existing = (
            db.query(SimulationResult)
            .filter(SimulationResult.recommendation_id == rec_id)
            .order_by(SimulationResult.id.desc())
            .first()
        )
        if existing is not None:
            return existing
    try:
        return simulate_recommendation(db, recommendation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/simulations", response_model=List[SimulationOut])
def api_simulations(db: Session = Depends(get_db)):
    return list_simulations(db)


@app.get("/api/simulations/{sim_id}", response_model=SimulationOut)
def api_simulation(sim_id: int, db: Session = Depends(get_db)):
    simulation = db.query(SimulationResult).filter(SimulationResult.id == sim_id).first()
    if simulation is None:
        raise HTTPException(status_code=404, detail=f"Simulation {sim_id} not found.")
    return simulation


@app.get("/api/dashboard")
def api_dashboard(db: Session = Depends(get_db)):
    current = current_energy(db)
    fc = forecast(db, horizon=24)
    anomaly_report = detect_anomalies(db, limit=3)
    recommendations = list_recommendations(db)
    simulations = list_simulations(db)

    pending = [r for r in recommendations if r.status == "pending"]
    latest = recommendations[0] if recommendations else None
    return {
        "current": {
            "timestamp": current["timestamp"],
            "total_kw": current["total_kw"],
            "tariff": current["tariff"],
            "is_peak_tariff": current["is_peak_tariff"],
            "last_24h_energy_kwh": current["last_24h_energy_kwh"],
            "last_24h_cost": current["last_24h_cost"],
        },
        "forecast": {
            "peak_demand_kw": fc["peak_demand_kw"],
            "peak_timestamp": fc["peak_timestamp"],
            "predicted_total_kwh": fc["predicted_total_kwh"],
            "holdout_mae_kwh": fc["holdout_mae_kwh"],
            "model": fc["model"],
        },
        "anomalies": {
            "count": anomaly_report["anomaly_count"],
            "injected_readings": anomaly_report["injected_readings"],
            "injected_detected": anomaly_report["injected_detected"],
            "top": anomaly_report["items"][:3],
        },
        "latest_recommendation": (
            RecommendationOut.model_validate(latest).model_dump(mode="json") if latest else None
        ),
        "recommendation_counts": {
            "total": len(recommendations),
            "pending": len(pending),
            "approved": sum(1 for r in recommendations if r.status == "approved"),
            "overridden": sum(1 for r in recommendations if r.status == "overridden"),
            "simulated": sum(1 for r in recommendations if r.status == "simulated"),
        },
        "savings": {
            "verified_energy_saved_kwh": round(sum(s.energy_saved_kwh for s in simulations), 2),
            "verified_cost_saved": round(sum(s.cost_saved for s in simulations), 2),
            "potential_cost_saved": round(sum(r.est_cost_impact for r in pending), 2),
            "simulation_count": len(simulations),
        },
        "settings": {
            "peak_threshold_kw": PEAK_THRESHOLD_KW,
            "flexible_machine": FLEXIBLE_MACHINE,
            "note": "Simulation only - no real equipment is controlled.",
        },
    }


@app.post("/api/reset")
def api_reset(
    db: Session = Depends(get_db),
    _auth: None = Depends(verify_destructive_access),
):
    """Re-generate the whole simulated dataset (handy for demos/tests)."""
    db.query(SimulationResult).delete()
    db.query(Recommendation).delete()
    db.query(EnergyReading).delete()
    db.commit()
    count = seed_demo_data(db)
    return {"status": "reset", "readings": count}



# --------------------------------------------------------------------------- #
# Data Pipeline & SQL-based Analytics
# --------------------------------------------------------------------------- #
@app.get("/api/pipeline/status")
def api_pipeline_status(db: Session = Depends(get_db)):
    """Retrieve metadata and status of the currently ingested dataset."""
    return get_dataset_metadata(db)


@app.post("/api/pipeline/run")
def api_pipeline_run(
    days: int = Query(30, ge=1, le=365, description="Number of days to simulate"),
    seed: int = Query(42, description="Random seed for reproducible data generation"),
    replace: bool = Query(False, description="Explicit flag: replace existing dataset if True"),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_token: Optional[str] = Query(None, alias="admin_token"),
    db: Session = Depends(get_db),
):
    """Execute the reproducible ETL pipeline (Extract -> Validate -> Transform -> Load)."""
    if replace:
        verify_destructive_access(x_admin_token=x_admin_token, admin_token=admin_token)

    try:
        result = run_pipeline(db, days=days, seed=seed, replace=replace)
        return result.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Pipeline execution failed")
        raise HTTPException(
            status_code=500,
            detail="Pipeline execution failed due to an internal server error.",
        ) from None


@app.get("/api/analytics/machine-summary")
def api_analytics_machines(db: Session = Depends(get_db)):
    """SQL analytics: Energy consumption and cost metrics by machine."""
    energy_summary = get_machine_energy_summary(db)
    cost_summary = get_machine_cost_summary(db)
    return {
        "energy": energy_summary,
        "cost": cost_summary,
    }


@app.get("/api/analytics/daily")
def api_analytics_daily(
    days: Optional[int] = Query(None, ge=1, le=365, description="Limit to last N days"),
    machine: str = Query("ALL", description="Filter by machine or 'ALL'"),
    db: Session = Depends(get_db),
):
    """SQL analytics: Daily aggregated consumption, cost, and peak demand."""
    return get_daily_energy_consumption(db, days=days, machine=machine)


@app.get("/api/analytics/hourly-profile")
def api_analytics_hourly_profile(
    machine: str = Query("ALL", description="Filter by machine or 'ALL'"),
    db: Session = Depends(get_db),
):
    """SQL analytics: 24-hour diurnal load profile (hours 0-23)."""
    return get_hourly_consumption_profile(db, machine=machine)


@app.get("/api/analytics/peak-demand")
def api_analytics_peak_demand(
    limit: int = Query(10, ge=1, le=100, description="Number of top peak hours to return"),
    machine: str = Query("ALL", description="Filter by machine or 'ALL'"),
    db: Session = Depends(get_db),
):
    """SQL analytics: Top peak-demand periods across the plant or per machine."""
    return get_peak_demand_periods(db, limit=limit, machine=machine)


@app.get("/api/analytics/efficiency")
def api_analytics_efficiency(db: Session = Depends(get_db)):
    """SQL analytics: Specific Energy Consumption (SEC) per production unit."""
    return get_production_efficiency(db)


@app.get("/api/analytics/top-consumers")
def api_analytics_top_consumers(
    limit: int = Query(15, ge=1, le=100, description="Number of top consumption readings"),
    machine: Optional[str] = Query(None, description="Optional machine filter"),
    db: Session = Depends(get_db),
):
    """SQL analytics: Top individual power readings for operator investigation."""
    return get_highest_consumption_readings(db, limit=limit, machine=machine)


# The frontend is served as static files; keep this mount LAST so that
# the /api/... routes above take precedence.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
