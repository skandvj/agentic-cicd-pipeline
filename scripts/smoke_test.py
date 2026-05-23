"""Basic production smoke test: three invocations per agent."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.runtime.agent_executor import REPO_ROOT, AgentExecutor
from src.runtime.models import InvokeRequest

PROMPTS = [
    "How do I reset my password?",
    "Where can I find invoices?",
    "The workspace export is broken and urgent.",
]


async def main() -> int:
    for config_path in sorted((REPO_ROOT / "agents").glob("*/agent.yaml")):
        executor = AgentExecutor(config_path.parent.name)
        for prompt in PROMPTS:
            response = await executor.invoke(InvokeRequest(message=prompt))
            if not response.output:
                raise RuntimeError(f"empty response for {executor.agent_id}")
            print(f"{executor.agent_id}: {prompt[:30]} -> {response.trace_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
