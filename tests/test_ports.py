from dev_agent.models import PortOwner
from dev_agent.ports.scanner import parse_ss


def test_parse_ss_ipv4_ipv6_and_process():
    output = """tcp LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:* users:((\"uvicorn\",pid=14523,fd=7))
udp UNCONN 0 0 [::]:5353 [::]:* users:((\"mdns\",pid=42,fd=3))
"""
    result = parse_ss(output)
    assert [(item.port, item.protocol, item.pid) for item in result] == [(8000, "tcp", 14523), (5353, "udp", 42)]
    assert result[0].process == "uvicorn"


def test_port_ownership_and_free_selection(service_factory):
    services = service_factory([PortOwner(port=8000), PortOwner(port=8001), PortOwner(port=3001)])
    assert services.ports.find_port_owner(8000).port == 8000
    assert not services.ports.is_port_available(8000)
    assert services.ports.find_free_port(8000) == 8002
    assert services.ports.find_free_ports(3000, 3004, 3) == [3000, 3002, 3003]


def test_invalid_port_rejected(service_factory):
    services = service_factory()
    try:
        services.ports.find_port_owner(70000)
    except ValueError as exc:
        assert "65535" in str(exc)
    else:
        raise AssertionError("invalid port accepted")


def test_cross_project_conflicts(service_factory, tmp_path):
    for name in ("one", "two"):
        project = tmp_path / name
        project.mkdir()
        (project / "compose.yaml").write_text("services:\n  api:\n    ports: ['8000:80']\n")
    services = service_factory()
    services.projects.register_project(tmp_path / "one")
    services.projects.register_project(tmp_path / "two")
    conflicts = services.ports.detect_port_conflicts()
    assert conflicts[0]["port"] == 8000
    assert {item["project"] for item in conflicts[0]["claims"]} == {"one", "two"}
