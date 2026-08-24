import asyncio
import json
import threading
from collections import Counter, deque
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from dev_agent.events.models import SystemEvent


class EventBus:
    def __init__(self, history_size: int = 250) -> None:
        self.history: deque[SystemEvent] = deque(maxlen=history_size)
        self._subscribers: set[asyncio.Queue[SystemEvent]] = set()
        self._published_total = 0
        self._types: Counter[str] = Counter()
        self._started_at = datetime.now(UTC)

    def publish(self, event: SystemEvent) -> SystemEvent:
        self.history.append(event)
        self._published_total += 1
        self._types[event.type] += 1
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    continue
        return event

    def stats(self) -> dict[str, Any]:
        return {
            "started_at": self._started_at.isoformat(),
            "published_total": self._published_total,
            "buffered": len(self.history),
            "history_capacity": self.history.maxlen,
            "subscribers": len(self._subscribers),
            "types": dict(self._types.most_common(12)),
            "last_event": self.history[-1].model_dump(mode="json") if self.history else None,
        }

    def recent(self, limit: int = 100) -> list[SystemEvent]:
        return list(self.history)[-max(1, min(limit, len(self.history))) :]

    async def stream(self) -> AsyncIterator[str]:
        queue: asyncio.Queue[SystemEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            for event in self.recent(25):
                yield self._encode(event)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                else:
                    yield self._encode(event)
        finally:
            self._subscribers.discard(queue)

    @staticmethod
    def _encode(event: SystemEvent) -> str:
        # The event type remains in the JSON payload. Keeping SSE's native event
        # name as "message" lets lightweight clients receive every resource type.
        return f"id: {event.id}\ndata: {json.dumps(event.model_dump(mode='json'))}\n\n"


class ObservationService:
    """Combines Docker events with inexpensive polling for host state changes."""

    def __init__(self, services, bus: EventBus, interval_seconds: float = 3.0) -> None:
        self.services = services
        self.bus = bus
        self.interval_seconds = max(1.0, interval_seconds)
        self._stop = asyncio.Event()
        self._poll_task: asyncio.Task[None] | None = None
        self._docker_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._snapshots: dict[str, dict[str, dict[str, Any]]] = {}
        self._started_at: datetime | None = None

    async def start(self) -> None:
        if self._poll_task:
            return
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._started_at = datetime.now(UTC)
        self._poll_task = asyncio.create_task(self._poll(), name="dev-agent-observer")
        if callable(getattr(self.services.docker, "events", None)):
            self._docker_thread = threading.Thread(
                target=self._watch_docker_events, daemon=True, name="dev-agent-docker-events"
            )
            self._docker_thread.start()

    async def stop(self) -> None:
        self._stop.set()
        if self._poll_task:
            self._poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._poll_task is not None and not self._poll_task.done(),
            "interval_seconds": self.interval_seconds,
            "started_at": self._started_at,
            "docker_event_stream": self._docker_thread is not None and self._docker_thread.is_alive(),
        }

    async def poll_once(self) -> None:
        try:
            ports = self.services.ports.list_used_ports()
        except Exception:
            ports = []
        try:
            containers = self.services.docker.list_containers()
        except Exception:
            containers = []
        port_by_pid: dict[int, list[int]] = {}
        for port in ports:
            if port.pid:
                port_by_pid.setdefault(port.pid, []).append(port.port)
        try:
            processes = self.services.system.processes(port_by_pid)
        except Exception:
            processes = []
        snapshots = {
            "container": {
                item.id: {
                    "name": item.name,
                    "state": item.state,
                    "project": item.compose_project,
                    "service": item.compose_service,
                }
                for item in containers
            },
            "port": {
                f"{item.protocol}:{item.port}:{item.pid or item.container_id or item.host}": item.model_dump(
                    mode="json"
                )
                for item in ports
            },
            "process": {
                str(item["pid"]): {
                    "process": item.get("process"),
                    "kind": item.get("kind"),
                    "ports": item.get("ports", []),
                }
                for item in processes
            },
        }
        if not self._snapshots:
            self._snapshots = snapshots
            return
        changed = False
        changed |= self._diff_containers(self._snapshots["container"], snapshots["container"])
        changed |= self._diff_ports(self._snapshots["port"], snapshots["port"])
        changed |= self._diff_processes(self._snapshots["process"], snapshots["process"])
        self._snapshots = snapshots
        if changed:
            self._publish(
                SystemEvent(
                    type="topology.updated",
                    resource_type="topology",
                    resource_id="local",
                    action="updated",
                    message="Local development topology changed",
                )
            )

    async def _poll(self) -> None:
        while not self._stop.is_set():
            with suppress(Exception):
                await self.poll_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue

    def _diff_containers(self, before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> bool:
        changed = False
        for identifier, item in after.items():
            prior = before.get(identifier)
            if not prior:
                changed = True
                self._publish(
                    self._event("container", identifier, "started", f"Container {item['name']} appeared", item)
                )
            elif prior["state"] != item["state"]:
                changed = True
                action = "started" if item["state"] == "running" else "stopped"
                self._publish(self._event("container", identifier, action, f"Container {item['name']} {action}", item))
        for identifier, item in before.items():
            if identifier not in after:
                changed = True
                self._publish(
                    self._event("container", identifier, "destroyed", f"Container {item['name']} disappeared", item)
                )
        return changed

    def _diff_ports(self, before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> bool:
        changed = False
        for identifier, item in after.items():
            if identifier not in before:
                changed = True
                self._publish(
                    self._event("port", identifier, "listening", f"Port {item['port']} is now listening", item)
                )
        for identifier, item in before.items():
            if identifier not in after:
                changed = True
                self._publish(
                    self._event("port", identifier, "closed", f"Port {item['port']} is no longer listening", item)
                )
        return changed

    def _diff_processes(self, before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> bool:
        changed = False
        for identifier, item in after.items():
            if identifier not in before and (item["kind"] != "process" or item["ports"]):
                changed = True
                self._publish(
                    self._event(
                        "process", identifier, "started", f"Process {item.get('process') or identifier} started", item
                    )
                )
        for identifier, item in before.items():
            if identifier not in after and (item["kind"] != "process" or item["ports"]):
                changed = True
                self._publish(
                    self._event(
                        "process", identifier, "exited", f"Process {item.get('process') or identifier} exited", item
                    )
                )
        return changed

    @staticmethod
    def _event(resource_type: str, resource_id: str, action: str, message: str, data: dict[str, Any]) -> SystemEvent:
        return SystemEvent(
            type=f"{resource_type}.{action}",
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            message=message,
            data=data,
        )

    def _watch_docker_events(self) -> None:
        try:
            for raw in self.services.docker.events():
                if self._stop.is_set():
                    return
                event_type = str(raw.get("Type") or "docker")
                if event_type not in {"container", "image", "network", "volume"}:
                    continue
                actor = raw.get("Actor") or {}
                attributes = actor.get("Attributes") or {}
                identifier = str(actor.get("ID") or attributes.get("name") or "unknown")
                action = str(raw.get("Action") or "changed")
                label = attributes.get("name") or identifier[:12]
                self._publish(
                    SystemEvent(
                        type=f"docker.{event_type}.{action}",
                        resource_type=event_type,
                        resource_id=identifier,
                        action=action,
                        message=f"Docker {event_type} {label} {action}",
                        data={"attributes": attributes, "time": raw.get("time")},
                    )
                )
        except Exception:
            return

    def _publish(self, event: SystemEvent) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self.bus.publish, event)
        else:
            self.bus.publish(event)
