import re
from pathlib import Path

from arbiter.make.models import MakeTargetInfo
from arbiter.models import Risk
from arbiter.system.processes import run

TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?![=])(?P<dependencies>[^#]*)(?:\s+#\s*(?P<description>.*))?$")
DESTRUCTIVE = ("down -v", "volume rm", "system prune", "dropdb", "reset --hard", "rm -rf")
HIGH = (" rm ", "clean", "prune", "delete", "destroy")
COMMAND_TOOLS = (
    "docker compose",
    "docker build",
    "docker run",
    "uvicorn",
    "gunicorn",
    "npm run",
    "pnpm",
    "yarn",
    "bun",
    "cargo run",
    "go run",
    "pytest",
    "make",
)
LONG_RUNNING = (
    "docker compose up",
    "docker run",
    "uvicorn",
    "gunicorn",
    "npm run",
    "pnpm",
    "yarn",
    "vite",
    "next dev",
    "cargo run",
    "go run",
)


class MakeService:
    def parse(self, makefile: Path) -> dict[str, list[str]]:
        targets: dict[str, list[str]] = {}
        current: str | None = None
        for line in makefile.read_text(errors="replace").splitlines():
            match = TARGET_RE.match(line)
            if match and not match.group(1).startswith("."):
                current = match.group(1)
                targets.setdefault(current, [])
            elif current and line.startswith("\t"):
                targets[current].append(line.strip())
            elif line and not line.startswith((" ", "\t", "#")):
                current = None
        return targets

    def parse_details(self, makefile: Path) -> dict[str, MakeTargetInfo]:
        if not makefile.is_file():
            raise LookupError("Makefile not found")
        details: dict[str, MakeTargetInfo] = {}
        current: str | None = None
        pending_description: str | None = None
        for line in makefile.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if line.startswith("##"):
                pending_description = stripped[2:].strip() or None
                continue
            match = TARGET_RE.match(line)
            if match and not match.group(1).startswith("."):
                current = match.group(1)
                dependencies = [
                    item for item in match.group("dependencies").strip().split() if item and "$" not in item
                ]
                details[current] = MakeTargetInfo(
                    name=current,
                    dependencies=dependencies,
                    description=match.group("description") or pending_description,
                    risk=Risk.HIGH_RISK,
                )
                pending_description = None
            elif current and line.startswith("\t"):
                details[current].commands.append(line.strip())
            elif line and not line.startswith((" ", "\t", "#")):
                current = None
        for target in details.values():
            target.risk = self.classify(target.name, target.commands)
            target.ports = self._ports(target.commands)
            target.tools = self._tools(target.commands)
            text = " ".join(target.commands).lower()
            target.starts_long_running_process = any(command in text for command in LONG_RUNNING)
        return details

    @staticmethod
    def _ports(commands: list[str]) -> list[int]:
        patterns = (
            r"--port(?:=|\s+)(\d+)",
            r"(?:^|\s)-p\s*(\d+)(?::\d+)?",
            r"(?:^|\s)(\d{4,5}):(\d{2,5})(?:/tcp|/udp)?",
        )
        values: set[int] = set()
        for command in commands:
            for pattern in patterns:
                for match in re.finditer(pattern, command):
                    for value in match.groups():
                        if value and value.isdigit() and 1 <= int(value) <= 65535:
                            values.add(int(value))
        return sorted(values)

    @staticmethod
    def _tools(commands: list[str]) -> list[str]:
        text = "\n".join(commands).lower()
        return [tool for tool in COMMAND_TOOLS if tool in text]

    def classify(self, target: str, commands: list[str]) -> Risk:
        text = f" {target.lower()} {' '.join(commands).lower()} "
        if any(pattern in text for pattern in DESTRUCTIVE):
            return Risk.DESTRUCTIVE
        if any(pattern in text for pattern in HIGH):
            return Risk.HIGH_RISK
        if target in {"test", "lint", "check", "format"}:
            return Risk.LOW_RISK
        if target in {"dev", "start", "stop", "restart", "up"}:
            return Risk.MEDIUM_RISK
        return Risk.HIGH_RISK

    def inspect(self, project: Path, target: str) -> dict[str, object]:
        makefile = project / "Makefile"
        targets = self.parse_details(makefile)
        if target not in targets:
            raise LookupError(f"Make target not found: {target}")
        result = targets[target].model_dump(mode="json")
        result["target"] = target
        return result

    def run(self, project: Path, target: str) -> dict[str, object]:
        self.inspect(project, target)
        result = run(["make", "--", target], cwd=project, timeout=300)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "verified": result.returncode == 0,
        }
