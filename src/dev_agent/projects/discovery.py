from pathlib import Path

from dev_agent.compose.parser import inspect_compose
from dev_agent.models import Project
from dev_agent.security import safe_project_path

COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
PROJECT_MARKERS = (*COMPOSE_NAMES, "Makefile", "Dockerfile", "pyproject.toml", "package.json", ".git")


def inspect_project(path: Path, roots: list[Path] | None = None) -> Project:
    root = safe_project_path(path, roots)
    compose_files = [root / name for name in COMPOSE_NAMES if (root / name).is_file()]
    services: list[str] = []
    ports = []
    for file in compose_files:
        parsed_services, parsed_ports = inspect_compose(file)
        services.extend(service for service in parsed_services if service not in services)
        ports.extend(parsed_ports)
    return Project(
        name=root.name,
        path=root,
        compose_files=compose_files,
        has_makefile=(root / "Makefile").is_file(),
        has_env=(root / ".env").is_file(),
        has_dockerfile=(root / "Dockerfile").is_file(),
        ports=ports,
        services=services,
    )


def discover_projects(roots: list[Path]) -> list[Project]:
    projects: list[Project] = []
    seen: set[Path] = set()
    for configured_root in roots:
        root = configured_root.expanduser().resolve(strict=False)
        if not root.is_dir():
            continue
        candidates = [root, *(item for item in root.iterdir() if item.is_dir() and not item.name.startswith("."))]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen or not any((resolved / marker).exists() for marker in PROJECT_MARKERS):
                continue
            seen.add(resolved)
            try:
                projects.append(inspect_project(resolved, roots))
            except (OSError, ValueError):
                continue
    return projects
