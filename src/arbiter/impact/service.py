from collections import deque
from typing import Any

from arbiter.models import ActionSpec
from arbiter.topology.models import RelationshipType, ResourceNode


class ImpactService:
    def __init__(self, topology) -> None:
        self.topology = topology

    def analyze(self, spec: ActionSpec) -> dict[str, Any]:
        graph = self.topology.graph()
        target = self._target(spec, graph.nodes)
        if not target:
            return {
                "action": spec.action,
                "known": False,
                "summary": (
                    "No runtime target could be resolved yet; execution will still independently verify the action."
                ),
                "affected": [],
            }
        related = self._related(target.id, graph.edges, graph.nodes, depth=2)
        dependencies = [
            edge.source
            for edge in graph.edges
            if edge.relationship == RelationshipType.DEPENDS_ON and edge.target == target.id
        ]
        node_by_id = {item.id: item for item in graph.nodes}
        dependent_services = [node_by_id[item].label for item in dependencies if item in node_by_id]
        affected = [
            {"type": item.resource_type.value, "id": item.resource_id, "label": item.label, "status": item.status}
            for item in related
            if item.id != target.id
        ]
        ports = [item.label for item in related if item.resource_type.value == "port"]
        volumes = [item.label for item in related if item.resource_type.value == "volume"]
        projects = [item.label for item in related if item.resource_type.value == "project"]
        summary_parts = [f"{spec.action} targets {target.label}."]
        if dependent_services:
            summary_parts.append(f"Dependent services: {', '.join(dependent_services)}.")
        if ports:
            summary_parts.append(f"Related ports: {', '.join(ports)}.")
        if volumes:
            summary_parts.append(f"Persistent volumes: {', '.join(volumes)}.")
        if spec.action in {"volume.remove", "image.remove", "container.remove"}:
            summary_parts.append(
                "This operation can remove data or a reusable runtime artifact; it remains explicitly approved."
            )
        return {
            "action": spec.action,
            "known": True,
            "target": {"type": target.resource_type.value, "id": target.resource_id, "label": target.label},
            "projects": sorted(set(projects)),
            "dependent_services": dependent_services,
            "ports": sorted(set(ports)),
            "volumes": sorted(set(volumes)),
            "affected": affected,
            "summary": " ".join(summary_parts),
        }

    @staticmethod
    def _target(spec: ActionSpec, nodes: list[ResourceNode]) -> ResourceNode | None:
        args = spec.arguments
        if spec.action.startswith("container."):
            identifier = str(args.get("identifier", ""))
            return next(
                (
                    item
                    for item in nodes
                    if item.resource_type.value == "container"
                    and (item.resource_id == identifier or item.label == identifier)
                ),
                None,
            )
        if spec.action.startswith("compose.") or spec.action.startswith("project.") or spec.action.startswith("file."):
            identifier = str(args.get("project_id", ""))
            return next(
                (item for item in nodes if item.resource_type.value == "project" and item.resource_id == identifier),
                None,
            )
        if spec.action == "volume.remove":
            return next(
                (
                    item
                    for item in nodes
                    if item.resource_type.value == "volume" and item.resource_id == str(args.get("identifier"))
                ),
                None,
            )
        if spec.action == "image.remove":
            return next(
                (
                    item
                    for item in nodes
                    if item.resource_type.value == "image" and item.resource_id == str(args.get("identifier"))
                ),
                None,
            )
        return None

    @staticmethod
    def _related(target_id: str, edges, nodes: list[ResourceNode], depth: int) -> list[ResourceNode]:
        adjacent: dict[str, set[str]] = {}
        for edge in edges:
            adjacent.setdefault(edge.source, set()).add(edge.target)
            adjacent.setdefault(edge.target, set()).add(edge.source)
        selected = {target_id}
        queue = deque([(target_id, 0)])
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for neighbor in adjacent.get(current, set()):
                if neighbor not in selected:
                    selected.add(neighbor)
                    queue.append((neighbor, current_depth + 1))
        return [item for item in nodes if item.id in selected]
