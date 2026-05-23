from __future__ import annotations

from fastapi.testclient import TestClient

from src.runtime.server import app


def test_full_runtime_flow_with_trace_query() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/agents/customer-support-agent/invoke",
        json={"message": "Urgent outage for customer account"},
    )
    assert response.status_code == 200
    assert response.json()["tool_calls"]

    traces = client.get("/api/traces", params={"agent_id": "customer-support-agent", "limit": 5})
    assert traces.status_code == 200
    assert traces.json()

    summary = client.get("/api/metrics/summary", params={"agent_id": "customer-support-agent"})
    assert summary.status_code == 200
    assert summary.json()["invocations"] >= 1
