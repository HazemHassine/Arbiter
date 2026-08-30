import json

from fastapi.testclient import TestClient

from arbiter.api.app import create_app


def test_api_agent_query(service_factory):
    client = TestClient(create_app(services=service_factory()))
    response = client.post("/api/v1/agent/query", json={"message": "Which projects have port conflicts?"})
    assert response.status_code == 200
    assert response.json()["approval_required"] is False


def test_api_agent_query_stream(service_factory):
    client = TestClient(create_app(services=service_factory()))
    with client.stream(
        "POST", "/api/v1/agent/query/stream", json={"message": "Which projects have port conflicts?"}
    ) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert len(events) >= 2
    assert events[0]["type"] == "step_started"
    assert events[-1]["type"] == "final"
