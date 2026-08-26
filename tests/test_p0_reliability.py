import shutil
from concurrent.futures import ThreadPoolExecutor
from subprocess import CompletedProcess
from threading import Barrier

from sqlalchemy import select

from arbiter.agent.service import AgentService
from arbiter.models import ActionSpec, Risk
from arbiter.persistence.tables import PortReservationRow


def _workspace(path, *, environment_driven: bool = False):
    path.mkdir()
    port = "${API_PORT}:80" if environment_driven else "8000:80"
    (path / "compose.yaml").write_text(f"services:\n  api:\n    image: alpine:3.20\n    ports: ['{port}']\n")
    if environment_driven:
        (path / ".env").write_text("API_PORT=8000\n")


def _resolve_spec(project, compose_file):
    return ActionSpec(
        action="project.resolve_ports",
        project_id=project.id,
        summary="Resolve test conflict",
        risk=Risk.MEDIUM_RISK,
        arguments={
            "project_id": project.id,
            "changes": [
                {
                    "service": "api",
                    "old_port": 8000,
                    "new_port": 8001,
                    "protocol": "tcp",
                    "compose_file": str(compose_file),
                    "env_variable": None,
                }
            ],
        },
    )


def test_compose_edit_rolls_back_when_recreation_fails(service_factory, tmp_path, monkeypatch):
    workspace = tmp_path / "compose-rollback"
    _workspace(workspace)
    compose_file = workspace / "compose.yaml"
    original = compose_file.read_text()
    services = service_factory()
    project = services.projects.register_project(workspace)

    def edit(*_args, **_kwargs):
        backup = compose_file.with_suffix(".backup")
        shutil.copy2(compose_file, backup)
        compose_file.write_text("services: {changed: {}}\n")
        return {"file": str(compose_file), "backup": str(backup)}

    attempts = []

    def recreate(_file, service):
        attempts.append(service)
        if len(attempts) == 1:
            raise RuntimeError("forced recreation failure")
        return {"recreated": service}

    monkeypatch.setattr(services.actions.editor, "change_service_host_port", edit)
    monkeypatch.setattr(services.actions.compose, "recreate_service", recreate)

    result = services.actions.execute(_resolve_spec(project, compose_file))

    assert result.status == "failed"
    assert "restored configuration" in result.error
    assert compose_file.read_text() == original
    assert attempts == ["api", "api"]


def test_env_edit_rolls_back_when_recreation_fails(service_factory, tmp_path, monkeypatch):
    workspace = tmp_path / "env-rollback"
    _workspace(workspace, environment_driven=True)
    compose_file = workspace / "compose.yaml"
    env_file = workspace / ".env"
    original = env_file.read_text()
    services = service_factory()
    project = services.projects.register_project(workspace)
    spec = _resolve_spec(project, compose_file)
    spec.arguments["changes"][0]["env_variable"] = "API_PORT"
    monkeypatch.setattr(services.actions.compose, "validate", lambda _file: {"valid": True})
    attempts = []

    def recreate(_file, service):
        attempts.append(service)
        if len(attempts) == 1:
            raise RuntimeError("forced recreation failure")
        return {"recreated": service}

    monkeypatch.setattr(services.actions.compose, "recreate_service", recreate)

    result = services.actions.execute(spec)

    assert result.status == "failed"
    assert env_file.read_text() == original
    assert attempts == ["api", "api"]


def test_compose_edit_rolls_back_when_validation_fails(service_factory, tmp_path, monkeypatch):
    workspace = tmp_path / "compose-validation-rollback"
    _workspace(workspace)
    compose_file = workspace / "compose.yaml"
    original = compose_file.read_text()
    services = service_factory()
    project = services.projects.register_project(workspace)
    monkeypatch.setattr(
        "arbiter.compose.editor.run",
        lambda *_args, **_kwargs: CompletedProcess([], returncode=1, stdout="", stderr="forced invalid compose"),
    )

    result = services.actions.execute(_resolve_spec(project, compose_file))

    assert result.status == "failed"
    assert compose_file.read_text() == original


