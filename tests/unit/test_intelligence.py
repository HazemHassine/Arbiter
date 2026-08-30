import asyncio

from arbiter.intelligence.filtering import IntelligenceService
from arbiter.models import ContainerInfo, PortBinding, PortOwner
from tests.fixtures.workspaces import create_sample_workspace


def test_deterministic_resource_filtering(service_factory, tmp_path):
    workspace = tmp_path / "filter-workspace"
    create_sample_workspace(workspace)
    container = ContainerInfo(
        id="cnt-filter",
        name="filter-web",
        image="web:latest",
        state="running",
        compose_project="filter-workspace",
        compose_service="web",
        compose_working_dir=str(workspace),
        ports=[PortBinding(host_port=3000, container_port=8000)],
    )
    services = service_factory(
        [PortOwner(port=3000, container_id="cnt-filter", container="filter-web", owner_type="container")],
        [container],
    )
    services.projects.register_project(workspace)
    services.system.processes = lambda _ports: []  # type: ignore[method-assign]

    filter_service = IntelligenceService(services)
    result = asyncio.run(filter_service.filter("running containers on port 3000", use_ai=False))
    assert result["mode"] == "deterministic"
    assert result["matched_count"] >= 1
    assert any(node["resource_type"] == "container" for node in result["graph"]["nodes"])
