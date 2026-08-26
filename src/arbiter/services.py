from dataclasses import dataclass

from arbiter.actions.service import ActionService
from arbiter.config import Settings
from arbiter.docker.service import DockerService
from arbiter.events.service import EventBus, ObservationService
from arbiter.files.service import FileService
from arbiter.impact.service import ImpactService
from arbiter.persistence.database import Database
from arbiter.ports.service import PortService
from arbiter.projects.service import ProjectService
from arbiter.runtimes.service import RuntimeService
from arbiter.system.service import SystemService
from arbiter.telemetry import TelemetryRegistry
from arbiter.topology.service import TopologyService


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
