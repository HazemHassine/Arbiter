from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from arbiter.models import ActionSpec, Project, Risk
from arbiter.persistence.repositories import ProjectRepository
from arbiter.persistence.tables import ActionRow, PortReservationRow


def test_project_repository_crud(service_factory, tmp_path: Path):
    services = service_factory()
    with services.database.sessions() as session:
        repo = ProjectRepository(session)

        proj = Project(name="persisted-proj", path=tmp_path / "persisted-proj")
        repo.save(proj)

        loaded = repo.get(proj.id)
        assert loaded is not None
        assert loaded.name == "persisted-proj"
        assert loaded.id == proj.id

        all_projs = repo.list()
        assert len(all_projs) == 1
        assert all_projs[0].name == "persisted-proj"


def test_approval_repository_lifecycle(service_factory):
    services = service_factory()
    repo = services.actions.approvals

    spec = ActionSpec(
        action="container.restart",
        arguments={"identifier": "db-1"},
        summary="Restart db",
        risk=Risk.MEDIUM_RISK,
    )
    approval = repo.create(spec)
    assert approval.status == "pending"

    # Fetch approval
    fetched = repo.get(approval.id)
    assert fetched.id == approval.id
    assert fetched.action == "container.restart"

    # Update status
    repo.decide(approval.id, True)
    updated = repo.get(approval.id)
    assert updated.status == "approved"


def test_port_reservation_table(service_factory):
    services = service_factory()
    with services.database.sessions() as session:
        reservation = PortReservationRow(
            key="tcp:8080",
            port=8080,
            protocol="tcp",
            approval_id="appr-123",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add(reservation)
        session.commit()

        row = session.scalar(select(PortReservationRow).where(PortReservationRow.key == "tcp:8080"))
        assert row is not None
        assert row.port == 8080
        assert row.approval_id == "appr-123"


def test_action_history_persisted(service_factory):
    services = service_factory()
    spec = ActionSpec(
        action="container.start",
        arguments={"identifier": "db"},
        summary="Start db container",
        risk=Risk.LOW_RISK,
    )
    result = services.actions.execute(spec)
    assert result.status == "completed"

    with services.database.sessions() as session:
        actions = session.scalars(select(ActionRow)).all()
        assert len(actions) == 1
        assert actions[0].action == "container.start"
        assert actions[0].status == "completed"
