from pathlib import Path

import pytest

from tests.fixtures.workspaces import create_sample_workspace


def test_list_and_read_project_files(service_factory, tmp_path: Path):
    workspace = tmp_path / "files-demo"
    create_sample_workspace(workspace, with_env=True)
    services = service_factory()
    project = services.projects.register_project(workspace)

    files = services.files.list_files(project.id)
    names = {f.name for f in files}
    assert {"compose.yaml", "Dockerfile", "Makefile", ".env", ".dockerignore"} <= names

    content = services.files.read(project.id, "compose.yaml")
    assert content.path == "compose.yaml"
    assert "services:" in content.content
    assert content.kind == "compose"
    assert len(content.sha256) == 64


def test_read_disallowed_file_or_path_traversal_rejected(service_factory, tmp_path: Path):
    workspace = tmp_path / "safety-demo"
    create_sample_workspace(workspace)
    (workspace / "secret.py").write_text("API_KEY=123\n")
    services = service_factory()
    project = services.projects.register_project(workspace)

    # Disallowed file extension (.py)
    with pytest.raises(ValueError, match="not editable through the control plane"):
        services.files.read(project.id, "secret.py")

    # Path traversal attack
    with pytest.raises(ValueError, match="relative path inside the registered project"):
        services.files.read(project.id, "../other.yaml")


def test_preview_and_apply_update_with_undo(service_factory, tmp_path: Path):
    workspace = tmp_path / "edit-demo"
    create_sample_workspace(workspace)
    compose = workspace / "compose.yaml"
    services = service_factory()
    project = services.projects.register_project(workspace)

    current = services.files.read(project.id, "compose.yaml")
    new_content = current.content + "\n# Test comment\n"

    # Preview
    preview = services.files.preview(project.id, "compose.yaml", new_content, current.sha256)
    assert "+# Test comment" in preview.diff

    # Apply update
    result = services.files.apply_update(project.id, "compose.yaml", new_content, current.sha256)
    assert result["verified"] is True
    assert compose.read_text() == new_content

    # Undo
    undo_result = services.files.undo_latest(project.id, "compose.yaml")
    assert undo_result["verified"] is True
    assert compose.read_text() == current.content


def test_apply_update_detects_hash_mismatch(service_factory, tmp_path: Path):
    workspace = tmp_path / "stale-demo"
    create_sample_workspace(workspace)
    services = service_factory()
    project = services.projects.register_project(workspace)

    with pytest.raises(ValueError, match="File changed since this edit was proposed"):
        services.files.apply_update(
            project.id,
            "compose.yaml",
            "services:\n  new: {}\n",
            expected_sha256="wrong-hash" + "0" * 54,
        )
