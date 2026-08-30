from pathlib import Path

import pytest

from arbiter.security import (
    redact,
    redact_action_arguments,
    safe_project_path,
    validate_bind_host,
)


def test_validate_bind_host_loopback():
    assert validate_bind_host("127.0.0.1") == "127.0.0.1"
    assert validate_bind_host("::1") == "::1"
    assert validate_bind_host("localhost") == "localhost"


def test_validate_bind_host_remote_protection():
    with pytest.raises(ValueError, match="ALLOW_REMOTE_ACCESS"):
        validate_bind_host("0.0.0.0", allow_remote_access=False)
    with pytest.raises(ValueError, match="ALLOW_REMOTE_ACCESS"):
        validate_bind_host("192.168.1.100", allow_remote_access=False)
    assert validate_bind_host("0.0.0.0", allow_remote_access=True) == "0.0.0.0"


def test_redact_secrets_in_nested_structures():
    raw = {
        "API_KEY": "sk-12345",
        "nested": {
            "password": "pass",
            "token": "tok-abc",
            "safe_val": 42,
            "list": [{"db_credential": "super-secret"}, "hello"],
        },
    }
    redacted = redact(raw)
    assert redacted["API_KEY"] == "<redacted>"
    assert redacted["nested"]["password"] == "<redacted>"
    assert redacted["nested"]["token"] == "<redacted>"
    assert redacted["nested"]["safe_val"] == 42
    assert redacted["nested"]["list"][0]["db_credential"] == "<redacted>"
    assert redacted["nested"]["list"][1] == "hello"


def test_safe_project_path_validation(tmp_path: Path):
    root = tmp_path / "projects"
    root.mkdir()
    project = root / "app"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    # Valid path inside root
    assert safe_project_path(project, roots=[root]) == project.resolve()

    # Path outside roots raises ValueError
    with pytest.raises(ValueError, match="outside configured project roots"):
        safe_project_path(outside, roots=[root])

    # Non-directory raises ValueError
    file_path = project / "somefile.txt"
    file_path.write_text("hello")
    with pytest.raises(ValueError, match="not a directory"):
        safe_project_path(file_path, roots=[root])


def test_redact_action_arguments_for_env_file():
    args = {"path": "/app/.env", "content": "SECRET_KEY=12345\n"}
    redacted = redact_action_arguments("file.update", args)
    assert redacted["content"] == "<redacted .env editor payload>"

    other_args = {"path": "/app/compose.yaml", "content": "services: {}\n"}
    other_redacted = redact_action_arguments("file.update", other_args)
    assert other_redacted["content"] == "services: {}\n"
