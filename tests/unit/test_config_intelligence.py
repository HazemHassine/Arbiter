from pathlib import Path

from arbiter.config_intelligence.models import (
    EnvVarAuditStatus,
    PortDriftType,
)
from arbiter.models import ActionSpec, Risk
from arbiter.security import is_placeholder_secret, mask_secret


def _setup_drift_project(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "compose.yaml").write_text("""services:
  web:
    image: nginx:alpine
    ports:
      - "${WEB_PORT:-8080}:80"
  db:
    image: postgres:16
    ports:
      - "${DB_PORT}:5432"
""")
    (root / ".env").write_text("""WEB_PORT=3000
SECRET_KEY=change_me
DATABASE_PASSWORD=super_secret_db_password_12345
EXTRA_KEY=undocumented
UNUSED_PORT=9000
""")
    (root / ".env.example").write_text("""# Web server port
WEB_PORT=8080

# Application secret
SECRET_KEY=

# Database password
DATABASE_PASSWORD=

# Required API key
API_KEY=your_api_key_here
""")


def test_port_drift_detection(service_factory, tmp_path: Path):
    proj_dir = tmp_path / "drift-app"
    _setup_drift_project(proj_dir)

    services = service_factory()
    project = services.projects.register_project(proj_dir)

    drift_report = services.config_intelligence.audit_project_config(project.id)

    assert drift_report.project_name == "drift-app"
    assert drift_report.has_env is True
    assert drift_report.has_env_example is True
    assert drift_report.has_compose is True

    # 1. Compose default mismatch: WEB_PORT=3000 overrides compose default 8080
    mismatches = [d for d in drift_report.port_drifts if d.drift_type == PortDriftType.COMPOSE_DEFAULT_MISMATCH]
    assert len(mismatches) >= 1
    assert mismatches[0].variable == "WEB_PORT"
    assert mismatches[0].env_value == 3000
    assert mismatches[0].compose_default == 8080

    # 2. Unresolved compose variable: DB_PORT in compose has no default and is missing in .env
    unresolved = [d for d in drift_report.port_drifts if d.drift_type == PortDriftType.UNRESOLVED_COMPOSE_VARIABLE]
    assert len(unresolved) >= 1
    assert unresolved[0].variable == "DB_PORT"

    # 3. Unreferenced port in .env: UNUSED_PORT=9000
    unreferenced = [d for d in drift_report.port_drifts if d.drift_type == PortDriftType.UNREFERENCED_ENV_PORT]
    assert len(unreferenced) >= 1
    assert unreferenced[0].variable == "UNUSED_PORT"


def test_safe_env_variable_auditing_and_secrets_masking(service_factory, tmp_path: Path):
    proj_dir = tmp_path / "audit-app"
    _setup_drift_project(proj_dir)

    services = service_factory()
    project = services.projects.register_project(proj_dir)

    report = services.config_intelligence.audit_project_config(project.id)

    # Missing variable: API_KEY is in .env.example but not in .env
    missing = {item.key: item for item in report.missing_env_vars}
    assert "API_KEY" in missing
    assert missing["API_KEY"].status == EnvVarAuditStatus.MISSING
    assert missing["API_KEY"].is_secret is True

    # Placeholder secret: SECRET_KEY=change_me
    audit_by_key = {item.key: item for item in report.env_audit}
    assert audit_by_key["SECRET_KEY"].status == EnvVarAuditStatus.PLACEHOLDER

    # Secrets masking: DATABASE_PASSWORD should be masked
    db_pass_item = audit_by_key["DATABASE_PASSWORD"]
    assert db_pass_item.is_secret is True
    assert "super_secret_db_password_12345" not in (db_pass_item.masked_value or "")
    assert "••••••••" in (db_pass_item.masked_value or "")

    # Undocumented variable: EXTRA_KEY is in .env but not in .env.example
    assert audit_by_key["EXTRA_KEY"].status == EnvVarAuditStatus.UNDOCUMENTED


def test_mask_secret_helper():
    assert mask_secret("") == ""
    assert mask_secret("12345") == "••••••••"
    assert mask_secret("password123") == "pa••••••••23"
    assert mask_secret("sk-proj-1234567890abcdef") == "sk-••••••••cdef"
    assert is_placeholder_secret("change_me") is True
    assert is_placeholder_secret("your_key_here") is True
    assert is_placeholder_secret("my-real-secret-12345") is False


def test_visual_diff_masks_env_secrets(service_factory):
    services = service_factory()
    old_env = "PORT=8000\nAPI_KEY=sk-proj-old1234567890\n"
    new_env = "PORT=8080\nAPI_KEY=sk-proj-new9876543210\n"

    diff = services.config_intelligence.build_visual_diff(old_env, new_env, ".env")
    assert diff.is_secret_file is True
    assert "sk-proj-old" not in diff.unified_diff
    assert "sk-proj-new" not in diff.unified_diff
    assert "••••••••" in diff.unified_diff
    assert diff.additions >= 1
    assert diff.deletions >= 1


def test_time_travel_preview_on_port_resolution(service_factory):
    services = service_factory()
    spec = ActionSpec(
        action="compose.change_port",
        risk=Risk.MEDIUM_RISK,
        arguments={"project_id": "proj-1", "service": "web", "old_port": 8000, "new_port": 8080},
        summary="Change web port",
    )
    preview = services.config_intelligence.build_time_travel_preview(spec)
    assert preview.action == "compose.change_port"
    assert len(preview.port_changes) == 1
    assert preview.port_changes[0]["service"] == "web"
    assert preview.port_changes[0]["before"] == "8000/tcp"
    assert preview.port_changes[0]["after"] == "8080/tcp"
    assert len(preview.container_changes) == 1
    assert preview.container_changes[0]["transition"] == "recreate_service"
    assert len(preview.resolves_drifts) >= 1
