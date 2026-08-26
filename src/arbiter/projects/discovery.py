import os
from collections import deque
from pathlib import Path

from arbiter.compose.parser import inspect_compose
from arbiter.models import Project
from arbiter.security import safe_project_path

COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
PROJECT_MARKERS = (*COMPOSE_NAMES, "Makefile", "Dockerfile", "pyproject.toml", "package.json", ".git")
IGNORED_DISCOVERY_DIRECTORIES = {
    ".cache",
    ".arbiter",
    ".dev-agent",
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}


def find_project_root(path: Path, max_parents: int = 6) -> Path | None:
    """Find a nearby project marker without recursively scanning the disk."""
    try:
        current = path.expanduser().resolve(strict=True)
    except OSError:
        return None
    if current.is_file():
        current = current.parent
    for _ in range(max_parents + 1):
        try:
            if any((current / marker).exists() for marker in PROJECT_MARKERS):
                return current
        except OSError:
            return None
        if current.parent == current:
            break
        current = current.parent
    return None


def project_dockerfiles(root: Path) -> list[Path]:
    """Find Dockerfiles only in a small project-local depth, never globally."""
    found: list[Path] = []
    ignored = {".git", ".venv", "node_modules", ".arbiter", ".dev-agent", "__pycache__"}
    for directory, subdirs, files in os.walk(root):
        current = Path(directory)
        relative = current.relative_to(root)
        if len(relative.parts) > 3:
            subdirs[:] = []
            continue
        subdirs[:] = [name for name in subdirs if name not in ignored and not name.startswith(".")]
        for name in files:
            if name == "Dockerfile" or name.startswith("Dockerfile."):
                found.append(current / name)
    return sorted(found)


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
        dockerfiles=project_dockerfiles(root),
        ports=ports,
        services=services,
    )


def discover_projects(roots: list[Path], max_depth: int = 4) -> list[Project]:
    """Discover project roots below configured folders with a strict depth bound.

    Discovery stops descending as soon as a project marker is found. This keeps
    monorepos as one project when their root is marked and avoids accidentally
    indexing generated dependency trees.
    """
    projects: list[Project] = []
    seen: set[Path] = set()
    for configured_root in roots:
        root = configured_root.expanduser().resolve(strict=False)
        if not root.is_dir():
            continue
        candidates: deque[tuple[Path, int]] = deque([(root, 0)])
        while candidates:
            candidate, depth = candidates.popleft()
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if resolved in seen:
                continue
            has_marker = any((resolved / marker).exists() for marker in PROJECT_MARKERS)
            if has_marker:
                seen.add(resolved)
                try:
                    projects.append(inspect_project(resolved, roots))
                except (OSError, ValueError):
                    continue
                continue
            if depth >= max_depth:
                continue
            try:
                children = sorted(
                    (
                        item
                        for item in resolved.iterdir()
                        if item.is_dir()
                        and not item.is_symlink()
                        and item.name not in IGNORED_DISCOVERY_DIRECTORIES
                        and not item.name.startswith(".")
                    ),
                    key=lambda item: item.name.casefold(),
                )
            except OSError:
                continue
            candidates.extend((child, depth + 1) for child in children)
    return sorted(projects, key=lambda project: str(project.path).casefold())
