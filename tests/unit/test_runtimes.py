from arbiter.runtimes.service import RuntimeService
from tests.fixtures.doubles import FakeDocker


class MockClient:
    def ping(self):
        return True


def test_runtime_service_detects_available_docker():
    fake_docker = FakeDocker()
    fake_docker.client = MockClient()
    service = RuntimeService(docker=fake_docker)

    capabilities = service.list_capabilities()
    docker_cap = next(c for c in capabilities if c.name == "Docker")
    assert docker_cap.available is True
    assert docker_cap.support == "full"
    assert "lifecycle" in docker_cap.capabilities


def test_runtime_service_handles_unavailable_docker():
    class BrokenClient:
        def ping(self):
            raise RuntimeError("daemon down")

    fake_docker = FakeDocker()
    fake_docker.client = BrokenClient()
    service = RuntimeService(docker=fake_docker)

    capabilities = service.list_capabilities()
    docker_cap = next(c for c in capabilities if c.name == "Docker")
    assert docker_cap.available is False
    assert docker_cap.support == "unavailable"
    assert "daemon down" in str(docker_cap.detail)
