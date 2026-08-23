from pathlib import Path
from uuid import uuid4

from dev_agent.models import ActionSpec, Risk
from dev_agent.persistence.tables import AgentRequestRow
from dev_agent.services import Services


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
        used = self.services.ports.list_used_ports()
        conflicts = []
        reserved = {item.port for item in used}
        for binding in project.ports:
            owner = next(
                (item for item in used if item.port == binding.host_port and item.protocol == binding.protocol), None
            )
            same_project = owner and owner.project in {project.name, project.id}
            if owner and not same_project:
                suggestion = binding.host_port + 1
                while suggestion in reserved and suggestion <= 65535:
                    suggestion += 1
                if suggestion > 65535:
                    raise RuntimeError("No deterministic alternative port available")
                reserved.add(suggestion)
                conflicts.append(
                    {
                        "service": binding.service,
                        "requested_port": binding.host_port,
                        "occupied_by": owner.model_dump(mode="json"),
                        "suggested_port": suggestion,
                        "compose_file": binding.source,
                        "env_variable": binding.variable,
                    }
                )
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
                            "compose_file": item["compose_file"],
                            "env_variable": item["env_variable"],
                        }
                        for item in conflicts
                    ],
                },
            )
            result = self.services.actions.propose(spec)
            return {"project": project.name, "conflicts": conflicts, **result}
        if conflicts:
            return {"status": "conflicts", "project": project.name, "conflicts": conflicts}
        if start:
            if project.compose_files:
                spec = ActionSpec(
                    action="compose.start",
                    risk=Risk.MEDIUM_RISK,
                    project_id=project.id,
                    summary=f"Start Compose project {project.name}",
                    arguments={"project_id": project.id, "verify": verify},
                )
                return {"project": project.name, "conflicts": [], **self.services.actions.propose(spec)}
            return {
                "status": "not_started",
                "project": project.name,
                "conflicts": [],
                "reason": "No supported startup mechanism found",
            }
        return {
            "status": "inspected",
            "project": project.name,
            "conflicts": [],
            "ports": [item.model_dump(mode="json") for item in project.ports],
        }

    def diagnose_project(self, identifier: str) -> dict[str, object]:
        project = self.services.projects.refresh_project(identifier)
        used = self.services.ports.list_used_ports()
        issues = []
        for binding in project.ports:
            owner = next((item for item in used if item.port == binding.host_port), None)
            if owner and owner.project != project.name:
                issues.append(
                    {
                        "type": "port_conflict",
                        "service": binding.service,
                        "requested_port": binding.host_port,
                        "owner": owner.model_dump(mode="json"),
                    }
                )
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
        return {"project": project.name, "status": "healthy" if not issues else "issues_found", "issues": issues}

    def query(self, message: str) -> dict[str, object]:
        request_id = str(uuid4())
        lower = message.lower()
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
        deterministic = self.query(message)
        if deterministic["observations"] or "not covered" not in str(deterministic["message"]):
            return deterministic
        settings = self.services.settings
        if not settings.llm_api_key or not settings.llm_model:
            return deterministic
        from dev_agent.agent.loop import AgentLoop
        from dev_agent.agent.tools import AgentTools
        from dev_agent.llm.openai_compatible import LLMProviderError, OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            reasoning_effort=settings.llm_reasoning_effort,
        )
        try:
            outcome = await AgentLoop(provider, AgentTools(self), settings.agent_max_steps).run(message)
        except LLMProviderError as exc:
            return self._update_request(
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
        except Exception:
            return self._update_request(
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
        return self._update_request(deterministic["request_id"], response)

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
