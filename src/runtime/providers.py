"""Unified provider adapters for demo and live production runtimes."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import anthropic
from openai import AsyncOpenAI

from .models import AgentConfig, ProviderRequest, ProviderResult, ToolCall, ToolSpec
from .settings import load_settings


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

    def _deterministic_chat(self, request: ProviderRequest) -> ProviderResult:
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
    _client: Any | None = None

    async def chat(self, request: ProviderRequest) -> ProviderResult:
        if load_settings().mode == "demo":
            return self._deterministic_chat(request)

        response = await self._anthropic_client().messages.create(
            model=request.config.model,
            system=_system_message(request.messages),
            messages=[message for message in request.messages if message["role"] != "system"],
            tools=[_anthropic_tool(tool) for tool in request.tools],
            temperature=request.config.temperature,
            max_tokens=request.config.max_tokens,
        )
        output = _anthropic_text(response)
        calls = _anthropic_tool_calls(response)
        input_tokens, output_tokens = _anthropic_usage(response, request.messages, output)
        return ProviderResult(
            output=output,
            requested_tool_calls=calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=self._cost(input_tokens, output_tokens),
        )

    def _anthropic_client(self) -> Any:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=load_settings().anthropic_api_key)
        return self._client


class OpenAIProvider(BaseProvider):
    name = "openai"
    input_cost_per_1k = 0.002
    output_cost_per_1k = 0.01
    _client: Any | None = None

    async def chat(self, request: ProviderRequest) -> ProviderResult:
        if load_settings().mode == "demo":
            return self._deterministic_chat(request)

        response = await self._openai_client().chat.completions.create(
            model=request.config.model,
            messages=request.messages,
            tools=[_openai_tool(tool) for tool in request.tools],
            temperature=request.config.temperature,
            max_tokens=request.config.max_tokens,
        )
        choice = response.choices[0]
        message = choice.message
        output = str(message.content or "")
        calls = _openai_tool_calls(message)
        input_tokens, output_tokens = _openai_usage(response, request.messages, output)
        return ProviderResult(
            output=output,
            requested_tool_calls=calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=self._cost(input_tokens, output_tokens),
        )

    def _openai_client(self) -> Any:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=load_settings().openai_api_key)
        return self._client


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


def tool_input_schema(tool: ToolSpec) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in tool.parameters.items():
        schema: dict[str, Any] = {"type": parameter.type}
        if parameter.enum:
            schema["enum"] = parameter.enum
        properties[name] = schema
        if parameter.required:
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _openai_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool_input_schema(tool),
        },
    }


def _anthropic_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool_input_schema(tool),
    }


def _system_message(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(message["content"] for message in messages if message["role"] == "system")


def _openai_tool_calls(message: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for call in getattr(message, "tool_calls", None) or []:
        function = getattr(call, "function", None)
        raw_arguments = getattr(function, "arguments", "{}")
        calls.append(
            ToolCall(
                name=str(getattr(function, "name", "")),
                arguments=_parse_json_object(raw_arguments),
            )
        )
    return calls


def _anthropic_text(response: Any) -> str:
    parts = [
        str(getattr(block, "text", ""))
        for block in getattr(response, "content", [])
        if getattr(block, "type", "") == "text"
    ]
    return "\n".join(part for part in parts if part)


def _anthropic_tool_calls(response: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for block in getattr(response, "content", []):
        if getattr(block, "type", "") == "tool_use":
            raw_input = getattr(block, "input", {})
            calls.append(
                ToolCall(
                    name=str(getattr(block, "name", "")),
                    arguments=raw_input if isinstance(raw_input, dict) else {},
                )
            )
    return calls


def _openai_usage(response: Any, messages: list[dict[str, str]], output: str) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    if input_tokens == 0:
        input_tokens = sum(_estimate_tokens(item["content"]) for item in messages)
    if output_tokens == 0:
        output_tokens = _estimate_tokens(output)
    return input_tokens, output_tokens


def _anthropic_usage(response: Any, messages: list[dict[str, str]], output: str) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    if input_tokens == 0:
        input_tokens = sum(_estimate_tokens(item["content"]) for item in messages)
    if output_tokens == 0:
        output_tokens = _estimate_tokens(output)
    return input_tokens, output_tokens


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
