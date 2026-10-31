"""AETHER — Reproducible Industrial Energy Data Pipeline CLI Runner.

Usage (Windows PowerShell):
    .venv\\Scripts\\python scripts\\run_pipeline.py
    .venv\\Scripts\\python scripts\\run_pipeline.py --days 30 --seed 42
    .venv\\Scripts\\python scripts\\run_pipeline.py --replace --days 30 --seed 42
    .venv\\Scripts\\python scripts\\run_pipeline.py --dry-run
    .venv\\Scripts\\python scripts\\run_pipeline.py --analytics

This script runs the modular Extract -> Validate -> Transform -> Load (ETL) pipeline
using the existing SQLite database and prints an industrial execution summary.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.analytics import (
    get_machine_cost_summary,
    get_machine_energy_summary,
    get_peak_demand_periods,
    get_production_efficiency,
)
from app.database import SessionLocal, init_db
from app.pipeline import (
    extract_energy_data,
    get_dataset_metadata,
    load_energy_data,
    run_pipeline,
    transform_records,
    validate_records,
)


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format tabular data cleanly for the command line."""
    if not rows:
        return "  (No data)"
    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(str(val)))

    header_str = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    data_lines = [
        " | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(row))
        for row in rows
    ]
    return f"{header_str}\n{separator}\n" + "\n".join(data_lines)


