import json
from pathlib import Path

from typer.testing import CliRunner

import arbiter.cli.app as cli_module
from arbiter.cli.app import app
from arbiter.cli.picker import (
    FuzzyPicker,
    PickerItem,
    fuzzy_match,
    pick_approval,
    pick_container,
    pick_port,
    pick_project,
)
from arbiter.models import (
    ActionSpec,
    ContainerInfo,
    PortBinding,
    PortOwner,
    Project,
    Risk,
)
from tests.fixtures.doubles import FakeDocker
from tests.fixtures.workspaces import create_sample_workspace


def test_fuzzy_match():
    # Empty query
    matched, score, indices = fuzzy_match("", "arbiter")
    assert matched is True
    assert score == 0
    assert indices == []

    # Exact match
    matched, score, indices = fuzzy_match("arbiter", "arbiter")
    assert matched is True
    assert score == 1000

    # Subsequence match
    matched, score, indices = fuzzy_match("arb", "arbiter-backend")
    assert matched is True
    assert score > 0
    assert indices == [0, 1, 2]

    # Non-match
    matched, score, indices = fuzzy_match("xyz", "arbiter")
    assert matched is False
    assert score == -1
    assert indices == []


def test_fuzzy_picker_filtering():
    items = [
        PickerItem(id="1", title="alpha-service", subtitle="src/alpha"),
        PickerItem(id="2", title="beta-service", subtitle="src/beta"),
        PickerItem(id="3", title="gamma-db", subtitle="src/gamma"),
    ]
    picker = FuzzyPicker(items, title="Test", placeholder="beta")
    filtered = picker.filter_items()
    assert len(filtered) == 1
    assert filtered[0][0].id == "2"


def test_pick_project_fallback():
    project = Project(
        id="proj1",
        name="web-app",
        path=Path("/tmp/web"),
        compose_files=[],
        services=[],
        ports=[PortBinding(host_port=3000, container_port=3000, protocol="tcp")],
    )
    result = pick_project([project])
    assert result is not None
    assert result.id == "proj1"


def test_pick_container_fallback():
    container = ContainerInfo(
        id="c123",
        name="redis-dev",
        image="redis:7",
        state="running",
    )
    result = pick_container([container])
    assert result is not None
    assert result.id == "c123"


def test_pick_approval_fallback(service_factory):
    services = service_factory()
    spec = ActionSpec(
        request_id="req1",
        action="container.restart",
        arguments={"identifier": "c1"},
        risk=Risk.LOW_RISK,
        summary="Restart redis",
    )
    approval = services.actions.approvals.create(spec)
    result = pick_approval([approval])
    assert result is not None
    assert result.id == approval.id


def test_pick_port_fallback():
    port = PortOwner(port=8080, protocol="tcp", process="node", pid=1234)
    result = pick_port([port])
    assert result is not None
    assert result.port == 8080


def test_cli_inspect_with_picker_fallback(cli_runner: CliRunner, service_factory, tmp_path: Path, monkeypatch):
    workspace = tmp_path / "picker-proj"
    create_sample_workspace(workspace)
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)

    # Register project
    reg_result = cli_runner.invoke(app, ["register", str(workspace)])
    assert reg_result.exit_code == 0

    # Inspect without argument (falls back to single project in non-interactive mode)
    inspect_result = cli_runner.invoke(app, ["inspect"])
    assert inspect_result.exit_code == 0
    inspect_data = json.loads(inspect_result.stdout)
    assert inspect_data["name"] == "picker-proj"


def test_cli_prepare_with_picker_fallback(cli_runner: CliRunner, service_factory, tmp_path: Path, monkeypatch):
    workspace = tmp_path / "picker-prep"
    create_sample_workspace(workspace)
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)

    # Register
    cli_runner.invoke(app, ["register", str(workspace)])

    # Prepare without argument
    prep_result = cli_runner.invoke(app, ["prepare"])
    assert prep_result.exit_code == 0
    prep_data = json.loads(prep_result.stdout)
    assert "status" in prep_data


def test_cli_logs_with_picker_fallback(cli_runner: CliRunner, service_factory, monkeypatch):
    container = ContainerInfo(
        id="cnt1",
        name="web-server",
        image="nginx:alpine",
        state="running",
    )
    fake_docker = FakeDocker([container])
    services = service_factory(docker=fake_docker)
    monkeypatch.setattr(cli_module, "services", lambda: services)

    # Logs without argument
    logs_result = cli_runner.invoke(app, ["logs"])
    assert logs_result.exit_code == 0
    assert "logs for cnt1" in logs_result.stdout


def test_cli_approve_with_picker_fallback(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory()
    spec = ActionSpec(
        request_id="r1",
        action="volume.remove",
        arguments={"identifier": "vol_test"},
        risk=Risk.HIGH_RISK,
        summary="Delete test volume",
    )
    services.actions.approvals.create(spec)
    monkeypatch.setattr(cli_module, "services", lambda: services)

    # Approve without argument
    approve_result = cli_runner.invoke(app, ["approve"])
    assert approve_result.exit_code == 0
    app_data = json.loads(approve_result.stdout)
    assert app_data["action"] == "volume.remove"
