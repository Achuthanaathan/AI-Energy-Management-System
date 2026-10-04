"""Simple rule-based recommendation engine.

No optimisation solver is used - just two clear rules:
  RULE 1 (peak shift): forecast peak demand above a threshold and a flexible
                       load is running in the peak-tariff window -> shift it
                       to the cheapest hour in the forecast horizon.
  RULE 2 (investigate): a detected anomaly on a machine -> ask the operator
                        to investigate. No automatic control is ever applied.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.anomaly import detect_anomalies
from app.data_generator import PEAK_TARIFF_HOURS, tariff_for_hour
from app.forecasting import forecast
from app.models import EnergyReading, Recommendation

FLEXIBLE_MACHINE = "Compressor-02"
PEAK_THRESHOLD_KW = 180.0
WINDOW_HOURS = 3            # hours of duty cycle moved per day
EFFICIENCY_GAIN = 0.08      # assumed efficiency gain when running outside peak
MAX_ANOMALY_RECOMMENDATIONS = 2


def _flexible_load_kw(db: Session, machine: str) -> float:
    """Average power of the flexible machine during the peak-tariff window."""
    rows = (
        db.query(EnergyReading)
        .filter(EnergyReading.machine == machine)
        .order_by(EnergyReading.timestamp)
        .all()
    )
    peak_hour_values = [row.energy_kwh for row in rows if row.timestamp.hour in PEAK_TARIFF_HOURS]
    if not peak_hour_values:
        return 0.0
    recent = peak_hour_values[-4 * len(PEAK_TARIFF_HOURS):]  # last 4 days of peak hours
    return round(sum(recent) / len(recent), 2)


def _exists(db: Session, code: str) -> bool:
    return db.query(Recommendation).filter(Recommendation.code == code).first() is not None


def _peak_shift_recommendation(db: Session, fc: dict):
    """RULE 1 - move a flexible load out of the peak-tariff window."""
    peak_ts = fc["peak_timestamp"]
    from_hour = peak_ts.hour
    tariff_from = tariff_for_hour(from_hour)

    # Cheapest hour in the forecast horizon, preferring a similar time of day.
    destination = min(
        fc["series"],
        key=lambda p: (tariff_for_hour(p["timestamp"].hour), abs(p["timestamp"].hour - from_hour)),
    )
    to_hour = destination["timestamp"].hour
    tariff_to = tariff_for_hour(to_hour)

    code = f"PEAK_SHIFT_{peak_ts.strftime('%Y%m%d%H')}"
    if tariff_to >= tariff_from or _exists(db, code):
        return None

    flex_kw = _flexible_load_kw(db, FLEXIBLE_MACHINE)
    shift_kwh = round(flex_kw * WINDOW_HOURS, 2)
    energy_saved = round(shift_kwh * EFFICIENCY_GAIN, 2)
    cost_saved = round(shift_kwh * (tariff_from - tariff_to) + energy_saved * tariff_to, 2)

    return Recommendation(
        code=code,
        rule="peak_shift",
        created_at=datetime.now(),
        machine=FLEXIBLE_MACHINE,
        title=f"Shift {FLEXIBLE_MACHINE} load out of the {from_hour:02d}:00 peak window",
        reason=(
            f"Forecast peak demand is {fc['peak_demand_kw']:.1f} kW at "
            f"{peak_ts.strftime('%Y-%m-%d %H:%M')}, above the plant threshold of "
            f"{PEAK_THRESHOLD_KW:.0f} kW. {FLEXIBLE_MACHINE} is a flexible load of about "
            f"{flex_kw:.1f} kW running in the peak-tariff window at {tariff_from:.2f}/kWh."
        ),
        action=(
            f"Move roughly {shift_kwh:.1f} kWh of {FLEXIBLE_MACHINE} duty cycle from the "
            f"{from_hour:02d}:00-{(from_hour + WINDOW_HOURS) % 24:02d}:00 peak-tariff window to "
            f"{to_hour:02d}:00 where the tariff is {tariff_to:.2f}/kWh. "
            f"Simulation only - no equipment is controlled."
        ),
        shift_kwh=shift_kwh,
        est_energy_impact_kwh=energy_saved,
        est_cost_impact=cost_saved,
        production_impact_pct=0.0,
        risk_level="low",
        shift_from_hour=from_hour,
        shift_to_hour=to_hour,
        window_hours=WINDOW_HOURS,
        forecast_peak_kw=fc["peak_demand_kw"],
        status="pending",
    )


def _anomaly_recommendations(db: Session, anomaly_report: dict, fc: dict):
    """RULE 2 - ask an operator to investigate detected anomalies."""
    created = []
    seen_machines = set()
    for anomaly in anomaly_report["items"]:
        if len(seen_machines) >= MAX_ANOMALY_RECOMMENDATIONS:
            break
        if anomaly["machine"] in seen_machines or anomaly["excess_kwh"] <= 0:
            continue
        seen_machines.add(anomaly["machine"])

        code = f"ANOMALY_CHECK_{anomaly['machine']}_{anomaly['timestamp'].strftime('%Y%m%d%H')}"
        if _exists(db, code):
            continue

        recoverable = round(anomaly["excess_kwh"] * 0.5, 2)  # modest assumption
        recommendation = Recommendation(
            code=code,
            rule="anomaly_check",
            created_at=datetime.now(),
            machine=anomaly["machine"],
            title=f"Investigate abnormal energy use on {anomaly['machine']}",
            reason=(
                f"Isolation Forest flagged {anomaly['energy_kwh']:.1f} kWh at "
                f"{anomaly['timestamp'].strftime('%Y-%m-%d %H:%M')}, about {anomaly['excess_kwh']:.1f} kWh above "
                f"the usual {anomaly['typical_energy_kwh']:.1f} kWh for this machine (energy per production unit: "
                f"{anomaly['energy_per_unit']}). The statistical model cannot say what caused it - possible causes "
                f"include a stuck load, a faulty sensor or idle running."
            ),
            action=(
                f"Ask maintenance to inspect {anomaly['machine']} for idle/unloaded running, leaks and sensor "
                f"calibration. No automatic action is taken on any equipment."
            ),
            shift_kwh=0.0,
            est_energy_impact_kwh=recoverable,
            est_cost_impact=round(recoverable * anomaly["tariff"], 2),
            production_impact_pct=0.0,
            risk_level="medium",
            shift_from_hour=anomaly["timestamp"].hour,
            shift_to_hour=anomaly["timestamp"].hour,
            window_hours=1,
            forecast_peak_kw=fc["peak_demand_kw"],
            status="pending",
        )
        created.append(recommendation)
    return created


def generate_recommendations(db: Session) -> list[Recommendation]:
    """Run every rule and store any new pending recommendation."""
    fc = forecast(db, horizon=24)
    anomaly_report = detect_anomalies(db, limit=MAX_ANOMALY_RECOMMENDATIONS * 3)

    created = []
    for candidate in (_peak_shift_recommendation(db, fc),):
        if candidate is not None:
            created.append(candidate)
    created.extend(_anomaly_recommendations(db, anomaly_report, fc))

    for recommendation in created:
        db.add(recommendation)
    db.commit()
    for recommendation in created:
        db.refresh(recommendation)
    return created


def list_recommendations(db: Session, status: str | None = None) -> list[Recommendation]:
    query = db.query(Recommendation).order_by(Recommendation.id.desc())
    if status and status.lower() != "all":
        query = query.filter(Recommendation.status == status.lower())
    return query.all()
