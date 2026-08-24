from fastapi.testclient import TestClient

from dev_agent.api.app import create_app
from dev_agent.llm.openai_compatible import OpenAICompatibleProvider
from dev_agent.models import ContainerInfo, PortBinding, PortOwner


def test_deterministic_resource_filter_returns_matches_and_neighbors(service_factory, tmp_path):
    workspace = tmp_path / "filter-demo"
    workspace.mkdir()
    (workspace / "compose.yaml").write_text("services:\n  web:\n    ports: ['5173:80']\n")
    container = ContainerInfo(
        id="web-id",
        name="filter-web",
        image="web:latest",
        state="running",
        compose_project="filter-demo",
        compose_service="web",
        compose_working_dir=str(workspace),
        ports=[PortBinding(host_port=5173, container_port=80)],
    )
    services = service_factory(
        [PortOwner(port=5173, container_id="web-id", container="filter-web", owner_type="container")],
        [container],
    )
    services.projects.register_project(workspace)
    services.system.processes = lambda _ports: []  # type: ignore[method-assign]

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/intelligence/filter",
            json={"query": "running containers on port 5173", "use_ai": False},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "deterministic"
    assert result["matched_count"] == 1
    assert result["graph"]["nodes"]
    assert any(item["resource_type"] == "container" for item in result["graph"]["nodes"])


def test_structured_resource_filter_uses_validated_plan(service_factory, monkeypatch):
    services = service_factory()
    services.settings.llm_api_key = "test-key"
    services.settings.filter_llm_model = "gpt-small"
    services.system.processes = lambda _ports: []  # type: ignore[method-assign]

    async def structured(*_args, **_kwargs):
        return (
            {
                "terms": [],
                "resource_types": ["port"],
                "statuses": [],
                "project_terms": [],
                "ports": [],
                "relationships": [],
                "only_running": False,
                "only_issues": False,
                "include_neighbors": True,
                "explanation": "Show ports.",
                "confidence": 0.95,
            },
            {"total_tokens": 20},
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "complete_structured", structured)
    with TestClient(create_app(services=services)) as client:
        result = client.post("/api/v1/intelligence/filter", json={"query": "show network listeners"}).json()

    assert result["mode"] == "ai"
    assert result["plan"]["resource_types"] == ["port"]


def test_admin_overview_reports_api_database_harness_and_process_metrics(service_factory):
    services = service_factory()
    services.settings.llm_api_key = "do-not-expose-this"
    services.settings.llm_model = "agent-model"
    with TestClient(create_app(services=services)) as client:
        client.get("/health")
        response = client.get("/api/v1/admin/overview")

    assert response.status_code == 200
    result = response.json()
    assert result["telemetry"]["requests"]["total"] >= 1
    assert result["database"]["counts"]["projects"] == 0
    assert result["harness"]["tool_count"] >= 10
    assert result["harness"]["filter_model"]
    assert result["process"]["pid"] > 0
    assert "do-not-expose-this" not in response.text
