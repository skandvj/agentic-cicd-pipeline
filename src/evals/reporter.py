"""Eval report renderers."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.runtime.models import EvalResult


class EvalReporter:
    def to_json(self, result: EvalResult) -> str:
        return result.model_dump_json(indent=2)

    def to_markdown(self, result: EvalResult) -> str:
        rows = [
            "| Case | Score | Passed | Latency | Notes |",
            "|---|---:|:---:|---:|---|",
        ]
        for case in result.cases:
            rows.append(
                f"| `{case.id}` | {case.score:.2f} | {'yes' if case.passed else 'no'} | "
                f"{case.latency_ms:.1f}ms | {case.reasoning} |"
            )
        return "\n".join(
            [
                f"# Eval Report: {result.agent_id}/{result.suite}",
                "",
                f"- Accuracy: {result.accuracy:.2%}",
                f"- Pass rate: {result.pass_rate:.2%}",
                f"- p95 latency: {result.p95_latency_ms:.1f}ms",
                f"- Total cost: {result.total_cost_cents:.5f} cents",
                f"- Baseline: `{json.dumps(result.baseline_comparison)}`",
                "",
                *rows,
                "",
            ]
        )

    def write(self, result: EvalResult, output: str | None) -> None:
        if not output:
            self.print_console(result)
            return
        path = Path(output)
        content = self.to_json(result) if path.suffix == ".json" else self.to_markdown(result)
        path.write_text(content, encoding="utf-8")

    def print_console(self, result: EvalResult) -> None:
        console = Console()
        table = Table(title=f"Eval {result.agent_id}/{result.suite}")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Accuracy", f"{result.accuracy:.2%}")
        table.add_row("Pass rate", f"{result.pass_rate:.2%}")
        table.add_row("p95 latency", f"{result.p95_latency_ms:.1f}ms")
        table.add_row("Total cost", f"{result.total_cost_cents:.5f} cents")
        console.print(table)

