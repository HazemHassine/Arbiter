from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from arbiter.models import ActionSpec, ApprovalInfo
from arbiter.persistence.database import Database
from arbiter.persistence.repositories import approval_info
from arbiter.persistence.tables import ApprovalRow


class ApprovalService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, spec: ActionSpec, ttl_minutes: int = 30) -> ApprovalInfo:
        now = datetime.now(UTC)
        row = ApprovalRow(
            id=str(uuid4()),
            request_id=spec.request_id,
            risk=spec.risk.value,
            action=spec.action,
            summary=spec.summary,
            arguments=spec.model_dump(mode="json")["arguments"],
            status="pending",
            created_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
        with self.database.sessions() as session:
            session.add(row)
            session.commit()
            return approval_info(row)

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
            session.commit()
            return approval_info(row)

    @staticmethod
    def _expire(row: ApprovalRow, session) -> ApprovalInfo:
        expires = row.expires_at.replace(tzinfo=UTC) if row.expires_at.tzinfo is None else row.expires_at
        if row.status == "pending" and expires <= datetime.now(UTC):
            row.status = "expired"
            session.commit()
        return approval_info(row)
