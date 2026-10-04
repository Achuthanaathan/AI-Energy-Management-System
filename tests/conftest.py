"""Shared pytest setup: use a temporary SQLite file for the tests."""
import os
import tempfile
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "ems_test_prototype.db"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["EMS_DB_PATH"] = str(TEST_DB)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """TestClient with the FastAPI lifespan -> creates tables + demo data."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def db(client):  # noqa: ARG001  (depends on client so the database is seeded)
    from app.database import SessionLocal

    session = SessionLocal()
    yield session
    session.close()
