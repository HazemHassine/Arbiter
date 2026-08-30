from fastapi.testclient import TestClient

from arbiter.api.app import create_app
from tests.fixtures.workspaces import create_sample_workspace


def test_api_projects_lifecycle_and_prepare(service_factory, tmp_path):
    workspace = tmp_path / "api-project"
    create_sample_workspace(workspace)
    client = TestClient(create_app(services=service_factory()))

    # Register project
    res = client.post("/api/v1/projects", json={"path": str(workspace)})
    assert res.status_code == 201
    project_id = res.json()["id"]

    # List projects
    list_res = client.get("/api/v1/projects")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    # Prepare project
    prep_res = client.post(
        f"/api/v1/projects/{project_id}/prepare",
        json={"resolve_port_conflicts": True, "start": False, "verify": True},
    )
    assert prep_res.status_code == 200


def test_api_project_files_endpoints(service_factory, tmp_path):
    workspace = tmp_path / "files-api-proj"
    create_sample_workspace(workspace)
    services = service_factory()
    project = services.projects.register_project(workspace)
    client = TestClient(create_app(services=services))

    # List files
    files_res = client.get(f"/api/v1/projects/{project.id}/files")
    assert files_res.status_code == 200
    paths = [f["path"] for f in files_res.json()]
    assert "compose.yaml" in paths

    # Get file content
    content_res = client.get(f"/api/v1/projects/{project.id}/files/content?path=compose.yaml")
    assert content_res.status_code == 200
    file_data = content_res.json()
    assert "services:" in file_data["content"]
    sha256 = file_data["sha256"]

    # Save file content
    new_content = file_data["content"] + "\n# updated by api\n"
    save_res = client.post(
        f"/api/v1/projects/{project.id}/files/save",
        json={"path": "compose.yaml", "content": new_content, "expected_sha256": sha256},
    )
    assert save_res.status_code == 200
    assert save_res.json()["status"] == "approval_required"
