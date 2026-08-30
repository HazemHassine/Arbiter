import sys
from pathlib import Path

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from typing import Any  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from arbiter.api.app import create_app  # noqa: E402
from arbiter.config import Settings  # noqa: E402
from arbiter.models import ContainerInfo  # noqa: E402
from arbiter.services import build_services  # noqa: E402
from tests.fixtures.doubles import FakeDocker, FakeScanner  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        project_roots=[tmp_path],
        default_port_search_range_start=3000,
        default_port_search_range_end=9999,
        _env_file=None,
    )


@pytest.fixture
def service_factory(settings: Settings):
    def factory(owners=None, containers=None, **kwargs: Any):
        docker = kwargs.pop("docker", FakeDocker(containers))
        scanner = kwargs.pop("scanner", FakeScanner(owners))
        return build_services(settings, docker=docker, scanner=scanner, **kwargs)

    return factory


@pytest.fixture
def container() -> ContainerInfo:
    return ContainerInfo(
        id="abc123456789",
        name="test-postgres",
        image="postgres:16",
        state="running",
        compose_project="test-project",
        compose_service="db",
    )


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def test_client_factory(service_factory):
    def factory(owners=None, containers=None, **kwargs: Any) -> TestClient:
        services = service_factory(owners=owners, containers=containers, **kwargs)
        return TestClient(create_app(services=services))

    return factory
