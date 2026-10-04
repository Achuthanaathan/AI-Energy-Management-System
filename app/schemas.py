"""Pydantic schemas used by the API."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    machine: str
    energy_kwh: float
    production_units: float
    tariff: float
    peak_demand_kw: float


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    rule: str
    created_at: datetime
    machine: str
    title: str
    reason: str
    action: str
    shift_kwh: float
    est_energy_impact_kwh: float
    est_cost_impact: float
    production_impact_pct: float
    risk_level: str
    shift_from_hour: int
    shift_to_hour: int
    window_hours: int
    forecast_peak_kw: float
    status: str
    decision: Optional[str] = None
    decision_note: Optional[str] = None
    decided_at: Optional[datetime] = None


class SimulationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_id: int
    created_at: datetime
    baseline_energy_kwh: float
    simulated_energy_kwh: float
    energy_saved_kwh: float
    baseline_cost: float
    simulated_cost: float
    cost_saved: float
    baseline_peak_kw: float
    simulated_peak_kw: float
    peak_reduction_kw: float
    note: str


class DecisionIn(BaseModel):
    note: Optional[str] = None
