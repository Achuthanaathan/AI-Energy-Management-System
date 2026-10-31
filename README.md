# AETHER — Industrial Energy Intelligence & Data Pipeline

An AI-powered, reproducible industrial energy management prototype and SQL analytics pipeline designed for industrial plant supervisors, energy auditors, and sustainability engineers.

AETHER processes high-resolution industrial machine telemetry, runs automated validation and transformation workflows, persists clean records to SQLite, surfaces SQL-based energy analytics, and feeds downstream AI models for peak demand forecasting and anomaly detection.

> [!NOTE]
> **Academic & Hackathon Prototype Disclaimer**
> All telemetry is simulated using statistical models representing industrial equipment. Savings are computed via simulated Measurement & Verification (M&V) algorithms and do not represent measured physical cost reductions. No real equipment is controlled (no SCADA/PLC/BMS integration).

---

## 1. Problem Statement & Target Users

Industrial manufacturing facilities face surging time-of-use (ToU) electricity tariffs and steep peak-demand penalty charges. Energy managers often lack:
1. **Automated ETL pipelines** to validate noisy machine sensor streams against negative, missing, or non-finite readings.
2. **Real-time SQL visibility** into Specific Energy Consumption ($\text{SEC} = \text{kWh} / \text{unit}$) and machine-wise load distribution.
3. **Actionable peak-shifting recommendations** before costly demand thresholds are breached.

**Target Users:**
- **Plant Operations Supervisors:** Inspect live telemetry, review automated load-shift recommendations, and approve operational interventions.
- **Facility Energy Managers:** Audit historical consumption, evaluate time-of-use tariff exposure, and verify simulated M&V savings.
- **Process Engineers:** Investigate machine-level power spikes and anomalous equipment degradation.

---

## 2. Technology Stack

AETHER is built with a lightweight, reproducible, single-user stack designed to run locally on any 8–16 GB Windows computer:

- **Backend Framework:** FastAPI (Python 3.10+)
- **Database & ORM:** SQLite with SQLAlchemy (Declarative ORM)
- **Data Pipeline:** Modular Python ETL engine (Extract, Validate, Transform, Load)
- **Analytics:** Pure SQL / SQLAlchemy aggregations over stored telemetry records
- **Machine Learning:** scikit-learn (Linear Regression forecasting, Isolation Forest anomaly detection)
- **Testing:** pytest with isolated temporary test databases
- **Frontend:** Vanilla HTML5, Modern CSS (Uilora Dark zinc-950 design system), and Vanilla JavaScript (SVG area charts, no npm/node build steps required)

*Transparency Notice: This implementation uses Python, SQLite, and SQLAlchemy SQL analytics. It does not use or require Exasol, Docker, Kubernetes, or cloud database infrastructure.*

---

## 3. Data Pipeline Architecture (ETL)

AETHER implements a 4-stage modular data pipeline with audit safeguards:

```
[Raw Simulation Engine / Sensor Ingestion]
                   │
                   ▼
  1. EXTRACT    -> Configurable duration (days) & random seed (default: 42)
                   │
                   ▼
  2. VALIDATE   -> Checks schema, non-empty machines, ISO timestamps
                   Rejects negative, NaN, Inf, and non-numeric values
                   Returns structured ValidationReport with itemized errors
                   │
                   ▼
  3. TRANSFORM  -> Normalizes timestamps, tags peak-tariff windows (18:00–21:00)
                   Derives analytical metrics: energy_cost and energy_per_unit
                   │
                   ▼
  4. LOAD       -> Ingests into SQLite with duplicate detection (timestamp, machine)
                   replace=False: skips existing duplicates
                   replace=True: safely refreshes readings while preserving
                                 operator decisions, recommendations, and simulations
                   │
                   ▼
  5. SQL ENGINE -> Machine summaries, daily trends, diurnal profiles, SEC efficiency
```

### Validation Rules
- Required fields: `timestamp`, `machine`, `energy_kwh`, `production_units`, `tariff`.
- Numeric values: Must be finite (`math.isnan` and `math.isinf` rejected) and $\ge 0.0$.
- Unknown machine names: Flagged if machine is not in the facility registry.
- Timestamp: Must be valid ISO 8601 string or Python `datetime`.

