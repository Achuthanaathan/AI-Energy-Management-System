"""Anomaly detection with Isolation Forest.

Note: the model flags statistically unusual energy/consumption patterns.
It does NOT know the physical cause of an anomaly.

Features are normalised per machine so that a normal plant peak-demand event
(high energy, high production) is not confused with a genuine anomaly
(unusually high energy for the amount produced).
"""
import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

from app.models import EnergyReading

CONTAMINATION = 0.02
FEATURES = ["energy_ratio_vs_machine_median", "energy_per_unit_ratio", "hour_of_day", "is_peak_tariff"]


def detect_anomalies(db: Session, limit: int = 25, contamination: float = CONTAMINATION) -> dict:
    rows = db.query(EnergyReading).order_by(EnergyReading.timestamp).all()
    if len(rows) < 20:
        return {
            "model": "IsolationForest",
            "features": FEATURES,
            "contamination": contamination,
            "total_readings": len(rows),
            "anomaly_count": 0,
            "injected_readings": 0,
            "injected_detected": 0,
            "items": [],
        }

    energy_by_machine: dict = {}
    unit_by_machine: dict = {}
    for row in rows:
        energy_by_machine.setdefault(row.machine, []).append(row.energy_kwh)
        if row.production_units:
            unit_by_machine.setdefault(row.machine, []).append(row.energy_kwh / row.production_units)

    median_energy = {m: float(np.median(v)) for m, v in energy_by_machine.items()}
    median_unit = {m: (float(np.median(v)) or 1.0) for m, v in unit_by_machine.items()}

    def energy_ratio(row):
        return row.energy_kwh / (median_energy.get(row.machine) or 1.0)

    def unit_ratio(row):
        if not row.production_units:
            return 1.0
        return (row.energy_kwh / row.production_units) / median_unit.get(row.machine, 1.0)

    X = np.array(
        [
            [energy_ratio(row), unit_ratio(row), row.timestamp.hour / 23.0, float(row.is_peak_tariff)]
            for row in rows
        ],
        dtype=float,
    )
    model = IsolationForest(n_estimators=100, contamination=contamination, random_state=42)
    labels = model.fit_predict(X)
    scores = model.decision_function(X)  # lower score = more anomalous

    items = []
    for row, label, score in zip(rows, labels, scores):
        if label != -1:
            continue
        baseline = median_energy.get(row.machine, row.energy_kwh)
        energy_per_unit = (row.energy_kwh / row.production_units) if row.production_units else None
        items.append(
            {
                "timestamp": row.timestamp,
                "machine": row.machine,
                "energy_kwh": row.energy_kwh,
                "production_units": row.production_units,
                "energy_per_unit": round(energy_per_unit, 4) if energy_per_unit else None,
                "energy_per_unit_ratio": round(unit_ratio(row), 3),
                "typical_energy_kwh": round(baseline, 2),
                "excess_kwh": round(max(0.0, row.energy_kwh - baseline), 2),
                "tariff": row.tariff,
                "is_peak_tariff": row.is_peak_tariff,
                "anomaly_score": round(float(-score), 4),
                # ground truth, kept only so the demo/tests can verify detection works
                "is_injected_anomaly": bool(row.is_injected_anomaly),
            }
        )

    items.sort(key=lambda item: item["anomaly_score"], reverse=True)
    return {
        "model": "IsolationForest",
        "features": FEATURES,
        "contamination": contamination,
        "total_readings": len(rows),
        "anomaly_count": len(items),
        "injected_readings": sum(1 for row in rows if row.is_injected_anomaly),
        "injected_detected": sum(1 for item in items if item["is_injected_anomaly"]),
        "items": items[:limit],
    }
