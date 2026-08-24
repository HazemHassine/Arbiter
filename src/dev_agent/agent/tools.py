import json
from typing import Any

from dev_agent.agent.service import AgentService


class AgentTools:
    def __init__(self, agent: AgentService) -> None:
        self.agent = agent

    def definitions(self) -> list[dict[str, Any]]:
        specs = [
            ("topology_get", "Get the connected live workstation topology", {}),
            (
                "resource_inspect",
                "Inspect one resource and all directly connected resources",
                {"resource_type": {"type": "string"}, "resource_id": {"type": "string"}},
            ),
            (
                "project_inspect",
                "Inspect a registered project's connected workspace",
                {"identifier": {"type": "string"}},
            ),
            (
                "project_diagnose",
                "Diagnose a registered project from observed state",
                {"identifier": {"type": "string"}},
            ),
            ("list_ports", "List real listening ports and owners", {}),
            ("find_port_owner", "Find the real owner of a TCP port", {"port": {"type": "integer"}}),
            ("find_free_port", "Find a deterministic free host port", {"preferred_port": {"type": "integer"}}),
            ("list_projects", "List registered projects", {}),
            ("detect_port_conflicts", "Find duplicate registered project port claims", {}),
            ("containers_list", "List Docker containers", {}),
            ("container_inspect", "Inspect one Docker container", {"identifier": {"type": "string"}}),
            ("volume_inspect", "Inspect one Docker volume", {"identifier": {"type": "string"}}),
            ("network_inspect", "Inspect one Docker network", {"identifier": {"type": "string"}}),
            ("processes_list", "List host processes with project and port evidence", {}),
            ("process_inspect", "Inspect one host process", {"pid": {"type": "integer"}}),
            (
                "make_targets_list",
                "List Make targets and inferred command metadata for a project",
                {"identifier": {"type": "string"}},
            ),
            (
                "dockerfile_inspect",
                "Inspect a Dockerfile in a registered project",
                {"identifier": {"type": "string"}, "path": {"type": "string"}},
            ),
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
        if name == "topology_get":
            return services.topology.graph().model_dump(mode="json")
        if name == "resource_inspect":
            return services.topology.inspect_resource(args["resource_type"], args["resource_id"]).model_dump(
                mode="json"
            )
        if name == "project_inspect":
            return services.topology.workspace(args["identifier"])
        if name == "project_diagnose":
            return self.agent.diagnose_project(args["identifier"])
        if name == "list_ports":
            return [item.model_dump(mode="json") for item in services.ports.list_used_ports()]
        if name == "find_port_owner":
            owner = services.ports.find_port_owner(int(args["port"]))
            return owner.model_dump(mode="json") if owner else {"port": args["port"], "available": True}
        if name == "find_free_port":
            return {"suggested_port": services.ports.find_free_port(int(args["preferred_port"]))}
        if name == "list_projects":
            return [item.model_dump(mode="json") for item in services.projects.list_projects()]
        if name == "detect_port_conflicts":
            return services.ports.detect_port_conflicts()
        if name == "containers_list":
            return [item.model_dump(mode="json") for item in services.docker.list_containers()]
        if name == "container_inspect":
            return services.docker.inspect_container(args["identifier"]).model_dump(mode="json")
        if name == "volume_inspect":
            return services.docker.inspect_volume(args["identifier"])
        if name == "network_inspect":
            return services.docker.inspect_network(args["identifier"])
        if name == "processes_list":
            owners = services.ports.list_used_ports()
            port_by_pid: dict[int, list[int]] = {}
            for owner in owners:
                if owner.pid:
                    port_by_pid.setdefault(owner.pid, []).append(owner.port)
            return services.system.processes(port_by_pid)
        if name == "process_inspect":
            return services.system.process(int(args["pid"]))
        if name == "make_targets_list":
            from dev_agent.make.service import MakeService

            project = services.projects.get_project(args["identifier"])
            return [
                item.model_dump(mode="json") for item in MakeService().parse_details(project.path / "Makefile").values()
            ]
        if name == "dockerfile_inspect":
            project = services.projects.get_project(args["identifier"])
            path = services.files.read(project.id, args["path"]).path
            return services.topology.dockerfiles.inspect(project.path / path).model_dump(mode="json")
        if name == "prepare_project":
            return self.agent.prepare_project(identifier=args["identifier"])
        raise ValueError(f"Unknown tool: {name}")
