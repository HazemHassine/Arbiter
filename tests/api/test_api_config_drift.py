from pathlib import Path

from fastapi.testclient import TestClient

from arbiter.api.app import create_app
from arbiter.models import ContainerInfo


def _setup_api_project(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "compose.yaml").write_text("""services:
  web:
    image: nginx:alpine
    ports:
      - "${PORT:-8000}:80"
""")
    (root / ".env").write_text("PORT=3000\nAPI_KEY=secret-token-12345\n")
    (root / ".env.example").write_text("PORT=8000\nAPI_KEY=\nEXTRA_REQUIRED_VAR=\n")


def test_api_config_drift_endpoints(service_factory, tmp_path: Path):
    proj_dir = tmp_path / "api-drift-project"
    _setup_api_project(proj_dir)

    services = service_factory()
    project = services.projects.register_project(proj_dir)
    client = TestClient(create_app(services=services))

    # Global config drift list
    global_res = client.get("/api/v1/config-drift")
    assert global_res.status_code == 200
    reports = global_res.json()
    assert len(reports) == 1
    assert reports[0]["project_name"] == "api-drift-project"
    assert reports[0]["has_env"] is True

    # Project-specific config drift
    proj_res = client.get(f"/api/v1/projects/{project.id}/config-drift")
    assert proj_res.status_code == 200
    drift_data = proj_res.json()
    assert drift_data["project_id"] == project.id
    assert len(drift_data["port_drifts"]) >= 1
    assert len(drift_data["missing_env_vars"]) >= 1
    assert any(v["key"] == "EXTRA_REQUIRED_VAR" for v in drift_data["missing_env_vars"])

    # Ensure secret is masked in API response
    api_key_item = next(v for v in drift_data["env_audit"] if v["key"] == "API_KEY")
    assert "secret-token-12345" not in api_key_item["masked_value"]
    assert "••••••••" in api_key_item["masked_value"]


def test_api_approvals_include_time_travel(service_factory):
    cnt = ContainerInfo(id="c-tt", name="web", image="nginx:alpine", state="running")
    services = service_factory(containers=[cnt])
    client = TestClient(create_app(services=services))

    action_res = client.post("/api/v1/containers/c-tt/stop").json()
    approval_id = action_res["approval"]["id"]

    approval_res = client.get(f"/api/v1/approvals/{approval_id}")
    assert approval_res.status_code == 200
    appr_data = approval_res.json()
    assert "time_travel" in appr_data
    assert appr_data["time_travel"]["action"] == "container.stop"
