"""Simple database models for the prototype.

Only three tables are needed:
  energy_readings, recommendations, simulation_results
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EnergyReading(Base):
    __tablename__ = "energy_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    machine: Mapped[str] = mapped_column(String(50), index=True)
    energy_kwh: Mapped[float] = mapped_column(Float)
    production_units: Mapped[float] = mapped_column(Float)
    tariff: Mapped[float] = mapped_column(Float)
    peak_demand_kw: Mapped[float] = mapped_column(Float)
    is_peak_tariff: Mapped[bool] = mapped_column(Boolean, default=False)
    # Only used to verify that the anomaly detector finds the injected readings.
    is_injected_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    rule: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    machine: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)

    # Estimated (not measured) impact shown to the user before simulation.
    shift_kwh: Mapped[float] = mapped_column(Float, default=0.0)
    est_energy_impact_kwh: Mapped[float] = mapped_column(Float, default=0.0)
    est_cost_impact: Mapped[float] = mapped_column(Float, default=0.0)
    production_impact_pct: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(20), default="low")

    # Time window used by the simulator.
    shift_from_hour: Mapped[int] = mapped_column(Integer, default=0)
    shift_to_hour: Mapped[int] = mapped_column(Integer, default=0)
    window_hours: Mapped[int] = mapped_column(Integer, default=1)

    forecast_peak_kw: Mapped[float] = mapped_column(Float, default=0.0)

    # pending -> approved | overridden -> simulated
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SimulationResult(Base):
    __tablename__ = "simulation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    baseline_energy_kwh: Mapped[float] = mapped_column(Float)
    simulated_energy_kwh: Mapped[float] = mapped_column(Float)
    energy_saved_kwh: Mapped[float] = mapped_column(Float)
    baseline_cost: Mapped[float] = mapped_column(Float)
    simulated_cost: Mapped[float] = mapped_column(Float)
    cost_saved: Mapped[float] = mapped_column(Float)
    baseline_peak_kw: Mapped[float] = mapped_column(Float)
    simulated_peak_kw: Mapped[float] = mapped_column(Float)
    peak_reduction_kw: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="")
