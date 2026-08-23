import shutil
from pathlib import Path
from uuid import uuid4

from dev_agent.compose.editor import ComposeEditor, change_env_port
from dev_agent.compose.service import ComposeService
from dev_agent.docker.service import DockerService
from dev_agent.make.service import MakeService
from dev_agent.models import ActionResult, ActionSpec
from dev_agent.persistence.database import Database
from dev_agent.persistence.tables import ActionRow
from dev_agent.ports.service import PortService
from dev_agent.projects.service import ProjectService
from dev_agent.safety.approvals import ApprovalService
from dev_agent.safety.policies import needs_approval


class ActionService:
    def __init__(
        self, database: Database, projects: ProjectService, ports: PortService, docker: DockerService, settings
    ) -> None:
        self.database, self.projects, self.ports, self.docker = database, projects, ports, docker
        self.settings = settings
        self.approvals = ApprovalService(database)
        self.compose = ComposeService()
        self.editor = ComposeEditor()
        self.make = MakeService()

    def propose(self, spec: ActionSpec) -> dict[str, object]:
        if needs_approval(spec.risk, self.settings):
            approval = self.approvals.create(spec)
            return {"status": "approval_required", "approval": approval.model_dump(mode="json")}
        return {"status": "completed", "action": self.execute(spec).model_dump(mode="json")}

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
        return self.execute(spec, approval_id=approval.id)

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
            result, verification = self._dispatch(spec)
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

    def _dispatch(self, spec: ActionSpec) -> tuple[dict, dict]:
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
        if spec.action == "project.resolve_ports":
            project, compose_file = self._project_compose(args["project_id"])
            changes = []
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
                self.compose.recreate_service(compose_file, change["service"])
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
        if spec.action == "image.remove":
            result = self.docker.remove_image(args["identifier"])
            return result, {"verified": result["verified"]}
        if spec.action == "volume.remove":
            result = self.docker.remove_volume(args["identifier"])
            return result, {"verified": result["verified"]}
        raise ValueError(f"Unsupported action: {spec.action}")

    def _project_compose(self, project_id: str):
        project = self.projects.get_project(project_id)
        if not project.compose_files:
            raise LookupError("Project has no Compose file")
        return project, project.compose_files[0]
