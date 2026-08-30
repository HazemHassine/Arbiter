import threading
import time
from collections import Counter, deque
from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


class TelemetryRegistry:
    """Small, process-local telemetry buffer with no external dependencies."""

    def __init__(self, history_size: int = 240) -> None:
        self.started_at = datetime.now(UTC)
        self._started_monotonic = time.monotonic()
        self._lock = threading.Lock()
        self._active_requests = 0
        self._request_total = 0
        self._request_errors = 0
        self._request_routes: Counter[str] = Counter()
        self._request_statuses: Counter[str] = Counter()
        self._request_history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._llm_history: deque[dict[str, Any]] = deque(maxlen=history_size)

    def request_started(self) -> None:
        with self._lock:
            self._active_requests += 1

    def request_finished(self, method: str, route: str, status_code: int, duration_ms: float) -> None:
        now = time.time()
        route_key = f"{method.upper()} {route}"
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)
            self._request_total += 1
            self._request_errors += int(status_code >= 500)
            self._request_routes[route_key] += 1
            self._request_statuses[f"{status_code // 100}xx"] += 1
            self._request_history.append(
                {
                    "timestamp": now,
                    "time": _now_iso(),
                    "route": route_key,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                }
            )

    def record_llm(
        self,
        *,
        operation: str,
        model: str,
        success: bool,
        duration_ms: float,
        usage: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        usage = usage or {}
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
        with self._lock:
            self._llm_history.append(
                {
                    "timestamp": time.time(),
                    "time": _now_iso(),
                    "operation": operation,
                    "model": model,
                    "success": success,
                    "duration_ms": round(duration_ms, 2),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "error_code": error_code,
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            requests = list(self._request_history)
            llm = list(self._llm_history)
            active = self._active_requests
            request_total = self._request_total
            request_errors = self._request_errors
            routes = self._request_routes.copy()
            statuses = self._request_statuses.copy()

        latencies = [float(item["duration_ms"]) for item in requests]
        last_minute = time.time() - 60
        recent_requests = sum(float(item["timestamp"]) >= last_minute for item in requests)
        model_counts = Counter(str(item["model"]) for item in llm)
        operation_counts = Counter(str(item["operation"]) for item in llm)
        llm_failures = sum(not bool(item["success"]) for item in llm)
        return {
            "started_at": self.started_at.isoformat(),
            "uptime_seconds": round(time.monotonic() - self._started_monotonic, 2),
            "requests": {
                "total": request_total,
                "active": active,
                "errors": request_errors,
                "error_rate": round(request_errors / request_total, 4) if request_total else 0,
                "requests_last_minute": recent_requests,
                "latency_ms": {
                    "average": round(sum(latencies) / len(latencies), 2) if latencies else 0,
                    "p50": round(_percentile(latencies, 0.5), 2),
                    "p95": round(_percentile(latencies, 0.95), 2),
                },
                "statuses": dict(statuses),
                "routes": [{"route": route, "count": count} for route, count in routes.most_common(12)],
                "samples": requests[-90:],
            },
            "llm": {
                "calls": len(llm),
                "successful": len(llm) - llm_failures,
                "failures": llm_failures,
                "input_tokens": sum(int(item["input_tokens"]) for item in llm),
                "output_tokens": sum(int(item["output_tokens"]) for item in llm),
                "total_tokens": sum(int(item["total_tokens"]) for item in llm),
                "models": dict(model_counts),
                "operations": dict(operation_counts),
                "last_call": llm[-1] if llm else None,
                "samples": llm[-60:],
            },
        }
