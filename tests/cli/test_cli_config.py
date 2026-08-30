import json
from pathlib import Path

from typer.testing import CliRunner

from arbiter.cli.app import app


def _setup_cli_project(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "compose.yaml").write_text("""services:
  web:
    image: nginx:alpine
    ports:
      - "${PORT:-8080}:80"
""")
    (root / ".env").write_text("PORT=3000\nAPI_KEY=super-secret-123456\n")
    (root / ".env.example").write_text("PORT=8080\nAPI_KEY=\nMISSING_FLAG=true\n")


def test_cli_config_drift_and_audit(service_factory, tmp_path: Path, monkeypatch):
    proj_dir = tmp_path / "cli-drift-project"
    _setup_cli_project(proj_dir)

    services = service_factory()
    services.projects.register_project(proj_dir)

    monkeypatch.setattr("arbiter.cli.app.services", lambda: services)
    runner = CliRunner()

    # 1. arbiter config drift
    res_drift = runner.invoke(app, ["config", "drift", "cli-drift-project"])
    assert res_drift.exit_code == 0
    data_drift = json.loads(res_drift.stdout)
    assert data_drift["project_name"] == "cli-drift-project"
    assert len(data_drift["port_drifts"]) >= 1

    # 2. arbiter config audit
    res_audit = runner.invoke(app, ["config", "audit", "cli-drift-project"])
    assert res_audit.exit_code == 0
    data_audit = json.loads(res_audit.stdout)
    assert data_audit["project"] == "cli-drift-project"
    assert "super-secret-123456" not in res_audit.stdout
    api_key_item = next(v for v in data_audit["env_audit"] if v["key"] == "API_KEY")
    assert "••••••••" in api_key_item["masked_value"]
    assert "super-secret-123456" not in api_key_item["masked_value"]
