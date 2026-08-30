import pytest

from arbiter.models import ReadinessGate, ReadinessProbeType, Stack, StackProjectMember


def test_stack_crud(service_factory):
    services = service_factory()
    stacks_svc = services.stacks

    # Create stack
    stack = stacks_svc.create_stack(
        name="AI Pipeline + Vector DB",
        description="Qdrant and LLM Gateway",
        projects=[
            StackProjectMember(
                project_id="proj-1",
                project_name="qdrant-store",
                boot_stage=0,
                readiness_gates=[
                    ReadinessGate(probe_type=ReadinessProbeType.TCP_PORT, host="127.0.0.1", port=6333, service="qdrant")
                ],
            ),
            StackProjectMember(
                project_id="proj-2",
                project_name="llm-gateway",
                depends_on=["qdrant-store"],
                boot_stage=1,
            ),
        ],
        tags=["ai", "vector"],
    )

    assert stack.id is not None
    assert stack.name == "AI Pipeline + Vector DB"
    assert len(stack.projects) == 2

    # List stacks
    all_stacks = stacks_svc.list_stacks()
    assert any(s.id == stack.id for s in all_stacks)

    # Get stack
    retrieved = stacks_svc.get_stack(stack.id)
    assert retrieved.name == stack.name

    # Update stack
    updated = stacks_svc.update_stack(stack.id, description="Updated description")
    assert updated.description == "Updated description"

    # Delete stack
    deleted = stacks_svc.delete_stack(stack.id)
    assert deleted is True
    with pytest.raises(LookupError):
        stacks_svc.get_stack(stack.id)


def test_seed_default_presets(service_factory):
    services = service_factory()
    stacks_svc = services.stacks

    seeded = stacks_svc.seed_default_presets()
    assert len(seeded) >= 3

    names = {s.name for s in seeded}
    assert "Billing Microservices" in names
    assert "AI Pipeline + Vector DB" in names
    assert "Frontend App + Mock API" in names


def test_compute_boot_plan_dag(service_factory):
    services = service_factory()
    stacks_svc = services.stacks

    stack = Stack(
        name="Test Stack",
        projects=[
            StackProjectMember(project_id="p1", project_name="db", depends_on=[], boot_stage=0),
            StackProjectMember(project_id="p2", project_name="redis", depends_on=[], boot_stage=0),
            StackProjectMember(project_id="p3", project_name="api", depends_on=["db", "redis"], boot_stage=1),
            StackProjectMember(project_id="p4", project_name="frontend", depends_on=["api"], boot_stage=2),
        ],
    )

    boot_plan = stacks_svc.compute_boot_plan(stack)
    assert boot_plan.dependencies_valid is True
    assert boot_plan.cycle_detected is False
    assert boot_plan.total_stages == 3

    # Stage 0 should contain db and redis
    stage_0_projects = set(boot_plan.stages[0].projects)
    assert "db" in stage_0_projects
    assert "redis" in stage_0_projects

    # Stage 1 should contain api
    assert "api" in boot_plan.stages[1].projects

    # Stage 2 should contain frontend
    assert "frontend" in boot_plan.stages[2].projects


def test_compute_boot_plan_cycle_detection(service_factory):
    services = service_factory()
    stacks_svc = services.stacks

    # Circular dependency: A -> B -> C -> A
    stack = Stack(
        name="Circular Stack",
        projects=[
            StackProjectMember(project_id="p1", project_name="svc-a", depends_on=["svc-c"]),
            StackProjectMember(project_id="p2", project_name="svc-b", depends_on=["svc-a"]),
            StackProjectMember(project_id="p3", project_name="svc-c", depends_on=["svc-b"]),
        ],
    )

    boot_plan = stacks_svc.compute_boot_plan(stack)
    assert boot_plan.cycle_detected is True
    assert boot_plan.dependencies_valid is False
    assert "Circular dependency" in (boot_plan.error or "")


def test_readiness_probe_tcp_socket(service_factory):
    import socket
    import threading

    services = service_factory()
    stacks_svc = services.stacks

    # Bind a temporary mock listening socket
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    assigned_port = server_sock.getsockname()[1]

    def accept_thread():
        try:
            conn, _ = server_sock.accept()
            conn.close()
        except Exception:
            pass

    t = threading.Thread(target=accept_thread, daemon=True)
    t.start()

    gate = ReadinessGate(
        probe_type=ReadinessProbeType.TCP_PORT,
        host="127.0.0.1",
        port=assigned_port,
        service="mock-db",
    )

    result = stacks_svc.check_readiness_gate(gate)
    server_sock.close()

    assert result.healthy is True
    assert result.service == "mock-db"
    assert result.latency_ms >= 0


def test_readiness_probe_unreachable_port(service_factory):
    services = service_factory()
    stacks_svc = services.stacks

    # Test an unused port
    gate = ReadinessGate(
        probe_type=ReadinessProbeType.TCP_PORT,
        host="127.0.0.1",
        port=59999,
        service="offline-service",
        timeout_seconds=0.5,
    )

    result = stacks_svc.check_readiness_gate(gate)
    assert result.healthy is False
    assert "unavailable" in result.message or "failed" in result.message
