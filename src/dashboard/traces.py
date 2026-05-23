"""Trace storage and observability query endpoints."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query

from src.runtime.models import AgentResponse, EvalResult, InvokeRequest

router = APIRouter(prefix="/api", tags=["observability"])


class InMemoryTraceStore:
    """Lightweight store used locally and in tests.

    Production deployments can wire these records to PostgreSQL using the schema
    documented in `docs/ARCHITECTURE.md`.
    """

    def __init__(self) -> None:
        self.traces: list[dict[str, Any]] = []
        self.eval_runs: list[dict[str, Any]] = []

    def record_trace(self, agent_id: str, request: InvokeRequest, response: AgentResponse) -> None:
        tokens_out = max(0, response.tokens_used // 2)
        tokens_in = response.tokens_used - tokens_out
        self.traces.append(
            {
                "id": len(self.traces) + 1,
                "agent_id": agent_id,
                "trace_id": response.trace_id,
                "input": request.message,
                "output": response.output,
                "tool_calls": [tool.model_dump(mode="json") for tool in response.tool_calls],
                "latency_ms": response.latency_ms,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_cents": response.cost_cents,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

    def record_eval_run(self, result: EvalResult) -> None:
        self.eval_runs.append(
            {
                "id": len(self.eval_runs) + 1,
                "agent_id": result.agent_id,
                "suite": result.suite,
                "results": [case.model_dump(mode="json") for case in result.cases],
                "metrics": result.model_dump(
                    mode="json",
                    exclude={"cases", "baseline_comparison", "agent_id", "suite"},
                ),
                "baseline_comparison": result.baseline_comparison,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

    def query_traces(self, agent_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        rows = [row for row in self.traces if agent_id is None or row["agent_id"] == agent_id]
        return list(reversed(rows[-limit:]))

    def query_eval_runs(
        self,
        agent_id: str | None = None,
        suite: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.eval_runs
            if (agent_id is None or row["agent_id"] == agent_id)
            and (suite is None or row["suite"] == suite)
        ]
        return list(reversed(rows[-limit:]))

    def summary(self, agent_id: str | None = None, period: str = "24h") -> dict[str, Any]:
        cutoff = datetime.now(UTC) - _parse_period(period)
        rows = []
        for row in self.traces:
            created_at = datetime.fromisoformat(row["created_at"])
            if created_at >= cutoff and (agent_id is None or row["agent_id"] == agent_id):
                rows.append(row)
        by_agent: dict[str, int] = defaultdict(int)
        for row in rows:
            by_agent[row["agent_id"]] += 1
        latency_values = sorted(float(row["latency_ms"]) for row in rows)
        return {
            "period": period,
            "agent_id": agent_id,
            "invocations": len(rows),
            "by_agent": dict(by_agent),
            "total_cost_cents": round(sum(float(row["cost_cents"]) for row in rows), 5),
            "p95_latency_ms": _percentile(latency_values, 0.95),
        }


def _parse_period(period: str) -> timedelta:
    if period.endswith("h"):
        return timedelta(hours=int(period[:-1]))
    if period.endswith("d"):
        return timedelta(days=int(period[:-1]))
    return timedelta(hours=24)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, round((len(values) - 1) * quantile))
    return values[index]


trace_store = InMemoryTraceStore()


@router.get("/traces")
async def get_traces(
    agent_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return trace_store.query_traces(agent_id=agent_id, limit=limit)


@router.get("/eval-runs")
async def get_eval_runs(
    agent_id: str | None = None,
    suite: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
) -> list[dict[str, Any]]:
    return trace_store.query_eval_runs(agent_id=agent_id, suite=suite, limit=limit)


@router.get("/metrics/summary")
async def get_metrics_summary(agent_id: str | None = None, period: str = "24h") -> dict[str, Any]:
    return trace_store.summary(agent_id=agent_id, period=period)
