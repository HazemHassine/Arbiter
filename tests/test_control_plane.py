import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arbiter.api.app import create_app
from arbiter.dockerfile.service import DockerfileService
from arbiter.events.models import SystemEvent
from arbiter.make.service import MakeService
from arbiter.models import ActionSpec, ContainerInfo, PortBinding, PortOwner, Risk


def create_workspace(path: Path) -> None:
    path.mkdir()
    (path / "compose.yaml").write_text(
        """services:
  web:
    build: .
    ports: ['3000:8000']
    depends_on: [db]
    networks: [app]
  db:
    image: postgres:16
    volumes: [db-data:/var/lib/postgresql/data]
networks:
  app: {}
volumes:
  db-data: {}
"""
    )
    (path / "Dockerfile").write_text(
        'FROM python:3.12\nWORKDIR /app\nEXPOSE 8000\nUSER app\nCMD ["python", "main.py"]\n'
    )
    (path / "Makefile").write_text(
        "## Start local development\ndev: db\n\tuvicorn app:app --port 8000\ndb:\n\tdocker compose up -d db\n"
    )
    (path / ".dockerignore").write_text(".git\n.venv\n")


def test_topology_connects_project_compose_container_ports_and_processes(service_factory, tmp_path):
    workspace = tmp_path / "graph-demo"
    create_workspace(workspace)
    container = ContainerInfo(
        id="container-web",
        name="graph-web",
        image="graph:web",
        state="running",
        compose_project="graph-demo",
        compose_service="web",
        compose_working_dir=str(workspace),
        ports=[PortBinding(host_port=3000, container_port=8000)],
        mounts=[{"Type": "volume", "Name": "graph-demo_db-data", "Destination": "/data", "RW": True}],
        networks=["graph-demo_app"],
    )
    services = service_factory([PortOwner(port=3000, pid=1234, process="uvicorn", owner_type="process")], [container])
    project = services.projects.register_project(workspace)
    services.docker.list_volumes = lambda: [  # type: ignore[method-assign]
        {
            "name": "graph-demo_db-data",
            "labels": {"com.docker.compose.project": "graph-demo", "com.docker.compose.volume": "db-data"},
            "users": [],
        }
    ]
    services.docker.list_networks = lambda: [  # type: ignore[method-assign]
        {
            "id": "network-app",
            "name": "graph-demo_app",
            "labels": {"com.docker.compose.project": "graph-demo", "com.docker.compose.network": "app"},
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
    volume = next(node for node in graph.nodes if node.resource_type.value == "volume" and node.label == "db-data")
    sources = {edge.source for edge in graph.edges if edge.target == volume.id and edge.relationship == "MOUNTS"}
    nodes_by_id = {node.id: node for node in graph.nodes}
    assert {nodes_by_id[source].resource_type.value for source in sources} == {"compose_service", "container"}
    inspection = services.topology.inspect_resource("container", "container-web")
    assert {item.resource_type.value for item in inspection.related} >= {"image", "port", "volume", "network"}
    impact = services.impact.analyze(
        ActionSpec(
            action="container.stop",
            arguments={"identifier": "container-web"},
            summary="Stop graph web",
            risk=Risk.MEDIUM_RISK,
        )
    )
    assert impact["known"] is True
    assert ":3000" in impact["ports"]


def test_topology_and_workspace_apis(service_factory, tmp_path):
    workspace = tmp_path / "api-graph"
    create_workspace(workspace)
    services = service_factory()
    project = services.projects.register_project(workspace)
    services.system.processes = lambda _ports: []  # type: ignore[method-assign]
    with TestClient(create_app(services=services)) as client:
        assert client.get("/ui/control-plane.js").status_code == 200
        graph = client.get(f"/api/v1/topology/project/{project.id}")
        assert graph.status_code == 200
        assert any(item["resource_type"] == "project" for item in graph.json()["nodes"])
        workspace_response = client.get(f"/api/v1/projects/{project.id}/workspace")
        assert workspace_response.status_code == 200
        assert workspace_response.json()["project"]["name"] == "api-graph"
        search = client.get("/api/v1/search", params={"q": "web"})
        assert search.status_code == 200
        assert search.json()


def test_safe_file_editor_preview_approval_backup_undo_and_rollback(service_factory, tmp_path, monkeypatch):
    workspace = tmp_path / "editor-demo"
    create_workspace(workspace)
    services = service_factory()
    project = services.projects.register_project(workspace)
    original = services.files.read(project.id, ".dockerignore")
    preview = services.files.preview(project.id, ".dockerignore", ".git\n.venv\nnode_modules\n", original.sha256)
    assert "node_modules" in preview.diff
    with TestClient(create_app(services=services)) as client:
        response = client.post(
            f"/api/v1/projects/{project.id}/files/save",
            json={
                "path": ".dockerignore",
                "content": ".git\n.venv\nnode_modules\n",
                "expected_sha256": original.sha256,
            },
        )
        assert response.status_code == 200
        proposed = response.json()
        assert proposed["status"] == "approval_required"
        executed = client.post(f"/api/v1/approvals/{proposed['approval']['id']}/approve")
        assert executed.json()["status"] == "completed"
    assert "node_modules" in (workspace / ".dockerignore").read_text()
    undone = services.files.undo_latest(project.id, ".dockerignore")
    assert undone["verified"] is True
    assert (workspace / ".dockerignore").read_text() == ".git\n.venv\n"
    with pytest.raises(ValueError, match="relative path"):
        services.files.read(project.id, "../outside.env")

    before_failure = services.files.read(project.id, ".dockerignore")
    monkeypatch.setattr(
        services.files, "_validate_written", lambda _path: (_ for _ in ()).throw(RuntimeError("invalid"))
    )
    with pytest.raises(RuntimeError, match="invalid"):
        services.files.apply_update(project.id, ".dockerignore", ".git\n", before_failure.sha256)
    assert services.files.read(project.id, ".dockerignore").content == before_failure.content


def test_dockerfile_make_and_event_observation(service_factory, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:latest AS build\nRUN pip install -r requirements.txt\n")
    info = DockerfileService().inspect(dockerfile)
    assert info.stages[0].name == "build"
    assert any(item["severity"] == "possible_issue" for item in info.warnings)

    makefile = tmp_path / "Makefile"
    makefile.write_text("## Start\ndev: db\n\tuvicorn app:app --port 8000\ndb:\n\tdocker compose up -d db\n")
    details = MakeService().parse_details(makefile)
    assert details["dev"].dependencies == ["db"]
    assert details["dev"].starts_long_running_process
    assert details["dev"].ports == [8000]

    container = ContainerInfo(id="event-1", name="event-web", image="web", state="running")
    services = service_factory(containers=[container])
    services.system.processes = lambda _ports: []  # type: ignore[method-assign]
    asyncio.run(services.observer.poll_once())
    container.state = "exited"
    asyncio.run(services.observer.poll_once())
    assert any(item.type == "container.stopped" for item in services.events.recent())
    services.events.history.clear()

    async def stream_one() -> str:
        services.events.publish(
            SystemEvent(
                type="port.listening",
                resource_type="port",
                resource_id="tcp:9000",
                action="listening",
                message="Port 9000 is now listening",
            )
        )
        stream = services.events.stream()
        try:
            return await anext(stream)
        finally:
            await stream.aclose()

    assert "port.listening" in asyncio.run(stream_one())
    capabilities = services.runtimes.list_capabilities()
    assert [item.name for item in capabilities] == ["Docker", "Podman", "nerdctl / containerd"]
