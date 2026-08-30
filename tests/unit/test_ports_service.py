import pytest

from arbiter.config import Settings
from arbiter.models import ContainerInfo, PortBinding, PortOwner
from arbiter.ports.service import PortService
from tests.fixtures.doubles import FakeScanner


def test_find_port_owner_and_availability(service_factory):
    services = service_factory([PortOwner(port=8000, protocol="tcp", process="uvicorn", pid=123)])
    owner = services.ports.find_port_owner(8000)
    assert owner is not None
    assert owner.port == 8000
    assert owner.process == "uvicorn"
    assert not services.ports.is_port_available(8000)
    assert services.ports.is_port_available(9000)
    assert services.ports.find_port_owner(9000) is None


def test_port_validation():
    service = PortService(
        scanner=FakeScanner(),
        settings=Settings(database_url="sqlite:///:memory:", _env_file=None),
    )
    with pytest.raises(ValueError, match="1 and 65535"):
        service.find_port_owner(0)
    with pytest.raises(ValueError, match="1 and 65535"):
        service.find_port_owner(70000)
    with pytest.raises(ValueError, match="Invalid range or count"):
        service.find_free_ports(start=5000, end=4000, count=1)
    with pytest.raises(ValueError, match="Invalid range or count"):
        service.find_free_ports(start=5000, end=5010, count=0)


def test_find_free_ports_with_gaps(service_factory):
    services = service_factory([PortOwner(port=3000), PortOwner(port=3001), PortOwner(port=3003)])
    free = services.ports.find_free_ports(start=3000, end=3005, count=2)
    assert free == [3002, 3004]


def test_find_free_port_wraps_to_start_range():
    used = [PortOwner(port=p) for p in range(8000, 8011)]
    service = PortService(
        scanner=FakeScanner(used),
        settings=Settings(
            database_url="sqlite:///:memory:",
            default_port_search_range_start=7990,
            default_port_search_range_end=8010,
            _env_file=None,
        ),
    )
    # Since 8000 to 8010 is taken, preferred 8000 should wrap to start at 7990
    assert service.find_free_port(8000) == 7990


def test_find_free_port_exhausted_raises_runtime_error():
    used = [PortOwner(port=p) for p in range(3000, 3005)]
    service = PortService(
        scanner=FakeScanner(used),
        settings=Settings(
            database_url="sqlite:///:memory:",
            default_port_search_range_start=3000,
            default_port_search_range_end=3004,
            _env_file=None,
        ),
    )
    with pytest.raises(RuntimeError, match="No free port in configured range"):
        service.find_free_port(3000)


def test_list_used_ports_enriches_from_docker_containers():
    container = ContainerInfo(
        id="cnt1",
        name="web_api",
        image="web:v1",
        state="running",
        compose_project="my-proj",
        compose_service="api",
        ports=[PortBinding(host_port=5000, container_port=80, protocol="tcp")],
        labels={"com.docker.compose.project.config_files": "/path/to/compose.yaml"},
    )
    service = PortService(
        scanner=FakeScanner([PortOwner(port=5000, protocol="tcp")]),
        settings=Settings(database_url="sqlite:///:memory:", _env_file=None),
        docker_provider=lambda: [container],
    )
    used = service.list_used_ports()
    assert len(used) == 1
    assert used[0].port == 5000
    assert used[0].owner_type == "docker_container"
    assert used[0].container == "web_api"
    assert used[0].project == "my-proj"
    assert used[0].service == "api"
