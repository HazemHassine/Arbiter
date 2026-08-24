from dev_agent.runtimes.models import RuntimeCapability
from dev_agent.system.processes import command_exists, run


class RuntimeService:
    """Detect local container runtimes without claiming unsupported operations."""

    def __init__(self, docker) -> None:
        self.docker = docker

    def list_capabilities(self) -> list[RuntimeCapability]:
        docker_available = False
        docker_detail = None
        try:
            self.docker.client.ping()
            docker_available = True
        except Exception as exc:
            docker_detail = str(exc)
        podman_available, podman_detail = self._command_version("podman")
        nerdctl_available, nerdctl_detail = self._command_version("nerdctl")
        containerd_available = command_exists("containerd")
        return [
            RuntimeCapability(
                name="Docker",
                available=docker_available,
                support="full" if docker_available else "unavailable",
                detail=docker_detail,
                capabilities=["inspect", "lifecycle", "events", "images", "volumes", "networks"]
                if docker_available
                else [],
            ),
            RuntimeCapability(
                name="Podman",
                available=podman_available,
                support="inspection_only" if podman_available else "not_detected",
                detail=podman_detail,
                capabilities=["detected", "CLI inspection planned"] if podman_available else [],
            ),
            RuntimeCapability(
                name="nerdctl / containerd",
                available=nerdctl_available or containerd_available,
                support="inspection_only"
                if nerdctl_available
                else "detected_only"
                if containerd_available
                else "not_detected",
                detail=nerdctl_detail or ("containerd binary detected" if containerd_available else None),
                capabilities=["detected"] if nerdctl_available or containerd_available else [],
            ),
        ]

    @staticmethod
    def _command_version(command: str) -> tuple[bool, str | None]:
        if not command_exists(command):
            return False, None
        try:
            result = run([command, "--version"], timeout=3)
        except OSError as exc:
            return True, str(exc)
        detail = (result.stdout or result.stderr).strip().splitlines()
        return True, detail[0] if detail else None
