import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from arbiter.agent.service import AgentService
from arbiter.cli.picker import pick_approval, pick_container, pick_project
from arbiter.config import get_settings
from arbiter.security import validate_bind_host
from arbiter.services import build_services

app = typer.Typer(help="Arbiter: safe local environment understanding and reconciliation.", no_args_is_help=True)
config_app = typer.Typer(help="Configuration, .env, and secrets intelligence.", no_args_is_help=True)
app.add_typer(config_app, name="config")
prompt_app = typer.Typer(help="Shell prompt and Starship integration.", invoke_without_command=True)
app.add_typer(prompt_app, name="prompt")


def services():
    return build_services(get_settings())


def emit(value) -> None:
    typer.echo(json.dumps(value, indent=2, default=str, ensure_ascii=False))


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
def inspect_project(
    identifier: Annotated[str | None, typer.Argument(help="Registered project identifier or path")] = None,
) -> None:
    """Inspect a registered project. Opens fuzzy picker if identifier is omitted."""
    svc = services().projects
    if not identifier:
        available = svc.list_projects()
        if not available:
            raise typer.BadParameter("No registered projects found. Use 'arbiter register <path>' first.")
        selected = pick_project(available, prompt="Select Project to Inspect")
        if not selected:
            raise typer.BadParameter("No project selected.")
        identifier = selected.id

    emit(svc.refresh_project(identifier).model_dump(mode="json"))


@app.command()
def register(path: Path) -> None:
    """Register one explicit project directory."""
    emit(services().projects.register_project(path).model_dump(mode="json"))


@app.command()
def prepare(
    identifier: Annotated[str | None, typer.Argument(help="Registered project identifier or directory name")] = None,
) -> None:
    """Inspect and safely propose preparation of a project. Opens fuzzy picker if omitted."""
    svc = services().projects
    if not identifier:
        available = svc.list_projects()
        if not available:
            raise typer.BadParameter("No registered projects found. Use 'arbiter register <path>' first.")
        selected = pick_project(available, prompt="Select Project to Prepare")
        if not selected:
            raise typer.BadParameter("No project selected.")
        identifier = selected.id

    emit(AgentService(services()).prepare_project(identifier=identifier))


@config_app.command("drift")
def config_drift(identifier: Annotated[str | None, typer.Argument(help="Optional project name or ID")] = None) -> None:
    """Audit project(s) for port drifts and missing variables."""
    svc = services().config_intelligence
    if identifier:
        emit(svc.audit_project_config(identifier).model_dump(mode="json"))
    else:
        emit([item.model_dump(mode="json") for item in svc.audit_all_projects()])


@config_app.command("audit")
def config_audit(identifier: Annotated[str | None, typer.Argument(help="Optional project name or ID")] = None) -> None:
    """Safe secrets and environment auditing (masked credentials)."""
    svc = services().config_intelligence
    if identifier:
        report = svc.audit_project_config(identifier)
        emit(
            {
                "project": report.project_name,
                "status": report.status,
                "drift_score": report.drift_score,
                "env_audit": [v.model_dump(mode="json") for v in report.env_audit],
                "recommendations": report.recommendations,
            }
        )
    else:
        reports = svc.audit_all_projects()
        emit(
            [
                {
                    "project": r.project_name,
                    "status": r.status,
                    "drift_score": r.drift_score,
                    "missing_count": len(r.missing_env_vars),
                    "port_drifts_count": len(r.port_drifts),
                }
                for r in reports
            ]
        )


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
def logs(
    identifier: Annotated[str | None, typer.Argument(help="Container identifier or name")] = None,
    tail: int = 200,
) -> None:
    """Read bounded container logs. Opens fuzzy container selector if omitted."""
    docker_svc = services().docker
    if not identifier:
        available = docker_svc.list_containers()
        if not available:
            raise typer.BadParameter("No Docker containers found.")
        selected = pick_container(available, prompt="Select Container for Logs")
        if not selected:
            raise typer.BadParameter("No container selected.")
        identifier = selected.id

    typer.echo(docker_svc.logs(identifier, tail))


@app.command()
def disk() -> None:
    """Show structured Docker disk usage."""
    emit(services().docker.disk_usage())


