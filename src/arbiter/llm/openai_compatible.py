import json
import time
from typing import Any

import httpx


class LLMProviderError(RuntimeError):
    """Sanitized upstream error safe to include in an agent response."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60,
        reasoning_effort: str | None = "none",
        transport: httpx.AsyncBaseTransport | None = None,
        telemetry: Any | None = None,
    ) -> None:
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout
        self.reasoning_effort = reasoning_effort
        self.transport = transport
        self.telemetry = telemetry

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.api_key or not self.model:
            raise LLMProviderError("LLM is not configured")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        body = await self._request(payload, "agent")
        try:
            return body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError("LLM provider returned a malformed response") from exc

    async def complete_structured(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        *,
        name: str,
        operation: str = "structured_output",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.api_key or not self.model:
            raise LLMProviderError("LLM is not configured")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        body = await self._request(payload, operation)
        try:
            content = body["choices"][0]["message"]["content"]
            return json.loads(content), body.get("usage") or {}
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError("LLM provider returned malformed structured output") from exc

    async def _request(self, payload: dict[str, Any], operation: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            error = self._error_details(exc.response)
            self._record(operation, False, started, error_code=error["code"])
            raise LLMProviderError(error["message"], status_code=exc.response.status_code, code=error["code"]) from exc
        except httpx.TimeoutException as exc:
            self._record(operation, False, started, error_code="timeout")
            raise LLMProviderError("LLM request timed out") from exc
        except httpx.RequestError as exc:
            self._record(operation, False, started, error_code="unreachable")
            raise LLMProviderError("LLM provider could not be reached") from exc
        except (TypeError, ValueError) as exc:
            self._record(operation, False, started, error_code="malformed_response")
            raise LLMProviderError("LLM provider returned a malformed response") from exc
        self._record(operation, True, started, usage=body.get("usage") or {})
        return body

    def _record(
        self,
        operation: str,
        success: bool,
        started: float,
        *,
        usage: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        if self.telemetry:
            self.telemetry.record_llm(
                operation=operation,
                model=self.model,
                success=success,
                duration_ms=(time.monotonic() - started) * 1000,
                usage=usage,
                error_code=error_code,
            )

    @staticmethod
    def _error_details(response: httpx.Response) -> dict[str, str | None]:
        default = f"LLM provider rejected the request with HTTP {response.status_code}"
        try:
            error = response.json().get("error", {})
            message = str(error.get("message") or default).replace("\n", " ")[:500]
            code = error.get("code") or error.get("type")
            return {"message": message, "code": str(code) if code else None}
        except (ValueError, AttributeError):
            return {"message": default, "code": None}
