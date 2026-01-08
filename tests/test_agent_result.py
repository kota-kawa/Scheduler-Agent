import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_agent_result_endpoint():
    response = client.get("/agent-result")
    assert response.status_code == 200
    assert "Agent Result - Calendar" in response.text
    assert "calendar-grid" in response.text
    assert "agent-result" in response.text  # Check for the self-links
