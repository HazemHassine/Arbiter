from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from datetime import UTC
from uuid import uuid4

from sqlalchemy import select

from arbiter.models import ReadinessAuthorization, ReadinessGate, ReadinessPolicyStatus, ReadinessProbeType
from arbiter.persistence.tables import ReadinessAuthorizationRow

_METADATA_HOSTS = {"metadata", "metadata.google.internal", "instance-data", "instance-data.ec2.internal"}


@dataclass(frozen=True)
class ReadinessPolicyDecision:
    status: ReadinessPolicyStatus
    reason: str
    protocol: str
    host: str
    port: int
    resolved_addresses: tuple[str, ...] = ()

    @property
    def target_key(self) -> str:
        return f"{self.protocol}:{self.host.lower()}:{self.port}"


class ReadinessPolicyService:
    """Authorize readiness traffic without turning probes into an SSRF primitive."""

    def __init__(self, database, projects) -> None:
        self.database = database
        self.projects = projects

    def evaluate(self, gate: ReadinessGate) -> ReadinessPolicyDecision:
        if gate.probe_type == ReadinessProbeType.DOCKER_HEALTH:
            return ReadinessPolicyDecision(
                ReadinessPolicyStatus.ALLOWED,
                "Docker health checks do not open network connections",
                "docker",
                "docker",
                0,
            )
        protocol = "http" if gate.probe_type == ReadinessProbeType.HTTP_GET else "tcp"
        port = gate.port or (80 if protocol == "http" else 0)
        if not port:
            return ReadinessPolicyDecision(
                ReadinessPolicyStatus.BLOCKED, "A network probe requires a port", protocol, gate.host, 0
            )
        host = gate.host.strip().rstrip(".").strip("[]")
        if host.lower() in _METADATA_HOSTS:
            return ReadinessPolicyDecision(
                ReadinessPolicyStatus.BLOCKED, "Cloud metadata destinations are never permitted", protocol, host, port
            )
        try:
            addresses = self._resolve(host, port)
        except OSError as exc:
            return ReadinessPolicyDecision(
                ReadinessPolicyStatus.BLOCKED, f"Host resolution failed: {exc}", protocol, host, port
            )
        parsed = [ipaddress.ip_address(address) for address in addresses]
        if parsed and all(address.is_loopback for address in parsed):
            return ReadinessPolicyDecision(
                ReadinessPolicyStatus.ALLOWED,
                "Loopback destination allowed automatically",
                protocol,
                host,
                port,
                addresses,
            )
        if any(address.is_loopback for address in parsed):
            return ReadinessPolicyDecision(
                ReadinessPolicyStatus.BLOCKED,
                "A hostname must not mix loopback and non-loopback addresses",
                protocol,
                host,
                port,
                addresses,
            )
        if any(self._hard_blocked(address) for address in parsed):
            return ReadinessPolicyDecision(
                ReadinessPolicyStatus.BLOCKED,
                "Link-local, metadata, multicast, unspecified, and reserved destinations are never permitted",
                protocol,
                host,
                port,
                addresses,
            )
        if self._is_registered_service(host) and all(address.is_private for address in parsed):
            return ReadinessPolicyDecision(
                ReadinessPolicyStatus.ALLOWED,
                "Registered Compose service destination allowed automatically",
                protocol,
                host,
                port,
                addresses,
            )
        decision = ReadinessPolicyDecision(
            ReadinessPolicyStatus.APPROVAL_REQUIRED,
            "Non-local readiness destinations require a scoped approval",
            protocol,
            host,
            port,
            addresses,
        )
        authorization = self._get(decision.target_key)
        if authorization and set(authorization.resolved_addresses) == set(addresses):
            return ReadinessPolicyDecision(
                ReadinessPolicyStatus.ALLOWED,
                "Destination matches a persisted scoped approval",
                protocol,
                host,
                port,
                addresses,
            )
        return decision

    def authorize(self, arguments: dict, approval_id: str) -> ReadinessAuthorization:
        gate = ReadinessGate.model_validate(arguments["gate"])
        decision = self.evaluate(gate)
        approved_addresses = sorted(str(item) for item in arguments.get("resolved_addresses", []))
        if decision.status == ReadinessPolicyStatus.BLOCKED:
            raise ValueError(decision.reason)
        if sorted(decision.resolved_addresses) != approved_addresses:
            raise ValueError("Destination resolution changed after approval; request a new authorization")
        row = ReadinessAuthorizationRow(
            id=str(uuid4()),
            target_key=decision.target_key,
            protocol=decision.protocol,
            host=decision.host,
            port=decision.port,
            resolved_addresses=list(decision.resolved_addresses),
            approval_id=approval_id,
        )
        with self.database.sessions() as session:
            existing = session.scalar(
                select(ReadinessAuthorizationRow).where(ReadinessAuthorizationRow.target_key == decision.target_key)
            )
            if existing:
                existing.resolved_addresses = row.resolved_addresses
                existing.approval_id = approval_id
                row = existing
            else:
                session.add(row)
            session.commit()
            return self._model(row)

    def list(self) -> list[ReadinessAuthorization]:
        with self.database.sessions() as session:
            rows = session.scalars(
                select(ReadinessAuthorizationRow).order_by(ReadinessAuthorizationRow.created_at.desc())
            ).all()
            return [self._model(row) for row in rows]

    def revoke(self, authorization_id: str) -> bool:
        with self.database.sessions() as session:
            row = session.get(ReadinessAuthorizationRow, authorization_id)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    def _get(self, target_key: str) -> ReadinessAuthorizationRow | None:
        with self.database.sessions() as session:
            return session.scalar(
                select(ReadinessAuthorizationRow).where(ReadinessAuthorizationRow.target_key == target_key)
            )

    def _is_registered_service(self, host: str) -> bool:
        normalized = host.lower()
        return any(
            normalized in {service.lower() for service in project.services} for project in self.projects.list_projects()
        )

    @staticmethod
    def _resolve(host: str, port: int) -> tuple[str, ...]:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM) if item and item[4]}
        if not addresses:
            raise OSError("no addresses returned")
        return tuple(sorted(addresses))

    @staticmethod
    def _hard_blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved

    @staticmethod
    def _model(row: ReadinessAuthorizationRow) -> ReadinessAuthorization:
        created = row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at
        return ReadinessAuthorization(
            id=row.id,
            target_key=row.target_key,
            protocol=row.protocol,
            host=row.host,
            port=row.port,
            resolved_addresses=list(row.resolved_addresses or []),
            approval_id=row.approval_id,
            created_at=created,
        )
