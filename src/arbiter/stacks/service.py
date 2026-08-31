import contextlib
import http.client
import shutil
import socket
import time
import urllib.parse
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from arbiter.compose.editor import ComposeEditor, change_env_port
from arbiter.compose.service import ComposeService
from arbiter.config import Settings, get_settings
from arbiter.docker.service import DockerService
from arbiter.files.service import FileService
from arbiter.models import (
    ActionSpec,
    BootOrderStage,
    PortReconciliationChange,
    ReadinessGate,
    ReadinessPolicyStatus,
    ReadinessProbeResult,
    ReadinessProbeType,
    Risk,
    Stack,
    StackBootPlan,
    StackProjectMember,
    StackSwitchResult,
    utcnow,
)
from arbiter.persistence.database import Database
from arbiter.persistence.repositories import StackRepository
from arbiter.ports.service import PortService
from arbiter.projects.service import ProjectService
from arbiter.readiness import ReadinessPolicyService
from arbiter.safety.approvals import ApprovalService


class StackService:
    def __init__(
        self,
        database: Database,
        projects: ProjectService,
        ports: PortService,
        docker: DockerService,
        compose: ComposeService | None = None,
        files: FileService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.database = database
        self.projects = projects
        self.ports = ports
        self.docker = docker
        self.compose = compose or ComposeService()
        self.editor = ComposeEditor()
        self.files = files
        self.settings = settings or get_settings()
        self.readiness_policy = ReadinessPolicyService(database, projects)

    def list_stacks(self) -> list[Stack]:
        with self.database.sessions() as session:
            return StackRepository(session).list()

    def get_stack(self, identifier: str) -> Stack:
        with self.database.sessions() as session:
            stack = StackRepository(session).get(identifier)
        if not stack:
            raise LookupError(f"Stack preset not found: {identifier}")
        return stack

    def get_active_stack(self) -> Stack | None:
        with self.database.sessions() as session:
            return StackRepository(session).get_active()

    def save_stack(self, stack: Stack) -> Stack:
        stack.updated_at = utcnow()
        with self.database.sessions() as session:
            return StackRepository(session).save(stack)

    def create_stack(
        self,
        name: str,
        description: str | None = None,
        projects: list[StackProjectMember] | list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
    ) -> Stack:
        member_list: list[StackProjectMember] = []
        if projects:
            for item in projects:
                if isinstance(item, StackProjectMember):
                    member_list.append(item)
                elif isinstance(item, dict):
                    member_list.append(StackProjectMember.model_validate(item))
        stack = Stack(
            id=str(uuid4()),
            name=name,
            description=description,
            projects=member_list,
            tags=tags or [],
            status="inactive",
            is_active=False,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        return self.save_stack(stack)

    def update_stack(
        self,
        identifier: str,
        name: str | None = None,
        description: str | None = None,
        projects: list[StackProjectMember] | list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
    ) -> Stack:
        stack = self.get_stack(identifier)
        if name is not None:
            stack.name = name
        if description is not None:
            stack.description = description
        if projects is not None:
            member_list: list[StackProjectMember] = []
            for item in projects:
                if isinstance(item, StackProjectMember):
                    member_list.append(item)
                elif isinstance(item, dict):
                    member_list.append(StackProjectMember.model_validate(item))
            stack.projects = member_list
        if tags is not None:
            stack.tags = tags
        return self.save_stack(stack)

    def delete_stack(self, identifier: str) -> bool:
        with self.database.sessions() as session:
            return StackRepository(session).delete(identifier)

    def seed_default_presets(self) -> list[Stack]:
        """Seed high-quality, pre-configured stack presets tailored to registered projects or standard profiles."""
        all_projects = self.projects.list_projects()
        project_by_name = {p.name.lower(): p for p in all_projects}

        presets_to_create = [
            {
                "name": "Billing Microservices",
                "description": "Payment Gateway, Webhook Handlers, Redis Queue, and Postgres Ledger",
                "tags": ["fintech", "microservices", "backend"],
                "keywords": ["billing", "payment", "ledger", "postgres", "redis", "finance"],
                "default_members": [
                    {
                        "project_name": "billing-infra",
                        "depends_on": [],
                        "boot_stage": 0,
                        "readiness_gates": [
                            {"probe_type": "tcp_port", "host": "127.0.0.1", "port": 5432, "service": "postgres"},
                            {"probe_type": "tcp_port", "host": "127.0.0.1", "port": 6379, "service": "redis"},
                        ],
                    },
                    {
                        "project_name": "billing-api",
                        "depends_on": ["billing-infra"],
                        "boot_stage": 1,
                        "env_overrides": {"PORT": "8001", "DB_PORT": "5432", "REDIS_PORT": "6379"},
                        "readiness_gates": [
                            {
                                "probe_type": "http_get",
                                "host": "127.0.0.1",
                                "port": 8001,
                                "path": "/health",
                                "service": "billing-api",
                            }
                        ],
                    },
                    {
                        "project_name": "billing-worker",
                        "depends_on": ["billing-api"],
                        "boot_stage": 2,
                        "readiness_gates": [{"probe_type": "docker_health", "service": "billing-worker"}],
                    },
                ],
            },
            {
                "name": "AI Pipeline + Vector DB",
                "description": "Qdrant Vector Store, Embedding Generator Worker, and FastAPI LLM Gateway",
                "tags": ["ai", "embeddings", "vector-search", "llm"],
                "keywords": ["ai", "vector", "qdrant", "embedding", "pipeline", "llm"],
                "default_members": [
                    {
                        "project_name": "vector-store",
                        "depends_on": [],
                        "boot_stage": 0,
                        "readiness_gates": [
                            {"probe_type": "tcp_port", "host": "127.0.0.1", "port": 6333, "service": "qdrant"}
                        ],
                    },
                    {
                        "project_name": "ai-pipeline-core",
                        "depends_on": ["vector-store"],
                        "boot_stage": 1,
                        "env_overrides": {"QDRANT_PORT": "6333", "PORT": "8000"},
                        "readiness_gates": [
                            {
                                "probe_type": "http_get",
                                "host": "127.0.0.1",
                                "port": 8000,
                                "path": "/health",
                                "service": "ai-pipeline",
                            }
                        ],
                    },
                ],
            },
            {
                "name": "Frontend App + Mock API",
                "description": "Next.js / Vite Single Page Application paired with Local Mock API Server",
                "tags": ["frontend", "web", "mock-api"],
                "keywords": ["frontend", "ui", "mock", "api", "web", "client"],
                "default_members": [
                    {
                        "project_name": "mock-api",
                        "depends_on": [],
                        "boot_stage": 0,
                        "readiness_gates": [
                            {"probe_type": "tcp_port", "host": "127.0.0.1", "port": 4000, "service": "mock-api"}
                        ],
                    },
                    {
                        "project_name": "frontend-web",
                        "depends_on": ["mock-api"],
                        "boot_stage": 1,
                        "env_overrides": {"API_URL": "http://127.0.0.1:4000", "PORT": "3000"},
                        "readiness_gates": [
                            {"probe_type": "tcp_port", "host": "127.0.0.1", "port": 3000, "service": "frontend"}
                        ],
                    },
                ],
            },
        ]

        created_stacks: list[Stack] = []
        for preset in presets_to_create:
            members: list[StackProjectMember] = []
            for dm in preset["default_members"]:
                matched_proj = None
                for pname, proj in project_by_name.items():
                    if pname in dm["project_name"] or dm["project_name"] in pname:
                        matched_proj = proj
                        break
                proj_id = matched_proj.id if matched_proj else str(uuid4())
                proj_name = matched_proj.name if matched_proj else dm["project_name"]
                gates = [ReadinessGate.model_validate(g) for g in dm.get("readiness_gates", [])]
                members.append(
                    StackProjectMember(
                        project_id=proj_id,
                        project_name=proj_name,
                        env_overrides=dm.get("env_overrides", {}),
                        depends_on=dm.get("depends_on", []),
                        readiness_gates=gates,
                        boot_stage=dm.get("boot_stage", 0),
                    )
                )

            existing = None
            with contextlib.suppress(LookupError):
                existing = self.get_stack(preset["name"])

            if not existing:
                stack = self.create_stack(
                    name=preset["name"],
                    description=preset["description"],
                    projects=members,
                    tags=preset["tags"],
                )
                created_stacks.append(stack)

        return created_stacks

    def compute_boot_plan(self, stack: Stack) -> StackBootPlan:
        """Compute topological boot order DAG and stage grouping for all projects in the stack."""
        if not stack.projects:
            return StackBootPlan(
                stack_id=stack.id,
                stack_name=stack.name,
                stages=[],
                total_stages=0,
                dependencies_valid=True,
                cycle_detected=False,
            )

        name_to_id = {m.project_name.lower(): m.project_id for m in stack.projects}
        id_to_member = {m.project_id: m for m in stack.projects}
        for m in stack.projects:
            name_to_id[m.project_id] = m.project_id

        graph: dict[str, set[str]] = defaultdict(set)
        in_degree: dict[str, int] = {m.project_id: 0 for m in stack.projects}

        for member in stack.projects:
            for dep in member.depends_on:
                dep_id = name_to_id.get(dep.lower()) or dep
                if dep_id in id_to_member:
                    graph[dep_id].add(member.project_id)
                    in_degree[member.project_id] += 1

        queue = deque([pid for pid, deg in in_degree.items() if deg == 0])
        stages_map: dict[int, list[str]] = defaultdict(list)
        stage_level: dict[str, int] = {}

        for pid in queue:
            member = id_to_member[pid]
            base_stage = max(0, member.boot_stage)
            stage_level[pid] = base_stage
            stages_map[base_stage].append(pid)

        processed_count = 0
        while queue:
            curr = queue.popleft()
            processed_count += 1
            curr_stage = stage_level[curr]

            for neighbor in graph[curr]:
                in_degree[neighbor] -= 1
                new_stage = max(stage_level.get(neighbor, 0), curr_stage + 1, id_to_member[neighbor].boot_stage)
                stage_level[neighbor] = new_stage

                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        cycle_detected = processed_count < len(stack.projects)
        if cycle_detected:
            unvisited = [pid for pid in stack.projects if pid.project_id not in stage_level]
            for m in unvisited:
                stage_level[m.project_id] = 99
                stages_map[99].append(m.project_id)

        stages_by_level: dict[int, list[str]] = defaultdict(list)
        for pid, lvl in stage_level.items():
            stages_by_level[lvl].append(pid)

        boot_stages: list[BootOrderStage] = []
        for index, (_lvl, pids) in enumerate(sorted(stages_by_level.items())):
            gates: list[ReadinessGate] = []
            for pid in pids:
                member = id_to_member[pid]
                if member.readiness_gates:
                    gates.extend(member.readiness_gates)
                else:
                    with contextlib.suppress(Exception):
                        proj = self.projects.get_project(pid)
                        for binding in proj.ports:
                            gates.append(
                                ReadinessGate(
                                    probe_type=ReadinessProbeType.TCP_PORT,
                                    host=binding.host_ip or "127.0.0.1",
                                    port=binding.host_port,
                                    service=binding.service or proj.name,
                                )
                            )

            boot_stages.append(
                BootOrderStage(
                    stage=index,
                    projects=[id_to_member[pid].project_name for pid in pids],
                    readiness_gates=gates,
                    description=f"Boot Stage {index + 1} ({len(pids)} project{'s' if len(pids) > 1 else ''})",
                )
            )

        return StackBootPlan(
            stack_id=stack.id,
            stack_name=stack.name,
            stages=boot_stages,
            total_stages=len(boot_stages),
            dependencies_valid=not cycle_detected,
            cycle_detected=cycle_detected,
            error="Circular dependency detected among stack projects" if cycle_detected else None,
        )

    def check_readiness_gate(self, gate: ReadinessGate) -> ReadinessProbeResult:
        """Probe a single readiness gate (TCP socket probe, HTTP GET endpoint, or Docker health check)."""
        start = time.perf_counter()
        probe_type = gate.probe_type
        decision = self.readiness_policy.evaluate(gate)
        if decision.status != ReadinessPolicyStatus.ALLOWED:
            return ReadinessProbeResult(
                service=gate.service,
                probe_type=probe_type,
                target=self._gate_target(gate),
                healthy=False,
                message=decision.reason,
                policy_status=decision.status,
                policy_reason=decision.reason,
                resolved_addresses=list(decision.resolved_addresses),
            )

        if probe_type == ReadinessProbeType.TCP_PORT:
            port = gate.port
            if not port:
                return ReadinessProbeResult(
                    service=gate.service,
                    probe_type=probe_type,
                    target=f"{gate.host}:[unspecified]",
                    healthy=False,
                    message="No port specified for TCP probe",
                )
            try:
                connection = socket.create_connection(
                    (decision.resolved_addresses[0], port), timeout=min(gate.timeout_seconds, 2.0)
                )
                connection.close()
                latency = (time.perf_counter() - start) * 1000.0
                return ReadinessProbeResult(
                    service=gate.service,
                    probe_type=probe_type,
                    target=f"{gate.host}:{port}",
                    healthy=True,
                    latency_ms=round(latency, 2),
                    message=f"TCP port {port} is open and accepting connections",
                    policy_reason=decision.reason,
                    resolved_addresses=list(decision.resolved_addresses),
                )
            except Exception as exc:
                latency = (time.perf_counter() - start) * 1000.0
                return ReadinessProbeResult(
                    service=gate.service,
                    probe_type=probe_type,
                    target=f"{gate.host}:{port}",
                    healthy=False,
                    latency_ms=round(latency, 2),
                    message=f"TCP port {port} unavailable: {exc}",
                    policy_reason=decision.reason,
                    resolved_addresses=list(decision.resolved_addresses),
                )

        elif probe_type == ReadinessProbeType.HTTP_GET:
            try:
                code, final_url, final_decision = self._http_get(gate, decision)
                latency = (time.perf_counter() - start) * 1000.0
                healthy = (200 <= code < 400) if gate.expected_status == 200 else code == gate.expected_status
                return ReadinessProbeResult(
                    service=gate.service,
                    probe_type=probe_type,
                    target=final_url,
                    healthy=healthy,
                    status_code=code,
                    latency_ms=round(latency, 2),
                    message=f"HTTP {code} OK" if healthy else f"Unexpected HTTP status {code}",
                    policy_reason=final_decision.reason,
                    resolved_addresses=list(final_decision.resolved_addresses),
                )
            except Exception as exc:
                latency = (time.perf_counter() - start) * 1000.0
                return ReadinessProbeResult(
                    service=gate.service,
                    probe_type=probe_type,
                    target=self._gate_target(gate),
                    healthy=False,
                    latency_ms=round(latency, 2),
                    message=f"HTTP connection failed: {exc}",
                    policy_reason=decision.reason,
                    resolved_addresses=list(decision.resolved_addresses),
                )

        elif probe_type == ReadinessProbeType.DOCKER_HEALTH:
            containers = self.docker.list_containers()
            target_name = gate.service or ""
            match = next(
                (
                    c
                    for c in containers
                    if (
                        target_name
                        and (c.name == target_name or c.compose_service == target_name or target_name in c.name)
                    )
                ),
                None,
            )
            latency = (time.perf_counter() - start) * 1000.0
            if match:
                healthy = match.state == "running" and (match.health in {None, "healthy", "n/a"})
                return ReadinessProbeResult(
                    service=gate.service,
                    probe_type=probe_type,
                    target=match.name,
                    healthy=healthy,
                    latency_ms=round(latency, 2),
                    message=f"Container {match.name} state={match.state}, health={match.health or 'healthy'}",
                )
            return ReadinessProbeResult(
                service=gate.service,
                probe_type=probe_type,
                target=target_name or "docker_container",
                healthy=False,
                latency_ms=round(latency, 2),
                message=f"Container for {target_name} not found or not running",
            )

        return ReadinessProbeResult(
            service=gate.service,
            probe_type=probe_type,
            target="unknown",
            healthy=False,
            message=f"Unsupported probe type: {probe_type}",
        )

    def request_readiness_authorizations(self, identifier: str) -> list[dict[str, object]]:
        """Create deduplicated approval requests for non-local gates in one stack."""
        stack = self.get_stack(identifier)
        plan = self.compute_boot_plan(stack)
        approvals = ApprovalService(self.database)
        pending = [
            item for item in approvals.list() if item.status == "pending" and item.action == "readiness.authorize"
        ]
        requested: list[dict[str, object]] = []
        seen: set[str] = set()
        for stage in plan.stages:
            for gate in stage.readiness_gates:
                decision = self.readiness_policy.evaluate(gate)
                if decision.status != ReadinessPolicyStatus.APPROVAL_REQUIRED or decision.target_key in seen:
                    continue
                seen.add(decision.target_key)
                existing = next(
                    (
                        item
                        for item in pending
                        if item.arguments.get("target_key") == decision.target_key
                        and sorted(item.arguments.get("resolved_addresses", [])) == sorted(decision.resolved_addresses)
                    ),
                    None,
                )
                if existing:
                    requested.append({"status": "approval_required", "approval": existing.model_dump(mode="json")})
                    continue
                spec = ActionSpec(
                    action="readiness.authorize",
                    risk=Risk.MEDIUM_RISK,
                    summary=f"Allow readiness probe to {decision.protocol}://{decision.host}:{decision.port}",
                    arguments={
                        "stack_id": stack.id,
                        "target_key": decision.target_key,
                        "gate": gate.model_dump(mode="json"),
                        "resolved_addresses": list(decision.resolved_addresses),
                    },
                )
                created = approvals.create(spec)
                requested.append({"status": "approval_required", "approval": created.model_dump(mode="json")})
        return requested

    @staticmethod
    def _gate_target(gate: ReadinessGate) -> str:
        if gate.probe_type == ReadinessProbeType.DOCKER_HEALTH:
            return gate.service or "docker_container"
        scheme = "http://" if gate.probe_type == ReadinessProbeType.HTTP_GET else ""
        port = gate.port or (80 if gate.probe_type == ReadinessProbeType.HTTP_GET else "[unspecified]")
        normalized_host = gate.host.strip("[]")
        display_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
        return f"{scheme}{display_host}:{port}{gate.path or '/' if scheme else ''}"

    def _http_get(self, gate, initial_decision):
        url = self._gate_target(gate)
        decision = initial_decision
        for redirect_count in range(4):
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "http" or parsed.username or parsed.password or not parsed.hostname:
                raise ValueError("Readiness redirects must use a plain HTTP URL without credentials")
            port = parsed.port or 80
            redirected_gate = ReadinessGate.model_validate(
                {
                    **gate.model_dump(mode="python"),
                    "host": parsed.hostname,
                    "port": port,
                    "path": urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, "")),
                }
            )
            decision = self.readiness_policy.evaluate(redirected_gate)
            if decision.status != ReadinessPolicyStatus.ALLOWED:
                raise PermissionError(f"Redirect destination denied: {decision.reason}")
            last_error: Exception | None = None
            for address in decision.resolved_addresses:
                connection = http.client.HTTPConnection(address, port, timeout=min(gate.timeout_seconds, 3.0))
                header_host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
                host_header = header_host if port == 80 else f"{header_host}:{port}"
                try:
                    connection.request(
                        "GET",
                        urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, "")),
                        headers={"Host": host_header, "User-Agent": "Arbiter-Readiness-Probe/1.0"},
                    )
                    response = connection.getresponse()
                    status = response.status
                    location = response.getheader("Location")
                    response.close()
                    if 300 <= status < 400 and location:
                        if redirect_count >= 3:
                            raise ValueError("Readiness endpoint exceeded the redirect limit")
                        url = urllib.parse.urljoin(url, location)
                        break
                    return status, url, decision
                except (OSError, http.client.HTTPException) as exc:
                    last_error = exc
                finally:
                    connection.close()
            else:
                raise last_error or ConnectionError("Readiness HTTP connection failed")
        raise ValueError("Readiness endpoint exceeded the redirect limit")

    def check_stack_readiness(self, identifier: str) -> list[ReadinessProbeResult]:
        """Check all readiness gates for all projects in the given stack preset."""
        stack = self.get_stack(identifier)
        boot_plan = self.compute_boot_plan(stack)
        results: list[ReadinessProbeResult] = []
        for stage in boot_plan.stages:
            for gate in stage.readiness_gates:
                results.append(self.check_readiness_gate(gate))
        return results

    def readiness_policy_failures(self, identifier: str) -> list[ReadinessProbeResult]:
        """Return denied gates without opening sockets or running Docker checks."""
        stack = self.get_stack(identifier)
        failures: list[ReadinessProbeResult] = []
        for stage in self.compute_boot_plan(stack).stages:
            for gate in stage.readiness_gates:
                decision = self.readiness_policy.evaluate(gate)
                if decision.status == ReadinessPolicyStatus.ALLOWED:
                    continue
                failures.append(
                    ReadinessProbeResult(
                        service=gate.service,
                        probe_type=gate.probe_type,
                        target=self._gate_target(gate),
                        healthy=False,
                        message=decision.reason,
                        policy_status=decision.status,
                        policy_reason=decision.reason,
                        resolved_addresses=list(decision.resolved_addresses),
                    )
                )
        return failures

    def wait_for_readiness_gates(
        self, gates: list[ReadinessGate], max_wait_seconds: float = 10.0, poll_interval: float = 0.3
    ) -> tuple[bool, list[ReadinessProbeResult]]:
        """Poll readiness gates until all pass or timeout expires."""
        if not gates:
            return True, []

        deadline = time.perf_counter() + max_wait_seconds
        last_results: list[ReadinessProbeResult] = []

        while time.perf_counter() < deadline:
            all_healthy = True
            current_results: list[ReadinessProbeResult] = []
            for gate in gates:
                res = self.check_readiness_gate(gate)
                current_results.append(res)
                if not res.healthy:
                    all_healthy = False
            last_results = current_results
            if all_healthy:
                return True, last_results
            time.sleep(poll_interval)

        return False, last_results

    def switch_stack(
        self,
        target_identifier: str,
        hibernate_current: bool = True,
        wait_for_readiness: bool = True,
        resolve_port_conflicts: bool = True,
    ) -> StackSwitchResult:
        """1-Click Context Switcher: Spin down / hibernate Stack A and spin up Stack B seamlessly."""
        target_stack = self.get_stack(target_identifier)
        previous_stack = self.get_active_stack()
        previous_stack_id = previous_stack.id if previous_stack else None

        policy_failures = self.readiness_policy_failures(target_stack.id) if wait_for_readiness else []
        if policy_failures:
            return StackSwitchResult(
                previous_stack_id=previous_stack_id,
                target_stack_id=target_stack.id,
                readiness_results=policy_failures,
                status="blocked",
                verified=False,
                error="Readiness destination access must be approved before switching stacks",
            )

        stopped_projects: list[str] = []
        started_projects: list[str] = []
        port_reconciliations: list[PortReconciliationChange] = []
        env_changes: list[dict[str, Any]] = []
        readiness_results: list[ReadinessProbeResult] = []

        target_member_project_ids = {m.project_id for m in target_stack.projects}
        target_member_project_names = {m.project_name.lower() for m in target_stack.projects}

        # Step 1: Spin down / Hibernate unneeded projects from previous stack / active containers
        all_registered = self.projects.list_projects()
        for proj in all_registered:
            is_in_target = proj.id in target_member_project_ids or proj.name.lower() in target_member_project_names
            if not is_in_target and proj.compose_files and hibernate_current:
                with contextlib.suppress(Exception):
                    self.compose.stop(proj.compose_files[0])
                    stopped_projects.append(proj.name)

        # Step 2: Apply dynamic .env overrides and resolve port collisions for target projects
        for member in target_stack.projects:
            try:
                proj = self.projects.get_project(member.project_id)
            except LookupError:
                proj = next((p for p in all_registered if p.name.lower() == member.project_name.lower()), None)
                if not proj:
                    continue

            # Apply stack-specific .env overrides
            if member.env_overrides and (proj.path / ".env").exists():
                env_file = proj.path / ".env"
                stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
                backup = env_file.with_name(f".env.bak.{stamp}")
                shutil.copy2(env_file, backup)
                lines = env_file.read_text().splitlines()
                updated_keys = set()
                new_lines = []
                for line in lines:
                    stripped = line.strip()
                    if "=" in stripped and not stripped.startswith("#"):
                        key, _ = stripped.split("=", 1)
                        key = key.strip()
                        if key in member.env_overrides:
                            new_lines.append(f"{key}={member.env_overrides[key]}")
                            updated_keys.add(key)
                            continue
                    new_lines.append(line)
                for key, val in member.env_overrides.items():
                    if key not in updated_keys:
                        new_lines.append(f"{key}={val}")
                env_file.write_text("\n".join(new_lines) + "\n")
                env_changes.append(
                    {
                        "project": proj.name,
                        "file": str(env_file),
                        "backup": str(backup),
                        "overrides": member.env_overrides,
                    }
                )

            # Resolve port collisions dynamically
            if resolve_port_conflicts and proj.compose_files:
                refreshed_proj = self.projects.refresh_project(proj.id)
                plan = self.ports.plan_port_reconciliation(refreshed_proj)
                if plan.changes:
                    compose_file = proj.compose_files[0]
                    for change in plan.changes:
                        port_reconciliations.append(change)
                        if change.env_variable and (proj.path / ".env").exists():
                            with contextlib.suppress(Exception):
                                change_env_port(
                                    proj.path / ".env",
                                    change.env_variable,
                                    change.requested_port,
                                    change.suggested_port,
                                )
                        elif change.service:
                            with contextlib.suppress(Exception):
                                self.editor.change_service_host_port(
                                    compose_file,
                                    change.service,
                                    change.requested_port,
                                    change.suggested_port,
                                    validate=False,
                                )

        # Step 3: Boot sequence stage-by-stage following topological dependencies and readiness gates
        boot_plan = self.compute_boot_plan(target_stack)
        overall_verified = True

        for stage in boot_plan.stages:
            for proj_name in stage.projects:
                proj = next(
                    (p for p in all_registered if p.name.lower() == proj_name.lower() or p.id == proj_name), None
                )
                if proj and proj.compose_files:
                    with contextlib.suppress(Exception):
                        self.compose.start(proj.compose_files[0])
                        started_projects.append(proj.name)

            if wait_for_readiness and stage.readiness_gates:
                passed, stage_results = self.wait_for_readiness_gates(
                    stage.readiness_gates, max_wait_seconds=5.0, poll_interval=0.2
                )
                readiness_results.extend(stage_results)
                if not passed:
                    overall_verified = False

        # Step 4: Update active stack state in persistence
        with self.database.sessions() as session:
            repo = StackRepository(session)
            repo.set_active(target_stack.id)

        return StackSwitchResult(
            id=str(uuid4()),
            previous_stack_id=previous_stack_id,
            target_stack_id=target_stack.id,
            stopped_projects=stopped_projects,
            started_projects=started_projects,
            port_reconciliations=port_reconciliations,
            env_changes=env_changes,
            readiness_results=readiness_results,
            status="completed" if overall_verified else "degraded",
            verified=overall_verified,
        )

    def stop_stack(self, identifier: str, hibernate: bool = True) -> dict[str, Any]:
        """Stop or hibernate all projects in the specified stack."""
        stack = self.get_stack(identifier)
        stopped = []
        all_registered = self.projects.list_projects()
        member_ids = {m.project_id for m in stack.projects}
        member_names = {m.project_name.lower() for m in stack.projects}

        for proj in all_registered:
            if (proj.id in member_ids or proj.name.lower() in member_names) and proj.compose_files:
                with contextlib.suppress(Exception):
                    self.compose.stop(proj.compose_files[0])
                    stopped.append(proj.name)

        with self.database.sessions() as session:
            repo = StackRepository(session)
            stack.is_active = False
            stack.status = "hibernated" if hibernate else "inactive"
            repo.save(stack)

        return {"stopped_projects": stopped, "status": "hibernated" if hibernate else "stopped"}
