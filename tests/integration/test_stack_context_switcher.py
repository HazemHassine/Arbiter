from pathlib import Path

from arbiter.models import ReadinessGate, ReadinessProbeType, StackProjectMember


def test_stack_context_switcher_workflow(service_factory, tmp_path: Path, monkeypatch):
    # Setup two mock project directories with .env and compose.yaml
    proj_a_dir = tmp_path / "billing-stack"
    proj_a_dir.mkdir(parents=True)
    (proj_a_dir / ".env").write_text("PORT=8001\nDB_PORT=5432\n")
    (proj_a_dir / "compose.yaml").write_text(
        "services:\n  billing-api:\n    image: node:20\n    ports:\n      - '${PORT}:8001'\n"
    )

    proj_b_dir = tmp_path / "ai-stack"
    proj_b_dir.mkdir(parents=True)
    (proj_b_dir / ".env").write_text("PORT=8000\nQDRANT_PORT=6333\n")
    (proj_b_dir / "compose.yaml").write_text(
        "services:\n  ai-api:\n    image: python:3.12\n    ports:\n      - '${PORT}:8000'\n"
    )

    services = service_factory()
    proj_a = services.projects.register_project(proj_a_dir)
    proj_b = services.projects.register_project(proj_b_dir)

    stacks_svc = services.stacks

    # Mock compose start/stop for fast in-memory execution
    monkeypatch.setattr(stacks_svc.compose, "start", lambda file: {"started": True})
    monkeypatch.setattr(stacks_svc.compose, "stop", lambda file: {"stopped": True})

    # Create Stack A (Billing)
    gate = ReadinessGate(
        probe_type=ReadinessProbeType.TCP_PORT,
        host="127.0.0.1",
        port=8001,
        service="billing-api",
    )
    stack_a = stacks_svc.create_stack(
        name="Billing Microservices",
        description="Billing services",
        projects=[
            StackProjectMember(
                project_id=proj_a.id,
                project_name=proj_a.name,
                boot_stage=0,
                readiness_gates=[gate],
            )
        ],
    )

    # Create Stack B (AI Pipeline) with dynamic .env override
    stack_b = stacks_svc.create_stack(
        name="AI Pipeline + Vector DB",
        description="AI Pipeline",
        projects=[
            StackProjectMember(
                project_id=proj_b.id,
                project_name=proj_b.name,
                env_overrides={"PORT": "9000"},
                boot_stage=0,
                readiness_gates=[],
            )
        ],
    )

    # Initial activation of Stack A
    res_a = stacks_svc.switch_stack(stack_a.id, wait_for_readiness=False)
    assert res_a.target_stack_id == stack_a.id
    assert stacks_svc.get_active_stack().id == stack_a.id

    # 1-Click switch to Stack B
    res_b = stacks_svc.switch_stack(stack_b.id, hibernate_current=True, wait_for_readiness=False)
    assert res_b.target_stack_id == stack_b.id
    assert res_b.previous_stack_id == stack_a.id
    assert proj_a.name in res_b.stopped_projects
    assert stacks_svc.get_active_stack().id == stack_b.id

    # Verify .env override PORT=9000 was dynamically written with backup created
    env_content = (proj_b_dir / ".env").read_text()
    assert "PORT=9000" in env_content
    backups = list(proj_b_dir.glob(".env.bak.*"))
    assert len(backups) >= 1

    # Stop / Hibernate Stack B
    stop_res = stacks_svc.stop_stack(stack_b.id, hibernate=True)
    assert stop_res["status"] == "hibernated"
    assert stacks_svc.get_active_stack() is None
