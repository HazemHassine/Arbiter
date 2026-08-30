from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from arbiter.models import ContainerInfo


class FakeScanner:
    def __init__(self, owners=None):
        self.owners = owners or []

    def scan(self):
        return [item.model_copy(deep=True) for item in self.owners]


class EmptyScanner:
    def scan(self):
        return []


class FakeDocker:
    def __init__(self, containers=None):
        self.containers = containers or []
        self.executed: list[tuple[str, str]] = []

    def list_containers(self, all=True):
        return list(self.containers)

    def inspect_container(self, identifier: str) -> ContainerInfo:
        matches = [item for item in self.containers if identifier in {item.id, item.name}]
        if not matches:
            raise LookupError(identifier)
        return matches[0]

    def container_action(self, identifier: str, action: str) -> dict[str, Any]:
        self.executed.append((identifier, action))
        return {"identifier": identifier, "action": action, "verified": True}

    def list_images(self) -> list[dict[str, Any]]:
        return []

    def list_volumes(self) -> list[dict[str, Any]]:
        return []

    def list_networks(self) -> list[dict[str, Any]]:
        return []

    def disk_usage(self) -> dict[str, Any]:
        return {"images": {"count": 0}}

    def logs(self, identifier: str, tail: int = 200) -> str:
        return f"logs for {identifier} (tail={tail})"


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
        if not self.responses:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Default fake response"))])
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])
