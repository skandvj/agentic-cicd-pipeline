from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime.agent_executor import AgentExecutor, GuardrailViolation
from src.runtime.models import Guardrails, InvokeRequest, ProviderRequest, ToolCall
from src.runtime.providers import get_provider, serialize_tool_for_provider, tool_input_schema
from src.runtime.tools import execute_tool


@pytest.mark.asyncio
async def test_support_agent_invokes_knowledge_base_with_citation() -> None:
    executor = AgentExecutor("customer-support-agent")
    response = await executor.invoke(InvokeRequest(message="How do I reset my password?"))

    assert "reset your password" in response.output.lower()
    assert "KB-RESET-001" in response.output
    assert response.tool_calls[0].name == "search_knowledge_base"
    assert response.tokens_used > 0
    assert response.cost_cents > 0


@pytest.mark.asyncio
async def test_support_agent_escalates_broken_urgent_issue() -> None:
    executor = AgentExecutor("customer-support-agent")
    response = await executor.invoke(
        InvokeRequest(message="Urgent: the export workflow is broken for our customer")
    )

    names = {call.name for call in response.tool_calls}
    assert "lookup_customer" in names
    assert "create_ticket" in names
    assert "support ticket" in response.output.lower()


@pytest.mark.asyncio
async def test_sales_agent_uses_openai_provider_shape() -> None:
    executor = AgentExecutor("sales-research-agent")
    response = await executor.invoke(
        InvokeRequest(message="Research competitor news for the Acme account in CRM")
    )

    assert response.tool_calls
    assert {call.name for call in response.tool_calls} == {
        "web_search",
        "crm_lookup",
        "company_research",
    }
    assert "sales angle" in response.output.lower()


@pytest.mark.asyncio
async def test_empty_message_rejected_by_guardrail() -> None:
    executor = AgentExecutor("customer-support-agent")
    with pytest.raises(GuardrailViolation):
        await executor.invoke(InvokeRequest(message="   "))


def test_reload_and_tool_serialization() -> None:
    executor = AgentExecutor("customer-support-agent")
    config = executor.reload()
    serialized = serialize_tool_for_provider(config.tools[0])
    schema = tool_input_schema(config.tools[0])

    assert config.provider == "anthropic"
    assert serialized["name"] == "search_knowledge_base"
    assert serialized["parameters"]["query"]["required"] is True
    assert schema["required"] == ["query"]


@pytest.mark.asyncio
async def test_production_openai_provider_normalizes_live_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCompletions:
        async def create(self, **_: object) -> object:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="Live account brief",
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="web_search",
                                        arguments='{"query":"Acme funding"}',
                                    )
                                )
                            ],
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=21, completion_tokens=8),
            )

    monkeypatch.setenv("RUNTIME_MODE", "production")
    provider = get_provider("openai")
    monkeypatch.setattr(
        provider,
        "_client",
        SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    config = AgentExecutor("sales-research-agent").config

    result = await provider.chat(
        ProviderRequest(
            messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "research Acme"}],
            tools=config.tools,
            config=config,
        )
    )

    assert result.output == "Live account brief"
    assert result.requested_tool_calls[0].arguments == {"query": "Acme funding"}
    assert result.tokens_used == 29
    assert result.cost_cents > 0


@pytest.mark.asyncio
async def test_production_anthropic_provider_normalizes_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMessages:
        async def create(self, **_: object) -> object:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text="Live support answer"),
                    SimpleNamespace(type="tool_use", name="create_ticket", input={"priority": "high"}),
                ],
                usage=SimpleNamespace(input_tokens=18, output_tokens=6),
            )

    monkeypatch.setenv("RUNTIME_MODE", "production")
    provider = get_provider("anthropic")
    monkeypatch.setattr(provider, "_client", SimpleNamespace(messages=FakeMessages()))
    config = AgentExecutor("customer-support-agent").config

    result = await provider.chat(
        ProviderRequest(
            messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "urgent issue"}],
            tools=config.tools,
            config=config,
        )
    )

    assert result.output == "Live support answer"
    assert result.requested_tool_calls[0].name == "create_ticket"
    assert result.requested_tool_calls[0].arguments == {"priority": "high"}
    assert result.tokens_used == 24


@pytest.mark.asyncio
async def test_unknown_tool_and_missing_provider_paths() -> None:
    call = await execute_tool(ToolCall(name="missing_tool", arguments={}))
    assert call.result["error"]

    with pytest.raises(ValueError):
        get_provider("missing")


def test_missing_agent_config_and_json_guardrail() -> None:
    with pytest.raises(FileNotFoundError):
        AgentExecutor("missing-agent")

    executor = AgentExecutor("customer-support-agent")
    executor.config.guardrails = Guardrails(required_output_format="json")
    with pytest.raises(GuardrailViolation):
        executor._apply_output_guardrails("plain text", [])
