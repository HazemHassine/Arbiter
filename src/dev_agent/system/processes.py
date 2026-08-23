import os
import subprocess
from pathlib import Path


def process_info(pid: int) -> dict[str, object]:
    if pid <= 0:
        raise ValueError("PID must be positive")
    proc = Path("/proc") / str(pid)
    if not proc.exists():
        raise LookupError(f"Process {pid} not found")
    try:
        command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        name = (proc / "comm").read_text().strip()
        return {"pid": pid, "process": name, "command": command, "uid": proc.stat().st_uid}
    except PermissionError:
        return {"pid": pid, "process": None, "command": None}


def run(args: list[str], timeout: float = 15.0, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)


def command_exists(name: str) -> bool:
    return any((Path(folder) / name).is_file() for folder in os.environ.get("PATH", "").split(os.pathsep))
