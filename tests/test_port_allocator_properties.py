import pytest
from hypothesis import given
from hypothesis import strategies as st

from arbiter.config import Settings
from arbiter.models import PortBinding, Project
from arbiter.ports.service import PortService


class EmptyScanner:
    def scan(self):
        return []


@given(
    preferred=st.integers(min_value=3000, max_value=3010),
    protocol=st.sampled_from(["tcp", "udp"]),
    reserved_ports=st.sets(st.integers(min_value=3000, max_value=3010)),
    other_protocol_ports=st.sets(st.integers(min_value=3000, max_value=3010)),
)
def test_reconciliation_allocator_is_deterministic_and_protocol_specific(
    preferred, protocol, reserved_ports, other_protocol_ports
):
    service = PortService(
        scanner=EmptyScanner(),
        settings=Settings(
            database_url="sqlite:///:memory:",
            default_port_search_range_start=3000,
            default_port_search_range_end=3010,
            _env_file=None,
        ),
    )
    other_protocol = "udp" if protocol == "tcp" else "tcp"
    reserved = {(port, protocol) for port in reserved_ports} | {
        (port, other_protocol) for port in other_protocol_ports
    }
    ordered_candidates = [*range(preferred + 1, 3011), *range(3000, preferred)]
    available = [port for port in ordered_candidates if port not in reserved_ports]

    if not available:
        with pytest.raises(RuntimeError, match=f"No free {protocol} port"):
            service._suggest_unclaimed_port(preferred, protocol, reserved)
        return

    result = service._suggest_unclaimed_port(preferred, protocol, reserved)

    assert result == available[0]
    assert (result, protocol) not in reserved


@given(port=st.integers(min_value=4000, max_value=5000), copies=st.integers(min_value=2, max_value=8))
def test_duplicate_project_claims_receive_unique_replacements(port, copies):
    project = Project(
        id="duplicate-project",
        name="duplicate-project",
        path="/tmp/duplicate-project",
        ports=[PortBinding(host_port=port, container_port=80, service=f"service-{index}") for index in range(copies)],
    )
    service = PortService(
        scanner=EmptyScanner(),
        settings=Settings(
            database_url="sqlite:///:memory:",
            default_port_search_range_start=3000,
            default_port_search_range_end=9999,
            _env_file=None,
        ),
        project_provider=lambda: [project],
    )

    plan = service.plan_port_reconciliation(project)
    replacements = [change.suggested_port for change in plan.changes]

    assert len(replacements) == copies - 1
    assert len(replacements) == len(set(replacements))
    assert port not in replacements
    assert all("duplicate_in_project" in change.reasons for change in plan.changes)
