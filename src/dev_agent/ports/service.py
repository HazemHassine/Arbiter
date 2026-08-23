from collections.abc import Callable

from dev_agent.config import Settings, get_settings
from dev_agent.models import PortOwner, Project
from dev_agent.ports.scanner import LinuxPortScanner


class PortService:
    def __init__(
        self,
        scanner: LinuxPortScanner | None = None,
        settings: Settings | None = None,
        docker_provider: Callable[[], list] | None = None,
        project_provider: Callable[[], list[Project]] | None = None,
    ) -> None:
        self.scanner = scanner or LinuxPortScanner()
        self.settings = settings or get_settings()
        self.docker_provider = docker_provider
        self.project_provider = project_provider

    def list_used_ports(self) -> list[PortOwner]:
        owners = self.scanner.scan()
        if self.docker_provider:
            try:
                by_port = {(p.port, p.protocol): p for p in owners}
                for container in self.docker_provider():
                    for binding in container.ports:
                        key = (binding.host_port, binding.protocol)
                        current = by_port.get(key)
                        enriched = current or PortOwner(port=binding.host_port, protocol=binding.protocol)
                        enriched.owner_type = "docker_container"
                        enriched.container_id = container.id
                        enriched.container = container.name
                        enriched.project = container.compose_project
                        enriched.service = container.compose_service
                        enriched.source = container.labels.get("com.docker.compose.project.config_files")
                        if not current:
                            owners.append(enriched)
                            by_port[key] = enriched
            except Exception:
                pass
        return sorted(owners, key=lambda item: (item.port, item.protocol))

    def find_port_owner(self, port: int, protocol: str = "tcp") -> PortOwner | None:
        self._validate_port(port)
        return next((item for item in self.list_used_ports() if item.port == port and item.protocol == protocol), None)

    def is_port_available(self, port: int, protocol: str = "tcp") -> bool:
        return self.find_port_owner(port, protocol) is None

    def find_free_port(self, preferred_port: int) -> int:
        self._validate_port(preferred_port)
        used = {item.port for item in self.list_used_ports()}
        end = self.settings.default_port_search_range_end
        for port in range(preferred_port, end + 1):
            if port not in used:
                return port
        for port in range(self.settings.default_port_search_range_start, preferred_port):
            if port not in used:
                return port
        raise RuntimeError("No free port in configured range")

    def find_free_ports(self, start: int, end: int, count: int = 1) -> list[int]:
        self._validate_port(start)
        self._validate_port(end)
        if start > end or not 1 <= count <= 1000:
            raise ValueError("Invalid range or count")
        used = {item.port for item in self.list_used_ports()}
        return [port for port in range(start, end + 1) if port not in used][:count]

    def detect_port_conflicts(self) -> list[dict[str, object]]:
        if not self.project_provider:
            return []
        claims: dict[tuple[int, str], list[dict[str, str]]] = {}
        for project in self.project_provider():
            for binding in project.ports:
                claims.setdefault((binding.host_port, binding.protocol), []).append(
                    {
                        "project": project.name,
                        "project_id": project.id,
                        "service": binding.service or "unknown",
                        "source": binding.source or "unknown",
                    }
                )
        runtime = {(item.port, item.protocol): item for item in self.list_used_ports()}
        conflicts = []
        for key, value in sorted(claims.items()):
            owner = runtime.get(key)
            owner_projects = {claim["project"] for claim in value} | {claim["project_id"] for claim in value}
            external_owner = owner if owner and owner.project not in owner_projects else None
            if len(value) > 1 or external_owner:
                conflict: dict[str, object] = {"port": key[0], "protocol": key[1], "claims": value}
                if external_owner:
                    conflict["runtime_owner"] = external_owner.model_dump(mode="json")
                conflicts.append(conflict)
        return conflicts

    @staticmethod
    def _validate_port(port: int) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
