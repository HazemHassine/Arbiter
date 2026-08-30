from fastapi.testclient import TestClient

from arbiter.api.app import create_app


def test_api_stacks_crud_and_lifecycle(service_factory):
    client = TestClient(create_app(services=service_factory()))

    # Create stack preset
    res = client.post(
        "/api/v1/stacks",
        json={
            "name": "Billing Microservices",
            "description": "Billing services and ledger",
            "projects": [
                {
                    "project_id": "p1",
                    "project_name": "billing-api",
                    "boot_stage": 0,
                    "readiness_gates": [
                        {"probe_type": "tcp_port", "host": "127.0.0.1", "port": 8001, "service": "billing-api"}
                    ],
                }
            ],
            "tags": ["billing", "finance"],
        },
    )
    assert res.status_code == 201
    stack_id = res.json()["id"]
    assert res.json()["name"] == "Billing Microservices"

    # List stacks
    list_res = client.get("/api/v1/stacks")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # Get single stack
    get_res = client.get(f"/api/v1/stacks/{stack_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Billing Microservices"

    # Update stack
    update_res = client.put(f"/api/v1/stacks/{stack_id}", json={"description": "Updated billing description"})
    assert update_res.status_code == 200
    assert update_res.json()["description"] == "Updated billing description"

    # Boot order endpoint
    boot_res = client.get(f"/api/v1/stacks/{stack_id}/boot-order")
    assert boot_res.status_code == 200
    assert boot_res.json()["total_stages"] >= 1

    # Readiness endpoint
    readiness_res = client.get(f"/api/v1/stacks/{stack_id}/readiness")
    assert readiness_res.status_code == 200
    assert isinstance(readiness_res.json(), list)

    # 1-Click switch endpoint
    switch_res = client.post(
        f"/api/v1/stacks/{stack_id}/switch",
        json={"hibernate_current": True, "wait_for_readiness": False},
    )
    assert switch_res.status_code == 200

    # Stop endpoint
    stop_res = client.post(f"/api/v1/stacks/{stack_id}/stop", json={"hibernate": True})
    assert stop_res.status_code == 200

    # Delete stack
    del_res = client.delete(f"/api/v1/stacks/{stack_id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True


def test_api_seed_defaults(service_factory):
    client = TestClient(create_app(services=service_factory()))

    res = client.post("/api/v1/stacks/seed-defaults")
    assert res.status_code == 200
    seeded = res.json()
    assert len(seeded) >= 3
