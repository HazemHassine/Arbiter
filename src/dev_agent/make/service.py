import re
from pathlib import Path

from dev_agent.models import Risk
from dev_agent.system.processes import run

TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?![=])")
DESTRUCTIVE = ("down -v", "volume rm", "system prune", "dropdb", "reset --hard", "rm -rf")
HIGH = (" rm ", "clean", "prune", "delete", "destroy")


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
        if not makefile.is_file():
            raise LookupError("Makefile not found")
        targets = self.parse(makefile)
        if target not in targets:
            raise LookupError(f"Make target not found: {target}")
        commands = targets[target]
        ports = sorted({int(value) for command in commands for value in re.findall(r"--port[= ](\d+)", command)})
        return {"target": target, "commands": commands, "risk": self.classify(target, commands), "ports": ports}

    def run(self, project: Path, target: str) -> dict[str, object]:
        self.inspect(project, target)
        result = run(["make", target], cwd=project, timeout=300)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "verified": result.returncode == 0,
        }
