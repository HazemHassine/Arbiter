from arbiter.models import PortOwner
from arbiter.ports.scanner import parse_ss


def test_parse_ss_ipv4_and_process():
    output = 'tcp LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:* users:(("uvicorn",pid=14523,fd=7))\n'
    result = parse_ss(output)
    assert len(result) == 1
    item = result[0]
    assert item.port == 8000
    assert item.protocol == "tcp"
    assert item.pid == 14523
    assert item.process == "uvicorn"
    assert item.host == "127.0.0.1"


def test_parse_ss_ipv6_and_udp():
    output = 'udp UNCONN 0 0 [::]:5353 [::]:* users:(("mdns",pid=42,fd=3))\n'
    result = parse_ss(output)
    assert len(result) == 1
    item = result[0]
    assert item.port == 5353
    assert item.protocol == "udp"
    assert item.pid == 42
    assert item.process == "mdns"


def test_parse_ss_multiple_and_empty_lines():
    output = """
tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=900,fd=3))

tcp LISTEN 0 511 *:80 *:* users:(("nginx",pid=1200,fd=6))
"""
    result = parse_ss(output)
    assert len(result) == 2
    assert result[0].port == 22
    assert result[0].process == "sshd"
    assert result[1].port == 80
    assert result[1].process == "nginx"


def test_parse_ss_without_process_info():
    output = "tcp LISTEN 0 100 127.0.0.1:6379 0.0.0.0:*\n"
    result = parse_ss(output)
    assert len(result) == 1
    assert result[0].port == 6379
    assert result[0].pid is None
    assert result[0].process is None


def test_parse_ss_ignores_invalid_lines():
    output = """Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port
invalid line that has no port or protocol
random string
"""
    result = parse_ss(output)
    assert len(result) == 0


def test_port_owner_model_instantiation():
    owner = PortOwner(port=5432, protocol="tcp", process="postgres", pid=100)
    assert owner.port == 5432
    assert owner.owner_type == "unknown"
    assert owner.state == "LISTEN"
