import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from arbiter.llm.openai_compatible import LLMProviderError, OpenAICompatibleProvider
from arbiter.topology.models import RelationshipType, ResourceNode, ResourceType, TopologyGraph


class ResourceFilterPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terms: list[str]
    resource_types: list[ResourceType]
    statuses: list[str]
    project_terms: list[str]
    ports: list[int]
    relationships: list[RelationshipType]
    only_running: bool
    only_issues: bool
    include_neighbors: bool
    explanation: str
    confidence: float = Field(ge=0, le=1)


class IntelligenceService:
    """Turns natural language into a typed plan, then filters locally."""

    _type_aliases = {
        "project": ResourceType.PROJECT,
        "projects": ResourceType.PROJECT,
        "workspace": ResourceType.PROJECT,
        "workspaces": ResourceType.PROJECT,
        "service": ResourceType.COMPOSE_SERVICE,
        "services": ResourceType.COMPOSE_SERVICE,
        "container": ResourceType.CONTAINER,
        "containers": ResourceType.CONTAINER,
        "image": ResourceType.IMAGE,
        "images": ResourceType.IMAGE,
        "volume": ResourceType.VOLUME,
        "volumes": ResourceType.VOLUME,
        "network": ResourceType.NETWORK,
        "networks": ResourceType.NETWORK,
        "port": ResourceType.PORT,
        "ports": ResourceType.PORT,
        "process": ResourceType.PROCESS,
        "processes": ResourceType.PROCESS,
        "dockerfile": ResourceType.DOCKERFILE,
        "make": ResourceType.MAKE_TARGET,
        "runtime": ResourceType.RUNTIME,
    }
    _stop_words = {
        "a",
        "all",
        "and",
        "anything",
        "for",
        "from",
        "in",
        "is",
        "me",
        "my",
        "of",
        "on",
        "only",
        "resource",
        "resources",
        "show",
        "that",
        "the",
        "to",
        "using",
        "with",
    }

    def __init__(self, services) -> None:
        self.services = services

    async def filter(self, query: str, *, project: str | None = None, use_ai: bool = True) -> dict[str, Any]:
        source = self.services.topology.graph(project)
        plan = self.deterministic_plan(query)
        mode = "deterministic"
        fallback_reason: str | None = None
        settings = self.services.settings
        if use_ai and settings.llm_api_key and settings.filter_llm_model:
            provider = OpenAICompatibleProvider(
                settings.llm_base_url,
                settings.llm_api_key,
                settings.filter_llm_model,
                reasoning_effort="none",
                telemetry=self.services.telemetry,
            )
            try:
                raw, _usage = await provider.complete_structured(
                    self._messages(query),
                    ResourceFilterPlan.model_json_schema(),
                    name="resource_filter_plan",
                    operation="resource_filter",
                )
                plan = ResourceFilterPlan.model_validate(raw)
                mode = "ai"
            except (LLMProviderError, ValueError):
                fallback_reason = "The structured interpreter was unavailable, so the local parser was used."
        graph, matched = self.apply_plan(source, plan)
        return {
            "mode": mode,
            "plan": plan.model_dump(mode="json"),
            "graph": graph.model_dump(mode="json"),
            "matched_node_ids": sorted(matched),
            "matched_count": len(matched),
            "visible_count": len(graph.nodes),
            "source_count": len(source.nodes),
            "fallback_reason": fallback_reason,
        }

    @classmethod
    def deterministic_plan(cls, query: str) -> ResourceFilterPlan:
        lowered = query.casefold().strip()
        explicit_types = re.findall(r"\btype:([a-z_]+)", lowered)
        tokens = re.findall(r"[a-z0-9_.-]+", lowered)
        types: list[ResourceType] = []
        for token in [*explicit_types, *tokens]:
            resource_type = cls._type_aliases.get(token)
            if resource_type and resource_type not in types:
                types.append(resource_type)
        ports = sorted(
            {
                int(value)
                for value in re.findall(r"(?:\bport[: ]|:)(\d{1,5})\b", lowered)
                if 0 < int(value) < 65536
            }
        )
        statuses = [value for value in re.findall(r"\bstatus:([a-z_-]+)", lowered)]
        if "running" in tokens and "running" not in statuses:
            statuses.append("running")
        project_terms = [value.strip('"\'') for value in re.findall(r"\bproject:([^\s]+)", lowered)]
        relationship_names = {item.value.casefold(): item for item in RelationshipType}
        relationships = [
            relationship
            for name, relationship in relationship_names.items()
            if name in lowered.replace(" ", "_")
        ]
        reserved = set(cls._type_aliases) | cls._stop_words | {
            "active",
            "broken",
            "conflict",
            "conflicts",
            "failed",
            "issue",
            "issues",
            "running",
            "status",
            "type",
        }
        terms = [
            token
            for token in tokens
            if token not in reserved
            and not token.isdigit()
            and not token.startswith(("type", "status", "project", "port"))
            and token not in project_terms
        ]
        terms = list(dict.fromkeys(terms))
        only_issues = bool({"broken", "conflict", "conflicts", "failed", "issue", "issues"} & set(tokens))
        return ResourceFilterPlan(
            terms=terms,
            resource_types=types,
            statuses=statuses,
            project_terms=project_terms,
            ports=ports,
            relationships=relationships,
            only_running="running" in tokens,
            only_issues=only_issues,
            include_neighbors=True,
            explanation="Parsed locally from explicit resource, status, project, port, and text terms.",
            confidence=0.72 if any((types, statuses, project_terms, ports, terms, only_issues)) else 0.25,
        )

    @staticmethod
    def apply_plan(graph: TopologyGraph, plan: ResourceFilterPlan) -> tuple[TopologyGraph, set[str]]:
        matched = {node.id for node in graph.nodes if IntelligenceService._matches(node, plan)}
        if plan.relationships:
            relationship_nodes = {
                identifier
                for edge in graph.edges
                if edge.relationship in plan.relationships
                for identifier in (edge.source, edge.target)
            }
            matched &= relationship_nodes
        visible = set(matched)
        if plan.include_neighbors:
            for edge in graph.edges:
                if edge.source in matched or edge.target in matched:
                    visible.update((edge.source, edge.target))
        nodes = [node for node in graph.nodes if node.id in visible]
        edges = [edge for edge in graph.edges if edge.source in visible and edge.target in visible]
        return (
            TopologyGraph(nodes=nodes, edges=edges, generated_at=graph.generated_at, warnings=graph.warnings),
            matched,
        )

    @staticmethod
    def _matches(node: ResourceNode, plan: ResourceFilterPlan) -> bool:
        attributes = node.attributes or {}
        encoded_attributes = json.dumps(attributes, default=str)
        haystack = f"{node.label} {node.resource_id} {node.status or ''} {encoded_attributes}".casefold()
        if plan.resource_types and node.resource_type not in plan.resource_types:
            return False
        if plan.terms and not all(term.casefold() in haystack for term in plan.terms):
            return False
        if plan.statuses and not any(status.casefold() in haystack for status in plan.statuses):
            return False
        if plan.project_terms and not all(term.casefold() in haystack for term in plan.project_terms):
            return False
        if plan.ports and not set(plan.ports) <= IntelligenceService._ports(node):
            return False
        if plan.only_running and not IntelligenceService._is_running(node):
            return False
        return not (plan.only_issues and not IntelligenceService._has_issue(node))

    @staticmethod
    def _ports(node: ResourceNode) -> set[int]:
        values: set[int] = set()

        def visit(value: Any, key: str = "") -> None:
            if isinstance(value, dict):
                for child_key, child in value.items():
                    visit(child, str(child_key))
            elif isinstance(value, list):
                for child in value:
                    visit(child, key)
            elif "port" in key.casefold() and isinstance(value, int) and 0 < value < 65536:
                values.add(value)

        visit(node.attributes)
        if node.resource_type is ResourceType.PORT:
            match = re.search(r"\d{1,5}", f"{node.resource_id} {node.label}")
            if match:
                values.add(int(match.group()))
        return values

    @staticmethod
    def _is_running(node: ResourceNode) -> bool:
        state = f"{node.status or ''} {node.attributes.get('state', '')}".casefold()
        is_live_process = node.resource_type is ResourceType.PROCESS and bool(node.resource_id)
        return "running" in state or "listen" in state or is_live_process

    @staticmethod
    def _has_issue(node: ResourceNode) -> bool:
        state = f"{node.status or ''} {node.attributes.get('state', '')} {node.attributes.get('health', '')}".casefold()
        return any(word in state for word in ("conflict", "dead", "error", "exited", "failed", "unhealthy"))

    @staticmethod
    def _messages(query: str) -> list[dict[str, str]]:
        resource_types = ", ".join(item.value for item in ResourceType)
        relationships = ", ".join(item.value for item in RelationshipType)
        return [
            {
                "role": "system",
                "content": (
                    "Convert a local developer resource search into the supplied strict JSON schema. "
                    f"Allowed resource_types: {resource_types}. Allowed relationships: {relationships}. "
                    "Use only literal constraints supported by the request. Keep terms short and lowercase. "
                    "Set include_neighbors true unless the user explicitly asks for exact matches only. "
                    "Never invent project names or ports. Return every schema field."
                ),
            },
            {"role": "user", "content": query},
        ]
