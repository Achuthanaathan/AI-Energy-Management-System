"""Energy demand forecasting with Linear Regression + simple time/lag features.

Features (all known for the next 24 hours without recursion):
  hour, day_of_week, is_weekend, lag_24h, avg_prev_24h
"""
from datetime import timedelta

import numpy as np
from sklearn.linear_model import LinearRegression
from sqlalchemy.orm import Session

from app.models import EnergyReading

FEATURE_NAMES = ["hour", "day_of_week", "is_weekend", "lag_24h", "avg_prev_24h"]
MIN_HOURS = 48


def hourly_series(db: Session, machine: str | None = None):
    """Aggregate readings into an hourly series ordered by time.

    machine=None or "ALL" -> plant total (sum of all machines).
    """
    query = db.query(EnergyReading)
    if machine and machine.upper() != "ALL":
        query = query.filter(EnergyReading.machine == machine)
    rows = query.order_by(EnergyReading.timestamp).all()

    buckets: dict = {}
    for row in rows:
        buckets[row.timestamp] = buckets.get(row.timestamp, 0.0) + row.energy_kwh

    timestamps = sorted(buckets)
    values = np.array([buckets[ts] for ts in timestamps], dtype=float)
    return timestamps, values


def _features(timestamps, values, idx):
    ts = timestamps[idx]
    return [
        float(ts.hour),
        float(ts.weekday()),
        1.0 if ts.weekday() >= 5 else 0.0,
        float(values[idx - 24]),
        float(np.mean(values[idx - 24:idx])),
    ]


def forecast(db: Session, machine: str = "ALL", horizon: int = 24) -> dict:
    """Train a LinearRegression and predict the next `horizon` hours."""
    timestamps, values = hourly_series(db, machine)
    if len(values) < MIN_HOURS:
        raise ValueError("Not enough data to forecast (need at least %d hourly points)." % MIN_HOURS)

    X, y = [], []
    for i in range(24, len(values)):
        X.append(_features(timestamps, values, i))
        y.append(values[i])
    X = np.array(X, dtype=float)
    y = np.array(y, dtype=float)

    # Hold out the last few known hours so the UI can show an honest error figure.
    n_test = max(1, min(horizon, len(X) // 5))
    model = LinearRegression().fit(X[:-n_test], y[:-n_test])
    mae = float(np.mean(np.abs(model.predict(X[-n_test:]) - y[-n_test:])))

    # Re-fit on everything for the actual future prediction.
    model = LinearRegression().fit(X, y)

    last_ts = timestamps[-1]
    recent = values[-24:]
    recent_mean = float(np.mean(recent))

    points = []
    for h in range(1, horizon + 1):
        ts = last_ts + timedelta(hours=h)
        features = np.array(
            [[
                float(ts.hour),
                float(ts.weekday()),
                1.0 if ts.weekday() >= 5 else 0.0,
                float(recent[h - 1]),  # value 24h before this future hour
                recent_mean,
            ]]
        )
        predicted = max(0.0, float(model.predict(features)[0]))
        points.append({"timestamp": ts, "predicted_kwh": round(predicted, 2)})

    peak = max(points, key=lambda p: p["predicted_kwh"])
    lowest = min(points, key=lambda p: p["predicted_kwh"])

    return {
        "machine": (machine or "ALL").upper(),
        "model": "LinearRegression",
        "features": FEATURE_NAMES,
        "horizon_hours": horizon,
        "trained_samples": int(X.shape[0]),
        "holdout_mae_kwh": round(mae, 2),
        "series": points,
        "predicted_total_kwh": round(sum(p["predicted_kwh"] for p in points), 2),
        "peak_demand_kw": round(peak["predicted_kwh"], 2),
        "peak_timestamp": peak["timestamp"],
        "lowest_kw": round(lowest["predicted_kwh"], 2),
        "lowest_timestamp": lowest["timestamp"],
    }
