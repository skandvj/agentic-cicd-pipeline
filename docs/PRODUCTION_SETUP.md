# Production Setup

This is the live-user path. Demo mode is intentionally deterministic; production mode uses real providers, live tool backends, PostgreSQL persistence, and a live eval judge.

## Required Services

- PostgreSQL for traces, eval runs, and baselines.
- Redis for runtime coordination and future rate limiting.
- OpenAI and Anthropic API keys for the sample agents in this repo.
- A live tool backend:
  - `http`: your API receives `POST /tools/{tool_name}`.
  - `mcp`: your MCP-compatible endpoint receives `tools/call`.
- A live eval judge using OpenAI or Anthropic.

## Environment

Create a production env file outside git:

```bash
RUNTIME_MODE=production
ENVIRONMENT=production
RUNTIME_IMAGE=ghcr.io/skandvj/agentic-cicd-pipeline/runtime:<validated-sha>

DATABASE_URL=postgresql+psycopg2://agent_user:...@db.example.com:5432/agentic_cicd
REDIS_URL=redis://redis.example.com:6379/0

OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...

TOOL_BACKEND=http
TOOL_HTTP_BASE_URL=https://tools.example.com
TOOL_TIMEOUT_SECONDS=10
TOOL_RETRIES=1

EVAL_JUDGE_PROVIDER=openai
EVAL_JUDGE_MODEL=gpt-4o-mini
```

For MCP tools, use:

```bash
TOOL_BACKEND=mcp
TOOL_MCP_ENDPOINT=https://mcp.example.com/messages
```

## Readiness Check

Run the same check used by staging and production workflows:

```bash
python scripts/check_production_config.py
```

It fails without required provider keys, database URLs, live tool backend config, or live judge config.

## Database

Initialize the production schema:

```bash
python scripts/init_db.py
```

Tables:

- `agent_traces`
- `eval_runs`

Eval baseline comparison reads the last five stored runs for each agent and suite.

## Start Runtime

```bash
docker pull "$RUNTIME_IMAGE"
docker compose up -d --no-build runtime
curl -f http://localhost:8000/health
```

Health includes the active mode and configured agents:

```json
{
  "status": "ok",
  "mode": "production",
  "environment": "production",
  "agents": ["customer-support-agent", "sales-research-agent"]
}
```

## Live Invocation

```bash
curl -X POST http://localhost:8000/v1/agents/customer-support-agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"message":"The export job failed for customer cus_123. Please escalate."}'
```

The response includes normalized provider/tool metadata:

```json
{
  "output": "...",
  "tool_calls": [
    {
      "name": "create_ticket",
      "backend": "http",
      "status": "success",
      "audit": {
        "backend": "http",
        "attempts": 1
      }
    }
  ],
  "latency_ms": 842.4,
  "tokens_used": 1180,
  "cost_cents": 1.72,
  "trace_id": "..."
}
```

## Production Eval Gates

Run live evals after deployment:

```bash
python -m src.evals.cli run-evals --agent customer-support --suite accuracy --threshold 0.95 --output accuracy.md
python -m src.evals.cli run-evals --agent customer-support --suite safety --threshold 1.0 --output safety.md
```

The production judge returns a normalized score from 0 to 1. The CLI fails when `pass_rate` falls below the threshold.

## GitHub Actions

Required GitHub environment secrets:

- `STAGING_DATABASE_URL`, `STAGING_REDIS_URL`
- `PROD_DATABASE_URL`, `PROD_REDIS_URL`
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- `TOOL_BACKEND`
- `TOOL_HTTP_BASE_URL` or `TOOL_MCP_ENDPOINT`
- `EVAL_JUDGE_PROVIDER`, `EVAL_JUDGE_MODEL`

Optional:

- `SLACK_WEBHOOK_URL`

Environment variables:

- `AUTO_PROMOTE_PROD=true` dispatches production after staging passes.
- `TOOL_TIMEOUT_SECONDS`
- `TOOL_RETRIES`

Use GitHub environment protection rules on `production` when you want manual approval before deployment.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Startup fails with `Production mode requires...` | Missing live config | Run `python scripts/check_production_config.py` and set the listed variables |
| Tool calls show `status=error` | HTTP/MCP endpoint unavailable or returned an error | Check tool backend logs, timeout, endpoint URL, and payload schema |
| Eval gate fails accuracy | Prompt/tool behavior regressed or expected answer is stale | Inspect report cases, update agent behavior or eval expectation |
| Eval gate fails safety | Agent leaked unsafe content or followed a prompt injection | Tighten guardrails and add adversarial eval coverage |
| No baseline comparison | No prior production eval run in PostgreSQL | Run the suite once after deployment to seed baselines |
| `/api/traces` empty in production | Runtime is not using `RUNTIME_MODE=production` or DB URL is wrong | Check `/health`, `DATABASE_URL`, and database connectivity |
