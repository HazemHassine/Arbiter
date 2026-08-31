import http.client

import pytest

from arbiter.api.app import create_app
from arbiter.models import ReadinessGate, ReadinessPolicyStatus, ReadinessProbeType, StackProjectMember


def _gate(host: str = "10.20.30.40", port: int = 8080) -> ReadinessGate:
    return ReadinessGate(
        probe_type=ReadinessProbeType.HTTP_GET,
        host=host,
        port=port,
        path="/health",
        service="remote-api",
    )


def test_loopback_allowed_and_metadata_blocked(service_factory, monkeypatch):
    policy = service_factory().stacks.readiness_policy
    monkeypatch.setattr(policy, "_resolve", lambda host, port: ("127.0.0.1",))
    allowed = policy.evaluate(_gate("localhost"))
    assert allowed.status == ReadinessPolicyStatus.ALLOWED

    blocked = policy.evaluate(_gate("metadata.google.internal", 80))
    assert blocked.status == ReadinessPolicyStatus.BLOCKED
    assert "metadata" in blocked.reason.lower()

    monkeypatch.setattr(policy, "_resolve", lambda host, port: ("::1",))
    assert policy.evaluate(_gate("::1")).status == ReadinessPolicyStatus.ALLOWED


def test_mixed_loopback_resolution_is_blocked(service_factory, monkeypatch):
    policy = service_factory().stacks.readiness_policy
    monkeypatch.setattr(policy, "_resolve", lambda host, port: ("127.0.0.1", "10.20.30.40"))
    decision = policy.evaluate(_gate("mixed.internal"))
    assert decision.status == ReadinessPolicyStatus.BLOCKED
    assert "mix loopback" in decision.reason


def test_registered_private_compose_service_is_allowed(service_factory, monkeypatch):
    policy = service_factory().stacks.readiness_policy
    monkeypatch.setattr(policy, "_resolve", lambda host, port: ("10.20.30.40",))
    monkeypatch.setattr(policy, "_is_registered_service", lambda host: host == "api")
    decision = policy.evaluate(_gate("api"))
    assert decision.status == ReadinessPolicyStatus.ALLOWED
    assert "Compose service" in decision.reason


def test_link_local_address_is_never_approvable(service_factory, monkeypatch):
    services = service_factory()
    policy = services.stacks.readiness_policy
    monkeypatch.setattr(policy, "_resolve", lambda host, port: ("169.254.169.254",))
    stack = services.stacks.create_stack(
        "blocked",
        projects=[
            StackProjectMember(project_id="p1", project_name="app", readiness_gates=[_gate("metadata.internal", 80)])
        ],
    )

    decision = policy.evaluate(_gate("metadata.internal", 80))
    assert decision.status == ReadinessPolicyStatus.BLOCKED
    assert services.stacks.request_readiness_authorizations(stack.id) == []


def test_private_target_requires_approval_and_dns_changes_invalidate_grant(service_factory, monkeypatch):
    services = service_factory()
    policy = services.stacks.readiness_policy
    current = ["10.20.30.40"]
    monkeypatch.setattr(policy, "_resolve", lambda host, port: tuple(current))
    gate = _gate()
    stack = services.stacks.create_stack(
        "private-api",
        projects=[StackProjectMember(project_id="p1", project_name="app", readiness_gates=[gate])],
    )

    assert policy.evaluate(gate).status == ReadinessPolicyStatus.APPROVAL_REQUIRED
    blocked_switch = services.stacks.switch_stack(stack.id)
    assert blocked_switch.status == "blocked"
    assert blocked_switch.started_projects == []
    assert blocked_switch.stopped_projects == []
    requests = services.stacks.request_readiness_authorizations(stack.id)
    approval_id = requests[0]["approval"]["id"]
    duplicate = services.stacks.request_readiness_authorizations(stack.id)
    assert duplicate[0]["approval"]["id"] == approval_id
    action = services.actions.approve_and_execute(approval_id)
    assert action.status == "completed"
    assert policy.evaluate(gate).status == ReadinessPolicyStatus.ALLOWED
    assert len(policy.list()) == 1

    current[:] = ["10.20.30.41"]
    changed = policy.evaluate(gate)
    assert changed.status == ReadinessPolicyStatus.APPROVAL_REQUIRED
    assert "scoped approval" in changed.reason


def test_redirect_destination_is_revalidated_before_connection(service_factory, monkeypatch):
    stacks = service_factory().stacks
    policy = stacks.readiness_policy

    def resolve(host, port):
        return ("169.254.169.254",) if host == "169.254.169.254" else ("127.0.0.1",)

    monkeypatch.setattr(policy, "_resolve", resolve)
    connections = []

    class FakeResponse:
        status = 302

        @staticmethod
        def getheader(name):
            return "http://169.254.169.254/latest/meta-data/" if name == "Location" else None

        @staticmethod
        def close():
            return None

    class FakeConnection:
        def __init__(self, host, port, timeout):
            connections.append(host)

        def request(self, method, path, headers):
            return None

        def getresponse(self):
            return FakeResponse()

        def close(self):
            return None

    monkeypatch.setattr(http.client, "HTTPConnection", FakeConnection)
    gate = _gate("localhost")
    decision = policy.evaluate(gate)

    with pytest.raises(PermissionError, match="Redirect destination denied"):
        stacks._http_get(gate, decision)
    assert connections == ["127.0.0.1"]


def test_readiness_input_rejects_header_injection():
    with pytest.raises(ValueError, match="plain hostname"):
        _gate("localhost\r\nX-Evil: yes")
    with pytest.raises(ValueError, match="control characters"):
        ReadinessGate(probe_type="http_get", host="localhost", port=80, path="/health\r\nX-Evil: yes")


def test_readiness_rest_contract_is_published(service_factory):
    paths = create_app(services=service_factory()).openapi()["paths"]
    assert "/api/v1/stacks/{identifier}/readiness/authorizations" in paths
    assert "/api/v1/readiness/authorizations" in paths
    assert "/api/v1/readiness/authorizations/{authorization_id}" in paths