def print_banner():
    print("=" * 72)
    print("  AETHER - Reproducible Industrial Energy Data Pipeline")
    print("  Simulated Industrial Energy Telemetry & SQL Analytics Engine")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="Run AETHER reproducible energy ETL pipeline and analytics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days of hourly telemetry to generate (default: 30).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible data generation (default: 42).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Explicitly replace the existing energy dataset. Safeguards recommendations.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract, validate, and transform without persisting to the database.",
    )
    parser.add_argument(
        "--analytics",
        action="store_true",
        default=True,
        help="Compute and print SQL analytics report after ingestion (default: True).",
    )
    parser.add_argument(
        "--no-analytics",
        dest="analytics",
        action="store_false",
        help="Skip computing SQL analytics report.",
    )

    args = parser.parse_args()
    print_banner()

    print(f"\n[*] Pipeline Configuration:")
    print(f"    - Simulation Duration: {args.days} days ({args.days * 24} hours)")
    print(f"    - Reproducibility Seed: {args.seed}")
    print(f"    - Dataset Replacement: {'ENABLED (explicit flag provided)' if args.replace else 'DISABLED (incremental / duplicate prevention)'}")
    print(f"    - Execution Mode:      {'DRY RUN (no database write)' if args.dry_run else 'STANDARD (write to SQLite)'}")

    # Ensure database schema is initialized
    init_db()

    start_time = time.perf_counter()

    if args.dry_run:
        print("\n[1/3] Extracting energy telemetry...")
        raw_data = extract_energy_data(days=args.days, seed=args.seed)
        print(f"      Extracted {len(raw_data)} records.")

        print("\n[2/3] Validating schema and numeric bounds...")
        valid_records, val_report = validate_records(raw_data)
        print(f"      Valid records:   {val_report.valid_count}")
        print(f"      Invalid records: {val_report.invalid_count}")

        print("\n[3/3] Transforming & calculating analytical fields...")
        transformed = transform_records(valid_records)
        print(f"      Transformed {len(transformed)} records.")
        print(f"\n[+] Dry run completed in {time.perf_counter() - start_time:.3f}s. No records were written to SQLite.")
        return 0

    with SessionLocal() as db:
        metadata_before = get_dataset_metadata(db)
        print(f"\n[*] Current Database State: {metadata_before['total_readings']} readings across {metadata_before['machine_count']} machines.")

        print("\n[*] Executing ETL Pipeline (Extract -> Validate -> Transform -> Load)...")
        result = run_pipeline(
            db=db,
            days=args.days,
            seed=args.seed,
            replace=args.replace,
        )

        print("\n" + "-" * 72)
        print("  ETL PIPELINE EXECUTION SUMMARY")
        print("-" * 72)
        print(f"  Status:               {result.status.upper()}")
        print(f"  Extracted Records:    {result.extracted_count}")
        print(f"  Valid Records:        {result.valid_count}")
        print(f"  Invalid Records:      {result.invalid_count}")
        print(f"  Inserted to SQLite:   {result.inserted_count}")
        print(f"  Duplicates Skipped:   {result.skipped_duplicates}")
        print(f"  Dataset Replaced:     {result.replaced_dataset}")
        print(f"  Execution Time:       {result.duration_seconds:.3f} seconds")

        if result.validation_report and result.validation_report.errors:
            print("\n[!] Validation Errors Sample (first 5):")
            for err in result.validation_report.errors[:5]:
                print(f"    - Row {err.index} [{err.field}]: {err.reason} (value: {err.value})")

        metadata_after = get_dataset_metadata(db)
        print("\n[*] Updated Database State:")
        print(f"    - Total Energy Readings: {metadata_after['total_readings']}")
        print(f"    - Machine Count:         {metadata_after['machine_count']}")
        print(f"    - Date Range:            {metadata_after['first_timestamp']} to {metadata_after['last_timestamp']}")
        print(f"    - Span:                  {metadata_after['span_days']} days")
        print(f"    - Existing Audit Recs:   {metadata_after['recommendation_count']} recommendations, {metadata_after['simulation_count']} simulations")

        if args.analytics and metadata_after["total_readings"] > 0:
            print("\n" + "=" * 72)
            print("  SQL-BASED INDUSTRIAL ENERGY ANALYTICS REPORT")
            print("=" * 72)

            # 1. Machine Energy & Cost Summary
            energy_summary = get_machine_energy_summary(db)
            cost_summary = get_machine_cost_summary(db)

            cost_by_machine = {m["machine"]: m for m in cost_summary["machines"]}

            rows = []
            for m in energy_summary["machines"]:
                c = cost_by_machine.get(m["machine"], {})
                rows.append([
                    m["machine"],
                    f"{m['total_energy_kwh']:,.1f}",
                    f"{m['percentage_of_total']:.1f}%",
                    f"{m['avg_hourly_kwh']:,.1f}",
                    f"{c.get('total_cost', 0):,.1f}",
                    f"{c.get('effective_tariff', 0):.2f}",
                ])

            print("\n[1] Machine-Wise Energy & Cost Distribution:")
            print(format_table(
                ["Machine", "Energy (kWh)", "Share %", "Avg kW", "Total Cost", "Eff. Tariff"],
                rows
            ))
            print(f"    Plant Total Energy: {energy_summary['total_plant_energy_kwh']:,.1f} kWh | Plant Total Cost: {cost_summary['total_plant_cost']:,.1f} cost units")

            # 2. Specific Energy Consumption (SEC) / Production Efficiency
            eff = get_production_efficiency(db)
            eff_rows = [
                [
                    m["machine"],
                    f"{m['total_energy_kwh']:,.1f}",
                    f"{m['total_production_units']:,.1f}",
                    f"{m['sec_kwh_per_unit']:.4f}",
                    f"{m['variance_from_overall_pct']:+.1f}%",
                ]
                for m in eff["machines"]
            ]
            print("\n[2] Industrial Production Efficiency (SEC = kWh / Unit):")
            print(format_table(
                ["Machine", "Total kWh", "Total Units", "SEC (kWh/unit)", "Variance vs Plant"],
                eff_rows
            ))
            print(f"    Overall Facility Benchmark SEC: {eff['overall_sec_kwh_per_unit']:.4f} kWh/unit")

            # 3. Peak Demand Periods
            peaks = get_peak_demand_periods(db, limit=5)
            peak_rows = [
                [
                    str(p["rank"]),
                    p["timestamp"],
                    f"{p['demand_kw']:,.2f}",
                    f"{p['hour_of_day']:02d}:00",
                    "YES (Peak)" if p["is_peak_tariff_window"] else "Standard",
                ]
                for p in peaks
            ]
            print("\n[3] Top 5 Plant Peak-Demand Events:")
            print(format_table(
                ["Rank", "Timestamp", "Peak Demand (kW)", "Hour", "Tariff Window"],
                peak_rows
            ))

    print("\n" + "=" * 72)
    print("  Pipeline execution complete. Data is ready for forecasting & AI models.")
    print("=" * 72 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
