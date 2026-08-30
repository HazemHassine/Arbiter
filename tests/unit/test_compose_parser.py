from arbiter.compose.parser import inspect_compose, load_env, parse_port, resolve_variables


def test_load_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("""
# Comment line
PORT=8080
DB_HOST="localhost"
API_SECRET='secret-value'
EMPTY=
INVALID_LINE_NO_EQUALS
""")
    env = load_env(env_file)
    assert env["PORT"] == "8080"
    assert env["DB_HOST"] == "localhost"
    assert env["API_SECRET"] == "secret-value"
    assert env["EMPTY"] == ""
    assert "INVALID_LINE_NO_EQUALS" not in env


def test_resolve_variables():
    env = {"APP_PORT": "3000", "HOST": "127.0.0.1"}
    assert resolve_variables("${APP_PORT}:80", env) == "3000:80"
    assert resolve_variables("${UNDEFINED:-8000}:80", env) == "8000:80"
    assert resolve_variables("${HOST}:${APP_PORT}", env) == "127.0.0.1:3000"


def test_parse_port_formats():
    # String format
    b1 = parse_port("8000:80")
    assert b1.host_port == 8000
    assert b1.container_port == 80
    assert b1.protocol == "tcp"

    # With host IP
    b2 = parse_port("127.0.0.1:8080:80")
    assert b2.host_port == 8080
    assert b2.container_port == 80
    assert b2.host_ip == "127.0.0.1"

    # With protocol
    b3 = parse_port("5353:53/udp")
    assert b3.host_port == 5353
    assert b3.container_port == 53
    assert b3.protocol == "udp"

    # Dict format
    b4 = parse_port({"published": 9000, "target": 9000, "protocol": "tcp", "host_ip": "0.0.0.0"})
    assert b4.host_port == 9000
    assert b4.container_port == 9000
    assert b4.host_ip == "0.0.0.0"

    # Environment variable resolution
    b5 = parse_port("${WEB_PORT}:80", env={"WEB_PORT": "4000"})
    assert b5.host_port == 4000
    assert b5.container_port == 80
    assert b5.variable == "WEB_PORT"


def test_inspect_compose_extracts_services_and_ports(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
  worker:
    image: redis:alpine
    ports:
      - "6379:6379"
""")
    services, ports = inspect_compose(compose_file)
    assert services == ["web", "worker"]
    assert len(ports) == 2
    assert {p.host_port for p in ports} == {8080, 6379}
