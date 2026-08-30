import json

from typer.testing import CliRunner

import arbiter.cli.app as cli_module
from arbiter.cli.app import app
from arbiter.models import PortOwner


def test_cli_ports_list(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory([PortOwner(port=5432, process="postgres", owner_type="process")])
    monkeypatch.setattr(cli_module, "services", lambda: services)

    result = cli_runner.invoke(app, ["ports"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data) == 1
    assert data[0]["port"] == 5432
    assert data[0]["process"] == "postgres"


def test_cli_ports_free_range(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory([PortOwner(port=3000)])
    monkeypatch.setattr(cli_module, "services", lambda: services)

    result = cli_runner.invoke(app, ["ports", "--free", "3000:3005", "--count", "2"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data == [3001, 3002]


def test_cli_ports_invalid_range(cli_runner: CliRunner, service_factory, monkeypatch):
    services = service_factory()
    monkeypatch.setattr(cli_module, "services", lambda: services)

    result = cli_runner.invoke(app, ["ports", "--free", "invalid_range"])
    assert result.exit_code != 0
    assert "Range must be START:END" in result.output
