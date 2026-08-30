import json

from typer.testing import CliRunner

import arbiter.cli.app as cli_module
from arbiter.cli.app import app


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