def test_env_edit_rolls_back_when_validation_fails(service_factory, tmp_path, monkeypatch):
    workspace = tmp_path / "env-validation-rollback"
    _workspace(workspace, environment_driven=True)
    compose_file = workspace / "compose.yaml"
    env_file = workspace / ".env"
    original = env_file.read_text()
    services = service_factory()
    project = services.projects.register_project(workspace)
    spec = _resolve_spec(project, compose_file)
    spec.arguments["changes"][0]["env_variable"] = "API_PORT"
    monkeypatch.setattr(
        services.actions.compose,
        "validate",
        lambda _file: {"valid": False, "error": "forced invalid environment"},
    )

    result = services.actions.execute(spec)

    assert result.status == "failed"
    assert env_file.read_text() == original


def test_concurrent_approvals_cannot_reserve_the_same_replacement_port(service_factory):
    services = service_factory()
    barrier = Barrier(2)

    def propose(project_id):
        spec = ActionSpec(
            action="project.resolve_ports",
            project_id=project_id,
            summary=f"Reserve for {project_id}",
            risk=Risk.MEDIUM_RISK,
            arguments={
                "project_id": project_id,
                "changes": [{"service": "api", "new_port": 8123, "protocol": "tcp"}],
            },
        )
        barrier.wait()
        try:
            return services.actions.propose(spec)
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(propose, ["project-one", "project-two"]))

    proposals = [item for item in outcomes if isinstance(item, dict)]
    conflicts = [item for item in outcomes if isinstance(item, ValueError)]
    assert len(proposals) == 1
    assert len(conflicts) == 1
    assert "already reserved" in str(conflicts[0])
    with services.database.sessions() as session:
        reservations = session.scalars(select(PortReservationRow)).all()
    assert [(item.port, item.protocol) for item in reservations] == [(8123, "tcp")]

    services.actions.approvals.decide(proposals[0]["approval"]["id"], False)
    replacement = services.actions.propose(
        ActionSpec(
            action="project.resolve_ports",
            project_id="project-three",
            summary="Reserve after release",
            risk=Risk.MEDIUM_RISK,
            arguments={
                "project_id": "project-three",
                "changes": [{"service": "api", "new_port": 8123, "protocol": "tcp"}],
            },
        )
    )
    assert replacement["status"] == "approval_required"
    udp = services.actions.propose(
        ActionSpec(
            action="project.resolve_ports",
            project_id="udp-project",
            summary="Reserve the UDP namespace independently",
            risk=Risk.MEDIUM_RISK,
            arguments={
                "project_id": "udp-project",
                "changes": [{"service": "api", "new_port": 8123, "protocol": "udp"}],
            },
        )
    )
    assert udp["status"] == "approval_required"


def test_concurrent_prepare_requests_cannot_propose_the_same_replacement(service_factory, tmp_path, monkeypatch):
    first_workspace = tmp_path / "concurrent-first"
    second_workspace = tmp_path / "concurrent-second"
    _workspace(first_workspace)
    _workspace(second_workspace)
    services = service_factory()
    first = services.projects.register_project(first_workspace)
    second = services.projects.register_project(second_workspace)
    barrier = Barrier(2)
    original_propose = services.actions.propose

    def synchronized_propose(spec):
        barrier.wait()
        return original_propose(spec)

    monkeypatch.setattr(services.actions, "propose", synchronized_propose)

    def prepare(project_id):
        try:
            return AgentService(services).prepare_project(identifier=project_id)
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(prepare, [first.id, second.id]))

    proposals = [item for item in outcomes if isinstance(item, dict)]
    conflicts = [item for item in outcomes if isinstance(item, ValueError)]
    assert len(proposals) == 1
    assert proposals[0]["approval"]["arguments"]["changes"][0]["new_port"] == 8001
    assert len(conflicts) == 1
    assert "already reserved" in str(conflicts[0])


def test_replacement_reservation_is_released_after_execution_failure(service_factory):
    services = service_factory()
    spec = ActionSpec(
        action="project.resolve_ports",
        project_id="missing-project",
        summary="Fail after approval",
        risk=Risk.MEDIUM_RISK,
        arguments={
            "project_id": "missing-project",
            "changes": [{"service": "api", "new_port": 8456, "protocol": "tcp"}],
        },
    )
    proposal = services.actions.propose(spec)

    result = services.actions.approve_and_execute(proposal["approval"]["id"])
    replacement = services.actions.propose(spec.model_copy(update={"request_id": "replacement-request"}))

    assert result.status == "failed"
    assert replacement["status"] == "approval_required"
