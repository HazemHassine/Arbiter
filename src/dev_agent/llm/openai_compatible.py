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
    ) -> None:
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout
        self.reasoning_effort = reasoning_effort
        self.transport = transport

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
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
                return body["choices"][0]["message"]
        except httpx.HTTPStatusError as exc:
            error = self._error_details(exc.response)
            raise LLMProviderError(error["message"], status_code=exc.response.status_code, code=error["code"]) from exc
        except httpx.TimeoutException as exc:
            raise LLMProviderError("LLM request timed out") from exc
        except httpx.RequestError as exc:
            raise LLMProviderError("LLM provider could not be reached") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError("LLM provider returned a malformed response") from exc

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
