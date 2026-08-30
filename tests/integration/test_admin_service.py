from arbiter.admin.service import AdminService


def test_admin_overview_metrics(service_factory):
    services = service_factory()
    admin = AdminService(services)
    overview = admin.overview()

    assert "telemetry" in overview
    assert "database" in overview
    assert "harness" in overview
    assert "process" in overview
    assert overview["process"]["pid"] > 0
    assert overview["harness"]["tool_count"] >= 10
    assert "documentation" in overview
    assert len(overview["documentation"]["sections"]) >= 4
