# AETHER — Pipeline Execution & Quickstart Guide

This guide provides step-by-step instructions for running the **AETHER Data Pipeline**, executing SQL analytics, and launching the application on a Windows machine using Windows PowerShell.

---

## 1. Prerequisites

- **Operating System:** Windows 10/11 (or macOS / Linux).
- **RAM:** 8–16 GB.
- **Python:** Python 3.10, 3.11, or 3.12.
- **Virtual Environment:** Configured in `.venv`.

---

## 2. Windows PowerShell Setup

Open Windows PowerShell in the project directory:
```powershell
cd "C:\Users\Achuthanaathan S\OneDrive\Documents\AI-Energy-Management-System"
```

Activate the virtual environment (if not already activated):
```powershell
.venv\Scripts\Activate.ps1
```

If script execution is restricted in your PowerShell session:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.venv\Scripts\Activate.ps1
```

---

## 3. Running the Data Pipeline CLI

The pipeline runner is located at `scripts/run_pipeline.py`. It supports extracting, validating, transforming, loading, and analyzing energy telemetry.

### A. Dry Run (Validate without database write)
Extracts and validates records without modifying the database:
```powershell
.venv\Scripts\python scripts\run_pipeline.py --dry-run
```

### B. Standard Ingestion (With duplicate prevention)
Loads 30 days of telemetry with reproducible seed `42`. Existing records are safely skipped:
```powershell
.venv\Scripts\python scripts\run_pipeline.py
```

### C. Configurable Duration & Seed
Generate 14 days of telemetry with a custom seed:
```powershell
.venv\Scripts\python scripts\run_pipeline.py --days 14 --seed 101
```

### D. Explicit Dataset Replacement (With audit safeguards)
Replaces existing energy readings with a fresh 30-day dataset while preserving user decisions, recommendations, and simulation records:
```powershell
.venv\Scripts\python scripts\run_pipeline.py --replace --days 30 --seed 42
```

---

## 4. Running the Web Application & Interactive UI

Start the FastAPI application server:
```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open your browser to:
- **Interactive Web Dashboard:** <http://127.0.0.1:8000>
- **FastAPI Interactive Swagger Docs:** <http://127.0.0.1:8000/docs>
- **ReDoc API Documentation:** <http://127.0.0.1:8000/redoc>

---

## 5. Testing the Pipeline & Analytics API Endpoints

Once the server is running, you can test the REST API endpoints using `curl` or your browser:

### 1. Check Pipeline Status & Metadata
```powershell
curl -s http://127.0.0.1:8000/api/pipeline/status | ConvertFrom-Json
```

### 2. Trigger Ingestion via API
```powershell
curl -X POST "http://127.0.0.1:8000/api/pipeline/run?days=30&seed=42&replace=false" | ConvertFrom-Json
```

### 3. Machine Energy & Cost Analytics
```powershell
curl -s http://127.0.0.1:8000/api/analytics/machine-summary | ConvertFrom-Json
```

### 4. Daily Aggregations
```powershell
curl -s "http://127.0.0.1:8000/api/analytics/daily?days=7" | ConvertFrom-Json
```

### 5. 24-Hour Diurnal Load Profile
```powershell
curl -s "http://127.0.0.1:8000/api/analytics/hourly-profile?machine=ALL" | ConvertFrom-Json
```

### 6. Peak Demand Interval Analysis
```powershell
curl -s "http://127.0.0.1:8000/api/analytics/peak-demand?limit=5" | ConvertFrom-Json
```

### 7. Production Efficiency (SEC)
```powershell
curl -s http://127.0.0.1:8000/api/analytics/efficiency | ConvertFrom-Json
```

### 8. Highest Consumption Outliers (Operator Investigation)
```powershell
curl -s "http://127.0.0.1:8000/api/analytics/top-consumers?limit=5" | ConvertFrom-Json
```

### 9. Destructive Operations & Security Configuration

AETHER protects destructive operations (`POST /api/reset` and `POST /api/pipeline/run?replace=true`):
- **Local Development / Testing (Default):** Permitted without credentials so local development remains frictionless.
- **Admin Token Authentication:** Set `$env:AETHER_ADMIN_TOKEN="your-secret-token"`. Calls to destructive endpoints must supply the header `-H "X-Admin-Token: your-secret-token"` or query parameter `?admin_token=your-secret-token`. Unauthorized requests return `401 Unauthorized`.
- **Public Deployments without Credentials:** Set `$env:AETHER_PUBLIC_DEPLOYMENT="true"`. Destructive endpoints are disabled (`403 Forbidden`) if no administrator token is configured.
- **Lock Down Destructive Operations:** Set `$env:AETHER_ENABLE_DESTRUCTIVE_OPS="false"` to completely disable reset and replacement operations (`403 Forbidden`).

---

## 6. Running the Automated Test Suite

Run all tests (existing prototype tests + new pipeline & analytics tests):
```powershell
.venv\Scripts\python -m pytest -v
```

Run only the pipeline & SQL analytics tests:
```powershell
.venv\Scripts\python -m pytest tests\test_pipeline.py -v
```

Run tests with concise output:
```powershell
.venv\Scripts\python -m pytest -q
```
*Expected result:* 19 passed. Tests run against an isolated temporary SQLite database without touching `energy.db`.
