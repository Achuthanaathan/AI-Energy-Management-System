"""Simulated Measurement & Verification (M&V).

Nothing here touches real equipment. The "simulated" case is recomputed from
historical readings of the same window, applying the recommended load shift.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.data_generator import tariff_for_hour
from app.models import EnergyReading, Recommendation, SimulationResult

EFFICIENCY_GAIN = 0.08  # assumed efficiency gain when the load runs off-peak

M_AND_V_NOTE = (
    "Simulated Measurement & Verification. Baseline and simulated values come from the "
    "simulated dataset only - these are NOT real industrial savings."
)


def compute_mv(
    baseline_energy_kwh: float,
    baseline_cost: float,
    shift_kwh: float,
    tariff_from: float,
    tariff_to: float,
    efficiency_gain: float = EFFICIENCY_GAIN,
) -> dict:
    """Pure calculation used by the simulator and by the tests."""
    energy_saved = shift_kwh * efficiency_gain
    simulated_energy = baseline_energy_kwh - energy_saved
    simulated_cost = baseline_cost - shift_kwh * tariff_from + (shift_kwh - energy_saved) * tariff_to
    return {
        "baseline_energy_kwh": round(baseline_energy_kwh, 2),
        "simulated_energy_kwh": round(simulated_energy, 2),
        "energy_saved_kwh": round(energy_saved, 2),
        "baseline_cost": round(baseline_cost, 2),
        "simulated_cost": round(simulated_cost, 2),
        "cost_saved": round(baseline_cost - simulated_cost, 2),
    }


def _window_hours(shift_from_hour: int, window_hours: int) -> list[int]:
    return [(shift_from_hour + i) % 24 for i in range(max(1, window_hours))]


def simulate_recommendation(db: Session, recommendation: Recommendation) -> SimulationResult:
    """Compute the M&V result for an approved/overridden recommendation."""
    # Baseline day = the most recent day present in the dataset.
    last_ts = db.query(func.max(EnergyReading.timestamp)).scalar()
    baseline_date = last_ts.date()
    hours = _window_hours(recommendation.shift_from_hour, recommendation.window_hours)

    rows = (
        db.query(EnergyReading)
        .filter(EnergyReading.machine == recommendation.machine)
        .order_by(EnergyReading.timestamp)
        .all()
    )
    window_rows = [r for r in rows if r.timestamp.date() == baseline_date and r.timestamp.hour in hours]
    if not window_rows:
        raise ValueError("No baseline readings available for the recommendation window.")

    baseline_energy = sum(r.energy_kwh for r in window_rows)
    baseline_cost = sum(r.energy_kwh * tariff_for_hour(r.timestamp.hour) for r in window_rows)
    tariff_from = tariff_for_hour(recommendation.shift_from_hour)
    tariff_to = tariff_for_hour(recommendation.shift_to_hour)

    result = compute_mv(
        baseline_energy_kwh=baseline_energy,
        baseline_cost=baseline_cost,
        shift_kwh=baseline_energy,  # the whole window load is moved
        tariff_from=tariff_from,
        tariff_to=tariff_to,
    )

    # Peak demand of the plant in the same window: baseline vs after the shift.
    plant_rows = (
        db.query(EnergyReading)
        .filter(EnergyReading.timestamp >= last_ts.replace(hour=0, minute=0, second=0, microsecond=0))
        .order_by(EnergyReading.timestamp)
        .all()
    )
    per_hour_totals: dict = {}
    for row in plant_rows:
        per_hour_totals[row.timestamp] = per_hour_totals.get(row.timestamp, 0.0) + row.energy_kwh
    baseline_peak = max(
        (total for ts, total in per_hour_totals.items() if ts.hour in hours), default=0.0
    )
    machine_window_peak = max((r.peak_demand_kw for r in window_rows), default=0.0)
    simulated_peak = max(0.0, baseline_peak - machine_window_peak)

    simulation = SimulationResult(
        recommendation_id=recommendation.id,
        created_at=datetime.now(),
        baseline_energy_kwh=result["baseline_energy_kwh"],
        simulated_energy_kwh=result["simulated_energy_kwh"],
        energy_saved_kwh=result["energy_saved_kwh"],
        baseline_cost=result["baseline_cost"],
        simulated_cost=result["simulated_cost"],
        cost_saved=result["cost_saved"],
        baseline_peak_kw=round(baseline_peak, 2),
        simulated_peak_kw=round(simulated_peak, 2),
        peak_reduction_kw=round(baseline_peak - simulated_peak, 2),
        note=M_AND_V_NOTE,
    )
    db.add(simulation)

    recommendation.status = "simulated"
    db.commit()
    db.refresh(simulation)
    return simulation


def list_simulations(db: Session) -> list[SimulationResult]:
    return db.query(SimulationResult).order_by(SimulationResult.id.desc()).all()
