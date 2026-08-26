import os
import re
import subprocess
from pathlib import Path

from arbiter.system.models import ProcessInfo

DEVELOPMENT_SIGNATURES: tuple[tuple[set[str], str, float], ...] = (
    (
        {"vite", "next", "nuxt", "webpack", "uvicorn", "gunicorn", "flask", "django", "fastapi"},
        "development_server",
        0.93,
    ),
    ({"node", "npm", "pnpm", "yarn", "bun"}, "javascript_runtime", 0.72),
    ({"python", "python3", "uv", "poetry"}, "python_runtime", 0.68),
    ({"java", "maven", "mvn", "gradle"}, "jvm_runtime", 0.72),
    ({"cargo", "rustc", "go"}, "compiled_runtime", 0.72),
    ({"postgres", "redis", "mongod", "meilisearch"}, "database_or_search", 0.9),
    ({"make"}, "build_tool", 0.84),
    ({"docker", "dockerd", "podman", "containerd", "nerdctl"}, "container_runtime", 0.9),
)
CONTAINER_ID_RE = re.compile(r"(?:docker[-/]|libpod[-/])([0-9a-f]{12,64})|/docker/([0-9a-f]{12,64})", re.IGNORECASE)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace").strip()
    except (OSError, PermissionError):
        return None


def _read_link(path: Path) -> str | None:
    try:
        return str(path.resolve(strict=True))
    except (OSError, RuntimeError):
        return None


def _stat_values(pid: int) -> tuple[str | None, int | None, int | None]:
    raw = _read_text(Path("/proc") / str(pid) / "stat")
    if not raw or ")" not in raw:
        return None, None, None
    values = raw.rsplit(")", 1)[1].strip().split()
    if len(values) < 13:
        return None, None, None
    try:
        return values[0], int(values[1]), int(values[11]) + int(values[12])
    except ValueError:
        return values[0], None, None


def _memory_bytes(proc: Path) -> int | None:
    status = _read_text(proc / "status")
    if not status:
        return None
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            try:
                return int(line.split()[1]) * 1024
            except (IndexError, ValueError):
                return None
    return None


def _container_id(proc: Path) -> str | None:
    cgroup = _read_text(proc / "cgroup") or ""
    match = CONTAINER_ID_RE.search(cgroup)
    if not match:
        return None
    return next(value for value in match.groups() if value is not None)


def classify_process(name: str | None, command: str | None, ports: list[int]) -> tuple[str, float, list[str]]:
    text = f"{name or ''} {command or ''}".lower()
    tokens = set(re.findall(r"[a-z0-9_.+-]+", text))
    evidence = []
    for signatures, kind, confidence in DEVELOPMENT_SIGNATURES:
        match = sorted(signatures & tokens)
        if match:
            evidence.append(f"matched={','.join(match)}")
            if ports:
                evidence.append(f"listens_on={','.join(str(port) for port in ports)}")
                if kind in {"javascript_runtime", "python_runtime", "jvm_runtime", "compiled_runtime"}:
                    return "development_server", max(confidence, 0.82), evidence
            return kind, confidence, evidence
    if ports:
        return "listening_process", 0.58, [f"listens_on={','.join(str(port) for port in ports)}"]
    return "process", 0.2, []


def inspect_process(pid: int, ports: list[int] | None = None) -> ProcessInfo:
    if pid <= 0:
        raise ValueError("PID must be positive")
    proc = Path("/proc") / str(pid)
    if not proc.exists():
        raise LookupError(f"Process {pid} not found")
    try:
        command_bytes = (proc / "cmdline").read_bytes()
        command = command_bytes.replace(b"\0", b" ").decode(errors="replace").strip() or None
    except (OSError, PermissionError):
        command = None
    name = _read_text(proc / "comm")
    state, ppid, cpu_ticks = _stat_values(pid)
    current_ports = sorted(set(ports or []))
    kind, confidence, evidence = classify_process(name, command, current_ports)
    cwd = _read_link(proc / "cwd")
    if cwd:
        evidence.append(f"cwd={cwd}")
    if command:
        evidence.append(f"cmdline={command}")
    try:
        uid = proc.stat().st_uid
    except (OSError, PermissionError):
        uid = None
    return ProcessInfo(
        pid=pid,
        ppid=ppid,
        process=name,
        command=command,
        executable=_read_link(proc / "exe"),
        cwd=cwd,
        uid=uid,
        state=state,
        memory_bytes=_memory_bytes(proc),
        cpu_ticks=cpu_ticks,
        cpu_seconds=round(cpu_ticks / os.sysconf("SC_CLK_TCK"), 3) if cpu_ticks is not None else None,
        ports=current_ports,
        container_id=_container_id(proc),
        kind=kind,
        confidence=confidence,
        evidence=evidence,
    )


def list_processes(port_by_pid: dict[int, list[int]] | None = None, limit: int = 10_000) -> list[ProcessInfo]:
    entries: list[ProcessInfo] = []
    mappings = port_by_pid or {}
    try:
        candidates = sorted(
            (item for item in Path("/proc").iterdir() if item.name.isdigit()), key=lambda item: int(item.name)
        )
    except OSError:
        return entries
    for proc in candidates[:limit]:
        try:
            entries.append(inspect_process(int(proc.name), mappings.get(int(proc.name), [])))
        except (LookupError, OSError, ValueError):
            continue
    children: dict[int, list[int]] = {}
    for item in entries:
        if item.ppid is not None:
            children.setdefault(item.ppid, []).append(item.pid)
    for item in entries:
        item.children = children.get(item.pid, [])
    return entries


def process_info(pid: int) -> dict[str, object]:
    try:
        return inspect_process(pid).model_dump(mode="json")
    except PermissionError:
        return {"pid": pid, "process": None, "command": None}


def run(args: list[str], timeout: float = 15.0, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)


def command_exists(name: str) -> bool:
    return any((Path(folder) / name).is_file() for folder in os.environ.get("PATH", "").split(os.pathsep))
