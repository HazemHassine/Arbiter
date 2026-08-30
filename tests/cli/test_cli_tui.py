from pathlib import Path

from typer.testing import CliRunner

import arbiter.cli.app as cli_module
from arbiter.cli.app import app
from arbiter.models import (
    ActionSpec,
    ContainerInfo,
    PortOwner,
    Risk,
)
from arbiter.tui.app import ArbiterTUI
from arbiter.tui.views import (
    TAB_APPROVALS,
    TAB_CONTAINERS,
    TAB_PROJECTS,
    TUIData,
    TUIState,
    format_container_row,
    format_port_row,
    get_item_details,
)
from tests.fixtures.doubles import FakeDocker
from tests.fixtures.workspaces import create_sample_workspace


def test_tui_row_formatters():
    port = PortOwner(port=5432, protocol="tcp", process="postgres", pid=999)
    p_proto, owner, pid, proj_svc, status = format_port_row(port, has_conflict=False)
    assert p_proto == "5432/tcp"
    assert owner == "postgres"
    assert pid == "999"
    assert status == "● ACTIVE"

    container = ContainerInfo(
        id="c111",
        name="web_api",
        image="python:3.12",
        state="running",
        compose_project="my-app",
        compose_service="api",
    )
    c_name, c_state, c_img, c_ps, c_ports = format_container_row(container)
    assert c_name == "web_api"
    assert "running" in c_state
    assert c_ps == "my-app/api"


def test_tui_state_and_details(service_factory, tmp_path: Path):
    workspace = tmp_path / "tui-proj"
    create_sample_workspace(workspace)
    services = service_factory()
    proj = services.projects.register_project(workspace)

    data = TUIData(projects=[proj])
    state = TUIState(active_tab=TAB_PROJECTS)

    details = get_item_details(data, state, proj)
    assert proj.id in details
    assert "tui-proj" in details


def test_arbiter_tui_load_and_filter(service_factory, tmp_path: Path):
    workspace = tmp_path / "tui-filter-proj"
    create_sample_workspace(workspace)

    container = ContainerInfo(id="c222", name="redis-cache", image="redis:7", state="running")
    fake_docker = FakeDocker([container])
    services = service_factory(docker=fake_docker)
    services.projects.register_project(workspace)

    spec = ActionSpec(
        request_id="r1",
        action="compose.restart",
        arguments={"project_id": "tui-filter-proj"},
        risk=Risk.LOW_RISK,
        summary="Restart dev container",
    )
    services.actions.approvals.create(spec)

    tui = ArbiterTUI(services)
    tui.load_data()

    assert len(tui.data.projects) == 1
    assert len(tui.data.containers) == 1
    assert len(tui.data.approvals) == 1

    # Filter containers tab
    tui.state.active_tab = TAB_CONTAINERS
    tui.state.set_current_filter_query("redis")
    filtered = tui.get_current_items()
    assert len(filtered) == 1
    assert filtered[0].name == "redis-cache"

    # Filter approvals tab
    tui.state.active_tab = TAB_APPROVALS
    tui.state.set_current_filter_query("compose")
    filtered_app = tui.get_current_items()
    assert len(filtered_app) == 1


def test_cli_tui_non_interactive(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)

    # In non-interactive test runner, arbiter tui prints status pill fallback
    res = cli_runner.invoke(app, ["tui"])
    assert res.exit_code == 0
    assert "Arbiter:" in res.stdout
