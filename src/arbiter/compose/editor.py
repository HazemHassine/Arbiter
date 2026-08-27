import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from arbiter.compose.parser import load_env, parse_port
from arbiter.config import get_settings
from arbiter.system.processes import run


def _secure_backup(path: Path, backup_root: Path | None = None) -> Path:
    directory = backup_root or get_settings().arbiter_state_directory.expanduser() / "backups" / "configuration"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    backup = directory / f"{stamp}-{uuid4()}-{path.name}"
    shutil.copy2(path, backup)
    backup.chmod(0o600)
    return backup


class ComposeEditor:
    def __init__(self, backup_root: Path | None = None) -> None:
        self.backup_root = backup_root

    def change_service_host_port(
        self, compose_file: Path, service: str, old_port: int, new_port: int, validate: bool = True
    ) -> dict[str, str | int]:
        path = compose_file.resolve(strict=True)
        if path.name not in {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}:
            raise ValueError("Not a recognized Compose file")
        data = yaml.safe_load(path.read_text()) or {}
        services = data.get("services", {})
        if service not in services:
            raise LookupError(f"Compose service not found: {service}")
        ports = services[service].get("ports", []) or []
        changed = False
        env = load_env(path.parent / ".env")
        for index, value in enumerate(ports):
            binding = parse_port(value, env)
            if not binding or binding.host_port != old_port:
                continue
            if isinstance(value, dict):
                value["published"] = new_port
            elif isinstance(value, int):
                ports[index] = f"{new_port}:{value}"
            else:
                raw = str(value)
                if "${" in raw:
                    raise ValueError("Port is environment-driven; edit its explicit .env variable instead")
                prefix = f"{binding.host_ip}:" if binding.host_ip else ""
                suffix = f"/{binding.protocol}" if "/" in raw else ""
                ports[index] = f"{prefix}{new_port}:{binding.container_port}{suffix}"
            changed = True
            break
        if not changed:
            raise LookupError(f"Host port {old_port} not found for service {service}")
        backup = _secure_backup(path, self.backup_root)
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        if validate:
            result = run(["docker", "compose", "-f", str(path), "config"], cwd=path.parent, timeout=30)
            if result.returncode:
                shutil.copy2(backup, path)
                raise RuntimeError(f"Compose validation failed; restored backup: {result.stderr.strip()}")
        return {
            "file": str(path),
            "backup": str(backup),
            "service": service,
            "old_host_port": old_port,
            "new_host_port": new_port,
        }


def change_env_port(
    env_file: Path,
    variable: str,
    old_port: int,
    new_port: int,
    backup_root: Path | None = None,
) -> dict[str, str | int]:
    path = env_file.resolve(strict=True)
    if path.name != ".env":
        raise ValueError("Only a project .env file may be edited")
    lines = path.read_text().splitlines()
    match_index = None
    for index, line in enumerate(lines):
        if line.startswith(f"{variable}=") and line.split("=", 1)[1].strip() == str(old_port):
            match_index = index
            break
    if match_index is None:
        raise LookupError(f"Explicit {variable}={old_port} not found")
    backup = _secure_backup(path, backup_root)
    lines[match_index] = f"{variable}={new_port}"
    path.write_text("\n".join(lines) + "\n")
    return {"file": str(path), "backup": str(backup), "variable": variable, "old_port": old_port, "new_port": new_port}
