import json
from typing import Any

from dev_agent.agent.prompts import SYSTEM_PROMPT
from dev_agent.agent.tools import AgentTools
from dev_agent.llm.base import LLMProvider


class AgentLoop:
    def __init__(self, provider: LLMProvider, tools: AgentTools, max_steps: int = 12) -> None:
        self.provider, self.tools, self.max_steps = provider, tools, max_steps

    async def run(self, message: str) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ]
        observations = []
        for _ in range(self.max_steps):
            response = await self.provider.complete(messages, self.tools.definitions())
            calls = response.get("tool_calls") or []
            if not calls:
                return {"message": response.get("content") or "No response", "observations": observations}
            messages.append(response)
            for call in calls:
                try:
                    result = self.tools.call(call["function"]["name"], call["function"].get("arguments", "{}"))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    result = {"error": "malformed_tool_call", "detail": str(exc)}
                observations.append({"tool": call.get("function", {}).get("name"), "result": result})
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)}
                )
        return {
            "message": "Agent step limit reached safely.",
            "observations": observations,
            "error": "max_steps_exceeded",
        }
