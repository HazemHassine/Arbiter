from fastapi.testclient import TestClient

from dev_agent.agent.service import AgentService
from dev_agent.agent.tools import AgentTools
from dev_agent.api.app import create_app
from dev_agent.models import ContainerInfo, PortOwner


def test_health_port_project_and_docker_apis(service_factory, tmp_path):
    container = ContainerInfo(id="id1", name="postgres", image="postgres:16", state="running")
    services = service_factory([PortOwner(port=5432, process="postgres", owner_type="process")], [container])
    with TestClient(create_app(services=services)) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/", follow_redirects=False).headers["location"] == "/ui/"
        ui = client.get("/ui/")
        assert ui.status_code == 200
        assert "Localhost — Developer Control Plane" in ui.text
        assert 'id="resource-selector"' in ui.text
        assert 'id="container-log-output"' in ui.text
        assert 'id="preview-frame"' in ui.text
        assert client.get("/api/v1/ports/5432").json()["process"] == "postgres"
        project = tmp_path / "api-demo"
        project.mkdir()
        (project / "compose.yaml").write_text("services:\n  api:\n    ports: ['8123:80']\n")
        assert client.post("/api/v1/projects", json={"path": str(project)}).status_code == 201
        assert client.get("/api/v1/projects").json()[0]["name"] == "api-demo"
        assert client.get("/api/v1/containers").json()[0]["name"] == "postgres"


def test_approval_api(service_factory):
    services = service_factory()
    client = TestClient(create_app(services=services))
    response = client.post("/api/v1/containers/demo/start").json()
    assert response["status"] == "approval_required"
    result = client.post(f"/api/v1/approvals/{response['approval']['id']}/approve").json()
    assert result["status"] == "completed"


def test_agent_deterministic_queries_and_tool_registry(service_factory):
    services = service_factory([PortOwner(port=8000, process="uvicorn", owner_type="process")])
    agent = AgentService(services)
    answer = agent.query("what is using port 8000?")
    assert answer["observations"][0]["process"] == "uvicorn"
    tools = AgentTools(agent)
    assert "find_port_owner" in {item["function"]["name"] for item in tools.definitions()}
    assert tools.call("find_port_owner", '{"port": 8000}')["process"] == "uvicorn"


def test_agent_query_api(service_factory):
    client = TestClient(create_app(services=service_factory()))
    response = client.post("/api/v1/agent/query", json={"message": "Which projects have port conflicts?"})
    assert response.status_code == 200
    assert response.json()["approval_required"] is False


def test_prepare_intent_proposes_env_port_repair(service_factory, tmp_path):
    project = tmp_path / "repair-me"
    project.mkdir()
    (project / ".env").write_text("API_PORT=8000\n")
    (project / "compose.yaml").write_text("services:\n  api:\n    ports: ['${API_PORT}:80']\n")
    services = service_factory([PortOwner(port=8000, process="other", owner_type="process")])
    services.projects.register_project(project)
    response = AgentService(services).query("Prepare repair-me and resolve port conflicts")
    assert response["approval_required"] is True
    change = response["actions"][0]["approval"]["arguments"]["changes"][0]
    assert change["env_variable"] == "API_PORT"
    assert change["new_port"] == 8001
