import json
from pathlib import Path

from typer.testing import CliRunner

import arbiter.cli.app as cli_module
from arbiter.cli.app import app
from tests.fixtures.workspaces import create_sample_workspace


def test_cli_projects_list_and_register(cli_runner: CliRunner, service_factory, tmp_path: Path, monkeypatch):
    workspace = tmp_path / "cli-proj"
    create_sample_workspace(workspace)
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)

    # Register project
    reg_result = cli_runner.invoke(app, ["register", str(workspace)])
    assert reg_result.exit_code == 0
    reg_data = json.loads(reg_result.stdout)
    assert reg_data["name"] == "cli-proj"

    # List projects
    list_result = cli_runner.invoke(app, ["projects"])
    assert list_result.exit_code == 0
    list_data = json.loads(list_result.stdout)
    assert len(list_data) == 1
    assert list_data[0]["name"] == "cli-proj"

    # Inspect project
    inspect_result = cli_runner.invoke(app, ["inspect", reg_data["id"]])
    assert inspect_result.exit_code == 0
    inspect_data = json.loads(inspect_result.stdout)
    assert inspect_data["id"] == reg_data["id"]

    # Prepare project
    prep_result = cli_runner.invoke(app, ["prepare", reg_data["id"]])
    assert prep_result.exit_code == 0