### Ingestion Safeguards
- **Duplicate Prevention:** Before insertion, incoming `(timestamp, machine)` composite keys are matched against stored records in the time window. Existing records are skipped.
- **Audit Preservation:** When running with `--replace`, only the `energy_readings` table is refreshed. The `recommendations` and `simulation_results` tables are preserved to protect operator history.

---

## 4. Database Schema

The SQLite schema consists of three relational tables:

```
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│         energy_readings         │       │         recommendations         │
├─────────────────────────────────┤       ├─────────────────────────────────┤
│ id (PK, Integer)                │       │ id (PK, Integer)                │
│ timestamp (DateTime, Indexed)   │       │ code (String, Unique, Indexed)  │
│ machine (String(50), Indexed)   │       │ rule (String(40))               │
│ energy_kwh (Float)              │       │ created_at (DateTime)           │
│ production_units (Float)        │       │ machine (String(50))            │
│ tariff (Float)                  │       │ title (String(200))             │
│ peak_demand_kw (Float)          │       │ reason (Text)                   │
│ is_peak_tariff (Boolean)        │       │ action (Text)                   │
│ is_injected_anomaly (Boolean)   │       │ shift_kwh (Float)               │
└─────────────────────────────────┘       │ est_energy_impact_kwh (Float)   │
                                          │ est_cost_impact (Float)         │
                                          │ production_impact_pct (Float)   │
                                          │ risk_level (String(20))         │
                                          │ shift_from_hour (Integer)       │
                                          │ shift_to_hour (Integer)         │
                                          │ forecast_peak_kw (Float)        │
                                          │ status (String, Indexed)        │
                                          │ decision (String, Nullable)     │
                                          │ decision_note (Text, Nullable)  │
                                          │ decided_at (DateTime, Nullable) │
                                          └────────────────┬────────────────┘
                                                           │ 1
                                                           │
                                                           │ verified by
                                                           │
                                                           │ 0..*
                                          ┌────────────────┴────────────────┐
                                          │       simulation_results        │
                                          ├─────────────────────────────────┤
                                          │ id (PK, Integer)                │
                                          │ recommendation_id (FK, Integer) │
                                          │ created_at (DateTime)           │
                                          │ baseline_energy_kwh (Float)     │
                                          │ simulated_energy_kwh (Float)    │
                                          │ energy_saved_kwh (Float)        │
                                          │ baseline_cost (Float)           │
                                          │ simulated_cost (Float)          │
                                          │ cost_saved (Float)              │
                                          │ baseline_peak_kw (Float)        │
                                          │ simulated_peak_kw (Float)       │
                                          │ peak_reduction_kw (Float)       │
                                          │ note (Text)                     │
                                          └─────────────────────────────────┘
```

---

## 5. Installation & Setup (Windows PowerShell)

### Step 1: Clone and navigate to the project
```powershell
cd "C:\Users\Achuthanaathan S\OneDrive\Documents\AI-Energy-Management-System"
```

### Step 2: Set up Virtual Environment
```powershell
# Create venv if not already created
python -m venv .venv

# Activate in Windows PowerShell
.venv\Scripts\Activate.ps1
```

*If script execution is blocked on Windows:*
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.venv\Scripts\Activate.ps1
```

### Step 3: Install Dependencies
```powershell
pip install -r requirements.txt
```

---

## 6. Running the Pipeline & CLI Commands

The pipeline CLI is located at `scripts/run_pipeline.py`.

### Dry Run (Validate without writing to database)
```powershell
.venv\Scripts\python scripts\run_pipeline.py --dry-run
```

### Standard Ingestion (With duplicate prevention)
```powershell
.venv\Scripts\python scripts\run_pipeline.py
```

### Custom Duration & Seed
```powershell
.venv\Scripts\python scripts\run_pipeline.py --days 14 --seed 99
```

### Explicit Dataset Replacement (With audit safeguards)
```powershell
.venv\Scripts\python scripts\run_pipeline.py --replace --days 30 --seed 42
```

---

## 7. Starting the Web Application

Start the local server:
```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open your browser:
- **AETHER Dashboard UI:** <http://127.0.0.1:8000>
- **Interactive Swagger Documentation:** <http://127.0.0.1:8000/docs>
- **ReDoc Technical Specification:** <http://127.0.0.1:8000/redoc>

