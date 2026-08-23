from datetime import UTC, datetime, timedelta

import pytest

from dev_agent.make.service import MakeService
from dev_agent.models import ActionSpec, Risk
from dev_agent.persistence.tables import ApprovalRow
from dev_agent.security import redact


def test_secret_redaction_nested():
    data = {"API_KEY": "secret", "safe": {"password": "bad", "port": 8000}}
    assert redact(data) == {"API_KEY": "<redacted>", "safe": {"password": "<redacted>", "port": 8000}}


def test_make_parsing_and_risk(tmp_path):
    makefile = tmp_path / "Makefile"
    makefile.write_text("test:\n\tpytest\ndev:\n\tuvicorn app:app --port 8000\ndestroy:\n\tdocker compose down -v\n")
    service = MakeService()
    targets = service.parse(makefile)
    assert service.classify("test", targets["test"]) == Risk.LOW_RISK
    assert service.inspect(tmp_path, "dev")["ports"] == [8000]
    assert service.classify("destroy", targets["destroy"]) == Risk.DESTRUCTIVE


def test_approval_persists_immutable_arguments(service_factory):
    services = service_factory()
    spec = ActionSpec(
        action="container.start", arguments={"identifier": "original"}, summary="start", risk=Risk.LOW_RISK
    )
    proposed = services.actions.propose(spec)
    approval_id = proposed["approval"]["id"]
    spec.arguments["identifier"] = "modified"
    assert services.actions.approvals.get(approval_id).arguments == {"identifier": "original"}
    result = services.actions.approve_and_execute(approval_id)
    assert result.status == "completed"
    assert services.docker.executed == [("original", "start")]


def test_approval_expiration(service_factory):
    services = service_factory()
    approval = services.actions.approvals.create(ActionSpec(action="x", arguments={}, summary="x", risk=Risk.HIGH_RISK))
    with services.database.sessions() as session:
        row = session.get(ApprovalRow, approval.id)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert services.actions.approvals.get(approval.id).status == "expired"
    with pytest.raises(ValueError, match="expired"):
        services.actions.approve_and_execute(approval.id)
