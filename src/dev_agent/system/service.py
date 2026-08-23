import shutil
from pathlib import Path

from dev_agent.system.processes import process_info


class SystemService:
    def resources(self, path: Path = Path(".")) -> dict[str, object]:
        disk = shutil.disk_usage(path)
        memory: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                memory[key] = int(value.strip().split()[0]) * 1024
        return {"disk": {"total": disk.total, "used": disk.used, "free": disk.free}, "memory": memory}

    def process(self, pid: int) -> dict[str, object]:
        return process_info(pid)
