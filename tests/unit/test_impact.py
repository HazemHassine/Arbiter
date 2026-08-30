from arbiter.models import ActionSpec, ContainerInfo, PortBinding, PortOwner, Risk
from tests.fixtures.workspaces import create_sample_workspace


def test_impact_analysis_for_known_container(service_factory, tmp_path):
    workspace = tmp_path / "impact-demo"
    create_sample_workspace(workspace)
    container = ContainerInfo(
        id="cnt-web",
        name="impact-demo-web-1",
        image="web:v1",
        state="running",
        compose_project="impact-demo",
        compose_service="web",
        compose_working_dir=str(workspace),
        ports=[PortBinding(host_port=3000, container_port=8000)],
    )
    services = service_factory(
        [PortOwner(port=3000, pid=999, process="uvicorn", owner_type="process")],
        [container],
    )
    services.projects.register_project(workspace)

    spec = ActionSpec(
        action="container.restart",
        arguments={"identifier": "impact-demo-web-1"},
        summary="Restart web container",
        risk=Risk.LOW_RISK,
    )
    impact = services.impact.analyze(spec)

    assert impact["known"] is True
    assert impact["action"] == "container.restart"
    assert impact["target"]["type"] == "container"
    assert "web" in impact["target"]["label"]
    assert any("3000" in p for p in impact["ports"])


def test_impact_analysis_for_unknown_target(service_factory):
    services = service_factory()
    spec = ActionSpec(
        action="container.restart",
        arguments={"identifier": "nonexistent"},
        summary="Restart missing container",
        risk=Risk.LOW_RISK,
    )
    impact = services.impact.analyze(spec)
    assert impact["known"] is False
    assert "No runtime target" in impact["summary"]
