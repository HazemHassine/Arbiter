"""Opt-in smoke tests against a real Docker daemon.

Run with ``ARBITER_RUN_DOCKER_TESTS=1 uv run pytest -m docker``. The lifecycle
test creates one clearly labelled temporary container and always removes it.
"""

import os
import socket
import subprocess
from uuid import uuid4

import docker
import pytest
import yaml

from arbiter.agent.service import AgentService
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


@pytest.fixture(scope="module")
def live_image(live_client):
    image = os.getenv("ARBITER_DOCKER_TEST_IMAGE", "alpine:3.20")
    try:
        live_client.images.get(image)
    except docker.errors.ImageNotFound:
        live_client.images.pull(image)
    return image


def _compose_down(compose_file):
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "down", "--volumes", "--remove-orphans"],
        cwd=compose_file.parent,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _available_ports(count):
    sockets = []
    try:
        for _ in range(count):
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            sockets.append(listener)
        return [int(listener.getsockname()[1]) for listener in sockets]
    finally:
        for listener in sockets:
            listener.close()


def test_live_docker_inspection(live_client):
    service = DockerService(live_client)

    assert isinstance(service.list_containers(), list)
    assert isinstance(service.list_networks(), list)
    assert set(service.disk_usage()) == {"images", "containers", "volumes", "build_cache"}


def test_live_approved_container_lifecycle(live_client, live_image, settings):
    name = f"arbiter-smoke-{uuid4().hex[:10]}"
    container = live_client.containers.run(
        live_image,
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


def test_live_compose_conflict_reconciliation_workflow(live_client, live_image, settings, tmp_path):
    blocker = live_client.containers.run(
        live_image,
        ["sh", "-c", "sleep 120"],
        ports={"8080/tcp": None},
        labels={"io.arbiter.test": "true"},
        detach=True,
    )
    blocker.reload()
    occupied_port = int(blocker.attrs["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"])
    project_name = f"arbiter-e2e-{uuid4().hex[:8]}"
    workspace = tmp_path / project_name
    workspace.mkdir()
    compose_file = workspace / "compose.yaml"
    compose_file.write_text(
        f"""name: {project_name}
services:
  api:
    image: {live_image}
    command: ["sh", "-c", "sleep 120"]
    labels:
      io.arbiter.test: "true"
    ports:
      - "{occupied_port}:8080"
"""
    )
    services = build_services(settings, docker=DockerService(live_client), scanner=LinuxPortScanner())
    project = services.projects.register_project(workspace)
    try:
        proposal = AgentService(services).prepare_project(identifier=project.id)
        replacement_port = proposal["reconciliation"]["changes"][0]["suggested_port"]

        result = services.actions.approve_and_execute(proposal["approval"]["id"])

        assert result.status == "completed"
        assert result.verification["verified"] is True
        assert yaml.safe_load(compose_file.read_text())["services"]["api"]["ports"] == [f"{replacement_port}:8080"]
        owner = services.ports.find_port_owner(replacement_port)
        assert owner is not None
        assert owner.project == project_name
        assert owner.service == "api"
    finally:
        _compose_down(compose_file)
        blocker.remove(force=True)


@pytest.mark.parametrize("environment_driven", [False, True], ids=["compose", "env"])
def test_live_reconciliation_rolls_back_after_recreation_failure(
    live_client, live_image, settings, tmp_path, monkeypatch, environment_driven
):
    project_name = f"arbiter-rollback-{uuid4().hex[:8]}"
    workspace = tmp_path / project_name
    workspace.mkdir()
    compose_file = workspace / "compose.yaml"
    old_port, new_port = _available_ports(2)
    published = "${API_PORT}:8080" if environment_driven else f"{old_port}:8080"
    compose_file.write_text(
        f"""name: {project_name}
services:
  api:
    image: {live_image}
    command: ["sh", "-c", "sleep 120"]
    labels:
      io.arbiter.test: "true"
    ports:
      - "{published}"
"""
    )
    env_file = workspace / ".env"
    if environment_driven:
        env_file.write_text(f"API_PORT={old_port}\n")
    changed_file = env_file if environment_driven else compose_file
    original = changed_file.read_text()
    services = build_services(settings, docker=DockerService(live_client), scanner=LinuxPortScanner())
    project = services.projects.register_project(workspace)
    original_recreate = services.actions.compose.recreate_service
    attempts = 0

    def fail_then_restore(file, service):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("forced live recreation failure")
        return original_recreate(file, service)

    monkeypatch.setattr(services.actions.compose, "recreate_service", fail_then_restore)
    spec = ActionSpec(
        action="project.resolve_ports",
        project_id=project.id,
        summary="Force live rollback",
        risk=Risk.MEDIUM_RISK,
        arguments={
            "project_id": project.id,
            "changes": [
                {
                    "service": "api",
                    "old_port": old_port,
                    "new_port": new_port,
                    "protocol": "tcp",
                    "compose_file": str(compose_file),
                    "env_variable": "API_PORT" if environment_driven else None,
                }
            ],
        },
    )
    try:
        result = services.actions.execute(spec)

        assert result.status == "failed"
        assert "restored configuration" in result.error
        assert changed_file.read_text() == original
        assert attempts == 2
        restored_owner = services.ports.find_port_owner(old_port)
        assert restored_owner is not None
        assert restored_owner.project == project_name
    finally:
        _compose_down(compose_file)
