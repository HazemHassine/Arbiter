from fastapi.testclient import TestClient

from arbiter.api.app import create_app
from arbiter.models import PortOwner


def test_api_list_ports(service_factory):
    services = service_factory(
        [
            PortOwner(port=5432, process="postgres", owner_type="process"),
            PortOwner(port=6379, process="redis", owner_type="process"),
        ]
    )
    client = TestClient(create_app(services=services))

    response = client.get("/api/v1/ports")
    assert response.status_code == 200
    ports = response.json()
    assert len(ports) == 2
    assert ports[0]["port"] == 5432
    assert ports[0]["process"] == "postgres"


def test_api_get_single_port(service_factory):
    services = service_factory([PortOwner(port=8000, process="uvicorn")])
    client = TestClient(create_app(services=services))

    response = client.get("/api/v1/ports/8000")
    assert response.status_code == 200
    assert response.json()["process"] == "uvicorn"

    free_port = client.get("/api/v1/ports/9999")
    assert free_port.status_code == 200
    assert free_port.json()["available"] is True


def test_api_find_free_ports(service_factory):
    services = service_factory([PortOwner(port=3000), PortOwner(port=3001)])
    client = TestClient(create_app(services=services))

    response = client.get("/api/v1/ports/free?start=3000&end=3005&count=3")
    assert response.status_code == 200
    free_ports = response.json()
    assert free_ports == [3002, 3003, 3004]


def test_api_detect_port_conflicts(service_factory, tmp_path):
    for name in ("p1", "p2"):
        d = tmp_path / name
        d.mkdir()
        (d / "compose.yaml").write_text("services:\n  app:\n    ports: ['9000:80']\n")
    services = service_factory()
    services.projects.register_project(tmp_path / "p1")
    services.projects.register_project(tmp_path / "p2")

    client = TestClient(create_app(services=services))
    response = client.get("/api/v1/ports/conflicts")
    assert response.status_code == 200
    conflicts = response.json()
    assert len(conflicts) >= 1
    assert conflicts[0]["port"] == 9000