---

## 8. API Reference

### Pipeline & Data Ingestion Endpoints
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/pipeline/status` | Current dataset metadata (row count, date range, table counts) |
| `POST` | `/api/pipeline/run` | Execute ETL pipeline (`replace=true` requires admin credentials) |

> [!TIP]
> **Destructive Operations & Access Control**
> `POST /api/reset` and `POST /api/pipeline/run?replace=true` are protected against unauthorized resets:
> - **Local Development:** Enabled by default without credentials for frictionless local testing.
> - **Admin Protection:** Configure `AETHER_ADMIN_TOKEN` to require `X-Admin-Token: <token>` header or `?admin_token=<token>` query parameter (`401 Unauthorized` if invalid).
> - **Public Deployments:** Setting `AETHER_PUBLIC_DEPLOYMENT="true"` disables destructive operations if no admin token is set (`403 Forbidden`). Setting `AETHER_ENABLE_DESTRUCTIVE_OPS="false"` permanently locks down destructive actions.

### SQL Analytics Endpoints
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/analytics/machine-summary` | Machine energy totals, percentage shares, and cost distribution |
| `GET` | `/api/analytics/daily` | Daily energy, cost, peak demand, and production units |
| `GET` | `/api/analytics/hourly-profile` | 24-hour diurnal profile (hours 0–23) with peak tariff windows |
| `GET` | `/api/analytics/peak-demand` | Top peak-demand timestamps across the plant or per machine |
| `GET` | `/api/analytics/efficiency` | Specific Energy Consumption ($\text{SEC} = \text{kWh} / \text{unit}$) per machine |
| `GET` | `/api/analytics/top-consumers` | Top individual consumption spikes for operator investigation |

### Core Workflow Endpoints
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/dashboard` | Main operational dashboard KPIs, 24h trend, and status |
| `GET` | `/api/forecast` | Linear Regression 24-hour demand forecast |
| `GET` | `/api/anomalies` | Isolation Forest anomaly detection report |
| `GET` | `/api/recommendations` | List optimization recommendations (filterable by status) |
| `POST` | `/api/recommendations/generate` | Run the rule engine to generate new recommendations |
| `POST` | `/api/recommendations/{id}/approve` | Operator approval with optional audit note |
| `POST` | `/api/recommendations/{id}/override` | Operator override with audit note |
| `POST` | `/api/recommendations/{id}/simulate` | Run M&V simulation for approved/overridden recommendation |
| `GET` | `/api/simulations` | Retrieve verified M&V savings results |

---

## 9. Running Tests

The test suite includes 22 comprehensive unit and integration tests covering data generation reproducibility, validation rules, ETL stages, duplicate prevention, atomic replacement rollback on failure, access control for destructive endpoints, server error sanitization, SQL analytics, and FastAPI endpoints:

```powershell
.venv\Scripts\python -m pytest -q
```

Output:
```text
......................                                                   [100%]
22 passed, 1 warning in 4.74s
```
*Tests run against an isolated temporary SQLite database and never modify the local `energy.db`.*

---

## 10. Limitations & Future Scope

### Current Prototype Scope
- Single-node SQLite database designed for local evaluation.
- Simulated industrial dataset with mathematical load models.
- Human-in-the-loop approval workflow; no real equipment is directly controlled.

### Future Scope
- **Industrial Protocols:** Integration with OPC-UA, MQTT, and Modbus TCP telemetry streams.
- **Enterprise Warehouses:** Pluggable connector architecture for PostgreSQL, TimescaleDB, or Snowflake.
- **Automated Demand Response:** Automated OpenADR 2.0b signaling for utility grid integration.
- **Advanced Predictive Models:** Gradient boosting (LightGBM) or deep neural networks for multi-day weather-aware load forecasting.
