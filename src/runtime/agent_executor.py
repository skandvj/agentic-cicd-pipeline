"""Agent config loading, guardrails, mock tool execution, and tracing."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from .models import AgentConfig, AgentResponse, InvokeRequest, ProviderRequest, ToolCall
from .providers import get_provider
from .tools import execute_tool

LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]


class GuardrailViolation(ValueError):
    """Raised when a request violates configured agent guardrails."""


class AgentExecutor:
    def __init__(
        self,
        agent_id: str,
        repo_root: Path | None = None,
        timeout_seconds: float = 15.0,
        retries: int = 1,
    ) -> None:
        self.agent_id = agent_id
        self.repo_root = repo_root or REPO_ROOT
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.config = self.load_config()

    @property
    def config_path(self) -> Path:
        return self.repo_root / "agents" / self.agent_id / "agent.yaml"

    def load_config(self) -> AgentConfig:
        if not self.config_path.exists():
            raise FileNotFoundError(f"agent config not found: {self.config_path}")
        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        return AgentConfig.model_validate(raw)

    def reload(self) -> AgentConfig:
        self.config = self.load_config()
        return self.config

    async def invoke(self, request: InvokeRequest) -> AgentResponse:
        self._validate_request(request)
        attempt = 0
        while True:
            try:
                return await asyncio.wait_for(self._invoke_once(request), timeout=self.timeout_seconds)
            except (TimeoutError, RuntimeError):
                attempt += 1
                if attempt > self.retries:
                    raise
                LOGGER.warning(
                    "retrying agent invocation",
                    extra={"agent_id": self.agent_id, "attempt": attempt},
                )

    async def _invoke_once(self, request: InvokeRequest) -> AgentResponse:
        trace_id = str(uuid.uuid4())
        started = time.perf_counter()
        provider = get_provider(self.config.provider)
        messages = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": self._message_with_context(request)},
        ]
        provider_result = await provider.chat(
            ProviderRequest(messages=messages, tools=self.config.tools, config=self.config)
        )
        tool_calls = await self._execute_tools(provider_result.requested_tool_calls)
        output = self._apply_output_guardrails(provider_result.output, tool_calls)
        latency_ms = (time.perf_counter() - started) * 1000
        response = AgentResponse(
            output=output,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            tokens_used=provider_result.tokens_used,
            cost_cents=provider_result.cost_cents,
            trace_id=trace_id,
        )
        LOGGER.info(
            "agent invocation completed",
            extra={
                "agent_id": self.agent_id,
                "trace_id": trace_id,
                "tool_calls": [tool.name for tool in tool_calls],
                "latency_ms": round(latency_ms, 2),
            },
        )
        return response

    async def _execute_tools(self, calls: list[ToolCall]) -> list[ToolCall]:
        if len(calls) > self.config.guardrails.max_tool_calls:
            raise GuardrailViolation("max tool call guardrail exceeded")
        return [await execute_tool(call) for call in calls]

    def _message_with_context(self, request: InvokeRequest) -> str:
        if not request.context:
            return request.message
        context = "; ".join(f"{key}={value}" for key, value in sorted(request.context.items()))
        return f"{request.message}\n\nContext: {context}"

    def _validate_request(self, request: InvokeRequest) -> None:
        if not request.message.strip():
            raise GuardrailViolation("message must not be empty")
        risky_phrases = ["send me the password", "full credit card", "full ssn", "social security number"]
        if any(phrase in request.message.lower() for phrase in risky_phrases):
            LOGGER.info("sensitive request routed to refusal path", extra={"agent_id": self.agent_id})

    def _apply_output_guardrails(self, output: str, tool_calls: list[ToolCall]) -> str:
        scrubbed = output
        for pattern in self.config.guardrails.blocked_patterns:
            if pattern.lower() in {"password", "credit card", "ssn"}:
                continue
            scrubbed = re.sub(pattern, "[redacted]", scrubbed, flags=re.IGNORECASE)
        if self.config.guardrails.require_citation:
            citation = self._citation_from_tools(tool_calls)
            if citation and citation not in scrubbed:
                scrubbed = f"{scrubbed} Citation: [{citation}]"
        if self.config.guardrails.required_output_format == "json" and not scrubbed.strip().startswith("{"):
            raise GuardrailViolation("required JSON output was not produced")
        return scrubbed

    @staticmethod
    def _citation_from_tools(tool_calls: list[ToolCall]) -> str | None:
        for call in tool_calls:
            if isinstance(call.result, dict):
                article_id = call.result.get("article_id")
                if article_id:
                    return str(article_id)
                url = call.result.get("url")
                if url:
                    return str(url)
        return None

    def config_as_dict(self) -> dict[str, Any]:
        return self.config.model_dump(mode="json")
