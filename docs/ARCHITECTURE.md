# Architecture

The system separates agent configuration, runtime execution, eval gates, and observability so every agent can be promoted like a microservice.

## Runtime

`src/runtime/server.py` exposes the FastAPI API. It caches `AgentExecutor` instances by agent id, hot-reloads YAML on demand, streams SSE chunks when requested, records Prometheus metrics, and stores traces.

`AgentExecutor` owns the per-agent workflow:

1. Load `agents/{agent_id}/agent.yaml`.
2. Validate against `AgentConfig`.
3. Build normalized provider messages.
4. Ask the configured provider for output and tool plans.
5. Execute tool calls through the configured backend: mock for demo/CI, HTTP for live APIs, or MCP for enterprise systems.
6. Apply guardrails.
7. Return `AgentResponse` with trace id, tool calls, latency, tokens, and cost.

Provider adapters in `src/runtime/providers.py` present a common interface for OpenAI and Anthropic. `RUNTIME_MODE=production` uses the real SDK clients and normalizes output, tool-call requests, token usage, latency, and cost. `RUNTIME_MODE=demo` keeps deterministic providers for local onboarding and CI.

## Eval Gates

`src/evals/runner.py` loads JSONL suites, invokes the runtime executor, scores each case, aggregates accuracy, pass rate, latency percentiles, and cost, then records the run for baseline comparison against the last five stored runs.

CI enforces:

- accuracy pass threshold: 95%
- safety threshold: 100%
- unit coverage threshold: 90%

## Observability

Prometheus metrics:

- `agent_invocation_total`
- `agent_latency_seconds`
- `agent_cost_cents`
- `agent_tokens_used`
- `eval_score`

Trace tables for production PostgreSQL:

- `agent_traces(id, agent_id, trace_id, input, output, tool_calls JSONB, latency_ms, tokens_in, tokens_out, cost_cents, created_at)`
- `eval_runs(id, agent_id, suite, results JSONB, metrics JSONB, baseline_comparison JSONB, created_at)`

`RUNTIME_MODE=production` uses `PostgresTraceStore`; demo and tests use `InMemoryTraceStore` so single-process development stays dependency-light.

## Deployment

Docker Compose runs runtime, PostgreSQL, Redis, Prometheus, and Grafana. Terraform provisions the equivalent AWS primitives: ECS Fargate, ECR, RDS PostgreSQL, ElastiCache Redis, ALB, CloudWatch, IAM, and security groups.
