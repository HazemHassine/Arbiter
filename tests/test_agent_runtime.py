import asyncio
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from dev_agent.agent.runtime import AgentRuntime
from dev_agent.agent.service import AgentService
from dev_agent.agent.tools import AgentTools
from dev_agent.models import PortOwner


class FakeToolCallingModel(BaseChatModel):
    responses: list[AIMessage]
    bound_tool_names: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling-model"

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "FakeToolCallingModel":
        self.bound_tool_names = [tool.name for tool in tools]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


def test_langchain_runtime_executes_registered_tool_and_preserves_observations(service_factory):
    services = service_factory([PortOwner(port=8000, process="uvicorn", owner_type="process")])
    model = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "find_port_owner", "args": {"port": 8000}, "id": "call-1", "type": "tool_call"}
                ],
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


def test_langchain_runtime_streams_safe_model_and_tool_steps(service_factory):
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


def test_langchain_runtime_reports_invalid_tool_arguments(service_factory):
    model = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                invalid_tool_calls=[
                    {
                        "name": "find_port_owner",
                        "args": '{"port":',
                        "id": "call-invalid",
                        "error": "Invalid JSON arguments",
                        "type": "invalid_tool_call",
                    }
                ],
            )
        ]
    )
    runtime = AgentRuntime(model, AgentTools(AgentService(service_factory())), max_steps=2)

    result = asyncio.run(runtime.run("What owns a port?"))

    assert result["message"] == "No response"
    assert result["observations"] == [
        {
            "tool": "find_port_owner",
            "result": {"error": "malformed_tool_call", "detail": "Invalid JSON arguments"},
        }
    ]
