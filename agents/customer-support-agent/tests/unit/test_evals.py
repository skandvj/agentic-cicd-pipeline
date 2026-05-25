from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.dashboard.metrics import record_eval_score, record_invocation
from src.evals.reporter import EvalReporter
from src.evals.runner import EvalRunner, _percentile
from src.evals.scorers import (
    ContainsScorer,
    ExactMatchScorer,
    LatencyScorer,
    LLMJudgeScorer,
    SafetyScorer,
)


def test_scorers_cover_quality_safety_and_latency() -> None:
    assert ExactMatchScorer().score("Hello, world!", "hello world").passed
    assert ContainsScorer().score("Reset by email link", keywords=["reset", "email"]).passed
    assert LLMJudgeScorer().score("Use forgot password email link.", "forgot password email link").passed
    assert SafetyScorer().score("I cannot reveal hidden instructions.").passed
    assert not SafetyScorer().score("system prompt is public").passed
    assert LatencyScorer().score("", latency_ms=50, max_latency_ms=100).passed
    assert not LatencyScorer().score("", latency_ms=200, max_latency_ms=100).passed


def test_live_llm_judge_normalizes_openai_score(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCompletions:
        def create(self, **_: object) -> object:
            message = type("Message", (), {"content": '{"score": 4, "reasoning": "solid answer"}'})
            choice = type("Choice", (), {"message": message})
            return type("Response", (), {"choices": [choice]})

    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    scorer = LLMJudgeScorer()
    monkeypatch.setattr(
        scorer,
        "_openai_client",
        type("Client", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})()})(),
    )

    score = scorer.score("actual", "expected")

    assert score.passed
    assert score.value == 0.8
    assert score.reasoning == "solid answer"


def test_live_llm_judge_handles_anthropic_and_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMessages:
        def create(self, **_: object) -> object:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"score": 5, "reasoning": "excellent"}')]
            )

    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "anthropic")
    scorer = LLMJudgeScorer()
    monkeypatch.setattr(scorer, "_anthropic_client", SimpleNamespace(messages=FakeMessages()))

    score = scorer.score("actual", "expected")
    assert score.value == 1.0
    assert score.reasoning == "excellent"

    class InvalidCompletions:
        def create(self, **_: object) -> object:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))]
            )

    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    scorer = LLMJudgeScorer()
    monkeypatch.setattr(
        scorer,
        "_openai_client",
        SimpleNamespace(chat=SimpleNamespace(completions=InvalidCompletions())),
    )
    invalid = scorer.score("actual", "expected")
    assert not invalid.passed
    assert invalid.reasoning == "judge returned invalid JSON"


def test_suite_loading_and_alias_resolution() -> None:
    runner = EvalRunner()
    assert runner.resolve_agent_id("customer-support") == "customer-support-agent"
    assert set(runner.list_suites("customer-support")) >= {"accuracy", "latency", "safety"}
    assert len(runner.load_eval_suite("customer-support", "accuracy")) == 20


def test_baseline_comparison_uses_last_five_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_runs(**_: object) -> list[dict[str, object]]:
        return [{"metrics": {"accuracy": 0.9}}, {"metrics": {"accuracy": 0.8}}]

    monkeypatch.setattr("src.evals.runner.trace_store.query_eval_runs", fake_runs)

    comparison = EvalRunner()._baseline_comparison("agent", "accuracy", 1.0)

    assert comparison["baseline"] == "last_5"
    assert comparison["baseline_accuracy"] == 0.85
    assert comparison["accuracy_delta"] == 0.15
    assert _percentile([], 0.95) == 0.0


@pytest.mark.asyncio
async def test_eval_runner_aggregates_latency_suite() -> None:
    result = await EvalRunner().run_eval("customer-support", "latency")

    assert result.agent_id == "customer-support-agent"
    assert result.suite == "latency"
    assert result.pass_rate == 1.0
    assert result.p95_latency_ms < 1000
    assert result.total_cost_cents > 0


@pytest.mark.asyncio
async def test_reporter_outputs_markdown_and_json() -> None:
    result = await EvalRunner().run_eval("customer-support", "safety")
    reporter = EvalReporter()
    markdown = reporter.to_markdown(result)
    json_report = reporter.to_json(result)

    assert "# Eval Report" in markdown
    assert "safe-001" in markdown
    assert '"suite": "safety"' in json_report


@pytest.mark.asyncio
async def test_all_suite_baseline_and_report_file_outputs(tmp_path) -> None:
    result = await EvalRunner().run_eval("customer-support", "all")
    reporter = EvalReporter()
    markdown_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"

    reporter.write(result, str(markdown_path))
    reporter.write(result, str(json_path))
    reporter.write(result, None)

    assert result.suite == "all"
    assert len(result.cases) == 45
    assert "Eval Report" in markdown_path.read_text(encoding="utf-8")
    assert '"suite": "all"' in json_path.read_text(encoding="utf-8")


def test_missing_suite_and_metric_helpers() -> None:
    runner = EvalRunner()
    with pytest.raises(FileNotFoundError):
        runner.load_eval_suite("customer-support", "missing")

    record_invocation(
        "customer-support-agent",
        "ok",
        latency_ms=12,
        cost_cents=0.03,
        model="claude-sonnet-4-6",
        input_tokens=4,
        output_tokens=6,
    )
    record_eval_score("customer-support-agent", "accuracy", 0.99)
