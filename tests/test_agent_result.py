import os
import pytest
import sqlmodel
from sqlmodel import create_engine, SQLModel
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient


if getattr(sqlmodel, "__stub__", False):
    pytest.skip("sqlmodel is not installed; skipping DB-backed tests.", allow_module_level=True)

# Set env before importing app (though we will monkeypatch anyway)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import app as app_module

# Re-create engine with StaticPool for in-memory SQLite testing
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Initialize tables
SQLModel.metadata.create_all(test_engine)

# Monkeypatch the engine in the app module
app_module.engine = test_engine

client = TestClient(app_module.app)

def test_agent_result_endpoint():
    response = client.get("/agent-result")
    assert response.status_code == 200
    body = response.text
    assert "Agent Result - Calendar" in body
    assert 'id="app-root"' in body
    assert 'data-page="agent-result"' in body

def test_agent_day_view_endpoint():
    # Use a dummy date
    response = client.get("/agent-result/day/2023-01-01")
    assert response.status_code == 200
    body = response.text
    assert "Agent Result - Day View" in body
    assert 'id="app-root"' in body
    assert 'data-page="agent-day"' in body
