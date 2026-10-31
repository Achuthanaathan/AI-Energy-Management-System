"""Reproducible Industrial Energy ETL Data Pipeline for AETHER.

Provides modular Extract, Validate, Transform, and Load (ETL) stages:
- Extract: Configurable generation or loading of hourly industrial telemetry.
- Validate: Strict schema, finite-numeric, non-negative, and constraint checks.
- Transform: Timestamp normalization, derived analytical metrics (cost, energy/unit).
- Load: Safe SQLite ingestion via SQLAlchemy with duplicate detection and safeguards.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.data_generator import MACHINES, PEAK_TARIFF_HOURS, generate_dataset, tariff_for_hour
from app.models import EnergyReading, Recommendation, SimulationResult

VALID_MACHINE_NAMES: Set[str] = {m["name"] for m in MACHINES}


@dataclass
class ValidationError:
    index: int
    field: str
    value: Any
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "field": self.field,
            "value": str(self.value) if self.value is not None else None,
            "reason": self.reason,
        }


@dataclass
class ValidationReport:
    total_records: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    errors: List[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.invalid_count == 0

    def to_dict(self, max_errors: int = 50) -> Dict[str, Any]:
        return {
            "total_records": self.total_records,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "error_count": len(self.errors),
            "errors": [err.to_dict() for err in self.errors[:max_errors]],
            "is_valid": self.is_valid,
        }


@dataclass
class PipelineResult:
    status: str
    extracted_count: int
    valid_count: int
    invalid_count: int
    inserted_count: int
    skipped_duplicates: int
    replaced_dataset: bool
    duration_seconds: float
    seed: Optional[int] = None
    days: Optional[int] = None
    validation_report: Optional[ValidationReport] = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "extracted_count": self.extracted_count,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "inserted_count": self.inserted_count,
            "skipped_duplicates": self.skipped_duplicates,
            "replaced_dataset": self.replaced_dataset,
            "duration_seconds": round(self.duration_seconds, 4),
            "seed": self.seed,
            "days": self.days,
            "validation": self.validation_report.to_dict() if self.validation_report else None,
            "message": self.message,
        }


# --------------------------------------------------------------------------- #
# 1. EXTRACT
# --------------------------------------------------------------------------- #
def extract_energy_data(
    days: int = 30,
    seed: int = 42,
    start: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Extract energy readings by generating a reproducible multi-machine dataset.

    Reuses app/data_generator.py with explicit configuration parameters.
    Default seed=42 guarantees identical output across repeated invocations.
    """
    if days <= 0:
        raise ValueError("Simulation duration 'days' must be greater than zero.")
    return generate_dataset(days=days, seed=seed, start=start)


