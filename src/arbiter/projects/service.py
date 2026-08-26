from pathlib import Path

from arbiter.compose.parser import load_env
from arbiter.config import Settings, get_settings
from arbiter.models import Project
from arbiter.persistence.database import Database
from arbiter.persistence.repositories import ProjectRepository
from arbiter.projects.discovery import discover_projects, inspect_project
from arbiter.security import redact


class ProjectService:
    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings or get_settings()

    def list_projects(self) -> list[Project]:
        with self.database.sessions() as session:
            return ProjectRepository(session).list()

    def register_project(self, path: Path) -> Project:
        # Explicit registration is itself the user's authorization for this directory.
        # Configured roots constrain only automatic scanning.
        project = inspect_project(path)
        with self.database.sessions() as session:
            return ProjectRepository(session).save(project)

    def unregister_project(self, identifier: str) -> bool:
        with self.database.sessions() as session:
            return ProjectRepository(session).delete(identifier)

    def get_project(self, identifier: str) -> Project:
        with self.database.sessions() as session:
            project = ProjectRepository(session).get(identifier)
        if not project:
            raise LookupError(f"Project not found: {identifier}")
        return project

    def refresh_project(self, identifier: str) -> Project:
        current = self.get_project(identifier)
        discovered = inspect_project(current.path)
        discovered.id = current.id
        with self.database.sessions() as session:
            return ProjectRepository(session).save(discovered)

    def scan(self) -> list[Project]:
        found = discover_projects(self.settings.project_roots, self.settings.project_scan_depth)
        with self.database.sessions() as session:
            repository = ProjectRepository(session)
            return [repository.save(item) for item in found]

    def get_environment(self, identifier: str) -> dict[str, str]:
        project = self.get_project(identifier)
        return redact(load_env(project.path / ".env"))
