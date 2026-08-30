from arbiter.models import PortOwner


def test_cross_project_port_conflicts(service_factory, tmp_path):
    for name in ("project-a", "project-b"):
        proj_dir = tmp_path / name
        proj_dir.mkdir()
        (proj_dir / "compose.yaml").write_text("services:\n  api:\n    ports: ['8000:80']\n")

    services = service_factory()
    services.projects.register_project(tmp_path / "project-a")
    services.projects.register_project(tmp_path / "project-b")

    conflicts = services.ports.detect_port_conflicts()
    assert len(conflicts) >= 1
    conflict = next(c for c in conflicts if c["port"] == 8000)
    claims = {claim["project"] for claim in conflict["claims"]}
    assert claims == {"project-a", "project-b"}


def test_port_reconciliation_plan_proposes_clean_replacements(service_factory, tmp_path):
    # Occupy port 8000 at runtime
    services = service_factory([PortOwner(port=8000, process="existing-app")])

    proj_dir = tmp_path / "target-proj"
    proj_dir.mkdir()
    (proj_dir / "compose.yaml").write_text("""services:
  web:
    ports: ['8000:80']
  api:
    ports: ['8000:8000']
""")
    project = services.projects.register_project(proj_dir)
    plan = services.ports.plan_port_reconciliation(project)

    assert plan.status == "changes_required"
    assert len(plan.changes) == 2
    suggested = {c.suggested_port for c in plan.changes}
    assert 8000 not in suggested
    assert len(suggested) == 2
