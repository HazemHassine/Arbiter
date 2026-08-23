from pathlib import Path

import pytest
import yaml

from dev_agent.compose.editor import ComposeEditor, change_env_port
from dev_agent.compose.parser import inspect_compose, parse_port
from dev_agent.projects.discovery import discover_projects


def test_compose_port_formats_and_environment(tmp_path):
    assert parse_port("127.0.0.1:5432:5432/udp").host_ip == "127.0.0.1"
    assert parse_port({"published": 8000, "target": 80}).host_port == 8000
    assert parse_port("${API_PORT:-8001}:80", {}).host_port == 8001
    file = tmp_path / "compose.yaml"
    file.write_text("services:\n  api:\n    ports:\n      - '${API_PORT}:80'\n")
    (tmp_path / ".env").write_text("API_PORT=9000\nPASSWORD=nope\n")
    services, ports = inspect_compose(file)
    assert services == ["api"]
    assert ports[0].host_port == 9000
    assert ports[0].variable == "API_PORT"


def test_project_discovery_is_bounded(tmp_path):
    project = tmp_path / "known"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='x'\nversion='1'\n")
    deep = project / "nested"
    deep.mkdir()
    (deep / "compose.yaml").write_text("services: {}\n")
    found = discover_projects([tmp_path])
    assert [item.name for item in found] == ["known"]


def test_project_registry_refresh(service_factory, tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    compose = project / "compose.yaml"
    compose.write_text("services:\n  web:\n    ports: ['3000:3000']\n")
    services = service_factory()
    registered = services.projects.register_project(project)
    assert services.projects.get_project(registered.id).ports[0].host_port == 3000
    compose.write_text("services:\n  web:\n    ports: ['3001:3000']\n")
    assert services.projects.refresh_project(registered.id).ports[0].host_port == 3001
    assert services.projects.unregister_project(registered.id)


def test_project_environment_redacts_secrets(service_factory, tmp_path):
    project = tmp_path / "env-demo"
    project.mkdir()
    (project / "compose.yaml").write_text("services: {}\n")
    (project / ".env").write_text("API_PORT=8000\nAPI_KEY=secret\n")
    services = service_factory()
    registered = services.projects.register_project(project)
    assert services.projects.get_environment(registered.id) == {"API_PORT": "8000", "API_KEY": "<redacted>"}


def test_structured_compose_edit_creates_backup(tmp_path):
    file = tmp_path / "compose.yaml"
    file.write_text("services:\n  db:\n    ports: ['5432:5432']\n")
    result = ComposeEditor().change_service_host_port(file, "db", 5432, 5433, validate=False)
    assert Path(result["backup"]).is_file()
    assert yaml.safe_load(file.read_text())["services"]["db"]["ports"] == ["5433:5432"]


def test_compose_edit_rejects_environment_driven_port(tmp_path):
    file = tmp_path / "compose.yaml"
    file.write_text("services:\n  db:\n    ports: ['${DB_PORT}:5432']\n")
    (tmp_path / ".env").write_text("DB_PORT=5432\n")
    with pytest.raises(ValueError, match="environment-driven"):
        ComposeEditor().change_service_host_port(file, "db", 5432, 5433, validate=False)


def test_structured_env_edit(tmp_path):
    file = tmp_path / ".env"
    file.write_text("API_PORT=8000\nPASSWORD=secret\n")
    result = change_env_port(file, "API_PORT", 8000, 8001)
    assert Path(result["backup"]).exists()
    assert "API_PORT=8001" in file.read_text()
    assert "PASSWORD=secret" in file.read_text()