@app.command()
def approve(
    approval_id: Annotated[str | None, typer.Argument(help="Pending action approval ID")] = None,
) -> None:
    """Approve and execute exactly one persisted action. Opens fuzzy selector if omitted."""
    action_svc = services().actions
    if not approval_id:
        pending = [a for a in action_svc.approvals.list() if a.status == "pending"]
        if not pending:
            raise typer.BadParameter("No pending approvals found.")
        selected = pick_approval(pending, prompt="Select Pending Approval to Execute")
        if not selected:
            raise typer.BadParameter("No approval selected.")
        approval_id = selected.id

    emit(action_svc.approve_and_execute(approval_id).model_dump(mode="json"))


@app.command()
def tui() -> None:
    """Launch the interactive Terminal UI (lazydocker/k9s style)."""
    from arbiter.tui.app import run_tui

    run_tui(services())


@prompt_app.callback(invoke_without_command=True)
def prompt_status(
    ctx: typer.Context,
    format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: pill, starship, json, plain, short"),
    ] = "pill",
    color: Annotated[bool, typer.Option("--color/--no-color", help="Enable/disable ANSI colors")] = True,
    status_only: Annotated[
        bool,
        typer.Option("--status-only", help="Exit code 0 if healthy, 1 if warnings/conflicts"),
    ] = False,
) -> None:
    """Output shell prompt status pill."""
    if ctx.invoked_subcommand is not None:
        return
    from arbiter.cli.prompt import format_prompt_status, get_prompt_status

    status = get_prompt_status(services())
    output = format_prompt_status(status, output_format=format, color=color)
    typer.echo(output)
    if status_only and status.status != "ok":
        raise typer.Exit(code=1)


@prompt_app.command("init")
def prompt_init(
    shell: Annotated[
        str,
        typer.Argument(help="Shell or tool type: starship, zsh, bash, fish"),
    ] = "starship",
) -> None:
    """Generate shell prompt hook configuration snippet."""
    from arbiter.cli.prompt import generate_shell_init

    try:
        snippet = generate_shell_init(shell)
        typer.echo(snippet)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("mcp")
def mcp_server() -> None:
    """Run the optional stdio MCP server."""
    from arbiter.integrations.mcp.server import main as run_mcp

    run_mcp()


stack_app = typer.Typer(help="Manage and switch multi-project stack presets.", no_args_is_help=True)
app.add_typer(stack_app, name="stack")


@stack_app.command("list")
def stack_list(seed_defaults: bool = False) -> None:
    """List all configured stack presets."""
    svc = services().stacks
    if seed_defaults:
        svc.seed_default_presets()
    emit([item.model_dump(mode="json") for item in svc.list_stacks()])


@stack_app.command("inspect")
def stack_inspect(identifier: str) -> None:
    """Inspect a stack preset details, projects, and active status."""
    emit(services().stacks.get_stack(identifier).model_dump(mode="json"))


@stack_app.command("boot-order")
def stack_boot_order(identifier: str) -> None:
    """Show computed topological boot order and readiness gates for a stack preset."""
    stack = services().stacks.get_stack(identifier)
    emit(services().stacks.compute_boot_plan(stack).model_dump(mode="json"))


@stack_app.command("readiness")
def stack_readiness(identifier: str) -> None:
    """Check live readiness gates for all projects in a stack preset."""
    emit([item.model_dump(mode="json") for item in services().stacks.check_stack_readiness(identifier)])


@stack_app.command("switch")
def stack_switch(
    identifier: str,
    hibernate: bool = True,
    wait: bool = True,
    resolve_ports: bool = True,
) -> None:
    """1-Click switch environment context to a target stack preset."""
    emit(
        services()
        .stacks.switch_stack(
            identifier,
            hibernate_current=hibernate,
            wait_for_readiness=wait,
            resolve_port_conflicts=resolve_ports,
        )
        .model_dump(mode="json")
    )


@stack_app.command("stop")
def stack_stop(identifier: str, hibernate: bool = True) -> None:
    """Stop or hibernate all projects in a stack preset."""
    emit(services().stacks.stop_stack(identifier, hibernate=hibernate))


@stack_app.command("create")
def stack_create(
    name: str,
    description: str | None = None,
    projects: Annotated[list[str] | None, typer.Option(help="Project names/IDs to include")] = None,
) -> None:
    """Create a new stack preset."""
    proj_members = [{"project_id": p, "project_name": p} for p in (projects or [])]
    emit(
        services()
        .stacks.create_stack(name=name, description=description, projects=proj_members)
        .model_dump(mode="json")
    )


def main() -> None:
    app()
