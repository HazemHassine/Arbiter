import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from arbiter.compose.editor import ComposeEditor, change_env_port
from arbiter.compose.service import ComposeService
from arbiter.docker.service import DockerService
from arbiter.files.service import FileService
from arbiter.impact.service import ImpactService
from arbiter.make.service import MakeService
from arbiter.models import ActionResult, ActionSpec
from arbiter.persistence.database import Database
from arbiter.persistence.tables import ActionRow
from arbiter.ports.service import PortService
from arbiter.projects.service import ProjectService
from arbiter.safety.approvals import ApprovalService
from arbiter.safety.policies import needs_approval
from arbiter.security import redact_action_arguments


class ActionService:
    def __init__(
        self,
        database: Database,
        projects: ProjectService,
        ports: PortService,
        docker: DockerService,
        settings,
        *,
        files: FileService | None = None,
        impact: ImpactService | None = None,
        stacks: Any | None = None,
    ) -> None:
        self.database, self.projects, self.ports, self.docker = database, projects, ports, docker
        self.settings = settings
        self.approvals = ApprovalService(database)
        self.compose = ComposeService()
        self.editor = ComposeEditor()
        self.make = MakeService()
        self.files = files
        self.impact = impact
        self.stacks = stacks

    def propose(self, spec: ActionSpec) -> dict[str, object]:
        impact = self.impact.analyze(spec) if self.impact else None
        time_travel = impact.get("time_travel") if impact else None
        if needs_approval(spec.risk, self.settings):
            approval = self.approvals.create(spec)
            public_approval = approval.model_dump(mode="json")
            public_approval["arguments"] = redact_action_arguments(approval.action, approval.arguments)
            if time_travel:
                public_approval["time_travel"] = time_travel
            response: dict[str, object] = {"status": "approval_required", "approval": public_approval}
            if impact:
                response["impact"] = impact
            if time_travel:
                response["time_travel"] = time_travel
            return response
        response = {"status": "completed", "action": self.execute(spec).model_dump(mode="json")}
        if impact:
            response["impact"] = impact
        if time_travel:
            response["time_travel"] = time_travel
        return response

    def approve_and_execute(self, approval_id: str) -> ActionResult:
        approval = self.approvals.decide(approval_id, True)
        spec = ActionSpec(
            request_id=approval.request_id,
            action=approval.action,
            arguments=approval.arguments,
            summary=approval.summary,
            risk=approval.risk,
            project_id=approval.arguments.get("project_id"),
        )
        try:
            return self.execute(spec, approval_id=approval.id)
        finally:
            self.approvals.release_reservations(approval.id)

    def execute(self, spec: ActionSpec, approval_id: str | None = None) -> ActionResult:
        action_id = str(uuid4())
        row = ActionRow(
            id=action_id,
            request_id=spec.request_id,
            project_id=spec.project_id,
            action=spec.action,
            arguments=spec.model_dump(mode="json")["arguments"],
            risk=spec.risk.value,
            approval_id=approval_id,
            status="running",
            result={},
            verification={},
        )
        with self.database.sessions() as session:
            session.add(row)
            session.commit()
        try:
            result, verification = self._dispatch(spec, action_id, approval_id)
            status = "completed" if verification.get("verified") else "verification_failed"
            response = ActionResult(
                id=action_id, action=spec.action, status=status, result=result, verification=verification
            )
        except Exception as exc:
            response = ActionResult(id=action_id, action=spec.action, status="failed", error=str(exc))
        with self.database.sessions() as session:
            stored = session.get(ActionRow, action_id)
            stored.status = response.status
            stored.result = response.result
            stored.verification = response.verification
            stored.error = response.error
            session.commit()
        return response

    def _dispatch(self, spec: ActionSpec, action_id: str, approval_id: str | None = None) -> tuple[dict, dict]:
        args = spec.arguments
        if spec.action.startswith("container."):
            result = self.docker.container_action(args["identifier"], spec.action.split(".", 1)[1])
            return result, {"verified": bool(result.get("verified"))}
        if spec.action in {"compose.start", "compose.stop", "compose.restart"}:
            project, compose_file = self._project_compose(args["project_id"])
            methods = {
                "compose.start": self.compose.start,
                "compose.stop": self.compose.stop,
                "compose.restart": self.compose.restart,
            }
            method = methods[spec.action]
            result = method(compose_file)
            containers = [
                item for item in self.docker.list_containers() if item.compose_working_dir == str(project.path)
            ]
            expected_running = not spec.action.endswith("stop")
            verified = bool(containers) and all((item.state == "running") == expected_running for item in containers)
            return result, {"verified": verified, "containers": [item.model_dump(mode="json") for item in containers]}
        if spec.action == "compose.restart_service":
            project, compose_file = self._project_compose(args["project_id"])
            result = self.compose.restart_service(compose_file, args["service"])
            containers = [
                item
                for item in self.docker.list_containers()
                if item.compose_working_dir == str(project.path) and item.compose_service == args["service"]
            ]
            return result, {"verified": bool(containers) and all(item.state == "running" for item in containers)}
        if spec.action == "compose.change_port":
            project, compose_file = self._project_compose(args["project_id"])
            edit = self.editor.change_service_host_port(
                compose_file, args["service"], int(args["old_port"]), int(args["new_port"])
            )
            try:
                self.compose.recreate_service(compose_file, args["service"])
            except Exception as exc:
                restore_errors = self._restore_edits([edit], compose_file, [args["service"]])
                detail = f"; compensation errors: {'; '.join(restore_errors)}" if restore_errors else ""
                raise RuntimeError(f"Service recreation failed; restored configuration{detail}") from exc
            owner = self.ports.find_port_owner(int(args["new_port"]))
            return edit, {
                "verified": bool(owner),
                "project": project.name,
                "new_port_owner": owner.model_dump(mode="json") if owner else None,
            }
        if spec.action == "project.resolve_ports":
            project, compose_file = self._project_compose(args["project_id"])
            changes = []
            runtime_touched_services: list[str] = []
            try:
                for change in args["changes"]:
                    if Path(change["compose_file"]).resolve() != compose_file.resolve():
                        raise ValueError("Approved Compose path does not match registered project")
                    if change.get("env_variable"):
                        edit = change_env_port(
                            project.path / ".env", change["env_variable"], change["old_port"], change["new_port"]
                        )
                        validation = self.compose.validate(compose_file)
                        if not validation["valid"]:
                            shutil.copy2(edit["backup"], edit["file"])
                            raise RuntimeError("Compose validation failed after .env edit; restored backup")
                        changes.append(edit)
                    else:
                        changes.append(
                            self.editor.change_service_host_port(
                                compose_file, change["service"], change["old_port"], change["new_port"]
                            )
                        )
                    runtime_touched_services.append(change["service"])
                    self.compose.recreate_service(compose_file, change["service"])
            except Exception as exc:
                restore_errors = self._restore_edits(changes, compose_file, runtime_touched_services)
                detail = f"; compensation errors: {'; '.join(restore_errors)}" if restore_errors else ""
                raise RuntimeError(f"Port reconciliation failed; restored configuration{detail}") from exc
            refreshed = self.projects.refresh_project(project.id)
            states = {
                item.compose_service: item.state
                for item in self.docker.list_containers()
                if item.compose_working_dir == str(project.path)
            }
            checks = [
                {
                    "service": item["service"],
                    "port": item["new_port"],
                    "config_updated": any(
                        p.service == item["service"] and p.host_port == item["new_port"] for p in refreshed.ports
                    ),
                    "container_running": states.get(item["service"]) == "running",
                    "owner": (owner := self.ports.find_port_owner(item["new_port"])) and owner.model_dump(mode="json"),
                }
                for item in args["changes"]
            ]
            verified = all(c["config_updated"] and c["container_running"] and c["owner"] for c in checks)
            return {"changes": changes}, {"verified": verified, "checks": checks}
        if spec.action == "make.run":
            project = self.projects.get_project(args["project_id"])
            result = self.make.run(project.path, args["target"])
            return result, {"verified": result["verified"]}
        if spec.action == "file.update":
            if not self.files:
                raise RuntimeError("Project file editing service is unavailable")
            result = self.files.apply_update(args["project_id"], args["path"], args["content"], args["expected_sha256"])
            return result, {"verified": bool(result.get("verified")), "validation": result.get("validation", {})}
        if spec.action == "file.undo":
            if not self.files:
                raise RuntimeError("Project file editing service is unavailable")
            result = self.files.undo_latest(args["project_id"], args["path"])
            return result, {"verified": bool(result.get("verified")), "validation": result.get("validation", {})}
        if spec.action == "image.remove":
            result = self.docker.remove_image(args["identifier"])
            return result, {"verified": result["verified"]}
        if spec.action == "volume.remove":
            result = self.docker.remove_volume(args["identifier"])
            return result, {"verified": result["verified"]}
        if spec.action == "stack.switch":
            if not self.stacks:
                raise RuntimeError("Stack preset service is unavailable")
            res = self.stacks.switch_stack(
                args["stack_id"],
                hibernate_current=args.get("hibernate_current", True),
                wait_for_readiness=args.get("wait_for_readiness", True),
                resolve_port_conflicts=args.get("resolve_port_conflicts", True),
            )
            return res.model_dump(mode="json"), {"verified": res.verified, "status": res.status}
        if spec.action == "stack.stop":
            if not self.stacks:
                raise RuntimeError("Stack preset service is unavailable")
            res = self.stacks.stop_stack(args["stack_id"], hibernate=args.get("hibernate", True))
            return res, {"verified": True, "status": res["status"]}
        if spec.action == "readiness.authorize":
            if not self.stacks:
                raise RuntimeError("Readiness policy service is unavailable")
            if not approval_id:
                raise ValueError("Readiness authorization requires a persisted approval")
            authorization = self.stacks.readiness_policy.authorize(args, approval_id)
            result = authorization.model_dump(mode="json")
            return result, {"verified": True, "target_key": authorization.target_key}
        raise ValueError(f"Unsupported action: {spec.action}")

    def _project_compose(self, project_id: str):
        project = self.projects.get_project(project_id)
        if not project.compose_files:
            raise LookupError("Project has no Compose file")
        return project, project.compose_files[0]

    def _restore_edits(self, edits: list[dict], compose_file: Path, services: list[str]) -> list[str]:
        errors: list[str] = []
        for edit in reversed(edits):
            try:
                shutil.copy2(str(edit["backup"]), str(edit["file"]))
            except OSError as exc:
                errors.append(f"could not restore {edit.get('file')}: {exc}")
        for service in dict.fromkeys(services):
            try:
                self.compose.recreate_service(compose_file, service)
            except Exception as exc:
                errors.append(f"could not restore service {service}: {exc}")
        return errors
