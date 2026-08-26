from fastapi.testclient import TestClient

from arbiter.agent.service import AgentService
from arbiter.api.app import create_app
from arbiter.models import PortOwner


def _compose_project(path, ports: list[str]) -> None:
    path.mkdir()
    rendered = "\n".join(f"      - '{port}'" for port in ports)
    (path / "compose.yaml").write_text(f"services:\n  api:\n    ports:\n{rendered}\n")


def test_reconciliation_reserves_runtime_and_all_registered_claims(service_factory, tmp_path):
    first = tmp_path / "first"
    target = tmp_path / "target"
    reserved = tmp_path / "reserved"
    _compose_project(first, ["8000:80"])
    _compose_project(target, ["8000:80"])
    _compose_project(reserved, ["8002:80"])
    services = service_factory([PortOwner(port=8001, process="uvicorn", owner_type="process")])
    services.projects.register_project(first)
    project = services.projects.register_project(target)
    services.projects.register_project(reserved)

    plan = services.ports.plan_port_reconciliation(project)

    assert plan.status == "changes_required"
    assert len(plan.changes) == 1
    change = plan.changes[0]
    assert change.suggested_port == 8003
    assert change.reasons == ["declared_by_another_project"]
    assert change.conflicting_claims[0].project == "first"
    assert change.source == str(target / "compose.yaml")


def test_reconciliation_classifies_runtime_and_in_project_duplicates(service_factory, tmp_path):
    target = tmp_path / "duplicate"
    _compose_project(target, ["9000:80", "9000:81"])
    services = service_factory([PortOwner(port=9000, process="other", owner_type="process")])
    project = services.projects.register_project(target)

    plan = services.ports.plan_port_reconciliation(project)

    assert [change.suggested_port for change in plan.changes] == [9001, 9002]
    assert all("occupied_at_runtime" in change.reasons for change in plan.changes)
    assert "duplicate_in_project" in plan.changes[1].reasons


def test_reconciliation_api_and_prepare_cover_declared_only_collision(service_factory, tmp_path):
    first = tmp_path / "api-first"
    target = tmp_path / "api-target"
    _compose_project(first, ["7000:80"])
    _compose_project(target, ["7000:80"])
    services = service_factory()
    services.projects.register_project(first)
    project = services.projects.register_project(target)

    with TestClient(create_app(services=services)) as client:
        response = client.get(f"/api/v1/projects/{project.id}/reconciliation-plan")

    assert response.status_code == 200
    assert response.json()["changes"][0]["suggested_port"] == 7001
    diagnosis = AgentService(services).diagnose_project(project.id)
    assert diagnosis["issues"][0]["reasons"] == ["declared_by_another_project"]
    prepared = AgentService(services).prepare_project(identifier=project.id)
    assert prepared["status"] == "approval_required"
    assert prepared["approval"]["arguments"]["changes"][0]["new_port"] == 7001
