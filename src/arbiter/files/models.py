from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from arbiter.models import utcnow


class ProjectFile(BaseModel):
    path: str
    name: str
    kind: str
    size: int
    modified_at: datetime | None = None


class FileContent(BaseModel):
    path: str
    content: str
    sha256: str
    kind: str


class FileChangePreview(BaseModel):
    path: str
    expected_sha256: str
    proposed_sha256: str
    diff: str
    validation: dict[str, object] = Field(default_factory=dict)


class ManagedFileBackup(BaseModel):
    id: str
    project_id: str
    relative_path: str
    backup_path: Path
    before_sha256: str
    after_sha256: str
    created_at: datetime = Field(default_factory=utcnow)
    undone_at: datetime | None = None
