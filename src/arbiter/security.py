import ipaddress
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

SECRET_PATTERN = re.compile(r"(PASSWORD|SECRET|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL)", re.IGNORECASE)
SENSITIVE_ARGUMENT_PATTERN = re.compile(
    r"(?i)(?P<prefix>(?:^|\s)(?:--?)?[A-Za-z0-9_.-]*"
    r"(?:password|passwd|secret|token|api[-_]?key|private[-_]?key|credential)[A-Za-z0-9_.-]*"
    r"(?:\s*=\s*|\s+))(?P<value>\"[^\"]*\"|'[^']*'|\S+)"
)
UNSAFE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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
        return {key: "<redacted>" if SECRET_PATTERN.search(str(key)) else redact(value) for key, value in data.items()}
    if isinstance(data, list):
        return [redact(item) for item in data]
    return data


def redact_sensitive_text(value: str | None) -> str | None:
    """Mask common secret-bearing command-line and assignment forms."""

    if value is None:
        return None
    return SENSITIVE_ARGUMENT_PATTERN.sub(lambda match: f"{match.group('prefix')}<redacted>", value)


def redact_sensitive_arguments(values: list[str]) -> list[str]:
    """Mask secret-bearing argv values without losing non-secret argument boundaries."""

    result: list[str] = []
    redact_next = False
    for value in values:
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue
        name, separator, _argument_value = value.partition("=")
        if SECRET_PATTERN.search(name.lstrip("-")):
            result.append(f"{name}=<redacted>" if separator else value)
            redact_next = not separator
        else:
            result.append(value)
    return result


def normalize_hostname(value: str) -> str:
    """Normalize a bare hostname or IP address for exact allowlist matching."""

    normalized = value.strip().lower().rstrip(".")
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    try:
        return ipaddress.ip_address(normalized).compressed
    except ValueError:
        return normalized


def is_unspecified_host(value: str) -> bool:
    """Return whether a host is an IPv4 or IPv6 wildcard bind address."""

    try:
        return ipaddress.ip_address(normalize_hostname(value)).is_unspecified
    except ValueError:
        return False


def validate_request_host(host_header: str, trusted_hosts: list[str] | set[str]) -> str:
    """Validate one HTTP Host authority against an exact host allowlist."""

    parsed = _parse_authority(host_header, scheme="http")
    host = normalize_hostname(parsed.hostname or "")
    allowed = {normalize_hostname(item) for item in trusted_hosts}
    if not host or host not in allowed:
        raise ValueError("Request Host is not trusted")
    return host


def validate_browser_origin(
    *,
    method: str,
    scheme: str,
    host_header: str,
    origin: str | None,
    referer: str | None,
    sec_fetch_site: str | None,
) -> None:
    """Reject cross-origin browser mutations while preserving non-browser API clients."""

    if method.upper() not in UNSAFE_HTTP_METHODS:
        return
    if (sec_fetch_site or "").strip().lower() == "cross-site":
        raise ValueError("Cross-site browser requests are not allowed")
    candidate = origin or referer
    if not candidate:
        return
    if candidate.strip().lower() == "null":
        raise ValueError("Opaque browser origins are not allowed")
    request_authority = _parse_authority(host_header, scheme=scheme)
    candidate_url = _parse_origin(candidate)
    if _origin_tuple(request_authority) != _origin_tuple(candidate_url):
        raise ValueError("Cross-origin browser requests are not allowed")


def _parse_authority(authority: str, *, scheme: str) -> SplitResult:
    raw = authority.strip()
    if not raw or any(character in raw for character in ("/", "\\", "@", ",", "\r", "\n", "\t", " ")):
        raise ValueError("Malformed HTTP Host header")
    try:
        parsed = urlsplit(f"{scheme}://{raw}")
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Malformed HTTP Host header") from exc
    if not parsed.hostname:
        raise ValueError("Malformed HTTP Host header")
    return parsed


def _parse_origin(origin: str) -> SplitResult:
    raw = origin.strip()
    if not raw or any(character.isspace() for character in raw):
        raise ValueError("Malformed browser Origin")
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Malformed browser Origin") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Malformed browser Origin")
    return parsed


def _origin_tuple(value: SplitResult) -> tuple[str, str, int]:
    scheme = value.scheme.lower()
    default_port = 443 if scheme == "https" else 80
    return scheme, normalize_hostname(value.hostname or ""), value.port or default_port


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
