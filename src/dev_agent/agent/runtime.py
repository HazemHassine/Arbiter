import json
import threading
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any
from uuid import UUID

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError

from dev_agent.agent.prompts import SYSTEM_PROMPT
from dev_agent.agent.tools import AgentTools
from dev_agent.config import Settings
from dev_agent.security import redact
from dev_agent.telemetry import TelemetryRegistry


class AgentRuntimeError(RuntimeError):
    """Sanitized model error that is safe to return from the public API."""


class AgentTelemetryCallback(BaseCallbackHandler):
    """Bridge LangChain model callbacks into the existing local telemetry registry."""

    def __init__(self, telemetry: TelemetryRegistry, model: str) -> None:
        self.telemetry = telemetry
        self.model = model
        self._started: dict[UUID, float] = {}
        self._lock = threading.Lock()

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            self._started[run_id] = time.monotonic()

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        usage = dict((response.llm_output or {}).get("token_usage") or {})
        if not usage and response.generations:
            message = response.generations[0][0].message
            usage = dict(getattr(message, "usage_metadata", None) or {})
        self._record(run_id, success=True, usage=usage)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._record(run_id, success=False, error_code=type(error).__name__)

    def _record(
        self,
        run_id: UUID,
        *,
        success: bool,
        usage: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        with self._lock:
            started = self._started.pop(run_id, time.monotonic())
        self.telemetry.record_llm(
            operation="agent",
            model=self.model,
            success=success,
            duration_ms=(time.monotonic() - started) * 1000,
            usage=usage,
            error_code=error_code,
        )


def build_agent_model(settings: Settings, telemetry: TelemetryRegistry) -> ChatOpenAI:
    """Create the standard LangChain chat-model integration from application settings."""

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        reasoning_effort=settings.llm_reasoning_effort,
        use_responses_api=False,
        max_retries=2,
        callbacks=[AgentTelemetryCallback(telemetry, settings.llm_model)],
    )


