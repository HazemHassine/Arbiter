"""Optional MCP adapter. Install with ``uv sync --extra mcp``."""

from arbiter import __version__
from arbiter.agent.service import AgentService
from arbiter.config import get_settings
from arbiter.services import build_services


def create_server():
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError("MCP support is optional; install the 'mcp' extra") from exc

    services = build_services(get_settings())
    agent = AgentService(services)
    server = MCPServer("arbiter", version=__version__)

    @server.tool(name="ports_list")
    def ports_list() -> list[dict]:
        """List actual local listening ports and their correlated owners."""
        return [item.model_dump(mode="json") for item in services.ports.list_used_ports()]

    @server.tool(name="ports_find_owner")
    def ports_find_owner(port: int) -> dict:
        """Find the process or Docker container that owns a port."""
        owner = services.ports.find_port_owner(port)
        return owner.model_dump(mode="json") if owner else {"port": port, "available": True}

    @server.tool(name="ports_find_free")
    def ports_find_free(preferred_port: int) -> int:
        """Find a deterministic free port at or above the preferred port."""
        return services.ports.find_free_port(preferred_port)

    @server.tool(name="ports_detect_conflicts")
    def ports_detect_conflicts() -> list[dict]:
        """Find registered port claims that conflict with projects or runtime owners."""
        return services.ports.detect_port_conflicts()

    @server.tool(name="projects_list")
    def projects_list() -> list[dict]:
        """List registered development projects."""
        return [item.model_dump(mode="json") for item in services.projects.list_projects()]

    @server.tool(name="arbiter_prepare_project")
    def prepare_project(identifier: str) -> dict:
        """Inspect, detect conflicts, and propose approved project preparation."""
        return agent.prepare_project(identifier=identifier)

    @server.tool(name="project_reconciliation_plan")
    def project_reconciliation_plan(identifier: str) -> dict:
        """Build a read-only deterministic port repair plan for one project."""
        project = services.projects.refresh_project(identifier)
        return services.ports.plan_port_reconciliation(project).model_dump(mode="json")

    @server.tool(name="docker_list_containers")
    def docker_list_containers() -> list[dict]:
        """List local Docker containers with Compose metadata."""
        return [item.model_dump(mode="json") for item in services.docker.list_containers()]

    @server.tool(name="topology_get")
    def topology_get() -> dict:
        """Get the connected, freshly observed workstation resource topology."""
        return services.topology.graph().model_dump(mode="json")

    @server.tool(name="resource_inspect")
    def resource_inspect(resource_type: str, resource_id: str) -> dict:
        """Inspect a resource and its direct topology relationships."""
        return services.topology.inspect_resource(resource_type, resource_id).model_dump(mode="json")

    @server.tool(name="processes_list")
    def processes_list() -> list[dict]:
        """List host processes with listening-port and heuristic runtime evidence."""
        owners = services.ports.list_used_ports()
        by_pid: dict[int, list[int]] = {}
        for owner in owners:
            if owner.pid:
                by_pid.setdefault(owner.pid, []).append(owner.port)
        return services.system.processes(by_pid)

    return server


def main() -> None:
    create_server().run()
