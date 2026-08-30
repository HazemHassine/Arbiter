import json

from typer.testing import CliRunner

import arbiter.cli.app as cli_module
from arbiter.cli.app import app
from arbiter.models import ActionSpec, Risk


def test_cli_approvals_topology_and_processes(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)

    # Propose an action to create an approval
    spec = ActionSpec(
        action="container.start",
        arguments={"identifier": "test-box"},
        summary="Start test-box",
        risk=Risk.LOW_RISK,
    )
    proposal = services.actions.propose(spec)
    approval_id = proposal["approval"]["id"]

    # Approve action via CLI
    approve_res = cli_runner.invoke(app, ["approve", approval_id])
    assert approve_res.exit_code == 0
    approve_data = json.loads(approve_res.stdout)
    assert approve_data["status"] == "completed"

    # Topology CLI
    topo_res = cli_runner.invoke(app, ["topology"])
    assert topo_res.exit_code == 0
    topo_data = json.loads(topo_res.stdout)
    assert "nodes" in topo_data

    # Processes CLI
    proc_res = cli_runner.invoke(app, ["processes"])
    assert proc_res.exit_code == 0


def test_cli_ask_agent(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)

    ask_res = cli_runner.invoke(app, ["ask", "Which projects have port conflicts?"])
    assert ask_res.exit_code == 0
    ask_data = json.loads(ask_res.stdout)
    assert ask_data["approval_required"] is False
