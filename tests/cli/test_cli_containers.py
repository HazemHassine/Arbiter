import json

from typer.testing import CliRunner

import arbiter.cli.app as cli_module
from arbiter.cli.app import app
from arbiter.models import ContainerInfo


def test_cli_containers_and_resources(cli_runner: CliRunner, service_factory, monkeypatch):
    cnt = ContainerInfo(id="c-cli", name="redis-cli-test", image="redis:7", state="running")
    services = service_factory(containers=[cnt])
    monkeypatch.setattr(cli_module, "services", lambda: services)

    # Containers list
    list_res = cli_runner.invoke(app, ["containers"])
    assert list_res.exit_code == 0
    containers = json.loads(list_res.stdout)
    assert len(containers) == 1
    assert containers[0]["name"] == "redis-cli-test"

    # Container logs
    logs_res = cli_runner.invoke(app, ["logs", "c-cli"])
    assert logs_res.exit_code == 0
    assert "logs for c-cli" in logs_res.stdout

    # Disk usage
    disk_res = cli_runner.invoke(app, ["disk"])
    assert disk_res.exit_code == 0

    # Runtimes
    runtimes_res = cli_runner.invoke(app, ["runtimes"])
    assert runtimes_res.exit_code == 0
    runtimes = json.loads(runtimes_res.stdout)
    assert any(r["name"] == "Docker" for r in runtimes)
