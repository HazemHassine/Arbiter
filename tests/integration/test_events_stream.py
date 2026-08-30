import asyncio

from arbiter.events.models import SystemEvent
from arbiter.events.service import EventBus


def test_event_bus_publish_and_history():
    bus = EventBus(history_size=10)
    event1 = SystemEvent(
        type="container_started",
        resource_type="container",
        resource_id="cnt-1",
        action="start",
        message="Container started",
    )
    event2 = SystemEvent(
        type="port_conflict_detected",
        resource_type="port",
        resource_id="8000",
        action="conflict",
        message="Port in use",
    )

    bus.publish(event1)
    bus.publish(event2)

    recent = bus.recent(limit=5)
    assert len(recent) == 2
    assert recent[0].type == "container_started"
    assert recent[1].type == "port_conflict_detected"

    stats = bus.stats()
    assert stats["published_total"] == 2
    assert stats["buffered"] == 2
    assert stats["types"]["container_started"] == 1


def test_event_bus_stream_subscriber():
    bus = EventBus(history_size=10)
    event = SystemEvent(
        type="test_event",
        resource_type="system",
        resource_id="res-1",
        action="test",
        message="Testing stream",
    )
    bus.publish(event)

    async def get_stream_item():
        async for line in bus.stream():
            return line

    line = asyncio.run(get_stream_item())
    assert "data: " in line
    assert "test_event" in line
