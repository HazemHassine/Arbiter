from fastapi.testclient import TestClient

from arbiter.api.app import create_app
from arbiter.models import ContainerInfo


def test_api_containers_and_resources(service_factory):
    cnt = ContainerInfo(id="c1", name="redis-container", image="redis:7", state="running")
    client = TestClient(create_app(services=service_factory(containers=[cnt])))

    # List containers
    res = client.get("/api/v1/containers")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["name"] == "redis-container"

    # Inspect container
    inspect_res = client.get("/api/v1/containers/c1")
    assert inspect_res.status_code == 200
    assert inspect_res.json()["name"] == "redis-container"

    # Start container (requires approval)
    action_res = client.post("/api/v1/containers/c1/start")
    assert action_res.status_code == 200
    assert action_res.json()["status"] == "approval_required"

    # Logs
    logs_res = client.get("/api/v1/containers/c1/logs")
    assert logs_res.status_code == 200
    assert "logs for c1" in logs_res.json()["logs"]

    # Docker resources
    assert client.get("/api/v1/images").status_code == 200
    assert client.get("/api/v1/volumes").status_code == 200
    assert client.get("/api/v1/networks").status_code == 200
    assert client.get("/api/v1/docker/disk-usage").status_code == 200
