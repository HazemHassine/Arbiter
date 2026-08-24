import shutil
from pathlib import Path

from dev_agent.system.processes import list_processes, process_info


class SystemService:
    def resources(self, path: Path = Path(".")) -> dict[str, object]:
        disk = shutil.disk_usage(path)
        memory: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                memory[key] = int(value.strip().split()[0]) * 1024
        return {"disk": {"total": disk.total, "used": disk.used, "free": disk.free}, "memory": memory}

    def process(self, pid: int, ports: list[int] | None = None) -> dict[str, object]:
        if ports:
            from dev_agent.system.processes import inspect_process

            return inspect_process(pid, ports).model_dump(mode="json")
        return process_info(pid)

    def processes(self, port_by_pid: dict[int, list[int]] | None = None) -> list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in list_processes(port_by_pid)]
