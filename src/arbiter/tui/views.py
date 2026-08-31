from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from arbiter.models import ApprovalInfo, ContainerInfo, PortOwner, Project, ReadinessAuthorization

TAB_PORTS = 0
TAB_CONTAINERS = 1
TAB_APPROVALS = 2
TAB_PROJECTS = 3
TAB_LOGS = 4
TAB_READINESS = 5

TAB_NAMES = ["Ports", "Containers", "Approvals", "Projects", "Logs", "Readiness"]


@dataclass
class TUIData:
    ports: list[PortOwner] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    containers: list[ContainerInfo] = field(default_factory=list)
    approvals: list[ApprovalInfo] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    readiness_authorizations: list[ReadinessAuthorization] = field(default_factory=list)


@dataclass
class TUIState:
    active_tab: int = TAB_PORTS
    selected_indices: dict[int, int] = field(
        default_factory=lambda: {
            TAB_PORTS: 0,
            TAB_CONTAINERS: 0,
            TAB_APPROVALS: 0,
            TAB_PROJECTS: 0,
            TAB_LOGS: 0,
            TAB_READINESS: 0,
        }
    )
    filter_queries: dict[int, str] = field(
        default_factory=lambda: {
            TAB_PORTS: "",
            TAB_CONTAINERS: "",
            TAB_APPROVALS: "",
            TAB_PROJECTS: "",
            TAB_LOGS: "",
            TAB_READINESS: "",
        }
    )
    is_filtering: bool = False
    show_help: bool = False
    confirm_action: dict[str, Any] | None = None
    log_container_id: str | None = None
    log_container_name: str | None = None
    log_lines: list[str] = field(default_factory=list)
    log_scroll_offset: int = 0
    status_message: str = "Ready"
    status_is_error: bool = False

    @property
    def current_selected_index(self) -> int:
        return self.selected_indices.get(self.active_tab, 0)

    def set_current_selected_index(self, index: int) -> None:
        self.selected_indices[self.active_tab] = index

    @property
    def current_filter_query(self) -> str:
        return self.filter_queries.get(self.active_tab, "")

    def set_current_filter_query(self, query: str) -> None:
        self.filter_queries[self.active_tab] = query


def format_port_row(port: PortOwner, has_conflict: bool = False) -> tuple[str, str, str, str, str]:
    port_proto = f"{port.port}/{port.protocol}"
    owner_str = port.process or port.container or port.owner_type or "unknown"
    pid_str = str(port.pid) if port.pid else "-"
    proj_svc = f"{port.project or '-'}:{port.service or '-'}" if port.project or port.service else "-"
    status_str = "⚠️ CONFLICT" if has_conflict else "● ACTIVE"
    return port_proto, owner_str, pid_str, proj_svc, status_str


def format_container_row(c: ContainerInfo) -> tuple[str, str, str, str, str]:
    name = c.name
    state = f"● {c.state}" if c.state == "running" else f"■ {c.state}"
    image = c.image[:24]
    proj_svc = f"{c.compose_project or '-'}/{c.compose_service or '-'}"
    ports_str = ",".join(f"{p.host_port}->{p.container_port}" for p in c.ports) if c.ports else "-"
    return name, state, image, proj_svc, ports_str


def format_approval_row(a: ApprovalInfo) -> tuple[str, str, str, str, str]:
    aid = a.id[:8]
    action = a.action
    risk = a.risk.value.upper()
    status = a.status.upper()
    summary = (a.summary or "-")[:35]
    return aid, action, risk, status, summary


def format_project_row(p: Project) -> tuple[str, str, str, str]:
    name = p.name
    services_count = f"{len(p.services)} services"
    ports_count = f"{len(p.ports)} ports"
    path_str = str(p.path)[:30]
    return name, services_count, ports_count, path_str


def format_readiness_authorization_row(item: ReadinessAuthorization) -> tuple[str, str, str, str]:
    return item.id[:8], item.protocol.upper(), f"{item.host}:{item.port}", ",".join(item.resolved_addresses)


def get_item_details(data: TUIData, state: TUIState, selected_item: Any) -> str:
    """Produce pretty formatted JSON / detail text for the inspector pane."""
    if not selected_item:
        return "No item selected."

    if state.active_tab == TAB_PORTS and isinstance(selected_item, PortOwner):
        p = selected_item
        conflicts = [c for c in data.conflicts if c.get("port") == p.port and c.get("protocol") == p.protocol]
        return json.dumps(
            {
                "port": p.port,
                "protocol": p.protocol,
                "owner_type": p.owner_type,
                "pid": p.pid,
                "process": p.process,
                "command": p.command,
                "container_id": p.container_id,
                "container": p.container,
                "project": p.project,
                "service": p.service,
                "source": p.source,
                "conflicts": conflicts,
            },
            indent=2,
            default=str,
        )

    if state.active_tab == TAB_CONTAINERS and isinstance(selected_item, ContainerInfo):
        c = selected_item
        return json.dumps(
            {
                "id": c.id,
                "name": c.name,
                "image": c.image,
                "state": c.state,
                "compose_project": c.compose_project,
                "compose_service": c.compose_service,
                "compose_working_dir": c.compose_working_dir,
                "ports": [
                    {
                        "host_port": p.host_port,
                        "container_port": p.container_port,
                        "protocol": p.protocol,
                        "host_ip": p.host_ip,
                    }
                    for p in c.ports
                ],
                "labels": c.labels,
            },
            indent=2,
            default=str,
        )

    if state.active_tab == TAB_APPROVALS and isinstance(selected_item, ApprovalInfo):
        a = selected_item
        return json.dumps(
            {
                "id": a.id,
                "request_id": a.request_id,
                "action": a.action,
                "risk": a.risk.value,
                "status": a.status,
                "summary": a.summary,
                "arguments": a.arguments,
                "created_at": a.created_at,
                "expires_at": a.expires_at,
            },
            indent=2,
            default=str,
        )

    if state.active_tab == TAB_PROJECTS and isinstance(selected_item, Project):
        p = selected_item
        return json.dumps(
            {
                "id": p.id,
                "name": p.name,
                "path": str(p.path),
                "services": list(p.services),
                "ports": [
                    {
                        "host_port": pt.host_port,
                        "container_port": pt.container_port,
                        "protocol": pt.protocol,
                        "service": pt.service,
                        "variable": pt.variable,
                        "source": pt.source,
                    }
                    for pt in p.ports
                ],
                "compose_files": [str(cf) for cf in p.compose_files],
            },
            indent=2,
            default=str,
        )

    if state.active_tab == TAB_READINESS and isinstance(selected_item, ReadinessAuthorization):
        return json.dumps(selected_item.model_dump(mode="json"), indent=2, default=str)

    return str(selected_item)
