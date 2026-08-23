import json
from typing import Any

from dev_agent.agent.service import AgentService


class AgentTools:
    def __init__(self, agent: AgentService) -> None:
        self.agent = agent

    def definitions(self) -> list[dict[str, Any]]:
        specs = [
            ("list_ports", "List real listening ports and owners", {}),
            ("find_port_owner", "Find the real owner of a TCP port", {"port": {"type": "integer"}}),
            ("list_projects", "List registered projects", {}),
            ("detect_port_conflicts", "Find duplicate registered project port claims", {}),
            (
                "prepare_project",
                "Inspect a registered project and propose safe preparation actions",
                {"identifier": {"type": "string"}},
            ),
        ]
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": list(properties),
                        "additionalProperties": False,
                    },
                },
            }
            for name, description, properties in specs
        ]

    def call(self, name: str, arguments: str | dict[str, Any]) -> Any:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        services = self.agent.services
        if name == "list_ports":
            return [item.model_dump(mode="json") for item in services.ports.list_used_ports()]
        if name == "find_port_owner":
            owner = services.ports.find_port_owner(int(args["port"]))
            return owner.model_dump(mode="json") if owner else {"port": args["port"], "available": True}
        if name == "list_projects":
            return [item.model_dump(mode="json") for item in services.projects.list_projects()]
        if name == "detect_port_conflicts":
            return services.ports.detect_port_conflicts()
        if name == "prepare_project":
            return self.agent.prepare_project(identifier=args["identifier"])
        raise ValueError(f"Unknown tool: {name}")
