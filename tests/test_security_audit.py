import stat
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arbiter.api.app import create_app
from arbiter.compose.editor import ComposeEditor, change_env_port
from arbiter.compose.service import ComposeService
from arbiter.config import Settings
from arbiter.make.service import MakeService
from arbiter.security import (
    redact_sensitive_arguments,
    redact_sensitive_text,
    validate_browser_origin,
    validate_request_host,
)


def test_http_host_allowlist_blocks_dns_rebinding(service_factory):
    client = TestClient(create_app(services=service_factory()))

    response = client.get("/health", headers={"Host": "attacker.example"})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_host"
    assert response.headers["x-frame-options"] == "DENY"


def test_browser_mutations_require_same_origin(service_factory):
    client = TestClient(create_app(services=service_factory()))
    url = "/api/v1/ports/suggest"

    blocked = client.post(url, json={"preferred_port": 8123}, headers={"Origin": "https://attacker.example"})
    fetch_metadata_blocked = client.post(
        url,
        json={"preferred_port": 8123},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    same_origin = client.post(url, json={"preferred_port": 8123}, headers={"Origin": "http://testserver"})
    api_client = client.post(url, json={"preferred_port": 8123})

    assert blocked.status_code == 403
    assert blocked.json()["error"] == "cross_origin_request"
    assert fetch_metadata_blocked.status_code == 403
    assert same_origin.status_code == 200
    assert api_client.status_code == 200


def test_security_headers_and_private_api_caching(service_factory):
    client = TestClient(create_app(services=service_factory()))

    health = client.get("/health")
    api = client.get("/api/v1/projects")

    assert health.headers["content-security-policy"] == "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    assert health.headers["cross-origin-resource-policy"] == "same-origin"
    assert health.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert health.headers["referrer-policy"] == "no-referrer"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert api.headers["cache-control"] == "no-store"


def test_trusted_hosts_are_exact_and_wildcards_are_rejected():
    settings = Settings(ARBITER_TRUSTED_HOSTS="control.example,127.0.0.1", _env_file=None)

    assert settings.arbiter_trusted_hosts == ["control.example", "127.0.0.1"]
    assert validate_request_host("control.example:8765", set(settings.arbiter_trusted_hosts)) == "control.example"
    with pytest.raises(ValueError, match="not trusted"):
        validate_request_host("sub.control.example", set(settings.arbiter_trusted_hosts))
    with pytest.raises(ValidationError, match="wildcards"):
        Settings(ARBITER_TRUSTED_HOSTS="*.example.com", _env_file=None)


def test_browser_origin_validation_rejects_scheme_and_port_changes():
    with pytest.raises(ValueError, match="Cross-origin"):
        validate_browser_origin(
            method="POST",
            scheme="http",
            host_header="localhost:8765",
            origin="https://localhost:8765",
            referer=None,
            sec_fetch_site="same-site",
        )
    with pytest.raises(ValueError, match="Cross-origin"):
        validate_browser_origin(
            method="DELETE",
            scheme="http",
            host_header="localhost:8765",
            origin="http://localhost:9000",
            referer=None,
            sec_fetch_site="same-site",
        )


def test_sqlite_state_database_is_owner_only(service_factory):
    services = service_factory()
    database_path = Path(services.database.engine.url.database or "")

    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600


def test_configuration_backups_are_private_and_not_adjacent(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    compose_file = project / "compose.yaml"
    compose_file.write_text("services:\n  api:\n    ports: ['8000:80']\n")
    env_file = project / ".env"
    env_file.write_text("API_PORT=8000\nPASSWORD=secret\n")

    backup_root = tmp_path / "state" / "backups"
    compose_result = ComposeEditor(backup_root).change_service_host_port(
        compose_file, "api", 8000, 8001, validate=False
    )
    env_result = change_env_port(env_file, "API_PORT", 8000, 8001, backup_root)

    for result in (compose_result, env_result):
        backup = Path(str(result["backup"]))
        assert backup.parent == backup_root
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
        assert not backup.is_relative_to(project)
    assert stat.S_IMODE(backup_root.stat().st_mode) == 0o700


def test_managed_file_backups_stay_outside_the_project(service_factory, tmp_path):
    project_path = tmp_path / "managed-project"
    project_path.mkdir()
    managed_file = project_path / ".dockerignore"
    managed_file.write_text(".git\n")
    services = service_factory()
    project = services.projects.register_project(project_path)
    current = services.files.read(project.id, ".dockerignore")

    result = services.files.apply_update(project.id, ".dockerignore", ".git\n.venv\n", current.sha256)
    backup = Path(str(result["backup"]["backup_path"]))

    assert backup.is_relative_to(services.settings.arbiter_state_directory)
    assert not backup.is_relative_to(project_path)
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_compose_validation_does_not_return_rendered_secret_output(tmp_path, monkeypatch):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n")
    monkeypatch.setattr(
        "arbiter.compose.service.run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, "PASSWORD=rendered-secret\n", ""),
    )

    result = ComposeService().validate(compose_file)

    assert result == {"valid": True, "error": ""}


def test_command_targets_are_separated_from_options(tmp_path, monkeypatch):
    makefile = tmp_path / "Makefile"
    makefile.write_text("--version:\n\t@echo safe\n")
    calls: list[list[str]] = []

    def capture(args, **_kwargs):
        calls.append(args)
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("arbiter.make.service.run", capture)

    assert MakeService().run(tmp_path, "--version")["verified"] is True
    assert calls == [["make", "--", "--version"]]


def test_sensitive_process_arguments_are_redacted():
    command = "server --api-key top-secret --port 8000 DATABASE_PASSWORD=also-secret"

    assert redact_sensitive_text(command) == "server --api-key <redacted> --port 8000 DATABASE_PASSWORD=<redacted>"
    assert redact_sensitive_arguments(["server", "--token", "abc", "--port=8000", "API_KEY=def"]) == [
        "server",
        "--token",
        "<redacted>",
        "--port=8000",
        "API_KEY=<redacted>",
    ]
