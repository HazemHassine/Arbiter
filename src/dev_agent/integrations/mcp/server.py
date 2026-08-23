"""Optional MCP adapter. Install with ``uv sync --extra mcp``."""

from dev_agent.agent.service import AgentService
from dev_agent.config import get_settings
from dev_agent.services import build_services


def create_server():
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError("MCP support is optional; install the 'mcp' extra") from exc

    services = build_services(get_settings())
    agent = AgentService(services)
    server = MCPServer("local-dev-environment", version="0.1.0")

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

    @server.tool(name="dev_environment_prepare_project")
    def prepare_project(identifier: str) -> dict:
        """Inspect, detect conflicts, and propose approved project preparation."""
        return agent.prepare_project(identifier=identifier)

    @server.tool(name="docker_list_containers")
    def docker_list_containers() -> list[dict]:
        """List local Docker containers with Compose metadata."""
        return [item.model_dump(mode="json") for item in services.docker.list_containers()]

    return server


def main() -> None:
    create_server().run()
