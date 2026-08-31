"""A2A-compatible capability description and REST task mapping.

The A2A ecosystem is intentionally not a mandatory runtime dependency in v1. This
adapter provides a stable Agent Card-shaped document and maps high-level tasks to
the same core service used by REST/MCP.
"""

from arbiter.agent.service import AgentService

AGENT_CARD = {
    "name": "Arbiter",
    "description": "Understands, diagnoses, and safely reconciles local Linux development environments.",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "skills": [
        {"id": "prepare_project", "name": "Prepare local project"},
        {"id": "resolve_port_conflicts", "name": "Resolve port conflicts"},
        {"id": "diagnose_project", "name": "Diagnose local environment"},
        {"id": "inspect_docker", "name": "Inspect Docker state"},
        {"id": "check_stack_readiness", "name": "Check policy-controlled stack readiness"},
    ],
    "taskEndpoint": "/api/v1/projects/{id}/prepare",
}


class A2AAdapter:
    def __init__(self, agent: AgentService) -> None:
        self.agent = agent

    def execute_task(self, skill: str, project: str) -> dict[str, object]:
        if skill in {"prepare_project", "resolve_port_conflicts"}:
            return self.agent.prepare_project(identifier=project)
        if skill == "diagnose_project":
            return self.agent.diagnose_project(project)
        if skill == "check_stack_readiness":
            return {
                "readiness": [
                    item.model_dump(mode="json")
                    for item in self.agent.services.stacks.check_stack_readiness(project)
                ]
            }
        raise ValueError(f"Unsupported A2A skill: {skill}")
