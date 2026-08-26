import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from arbiter.agent.service import AgentService
from arbiter.config import get_settings
from arbiter.security import validate_bind_host
from arbiter.services import build_services

app = typer.Typer(help="Arbiter: safe local environment understanding and reconciliation.", no_args_is_help=True)


def services():
    return build_services(get_settings())


def emit(value) -> None:
    typer.echo(json.dumps(value, indent=2, default=str))


@app.command()
def serve(host: str | None = None, port: int | None = None) -> None:
    """Run the local-only REST API."""
    import uvicorn

    settings = get_settings()
    bind_host = host or settings.arbiter_host
    validate_bind_host(bind_host, settings.allow_remote_access)
    uvicorn.run(
        "arbiter.api.app:app",
        host=bind_host,
        port=port or settings.arbiter_port,
        reload=False,
    )


@app.command()
def ask(message: Annotated[str, typer.Argument(help="Operational question")]) -> None:
    """Ask the deterministic/tool-calling agent."""
    emit(asyncio.run(AgentService(services()).async_query(message)))


@app.command()
def ports(
    free: Annotated[str | None, typer.Option(help="Free-port range, e.g. 3000:4000")] = None, count: int = 10
) -> None:
    """List used ports or deterministic free ports."""
    svc = services().ports
    if free:
        try:
            start, end = (int(value) for value in free.split(":", 1))
        except ValueError as exc:
            raise typer.BadParameter("Range must be START:END") from exc
        emit(svc.find_free_ports(start, end, count))
    else:
        emit([item.model_dump(mode="json") for item in svc.list_used_ports()])


@app.command()
def projects(scan: bool = False) -> None:
    """List registered projects; optionally scan configured roots."""
    svc = services().projects
    items = svc.scan() if scan else svc.list_projects()
    emit([item.model_dump(mode="json") for item in items])


@app.command("inspect")
def inspect_project(identifier: str) -> None:
    """Inspect a registered project."""
    emit(services().projects.refresh_project(identifier).model_dump(mode="json"))


@app.command()
def register(path: Path) -> None:
    """Register one explicit project directory."""
    emit(services().projects.register_project(path).model_dump(mode="json"))


@app.command()
def prepare(identifier: str) -> None:
    """Inspect and safely propose preparation of a project."""
    emit(AgentService(services()).prepare_project(identifier=identifier))


@app.command()
def containers() -> None:
    """List Docker containers and Compose ownership."""
    emit([item.model_dump(mode="json") for item in services().docker.list_containers()])


@app.command()
def topology(project: str | None = None) -> None:
    """Show the connected, freshly observed workstation topology."""
    emit(services().topology.graph(project).model_dump(mode="json"))


@app.command()
def processes() -> None:
    """List host processes with port and development-runtime evidence."""
    svc = services()
    owners = svc.ports.list_used_ports()
    by_pid: dict[int, list[int]] = {}
    for owner in owners:
        if owner.pid:
            by_pid.setdefault(owner.pid, []).append(owner.port)
    emit(svc.system.processes(by_pid))


@app.command()
def runtimes() -> None:
    """Report detected container runtime capabilities."""
    emit([item.model_dump(mode="json") for item in services().runtimes.list_capabilities()])


@app.command()
def logs(identifier: str, tail: int = 200) -> None:
    """Read bounded container logs."""
    typer.echo(services().docker.logs(identifier, tail))


@app.command()
def disk() -> None:
    """Show structured Docker disk usage."""
    emit(services().docker.disk_usage())


@app.command()
def approve(approval_id: str) -> None:
    """Approve and execute exactly one persisted action."""
    emit(services().actions.approve_and_execute(approval_id).model_dump(mode="json"))


@app.command("mcp")
def mcp_server() -> None:
    """Run the optional stdio MCP server."""
    from arbiter.integrations.mcp.server import main as run_mcp

    run_mcp()


def main() -> None:
    app()
