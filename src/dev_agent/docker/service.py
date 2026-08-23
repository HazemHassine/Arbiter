from typing import Any

import docker
from docker.errors import DockerException, NotFound

from dev_agent.models import ContainerInfo, PortBinding


class DockerUnavailable(RuntimeError):
    pass


class DockerService:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                self._client = docker.from_env()
                self._client.ping()
            except DockerException as exc:
                raise DockerUnavailable(f"Docker daemon unavailable: {exc}") from exc
        return self._client

    @staticmethod
    def _container_info(container: Any) -> ContainerInfo:
        attrs = container.attrs
        config = attrs.get("Config", {})
        state = attrs.get("State", {})
        labels = config.get("Labels") or {}
        bindings: list[PortBinding] = []
        for internal, published in (attrs.get("NetworkSettings", {}).get("Ports") or {}).items():
            container_port, _, protocol = internal.partition("/")
            for item in published or []:
                if str(item.get("HostPort", "")).isdigit():
                    bindings.append(
                        PortBinding(
                            host_port=int(item["HostPort"]),
                            container_port=int(container_port),
                            protocol=protocol or "tcp",
                            host_ip=item.get("HostIp"),
                            service=labels.get("com.docker.compose.service"),
                            source=labels.get("com.docker.compose.project.config_files"),
                        )
                    )
        image = config.get("Image") or next(iter(attrs.get("RepoTags") or []), "<unknown>")
        return ContainerInfo(
            id=container.id,
            name=container.name,
            image=image,
            state=state.get("Status", container.status),
            status=container.status,
            health=(state.get("Health") or {}).get("Status"),
            restart_count=attrs.get("RestartCount", 0),
            ports=bindings,
            mounts=attrs.get("Mounts", []),
            networks=list((attrs.get("NetworkSettings", {}).get("Networks") or {}).keys()),
            labels=labels,
            compose_project=labels.get("com.docker.compose.project"),
            compose_service=labels.get("com.docker.compose.service"),
            compose_working_dir=labels.get("com.docker.compose.project.working_dir"),
        )

    def list_containers(self, all: bool = True) -> list[ContainerInfo]:
        return [self._container_info(item) for item in self.client.containers.list(all=all)]

    def find_container(self, identifier: str) -> Any:
        exact = []
        partial = []
        for item in self.client.containers.list(all=True):
            if identifier in {item.id, item.id[:12], item.name}:
                exact.append(item)
            elif item.id.startswith(identifier) or identifier.lower() in item.name.lower():
                partial.append(item)
        matches = exact or partial
        if not matches:
            raise LookupError(f"Container not found: {identifier}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous container identifier: {identifier}")
        return matches[0]

    def inspect_container(self, identifier: str) -> ContainerInfo:
        return self._container_info(self.find_container(identifier))

    def logs(self, identifier: str, tail: int = 200) -> str:
        if not 1 <= tail <= 5000:
            raise ValueError("tail must be between 1 and 5000")
        return self.find_container(identifier).logs(tail=tail).decode(errors="replace")

    def stats(self, identifier: str) -> dict[str, Any]:
        return self.find_container(identifier).stats(stream=False)

    def container_action(self, identifier: str, action: str) -> dict[str, Any]:
        container = self.find_container(identifier)
        allowed = {"start", "stop", "restart", "pause", "unpause", "remove"}
        if action not in allowed:
            raise ValueError(f"Unsupported container action: {action}")
        kwargs = {"force": False} if action == "remove" else {}
        getattr(container, action)(**kwargs)
        if action != "remove":
            container.reload()
            info = self._container_info(container)
            return {"container": info.model_dump(mode="json"), "verified": True}
        try:
            self.client.containers.get(container.id)
        except NotFound:
            return {"removed": identifier, "verified": True}
        raise RuntimeError("Container still exists after removal")

    def list_images(self) -> list[dict[str, Any]]:
        used = {container.image.id for container in self.client.containers.list(all=True)}
        return [
            {
                "id": image.id,
                "tags": image.tags,
                "size": image.attrs.get("Size", 0),
                "created": image.attrs.get("Created"),
                "used": image.id in used,
            }
            for image in self.client.images.list(all=True)
        ]

    def inspect_image(self, identifier: str) -> dict[str, Any]:
        try:
            image = self.client.images.get(identifier)
        except NotFound as exc:
            raise LookupError(f"Image not found: {identifier}") from exc
        used = any(container.image.id == image.id for container in self.client.containers.list(all=True))
        return {
            "id": image.id,
            "tags": image.tags,
            "size": image.attrs.get("Size", 0),
            "created": image.attrs.get("Created"),
            "used": used,
            "labels": (image.attrs.get("Config") or {}).get("Labels") or {},
        }

    def remove_image(self, identifier: str) -> dict[str, Any]:
        if self.inspect_image(identifier)["used"]:
            raise ValueError("Image is currently used by a container")
        self.client.images.remove(identifier, force=False, noprune=False)
        try:
            self.client.images.get(identifier)
        except NotFound:
            return {"removed": identifier, "verified": True}
        raise RuntimeError("Image still exists after removal")

    def list_volumes(self) -> list[dict[str, Any]]:
        containers = self.client.containers.list(all=True)
        return [
            {
                "name": volume.name,
                "driver": volume.attrs.get("Driver"),
                "mountpoint": volume.attrs.get("Mountpoint"),
                "users": [
                    c.name for c in containers if any(m.get("Name") == volume.name for m in c.attrs.get("Mounts", []))
                ],
            }
            for volume in self.client.volumes.list()
        ]

    def inspect_volume(self, identifier: str) -> dict[str, Any]:
        try:
            volume = self.client.volumes.get(identifier)
        except NotFound as exc:
            raise LookupError(f"Volume not found: {identifier}") from exc
        users = [
            container.name
            for container in self.client.containers.list(all=True)
            if any(mount.get("Name") == volume.name for mount in container.attrs.get("Mounts", []))
        ]
        return {
            "name": volume.name,
            "driver": volume.attrs.get("Driver"),
            "mountpoint": volume.attrs.get("Mountpoint"),
            "labels": volume.attrs.get("Labels") or {},
            "users": users,
        }

    def remove_volume(self, identifier: str) -> dict[str, Any]:
        info = self.inspect_volume(identifier)
        if info["users"]:
            raise ValueError("Volume is currently used by a container")
        self.client.volumes.get(identifier).remove(force=False)
        try:
            self.client.volumes.get(identifier)
        except NotFound:
            return {"removed": identifier, "verified": True}
        raise RuntimeError("Volume still exists after removal")

    def list_networks(self) -> list[dict[str, Any]]:
        return [
            {
                "id": network.id,
                "name": network.name,
                "driver": network.attrs.get("Driver"),
                "scope": network.attrs.get("Scope"),
                "members": [item.get("Name") for item in (network.attrs.get("Containers") or {}).values()],
            }
            for network in self.client.networks.list()
        ]

    def inspect_network(self, identifier: str) -> dict[str, Any]:
        try:
            network = self.client.networks.get(identifier)
        except NotFound as exc:
            raise LookupError(f"Network not found: {identifier}") from exc
        return {
            "id": network.id,
            "name": network.name,
            "driver": network.attrs.get("Driver"),
            "scope": network.attrs.get("Scope"),
            "labels": network.attrs.get("Labels") or {},
            "members": list((network.attrs.get("Containers") or {}).values()),
        }

    def disk_usage(self) -> dict[str, Any]:
        data = self.client.df()
        return {
            "images": {"count": len(data.get("Images") or [])},
            "containers": {"count": len(data.get("Containers") or [])},
            "volumes": {"count": len(data.get("Volumes") or [])},
            "build_cache": {"count": len(data.get("BuildCache") or [])},
        }
