"""Prometheus metrics for agent runtime and eval quality gates."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

agent_invocation_total = Counter(
    "agent_invocation_total",
    "Total agent invocations by agent and status.",
    ["agent_id", "status"],
)

agent_latency_seconds = Histogram(
    "agent_latency_seconds",
    "Agent invocation latency in seconds.",
    ["agent_id"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

agent_cost_cents = Counter(
    "agent_cost_cents",
    "Cumulative model cost in cents.",
    ["agent_id", "model"],
)

agent_tokens_used = Counter(
    "agent_tokens_used",
    "Cumulative tokens used by agent.",
    ["agent_id", "direction"],
)

eval_score = Gauge(
    "eval_score",
    "Latest eval score for an agent and suite.",
    ["agent_id", "suite"],
)


def record_invocation(
    agent_id: str,
    status: str,
    latency_ms: float,
    cost_cents: float,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    agent_invocation_total.labels(agent_id=agent_id, status=status).inc()
    if latency_ms:
        agent_latency_seconds.labels(agent_id=agent_id).observe(latency_ms / 1000)
    if cost_cents:
        agent_cost_cents.labels(agent_id=agent_id, model=model).inc(cost_cents)
    if input_tokens:
        agent_tokens_used.labels(agent_id=agent_id, direction="input").inc(input_tokens)
    if output_tokens:
        agent_tokens_used.labels(agent_id=agent_id, direction="output").inc(output_tokens)


def record_eval_score(agent_id: str, suite: str, score: float) -> None:
    eval_score.labels(agent_id=agent_id, suite=suite).set(score)

