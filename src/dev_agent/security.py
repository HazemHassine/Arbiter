import re
from copy import deepcopy
from pathlib import Path
from typing import Any

SECRET_PATTERN = re.compile(r"(PASSWORD|SECRET|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL)", re.IGNORECASE)


def redact(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: "<redacted>" if SECRET_PATTERN.search(str(key)) else redact(value) for key, value in data.items()}
    if isinstance(data, list):
        return [redact(item) for item in data]
    return data


def safe_project_path(path: Path, roots: list[Path] | None = None) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"Project path is not a directory: {resolved}")
    if roots:
        allowed = [root.expanduser().resolve(strict=False) for root in roots]
        if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
            raise ValueError(f"Path is outside configured project roots: {resolved}")
    return resolved


def redact_action_arguments(action: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Hide editor payloads that could contain an environment secret from list APIs.

    The immutable stored action remains available to the action dispatcher, while
    API consumers receive the diff preview and a stable hash instead of an
    accidental copy of a full ``.env`` file.
    """
    result = deepcopy(arguments)
    if action == "file.update" and Path(str(result.get("path", ""))).name == ".env" and "content" in result:
        result["content"] = "<redacted .env editor payload>"
    return result