# --------------------------------------------------------------------------- #
# 2. VALIDATE
# --------------------------------------------------------------------------- #
def validate_reading(
    record: Any,
    index: int,
    allowed_machines: Optional[Set[str]] = None,
) -> Tuple[bool, List[ValidationError]]:
    """Validate a single energy reading dictionary.

    Checks:
    - Must be a dictionary.
    - Required fields: timestamp, machine, energy_kwh, production_units, tariff.
    - Timestamp must be valid datetime or parseable ISO string.
    - Machine must be non-empty string.
    - Numeric values (energy_kwh, production_units, tariff, peak_demand_kw) must be:
      - finite (not NaN, not Inf)
      - non-negative (>= 0)
    """
    errors: List[ValidationError] = []

    if not isinstance(record, dict):
        return False, [
            ValidationError(
                index=index,
                field="record",
                value=type(record).__name__,
                reason="Record must be a dictionary.",
            )
        ]

    # Required fields presence check
    required_fields = ("timestamp", "machine", "energy_kwh", "production_units", "tariff")
    for req in required_fields:
        if req not in record or record[req] is None:
            errors.append(
                ValidationError(
                    index=index,
                    field=req,
                    value=None,
                    reason=f"Missing required field '{req}'.",
                )
            )

    # Validate machine
    machine = record.get("machine")
    if machine is not None:
        if not isinstance(machine, str) or not machine.strip():
            errors.append(
                ValidationError(
                    index=index,
                    field="machine",
                    value=machine,
                    reason="Machine must be a non-empty string.",
                )
            )
        elif allowed_machines and machine not in allowed_machines:
            errors.append(
                ValidationError(
                    index=index,
                    field="machine",
                    value=machine,
                    reason=f"Unknown machine '{machine}'. Expected one of {sorted(allowed_machines)}.",
                )
            )

    # Validate timestamp
    raw_ts = record.get("timestamp")
    if raw_ts is not None:
        if isinstance(raw_ts, str):
            try:
                datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                errors.append(
                    ValidationError(
                        index=index,
                        field="timestamp",
                        value=raw_ts,
                        reason="Timestamp string is not valid ISO 8601 format.",
                    )
                )
        elif not isinstance(raw_ts, datetime):
            errors.append(
                ValidationError(
                    index=index,
                    field="timestamp",
                    value=raw_ts,
                    reason="Timestamp must be a datetime object or ISO string.",
                )
            )

    # Helper for numeric validation
    def _validate_numeric(field_name: str, min_val: float = 0.0, optional: bool = False):
        val = record.get(field_name)
        if val is None:
            if not optional:
                # already captured in required_fields check
                pass
            return
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            errors.append(
                ValidationError(
                    index=index,
                    field=field_name,
                    value=val,
                    reason=f"Field '{field_name}' must be numeric (int or float).",
                )
            )
            return
        if math.isnan(val) or math.isinf(val):
            errors.append(
                ValidationError(
                    index=index,
                    field=field_name,
                    value=val,
                    reason=f"Field '{field_name}' cannot be NaN or Infinite.",
                )
            )
            return
        if val < min_val:
            errors.append(
                ValidationError(
                    index=index,
                    field=field_name,
                    value=val,
                    reason=f"Field '{field_name}' cannot be negative ({val} < {min_val}).",
                )
            )

    _validate_numeric("energy_kwh", min_val=0.0)
    _validate_numeric("production_units", min_val=0.0)
    _validate_numeric("tariff", min_val=0.0)
    _validate_numeric("peak_demand_kw", min_val=0.0, optional=True)

    return (len(errors) == 0, errors)


def validate_records(
    records: Sequence[Any],
    allowed_machines: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], ValidationReport]:
    """Validate a batch of energy records.

    Returns:
        (valid_records, validation_report)
    """
    valid_records: List[Dict[str, Any]] = []
    report = ValidationReport(total_records=len(records))

    for idx, record in enumerate(records):
        is_valid, errors = validate_reading(record, index=idx, allowed_machines=allowed_machines)
        if is_valid:
            valid_records.append(record)
            report.valid_count += 1
        else:
            report.invalid_count += 1
            report.errors.extend(errors)

    return valid_records, report


