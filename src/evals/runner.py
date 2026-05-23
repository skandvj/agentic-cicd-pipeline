"""Eval suite loading, execution, aggregation, and baseline comparison."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from statistics import mean

from src.dashboard.metrics import record_eval_score
from src.dashboard.traces import trace_store
from src.runtime.agent_executor import REPO_ROOT, AgentExecutor
from src.runtime.models import EvalCase, EvalCaseResult, EvalResult, InvokeRequest

from .scorers import get_scorer

AGENT_ALIASES = {
    "customer-support": "customer-support-agent",
    "sales-research": "sales-research-agent",
}


class EvalRunner:
    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or REPO_ROOT

    def resolve_agent_id(self, agent_id: str) -> str:
        return AGENT_ALIASES.get(agent_id, agent_id)

    def list_suites(self, agent_id: str) -> list[str]:
        resolved = self.resolve_agent_id(agent_id)
        eval_dir = self.repo_root / "agents" / resolved / "evals"
        if not eval_dir.exists():
            return []
        return sorted(path.stem for path in eval_dir.glob("*.jsonl"))

    def load_eval_suite(self, agent_id: str, suite_name: str) -> list[EvalCase]:
        resolved = self.resolve_agent_id(agent_id)
        path = self.repo_root / "agents" / resolved / "evals" / f"{suite_name}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"eval suite not found: {path}")
        cases = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    cases.append(EvalCase.model_validate(json.loads(line)))
        return cases

    async def run_eval(self, agent_id: str, suite_name: str) -> EvalResult:
        resolved = self.resolve_agent_id(agent_id)
        if suite_name == "all":
            return await self._run_all(resolved)
        cases = self.load_eval_suite(resolved, suite_name)
        executor = AgentExecutor(agent_id=resolved, repo_root=self.repo_root)
        results: list[EvalCaseResult] = []
        for case in cases:
            response = await executor.invoke(
                InvokeRequest(message=case.input, context=case.context, session_id=f"eval-{case.id}")
            )
            scorer_name = case.scorer or self._default_scorer(suite_name)
            score = get_scorer(scorer_name).score(
                response.output,
                case.expected_output,
                keywords=case.keywords,
                latency_ms=response.latency_ms,
                max_latency_ms=case.max_latency_ms,
            )
            results.append(
                EvalCaseResult(
                    id=case.id,
                    input=case.input,
                    expected=case.expected_output,
                    actual=response.output,
                    score=score.value,
                    passed=score.passed,
                    latency_ms=response.latency_ms,
                    tokens_used=response.tokens_used,
                    cost_cents=response.cost_cents,
                    reasoning=score.reasoning,
                )
            )
        eval_result = self._aggregate(resolved, suite_name, results)
        trace_store.record_eval_run(eval_result)
        record_eval_score(resolved, suite_name, eval_result.accuracy)
        return eval_result

    async def _run_all(self, agent_id: str) -> EvalResult:
        suites = self.list_suites(agent_id)
        suite_results = [await self.run_eval(agent_id, suite) for suite in suites]
        cases = [case for suite in suite_results for case in suite.cases]
        return self._aggregate(agent_id, "all", cases)

    @staticmethod
    def _default_scorer(suite_name: str) -> str:
        if suite_name == "safety":
            return "safety"
        if suite_name == "latency":
            return "latency"
        return "llm_judge"

    def _aggregate(self, agent_id: str, suite_name: str, cases: list[EvalCaseResult]) -> EvalResult:
        latencies = sorted(case.latency_ms for case in cases)
        accuracy = mean(case.score for case in cases) if cases else 0.0
        pass_rate = mean(1.0 if case.passed else 0.0 for case in cases) if cases else 0.0
        return EvalResult(
            agent_id=agent_id,
            suite=suite_name,
            accuracy=round(accuracy, 4),
            pass_rate=round(pass_rate, 4),
            p50_latency_ms=round(_percentile(latencies, 0.50), 2),
            p95_latency_ms=round(_percentile(latencies, 0.95), 2),
            p99_latency_ms=round(_percentile(latencies, 0.99), 2),
            total_cost_cents=round(sum(case.cost_cents for case in cases), 5),
            cases=cases,
            baseline_comparison=self._baseline_comparison(agent_id, suite_name, accuracy),
        )

    @staticmethod
    def _baseline_comparison(agent_id: str, suite_name: str, accuracy: float) -> dict[str, float | str]:
        prior_runs = trace_store.query_eval_runs(agent_id=agent_id, suite=suite_name, limit=5)
        if not prior_runs:
            return {"baseline": "none", "accuracy_delta": 0.0}
        prior_accuracy = float(prior_runs[0]["metrics"].get("accuracy", 0.0))
        return {"baseline": "latest", "accuracy_delta": round(accuracy - prior_accuracy, 4)}


def _percentile(values: Iterable[float], quantile: float) -> float:
    ordered = list(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * quantile))
    return ordered[index]

