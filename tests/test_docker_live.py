"""Opt-in smoke tests against a real Docker daemon.

Run with ``ARBITER_RUN_DOCKER_TESTS=1 uv run pytest -m docker``. The lifecycle
test creates one clearly labelled temporary container and always removes it.
"""

import os
from uuid import uuid4

import docker
import pytest

from arbiter.docker.service import DockerService
from arbiter.models import ActionSpec, Risk
from arbiter.ports.scanner import LinuxPortScanner
from arbiter.services import build_services

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def live_client():
    if os.getenv("ARBITER_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set ARBITER_RUN_DOCKER_TESTS=1 to enable live Docker tests")
    client = docker.from_env()
    client.ping()
    yield client
    client.close()


def test_live_docker_inspection(live_client):
    service = DockerService(live_client)

    assert isinstance(service.list_containers(), list)
    assert isinstance(service.list_networks(), list)
    assert set(service.disk_usage()) == {"images", "containers", "volumes", "build_cache"}


def test_live_approved_container_lifecycle(live_client, settings):
    image = os.getenv("ARBITER_DOCKER_TEST_IMAGE", "alpine:3.20")
    try:
        live_client.images.get(image)
    except docker.errors.ImageNotFound:
        live_client.images.pull(image)
    name = f"arbiter-smoke-{uuid4().hex[:10]}"
    container = live_client.containers.run(
        image,
        ["sh", "-c", "sleep 60"],
        name=name,
        labels={"io.arbiter.test": "true"},
        detach=True,
    )
    try:
        services = build_services(settings, docker=DockerService(live_client), scanner=LinuxPortScanner())
        proposal = services.actions.propose(
            ActionSpec(
                action="container.stop",
                arguments={"identifier": container.id},
                summary=f"Stop temporary test container {name}",
                risk=Risk.MEDIUM_RISK,
            )
        )

        result = services.actions.approve_and_execute(proposal["approval"]["id"])

        assert result.status == "completed"
        container.reload()
        assert container.status == "exited"
    finally:
        container.remove(force=True)
