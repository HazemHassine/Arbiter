from pathlib import Path


def create_sample_workspace(
    path: Path,
    *,
    service_name: str = "web",
    port_mapping: str = "3000:8000",
    env_variable: str | None = None,
    with_dockerfile: bool = True,
    with_makefile: bool = True,
    with_dockerignore: bool = True,
    with_env: bool = False,
) -> Path:
    """Helper to generate standard sample workspaces for testing."""
    path.mkdir(parents=True, exist_ok=True)

    port_spec = f"'${{{env_variable}}}:8000'" if env_variable else f"'{port_mapping}'"
    (path / "compose.yaml").write_text(
        f"""services:
  {service_name}:
    build: .
    ports: [{port_spec}]
    depends_on: [db]
    networks: [app]
  db:
    image: postgres:16
    ports: ['5432:5432']
    volumes: [db-data:/var/lib/postgresql/data]
networks:
  app: {{}}
volumes:
  db-data: {{}}
"""
    )

    if with_dockerfile:
        (path / "Dockerfile").write_text(
            'FROM python:3.12-slim\nWORKDIR /app\nEXPOSE 8000\nUSER app\nCMD ["python", "main.py"]\n'
        )

    if with_makefile:
        (path / "Makefile").write_text(
            "## Start local development\ndev: db\n\tuvicorn app:app --port 8000\ndb:\n\tdocker compose up -d db\n"
        )

    if with_dockerignore:
        (path / ".dockerignore").write_text(".git\n.venv\n*.pyc\n")

    if with_env or env_variable:
        env_content = f"{env_variable}=3000\n" if env_variable else "API_PORT=3000\n"
        (path / ".env").write_text(env_content)

    return path
