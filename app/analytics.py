"""SQL-based Energy Analytics Engine for AETHER.

Provides reusable SQL/SQLAlchemy analytics over actual stored database records:
- Machine energy breakdown and percentage share.
- Machine-wise energy costs and average cost per kWh.
- Daily energy consumption, cost, and peak demand.
- 24-hour diurnal load profiles (hourly average and peak).
- Peak-demand period detection.
- Specific Energy Consumption (SEC) / Energy efficiency per production unit.
- Highest-consumption anomaly & spike readings for operator investigation.

All queries execute against SQLite via SQLAlchemy ORM / func expressions.
No demonstration numbers or fixed strings are hardcoded.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.data_generator import PEAK_TARIFF_HOURS
from app.models import EnergyReading


def get_machine_energy_summary(db: Session) -> Dict[str, Any]:
    """Calculate total energy consumption and percentage share by machine.

    SQL equivalent:
        SELECT machine, SUM(energy_kwh), AVG(energy_kwh), COUNT(id)
        FROM energy_readings
        GROUP BY machine ORDER BY SUM(energy_kwh) DESC;
    """
    rows = (
        db.query(
            EnergyReading.machine.label("machine"),
            func.sum(EnergyReading.energy_kwh).label("total_kwh"),
            func.avg(EnergyReading.energy_kwh).label("avg_kwh"),
            func.min(EnergyReading.energy_kwh).label("min_kwh"),
            func.max(EnergyReading.energy_kwh).label("max_kwh"),
            func.count(EnergyReading.id).label("reading_count"),
        )
        .group_by(EnergyReading.machine)
        .order_by(desc("total_kwh"))
        .all()
    )

    if not rows:
        return {"total_plant_energy_kwh": 0.0, "machine_count": 0, "machines": []}

    total_plant_kwh = sum(r.total_kwh for r in rows)

    machines = []
    for r in rows:
        pct = (r.total_kwh / total_plant_kwh * 100.0) if total_plant_kwh > 0 else 0.0
        machines.append(
            {
                "machine": r.machine,
                "total_energy_kwh": round(r.total_kwh, 2),
                "avg_hourly_kwh": round(r.avg_kwh, 2),
                "min_hourly_kwh": round(r.min_kwh, 2),
                "max_hourly_kwh": round(r.max_kwh, 2),
                "percentage_of_total": round(pct, 2),
                "reading_count": r.reading_count,
            }
        )

    return {
        "total_plant_energy_kwh": round(total_plant_kwh, 2),
        "machine_count": len(machines),
        "machines": machines,
    }


def get_machine_cost_summary(db: Session) -> Dict[str, Any]:
    """Calculate machine-wise energy costs and average effective tariff.

    SQL equivalent:
        SELECT machine,
               SUM(energy_kwh * tariff) AS total_cost,
               SUM(energy_kwh) AS total_kwh
        FROM energy_readings
        GROUP BY machine ORDER BY total_cost DESC;
    """
    rows = (
        db.query(
            EnergyReading.machine.label("machine"),
            func.sum(EnergyReading.energy_kwh * EnergyReading.tariff).label("total_cost"),
            func.sum(EnergyReading.energy_kwh).label("total_kwh"),
            func.count(EnergyReading.id).label("reading_count"),
        )
        .group_by(EnergyReading.machine)
        .order_by(desc("total_cost"))
        .all()
    )

    if not rows:
        return {"total_plant_cost": 0.0, "total_plant_energy_kwh": 0.0, "machines": []}

    total_cost = sum(r.total_cost for r in rows)
    total_kwh = sum(r.total_kwh for r in rows)

    machines = []
    for r in rows:
        pct = (r.total_cost / total_cost * 100.0) if total_cost > 0 else 0.0
        effective_tariff = (r.total_cost / r.total_kwh) if r.total_kwh > 0 else 0.0
        machines.append(
            {
                "machine": r.machine,
                "total_cost": round(r.total_cost, 2),
                "total_energy_kwh": round(r.total_kwh, 2),
                "effective_tariff": round(effective_tariff, 4),
                "percentage_of_total_cost": round(pct, 2),
                "reading_count": r.reading_count,
            }
        )

    return {
        "total_plant_cost": round(total_cost, 2),
        "total_plant_energy_kwh": round(total_kwh, 2),
        "average_plant_tariff": round(total_cost / total_kwh, 4) if total_kwh > 0 else 0.0,
        "machines": machines,
    }


def get_daily_energy_consumption(
    db: Session,
    days: Optional[int] = None,
    machine: str = "ALL",
) -> List[Dict[str, Any]]:
    """Aggregate daily energy, cost, peak demand, and production units.

    SQL equivalent:
        SELECT DATE(timestamp) AS reading_date,
               SUM(energy_kwh) AS total_kwh,
               SUM(energy_kwh * tariff) AS total_cost,
               MAX(peak_demand_kw) AS peak_kw,
               SUM(production_units) AS total_units
        FROM energy_readings
        [WHERE machine = :machine]
        GROUP BY DATE(timestamp)
        ORDER BY reading_date ASC;
    """
    query = db.query(
        func.date(EnergyReading.timestamp).label("reading_date"),
        func.sum(EnergyReading.energy_kwh).label("total_kwh"),
        func.sum(EnergyReading.energy_kwh * EnergyReading.tariff).label("total_cost"),
        func.max(EnergyReading.peak_demand_kw).label("peak_kw"),
        func.sum(EnergyReading.production_units).label("total_units"),
        func.count(EnergyReading.id).label("reading_count"),
    )

    if machine.upper() != "ALL":
        query = query.filter(EnergyReading.machine == machine)

    if days is not None and days > 0:
        last_ts = db.query(func.max(EnergyReading.timestamp)).scalar()
        if last_ts is not None:
            cutoff = last_ts - timedelta(days=days)
            query = query.filter(EnergyReading.timestamp >= cutoff)

    rows = (
        query.group_by(func.date(EnergyReading.timestamp))
        .order_by("reading_date")
        .all()
    )

    result = []
    for r in rows:
        sec = round(r.total_kwh / r.total_units, 4) if r.total_units and r.total_units > 0 else 0.0
        result.append(
            {
                "date": str(r.reading_date),
                "total_energy_kwh": round(r.total_kwh, 2),
                "total_cost": round(r.total_cost, 2),
                "peak_demand_kw": round(r.peak_kw, 2),
                "production_units": round(r.total_units, 2),
                "sec_kwh_per_unit": sec,
                "reading_count": r.reading_count,
            }
        )

    return result


def get_hourly_consumption_profile(
    db: Session,
    machine: str = "ALL",
) -> List[Dict[str, Any]]:
    """Compute 24-hour diurnal profile (hours 0-23) across the entire dataset.

    Shows baseline operational shifts, peak tariff impact, and mean hourly load.
    """
    all_readings = db.query(EnergyReading)
    if machine.upper() != "ALL":
        all_readings = all_readings.filter(EnergyReading.machine == machine)
    all_rows = all_readings.all()

    if not all_rows:
        return []

    # Group by hour of day (0..23)
    hour_buckets: Dict[int, List[float]] = {h: [] for h in range(24)}
    for row in all_rows:
        h = row.timestamp.hour
        hour_buckets[h].append(row.energy_kwh)

    profile = []
    for h in range(24):
        vals = hour_buckets[h]
        if vals:
            avg_kw = sum(vals) / len(vals)
            max_kw = max(vals)
            min_kw = min(vals)
            count = len(vals)
        else:
            avg_kw = max_kw = min_kw = 0.0
            count = 0

        is_peak = h in PEAK_TARIFF_HOURS
        profile.append(
            {
                "hour": h,
                "hour_formatted": f"{h:02d}:00",
                "avg_demand_kw": round(avg_kw, 2),
                "min_demand_kw": round(min_kw, 2),
                "max_demand_kw": round(max_kw, 2),
                "sample_count": count,
                "is_peak_tariff_window": is_peak,
            }
        )

    return profile


def get_peak_demand_periods(
    db: Session,
    limit: int = 10,
    machine: str = "ALL",
) -> List[Dict[str, Any]]:
    """Identify the top peak-demand timestamps for the plant or machine.

    Aggregates plant-wide hourly load (sum of all machines at that hour)
    and sorts descending to surface peak demand events.
    """
    if limit <= 0:
        limit = 10

    query = db.query(
        EnergyReading.timestamp.label("timestamp"),
        func.sum(EnergyReading.energy_kwh).label("total_plant_kw"),
        func.max(EnergyReading.is_peak_tariff).label("is_peak_tariff"),
        func.count(EnergyReading.machine).label("machine_count"),
    )

    if machine.upper() != "ALL":
        query = query.filter(EnergyReading.machine == machine)

    rows = (
        query.group_by(EnergyReading.timestamp)
        .order_by(desc("total_plant_kw"))
        .limit(limit)
        .all()
    )

    results = []
    for rank, r in enumerate(rows, start=1):
        is_peak_window = r.timestamp.hour in PEAK_TARIFF_HOURS
        results.append(
            {
                "rank": rank,
                "timestamp": r.timestamp.isoformat(),
                "demand_kw": round(r.total_plant_kw, 2),
                "hour_of_day": r.timestamp.hour,
                "is_peak_tariff_window": is_peak_window,
                "active_machines": r.machine_count,
            }
        )

    return results


def get_production_efficiency(db: Session) -> Dict[str, Any]:
    """Calculate Specific Energy Consumption (SEC) = kWh / production unit per machine.

    Lower SEC represents higher industrial energy efficiency.
    """
    rows = (
        db.query(
            EnergyReading.machine.label("machine"),
            func.sum(EnergyReading.energy_kwh).label("total_kwh"),
            func.sum(EnergyReading.production_units).label("total_units"),
            func.count(EnergyReading.id).label("reading_count"),
        )
        .group_by(EnergyReading.machine)
        .order_by(EnergyReading.machine)
        .all()
    )

    if not rows:
        return {"overall_sec_kwh_per_unit": 0.0, "machines": []}

    total_kwh = sum(r.total_kwh for r in rows)
    total_units = sum(r.total_units for r in rows)
    overall_sec = round(total_kwh / total_units, 4) if total_units > 0 else 0.0

    machines = []
    for r in rows:
        sec = round(r.total_kwh / r.total_units, 4) if r.total_units > 0 else 0.0
        machines.append(
            {
                "machine": r.machine,
                "total_energy_kwh": round(r.total_kwh, 2),
                "total_production_units": round(r.total_units, 2),
                "sec_kwh_per_unit": sec,
                "variance_from_overall_pct": round(((sec - overall_sec) / overall_sec * 100.0), 2)
                if overall_sec > 0
                else 0.0,
                "reading_count": r.reading_count,
            }
        )

    return {
        "overall_sec_kwh_per_unit": overall_sec,
        "total_plant_energy_kwh": round(total_kwh, 2),
        "total_production_units": round(total_units, 2),
        "machines": machines,
    }


def get_highest_consumption_readings(
    db: Session,
    limit: int = 15,
    machine: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve top highest individual machine readings for operator investigation.

    Useful for isolating power spikes, machine overloading, and injected anomalies.
    """
    if limit <= 0:
        limit = 15

    query = db.query(EnergyReading)
    if machine and machine.upper() != "ALL":
        query = query.filter(EnergyReading.machine == machine)

    rows = query.order_by(desc(EnergyReading.energy_kwh)).limit(limit).all()

    results = []
    for rank, r in enumerate(rows, start=1):
        cost = round(r.energy_kwh * r.tariff, 2)
        sec = round(r.energy_kwh / r.production_units, 4) if r.production_units > 0 else None
        results.append(
            {
                "rank": rank,
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "machine": r.machine,
                "energy_kwh": round(r.energy_kwh, 2),
                "production_units": round(r.production_units, 2),
                "sec_kwh_per_unit": sec,
                "tariff": r.tariff,
                "calculated_cost": cost,
                "is_peak_tariff": r.is_peak_tariff,
                "is_injected_anomaly": r.is_injected_anomaly,
            }
        )

    return results
