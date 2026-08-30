import difflib
from pathlib import Path
from typing import Any

from arbiter.compose.parser import VARIABLE_RE, inspect_compose, load_env
from arbiter.config_intelligence.models import (
    EnvVarAuditItem,
    EnvVarAuditStatus,
    PortDriftItem,
    PortDriftType,
    ProjectConfigDrift,
    StateTransition,
    TimeTravelPreview,
    VisualDiff,
    VisualDiffLine,
)
from arbiter.models import ActionSpec, Project
from arbiter.security import is_placeholder_secret, is_secret_key, mask_secret

ENV_EXAMPLE_NAMES = (
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
    ".env.default",
    "example.env",
)


def find_env_example_file(project_path: Path) -> Path | None:
    """Find nearby example or template environment files."""
    for name in ENV_EXAMPLE_NAMES:
        candidate = project_path / name
        if candidate.is_file():
            return candidate
    return None


def parse_env_comments(path: Path) -> dict[str, str]:
    """Extract inline or header comments associated with environment variables."""
    comments: dict[str, str] = {}
    if not path.is_file():
        return comments
    current_comment: list[str] = []
    for raw_line in path.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            current_comment = []
            continue
        if line.startswith("#"):
            current_comment.append(line.lstrip("#").strip())
            continue
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            if current_comment:
                comments[key] = " ".join(current_comment)
                current_comment = []
    return comments


