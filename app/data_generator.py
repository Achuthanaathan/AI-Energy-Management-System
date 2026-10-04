"""Simulated industrial energy data.

This is a deliberately SIMPLE simulator for a college prototype.
It is not a realistic industrial process model.

Produces: 30 days x 24 hours x 4 machines of hourly readings, with
  * a high plant peak-demand event on the last few days
  * a small number of injected abnormal (very high) readings
"""
import random
from datetime import datetime, timedelta

MACHINES = [
    {"name": "CNC-Mill-01", "base_kw": 25.0, "shift_factor": 1.4, "flexible": False},
    {"name": "Compressor-02", "base_kw": 30.0, "shift_factor": 1.3, "flexible": True},
    {"name": "Chiller-03", "base_kw": 22.0, "shift_factor": 1.5, "flexible": True},
    {"name": "Conveyor-Line-04", "base_kw": 18.0, "shift_factor": 1.6, "flexible": False},
]

# Time-of-use tariff (currency units per kWh)
TARIFF_OFFPEAK = 4.5   # 22:00 - 05:59
TARIFF_NORMAL = 7.0    # 06:00 - 17:59
TARIFF_PEAK = 9.5      # 18:00 - 21:59

PEAK_TARIFF_HOURS = (18, 19, 20, 21)

UNITS_PER_KWH = 6.0            # simulated production output per kWh
PEAK_EVENT_DAYS = 4            # last N days contain the plant peak-demand event
PEAK_EVENT_MULTIPLIER = 2.6
INJECTED_ANOMALY_COUNT = 12
ANOMALY_MULTIPLIER_RANGE = (2.8, 4.0)


def tariff_for_hour(hour: int) -> float:
    if hour in PEAK_TARIFF_HOURS:
        return TARIFF_PEAK
    if 6 <= hour <= 17:
        return TARIFF_NORMAL
    return TARIFF_OFFPEAK


def generate_dataset(days: int = 30, seed: int = 42, start: datetime | None = None):
    """Return a list of reading dicts ready for bulk insertion."""
    rng = random.Random(seed)
    if start is None:
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        start = now - timedelta(hours=days * 24)

    rows = []
    for day in range(days):
        high_peak_day = day >= days - PEAK_EVENT_DAYS
        for hour in range(24):
            ts = start + timedelta(hours=day * 24 + hour)
            for machine in MACHINES:
                load = machine["base_kw"]
                if 8 <= hour <= 17:
                    load *= machine["shift_factor"]
                load *= 1 + rng.uniform(-0.06, 0.06)
                if high_peak_day and hour in PEAK_TARIFF_HOURS:
                    load *= PEAK_EVENT_MULTIPLIER
                energy = round(load, 2)
                production = round(energy * UNITS_PER_KWH * (1 + rng.uniform(-0.05, 0.05)), 2)
                rows.append(
                    {
                        "timestamp": ts,
                        "machine": machine["name"],
                        "energy_kwh": energy,
                        "production_units": production,
                        "tariff": tariff_for_hour(hour),
                        "peak_demand_kw": energy,  # hourly average power == hourly energy
                        "is_peak_tariff": hour in PEAK_TARIFF_HOURS,
                        "is_injected_anomaly": False,
                    }
                )

    _inject_anomalies(rows, rng, days)
    return rows


def _inject_anomalies(rows, rng, days):
    """Set a handful of readings to ~3-4x their normal value."""
    picked = set()
    attempts = 0
    max_day = max(2, days - PEAK_EVENT_DAYS)
    while len(picked) < INJECTED_ANOMALY_COUNT and attempts < 5000:
        attempts += 1
        day = rng.randrange(1, max_day)
        hour = rng.randrange(24)
        machine_idx = rng.randrange(len(MACHINES))
        key = (day, hour, machine_idx)
        if key in picked:
            continue
        picked.add(key)

        idx = (day * 24 + hour) * len(MACHINES) + machine_idx
        row = rows[idx]
        machine = MACHINES[machine_idx]
        base = machine["base_kw"]
        if 8 <= hour <= 17:
            base *= machine["shift_factor"]

        row["energy_kwh"] = round(base * rng.uniform(*ANOMALY_MULTIPLIER_RANGE), 2)
        # Production stays normal -> energy per unit produced is clearly abnormal.
        row["production_units"] = round(base * UNITS_PER_KWH * (1 + rng.uniform(-0.05, 0.05)), 2)
        row["peak_demand_kw"] = row["energy_kwh"]
        row["is_injected_anomaly"] = True
    return rows
