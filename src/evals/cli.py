"""Command line interface for local and CI eval gates."""

from __future__ import annotations

import asyncio

import click

from .reporter import EvalReporter
from .runner import EvalRunner


@click.group()
def cli() -> None:
    """Run and inspect agent eval suites."""


@cli.command("run-evals")
@click.option("--agent", required=True, help="Agent id or alias.")
@click.option("--suite", required=True, help="Suite name or all.")
@click.option("--baseline", default=None, help="Baseline selector, e.g. latest.")
@click.option("--threshold", default=None, type=float, help="Minimum pass-rate threshold.")
@click.option("--output", default=None, help="Write report to .md or .json.")
def run_evals(
    agent: str,
    suite: str,
    baseline: str | None,
    threshold: float | None,
    output: str | None,
) -> None:
    del baseline
    result = asyncio.run(EvalRunner().run_eval(agent, suite))
    EvalReporter().write(result, output)
    if threshold is not None and result.pass_rate < threshold:
        raise click.ClickException(
            f"eval threshold failed: pass_rate={result.pass_rate:.2%}, threshold={threshold:.2%}"
        )


@cli.command("list-suites")
@click.option("--agent", required=True)
def list_suites(agent: str) -> None:
    for suite in EvalRunner().list_suites(agent):
        click.echo(suite)


@cli.command("show-baseline")
@click.option("--agent", required=True)
@click.option("--suite", required=True)
def show_baseline(agent: str, suite: str) -> None:
    runner = EvalRunner()
    resolved = runner.resolve_agent_id(agent)
    result = runner._baseline_comparison(resolved, suite, 0.0)
    click.echo(result)


if __name__ == "__main__":
    cli()
