import json
from pathlib import Path

from typer.testing import CliRunner

import arbiter.cli.app as cli_module
from arbiter.cli.app import app
from arbiter.cli.prompt import (
    PromptStatus,
    format_prompt_status,
    generate_shell_init,
    get_prompt_status,
)
from arbiter.models import ActionSpec, PortOwner, Risk
from tests.fixtures.workspaces import create_sample_workspace


def test_prompt_status_formatter():
    status = PromptStatus(
        pending_approvals=2,
        port_conflicts=1,
        running_containers=4,
        registered_projects=2,
        status="critical",
    )

    # Pill format with color
    pill_colored = format_prompt_status(status, output_format="pill", color=True)
    assert "⚡ Arbiter:" in pill_colored
    assert "2 pending approvals" in pill_colored
    assert "1 conflict" in pill_colored

    # Pill format without color
    pill_plain = format_prompt_status(status, output_format="pill", color=False)
    assert "⚡ Arbiter: 2 pending approvals | 1 conflict" in pill_plain

    # Plain format
    plain = format_prompt_status(status, output_format="plain")
    assert "Arbiter: 2 pending approvals | 1 conflict" in plain

    # Short format
    short = format_prompt_status(status, output_format="short", color=False)
    assert "2! 1⚡" in short

    # Starship format
    starship = format_prompt_status(status, output_format="starship")
    assert "2 pending approvals | 1 conflict" in starship

    # JSON format
    json_out = json.loads(format_prompt_status(status, output_format="json"))
    assert json_out["pending_approvals"] == 2
    assert json_out["port_conflicts"] == 1
    assert json_out["status"] == "critical"


def test_get_prompt_status_integration(service_factory, tmp_path: Path):
    workspace = tmp_path / "prompt-proj"
    create_sample_workspace(workspace)
    services = service_factory(owners=[PortOwner(port=3000, protocol="tcp", process="node")])
    services.projects.register_project(workspace)

    # Add pending approval
    spec = ActionSpec(
        request_id="r1",
        action="compose.restart",
        arguments={"project_id": "prompt-proj"},
        risk=Risk.MEDIUM_RISK,
        summary="Restart project",
    )
    services.actions.approvals.create(spec)

    status = get_prompt_status(services)
    assert status.pending_approvals == 1
    assert status.registered_projects == 1


def test_generate_shell_init():
    starship_init = generate_shell_init("starship")
    assert "[custom.arbiter]" in starship_init
    assert "arbiter prompt --format starship" in starship_init

    zsh_init = generate_shell_init("zsh")
    assert "_arbiter_prompt_precmd" in zsh_init
    assert "add-zsh-hook precmd" in zsh_init

    bash_init = generate_shell_init("bash")
    assert "PROMPT_COMMAND" in bash_init

    fish_init = generate_shell_init("fish")
    assert "fish_prompt" in fish_init


def test_cli_prompt_command(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)

    res = cli_runner.invoke(app, ["prompt", "--format", "json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert "pending_approvals" in data
    assert "port_conflicts" in data


def test_cli_prompt_init_command(cli_runner: CliRunner):
    res = cli_runner.invoke(app, ["prompt", "init", "starship"])
    assert res.exit_code == 0
    assert "[custom.arbiter]" in res.stdout
