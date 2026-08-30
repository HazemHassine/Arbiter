from arbiter.models import ContainerInfo, PortBinding, PortOwner
from tests.fixtures.workspaces import create_sample_workspace


def test_topology_connects_resources(service_factory, tmp_path):
    workspace = tmp_path / "topo-unit"
    create_sample_workspace(workspace)
    container = ContainerInfo(
        id="cnt-topo",
        name="topo-web",
        image="graph:web",
        state="running",
        compose_project="topo-unit",
        compose_service="web",
        compose_working_dir=str(workspace),
        ports=[PortBinding(host_port=3000, container_port=8000)],
        mounts=[{"Type": "volume", "Name": "topo-unit_db-data", "Destination": "/data", "RW": True}],
        networks=["topo-unit_app"],
    )
    services = service_factory(
        [PortOwner(port=3000, pid=1234, process="uvicorn", owner_type="process")],
        [container],
    )
    project = services.projects.register_project(workspace)
    services.docker.list_volumes = lambda: [  # type: ignore[method-assign]
        {
            "name": "topo-unit_db-data",
            "labels": {"com.docker.compose.project": "topo-unit", "com.docker.compose.volume": "db-data"},
            "users": [],
        }
    ]
    services.docker.list_networks = lambda: [  # type: ignore[method-assign]
        {
            "id": "network-app",
            "name": "topo-unit_app",
            "labels": {"com.docker.compose.project": "topo-unit", "com.docker.compose.network": "app"},
            "members": [],
        }
    ]
    services.system.processes = lambda _ports: [  # type: ignore[method-assign]
        {
            "pid": 1234,
            "ppid": 1,
            "process": "uvicorn",
            "command": "uvicorn app:app --port 3000",
            "cwd": str(workspace),
            "ports": [3000],
            "kind": "development_server",
            "confidence": 0.93,
            "evidence": [f"cwd={workspace}", "listens_on=3000"],
        }
    ]

    graph = services.topology.project_graph(project.id)
    types = {node.resource_type.value for node in graph.nodes}
    assert {"project", "compose_service", "container", "port", "process", "dockerfile", "make_target"} <= types
    assert any(edge.relationship == "FORWARDS_TO" for edge in graph.edges)
    assert any(edge.relationship == "LISTENS_ON" for edge in graph.edges)
    assert any(edge.relationship == "DEPENDS_ON" for edge in graph.edges)

    inspection = services.topology.inspect_resource("container", "cnt-topo")
    assert {item.resource_type.value for item in inspection.related} >= {"image", "port", "volume", "network"}
