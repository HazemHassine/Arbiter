import re
from pathlib import Path
from typing import Any

import yaml

from dev_agent.models import PortBinding

PORT_RE = re.compile(r"^(?:(?P<host_ip>[^:]+):)?(?P<host>\d+):(?P<container>\d+)(?:/(?P<proto>tcp|udp))?$")
VARIABLE_RE = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]+))?}")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def resolve_variables(value: str, env: dict[str, str]) -> str:
    return VARIABLE_RE.sub(lambda match: env.get(match.group("name"), match.group("default") or match.group(0)), value)


def parse_port(value: str | int | dict[str, Any], env: dict[str, str] | None = None) -> PortBinding | None:
    if isinstance(value, int):
        return PortBinding(host_port=value, container_port=value)
    if isinstance(value, dict):
        published, target = value.get("published"), value.get("target")
        if str(published).isdigit() and str(target).isdigit():
            return PortBinding(
                host_port=int(published),
                container_port=int(target),
                protocol=value.get("protocol", "tcp"),
                host_ip=value.get("host_ip"),
            )
        return None
    raw_value = str(value)
    variable_match = VARIABLE_RE.search(raw_value)
    rendered = resolve_variables(raw_value, env or {})
    match = PORT_RE.match(rendered.strip().strip("\"'"))
    if not match:
        return None
    return PortBinding(
        host_port=int(match.group("host")),
        container_port=int(match.group("container")),
        protocol=match.group("proto") or "tcp",
        host_ip=match.group("host_ip"),
        variable=variable_match.group("name") if variable_match else None,
    )


def inspect_compose(path: Path) -> tuple[list[str], list[PortBinding]]:
    data = yaml.safe_load(path.read_text()) or {}
    env = load_env(path.parent / ".env")
    services = data.get("services") if isinstance(data, dict) else {}
    if not isinstance(services, dict):
        return [], []
    bindings: list[PortBinding] = []
    for service, config in services.items():
        if not isinstance(config, dict):
            continue
        for value in config.get("ports", []) or []:
            binding = parse_port(value, env)
            if binding:
                binding.service = str(service)
                binding.source = str(path)
                bindings.append(binding)
    return list(services), bindings
