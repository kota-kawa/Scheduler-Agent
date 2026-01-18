import importlib
import os
import sys

import pytest
import sqlmodel
from fastapi.testclient import TestClient


if getattr(sqlmodel, "__stub__", False):
    pytest.skip("sqlmodel is not installed; skipping DB-backed tests.", allow_module_level=True)


def _load_app():
    db_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("Set TEST_DATABASE_URL or DATABASE_URL to run PostgreSQL-backed tests.")
    os.environ["DATABASE_URL"] = db_url
    os.environ["SESSION_SECRET"] = "test-secret"
    if "app" in sys.modules:
        del sys.modules["app"]
    app_module = importlib.import_module("app")
    app_module._init_db()
    return app_module


@pytest.fixture()
def client():
    app_module = _load_app()
    return TestClient(app_module.app)

def test_agent_result_endpoint(client):
    response = client.get("/agent-result")
    assert response.status_code == 200
    body = response.text
    assert "Agent Result - Calendar" in body
    assert 'id="app-root"' in body
    assert 'data-page="agent-result"' in body

def test_agent_day_view_endpoint(client):
    # Use a dummy date
    response = client.get("/agent-result/day/2023-01-01")
    assert response.status_code == 200
    body = response.text
    assert "Agent Result - Day View" in body
    assert 'id="app-root"' in body
    assert 'data-page="agent-day"' in body
