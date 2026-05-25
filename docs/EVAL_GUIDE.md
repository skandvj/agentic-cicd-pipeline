# Eval Guide

Eval suites live at `agents/{agent_id}/evals/{suite}.jsonl`. Each line is an eval case.

```json
{"id":"acc-001","input":"How do I reset my password?","expected_output":"reset password email link","scorer":"llm_judge"}
```

## Case Fields

| Field | Required | Notes |
|---|---:|---|
| `id` | yes | Stable case id for reports |
| `input` | yes | User message sent to the agent |
| `expected_output` | no | Reference answer or expected concepts |
| `scorer` | no | Defaults by suite name |
| `keywords` | no | Used by `contains` |
| `max_latency_ms` | no | Used by `latency` |
| `context` | no | Optional invocation context |

## Scorers

- `llm_judge`: uses a live OpenAI or Anthropic judge when `EVAL_JUDGE_PROVIDER=openai|anthropic`; uses deterministic concept coverage with citation bonus when `EVAL_JUDGE_PROVIDER=deterministic`.
- `exact`: normalized exact string comparison.
- `contains`: checks required keywords.
- `safety`: detects PII leaks, prompt-injection compliance, and secret-like output.
- `latency`: validates response time against `max_latency_ms`.

## Interpreting Results

`accuracy` is the mean score across cases. `pass_rate` is the percentage of cases where the scorer marked the result as passing. CI uses pass rate for thresholds because it is easier to reason about as a release gate.

Latency percentiles are calculated from per-case runtime latency. `total_cost_cents` is based on provider token estimates and configured model pricing.

Production runs persist eval results to PostgreSQL. Baseline comparison uses the mean accuracy of the last five persisted runs for the same agent and suite, then reports `accuracy_delta`.

## Production Judge Setup

Use a live judge for production gates:

```bash
export RUNTIME_MODE=production
export EVAL_JUDGE_PROVIDER=openai
export EVAL_JUDGE_MODEL=gpt-4o-mini
```

or:

```bash
export EVAL_JUDGE_PROVIDER=anthropic
export EVAL_JUDGE_MODEL=claude-3-haiku-20240307
```

CI/demo mode may keep `EVAL_JUDGE_PROVIDER=deterministic` so tests remain offline and repeatable. Do not use the deterministic judge as the only production release gate.

## Adding a Suite

1. Create `agents/{agent_id}/evals/{suite}.jsonl`.
2. Include diverse happy path, edge case, and adversarial prompts.
3. Run `python -m src.evals.cli run-evals --agent {agent_id} --suite {suite}`.
4. Commit the suite with the behavior change it protects.
