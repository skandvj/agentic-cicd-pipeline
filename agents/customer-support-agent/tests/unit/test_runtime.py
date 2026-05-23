from __future__ import annotations

import pytest

from src.runtime.agent_executor import AgentExecutor, GuardrailViolation
from src.runtime.models import Guardrails, InvokeRequest, ToolCall
from src.runtime.providers import get_provider, serialize_tool_for_provider
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

    assert config.provider == "anthropic"
    assert serialized["name"] == "search_knowledge_base"
    assert serialized["parameters"]["query"]["required"] is True


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
