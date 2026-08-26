from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.models import ApprovalInfo, Project, Risk
from arbiter.persistence.tables import ApprovalRow, ProjectRow


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, project: Project) -> Project:
        row = self.session.scalar(select(ProjectRow).where(ProjectRow.path == str(project.path)))
        data = project.model_dump(mode="json")
        if row:
            project.id = row.id
            data["id"] = row.id
            row.name, row.data, row.last_discovered = project.name, data, project.last_discovered
        else:
            row = ProjectRow(
                id=project.id,
                name=project.name,
                path=str(project.path),
                data=data,
                last_discovered=project.last_discovered,
            )
            self.session.add(row)
        self.session.commit()
        return project

    def list(self) -> list[Project]:
        return [Project.model_validate(row.data) for row in self.session.scalars(select(ProjectRow)).all()]

    def get(self, identifier: str) -> Project | None:
        row = self.session.scalar(
            select(ProjectRow).where((ProjectRow.id == identifier) | (ProjectRow.name == identifier))
        )
        return Project.model_validate(row.data) if row else None

    def delete(self, identifier: str) -> bool:
        row = self.session.scalar(select(ProjectRow).where(ProjectRow.id == identifier))
        if not row:
            return False
        self.session.delete(row)
        self.session.commit()
        return True


def approval_info(row: ApprovalRow) -> ApprovalInfo:
    created = row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at
    expires = row.expires_at.replace(tzinfo=UTC) if row.expires_at.tzinfo is None else row.expires_at
    return ApprovalInfo(
        id=row.id,
        request_id=row.request_id,
        risk=Risk(row.risk),
        action=row.action,
        summary=row.summary,
        arguments=row.arguments,
        status=row.status,
        created_at=created,
        expires_at=expires,
    )
