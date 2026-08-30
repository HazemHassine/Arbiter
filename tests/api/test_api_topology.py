from fastapi.testclient import TestClient

from arbiter.api.app import create_app
from arbiter.models import PortOwner
from tests.fixtures.workspaces import create_sample_workspace


def test_api_topology_endpoints(service_factory, tmp_path):
    workspace = tmp_path / "topo-proj"
    create_sample_workspace(workspace)
    services = service_factory([PortOwner(port=3000, process="uvicorn")])
    project = services.projects.register_project(workspace)
    client = TestClient(create_app(services=services))

    # Global topology
    res = client.get("/api/v1/topology")
    assert res.status_code == 200
    graph = res.json()
    assert "nodes" in graph
    assert "edges" in graph

    # Project-scoped topology
    proj_res = client.get(f"/api/v1/topology/project/{project.id}")
    assert proj_res.status_code == 200
    assert len(proj_res.json()["nodes"]) >= 1

    # Search
    search_res = client.get("/api/v1/search?q=topo")
    assert search_res.status_code == 200
