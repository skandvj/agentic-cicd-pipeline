"""Trace storage and observability query endpoints."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    desc,
    insert,
    select,
)

from src.runtime.models import AgentResponse, EvalResult, InvokeRequest
from src.runtime.settings import load_settings

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


class PostgresTraceStore:
    """SQLAlchemy-backed trace store used in production mode."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, future=True)
        self.metadata = MetaData()
        self.agent_traces = Table(
            "agent_traces",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("agent_id", String, index=True, nullable=False),
            Column("trace_id", String, unique=True, index=True, nullable=False),
            Column("input", String, nullable=False),
            Column("output", String, nullable=False),
            Column("tool_calls", JSON, nullable=False),
            Column("latency_ms", Float, nullable=False),
            Column("tokens_in", Integer, nullable=False),
            Column("tokens_out", Integer, nullable=False),
            Column("cost_cents", Float, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.eval_runs = Table(
            "eval_runs",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("agent_id", String, index=True, nullable=False),
            Column("suite", String, index=True, nullable=False),
            Column("results", JSON, nullable=False),
            Column("metrics", JSON, nullable=False),
            Column("baseline_comparison", JSON, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(self.engine)

    def record_trace(self, agent_id: str, request: InvokeRequest, response: AgentResponse) -> None:
        tokens_out = max(0, response.tokens_used // 2)
        tokens_in = response.tokens_used - tokens_out
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.agent_traces).values(
                    agent_id=agent_id,
                    trace_id=response.trace_id,
                    input=request.message,
                    output=response.output,
                    tool_calls=[tool.model_dump(mode="json") for tool in response.tool_calls],
                    latency_ms=response.latency_ms,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_cents=response.cost_cents,
                    created_at=datetime.now(UTC),
                )
            )

    def record_eval_run(self, result: EvalResult) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.eval_runs).values(
                    agent_id=result.agent_id,
                    suite=result.suite,
                    results=[case.model_dump(mode="json") for case in result.cases],
                    metrics=result.model_dump(
                        mode="json",
                        exclude={"cases", "baseline_comparison", "agent_id", "suite"},
                    ),
                    baseline_comparison=result.baseline_comparison,
                    created_at=datetime.now(UTC),
                )
            )

    def query_traces(self, agent_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        statement = select(self.agent_traces).order_by(desc(self.agent_traces.c.created_at)).limit(limit)
        if agent_id is not None:
            statement = statement.where(self.agent_traces.c.agent_id == agent_id)
        with self.engine.begin() as connection:
            return [_row_to_dict(row) for row in connection.execute(statement).mappings()]

    def query_eval_runs(
        self,
        agent_id: str | None = None,
        suite: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        statement = select(self.eval_runs).order_by(desc(self.eval_runs.c.created_at)).limit(limit)
        if agent_id is not None:
            statement = statement.where(self.eval_runs.c.agent_id == agent_id)
        if suite is not None:
            statement = statement.where(self.eval_runs.c.suite == suite)
        with self.engine.begin() as connection:
            return [_row_to_dict(row) for row in connection.execute(statement).mappings()]

    def summary(self, agent_id: str | None = None, period: str = "24h") -> dict[str, Any]:
        cutoff = datetime.now(UTC) - _parse_period(period)
        statement = select(self.agent_traces).where(self.agent_traces.c.created_at >= cutoff)
        if agent_id is not None:
            statement = statement.where(self.agent_traces.c.agent_id == agent_id)
        with self.engine.begin() as connection:
            rows = [_row_to_dict(row) for row in connection.execute(statement).mappings()]
        by_agent: dict[str, int] = defaultdict(int)
        for row in rows:
            by_agent[str(row["agent_id"])] += 1
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


def build_trace_store() -> InMemoryTraceStore | PostgresTraceStore:
    settings = load_settings()
    if settings.is_production and settings.database_url:
        return PostgresTraceStore(settings.database_url)
    return InMemoryTraceStore()


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    created_at = data.get("created_at")
    if isinstance(created_at, datetime):
        data["created_at"] = created_at.isoformat()
    return data


trace_store = build_trace_store()


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
