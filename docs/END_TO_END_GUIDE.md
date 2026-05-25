# End-to-End Guide

This guide walks through the full demo lifecycle: install, run the runtime, invoke an agent, run evals, inspect scoring, check observability, and understand how CI blocks unsafe changes. For live users and real provider/tool connections, use [PRODUCTION_SETUP.md](PRODUCTION_SETUP.md).

## 1. Clone and Install

```bash
git clone https://github.com/skandvj/agentic-cicd-pipeline.git
cd agentic-cicd-pipeline

python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Validate that the agent YAML files match the runtime schema:

```bash
python scripts/validate_agents.py
```

Expected result:

```text
valid .../agents/customer-support-agent/agent.yaml
valid .../agents/sales-research-agent/agent.yaml
```

## 2. Run the Runtime Locally

Start the FastAPI runtime:

```bash
uvicorn src.runtime.server:app --host 0.0.0.0 --port 8000
```

In another terminal, check health:

```bash
curl -f http://localhost:8000/health
```

Expected shape:

```json
{
  "status": "ok",
  "mode": "demo",
  "agents": ["customer-support-agent", "sales-research-agent"]
}
```

## 3. Invoke an Agent

Invoke the customer support agent:

```bash
curl -X POST http://localhost:8000/v1/agents/customer-support-agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"message":"How do I reset my password?"}'
```

The response is a structured `AgentResponse`:

```json
{
  "output": "To reset your password...",
  "tool_calls": [
    {
      "name": "search_knowledge_base",
      "arguments": { "query": "How do I reset my password?" },
      "result": { "article_id": "KB-RESET-001" },
      "latency_ms": 0.03
    }
  ],
  "latency_ms": 1.2,
  "tokens_used": 66,
  "cost_cents": 0.051,
  "trace_id": "..."
}
```

What happened internally:

1. The runtime loaded `agents/customer-support-agent/agent.yaml`.
2. It selected the configured provider adapter.
3. In demo mode, the deterministic provider planned a tool call.
4. The mock knowledge-base tool returned support article data.
5. Guardrails added a citation because `require_citation` is enabled.
6. Runtime metrics and trace data were recorded.

## 4. Run Eval Suites

Run the accuracy suite:

```bash
python -m src.evals.cli run-evals --agent customer-support --suite accuracy --threshold 0.95
```

Run the safety suite:

```bash
python -m src.evals.cli run-evals --agent customer-support --suite safety --threshold 1.0
```

Run every suite for an agent:

```bash
python -m src.evals.cli run-evals --agent customer-support --suite all --output report.md
```

List available suites:

```bash
python -m src.evals.cli list-suites --agent customer-support
```

## 5. Understand the Scoring Mechanism

Eval cases are JSONL records under `agents/{agent_id}/evals`.

Example:

```json
{"id":"acc-001","input":"How do I reset my password?","expected_output":"reset password sign-in forgot password email reset link","scorer":"llm_judge"}
```

The scoring implementations live in `src/evals/scorers.py`. Demo mode uses deterministic scoring for repeatable local runs. Production mode should set `EVAL_JUDGE_PROVIDER=openai|anthropic` and `EVAL_JUDGE_MODEL` so the `llm_judge` scorer calls a real judge model.

| Scorer | What it checks | Pass condition |
|---|---|---|
| `ExactMatchScorer` | Normalized exact string match | Actual text equals expected text after normalization |
| `ContainsScorer` | Required keyword coverage | At least 80% of required terms are present |
| `LLMJudgeScorer` | Live LLM judge in production; expected concept coverage in demo | At least 70% normalized score |
| `SafetyScorer` | PII leaks, secret-like output, prompt-injection compliance | No violation patterns are detected |
| `LatencyScorer` | Runtime latency | `latency_ms <= max_latency_ms` |

The runner aggregates scores in `src/evals/runner.py`.

| Metric | Meaning |
|---|---|
| `accuracy` | Mean score across all eval cases |
| `pass_rate` | Percentage of cases marked passing |
| `p50_latency_ms` | Median latency |
| `p95_latency_ms` | 95th percentile latency |
| `p99_latency_ms` | 99th percentile latency |
| `total_cost_cents` | Sum of estimated provider costs for the suite |
| `baseline_comparison` | Delta versus the last five persisted runs, when available |

CI uses thresholds as release gates:

```text
accuracy >= 95%
safety pass_rate == 100%
unit test coverage >= 90%
```

## 6. Run the Full Docker Stack

Create a local environment file:

```bash
cp .env.example .env
```

Start runtime, PostgreSQL, Redis, Prometheus, and Grafana:

```bash
docker compose up -d
```

Verify the runtime:

```bash
curl -f http://localhost:8000/health
```

Invoke the agent through the containerized runtime:

```bash
curl -X POST http://localhost:8000/v1/agents/customer-support-agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"message":"Where can I download invoices?"}'
```

Check Prometheus:

```bash
curl 'http://localhost:9090/api/v1/query?query=agent_invocation_total'
```

Open Grafana:

```text
http://localhost:3000
```

The included dashboard tracks request volume, latency, cost, eval scores, and error rate.

Stop the stack:

```bash
docker compose down
```

## 7. Understand the CI/CD Flow

The PR workflow is `.github/workflows/pr-review.yml`.

It runs:

1. Agent YAML schema validation.
2. Ruff linting.
3. Mypy type checking.
4. Unit tests with 90% coverage.
5. Runtime startup.
6. Changed-agent eval suites.
7. PR scorecard comment.
8. Commit status for the eval gate.

The deploy workflows are:

- `.github/workflows/deploy-staging.yml`: builds the Docker image, runs staging evals, and prepares promotion.
- `.github/workflows/deploy-prod.yml`: runs smoke tests, records baseline metrics, and tags a release.

## 8. Make a Safe Agent Change

To add or modify an agent:

1. Edit `agents/{agent_id}/agent.yaml`.
2. Add or update eval cases in `agents/{agent_id}/evals`.
3. Run validation:

```bash
python scripts/validate_agents.py
```

4. Run tests:

```bash
pytest agents/*/tests/unit/ -v --cov=src --cov-report=term-missing --cov-fail-under=90
```

5. Run eval gates:

```bash
python -m src.evals.cli run-evals --agent customer-support --suite accuracy --threshold 0.95
python -m src.evals.cli run-evals --agent customer-support --suite safety --threshold 1.0
```

If any gate fails, fix the prompt, tool behavior, guardrail, or eval expectation before merging.

## 9. What to Show in a Demo

A strong demo path:

1. Show `agents/customer-support-agent/agent.yaml`.
2. Invoke `/v1/agents/customer-support-agent/invoke`.
3. Point out the structured response: output, tool calls, latency, tokens, cost, trace id.
4. Run the accuracy eval suite.
5. Open `src/evals/scorers.py` and explain how scoring works.
6. Show the GitHub Actions workflow gate.
7. Start Docker Compose and show Prometheus/Grafana observability.

The main story: this project turns AI-agent changes into a tested, observable, deployable software lifecycle.
