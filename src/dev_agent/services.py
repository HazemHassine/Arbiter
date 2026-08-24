from dataclasses import dataclass

from dev_agent.actions.service import ActionService
from dev_agent.config import Settings
from dev_agent.docker.service import DockerService
from dev_agent.events.service import EventBus, ObservationService
from dev_agent.files.service import FileService
from dev_agent.impact.service import ImpactService
from dev_agent.persistence.database import Database
from dev_agent.ports.service import PortService
from dev_agent.projects.service import ProjectService
from dev_agent.runtimes.service import RuntimeService
from dev_agent.system.service import SystemService
from dev_agent.telemetry import TelemetryRegistry
from dev_agent.topology.service import TopologyService


@dataclass
class Services:
    settings: Settings
    database: Database
    projects: ProjectService
    docker: DockerService
    ports: PortService
    actions: ActionService
    system: SystemService
    topology: TopologyService
    files: FileService
    impact: ImpactService
    runtimes: RuntimeService
    events: EventBus
    telemetry: TelemetryRegistry
    observer: ObservationService | None = None


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
    system = SystemService()
    files = FileService(database, projects)
    topology = TopologyService(projects, docker_service, ports, system)
    impact = ImpactService(topology)
    actions = ActionService(database, projects, ports, docker_service, settings, files=files, impact=impact)
    services = Services(
        settings,
        database,
        projects,
        docker_service,
        ports,
        actions,
        system,
        topology,
        files,
        impact,
        RuntimeService(docker_service),
        EventBus(),
        TelemetryRegistry(),
    )
    services.observer = ObservationService(services, services.events, settings.observation_interval_seconds)
    return services
