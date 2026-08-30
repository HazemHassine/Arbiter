import asyncio

from langchain_core.messages import AIMessage

from arbiter.agent.runtime import AgentRuntime
from arbiter.agent.service import AgentService
from arbiter.agent.tools import AgentTools
from arbiter.models import PortOwner
from tests.fixtures.doubles import FakeToolCallingModel


def test_agent_runtime_executes_tool_call_loop(service_factory):
    services = service_factory([PortOwner(port=8000, process="uvicorn", owner_type="process")])
    model = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "find_port_owner", "args": {"port": 8000}, "id": "call-1", "type": "tool_call"}],
            ),
            AIMessage(content="Port 8000 is owned by uvicorn."),
        ]
    )
    runtime = AgentRuntime(model, AgentTools(AgentService(services)), max_steps=4)

    result = asyncio.run(runtime.run("What owns port 8000?"))

    assert "find_port_owner" in model.bound_tool_names
    assert result["message"] == "Port 8000 is owned by uvicorn."
    assert result["observations"][0]["tool"] == "find_port_owner"
    assert result["observations"][0]["result"]["port"] == 8000
    assert result["observations"][0]["result"]["process"] == "uvicorn"


def test_agent_runtime_streams_steps(service_factory):
    services = service_factory([PortOwner(port=8000, process="uvicorn", owner_type="process")])
    model = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "find_port_owner", "args": {"port": 8000}, "id": "call-stream", "type": "tool_call"}
                ],
            ),
            AIMessage(content="**Port 8000** is owned by `uvicorn`."),
        ]
    )
    runtime = AgentRuntime(model, AgentTools(AgentService(services)), max_steps=4)

    async def collect():
        return [event async for event in runtime.stream("What owns port 8000?")]

    events = asyncio.run(collect())

    tool_started = next(event for event in events if event["type"] == "step_started" and event["kind"] == "tool")
    tool_completed = next(event for event in events if event["type"] == "step_completed" and event["kind"] == "tool")
    final = events[-1]
    assert tool_started["step_id"] == "call-stream"
    assert tool_started["arguments"] == {"port": 8000}
    assert tool_completed["step_id"] == "call-stream"
    assert tool_completed["result"]["process"] == "uvicorn"
    assert final["type"] == "runtime_completed"
    assert final["outcome"]["message"] == "**Port 8000** is owned by `uvicorn`."
