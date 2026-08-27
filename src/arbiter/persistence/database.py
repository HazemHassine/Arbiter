from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from arbiter.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        options = {"check_same_thread": False} if self.settings.database_url.startswith("sqlite") else {}
        self.engine = create_engine(self.settings.database_url, connect_args=options)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        from arbiter.persistence import tables  # noqa: F401

        Base.metadata.create_all(self.engine)
        database = self.engine.url.database
        if self.engine.url.get_backend_name() == "sqlite" and database and database != ":memory:":
            path = Path(database).expanduser()
            if path.exists():
                path.chmod(0o600)

    def session(self) -> Iterator[Session]:
        with self.sessions() as session:
            yield session
