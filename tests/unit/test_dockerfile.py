from pathlib import Path

from arbiter.dockerfile.service import DockerfileService


def test_inspect_single_stage_dockerfile(tmp_path: Path):
    df = tmp_path / "Dockerfile"
    df.write_text("""FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
EXPOSE 8000 8080/tcp
USER appuser
CMD ["python", "app.py"]
""")
    service = DockerfileService()
    info = service.inspect(df)

    assert len(info.stages) == 1
    assert info.stages[0].base_image == "python:3.12-slim"
    assert info.workdir == "/app"
    assert info.exposed_ports == ["8000", "8080/tcp"]
    assert info.user == "appuser"
    assert info.cmd == '["python", "app.py"]'
    assert len(info.run) == 1
    assert not any(w["severity"] == "confirmed_issue" for w in info.warnings)


def test_inspect_multi_stage_dockerfile(tmp_path: Path):
    df = tmp_path / "Dockerfile"
    df.write_text("""FROM node:20 AS builder
WORKDIR /build
COPY package.json .
RUN npm install

FROM nginx:1.25-alpine
COPY --from=builder /build/dist /usr/share/nginx/html
EXPOSE 80
""")
    service = DockerfileService()
    info = service.inspect(df)

    assert len(info.stages) == 2
    assert info.stages[0].name == "builder"
    assert info.stages[0].base_image == "node:20"
    assert info.stages[1].base_image == "nginx:1.25-alpine"
    assert info.exposed_ports == ["80"]
    # Should flag missing USER as possible issue
    assert any("root" in w["message"] for w in info.warnings)


def test_dockerfile_unpinned_base_image_warning(tmp_path: Path):
    df = tmp_path / "Dockerfile"
    df.write_text("FROM alpine:latest\n")
    service = DockerfileService()
    info = service.inspect(df)
    assert any("not pinned" in w["message"] for w in info.warnings)


def test_dockerfile_no_from_issue(tmp_path: Path):
    df = tmp_path / "Dockerfile"
    df.write_text("RUN echo hello\n")
    service = DockerfileService()
    info = service.inspect(df)
    assert any("no FROM instruction" in w["message"] for w in info.warnings)
