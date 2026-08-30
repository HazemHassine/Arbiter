from arbiter.telemetry import TelemetryRegistry, _percentile


def test_percentile_calculation():
    assert _percentile([], 0.5) == 0.0
    assert _percentile([10.0], 0.5) == 10.0
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    assert _percentile(values, 0.5) == 50.0
    assert _percentile(values, 0.9) == 90.0
    assert _percentile(values, 0.99) == 100.0


def test_telemetry_registry_requests_and_llm_tracking():
    reg = TelemetryRegistry(history_size=50)

    # Simulate requests
    reg.request_started()
    reg.request_finished("GET", "/api/v1/ports", status_code=200, duration_ms=12.5)
    reg.request_started()
    reg.request_finished("GET", "/api/v1/ports", status_code=500, duration_ms=150.0)

    # Record LLM call
    reg.record_llm(
        operation="query",
        model="gpt-5.4-nano",
        duration_ms=250.0,
        success=True,
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )

    snapshot = reg.snapshot()
    assert snapshot["requests"]["total"] == 2
    assert snapshot["requests"]["errors"] == 1
    assert snapshot["requests"]["statuses"]["2xx"] == 1
    assert snapshot["requests"]["statuses"]["5xx"] == 1
    assert snapshot["llm"]["calls"] == 1
    assert snapshot["llm"]["total_tokens"] == 150
    assert snapshot["llm"]["models"]["gpt-5.4-nano"] == 1
