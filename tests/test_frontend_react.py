import os

import pytest
import sqlmodel
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine
from sqlmodel.pool import StaticPool


if getattr(sqlmodel, "__stub__", False):
    pytest.skip("sqlmodel is not installed; skipping DB-backed tests.", allow_module_level=True)

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import app as app_module


test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SQLModel.metadata.create_all(test_engine)
app_module.engine = test_engine

client = TestClient(app_module.app)


def test_layout_contains_react_root_and_scripts():
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert 'id="app-root"' in body
    assert 'data-page="index"' in body
    assert "react.production.min.js" in body
    assert "react-dom.production.min.js" in body
    assert "scheduler.js" in body


def test_calendar_api_basic():
    response = client.get("/api/calendar")
    assert response.status_code == 200
    data = response.json()
    assert "calendar_data" in data
    assert "year" in data
    assert "month" in data
    assert "today" in data
