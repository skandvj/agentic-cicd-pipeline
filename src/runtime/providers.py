"""Unified provider adapters.

The adapters expose OpenAI- and Anthropic-shaped providers while using a
deterministic local implementation by default. That keeps CI, eval gates, and
developer onboarding independent from live LLM credentials.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from .models import AgentConfig, ProviderRequest, ProviderResult, ToolCall, ToolSpec


def _estimate_tokens(text: str) -> int:
    return max(1, len(re.findall(r"\w+|[^\w\s]", text)))


def _tool_names(tools: list[ToolSpec]) -> set[str]:
    return {tool.name for tool in tools}


class BaseProvider(ABC):
    name: str
    input_cost_per_1k: float
    output_cost_per_1k: float

    @abstractmethod
    async def chat(self, request: ProviderRequest) -> ProviderResult:
        """Return a provider result in the runtime's normalized format."""

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        dollars = (
            input_tokens / 1000 * self.input_cost_per_1k
            + output_tokens / 1000 * self.output_cost_per_1k
        )
        return round(dollars * 100, 5)


class DeterministicAgentBrain:
    """Small intent model used by both provider adapters for offline tests."""

    @staticmethod
    def plan(config: AgentConfig, message: str, tools: list[ToolSpec]) -> tuple[str, list[ToolCall]]:
        lower = message.lower()
        names = _tool_names(tools)
        calls: list[ToolCall] = []

        if config.provider == "anthropic":
            if "search_knowledge_base" in names and any(
                word in lower for word in ["reset", "password", "billing", "invoice", "login"]
            ):
                calls.append(ToolCall(name="search_knowledge_base", arguments={"query": message}))
            if "lookup_customer" in names and "customer" in lower:
                calls.append(ToolCall(name="lookup_customer", arguments={"customer_id": "cus_mock_123"}))
            if "create_ticket" in names and any(
                word in lower for word in ["broken", "outage", "cannot", "can't", "escalate", "urgent"]
            ):
                calls.append(
                    ToolCall(
                        name="create_ticket",
                        arguments={
                            "subject": "Customer support escalation",
                            "description": message,
                            "priority": "high" if "urgent" in lower else "medium",
                        },
                    )
                )
            output = DeterministicAgentBrain._support_answer(lower)
        else:
            if "web_search" in names and any(
                word in lower for word in ["research", "news", "competitor", "funding", "market"]
            ):
                calls.append(ToolCall(name="web_search", arguments={"query": message}))
            if "crm_lookup" in names and any(word in lower for word in ["account", "deal", "crm"]):
                calls.append(ToolCall(name="crm_lookup", arguments={"account": "Acme Corp"}))
            if "company_research" in names:
                calls.append(ToolCall(name="company_research", arguments={"company": "Acme Corp"}))
            output = DeterministicAgentBrain._sales_answer(lower)

        return output, calls[: config.guardrails.max_tool_calls]

    @staticmethod
    def _support_answer(lower: str) -> str:
        if any(marker in lower for marker in ["ignore previous", "developer mode", "system prompt"]):
            return (
                "I cannot override instructions or reveal internal policy. "
                "I can help with the product issue instead."
            )
        if any(marker in lower for marker in ["credit card", "ssn", "social security"]):
            return (
                "I cannot collect or disclose sensitive personal data. "
                "I can escalate this securely to a human agent."
            )
        if "password" in lower or "reset" in lower:
            return (
                "To reset your password, open the sign-in page, choose Forgot password, "
                "and use the reset link sent to your email."
            )
        if "billing" in lower or "invoice" in lower:
            return "Workspace admins can view invoices from Settings > Billing and download receipts there."
        if any(word in lower for word in ["outage", "broken", "cannot", "can't", "urgent"]):
            return (
                "I found signs this may need escalation, so I created a support ticket "
                "and noted the urgency."
            )
        return (
            "I can help troubleshoot this. "
            "Please share the workspace area affected and any error text you see."
        )

    @staticmethod
    def _sales_answer(lower: str) -> str:
        if any(marker in lower for marker in ["ignore previous", "system prompt"]):
            return (
                "I cannot bypass operating instructions, "
                "but I can continue with compliant account research."
            )
        if "competitor" in lower:
            return (
                "The strongest sales angle is to compare implementation speed, security posture, "
                "and support coverage against the named competitor."
            )
        if "funding" in lower or "news" in lower:
            return "Recent market signals suggest budget expansion and an active buying window."
        return (
            "I prepared a concise account brief with company signals, "
            "CRM context, and recommended next steps."
        )


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    input_cost_per_1k = 0.003
    output_cost_per_1k = 0.015

    async def chat(self, request: ProviderRequest) -> ProviderResult:
        message = request.messages[-1]["content"]
        output, calls = DeterministicAgentBrain.plan(request.config, message, request.tools)
        input_tokens = sum(_estimate_tokens(item["content"]) for item in request.messages)
        output_tokens = _estimate_tokens(output)
        return ProviderResult(
            output=output,
            requested_tool_calls=calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=self._cost(input_tokens, output_tokens),
        )


class OpenAIProvider(BaseProvider):
    name = "openai"
    input_cost_per_1k = 0.002
    output_cost_per_1k = 0.01

    async def chat(self, request: ProviderRequest) -> ProviderResult:
        message = request.messages[-1]["content"]
        output, calls = DeterministicAgentBrain.plan(request.config, message, request.tools)
        input_tokens = sum(_estimate_tokens(item["content"]) for item in request.messages)
        output_tokens = _estimate_tokens(output)
        return ProviderResult(
            output=output,
            requested_tool_calls=calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=self._cost(input_tokens, output_tokens),
        )


PROVIDERS: dict[str, BaseProvider] = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
}


def get_provider(name: str) -> BaseProvider:
    try:
        return PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported provider '{name}'") from exc


def serialize_tool_for_provider(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": {
            name: parameter.model_dump(exclude_none=True)
            for name, parameter in tool.parameters.items()
        },
    }
