import re
from pathlib import Path

from arbiter.dockerfile.models import DockerfileInfo, DockerfileInstruction, DockerfileStage

INSTRUCTION_RE = re.compile(r"^(?P<keyword>[A-Za-z]+)\s+(?P<value>.*)$")
FROM_RE = re.compile(r"^(?P<image>\S+)(?:\s+AS\s+(?P<name>[A-Za-z0-9_.-]+))?", re.IGNORECASE)


class DockerfileService:
    """Small deterministic Dockerfile reader; it does not try to execute builds."""

    def inspect(self, path: Path) -> DockerfileInfo:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise LookupError(f"Dockerfile not found: {resolved}")
        return self.inspect_text(resolved.read_text(errors="replace"), resolved)

    def inspect_text(self, text: str, path: Path) -> DockerfileInfo:
        instructions = self._instructions(text)
        info = DockerfileInfo(path=path)
        current_stage: DockerfileStage | None = None
        for instruction in instructions:
            keyword, value = instruction.keyword, instruction.value
            if keyword == "FROM":
                match = FROM_RE.match(value)
                if not match:
                    info.warnings.append(
                        {
                            "severity": "warning",
                            "message": f"Could not parse FROM instruction on line {instruction.line}",
                        }
                    )
                    continue
                current_stage = DockerfileStage(
                    index=len(info.stages), base_image=match.group("image"), name=match.group("name"), instructions=[]
                )
                info.stages.append(current_stage)
                continue
            if current_stage:
                current_stage.instructions.append(instruction)
            self._record(info, instruction)
        self._diagnose(info)
        return info

    @staticmethod
    def _instructions(text: str) -> list[DockerfileInstruction]:
        result: list[DockerfileInstruction] = []
        pending = ""
        start_line = 0
        for line_number, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            if not pending and (not stripped or stripped.startswith("#")):
                continue
            if not pending:
                start_line = line_number
            value = f"{pending} {stripped}".strip() if pending else stripped
            if value.endswith("\\"):
                pending = value[:-1].rstrip()
                continue
            pending = ""
            match = INSTRUCTION_RE.match(value)
            if match:
                result.append(
                    DockerfileInstruction(
                        keyword=match.group("keyword").upper(), value=match.group("value").strip(), line=start_line
                    )
                )
        if pending:
            result.append(DockerfileInstruction(keyword="INVALID", value=pending, line=start_line))
        return result

    @staticmethod
    def _record(info: DockerfileInfo, instruction: DockerfileInstruction) -> None:
        keyword, value = instruction.keyword, instruction.value
        if keyword in {"COPY", "ADD"}:
            info.copy_instructions.append(value)
        elif keyword == "RUN":
            info.run.append(value)
        elif keyword == "WORKDIR":
            info.workdir = value
        elif keyword == "ARG":
            key, separator, default = value.partition("=")
            info.args[key.strip()] = default if separator else None
        elif keyword == "ENV":
            for item in DockerfileService._environment_pairs(value):
                key, separator, default = item.partition("=")
                info.environment[key.strip()] = default if separator else None
        elif keyword == "EXPOSE":
            info.exposed_ports.extend(value.split())
        elif keyword == "CMD":
            info.cmd = value
        elif keyword == "ENTRYPOINT":
            info.entrypoint = value
        elif keyword == "HEALTHCHECK":
            info.healthcheck = value
        elif keyword == "USER":
            info.user = value
        elif keyword == "INVALID":
            info.warnings.append(
                {
                    "severity": "confirmed_issue",
                    "message": f"Unterminated continued instruction beginning on line {instruction.line}",
                }
            )

    @staticmethod
    def _environment_pairs(value: str) -> list[str]:
        if "=" in value:
            return re.findall(r"(?:[^\s=]+)=(?:\"[^\"]*\"|'[^']*'|[^\s]+)", value)
        parts = value.split(None, 1)
        return [f"{parts[0]}={parts[1]}" if len(parts) == 2 else parts[0]]

    @staticmethod
    def _diagnose(info: DockerfileInfo) -> None:
        if not info.stages:
            info.warnings.append({"severity": "confirmed_issue", "message": "Dockerfile has no FROM instruction"})
        if not info.user:
            info.warnings.append(
                {"severity": "possible_issue", "message": "No USER instruction found; the image may run as root"}
            )
        for stage in info.stages:
            image = stage.base_image
            if image.endswith(":latest") or ":" not in image and "@" not in image:
                info.warnings.append(
                    {
                        "severity": "possible_issue",
                        "message": f"Base image {image!r} is not pinned to a specific tag or digest",
                    }
                )
