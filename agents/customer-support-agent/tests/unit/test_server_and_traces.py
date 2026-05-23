from __future__ import annotations

from fastapi.testclient import TestClient

from src.dashboard.traces import InMemoryTraceStore
from src.runtime.models import AgentResponse, InvokeRequest
from src.runtime.server import app


def test_api_lists_agents_and_invokes_agent() -> None:
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert "customer-support-agent" in health.json()["agents"]

    response = client.post(
        "/v1/agents/customer-support-agent/invoke",
        json={"message": "How do I reset my password?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_id"]
    assert payload["tool_calls"]

    config = client.get("/v1/agents/customer-support-agent/config")
    assert config.status_code == 200
    assert config.json()["provider"] == "anthropic"

    reload_response = client.post("/v1/agents/customer-support-agent/reload")
    assert reload_response.status_code == 200
    assert reload_response.json()["status"] == "reloaded"

    missing = client.get("/v1/agents/missing-agent/config")
    assert missing.status_code == 404

    bad_request = client.post(
        "/v1/agents/customer-support-agent/invoke",
        json={"message": "   "},
    )
    assert bad_request.status_code == 400


def test_api_streams_sse_response_and_exposes_metrics() -> None:
    client = TestClient(app)
    with client.stream(
        "POST",
        "/v1/agents/customer-support-agent/invoke",
        headers={"Accept": "text/event-stream"},
        json={"message": "Where can I download invoices?"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "data:" in body
    assert "metadata" in body

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "agent_invocation_total" in metrics.text


def test_trace_store_query_and_summary() -> None:
    store = InMemoryTraceStore()
    request = InvokeRequest(message="test")
    response = AgentResponse(
        output="ok",
        tool_calls=[],
        latency_ms=25.0,
        tokens_used=10,
        cost_cents=0.01,
        trace_id="trace-1",
    )
    store.record_trace("agent-a", request, response)

    assert store.query_traces(agent_id="agent-a")[0]["trace_id"] == "trace-1"
    summary = store.summary(agent_id="agent-a", period="24h")
    assert summary["invocations"] == 1
    assert summary["p95_latency_ms"] == 25.0
    assert store.summary(agent_id="agent-a", period="1d")["invocations"] == 1
