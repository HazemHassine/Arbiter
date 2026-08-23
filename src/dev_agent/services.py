from dataclasses import dataclass

from dev_agent.actions.service import ActionService
from dev_agent.config import Settings
from dev_agent.docker.service import DockerService
from dev_agent.persistence.database import Database
from dev_agent.ports.service import PortService
from dev_agent.projects.service import ProjectService
from dev_agent.system.service import SystemService


@dataclass
class Services:
    settings: Settings
    database: Database
    projects: ProjectService
    docker: DockerService
    ports: PortService
    actions: ActionService
    system: SystemService


def build_services(settings: Settings, docker: DockerService | None = None, scanner=None) -> Services:
    database = Database(settings)
    database.create_all()
    projects = ProjectService(database, settings)
    docker_service = docker or DockerService()
    ports = PortService(
        scanner=scanner,
        settings=settings,
        docker_provider=docker_service.list_containers,
        project_provider=projects.list_projects,
    )
    actions = ActionService(database, projects, ports, docker_service, settings)
    return Services(settings, database, projects, docker_service, ports, actions, SystemService())
