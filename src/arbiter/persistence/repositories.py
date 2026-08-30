from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.models import ApprovalInfo, Project, Risk, Stack
from arbiter.persistence.tables import ApprovalRow, ProjectRow, StackRow


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


class StackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, stack: Stack) -> Stack:
        row = self.session.scalar(select(StackRow).where((StackRow.id == stack.id) | (StackRow.name == stack.name)))
        data = stack.model_dump(mode="json")
        if row:
            stack.id = row.id
            data["id"] = row.id
            row.name = stack.name
            row.description = stack.description
            row.data = data
            row.is_active = stack.is_active
            row.status = stack.status
            row.updated_at = stack.updated_at
        else:
            row = StackRow(
                id=stack.id,
                name=stack.name,
                description=stack.description,
                data=data,
                is_active=stack.is_active,
                status=stack.status,
                created_at=stack.created_at,
                updated_at=stack.updated_at,
            )
            self.session.add(row)
        self.session.commit()
        return stack

    def list(self) -> list[Stack]:
        return [
            Stack.model_validate(row.data)
            for row in self.session.scalars(select(StackRow).order_by(StackRow.created_at.desc())).all()
        ]

    def get(self, identifier: str) -> Stack | None:
        row = self.session.scalar(select(StackRow).where((StackRow.id == identifier) | (StackRow.name == identifier)))
        return Stack.model_validate(row.data) if row else None

    def get_active(self) -> Stack | None:
        row = self.session.scalar(select(StackRow).where(StackRow.is_active.is_(True)))
        return Stack.model_validate(row.data) if row else None

    def set_active(self, identifier: str | None) -> None:
        for row in self.session.scalars(select(StackRow)).all():
            if identifier and (row.id == identifier or row.name == identifier):
                row.is_active = True
                row.status = "active"
                row.data["is_active"] = True
                row.data["status"] = "active"
            else:
                row.is_active = False
                row.status = "inactive"
                row.data["is_active"] = False
                row.data["status"] = "inactive"
        self.session.commit()

    def delete(self, identifier: str) -> bool:
        row = self.session.scalar(select(StackRow).where((StackRow.id == identifier) | (StackRow.name == identifier)))
        if not row:
            return False
        self.session.delete(row)
        self.session.commit()
        return True
