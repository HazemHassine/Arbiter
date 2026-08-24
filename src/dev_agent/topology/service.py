import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from dev_agent.compose.parser import inspect_compose_details
from dev_agent.dockerfile.service import DockerfileService
from dev_agent.make.service import MakeService
from dev_agent.models import ContainerInfo, Project
from dev_agent.projects.discovery import find_project_root, inspect_project
from dev_agent.system.models import ProcessInfo
from dev_agent.topology.models import (
    RelationshipType,
    ResourceEdge,
    ResourceInspection,
    ResourceNode,
    ResourceType,
    TopologyGraph,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def _node_id(resource_type: ResourceType, resource_id: str) -> str:
    return f"{resource_type.value}:{resource_id}"


class _GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, ResourceNode] = {}
        self.edges: list[ResourceEdge] = []
        self._edge_keys: set[tuple[str, str, RelationshipType, str]] = set()
        self.warnings: list[dict[str, Any]] = []

    def node(
        self,
        resource_type: ResourceType,
        resource_id: str,
        label: str,
        *,
        status: str | None = None,
        attributes: dict[str, Any] | None = None,
        evidence: list[str] | None = None,
    ) -> ResourceNode:
        identifier = _node_id(resource_type, resource_id)
        current = self.nodes.get(identifier)
        if current:
            if status and not current.status:
                current.status = status
            current.attributes.update(attributes or {})
            for item in evidence or []:
                if item not in current.evidence:
                    current.evidence.append(item)
            return current
        current = ResourceNode(
            id=identifier,
            resource_type=resource_type,
            resource_id=resource_id,
            label=label,
            status=status,
            attributes=attributes or {},
            evidence=evidence or [],
        )
        self.nodes[identifier] = current
        return current

    def edge(
        self,
        source: str,
        target: str,
        relationship: RelationshipType,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        encoded = json.dumps(attributes or {}, sort_keys=True, default=str)
        key = (source, target, relationship, encoded)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append(
            ResourceEdge(source=source, target=target, relationship=relationship, attributes=attributes or {})
        )

    def build(self) -> TopologyGraph:
        return TopologyGraph(nodes=list(self.nodes.values()), edges=self.edges, warnings=self.warnings)


class TopologyService:
    """Build a fresh connected graph from project metadata and machine evidence."""

    def __init__(self, projects, docker, ports, system) -> None:
        self.projects = projects
        self.docker = docker
        self.ports = ports
        self.system = system
        self.dockerfiles = DockerfileService()
        self.make = MakeService()

    def graph(self, project_identifier: str | None = None) -> TopologyGraph:
        builder = _GraphBuilder()
        try:
            projects = self.projects.list_projects()
        except Exception as exc:
            projects = []
            builder.warnings.append({"severity": "warning", "message": f"Project registry unavailable: {exc}"})

        project_nodes_by_path: dict[Path, str] = {}
        project_nodes_by_name: dict[str, str] = {}
        compose_services: dict[tuple[str, str], str] = {}
        make_targets: dict[tuple[str, str], str] = {}
        for project in projects:
            project_node = self._add_project(builder, project, registered=True)
            project_nodes_by_path[project.path.resolve(strict=False)] = project_node.id
            project_nodes_by_name.setdefault(project.name, project_node.id)
            service_map, target_map = self._add_project_configuration(builder, project, project_node)
            compose_services.update(service_map)
            make_targets.update(target_map)

        ports = self._ports(builder)
        port_by_pid: dict[int, list[int]] = defaultdict(list)
        for owner in ports:
            if owner.pid:
                port_by_pid[owner.pid].append(owner.port)

        containers = self._containers(builder)
        networks = self._networks(builder)
        volumes = self._volumes(builder)
        self._images(builder)
        for container in containers:
            project_node = self._container_project(
                builder, container, project_nodes_by_path, project_nodes_by_name, compose_services, make_targets
            )
            self._add_container(builder, container, project_node, compose_services, networks, volumes)

        processes = self._processes(builder, port_by_pid)
        self._add_processes(
            builder,
            processes,
            project_nodes_by_path,
            compose_services,
            make_targets,
            containers,
        )
        self._add_port_observations(builder, ports)
        self._port_warnings(builder)
        graph = builder.build()
        return self._scope_project(graph, project_identifier) if project_identifier else graph

    def project_graph(self, identifier: str) -> TopologyGraph:
        return self.graph(project_identifier=identifier)

    def inspect_resource(self, resource_type: str, resource_id: str) -> ResourceInspection:
        try:
            expected_type = ResourceType(resource_type)
        except ValueError as exc:
            raise ValueError(f"Unknown resource type: {resource_type}") from exc
        graph = self.graph()
        node = next(
            (
                item
                for item in graph.nodes
                if item.resource_type == expected_type
                and (
                    item.resource_id == resource_id
                    or str(item.attributes.get("runtime_id")) == resource_id
                    or str(item.attributes.get("name")) == resource_id
                )
            ),
            None,
        )
        if not node:
            raise LookupError(f"Resource not found: {resource_type}/{resource_id}")
        edges = [edge for edge in graph.edges if node.id in {edge.source, edge.target}]
        related_ids = {edge.target if edge.source == node.id else edge.source for edge in edges}
        related = [item for item in graph.nodes if item.id in related_ids]
        return ResourceInspection(node=node, relationships=edges, related=related, generated_at=graph.generated_at)

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return []
        matches = []
        for node in self.graph().nodes:
            haystack = f"{node.resource_type.value} {node.label} {json.dumps(node.attributes, default=str)}".lower()
            if needle in haystack:
                score = 3 if needle == node.label.lower() else 2 if node.label.lower().startswith(needle) else 1
                matches.append({"score": score, "resource": node.model_dump(mode="json")})
        return sorted(matches, key=lambda item: (-item["score"], item["resource"]["label"]))[:limit]

    def workspace(self, identifier: str) -> dict[str, Any]:
        project = self.projects.refresh_project(identifier)
        graph = self.project_graph(project.id)
        containers = [item for item in graph.nodes if item.resource_type == ResourceType.CONTAINER]
        processes = [item for item in graph.nodes if item.resource_type == ResourceType.PROCESS]
        return {
            "project": project.model_dump(mode="json"),
            "status": self._workspace_status(project, containers),
            "topology": graph.model_dump(mode="json"),
            "summary": {
                "services": len(project.services),
                "containers": len(containers),
                "processes": len(processes),
                "ports": len([item for item in graph.nodes if item.resource_type == ResourceType.PORT]),
            },
        }

    @staticmethod
    def _workspace_status(project: Project, containers: list[ResourceNode]) -> str:
        if not project.services and not containers:
            return "not_configured"
        states = [item.status for item in containers]
        if states and all(state == "running" for state in states):
            return "running"
        if any(state == "running" for state in states):
            return "partially_running"
        return "stopped"

    def _add_project(self, builder: _GraphBuilder, project: Project, registered: bool) -> ResourceNode:
        return builder.node(
            ResourceType.PROJECT,
            project.id if registered else f"runtime-{_hash(str(project.path))}",
            project.name,
            status=project.status,
            attributes={
                "name": project.name,
                "path": str(project.path),
                "registered": registered,
                "runtime_discovered": not registered,
                "services": project.services,
            },
            evidence=[f"project_root={project.path}"] if not registered else [],
        )

    def _add_project_configuration(
        self, builder: _GraphBuilder, project: Project, project_node: ResourceNode
    ) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
        services: dict[tuple[str, str], str] = {}
        targets: dict[tuple[str, str], str] = {}
        root = project.path.resolve(strict=False)
        compose_by_service: dict[str, str] = {}
        for compose_file in project.compose_files:
            path = compose_file.resolve(strict=False)
            compose_file_id = _hash(str(path))
            compose_file_node = builder.node(
                ResourceType.COMPOSE_FILE,
                compose_file_id,
                path.name,
                attributes={"path": str(path), "project_id": project_node.resource_id},
            )
            builder.edge(project_node.id, compose_file_node.id, RelationshipType.OWNS)
            compose_id = f"{project_node.resource_id}:{compose_file_id}"
            compose_node = builder.node(
                ResourceType.COMPOSE_PROJECT,
                compose_id,
                f"{project.name} compose",
                attributes={"path": str(path), "project_id": project_node.resource_id},
            )
            builder.edge(project_node.id, compose_node.id, RelationshipType.OWNS)
            builder.edge(compose_node.id, compose_file_node.id, RelationshipType.CONFIGURED_BY)
            try:
                details = inspect_compose_details(path)
            except (OSError, ValueError) as exc:
                builder.warnings.append({"severity": "warning", "message": f"Could not read {path}: {exc}"})
                continue
            for service_name, detail in details.items():
                service_id = f"{compose_id}:{service_name}"
                service_node = builder.node(
                    ResourceType.COMPOSE_SERVICE,
                    service_id,
                    service_name,
                    attributes={
                        "project_id": project_node.resource_id,
                        "compose_path": str(path),
                        "image": detail.get("image"),
                        "restart": detail.get("restart"),
                        "command": detail.get("command"),
                    },
                )
                services[(str(root), service_name)] = service_node.id
                compose_by_service[service_name] = service_node.id
                builder.edge(compose_node.id, service_node.id, RelationshipType.OWNS)
                builder.edge(service_node.id, compose_file_node.id, RelationshipType.CONFIGURED_BY)
                for binding in detail["ports"]:
                    port_node = self._port_node(builder, binding.host_port, binding.protocol, binding.host_ip)
                    declarations = port_node.attributes.setdefault("declared", [])
                    declarations.append(binding.model_dump(mode="json"))
                    builder.edge(
                        service_node.id,
                        port_node.id,
                        RelationshipType.EXPOSES,
                        {"container_port": binding.container_port},
                    )
                dockerfile = self._service_dockerfile(root, detail)
                if dockerfile:
                    docker_node = self._dockerfile_node(builder, dockerfile)
                    builder.edge(service_node.id, docker_node.id, RelationshipType.BUILT_FROM)
                    self._dockerfile_compose_warnings(builder, service_node, docker_node, detail, root)
                for volume in detail.get("volumes", []):
                    name, destination, read_only = self._compose_mount(volume)
                    if not name:
                        continue
                    volume_node = builder.node(
                        ResourceType.VOLUME,
                        f"compose:{project_node.resource_id}:{name}",
                        name,
                        attributes={
                            "declared_by": project_node.resource_id,
                            "compose_project_name": project.name,
                            "compose_volume_name": name,
                        },
                    )
                    builder.edge(
                        service_node.id,
                        volume_node.id,
                        RelationshipType.MOUNTS,
                        {"destination": destination, "read_only": read_only},
                    )
                for network in detail.get("networks", []):
                    network_node = builder.node(
                        ResourceType.NETWORK,
                        f"compose:{project_node.resource_id}:{network}",
                        network,
                        attributes={
                            "declared_by": project_node.resource_id,
                            "compose_project_name": project.name,
                            "compose_network_name": network,
                        },
                    )
                    builder.edge(service_node.id, network_node.id, RelationshipType.CONNECTED_TO)
                for dependency in detail.get("depends_on", []):
                    # Compose files may refer to a service declared later; add the edge after all nodes exist.
                    service_node.attributes.setdefault("depends_on", []).append(dependency)
            for service_name, detail in details.items():
                source = compose_by_service.get(service_name)
                if not source:
                    continue
                for dependency in detail.get("depends_on", []):
                    target = compose_by_service.get(dependency)
                    if target:
                        builder.edge(source, target, RelationshipType.DEPENDS_ON)

        for dockerfile in project.dockerfiles:
            docker_node = self._dockerfile_node(builder, dockerfile)
            builder.edge(project_node.id, docker_node.id, RelationshipType.OWNS)
        env_path = root / ".env"
        if env_path.is_file():
            env_node = builder.node(
                ResourceType.ENV_FILE, _hash(str(env_path)), ".env", attributes={"path": str(env_path)}
            )
            builder.edge(project_node.id, env_node.id, RelationshipType.OWNS)
        makefile = root / "Makefile"
        if makefile.is_file():
            make_node = builder.node(
                ResourceType.MAKEFILE, _hash(str(makefile)), "Makefile", attributes={"path": str(makefile)}
            )
            builder.edge(project_node.id, make_node.id, RelationshipType.OWNS)
            try:
                details = self.make.parse_details(makefile)
            except (OSError, LookupError) as exc:
                builder.warnings.append({"severity": "warning", "message": f"Could not parse Makefile: {exc}"})
                details = {}
            for target_name, detail in details.items():
                target_id = f"{make_node.resource_id}:{target_name}"
                target_node = builder.node(
                    ResourceType.MAKE_TARGET,
                    target_id,
                    target_name,
                    attributes=detail.model_dump(mode="json"),
                    status=detail.risk.value.lower(),
                )
                targets[(str(root), target_name)] = target_node.id
                builder.edge(make_node.id, target_node.id, RelationshipType.OWNS)
            for target_name, detail in details.items():
                source = targets.get((str(root), target_name))
                if source:
                    for dependency in detail.dependencies:
                        target = targets.get((str(root), dependency))
                        if target:
                            builder.edge(source, target, RelationshipType.DEPENDS_ON)
        return services, targets

    def _dockerfile_node(self, builder: _GraphBuilder, path: Path) -> ResourceNode:
        resolved = path.resolve(strict=False)
        attributes: dict[str, Any] = {"path": str(resolved)}
        warnings: list[str] = []
        if resolved.is_file():
            try:
                info = self.dockerfiles.inspect(resolved)
                attributes.update(info.model_dump(mode="json"))
                warnings = [item["message"] for item in info.warnings]
            except (OSError, LookupError, ValueError) as exc:
                warnings = [f"Could not inspect Dockerfile: {exc}"]
        return builder.node(
            ResourceType.DOCKERFILE,
            _hash(str(resolved)),
            str(resolved.relative_to(resolved.parent)) if resolved.name != "Dockerfile" else "Dockerfile",
            attributes=attributes,
            evidence=warnings,
        )

    @staticmethod
    def _dockerfile_compose_warnings(
        builder: _GraphBuilder,
        service_node: ResourceNode,
        docker_node: ResourceNode,
        detail: dict[str, Any],
        project_root: Path,
    ) -> None:
        declared = {item.container_port for item in detail.get("ports", []) if item.container_port}
        exposed = {
            int(str(item).split("/", 1)[0])
            for item in docker_node.attributes.get("exposed_ports", [])
            if str(item).split("/", 1)[0].isdigit()
        }
        missing_expose = sorted(port for port in declared if port not in exposed)
        missing_publish = sorted(port for port in exposed if port not in declared)
        if missing_expose:
            builder.warnings.append(
                {
                    "severity": "possible_issue",
                    "resource_id": docker_node.resource_id,
                    "message": (
                        f"{service_node.label} publishes container port(s) {', '.join(map(str, missing_expose))} "
                        "that its Dockerfile does not EXPOSE"
                    ),
                }
            )
        if missing_publish:
            builder.warnings.append(
                {
                    "severity": "possible_issue",
                    "resource_id": docker_node.resource_id,
                    "message": (
                        f"{docker_node.label} EXPOSEs port(s) {', '.join(map(str, missing_publish))} "
                        "that Compose does not publish"
                    ),
                }
            )
        if not (project_root / ".dockerignore").is_file():
            builder.warnings.append(
                {
                    "severity": "possible_issue",
                    "resource_id": docker_node.resource_id,
                    "message": f"{docker_node.label} has a build configuration but no project .dockerignore was found",
                }
            )
        context = detail.get("build_context")
        if context:
            try:
                context_path = (project_root / str(context)).resolve(strict=False)
                if not context_path.is_relative_to(project_root):
                    builder.warnings.append(
                        {
                            "severity": "warning",
                            "resource_id": docker_node.resource_id,
                            "message": f"{service_node.label} uses a build context outside the project root",
                        }
                    )
            except OSError:
                pass

    @staticmethod
    def _service_dockerfile(root: Path, detail: dict[str, Any]) -> Path | None:
        context, dockerfile = detail.get("build_context"), detail.get("dockerfile")
        if not context or not dockerfile:
            return None
        try:
            return (root / str(context) / str(dockerfile)).resolve(strict=False)
        except OSError:
            return None

    @staticmethod
    def _compose_mount(value: Any) -> tuple[str | None, str | None, bool]:
        if isinstance(value, dict):
            source = value.get("source")
            return str(source) if source else None, value.get("target"), bool(value.get("read_only", False))
        raw = str(value)
        parts = raw.split(":")
        if len(parts) < 2 or parts[0].startswith((".", "/", "~")):
            return None, None, False
        return parts[0], parts[1], len(parts) > 2 and parts[2] == "ro"

    def _ports(self, builder: _GraphBuilder) -> list[Any]:
        try:
            return self.ports.list_used_ports()
        except Exception as exc:
            builder.warnings.append({"severity": "warning", "message": f"Port observation unavailable: {exc}"})
            return []

    def _containers(self, builder: _GraphBuilder) -> list[ContainerInfo]:
        try:
            return self.docker.list_containers()
        except Exception as exc:
            builder.warnings.append({"severity": "warning", "message": f"Docker observation unavailable: {exc}"})
            return []

    def _networks(self, builder: _GraphBuilder) -> dict[str, str]:
        try:
            networks = self.docker.list_networks()
        except Exception:
            return {}
        result: dict[str, str] = {}
        for network in networks:
            resource_id = str(network.get("id") or network.get("name"))
            name = str(network.get("name") or resource_id)
            labels = network.get("labels") or {}
            declared = self._compose_resource_node(
                builder,
                ResourceType.NETWORK,
                str(labels.get("com.docker.compose.project") or ""),
                str(labels.get("com.docker.compose.network") or ""),
            )
            if declared:
                node = declared
                node.attributes.update({key: value for key, value in network.items() if key != "id"})
                node.attributes.update({"runtime_id": resource_id, "runtime_name": name})
            else:
                node = builder.node(
                    ResourceType.NETWORK,
                    resource_id,
                    name,
                    attributes={key: value for key, value in network.items() if key != "id"},
                )
            result[name] = node.id
        return result

    def _volumes(self, builder: _GraphBuilder) -> dict[str, str]:
        try:
            volumes = self.docker.list_volumes()
        except Exception:
            return {}
        result: dict[str, str] = {}
        for volume in volumes:
            name = str(volume.get("name"))
            labels = volume.get("labels") or {}
            declared = self._compose_resource_node(
                builder,
                ResourceType.VOLUME,
                str(labels.get("com.docker.compose.project") or ""),
                str(labels.get("com.docker.compose.volume") or ""),
            )
            if declared:
                declared.attributes.update(volume)
                declared.attributes.update({"runtime_name": name})
                result[name] = declared.id
            else:
                result[name] = builder.node(ResourceType.VOLUME, name, name, attributes=volume).id
        return result

    @staticmethod
    def _compose_resource_node(
        builder: _GraphBuilder, resource_type: ResourceType, project_name: str, resource_name: str
    ) -> ResourceNode | None:
        if not project_name or not resource_name:
            return None
        name_key = "compose_network_name" if resource_type == ResourceType.NETWORK else "compose_volume_name"
        return next(
            (
                node
                for node in builder.nodes.values()
                if node.resource_type == resource_type
                and node.attributes.get("compose_project_name") == project_name
                and node.attributes.get(name_key) == resource_name
            ),
            None,
        )

    def _images(self, builder: _GraphBuilder) -> None:
        try:
            images = self.docker.list_images()
        except Exception:
            return
        for image in images:
            identifier = str(image.get("id"))
            label = ", ".join(image.get("tags") or []) or identifier[:20]
            builder.node(
                ResourceType.IMAGE,
                identifier,
                label,
                attributes=image,
                status="used" if image.get("used") else "unused",
            )

    def _container_project(
        self,
        builder: _GraphBuilder,
        container: ContainerInfo,
        project_nodes_by_path: dict[Path, str],
        project_nodes_by_name: dict[str, str],
        compose_services: dict[tuple[str, str], str],
        make_targets: dict[tuple[str, str], str],
    ) -> ResourceNode | None:
        path: Path | None = None
        if container.compose_working_dir:
            try:
                path = Path(container.compose_working_dir).resolve(strict=False)
            except OSError:
                path = None
        if path:
            for known_path, node_id in project_nodes_by_path.items():
                if path == known_path:
                    return builder.nodes[node_id]
            runtime_root = find_project_root(path) or path if path.is_dir() else None
            if runtime_root:
                try:
                    runtime_project = inspect_project(runtime_root)
                except (OSError, ValueError):
                    runtime_project = Project(name=runtime_root.name, path=runtime_root)
                node = self._add_project(builder, runtime_project, registered=False)
                project_nodes_by_path[runtime_root.resolve(strict=False)] = node.id
                project_nodes_by_name.setdefault(runtime_project.name, node.id)
                services, targets = self._add_project_configuration(builder, runtime_project, node)
                compose_services.update(services)
                make_targets.update(targets)
                return node
        if container.compose_project and container.compose_project in project_nodes_by_name:
            return builder.nodes[project_nodes_by_name[container.compose_project]]
        return None

    def _add_container(
        self,
        builder: _GraphBuilder,
        container: ContainerInfo,
        project_node: ResourceNode | None,
        compose_services: dict[tuple[str, str], str],
        networks: dict[str, str],
        volumes: dict[str, str],
    ) -> None:
        node = builder.node(
            ResourceType.CONTAINER,
            container.id,
            container.name,
            status=container.state,
            attributes=container.model_dump(mode="json"),
        )
        if project_node:
            builder.edge(project_node.id, node.id, RelationshipType.OWNS)
        service_node: str | None = None
        if container.compose_service and container.compose_working_dir:
            service_node = compose_services.get(
                (str(Path(container.compose_working_dir).resolve(strict=False)), container.compose_service)
            )
        if service_node:
            builder.edge(service_node, node.id, RelationshipType.RUNS)
            dockerfile_nodes = [
                edge.target
                for edge in builder.edges
                if edge.source == service_node and edge.relationship == RelationshipType.BUILT_FROM
            ]
            for dockerfile_node_id in dockerfile_nodes:
                dockerfile_node = builder.nodes[dockerfile_node_id]
                docker_cmd = dockerfile_node.attributes.get("cmd")
                if docker_cmd and container.command and " ".join(container.command) not in str(docker_cmd):
                    builder.warnings.append(
                        {
                            "severity": "possible_issue",
                            "resource_id": node.resource_id,
                            "message": (
                                f"Container {container.name} command differs from the Dockerfile CMD; "
                                "this may be an intentional Compose override"
                            ),
                        }
                    )
        elif container.compose_project and container.compose_service:
            compose_id = f"runtime:{container.compose_project}"
            compose_node = builder.node(
                ResourceType.COMPOSE_PROJECT,
                compose_id,
                f"{container.compose_project} compose",
                attributes={"runtime_only": True},
            )
            service_id = f"{compose_id}:{container.compose_service}"
            service = builder.node(
                ResourceType.COMPOSE_SERVICE,
                service_id,
                container.compose_service,
                attributes={"compose_project": container.compose_project, "runtime_only": True},
            )
            builder.edge(compose_node.id, service.id, RelationshipType.OWNS)
            builder.edge(service.id, node.id, RelationshipType.RUNS)
        image = builder.node(
            ResourceType.IMAGE, container.image, container.image, attributes={"reference": container.image}
        )
        builder.edge(node.id, image.id, RelationshipType.USES)
        for mount in container.mounts:
            mount_type = mount.get("Type")
            source = mount.get("Name") if mount_type == "volume" else mount.get("Source")
            if not source:
                continue
            volume_id = volumes.get(str(source))
            volume = builder.nodes.get(volume_id) if volume_id else None
            if volume is None:
                volume = builder.node(
                    ResourceType.VOLUME,
                    str(source),
                    str(source),
                    attributes={"type": mount_type, "source": mount.get("Source")},
                )
            builder.edge(
                node.id,
                volume.id,
                RelationshipType.MOUNTS,
                {"destination": mount.get("Destination"), "read_only": not bool(mount.get("RW", True))},
            )
        for name in container.networks:
            network_id = networks.get(name)
            network = builder.nodes.get(network_id) if network_id else None
            if network is None:
                network = builder.node(ResourceType.NETWORK, name, name, attributes={"runtime_only": True})
            builder.edge(node.id, network.id, RelationshipType.CONNECTED_TO)
        for binding in container.ports:
            port = self._port_node(builder, binding.host_port, binding.protocol, binding.host_ip)
            records = port.attributes.setdefault("published", [])
            records.append(
                {"container_id": container.id, "container_port": binding.container_port, "host_ip": binding.host_ip}
            )
            builder.edge(port.id, node.id, RelationshipType.FORWARDS_TO, {"container_port": binding.container_port})
        for binding in container.exposed_ports:
            resource_id = f"internal:{container.id}:{binding.protocol}:{binding.container_port or binding.host_port}"
            port = builder.node(
                ResourceType.PORT,
                resource_id,
                f"{binding.container_port or binding.host_port}/{binding.protocol}",
                attributes={"kind": "exposed_unpublished", "container_id": container.id},
            )
            builder.edge(node.id, port.id, RelationshipType.EXPOSES)

    def _processes(self, builder: _GraphBuilder, port_by_pid: dict[int, list[int]]) -> list[ProcessInfo]:
        try:
            return [ProcessInfo.model_validate(item) for item in self.system.processes(port_by_pid)]
        except Exception as exc:
            builder.warnings.append({"severity": "warning", "message": f"Process observation unavailable: {exc}"})
            return []

    def _add_processes(
        self,
        builder: _GraphBuilder,
        processes: list[ProcessInfo],
        project_nodes_by_path: dict[Path, str],
        compose_services: dict[tuple[str, str], str],
        make_targets: dict[tuple[str, str], str],
        containers: list[ContainerInfo],
    ) -> None:
        process_nodes: dict[int, str] = {}
        by_container = {container.id: container for container in containers}
        for process in processes:
            root = find_project_root(Path(process.cwd)) if process.cwd else None
            project_node: ResourceNode | None = None
            if root:
                process.project_path = str(root)
                known = project_nodes_by_path.get(root.resolve(strict=False))
                if known:
                    project_node = builder.nodes[known]
                else:
                    try:
                        runtime = inspect_project(root)
                    except (OSError, ValueError):
                        runtime = Project(name=root.name, path=root)
                    project_node = self._add_project(builder, runtime, registered=False)
                    project_nodes_by_path[root.resolve(strict=False)] = project_node.id
                    services, targets = self._add_project_configuration(builder, runtime, project_node)
                    compose_services.update(services)
                    make_targets.update(targets)
            node = builder.node(
                ResourceType.PROCESS,
                str(process.pid),
                process.process or f"PID {process.pid}",
                status=process.state,
                attributes=process.model_dump(mode="json"),
                evidence=process.evidence,
            )
            process_nodes[process.pid] = node.id
            if project_node:
                builder.edge(project_node.id, node.id, RelationshipType.OWNS)
            if process.container_id:
                container = next(
                    (
                        item
                        for identifier, item in by_container.items()
                        if identifier.startswith(process.container_id or "")
                    ),
                    None,
                )
                if container:
                    builder.edge(node.id, _node_id(ResourceType.CONTAINER, container.id), RelationshipType.BELONGS_TO)
            for port_number in process.ports:
                port = self._port_node(builder, port_number, "tcp", None)
                builder.edge(node.id, port.id, RelationshipType.LISTENS_ON)
            if process.process == "make" and project_node and process.command:
                parts = process.command.split()
                target = next((item for item in parts[1:] if not item.startswith("-")), None)
                if target:
                    target_node = make_targets.get((str(Path(project_node.attributes["path"])), target))
                    if target_node:
                        builder.edge(node.id, target_node, RelationshipType.RUNS)
        for process in processes:
            if process.ppid and process.ppid in process_nodes:
                builder.edge(process_nodes[process.pid], process_nodes[process.ppid], RelationshipType.CHILD_OF)
        self._link_make_descendants(builder, processes, process_nodes, make_targets)

    @staticmethod
    def _link_make_descendants(
        builder: _GraphBuilder,
        processes: list[ProcessInfo],
        process_nodes: dict[int, str],
        make_targets: dict[tuple[str, str], str],
    ) -> None:
        by_pid = {item.pid: item for item in processes}
        for process in processes:
            current = process
            for _ in range(12):
                if not current.ppid or current.ppid not in by_pid:
                    break
                current = by_pid[current.ppid]
                if current.process != "make" or not current.command or not current.project_path:
                    continue
                target = next((item for item in current.command.split()[1:] if not item.startswith("-")), None)
                if target and (target_node := make_targets.get((current.project_path, target))):
                    builder.edge(process_nodes[process.pid], target_node, RelationshipType.STARTED_BY)
                break

    def _add_port_observations(self, builder: _GraphBuilder, owners: list[Any]) -> None:
        for owner in owners:
            port = self._port_node(builder, owner.port, owner.protocol, owner.host)
            observed = owner.model_dump(mode="json")
            records = port.attributes.setdefault("runtime_owners", [])
            if observed not in records:
                records.append(observed)
            port.status = owner.state

    @staticmethod
    def _port_node(builder: _GraphBuilder, port: int, protocol: str, host: str | None) -> ResourceNode:
        resource_id = f"{protocol.lower()}:{port}"
        node = builder.node(
            ResourceType.PORT,
            resource_id,
            f":{port}",
            attributes={"port": port, "protocol": protocol.lower(), "hosts": []},
        )
        if host and host not in node.attributes["hosts"]:
            node.attributes["hosts"].append(host)
        return node

    @staticmethod
    def _port_warnings(builder: _GraphBuilder) -> None:
        for node in builder.nodes.values():
            if node.resource_type != ResourceType.PORT:
                continue
            declarations = node.attributes.get("declared", [])
            owners = node.attributes.get("runtime_owners", [])
            if declarations and not owners:
                builder.warnings.append(
                    {
                        "severity": "possible_issue",
                        "resource_id": node.resource_id,
                        "message": f"{node.label} is declared in Compose but no listener is currently observed",
                    }
                )
            declared_projects = {item.get("source") for item in declarations}
            external = [owner for owner in owners if owner.get("source") not in declared_projects]
            if declarations and external:
                builder.warnings.append(
                    {
                        "severity": "warning",
                        "resource_id": node.resource_id,
                        "message": (
                            f"{node.label} has a declared mapping and an observed runtime owner; "
                            "inspect ownership before changing it"
                        ),
                    }
                )

    @staticmethod
    def _scope_project(graph: TopologyGraph, identifier: str) -> TopologyGraph:
        starts = [
            node.id
            for node in graph.nodes
            if node.resource_type == ResourceType.PROJECT
            and (node.resource_id == identifier or node.attributes.get("name") == identifier)
        ]
        if not starts:
            raise LookupError(f"Project not found in topology: {identifier}")
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in graph.edges:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)
        included = set(starts)
        queue = deque((node, 0) for node in starts)
        while queue:
            node, depth = queue.popleft()
            if depth >= 5:
                continue
            for related in adjacency[node]:
                if related not in included:
                    included.add(related)
                    queue.append((related, depth + 1))
        edges = [edge for edge in graph.edges if edge.source in included and edge.target in included]
        warnings = [
            warning
            for warning in graph.warnings
            if not warning.get("resource_id") or _node_id(ResourceType.PORT, str(warning["resource_id"])) in included
        ]
        return TopologyGraph(
            nodes=[node for node in graph.nodes if node.id in included], edges=edges, warnings=warnings
        )
