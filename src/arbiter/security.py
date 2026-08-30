import ipaddress
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

SECRET_PATTERN = re.compile(
    r"(PASSWORD|SECRET|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL|AUTH|ACCESS[_-]?KEY|ENCRYPTION)",
    re.IGNORECASE,
)

COMMON_PLACEHOLDERS = {
    "change_me",
    "changeme",
    "your_key_here",
    "your-api-key-here",
    "your_secret_here",
    "your-secret-here",
    "your_token_here",
    "your-password-here",
    "password",
    "secret",
    "admin",
    "root",
    "example",
    "test",
    "dummy",
    "placeholder",
    "todo",
    "xxx",
    "123456",
}


def is_secret_key(key: str) -> bool:
    """Determine if an environment variable key is likely sensitive."""
    return bool(SECRET_PATTERN.search(str(key)))


def is_placeholder_secret(value: str) -> bool:
    """Check if a secret value appears to be an unconfigured placeholder."""
    val = value.strip().lower().strip("\"'")
    if not val:
        return True
    if val in COMMON_PLACEHOLDERS:
        return True
    return any(placeholder in val for placeholder in ("your_", "your-", "replace_me", "insert_", "todo"))


def mask_secret(value: str) -> str:
    """Safely mask secret values without leaking credentials.

    Retains safe diagnostic prefixes/suffixes for recognizable token types while
    obscuring the entropy.
    """
    val = str(value).strip()
    if not val:
        return ""
    if len(val) <= 6:
        return "••••••••"
    if val.startswith(("sk-", "ghp_", "glpat-", "npm_", "xoxb-", "xoxp-")):
        sep = "-" if "-" in val else "_"
        prefix, _, rest = val.partition(sep)
        suffix = val[-4:]
        return f"{prefix}{sep}••••••••{suffix}"
    return f"{val[:2]}••••••••{val[-2:]}"


def validate_bind_host(host: str, allow_remote_access: bool = False) -> str:
    """Reject accidental unauthenticated network exposure unless explicitly allowed."""
    normalized = host.strip().lower()
    try:
        loopback = normalized == "localhost" or ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        loopback = normalized == "localhost"
    if not loopback and not allow_remote_access:
        raise ValueError(
            "Arbiter has no built-in remote authentication; set ALLOW_REMOTE_ACCESS=true "
            "only when an external authentication boundary is in place"
        )
    return host


def redact(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: "<redacted>" if is_secret_key(str(key)) else redact(value) for key, value in data.items()}
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
