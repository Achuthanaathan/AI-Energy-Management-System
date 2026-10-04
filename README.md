# AI-Powered Energy Management System for Industrial Cost Reduction

A small, complete, **local single-user prototype** of an AI-assisted energy
management system for an industrial plant.

It runs the full workflow:

**Simulated data → Forecast → Anomaly detection → Recommendation → Approve/Override → Simulation → Savings (Simulated M&V)**

Everything runs on **simulated data**. It is a college project prototype, not an
industrial control system:

* no real equipment is ever controlled (no PLC/SCADA/BMS/Modbus/BACnet/OPC-UA)
* the calculated savings are **simulated**, not measured industrial savings
* the anomaly model flags statistically unusual readings; it does **not** know
  the physical cause of an anomaly

## Technology stack

Python, FastAPI, SQLite, SQLAlchemy, scikit-learn, pytest, plain HTML/CSS/JavaScript.
No frontend framework, no build step, no Docker, no login, no deployment config.

## Installation

```text
python -m venv .venv
.venv\Scripts\activate          (Windows)
# source .venv/bin/activate     (Linux/macOS)
pip install -r requirements.txt
```

## Start the application

```text
python -m uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000> in a browser.

On the first start the app creates `energy.db`, generates the simulated dataset
(30 days x 24 hours x 4 machines) and creates the first recommendations, so the
dashboard is never empty. Interactive API docs: <http://127.0.0.1:8000/docs>.

## Run the tests

```text
python -m pytest -v
```

Five focused tests: forecast output, injected-anomaly detection, high peak demand
produces a recommendation, savings calculation, and approve/override → simulation.

## How the prototype works

| Step | Module | What happens |
| --- | --- | --- |
| Simulated data | `app/data_generator.py` | Hourly readings for 4 machines with a time-of-use tariff, a plant peak-demand event on the last days and a few injected abnormal readings |
| Forecast | `app/forecasting.py` | Linear Regression on `hour`, `day_of_week`, `is_weekend`, `lag_24h`, `avg_prev_24h` → next 24 hours |
| Anomaly detection | `app/anomaly.py` | Isolation Forest over energy, production, hour of day and peak-tariff flag |
| Recommendation | `app/recommendations.py` | Rule 1: predicted peak above 180 kW and a flexible load in the peak window → shift it to the cheapest hour. Rule 2: detected anomaly → ask an operator to investigate |
| Human approval | `app/main.py` | `pending → approved` or `pending → overridden`; every recommendation keeps reason, action, estimated energy/cost impact, production impact and risk |
| Simulation | `app/simulation.py` | Approved/overridden recommendation moves the load to the cheaper hour; nothing is controlled |
| Savings (M&V) | `app/simulation.py` | Baseline vs simulated energy and cost, energy saved, money saved and peak-demand reduction |

## Main API endpoints

| Method | Endpoint |
| --- | --- |
| GET | `/api/energy/current`, `/api/energy/history`, `/api/energy/summary` |
| GET | `/api/forecast`, `/api/anomalies` |
| GET | `/api/recommendations`, POST `/api/recommendations/generate` |
| POST | `/api/recommendations/{id}/approve`, `/api/recommendations/{id}/override` |
| POST | `/api/recommendations/{id}/simulate` |
| GET | `/api/simulations`, `/api/dashboard` |
| POST | `/api/reset` (re-generate the simulated dataset) |

## Disclaimer

Prototype for academic use. Data is simulated, savings are simulated, and no
equipment control, grid integration or measurement hardware is included.
