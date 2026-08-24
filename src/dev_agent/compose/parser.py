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


def inspect_compose_details(path: Path) -> dict[str, dict[str, Any]]:
    """Return the topology-relevant, non-executing subset of a Compose file.

    The result intentionally keeps unknown Compose fields out of the domain layer.
    It is evidence for visualization and diagnostics, not a replacement for
    ``docker compose config``.
    """
    data = yaml.safe_load(path.read_text(errors="replace")) or {}
    raw_services = data.get("services") if isinstance(data, dict) else {}
    if not isinstance(raw_services, dict):
        return {}
    env = load_env(path.parent / ".env")
    details: dict[str, dict[str, Any]] = {}
    for raw_name, raw_config in raw_services.items():
        if not isinstance(raw_config, dict):
            continue
        name = str(raw_name)
        build = raw_config.get("build")
        if isinstance(build, str):
            build_context, dockerfile = build, "Dockerfile"
        elif isinstance(build, dict):
            build_context, dockerfile = build.get("context", "."), build.get("dockerfile", "Dockerfile")
        else:
            build_context, dockerfile = None, None
        depends = raw_config.get("depends_on") or []
        if isinstance(depends, dict):
            depends = list(depends)
        volumes = raw_config.get("volumes") or []
        networks = raw_config.get("networks") or []
        if isinstance(networks, dict):
            networks = list(networks)
        bindings = [binding for value in raw_config.get("ports", []) or [] if (binding := parse_port(value, env))]
        for binding in bindings:
            binding.service = name
            binding.source = str(path)
        details[name] = {
            "name": name,
            "image": raw_config.get("image"),
            "build_context": str(build_context) if build_context is not None else None,
            "dockerfile": str(dockerfile) if dockerfile is not None else None,
            "depends_on": [str(item) for item in depends],
            "ports": bindings,
            "volumes": [str(item) if not isinstance(item, dict) else item for item in volumes],
            "networks": [str(item) for item in networks],
            "restart": raw_config.get("restart"),
            "command": raw_config.get("command"),
        }
    return details
