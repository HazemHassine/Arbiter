from fastapi.testclient import TestClient

from arbiter.api.app import create_app
from arbiter.models import ContainerInfo


def test_api_approvals_and_action_history(service_factory):
    cnt = ContainerInfo(id="c-safety", name="db", image="postgres:16", state="running")
    services = service_factory(containers=[cnt])
    client = TestClient(create_app(services=services))

    # Propose container stop
    action_res = client.post("/api/v1/containers/c-safety/stop").json()
    assert action_res["status"] == "approval_required"
    approval_id = action_res["approval"]["id"]

    # List approvals
    list_res = client.get("/api/v1/approvals")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # Approve and execute
    approve_res = client.post(f"/api/v1/approvals/{approval_id}/approve")
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "completed"

    # Action history
    history_res = client.get("/api/v1/actions")
    assert history_res.status_code == 200
    assert len(history_res.json()) >= 1
    assert history_res.json()[0]["action"] == "container.stop"
