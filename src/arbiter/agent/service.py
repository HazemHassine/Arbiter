from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

from arbiter.models import ActionSpec, Risk
from arbiter.persistence.tables import AgentRequestRow
from arbiter.security import redact
from arbiter.services import Services


class AgentService:
    def __init__(self, services: Services) -> None:
        self.services = services

    def prepare_project(
        self,
        identifier: str | None = None,
        path: Path | None = None,
        resolve_port_conflicts: bool = True,
        start: bool = True,
        verify: bool = True,
    ) -> dict[str, object]:
        project = (
            self.services.projects.register_project(path)
            if path
            else self.services.projects.refresh_project(identifier or "")
        )
        plan = self.services.ports.plan_port_reconciliation(project)
        conflicts = [item.model_dump(mode="json") for item in plan.changes]
        if conflicts and resolve_port_conflicts:
            spec = ActionSpec(
                action="project.resolve_ports",
                risk=Risk.MEDIUM_RISK,
                project_id=project.id,
                summary=f"Resolve {len(conflicts)} port conflict(s) for {project.name} and recreate affected services",
                arguments={
                    "project_id": project.id,
                    "verify": verify,
                    "changes": [
                        {
                            "service": item["service"],
                            "old_port": item["requested_port"],
                            "new_port": item["suggested_port"],
                            "compose_file": item["source"],
                            "env_variable": item["env_variable"],
                        }
                        for item in conflicts
                    ],
                },
            )
            result = self.services.actions.propose(spec)
            return {
                "project": project.name,
                "reconciliation": plan.model_dump(mode="json"),
                "conflicts": conflicts,
                **result,
            }
        if conflicts:
            return {
                "status": "conflicts",
                "project": project.name,
                "reconciliation": plan.model_dump(mode="json"),
                "conflicts": conflicts,
            }
        if start:
            if project.compose_files:
                spec = ActionSpec(
                    action="compose.start",
                    risk=Risk.MEDIUM_RISK,
                    project_id=project.id,
                    summary=f"Start Compose project {project.name}",
                    arguments={"project_id": project.id, "verify": verify},
                )
                return {
                    "project": project.name,
                    "reconciliation": plan.model_dump(mode="json"),
                    "conflicts": [],
                    **self.services.actions.propose(spec),
                }
            return {
                "status": "not_started",
                "project": project.name,
                "reconciliation": plan.model_dump(mode="json"),
                "conflicts": [],
                "reason": "No supported startup mechanism found",
            }
        return {
            "status": "inspected",
            "project": project.name,
            "reconciliation": plan.model_dump(mode="json"),
            "conflicts": [],
            "ports": [item.model_dump(mode="json") for item in project.ports],
        }

    def diagnose_project(self, identifier: str) -> dict[str, object]:
        project = self.services.projects.refresh_project(identifier)
        plan = self.services.ports.plan_port_reconciliation(project)
        issues = [
            {"type": "port_conflict", **change.model_dump(mode="json")}
            for change in plan.changes
        ]
        try:
            containers = [
                item for item in self.services.docker.list_containers() if item.compose_working_dir == str(project.path)
            ]
            for item in containers:
                if item.state != "running" or item.health == "unhealthy":
                    issues.append(
                        {"type": "container_health", "container": item.name, "state": item.state, "health": item.health}
                    )
        except Exception as exc:
            issues.append({"type": "docker_unavailable", "evidence": str(exc)})
        return {
            "project": project.name,
            "status": "healthy" if not issues else "issues_found",
            "reconciliation": plan.model_dump(mode="json"),
            "issues": issues,
        }

    def query(self, message: str) -> dict[str, object]:
        request_id = str(uuid4())
        lower = message.lower()
        if any(phrase in lower for phrase in ("what is running", "which projects are running", "running projects")):
            workspaces = []
            for project in self.services.projects.list_projects():
                workspace = self.services.topology.workspace(project.id)
                if workspace["status"] in {"running", "partially_running"}:
                    workspaces.append(
                        {"project": project.name, "status": workspace["status"], "summary": workspace["summary"]}
                    )
            return self._persist_request(
                message,
                {
                    "request_id": request_id,
                    "status": "completed",
                    "message": f"Found {len(workspaces)} registered project(s) with observed runtime activity.",
                    "observations": workspaces,
                    "actions": [],
                    "approval_required": False,
                },
            )
        if "what would break" in lower or "impact" in lower and "container" in lower:
            containers = self.services.docker.list_containers()
            matches = [item for item in containers if item.name.lower() in lower or item.id[:12].lower() in lower]
            if len(matches) == 1:
                impact = self.services.impact.analyze(
                    ActionSpec(
                        action="container.stop",
                        arguments={"identifier": matches[0].id},
                        summary=f"Impact of stopping {matches[0].name}",
                        risk=Risk.MEDIUM_RISK,
                    )
                )
                return self._persist_request(
                    message,
                    {
                        "request_id": request_id,
                        "status": "completed",
                        "message": impact["summary"],
                        "observations": [impact],
                        "actions": [],
                        "approval_required": False,
                    },
                )
        if "process" in lower and any(word in lower for word in ("running", "list", "show", "which")):
            owners = self.services.ports.list_used_ports()
            by_pid: dict[int, list[int]] = {}
            for owner in owners:
                if owner.pid:
                    by_pid.setdefault(owner.pid, []).append(owner.port)
            processes = self.services.system.processes(by_pid)
            interesting = [item for item in processes if item.get("kind") != "process" or item.get("ports")]
            return self._persist_request(
                message,
                {
                    "request_id": request_id,
                    "status": "completed",
                    "message": f"Found {len(interesting)} development-related or listening process(es).",
                    "observations": interesting,
                    "actions": [],
                    "approval_required": False,
                },
            )
        if any(word in lower for word in ("prepare", "start")):
            matches = [project for project in self.services.projects.list_projects() if project.name.lower() in lower]
            if len(matches) == 1:
                operation = self.prepare_project(identifier=matches[0].id)
                approval = operation.get("status") == "approval_required"
                return self._persist_request(
                    message,
                    {
                        "request_id": request_id,
                        "status": operation.get("status", "completed"),
                        "message": (
                            f"Inspected {matches[0].name}; approval is required for the proposed action."
                            if approval
                            else f"Inspected {matches[0].name}."
                        ),
                        "observations": operation.get("conflicts", []),
                        "actions": [operation],
                        "approval_required": approval,
                    },
                )
        if "port" in lower and any(word in lower for word in ("used", "using", "occupied", "what")):
            import re

            numbers = re.findall(r"\b([1-9]\d{0,4})\b", lower)
            if numbers:
                owner = self.services.ports.find_port_owner(int(numbers[0]))
                text = (
                    f"Port {numbers[0]} is free."
                    if not owner
                    else f"Port {numbers[0]} is owned by {owner.container or owner.process or 'an unknown listener'}."
                )
                observations = [owner.model_dump(mode="json")] if owner else []
            else:
                owners = self.services.ports.list_used_ports()
                text = f"Found {len(owners)} listening port bindings."
                observations = [item.model_dump(mode="json") for item in owners]
            return self._persist_request(
                message,
                {
                    "request_id": request_id,
                    "status": "completed",
                    "message": text,
                    "observations": observations,
                    "actions": [],
                    "approval_required": False,
                },
            )
        if "conflict" in lower:
            conflicts = self.services.ports.detect_port_conflicts()
            return self._persist_request(
                message,
                {
                    "request_id": request_id,
                    "status": "completed",
                    "message": f"Found {len(conflicts)} registered cross-project port conflicts.",
                    "observations": conflicts,
                    "actions": [],
                    "approval_required": False,
                },
            )
        return self._persist_request(
            message,
            {
                "request_id": request_id,
                "status": "completed",
                "message": (
                    "This request is not covered by deterministic v1 intents; "
                    "configure an LLM provider for open-ended queries."
                ),
                "observations": [],
                "actions": [],
                "approval_required": False,
            },
        )

    async def async_query(self, message: str) -> dict[str, object]:
        response: dict[str, object] | None = None
        async for event in self.async_query_events(message):
            if event["type"] == "final":
                response = event["response"]
        if response is None:
            raise RuntimeError("Agent stream ended without a final response")
        return response

    async def async_query_events(self, message: str) -> AsyncIterator[dict[str, object]]:
        classification_step = "classify-request"
        yield {
            "type": "step_started",
            "step_id": classification_step,
            "kind": "routing",
            "title": "Inspecting request",
            "detail": "Checking deterministic capabilities before invoking a model.",
        }
        deterministic = self.query(message)
        deterministic_match = bool(deterministic["observations"]) or "not covered" not in str(
            deterministic["message"]
        )
        if deterministic_match:
            yield {
                "type": "step_completed",
                "step_id": classification_step,
                "kind": "routing",
                "title": "Inspecting request",
                "detail": "Handled by deterministic control-plane services; no model call was needed.",
                "status": "completed",
            }
            observations = deterministic.get("observations") or []
            if observations:
                yield {
                    "type": "step_completed",
                    "step_id": "deterministic-evidence",
                    "kind": "evidence",
                    "title": "Collected live evidence",
                    "detail": f"Collected {len(observations)} observation(s) from local services.",
                    "status": "completed",
                    "result": redact(observations),
                }
            yield {"type": "final", "response": deterministic}
            return
        settings = self.services.settings
        if not settings.llm_api_key or not settings.llm_model:
            yield {
                "type": "step_completed",
                "step_id": classification_step,
                "kind": "routing",
                "title": "Inspecting request",
                "detail": "No deterministic intent matched and no model is configured.",
                "status": "completed",
            }
            yield {"type": "final", "response": deterministic}
            return
        from arbiter.agent.runtime import AgentRuntime, AgentRuntimeError, build_agent_model
        from arbiter.agent.tools import AgentTools

        yield {
            "type": "step_completed",
            "step_id": classification_step,
            "kind": "routing",
            "title": "Inspecting request",
            "detail": "Delegated the open-ended request to the bounded LangGraph runtime.",
            "status": "completed",
        }
        try:
            model = build_agent_model(settings, self.services.telemetry)
            outcome: dict[str, object] | None = None
            async for event in AgentRuntime(model, AgentTools(self), settings.agent_max_steps).stream(message):
                if event["type"] == "runtime_completed":
                    outcome = event["outcome"]
                else:
                    yield event
            if outcome is None:
                raise RuntimeError("Agent runtime ended without an outcome")
        except AgentRuntimeError as exc:
            response = self._update_request(
                deterministic["request_id"],
                {
                    "request_id": deterministic["request_id"],
                    "status": "degraded",
                    "message": f"The configured LLM is unavailable: {exc}",
                    "observations": [],
                    "actions": [],
                    "approval_required": False,
                },
            )
            yield {"type": "run_error", "message": str(response["message"])}
            yield {"type": "final", "response": response}
            return
        except Exception:
            response = self._update_request(
                deterministic["request_id"],
                {
                    "request_id": deterministic["request_id"],
                    "status": "degraded",
                    "message": "The configured LLM failed unexpectedly. Deterministic operations remain available.",
                    "observations": [],
                    "actions": [],
                    "approval_required": False,
                },
            )
            yield {"type": "run_error", "message": str(response["message"])}
            yield {"type": "final", "response": response}
            return
        approval_required = any(
            isinstance(item.get("result"), dict) and item["result"].get("status") == "approval_required"
            for item in outcome.get("observations", [])
        )
        response = {
            "request_id": deterministic["request_id"],
            "status": "completed",
            "message": outcome["message"],
            "observations": outcome.get("observations", []),
            "actions": [],
            "approval_required": approval_required,
        }
        persisted = self._update_request(deterministic["request_id"], response)
        yield {"type": "final", "response": persisted}

    def _persist_request(self, message: str, response: dict[str, object]) -> dict[str, object]:
        with self.services.database.sessions() as session:
            session.add(
                AgentRequestRow(
                    id=str(response["request_id"]), message=message, status=str(response["status"]), response=response
                )
            )
            session.commit()
        return response

    def _update_request(self, request_id: object, response: dict[str, object]) -> dict[str, object]:
        with self.services.database.sessions() as session:
            row = session.get(AgentRequestRow, str(request_id))
            if row:
                row.status = str(response["status"])
                row.response = response
                session.commit()
        return response
