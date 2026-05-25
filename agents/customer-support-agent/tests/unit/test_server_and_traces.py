from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.check_production_config import main as check_production_config
from src.dashboard.traces import InMemoryTraceStore, PostgresTraceStore
from src.runtime.models import AgentResponse, InvokeRequest
from src.runtime.server import app
from src.runtime.settings import ProductionConfigurationError, RuntimeSettings, validate_production_settings


def test_api_lists_agents_and_invokes_agent() -> None:
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "demo"
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


def test_sql_trace_store_persists_traces_and_eval_runs() -> None:
    store = PostgresTraceStore("sqlite+pysqlite:///:memory:")
    request = InvokeRequest(message="persist me")
    response = AgentResponse(
        output="ok",
        tool_calls=[],
        latency_ms=15.0,
        tokens_used=12,
        cost_cents=0.02,
        trace_id="trace-sql-1",
    )
    store.record_trace("agent-sql", request, response)

    traces = store.query_traces(agent_id="agent-sql")
    assert traces[0]["trace_id"] == "trace-sql-1"
    assert store.summary(agent_id="agent-sql")["invocations"] == 1


def test_production_settings_fail_fast_without_live_config() -> None:
    settings = RuntimeSettings(mode="production")

    with pytest.raises(ProductionConfigurationError) as error:
        validate_production_settings(Path.cwd(), settings)

    assert "DATABASE_URL" in str(error.value)


def test_production_config_script_reports_missing_env(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RUNTIME_MODE", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    assert check_production_config(Path.cwd()) == 1
    assert "Production configuration check failed" in capsys.readouterr().err


def test_production_config_script_accepts_live_settings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RUNTIME_MODE", "production")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://agent:pass@db:5432/agentic_cicd")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("TOOL_BACKEND", "http")
    monkeypatch.setenv("TOOL_HTTP_BASE_URL", "https://tools.example.test")
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "gpt-4o-mini")

    assert check_production_config(Path.cwd()) == 0
    assert "environment=staging" in capsys.readouterr().out
