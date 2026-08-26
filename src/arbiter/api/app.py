import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from arbiter import __version__
from arbiter.admin import AdminService
from arbiter.agent.service import AgentService
from arbiter.config import Settings, get_settings
from arbiter.docker.service import DockerUnavailable
from arbiter.integrations.a2a.server import AGENT_CARD
from arbiter.intelligence import IntelligenceService
from arbiter.make.service import MakeService
from arbiter.models import ActionSpec, Risk
from arbiter.persistence.tables import ActionRow
from arbiter.security import redact, redact_action_arguments, validate_bind_host
from arbiter.services import Services, build_services


class AgentQuery(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)


class RegisterProject(BaseModel):
    path: Path


class PrepareProject(BaseModel):
    path: Path | None = None
    resolve_port_conflicts: bool = True
    start: bool = True
    verify: bool = True


class PortSuggestion(BaseModel):
    preferred_port: int = Field(ge=1, le=65535)


class FileChangeRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=1_000_000)
    expected_sha256: str = Field(min_length=64, max_length=64)


class FileUndoRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)


class ComposePortChange(BaseModel):
    service: str = Field(min_length=1, max_length=255)
    old_port: int = Field(ge=1, le=65535)
    new_port: int = Field(ge=1, le=65535)


class ImpactRequest(BaseModel):
    action: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk: Risk = Risk.MEDIUM_RISK
    project_id: str | None = None


class ResourceFilterRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    project: str | None = None
    use_ai: bool = True


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    configured = settings or (services.settings if services else get_settings())
    validate_bind_host(configured.arbiter_host, configured.allow_remote_access)
    service_container = services or build_services(configured)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service_container.database.create_all()
        if service_container.observer:
            await service_container.observer.start()
        try:
            yield
        finally:
            if service_container.observer:
                await service_container.observer.stop()

    app = FastAPI(title="Arbiter", version=__version__, lifespan=lifespan)
    app.state.services = service_container

    @app.middleware("http")
    async def enforce_local_bind(request: Request, call_next):
        server = request.scope.get("server")
        bound_host = str(server[0]) if server else configured.arbiter_host
        if bound_host != "testserver":
            try:
                validate_bind_host(bound_host, configured.allow_remote_access)
            except ValueError as exc:
                return JSONResponse(status_code=403, content={"error": "remote_access_disabled", "detail": str(exc)})
        return await call_next(request)

    @app.middleware("http")
    async def collect_request_metrics(request: Request, call_next):
        started = time.monotonic()
        service_container.telemetry.request_started()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or request.url.path
            service_container.telemetry.request_finished(
                request.method,
                route_path,
                status_code,
                (time.monotonic() - started) * 1000,
            )

    @app.exception_handler(LookupError)
    async def lookup_error(_request: Request, exc: LookupError):
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"error": "invalid_request", "detail": str(exc)})

    @app.exception_handler(DockerUnavailable)
    async def docker_error(_request: Request, exc: DockerUnavailable):
        return JSONResponse(status_code=503, content={"error": "docker_unavailable", "detail": str(exc)})

    def svc(request: Request) -> Services:
        return request.app.state.services

    Dep = Annotated[Services, Depends(svc)]
    router = APIRouter(prefix="/api/v1")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "name": "Arbiter", "version": __version__}

    @app.get("/.well-known/agent-card.json")
    def agent_card() -> dict[str, Any]:
        return AGENT_CARD

    @app.get("/", include_in_schema=False)
    def control_panel() -> RedirectResponse:
        return RedirectResponse("/ui/")

    @router.post("/agent/query")
    async def query(body: AgentQuery, services: Dep) -> dict[str, object]:
        return await AgentService(services).async_query(body.message)

    @router.post("/agent/query/stream")
    async def query_stream(body: AgentQuery, services: Dep) -> StreamingResponse:
        async def frames():
            async for event in AgentService(services).async_query_events(body.message):
                yield json.dumps(redact(event), default=str, separators=(",", ":")) + "\n"

        return StreamingResponse(
            frames(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"},
        )

    @router.get("/ports")
    def ports(services: Dep) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in services.ports.list_used_ports()]

    @router.get("/ports/free")
    def free_ports(
        services: Dep, start: int | None = None, end: int | None = None, count: int = Query(1, ge=1, le=1000)
    ) -> list[int]:
        start = start or services.settings.default_port_search_range_start
        end = end or services.settings.default_port_search_range_end
        return services.ports.find_free_ports(start, end, count)

    @router.get("/ports/conflicts")
    def port_conflicts(services: Dep) -> list[dict[str, object]]:
        return services.ports.detect_port_conflicts()

    @router.post("/ports/suggest")
    def suggest_port(body: PortSuggestion, services: Dep) -> dict[str, int]:
        return {
            "preferred_port": body.preferred_port,
            "suggested_port": services.ports.find_free_port(body.preferred_port),
        }

    @router.get("/ports/{port}")
    @router.get("/ports/{port}/owner")
    def port_owner(port: int, services: Dep) -> dict[str, Any]:
        owner = services.ports.find_port_owner(port)
        return owner.model_dump(mode="json") if owner else {"port": port, "available": True}

    @router.get("/topology")
    def topology(services: Dep, project: str | None = None) -> dict[str, Any]:
        return services.topology.graph(project).model_dump(mode="json")

    @router.get("/topology/project/{identifier}")
    def project_topology(identifier: str, services: Dep) -> dict[str, Any]:
        return services.topology.project_graph(identifier).model_dump(mode="json")

    @router.get("/resources/{resource_type}/{resource_id:path}")
    def resource_inspection(resource_type: str, resource_id: str, services: Dep) -> dict[str, Any]:
        return services.topology.inspect_resource(resource_type, resource_id).model_dump(mode="json")

    @router.get("/search")
    def search_resources(
        services: Dep, q: str = Query(min_length=1, max_length=200), limit: int = Query(30, ge=1, le=100)
    ) -> list[dict[str, Any]]:
        return services.topology.search(q, limit)

    @router.post("/intelligence/filter")
    async def intelligent_filter(body: ResourceFilterRequest, services: Dep) -> dict[str, Any]:
        return await IntelligenceService(services).filter(body.query, project=body.project, use_ai=body.use_ai)

    @router.get("/admin/overview")
    def admin_overview(services: Dep) -> dict[str, Any]:
        return AdminService(services).overview()

    @router.get("/runtimes")
    def runtimes(services: Dep) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in services.runtimes.list_capabilities()]

    @router.get("/activity")
    def activity(services: Dep, limit: int = Query(100, ge=1, le=250)) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in services.events.recent(limit)]

    @router.get("/events/stream")
    async def event_stream(services: Dep) -> StreamingResponse:
        return StreamingResponse(
            services.events.stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/observation")
    def observation_status(services: Dep) -> dict[str, Any]:
        return services.observer.status() if services.observer else {"running": False}

    @router.get("/projects")
    def projects(services: Dep) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in services.projects.list_projects()]

    @router.post("/projects", status_code=201)
    def register(body: RegisterProject, services: Dep) -> dict[str, Any]:
        return services.projects.register_project(body.path).model_dump(mode="json")

    @router.post("/projects/scan")
    def scan(services: Dep) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in services.projects.scan()]

    @router.post("/projects/prepare")
    def prepare_by_path(body: PrepareProject, services: Dep) -> dict[str, object]:
        if not body.path:
            raise HTTPException(422, "path is required")
        return AgentService(services).prepare_project(
            path=body.path, resolve_port_conflicts=body.resolve_port_conflicts, start=body.start, verify=body.verify
        )

    @router.get("/projects/{identifier}/workspace")
    def workspace(identifier: str, services: Dep) -> dict[str, Any]:
        return services.topology.workspace(identifier)

    @router.get("/projects/{identifier}/files")
    def project_files(identifier: str, services: Dep) -> list[dict[str, Any]]:
        project = services.projects.get_project(identifier)
        return [item.model_dump(mode="json") for item in services.files.list_files(project.id)]

    @router.get("/projects/{identifier}/files/content")
    def project_file(identifier: str, services: Dep, path: str = Query(min_length=1)) -> dict[str, Any]:
        project = services.projects.get_project(identifier)
        return services.files.read(project.id, path).model_dump(mode="json")

    @router.post("/projects/{identifier}/files/preview")
    def preview_file_change(identifier: str, body: FileChangeRequest, services: Dep) -> dict[str, Any]:
        project = services.projects.get_project(identifier)
        return services.files.preview(project.id, body.path, body.content, body.expected_sha256).model_dump(mode="json")

    @router.post("/projects/{identifier}/files/save")
    def save_file_change(identifier: str, body: FileChangeRequest, services: Dep) -> dict[str, Any]:
        project = services.projects.get_project(identifier)
        preview = services.files.preview(project.id, body.path, body.content, body.expected_sha256)
        spec = ActionSpec(
            action="file.update",
            risk=Risk.MEDIUM_RISK,
            project_id=project.id,
            summary=f"Apply reviewed edit to {project.name}/{preview.path}",
            arguments={
                "project_id": project.id,
                "path": preview.path,
                "content": body.content,
                "expected_sha256": body.expected_sha256,
            },
        )
        return {"preview": preview.model_dump(mode="json"), **services.actions.propose(spec)}

    @router.post("/projects/{identifier}/files/undo")
    def undo_file_change(identifier: str, body: FileUndoRequest, services: Dep) -> dict[str, Any]:
        project = services.projects.get_project(identifier)
        # Resolving the file now prevents approvals for paths outside the project.
        services.files.read(project.id, body.path)
        spec = ActionSpec(
            action="file.undo",
            risk=Risk.MEDIUM_RISK,
            project_id=project.id,
            summary=f"Undo the last managed edit to {project.name}/{body.path}",
            arguments={"project_id": project.id, "path": body.path},
        )
        return services.actions.propose(spec)

    @router.get("/projects/{identifier}/dockerfiles")
    def dockerfiles(identifier: str, services: Dep) -> list[dict[str, Any]]:
        project = services.projects.refresh_project(identifier)
        return [services.topology.dockerfiles.inspect(path).model_dump(mode="json") for path in project.dockerfiles]

    @router.get("/projects/{identifier}")
    def project(identifier: str, services: Dep) -> dict[str, Any]:
        return services.projects.get_project(identifier).model_dump(mode="json")

    @router.delete("/projects/{identifier}")
    def unregister(identifier: str, services: Dep) -> dict[str, bool]:
        return {"deleted": services.projects.unregister_project(identifier)}

    @router.get("/projects/{identifier}/ports")
    def project_ports(identifier: str, services: Dep) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in services.projects.refresh_project(identifier).ports]

    @router.get("/projects/{identifier}/services")
    def project_services(identifier: str, services: Dep) -> list[str]:
        return services.projects.refresh_project(identifier).services

    @router.get("/projects/{identifier}/status")
    @router.post("/projects/{identifier}/diagnose")
    def diagnose(identifier: str, services: Dep) -> dict[str, object]:
        return AgentService(services).diagnose_project(identifier)

    @router.get("/projects/{identifier}/reconciliation-plan")
    def reconciliation_plan(identifier: str, services: Dep) -> dict[str, Any]:
        project = services.projects.refresh_project(identifier)
        return services.ports.plan_port_reconciliation(project).model_dump(mode="json")

    @router.get("/projects/{identifier}/environment")
    def project_environment(identifier: str, services: Dep) -> dict[str, str]:
        return services.projects.get_environment(identifier)

    @router.post("/projects/{identifier}/prepare")
    @router.post("/projects/{identifier}/resolve-port-conflicts")
    def prepare(identifier: str, body: PrepareProject, services: Dep) -> dict[str, object]:
        return AgentService(services).prepare_project(
            identifier=identifier,
            resolve_port_conflicts=body.resolve_port_conflicts,
            start=body.start,
            verify=body.verify,
        )

    def project_lifecycle(identifier: str, action: str, services: Services) -> dict[str, object]:
        project = services.projects.get_project(identifier)
        action_name = "compose.start" if action == "start" else "compose.stop"
        if action == "restart":
            return {"status": "unsupported", "detail": "Restart services individually or stop/start with approvals"}
        spec = ActionSpec(
            action=action_name,
            risk=Risk.MEDIUM_RISK,
            project_id=project.id,
            summary=f"{action.title()} project {project.name}",
            arguments={"project_id": project.id},
        )
        return services.actions.propose(spec)

    @router.post("/projects/{identifier}/start")
    def start_project(identifier: str, services: Dep) -> dict[str, object]:
        return project_lifecycle(identifier, "start", services)

    @router.post("/projects/{identifier}/stop")
    def stop_project(identifier: str, services: Dep) -> dict[str, object]:
        return project_lifecycle(identifier, "stop", services)

    @router.post("/projects/{identifier}/restart")
    def restart_project(identifier: str, services: Dep) -> dict[str, object]:
        project = services.projects.get_project(identifier)
        spec = ActionSpec(
            action="compose.restart",
            risk=Risk.MEDIUM_RISK,
            project_id=project.id,
            summary=f"Restart project {project.name}",
            arguments={"project_id": project.id},
        )
        return services.actions.propose(spec)

    @router.get("/projects/{identifier}/make/targets")
    def make_targets(identifier: str, services: Dep) -> list[dict[str, object]]:
        project = services.projects.get_project(identifier)
        service = MakeService()
        targets = service.parse_details(project.path / "Makefile")
        return [{"target": name, **item.model_dump(mode="json")} for name, item in targets.items()]

    @router.get("/projects/{identifier}/make/targets/{target}")
    def make_target(identifier: str, target: str, services: Dep) -> dict[str, object]:
        return MakeService().inspect(services.projects.get_project(identifier).path, target)

    @router.post("/projects/{identifier}/make/targets/{target}/run")
    def run_make(identifier: str, target: str, services: Dep) -> dict[str, object]:
        project = services.projects.get_project(identifier)
        inspected = MakeService().inspect(project.path, target)
        spec = ActionSpec(
            action="make.run",
            risk=Risk(inspected["risk"]),
            project_id=project.id,
            summary=f"Run make {target} in {project.name}",
            arguments={"project_id": project.id, "target": target},
        )
        return services.actions.propose(spec)

    @router.get("/containers")
    def containers(services: Dep) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in services.docker.list_containers()]

    @router.get("/containers/{identifier}")
    def container(identifier: str, services: Dep) -> dict[str, Any]:
        return services.docker.inspect_container(identifier).model_dump(mode="json")

    @router.get("/containers/{identifier}/logs")
    def logs(identifier: str, services: Dep, tail: int = Query(200, ge=1, le=5000)) -> dict[str, str]:
        return {"logs": services.docker.logs(identifier, tail)}

    @router.get("/containers/{identifier}/stats")
    def stats(identifier: str, services: Dep) -> dict[str, Any]:
        return services.docker.stats(identifier)

    def mutate_container(identifier: str, action: str, services: Services) -> dict[str, object]:
        risk = Risk.LOW_RISK if action == "start" else Risk.MEDIUM_RISK
        spec = ActionSpec(
            action=f"container.{action}",
            risk=risk,
            summary=f"{action.title()} container {identifier}",
            arguments={"identifier": identifier},
        )
        return services.actions.propose(spec)

    @router.post("/containers/{identifier}/start")
    def start_container(identifier: str, services: Dep) -> dict[str, object]:
        return mutate_container(identifier, "start", services)

    @router.post("/containers/{identifier}/stop")
    def stop_container(identifier: str, services: Dep) -> dict[str, object]:
        return mutate_container(identifier, "stop", services)

    @router.post("/containers/{identifier}/restart")
    def restart_container(identifier: str, services: Dep) -> dict[str, object]:
        return mutate_container(identifier, "restart", services)

    @router.get("/images")
    def images(services: Dep) -> list[dict[str, Any]]:
        return services.docker.list_images()

    @router.get("/images/{identifier}")
    def image(identifier: str, services: Dep) -> dict[str, Any]:
        return services.docker.inspect_image(identifier)

    @router.delete("/images/{identifier}")
    def remove_image(identifier: str, services: Dep) -> dict[str, object]:
        spec = ActionSpec(
            action="image.remove",
            risk=Risk.HIGH_RISK,
            summary=f"Remove unused Docker image {identifier}",
            arguments={"identifier": identifier},
        )
        return services.actions.propose(spec)

    @router.get("/volumes")
    def volumes(services: Dep) -> list[dict[str, Any]]:
        return services.docker.list_volumes()

    @router.get("/volumes/{identifier}")
    def volume(identifier: str, services: Dep) -> dict[str, Any]:
        return services.docker.inspect_volume(identifier)

    @router.delete("/volumes/{identifier}")
    def remove_volume(identifier: str, services: Dep) -> dict[str, object]:
        spec = ActionSpec(
            action="volume.remove",
            risk=Risk.DESTRUCTIVE,
            summary=f"Permanently remove unused Docker volume {identifier}",
            arguments={"identifier": identifier},
        )
        return services.actions.propose(spec)

    @router.get("/networks")
    def networks(services: Dep) -> list[dict[str, Any]]:
        return services.docker.list_networks()

    @router.get("/networks/{identifier}")
    def network(identifier: str, services: Dep) -> dict[str, Any]:
        return services.docker.inspect_network(identifier)

    @router.get("/docker/disk-usage")
    def disk_usage(services: Dep) -> dict[str, Any]:
        return services.docker.disk_usage()

    @router.get("/compose/projects")
    def compose_projects(services: Dep) -> list[dict[str, Any]]:
        projects_by_name: dict[str, dict[str, Any]] = {}
        for item in services.docker.list_containers():
            if item.compose_project:
                current = projects_by_name.setdefault(
                    item.compose_project,
                    {"name": item.compose_project, "containers": [], "working_dir": item.compose_working_dir},
                )
                current["containers"].append(item.model_dump(mode="json"))
        return list(projects_by_name.values())

    @router.get("/compose/projects/{identifier}")
    def compose_project(identifier: str, services: Dep) -> dict[str, Any]:
        project = services.projects.get_project(identifier)
        containers = [
            item.model_dump(mode="json")
            for item in services.docker.list_containers()
            if item.compose_working_dir == str(project.path) or item.compose_project == project.name
        ]
        return {"project": project.model_dump(mode="json"), "containers": containers}

    @router.post("/compose/projects/{identifier}/validate")
    def validate_compose(identifier: str, services: Dep) -> dict[str, object]:
        project = services.projects.get_project(identifier)
        if not project.compose_files:
            raise LookupError("Project has no Compose file")
        return services.actions.compose.validate(project.compose_files[0])

    @router.post("/compose/projects/{identifier}/services/{service}/restart")
    def restart_compose_service(identifier: str, service: str, services: Dep) -> dict[str, object]:
        project = services.projects.get_project(identifier)
        spec = ActionSpec(
            action="compose.restart_service",
            risk=Risk.MEDIUM_RISK,
            project_id=project.id,
            summary=f"Restart {project.name}/{service}",
            arguments={"project_id": project.id, "service": service},
        )
        return services.actions.propose(spec)

    @router.post("/compose/projects/{identifier}/services/port")
    def change_compose_port(identifier: str, body: ComposePortChange, services: Dep) -> dict[str, object]:
        project = services.projects.get_project(identifier)
        spec = ActionSpec(
            action="compose.change_port",
            risk=Risk.MEDIUM_RISK,
            project_id=project.id,
            summary=f"Change {project.name}/{body.service} host port from {body.old_port} to {body.new_port}",
            arguments={"project_id": project.id, **body.model_dump(mode="json")},
        )
        return services.actions.propose(spec)

    @router.post("/impact")
    def impact(body: ImpactRequest, services: Dep) -> dict[str, Any]:
        return services.impact.analyze(
            ActionSpec(
                action=body.action,
                arguments=body.arguments,
                risk=body.risk,
                project_id=body.project_id,
                summary=f"Impact analysis for {body.action}",
            )
        )

    @router.get("/approvals")
    def approvals(services: Dep) -> list[dict[str, Any]]:
        return [_public_approval(item) for item in services.actions.approvals.list()]

    @router.get("/approvals/{approval_id}")
    def approval(approval_id: str, services: Dep) -> dict[str, Any]:
        return _public_approval(services.actions.approvals.get(approval_id))

    @router.post("/approvals/{approval_id}/approve")
    def approve(approval_id: str, services: Dep) -> dict[str, Any]:
        return services.actions.approve_and_execute(approval_id).model_dump(mode="json")

    @router.post("/approvals/{approval_id}/reject")
    def reject(approval_id: str, services: Dep) -> dict[str, Any]:
        return services.actions.approvals.decide(approval_id, False).model_dump(mode="json")

    @router.get("/actions")
    def actions(services: Dep) -> list[dict[str, Any]]:
        with services.database.sessions() as session:
            rows = session.scalars(select(ActionRow).order_by(ActionRow.created_at.desc())).all()
            return [
                {
                    "id": row.id,
                    "request_id": row.request_id,
                    "project_id": row.project_id,
                    "action": row.action,
                    "arguments": redact_action_arguments(row.action, row.arguments),
                    "risk": row.risk,
                    "approval_id": row.approval_id,
                    "status": row.status,
                    "result": row.result,
                    "verification": row.verification,
                    "error": row.error,
                }
                for row in rows
            ]

    @router.get("/system/resources")
    def resources(services: Dep) -> dict[str, object]:
        return services.system.resources()

    @router.get("/system/processes/{pid}")
    def process(pid: int, services: Dep) -> dict[str, object]:
        return services.system.process(pid)

    @router.get("/processes")
    def processes(services: Dep) -> list[dict[str, object]]:
        owners = services.ports.list_used_ports()
        port_by_pid: dict[int, list[int]] = {}
        for owner in owners:
            if owner.pid:
                port_by_pid.setdefault(owner.pid, []).append(owner.port)
        return services.system.processes(port_by_pid)

    @router.get("/processes/{pid}")
    def detailed_process(pid: int, services: Dep) -> dict[str, object]:
        owners = services.ports.list_used_ports()
        return services.system.process(pid, [owner.port for owner in owners if owner.pid == pid])

    @router.get("/system/ports")
    def system_ports(services: Dep) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in services.ports.scanner.scan()]

    app.include_router(router)
    ui_directory = Path(__file__).resolve().parent.parent / "ui" / "out"
    app.mount("/ui", StaticFiles(directory=ui_directory, html=True), name="control-panel")
    return app


def _public_approval(approval) -> dict[str, Any]:
    result = approval.model_dump(mode="json")
    result["arguments"] = redact_action_arguments(approval.action, approval.arguments)
    return result


app = create_app()
