import json

from typer.testing import CliRunner

import arbiter.cli.app as cli_module
from arbiter.cli.app import app
from arbiter.models import ReadinessGate, StackProjectMember


def test_cli_stack_commands(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)

    # 1. Seed defaults
    seed_result = cli_runner.invoke(app, ["stack", "list", "--seed-defaults"])
    assert seed_result.exit_code == 0
    seeded = json.loads(seed_result.stdout)
    assert len(seeded) >= 3

    # 2. Inspect a stack preset
    target_stack = seeded[0]
    inspect_result = cli_runner.invoke(app, ["stack", "inspect", target_stack["id"]])
    assert inspect_result.exit_code == 0
    inspected = json.loads(inspect_result.stdout)
    assert inspected["id"] == target_stack["id"]

    # 3. View boot order
    boot_result = cli_runner.invoke(app, ["stack", "boot-order", target_stack["id"]])
    assert boot_result.exit_code == 0
    boot_plan = json.loads(boot_result.stdout)
    assert "stages" in boot_plan

    # 4. Check readiness
    readiness_result = cli_runner.invoke(app, ["stack", "readiness", target_stack["id"]])
    assert readiness_result.exit_code == 0
    probes = json.loads(readiness_result.stdout)
    assert isinstance(probes, list)

    # 5. Switch stack
    switch_result = cli_runner.invoke(app, ["stack", "switch", target_stack["id"], "--no-wait"])
    assert switch_result.exit_code == 0
    switch_data = json.loads(switch_result.stdout)
    assert switch_data["target_stack_id"] == target_stack["id"]

    # 6. Stop stack
    stop_result = cli_runner.invoke(app, ["stack", "stop", target_stack["id"]])
    assert stop_result.exit_code == 0

    # 7. Create custom stack
    create_result = cli_runner.invoke(
        app,
        ["stack", "create", "Custom Pipeline", "--description", "Custom stack", "--projects", "p1", "--projects", "p2"],
    )
    assert create_result.exit_code == 0
    created = json.loads(create_result.stdout)
    assert created["name"] == "Custom Pipeline"
    assert len(created["projects"]) == 2


def test_cli_readiness_access_workflow(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)
    monkeypatch.setattr(services.stacks.readiness_policy, "_resolve", lambda host, port: ("10.20.30.40",))
    stack = services.stacks.create_stack(
        "private readiness",
        projects=[
            StackProjectMember(
                project_id="p1",
                project_name="api",
                readiness_gates=[ReadinessGate(probe_type="tcp_port", host="private.internal", port=8080)],
            )
        ],
    )

    request = cli_runner.invoke(app, ["stack", "readiness", stack.id, "--request-access"])
    assert request.exit_code == 0
    payload = json.loads(request.stdout)
    assert payload["probes"][0]["policy_status"] == "approval_required"
    approval_id = payload["authorization_requests"][0]["approval"]["id"]
    services.actions.approve_and_execute(approval_id)

    listed = cli_runner.invoke(app, ["stack", "readiness-access"])
    authorization_id = json.loads(listed.stdout)[0]["id"]
    revoked = cli_runner.invoke(app, ["stack", "readiness-access", "--revoke", authorization_id])
    assert revoked.exit_code == 0
    assert json.loads(revoked.stdout)["revoked"] is True
