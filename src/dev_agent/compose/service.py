from pathlib import Path

from dev_agent.compose.parser import inspect_compose
from dev_agent.system.processes import run


class ComposeService:
    def validate(self, file: Path) -> dict[str, object]:
        result = run(["docker", "compose", "-f", str(file), "config"], cwd=file.parent, timeout=30)
        return {"valid": result.returncode == 0, "output": result.stdout, "error": result.stderr}

    def start(self, file: Path) -> dict[str, object]:
        result = run(["docker", "compose", "-f", str(file), "up", "-d"], cwd=file.parent, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return {"started": True, "output": result.stdout or result.stderr}

    def stop(self, file: Path) -> dict[str, object]:
        result = run(["docker", "compose", "-f", str(file), "stop"], cwd=file.parent, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return {"stopped": True, "output": result.stdout or result.stderr}

    def restart(self, file: Path) -> dict[str, object]:
        result = run(["docker", "compose", "-f", str(file), "restart"], cwd=file.parent, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return {"restarted": True, "output": result.stdout or result.stderr}

    def restart_service(self, file: Path, service: str) -> dict[str, object]:
        known, _ = inspect_compose(file)
        if service not in known:
            raise LookupError(f"Unknown service: {service}")
        result = run(["docker", "compose", "-f", str(file), "restart", service], cwd=file.parent, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return {"restarted": service, "output": result.stdout or result.stderr}

    def recreate_service(self, file: Path, service: str) -> dict[str, object]:
        known, _ = inspect_compose(file)
        if service not in known:
            raise LookupError(f"Unknown service: {service}")
        result = run(
            ["docker", "compose", "-f", str(file), "up", "-d", "--force-recreate", service],
            cwd=file.parent,
            timeout=180,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return {"recreated": service, "output": result.stdout or result.stderr}
