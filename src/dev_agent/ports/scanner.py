import re

from dev_agent.models import PortOwner
from dev_agent.system.processes import process_info, run

PROCESS_RE = re.compile(r'users:\(\("(?P<name>[^"]+)".*?pid=(?P<pid>\d+)')


def _split_endpoint(endpoint: str) -> tuple[str, int] | None:
    endpoint = endpoint.strip()
    if endpoint.startswith("[") and "]" in endpoint:
        host, _, port = endpoint[1:].partition("]:")
    else:
        host, sep, port = endpoint.rpartition(":")
        if not sep:
            return None
    if not port.isdigit():
        return None
    return host or "*", int(port)


def parse_ss(output: str) -> list[PortOwner]:
    owners: list[PortOwner] = []
    seen: set[tuple[int, str, int | None]] = set()
    for raw in output.splitlines():
        fields = raw.split()
        if len(fields) < 5:
            continue
        protocol = fields[0].lower()
        if protocol not in {"tcp", "udp"}:
            continue
        state = fields[1]
        endpoint = _split_endpoint(fields[4])
        if not endpoint:
            continue
        host, port = endpoint
        match = PROCESS_RE.search(raw)
        pid = int(match.group("pid")) if match else None
        key = (port, protocol, pid)
        if key in seen:
            continue
        seen.add(key)
        owner = PortOwner(
            port=port,
            protocol=protocol,
            state=state,
            host=host,
            owner_type="process" if match else "unknown",
            pid=pid,
            process=match.group("name") if match else None,
        )
        if pid:
            try:
                details = process_info(pid)
                owner.command = details.get("command")  # type: ignore[assignment]
            except (LookupError, OSError):
                pass
        owners.append(owner)
    return owners


class LinuxPortScanner:
    def scan(self) -> list[PortOwner]:
        result = run(["ss", "-H", "-lntu", "-p"])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "ss failed")
        return parse_ss(result.stdout)