class AgentRuntime:
    """LangChain v1 agent runtime, backed by LangGraph's execution engine."""

    def __init__(self, model: BaseChatModel, tools: AgentTools, max_steps: int = 12) -> None:
        self.max_steps = max_steps
        self.graph = create_agent(
            model=model,
            tools=tools.langchain_tools(),
            system_prompt=SYSTEM_PROMPT,
            middleware=[ModelCallLimitMiddleware(run_limit=max_steps, exit_behavior="end")],
            name="local_dev_environment_agent",
        )

    async def run(self, message: str) -> dict[str, Any]:
        outcome: dict[str, Any] | None = None
        async for event in self.stream(message):
            if event["type"] == "runtime_completed":
                outcome = event["outcome"]
        return outcome or {"message": "No response", "observations": []}

    async def stream(self, message: str) -> AsyncIterator[dict[str, Any]]:
        messages: list[Any] = []
        model_call = 1
        model_step_id = f"model-{model_call}"
        yield {
            "type": "step_started",
            "step_id": model_step_id,
            "kind": "model",
            "title": "Planning next action",
            "detail": "Choosing the next safe action from the available typed tools.",
        }
        try:
            updates = self.graph.astream(
                {"messages": [{"role": "user", "content": message}]},
                config={"recursion_limit": self.max_steps * 3 + 2},
                stream_mode="updates",
                version="v2",
            )
            async for update in updates:
                update_messages = _messages_from_update(update)
                saw_tool_result = False
                for item in update_messages:
                    messages.append(item)
                    if isinstance(item, AIMessage):
                        if model_step_id:
                            detail = (
                                f"Selected {len(item.tool_calls)} tool call(s)."
                                if item.tool_calls
                                else "Prepared the final response from collected evidence."
                            )
                            yield {
                                "type": "step_completed",
                                "step_id": model_step_id,
                                "kind": "model",
                                "title": "Planning next action" if model_call == 1 else "Evaluating evidence",
                                "detail": detail,
                                "status": "completed",
                            }
                            model_step_id = ""
                        for call in item.tool_calls:
                            yield {
                                "type": "step_started",
                                "step_id": call["id"],
                                "kind": "tool",
                                "title": _tool_title(call["name"]),
                                "detail": f"Calling {call['name']} with validated arguments.",
                                "tool": call["name"],
                                "arguments": redact(call.get("args") or {}),
                            }
                        for call in item.invalid_tool_calls:
                            step_id = call.get("id") or f"invalid-{len(messages)}"
                            yield {
                                "type": "step_started",
                                "step_id": step_id,
                                "kind": "tool",
                                "title": _tool_title(call.get("name") or "invalid_tool_call"),
                                "detail": "The model requested a tool with invalid arguments.",
                                "tool": call.get("name"),
                            }
                            yield {
                                "type": "step_completed",
                                "step_id": step_id,
                                "kind": "tool",
                                "title": _tool_title(call.get("name") or "invalid_tool_call"),
                                "detail": call.get("error") or "The model returned invalid tool arguments.",
                                "status": "error",
                            }
                    elif isinstance(item, ToolMessage):
                        saw_tool_result = True
                        result = _tool_result(item)
                        failed = item.status == "error" or isinstance(result, dict) and bool(result.get("error"))
                        yield {
                            "type": "step_completed",
                            "step_id": item.tool_call_id,
                            "kind": "tool",
                            "title": _tool_title(item.name or "tool"),
                            "detail": "Tool returned an error." if failed else "Tool completed and returned evidence.",
                            "tool": item.name,
                            "result": redact(result),
                            "status": "error" if failed else "completed",
                        }
                if saw_tool_result:
                    model_call += 1
                    model_step_id = f"model-{model_call}"
                    yield {
                        "type": "step_started",
                        "step_id": model_step_id,
                        "kind": "model",
                        "title": "Evaluating evidence",
                        "detail": "Reviewing tool results and deciding whether more evidence is needed.",
                    }
        except APIStatusError as exc:
            detail = str(getattr(exc, "message", "") or f"HTTP {exc.status_code}")
            raise AgentRuntimeError(_sanitize_error(detail)) from exc
        except APITimeoutError as exc:
            raise AgentRuntimeError("LLM request timed out") from exc
        except APIConnectionError as exc:
            raise AgentRuntimeError("LLM provider could not be reached") from exc

        final = next(
            (item for item in reversed(messages) if isinstance(item, AIMessage) and not item.tool_calls),
            None,
        )
        yield {
            "type": "runtime_completed",
            "outcome": {
                "message": final.text if final and final.text else "No response",
                "observations": _observations(messages),
            },
        }


def _observations(messages: list[Any]) -> list[dict[str, Any]]:
    observations = [_observation(item) for item in messages if isinstance(item, ToolMessage)]
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        observations.extend(
            {
                "tool": call.get("name"),
                "result": {
                    "error": "malformed_tool_call",
                    "detail": call.get("error") or "The model returned invalid tool arguments.",
                },
            }
            for call in message.invalid_tool_calls
        )
    return observations


def _observation(message: ToolMessage) -> dict[str, Any]:
    return {"tool": message.name, "result": _tool_result(message)}


def _tool_result(message: ToolMessage) -> Any:
    result: Any = message.content
    if isinstance(result, str):
        with suppress(json.JSONDecodeError):
            result = json.loads(result)
    return result


def _messages_from_update(update: dict[str, Any]) -> list[Any]:
    if update.get("type") != "updates" or not isinstance(update.get("data"), dict):
        return []
    messages: list[Any] = []
    for value in update["data"].values():
        if isinstance(value, dict) and isinstance(value.get("messages"), list):
            messages.extend(value["messages"])
    return messages


def _tool_title(name: str) -> str:
    return name.replace("_", " ").strip().capitalize() or "Tool call"


def _sanitize_error(detail: str) -> str:
    return detail.replace("\n", " ")[:500] or "LLM provider rejected the request"
