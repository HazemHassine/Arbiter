import pytest

from arbiter.compose.editor import ComposeEditor, change_env_port
from arbiter.compose.parser import inspect_compose


def test_change_service_host_port(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""services:
  web:
    image: nginx:alpine
    ports:
      - "8000:80"
  db:
    image: postgres:16
    ports:
      - "5432:5432"
""")
    editor = ComposeEditor()
    result = editor.change_service_host_port(compose_file, "web", old_port=8000, new_port=8080, validate=False)
    assert result["old_host_port"] == 8000
    assert result["new_host_port"] == 8080

    services, ports = inspect_compose(compose_file)
    web_ports = [p for p in ports if p.service == "web" or p.host_port == 8080]
    assert len(web_ports) == 1
    assert web_ports[0].host_port == 8080


def test_change_service_host_port_missing_service_raises_lookup_error(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services:\n  web:\n    ports: ['8000:80']\n")
    editor = ComposeEditor()
    with pytest.raises(LookupError, match="Compose service not found"):
        editor.change_service_host_port(compose_file, "nonexistent", old_port=8000, new_port=8080, validate=False)


def test_change_service_host_port_missing_port_raises_lookup_error(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services:\n  web:\n    ports: ['8000:80']\n")
    editor = ComposeEditor()
    with pytest.raises(LookupError, match="Host port 9000 not found"):
        editor.change_service_host_port(compose_file, "web", old_port=9000, new_port=8080, validate=False)


def test_change_service_host_port_env_driven_raises_value_error(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services:\n  web:\n    ports: ['${PORT}:80']\n")
    (tmp_path / ".env").write_text("PORT=8000\n")
    editor = ComposeEditor()
    with pytest.raises(ValueError, match="environment-driven"):
        editor.change_service_host_port(compose_file, "web", old_port=8000, new_port=8080, validate=False)


def test_change_env_port_variable(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=8000\nOTHER=123\n")
    result = change_env_port(env_file, "PORT", old_port=8000, new_port=8080)
    assert result["new_port"] == 8080
    assert "PORT=8080" in env_file.read_text()
    assert "OTHER=123" in env_file.read_text()