class ConfigIntelligenceService:
    def __init__(self, services) -> None:
        self.services = services

    def audit_project_config(self, identifier: str) -> ProjectConfigDrift:
        project = self.services.projects.get_project(identifier)
        return self._audit_project(project)

    def audit_all_projects(self) -> list[ProjectConfigDrift]:
        projects = self.services.projects.list_projects()
        return [self._audit_project(proj) for proj in projects]

    def _audit_project(self, project: Project) -> ProjectConfigDrift:
        root = project.path
        env_file = root / ".env"
        example_file = find_env_example_file(root)

        env_vars = load_env(env_file) if env_file.is_file() else {}
        example_vars = load_env(example_file) if example_file else {}
        example_comments = parse_env_comments(example_file) if example_file else {}

        # 1. Safe Env Variable Audit
        env_audit: list[EnvVarAuditItem] = []
        missing_vars: list[EnvVarAuditItem] = []

        all_keys = set(example_vars.keys()) | set(env_vars.keys())
        for key in sorted(all_keys):
            is_sec = is_secret_key(key)
            in_env = key in env_vars
            in_example = key in example_vars

            env_val = env_vars.get(key)
            example_val = example_vars.get(key)
            comment = example_comments.get(key)

            masked_val = mask_secret(env_val) if in_env and env_val is not None else None
            example_preview = mask_secret(example_val) if (is_sec and example_val) else example_val

            if not in_env and in_example:
                status = EnvVarAuditStatus.MISSING
                item = EnvVarAuditItem(
                    key=key,
                    status=status,
                    is_secret=is_sec,
                    masked_value=None,
                    example_preview=example_preview,
                    comment=comment,
                    recommendation=f"Add {key} to .env (see {example_file.name if example_file else '.env.example'})",
                )
                env_audit.append(item)
                missing_vars.append(item)
            elif in_env and not in_example:
                status = EnvVarAuditStatus.UNDOCUMENTED
                env_audit.append(
                    EnvVarAuditItem(
                        key=key,
                        status=status,
                        is_secret=is_sec,
                        masked_value=masked_val,
                        example_preview=None,
                        comment=comment,
                        recommendation=f"Document {key} in {example_file.name if example_file else '.env.example'}",
                    )
                )
            else:
                if env_val == "":
                    status = EnvVarAuditStatus.EMPTY
                    rec = f"Provide a value for {key} in .env"
                elif is_sec and is_placeholder_secret(env_val or ""):
                    status = EnvVarAuditStatus.PLACEHOLDER
                    rec = f"Replace placeholder secret value for {key} in .env"
                else:
                    status = EnvVarAuditStatus.OK
                    rec = None

                env_audit.append(
                    EnvVarAuditItem(
                        key=key,
                        status=status,
                        is_secret=is_sec,
                        masked_value=masked_val,
                        example_preview=example_preview,
                        comment=comment,
                        recommendation=rec,
                    )
                )

        # 2. Port Drift Detection
        port_drifts: list[PortDriftItem] = []
        referenced_env_vars: set[str] = set()

        for compose_file in project.compose_files:
            if not compose_file.is_file():
                continue
            raw_text = compose_file.read_text(errors="replace")

            # Check variable interpolations in compose
            for match in VARIABLE_RE.finditer(raw_text):
                var_name = match.group("name")
                default_val = match.group("default")
                referenced_env_vars.add(var_name)

                # If variable looks like a port variable or default is digits
                is_port_var = "port" in var_name.lower() or (default_val and default_val.isdigit())
                if is_port_var:
                    env_val_str = env_vars.get(var_name)
                    example_val_str = example_vars.get(var_name)

                    env_port = int(env_val_str) if env_val_str and env_val_str.isdigit() else None
                    default_port = int(default_val) if default_val and default_val.isdigit() else None
                    example_port = int(example_val_str) if example_val_str and example_val_str.isdigit() else None

                    # Check compose default vs env
                    if default_port is not None and env_port is not None and default_port != env_port:
                        port_drifts.append(
                            PortDriftItem(
                                variable=var_name,
                                env_value=env_port,
                                compose_default=default_port,
                                example_value=example_port,
                                drift_type=PortDriftType.COMPOSE_DEFAULT_MISMATCH,
                                severity="info",
                                message=(
                                    f"Environment variable {var_name}={env_port} overrides "
                                    f"Compose default {default_port}"
                                ),
                                suggested_fix=f"Keep .env at {env_port} or sync compose default to {env_port}",
                            )
                        )

                    # Check example vs env
                    if example_port is not None and env_port is not None and example_port != env_port:
                        port_drifts.append(
                            PortDriftItem(
                                variable=var_name,
                                env_value=env_port,
                                compose_default=default_port,
                                example_value=example_port,
                                drift_type=PortDriftType.EXAMPLE_MISMATCH,
                                severity="info",
                                message=(
                                    f"Environment variable {var_name}={env_port} diverges from "
                                    f"example value {example_port}"
                                ),
                                suggested_fix="Update .env.example or keep local override in .env",
                            )
                        )

                    # Check unresolved variable in compose
                    if env_val_str is None and default_val is None:
                        port_drifts.append(
                            PortDriftItem(
                                variable=var_name,
                                env_value=None,
                                compose_default=None,
                                example_value=example_port,
                                drift_type=PortDriftType.UNRESOLVED_COMPOSE_VARIABLE,
                                severity="critical",
                                message=(
                                    f"Compose references ${{{var_name}}} which has no default and is missing from .env"
                                ),
                                suggested_fix=f"Define {var_name} in .env",
                            )
                        )

            # Check unreferenced port variables in .env
            for key, val in env_vars.items():
                if ("port" in key.lower()) and key not in referenced_env_vars and val.isdigit():
                    port_drifts.append(
                        PortDriftItem(
                            variable=key,
                            env_value=int(val),
                            drift_type=PortDriftType.UNREFERENCED_ENV_PORT,
                            severity="warning",
                            message=(
                                f"Variable {key}={val} is defined in .env but not referenced by any Compose service"
                            ),
                            suggested_fix=f"Use ${{{key}}} in compose.yaml ports or remove unused variable",
                        )
                    )

            # Check runtime port collisions for declared ports
            _, bindings = inspect_compose(compose_file)
            for binding in bindings:
                owner = self.services.ports.find_port_owner(binding.host_port)
                if owner and owner.owner_type != "unknown":
                    # If owned by a different project or process
                    is_same_container = owner.project == project.name or (
                        owner.container and project.name in owner.container
                    )
                    if not is_same_container:
                        owner_desc = owner.process or owner.container or "another process"
                        port_drifts.append(
                            PortDriftItem(
                                service=binding.service,
                                variable=binding.variable,
                                env_value=binding.host_port,
                                compose_mapping=f"{binding.host_port}:{binding.container_port}",
                                drift_type=PortDriftType.RUNTIME_PORT_COLLISION,
                                severity="critical",
                                message=(
                                    f"Host port {binding.host_port} for service '{binding.service}' is already "
                                    f"occupied by {owner_desc} (PID {owner.pid})"
                                ),
                                suggested_fix="Use Arbiter port reconciliation to allocate an available free port",
                            )
                        )

        # 3. Calculate score & summary
        score = 0
        recommendations: list[str] = []
        for drift in port_drifts:
            if drift.severity == "critical":
                score += 15
            elif drift.severity == "warning":
                score += 5
            else:
                score += 2
            if drift.suggested_fix and drift.suggested_fix not in recommendations:
                recommendations.append(drift.suggested_fix)

        for var in env_audit:
            if var.status == EnvVarAuditStatus.MISSING:
                score += 8
            elif var.status == EnvVarAuditStatus.PLACEHOLDER:
                score += 10
            elif var.status == EnvVarAuditStatus.EMPTY:
                score += 4
            elif var.status == EnvVarAuditStatus.UNDOCUMENTED:
                score += 1
            if var.recommendation and var.recommendation not in recommendations:
                recommendations.append(var.recommendation)

        if score == 0:
            status = "clean"
            summary = "Configuration is fully synchronized, documented, and free of port collisions."
        elif score < 15:
            status = "warning"
            summary = f"Detected {len(port_drifts)} port drift(s) and {len(missing_vars)} missing env variable(s)."
        else:
            status = "critical"
            summary = (
                f"Configuration requires attention: {len(port_drifts)} port drift(s), "
                f"{len(missing_vars)} missing variable(s), and unconfigured secrets detected."
            )

        return ProjectConfigDrift(
            project_id=project.id,
            project_name=project.name,
            project_path=str(project.path),
            has_env=env_file.is_file(),
            has_env_example=example_file is not None,
            has_compose=bool(project.compose_files),
            drift_score=score,
            status=status,
            port_drifts=port_drifts,
            missing_env_vars=missing_vars,
            env_audit=env_audit,
            summary=summary,
            recommendations=recommendations,
        )

    def build_visual_diff(self, old_content: str, new_content: str, file_path: str = "") -> VisualDiff:
        """Create a safe unified side-by-side visual diff, masking secrets if editing .env."""
        is_env = Path(file_path).name.startswith(".env") if file_path else False

        def _safe_line(line: str) -> str:
            if not is_env or "=" not in line:
                return line
            key, val = line.split("=", 1)
            if is_secret_key(key):
                return f"{key}={mask_secret(val)}"
            return line

        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        safe_old_lines = [_safe_line(line) for line in old_lines]
        safe_new_lines = [_safe_line(line) for line in new_lines]

        diff_gen = difflib.unified_diff(
            safe_old_lines,
            safe_new_lines,
            fromfile=f"a/{file_path}" if file_path else "before",
            tofile=f"b/{file_path}" if file_path else "after",
            lineterm="",
        )
        unified_diff_str = "\n".join(diff_gen)

        matcher = difflib.SequenceMatcher(None, safe_old_lines, safe_new_lines)
        visual_lines: list[VisualDiffLine] = []
        additions = 0
        deletions = 0

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for idx in range(i1, i2):
                    visual_lines.append(
                        VisualDiffLine(
                            line_number_before=idx + 1,
                            line_number_after=j1 + (idx - i1) + 1,
                            kind="unchanged",
                            content=safe_old_lines[idx],
                        )
                    )
            elif tag == "delete":
                for idx in range(i1, i2):
                    deletions += 1
                    visual_lines.append(
                        VisualDiffLine(
                            line_number_before=idx + 1,
                            line_number_after=None,
                            kind="deletion",
                            content=safe_old_lines[idx],
                        )
                    )
            elif tag == "insert":
                for idx in range(j1, j2):
                    additions += 1
                    visual_lines.append(
                        VisualDiffLine(
                            line_number_before=None,
                            line_number_after=idx + 1,
                            kind="addition",
                            content=safe_new_lines[idx],
                        )
                    )
            elif tag == "replace":
                for idx in range(i1, i2):
                    deletions += 1
                    visual_lines.append(
                        VisualDiffLine(
                            line_number_before=idx + 1,
                            line_number_after=None,
                            kind="deletion",
                            content=safe_old_lines[idx],
                        )
                    )
                for idx in range(j1, j2):
                    additions += 1
                    visual_lines.append(
                        VisualDiffLine(
                            line_number_before=None,
                            line_number_after=idx + 1,
                            kind="addition",
                            content=safe_new_lines[idx],
                        )
                    )

        return VisualDiff(
            file_path=file_path,
            unified_diff=unified_diff_str,
            lines=visual_lines,
            additions=additions,
            deletions=deletions,
            is_secret_file=is_env,
        )

    def build_time_travel_preview(self, spec: ActionSpec) -> TimeTravelPreview:
        """Construct before vs after runtime states, visual diffs, and transition timeline."""
        args = spec.arguments
        action = spec.action
        visual_diffs: list[VisualDiff] = []
        state_transitions: list[StateTransition] = []
        port_changes: list[dict[str, Any]] = []
        container_changes: list[dict[str, Any]] = []
        resolves_drifts: list[str] = []
        impacted_deps: list[str] = []

        # 1. Handle file updates
        if action == "file.update" and "project_id" in args and "path" in args:
            project_id = str(args["project_id"])
            rel_path = str(args["path"])
            new_content = str(args.get("content", ""))
            try:
                current_file = self.services.files.read(project_id, rel_path)
                vdiff = self.build_visual_diff(current_file.content, new_content, rel_path)
                visual_diffs.append(vdiff)
                after_data = {
                    "size_bytes": len(new_content),
                    "additions": vdiff.additions,
                    "deletions": vdiff.deletions,
                }
                state_transitions.append(
                    StateTransition(
                        resource_type="file",
                        identifier=f"{project_id}:{rel_path}",
                        label=rel_path,
                        before_state={"size_bytes": len(current_file.content), "sha256": current_file.sha256},
                        after_state=after_data,
                        action_type="file_updated",
                    )
                )
            except Exception:
                pass

        # 2. Handle port resolution / compose port changes
        elif action in {"project.resolve_ports", "compose.change_port"}:
            project_id = str(args.get("project_id", ""))
            changes = args.get("changes") or []
            if action == "compose.change_port":
                changes = [
                    {
                        "service": args.get("service"),
                        "old_port": args.get("old_port"),
                        "new_port": args.get("new_port"),
                        "protocol": "tcp",
                    }
                ]

            for change in changes:
                svc_name = change.get("service", "unknown")
                old_p = change.get("old_port")
                new_p = change.get("new_port")
                proto = change.get("protocol", "tcp")

                port_changes.append(
                    {
                        "service": svc_name,
                        "before": f"{old_p}/{proto}",
                        "after": f"{new_p}/{proto}",
                    }
                )
                state_transitions.append(
                    StateTransition(
                        resource_type="port",
                        identifier=f"{svc_name}:{new_p}",
                        label=f"{svc_name} port",
                        before_state={"host_port": old_p, "protocol": proto},
                        after_state={"host_port": new_p, "protocol": proto},
                        action_type="port_rebound",
                    )
                )
                container_changes.append(
                    {
                        "service": svc_name,
                        "transition": "recreate_service",
                        "reason": f"Port changed to {new_p}",
                    }
                )
                resolves_drifts.append(f"Resolves port conflict on port {old_p} -> {new_p}")

        # 3. Handle container lifecycle actions
        elif action.startswith("container."):
            cid = str(args.get("identifier", ""))
            sub_action = action.removeprefix("container.")
            container_changes.append(
                {
                    "container_id": cid,
                    "transition": sub_action,
                    "reason": f"Manual {sub_action} triggered via control plane",
                }
            )
            state_transitions.append(
                StateTransition(
                    resource_type="container",
                    identifier=cid,
                    label=cid,
                    before_state={"state": "running" if sub_action in {"stop", "restart"} else "stopped"},
                    after_state={"state": "running" if sub_action in {"start", "restart"} else "stopped"},
                    action_type=f"container_{sub_action}",
                )
            )

        # 4. Check dependencies in topology
        try:
            graph = self.services.topology.graph()
            if "project_id" in args:
                target_pid = str(args["project_id"])
                for edge in graph.edges:
                    if edge.relationship.value == "depends_on" and edge.target == target_pid:
                        impacted_deps.append(edge.source)
        except Exception:
            pass

        return TimeTravelPreview(
            action=spec.action,
            summary=spec.summary,
            visual_diffs=visual_diffs,
            state_transitions=state_transitions,
            port_changes=port_changes,
            container_changes=container_changes,
            impacted_dependencies=sorted(set(impacted_deps)),
            resolves_drifts=resolves_drifts,
        )
