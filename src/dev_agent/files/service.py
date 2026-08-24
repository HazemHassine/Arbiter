import difflib
import hashlib
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from sqlalchemy import select

from dev_agent.dockerfile.service import DockerfileService
from dev_agent.files.models import FileChangePreview, FileContent, ManagedFileBackup, ProjectFile
from dev_agent.make.service import MakeService
from dev_agent.persistence.tables import ManagedFileBackupRow
from dev_agent.system.processes import command_exists, run

COMPOSE_NAMES = {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}
EXACT_NAMES = {"Makefile", ".env", ".dockerignore", *COMPOSE_NAMES}
IGNORED_DIRECTORIES = {".git", ".venv", "node_modules", "__pycache__", ".dev-agent"}
MAX_FILE_BYTES = 1_000_000


class FileService:
    """Bounded editor service for known files below a registered project root."""

    def __init__(self, database, projects) -> None:
        self.database = database
        self.projects = projects
        self.dockerfiles = DockerfileService()
        self.make = MakeService()

    def list_files(self, project_id: str) -> list[ProjectFile]:
        project = self.projects.get_project(project_id)
        root = project.path.resolve(strict=True)
        files: list[ProjectFile] = []
        for directory, subdirectories, names in os.walk(root):
            current = Path(directory)
            relative_directory = current.relative_to(root)
            if len(relative_directory.parts) > 3:
                subdirectories[:] = []
                continue
            subdirectories[:] = [
                name for name in subdirectories if name not in IGNORED_DIRECTORIES and not name.startswith(".")
            ]
            for name in names:
                candidate = current / name
                if not self._is_supported_name(name):
                    continue
                try:
                    resolved = self._resolve(project_id, candidate.relative_to(root).as_posix())
                    stat = resolved.stat()
                except (OSError, ValueError):
                    continue
                if stat.st_size > MAX_FILE_BYTES:
                    continue
                files.append(
                    ProjectFile(
                        path=resolved.relative_to(root).as_posix(),
                        name=name,
                        kind=self._kind(resolved.name),
                        size=stat.st_size,
                        modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                    )
                )
        return sorted(files, key=lambda item: item.path)

    def read(self, project_id: str, relative_path: str) -> FileContent:
        path = self._resolve(project_id, relative_path)
        raw = path.read_bytes()
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError(f"File is larger than {MAX_FILE_BYTES} bytes")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Only UTF-8 text files can be edited") from exc
        return FileContent(
            path=path.relative_to(self._root(project_id)).as_posix(),
            content=content,
            sha256=self._sha(raw),
            kind=self._kind(path.name),
        )

    def preview(self, project_id: str, relative_path: str, content: str, expected_sha256: str) -> FileChangePreview:
        current = self.read(project_id, relative_path)
        if current.sha256 != expected_sha256:
            raise ValueError("File changed since it was opened; reload before saving")
        if len(content.encode()) > MAX_FILE_BYTES:
            raise ValueError(f"Proposed content exceeds {MAX_FILE_BYTES} bytes")
        validation = self._validate_content(Path(current.path), content)
        diff = "".join(
            difflib.unified_diff(
                current.content.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{current.path}",
                tofile=f"b/{current.path}",
                n=3,
            )
        )
        return FileChangePreview(
            path=current.path,
            expected_sha256=current.sha256,
            proposed_sha256=self._sha(content.encode()),
            diff=diff[:120_000],
            validation=validation,
        )

    def apply_update(
        self, project_id: str, relative_path: str, content: str, expected_sha256: str
    ) -> dict[str, object]:
        project = self.projects.get_project(project_id)
        root = self._root(project_id)
        path = self._resolve(project_id, relative_path)
        current = self.read(project_id, relative_path)
        if current.sha256 != expected_sha256:
            raise ValueError("File changed since this edit was proposed; no write was performed")
        self._validate_content(path, content)
        backup_path = self._create_backup(root, path, current.sha256)
        try:
            self._atomic_write(path, content.encode(), path.stat().st_mode)
            validation = self._validate_written(path)
        except Exception:
            self._atomic_write(path, backup_path.read_bytes(), path.stat().st_mode)
            raise
        after_hash = self._sha(path.read_bytes())
        backup = ManagedFileBackupRow(
            id=str(uuid4()),
            project_id=project.id,
            relative_path=path.relative_to(root).as_posix(),
            backup_path=backup_path.relative_to(root).as_posix(),
            before_sha256=current.sha256,
            after_sha256=after_hash,
        )
        with self.database.sessions() as session:
            session.add(backup)
            session.commit()
        return {
            "file": str(path),
            "backup": self._backup_model(backup).model_dump(mode="json"),
            "validation": validation,
            "verified": after_hash == self._sha(content.encode()),
        }

    def undo_latest(self, project_id: str, relative_path: str) -> dict[str, object]:
        root = self._root(project_id)
        path = self._resolve(project_id, relative_path)
        with self.database.sessions() as session:
            row = session.scalar(
                select(ManagedFileBackupRow)
                .where(
                    ManagedFileBackupRow.project_id == project_id,
                    ManagedFileBackupRow.relative_path == path.relative_to(root).as_posix(),
                    ManagedFileBackupRow.undone_at.is_(None),
                )
                .order_by(ManagedFileBackupRow.created_at.desc())
            )
            if not row:
                raise LookupError("No managed change is available to undo for this file")
            if self._sha(path.read_bytes()) != row.after_sha256:
                raise ValueError("File changed after the managed edit; refusing to overwrite your newer change")
            backup_path = self._backup_path(root, row.backup_path)
            current_bytes = path.read_bytes()
            mode = path.stat().st_mode
            self._atomic_write(path, backup_path.read_bytes(), mode)
            try:
                validation = self._validate_written(path)
            except Exception:
                self._atomic_write(path, current_bytes, mode)
                raise
            if self._sha(path.read_bytes()) != row.before_sha256:
                raise RuntimeError("Backup restoration verification failed")
            row.undone_at = datetime.now(UTC)
            session.commit()
            model = self._backup_model(row)
        return {
            "file": str(path),
            "restored_backup": model.model_dump(mode="json"),
            "validation": validation,
            "verified": True,
        }

    def _root(self, project_id: str) -> Path:
        return self.projects.get_project(project_id).path.resolve(strict=True)

    def _resolve(self, project_id: str, relative_path: str) -> Path:
        root = self._root(project_id)
        candidate = Path(relative_path)
        if not relative_path or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("File path must be a relative path inside the registered project")
        if not self._is_supported_name(candidate.name):
            raise ValueError("This file type is not editable through the control plane")
        try:
            resolved = (root / candidate).resolve(strict=True)
        except OSError as exc:
            raise LookupError(f"Project file not found: {relative_path}") from exc
        if not resolved.is_file() or not resolved.is_relative_to(root):
            raise ValueError("Resolved path is outside the registered project")
        return resolved

    @staticmethod
    def _is_supported_name(name: str) -> bool:
        return name in EXACT_NAMES or name == "Dockerfile" or name.startswith("Dockerfile.")

    @staticmethod
    def _kind(name: str) -> str:
        if name in COMPOSE_NAMES:
            return "compose"
        if name == "Makefile":
            return "makefile"
        if name == ".env":
            return "env"
        if name == ".dockerignore":
            return "dockerignore"
        return "dockerfile"

    def _validate_content(self, path: Path, content: str) -> dict[str, object]:
        kind = self._kind(path.name)
        if kind == "compose":
            parsed = yaml.safe_load(content) or {}
            if not isinstance(parsed, dict):
                raise ValueError("Compose document must be a mapping")
            services = parsed.get("services", {})
            if services is not None and not isinstance(services, dict):
                raise ValueError("Compose services must be a mapping")
            return {"parser": "yaml", "valid": True, "services": len(services or {})}
        if kind == "dockerfile":
            info = self.dockerfiles.inspect_text(content, path)
            confirmed = [item for item in info.warnings if item["severity"] == "confirmed_issue"]
            if confirmed:
                raise ValueError(confirmed[0]["message"])
            return {"parser": "dockerfile", "valid": True, "stages": len(info.stages), "warnings": info.warnings}
        if kind == "makefile":
            # Parsing commands from the supplied text does not require execution.
            targets = []
            for line in content.splitlines():
                if line and not line.startswith(("\t", " ", "#")) and ":" in line and "=" not in line.split(":", 1)[0]:
                    targets.append(line.split(":", 1)[0].strip())
            return {"parser": "make", "valid": True, "targets": targets}
        if kind == "env":
            invalid = [
                line_number
                for line_number, raw in enumerate(content.splitlines(), start=1)
                if raw.strip() and not raw.lstrip().startswith("#") and "=" not in raw
            ]
            if invalid:
                raise ValueError(f".env line {invalid[0]} must be KEY=VALUE or a comment")
            return {"parser": "env", "valid": True}
        return {"parser": "text", "valid": True}

    def _validate_written(self, path: Path) -> dict[str, object]:
        validation = self._validate_content(path, path.read_text(encoding="utf-8"))
        if self._kind(path.name) == "compose":
            if command_exists("docker"):
                result = run(["docker", "compose", "-f", str(path), "config"], cwd=path.parent, timeout=30)
                if result.returncode:
                    raise RuntimeError(f"Compose validation failed: {result.stderr.strip() or result.stdout.strip()}")
                validation["docker_compose"] = "valid"
            else:
                validation["docker_compose"] = "skipped (docker command unavailable)"
        return validation

    @staticmethod
    def _sha(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _atomic_write(path: Path, content: bytes, mode: int) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _create_backup(root: Path, path: Path, before_sha: str) -> Path:
        directory = root / ".dev-agent" / "backups"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        safe_name = path.relative_to(root).as_posix().replace("/", "__")
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        backup = directory / f"{stamp}-{before_sha[:12]}-{safe_name}"
        shutil.copy2(path, backup)
        return backup

    @staticmethod
    def _backup_path(root: Path, raw_path: str) -> Path:
        candidate = (root / raw_path).resolve(strict=True)
        allowed = (root / ".dev-agent" / "backups").resolve(strict=True)
        if not candidate.is_file() or not candidate.is_relative_to(allowed):
            raise ValueError("Managed backup path is invalid")
        return candidate

    @staticmethod
    def _backup_model(row: ManagedFileBackupRow) -> ManagedFileBackup:
        return ManagedFileBackup(
            id=row.id,
            project_id=row.project_id,
            relative_path=row.relative_path,
            backup_path=Path(row.backup_path),
            before_sha256=row.before_sha256,
            after_sha256=row.after_sha256,
            created_at=row.created_at,
            undone_at=row.undone_at,
        )
