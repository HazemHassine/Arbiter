import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from arbiter.agent.service import AgentService


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    properties: dict[str, dict[str, Any]]


class AgentTools:
    def __init__(self, agent: "AgentService") -> None:
        self.agent = agent

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": self._schema(spec),
                },
            }
            for spec in self._specs()
        ]

    def langchain_tools(self) -> list["BaseTool"]:
        """Expose the registry as typed LangChain tools without duplicating implementations."""

        from langchain_core.tools import StructuredTool

        return [
            StructuredTool.from_function(
                func=self._safe_runner(spec.name),
                name=spec.name,
                description=spec.description,
                args_schema=self._schema(spec),
            )
            for spec in self._specs()
        ]

    @staticmethod
    def _schema(spec: ToolSpec) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": spec.properties,
            "required": list(spec.properties),
            "additionalProperties": False,
        }

    def _safe_runner(self, name: str) -> Callable[..., Any]:
        def run(**arguments: Any) -> Any:
            try:
                return self.call(name, arguments)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return {"error": "malformed_tool_call", "detail": str(exc)}

        return run

    @staticmethod
    def _specs() -> list[ToolSpec]:
        return [
            ToolSpec("topology_get", "Get the connected live workstation topology", {}),
            ToolSpec(
                "resource_inspect",
                "Inspect one resource and all directly connected resources",
                {"resource_type": {"type": "string"}, "resource_id": {"type": "string"}},
            ),
            ToolSpec(
                "project_inspect",
                "Inspect a registered project's connected workspace",
                {"identifier": {"type": "string"}},
            ),
            ToolSpec(
                "project_diagnose",
                "Diagnose a registered project from observed state",
                {"identifier": {"type": "string"}},
            ),
            ToolSpec(
                "project_reconciliation_plan",
                "Build a read-only deterministic port reconciliation plan for a registered project",
                {"identifier": {"type": "string"}},
            ),
            ToolSpec(
                "config_drift_audit",
                "Audit a project for .env and Compose configuration drift, port divergences, and missing variables",
                {"identifier": {"type": "string"}},
            ),
            ToolSpec("list_ports", "List real listening ports and owners", {}),
            ToolSpec("find_port_owner", "Find the real owner of a TCP port", {"port": {"type": "integer"}}),
            ToolSpec("find_free_port", "Find a deterministic free host port", {"preferred_port": {"type": "integer"}}),
            ToolSpec("list_projects", "List registered projects", {}),
            ToolSpec("detect_port_conflicts", "Find duplicate registered project port claims", {}),
            ToolSpec("containers_list", "List Docker containers", {}),
            ToolSpec("container_inspect", "Inspect one Docker container", {"identifier": {"type": "string"}}),
            ToolSpec("volume_inspect", "Inspect one Docker volume", {"identifier": {"type": "string"}}),
            ToolSpec("network_inspect", "Inspect one Docker network", {"identifier": {"type": "string"}}),
            ToolSpec("processes_list", "List host processes with project and port evidence", {}),
            ToolSpec("process_inspect", "Inspect one host process", {"pid": {"type": "integer"}}),
            ToolSpec(
                "make_targets_list",
                "List Make targets and inferred command metadata for a project",
                {"identifier": {"type": "string"}},
            ),
            ToolSpec(
                "dockerfile_inspect",
                "Inspect a Dockerfile in a registered project",
                {"identifier": {"type": "string"}, "path": {"type": "string"}},
            ),
            ToolSpec(
                "prepare_project",
                "Inspect a registered project and propose safe preparation actions",
                {"identifier": {"type": "string"}},
            ),
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
        if name == "project_reconciliation_plan":
            project = services.projects.refresh_project(args["identifier"])
            return services.ports.plan_port_reconciliation(project).model_dump(mode="json")
        if name == "config_drift_audit":
            identifier = args.get("identifier")
            if identifier:
                return services.config_intelligence.audit_project_config(identifier).model_dump(mode="json")
            return [item.model_dump(mode="json") for item in services.config_intelligence.audit_all_projects()]
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
            from arbiter.make.service import MakeService

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
