from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from arbiter.models import ActionSpec, ApprovalInfo
from arbiter.persistence.database import Database
from arbiter.persistence.repositories import approval_info
from arbiter.persistence.tables import ApprovalRow, PortReservationRow


class ApprovalService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, spec: ActionSpec, ttl_minutes: int = 30) -> ApprovalInfo:
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=ttl_minutes)
        row = ApprovalRow(
            id=str(uuid4()),
            request_id=spec.request_id,
            risk=spec.risk.value,
            action=spec.action,
            summary=spec.summary,
            arguments=spec.model_dump(mode="json")["arguments"],
            status="pending",
            created_at=now,
            expires_at=expires_at,
        )
        reservations = self._port_reservations(spec)
        try:
            with self.database.sessions() as session:
                session.execute(delete(PortReservationRow).where(PortReservationRow.expires_at <= now))
                session.add(row)
                session.add_all(
                    PortReservationRow(
                        key=f"{protocol}:{port}",
                        port=port,
                        protocol=protocol,
                        approval_id=row.id,
                        project_id=spec.project_id,
                        expires_at=expires_at,
                    )
                    for port, protocol in reservations
                )
                session.commit()
                return approval_info(row)
        except IntegrityError as exc:
            raise ValueError("A replacement port is already reserved by another active approval") from exc

    def list(self) -> list[ApprovalInfo]:
        with self.database.sessions() as session:
            rows = session.scalars(select(ApprovalRow).order_by(ApprovalRow.created_at.desc())).all()
            return [self._expire(row, session) for row in rows]

    def get(self, approval_id: str) -> ApprovalInfo:
        with self.database.sessions() as session:
            row = session.get(ApprovalRow, approval_id)
            if not row:
                raise LookupError(f"Approval not found: {approval_id}")
            return self._expire(row, session)

    def decide(self, approval_id: str, approved: bool) -> ApprovalInfo:
        with self.database.sessions() as session:
            row = session.get(ApprovalRow, approval_id)
            if not row:
                raise LookupError(f"Approval not found: {approval_id}")
            info = self._expire(row, session)
            if info.status != "pending":
                raise ValueError(f"Approval is already {info.status}")
            row.status = "approved" if approved else "rejected"
            if not approved:
                session.execute(delete(PortReservationRow).where(PortReservationRow.approval_id == row.id))
            session.commit()
            return approval_info(row)

    def release_reservations(self, approval_id: str) -> None:
        with self.database.sessions() as session:
            session.execute(delete(PortReservationRow).where(PortReservationRow.approval_id == approval_id))
            session.commit()

    @staticmethod
    def _expire(row: ApprovalRow, session) -> ApprovalInfo:
        expires = row.expires_at.replace(tzinfo=UTC) if row.expires_at.tzinfo is None else row.expires_at
        if row.status == "pending" and expires <= datetime.now(UTC):
            row.status = "expired"
            session.execute(delete(PortReservationRow).where(PortReservationRow.approval_id == row.id))
            session.commit()
        return approval_info(row)

    @staticmethod
    def _port_reservations(spec: ActionSpec) -> list[tuple[int, str]]:
        if spec.action != "project.resolve_ports":
            return []
        reservations = [
            (int(change["new_port"]), str(change.get("protocol") or "tcp").lower())
            for change in spec.arguments.get("changes", [])
        ]
        if any(not 1 <= port <= 65535 for port, _protocol in reservations):
            raise ValueError("Replacement ports must be between 1 and 65535")
        if any(protocol not in {"tcp", "udp"} for _port, protocol in reservations):
            raise ValueError("Replacement port protocol must be tcp or udp")
        if len(reservations) != len(set(reservations)):
            raise ValueError("One reconciliation approval cannot reserve the same replacement port twice")
        return reservations
