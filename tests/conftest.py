from pathlib import Path

import pytest

from arbiter.config import Settings
from arbiter.models import ContainerInfo
from arbiter.services import build_services


class FakeScanner:
    def __init__(self, owners=None):
        self.owners = owners or []

    def scan(self):
        return [item.model_copy(deep=True) for item in self.owners]


class FakeDocker:
    def __init__(self, containers=None):
        self.containers = containers or []
        self.executed = []

    def list_containers(self, all=True):
        return list(self.containers)

    def inspect_container(self, identifier):
        matches = [item for item in self.containers if identifier in {item.id, item.name}]
        if not matches:
            raise LookupError(identifier)
        return matches[0]

    def container_action(self, identifier, action):
        self.executed.append((identifier, action))
        return {"identifier": identifier, "action": action, "verified": True}

    def list_images(self):
        return []

    def list_volumes(self):
        return []

    def list_networks(self):
        return []

    def disk_usage(self):
        return {"images": {"count": 0}}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        project_roots=[tmp_path],
        default_port_search_range_start=3000,
        default_port_search_range_end=9999,
    )


@pytest.fixture
def service_factory(settings):
    def factory(owners=None, containers=None):
        return build_services(settings, docker=FakeDocker(containers), scanner=FakeScanner(owners))

    return factory


@pytest.fixture
def container():
    return ContainerInfo(id="abc123", name="db", image="postgres:16", state="running")