# --------------------------------------------------------------------------- #
# 3. TRANSFORM
# --------------------------------------------------------------------------- #
def transform_reading(record: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize and enrich a validated energy record.

    - Normalizes timestamp to a standard datetime object.
    - Sets peak_demand_kw (defaults to energy_kwh if missing).
    - Verifies is_peak_tariff flag against hour of day.
    - Calculates derived analytical fields:
      * energy_cost = energy_kwh * tariff
      * energy_per_unit = energy_kwh / production_units (safely handled if production_units == 0)
    - Preserves is_injected_anomaly flag.
    """
    raw_ts = record["timestamp"]
    if isinstance(raw_ts, str):
        # Handle ISO strings
        ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
    elif isinstance(raw_ts, datetime):
        ts = raw_ts.replace(tzinfo=None) if raw_ts.tzinfo is not None else raw_ts
    else:
        raise ValueError(f"Unsupported timestamp type: {type(raw_ts)}")

    energy = float(record["energy_kwh"])
    production = float(record["production_units"])
    tariff = float(record["tariff"])
    peak_kw = float(record.get("peak_demand_kw", energy))
    is_peak = bool(record.get("is_peak_tariff", ts.hour in PEAK_TARIFF_HOURS))
    is_anomaly = bool(record.get("is_injected_anomaly", False))

    # Derived analytical metrics
    energy_cost = round(energy * tariff, 4)
    energy_per_unit = round(energy / production, 4) if production > 0 else 0.0

    return {
        "timestamp": ts,
        "machine": str(record["machine"]).strip(),
        "energy_kwh": round(energy, 2),
        "production_units": round(production, 2),
        "tariff": round(tariff, 2),
        "peak_demand_kw": round(peak_kw, 2),
        "is_peak_tariff": is_peak,
        "is_injected_anomaly": is_anomaly,
        # Derived fields attached for analytics / storage
        "energy_cost": energy_cost,
        "energy_per_unit": energy_per_unit,
    }


def transform_records(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transform an entire batch of validated records."""
    return [transform_reading(r) for r in records]


# --------------------------------------------------------------------------- #
# 4. LOAD
# --------------------------------------------------------------------------- #
def load_energy_data(
    db: Session,
    records: Sequence[Dict[str, Any]],
    replace: bool = False,
) -> Tuple[int, int]:
    """Load transformed records into SQLite via SQLAlchemy.

    Safeguards:
    - If `replace=True`: Clears only `energy_readings`. Preserves existing
      `recommendations` and `simulation_results` to maintain audit trail.
    - If `replace=False`: Prevents duplicate records by checking (timestamp, machine)
      unique composite keys already in the database.

    Returns:
        (inserted_count, skipped_duplicates)
    """
    if not records:
        return 0, 0

    if replace:
        # Atomic replacement: delete existing readings and insert replacement readings
        # within a single database transaction. If insertion fails, rollback so the previous
        # dataset remains intact. Existing recommendations and simulations are preserved.
        try:
            db.query(EnergyReading).delete()

            # Database rows to insert (strip extra derived fields not in EnergyReading model)
            rows_to_insert = [
                {
                    "timestamp": r["timestamp"],
                    "machine": r["machine"],
                    "energy_kwh": r["energy_kwh"],
                    "production_units": r["production_units"],
                    "tariff": r["tariff"],
                    "peak_demand_kw": r["peak_demand_kw"],
                    "is_peak_tariff": r["is_peak_tariff"],
                    "is_injected_anomaly": r["is_injected_anomaly"],
                }
                for r in records
            ]
            db.bulk_insert_mappings(EnergyReading, rows_to_insert)
            db.commit()
            return len(rows_to_insert), 0
        except Exception:
            db.rollback()
            raise

    # Incremental safe load with duplicate prevention:
    # Find existing (timestamp, machine) combinations in the incoming time window
    timestamps = [r["timestamp"] for r in records]
    min_ts = min(timestamps)
    max_ts = max(timestamps)

    existing_pairs: Set[Tuple[datetime, str]] = set(
        db.query(EnergyReading.timestamp, EnergyReading.machine)
        .filter(EnergyReading.timestamp >= min_ts, EnergyReading.timestamp <= max_ts)
        .all()
    )

    new_rows = []
    skipped_duplicates = 0
    for r in records:
        key = (r["timestamp"], r["machine"])
        if key in existing_pairs:
            skipped_duplicates += 1
            continue
        existing_pairs.add(key)
        new_rows.append(
            {
                "timestamp": r["timestamp"],
                "machine": r["machine"],
                "energy_kwh": r["energy_kwh"],
                "production_units": r["production_units"],
                "tariff": r["tariff"],
                "peak_demand_kw": r["peak_demand_kw"],
                "is_peak_tariff": r["is_peak_tariff"],
                "is_injected_anomaly": r["is_injected_anomaly"],
            }
        )

    try:
        if new_rows:
            db.bulk_insert_mappings(EnergyReading, new_rows)
            db.commit()
        return len(new_rows), skipped_duplicates
    except Exception:
        db.rollback()
        raise


# --------------------------------------------------------------------------- #
# 5. PIPELINE RUNNER
# --------------------------------------------------------------------------- #
def run_pipeline(
    db: Session,
    days: int = 30,
    seed: int = 42,
    replace: bool = False,
    custom_records: Optional[Sequence[Any]] = None,
    allowed_machines: Optional[Set[str]] = None,
) -> PipelineResult:
    """Execute the end-to-end Extract-Validate-Transform-Load (ETL) pipeline.

    Args:
        db: Active SQLAlchemy database session.
        days: Duration in days to simulate if custom_records is None (default: 30).
        seed: Random seed for reproducible generation (default: 42).
        replace: If True, replace existing energy dataset safely without deleting recommendations.
        custom_records: Optional external records to validate and ingest instead of generated data.
        allowed_machines: Set of allowed machine names for validation. Defaults to MACHINES.

    Returns:
        PipelineResult detailing extraction, validation, and ingestion metrics.
    """
    start_time = time.perf_counter()

    # Step 1: Extract
    if custom_records is not None:
        extracted = list(custom_records)
    else:
        extracted = extract_energy_data(days=days, seed=seed)

    extracted_count = len(extracted)

    # Step 2: Validate
    valid_records, validation_report = validate_records(
        extracted,
        allowed_machines=allowed_machines if allowed_machines is not None else VALID_MACHINE_NAMES,
    )

    # Step 3: Transform
    transformed = transform_records(valid_records)

    # Step 4: Load
    inserted_count, skipped_duplicates = load_energy_data(db, transformed, replace=replace)

    duration = time.perf_counter() - start_time

    status = "success"
    if validation_report.invalid_count > 0:
        status = "partial_success" if inserted_count > 0 else "failed"

    msg = (
        f"Pipeline {status}: Extracted {extracted_count}, Valid {validation_report.valid_count}, "
        f"Invalid {validation_report.invalid_count}, Inserted {inserted_count}, "
        f"Skipped Duplicates {skipped_duplicates}."
    )

    return PipelineResult(
        status=status,
        extracted_count=extracted_count,
        valid_count=validation_report.valid_count,
        invalid_count=validation_report.invalid_count,
        inserted_count=inserted_count,
        skipped_duplicates=skipped_duplicates,
        replaced_dataset=replace,
        duration_seconds=duration,
        seed=seed if custom_records is None else None,
        days=days if custom_records is None else None,
        validation_report=validation_report,
        message=msg,
    )


def get_dataset_metadata(db: Session) -> Dict[str, Any]:
    """Retrieve metadata about the currently stored energy readings in SQLite."""
    count = db.query(func.count(EnergyReading.id)).scalar() or 0
    if count == 0:
        return {
            "total_readings": 0,
            "machine_count": 0,
            "machines": [],
            "first_timestamp": None,
            "last_timestamp": None,
            "span_days": 0.0,
            "recommendation_count": db.query(func.count(Recommendation.id)).scalar() or 0,
            "simulation_count": db.query(func.count(SimulationResult.id)).scalar() or 0,
        }

    min_ts, max_ts = db.query(
        func.min(EnergyReading.timestamp), func.max(EnergyReading.timestamp)
    ).first()

    machines = [
        row[0]
        for row in db.query(EnergyReading.machine)
        .distinct()
        .order_by(EnergyReading.machine)
        .all()
    ]

    span_days = round((max_ts - min_ts).total_seconds() / 86400, 2) if min_ts and max_ts else 0.0

    return {
        "total_readings": count,
        "machine_count": len(machines),
        "machines": machines,
        "first_timestamp": min_ts.isoformat() if min_ts else None,
        "last_timestamp": max_ts.isoformat() if max_ts else None,
        "span_days": span_days,
        "recommendation_count": db.query(func.count(Recommendation.id)).scalar() or 0,
        "simulation_count": db.query(func.count(SimulationResult.id)).scalar() or 0,
    }
