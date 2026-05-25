from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime.agent_executor import AgentExecutor, GuardrailViolation
from src.runtime.models import Guardrails, InvokeRequest, ProviderRequest, ToolCall
from src.runtime.providers import get_provider, serialize_tool_for_provider, tool_input_schema
from src.runtime.settings import ProductionConfigurationError, RuntimeSettings, load_settings
from src.runtime.tools import (
    _execute_http_backend,
    _execute_mcp_backend,
    _post_json_with_retries,
    execute_tool,
)


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
    assert call.backend == "mock"
    assert call.status == "success"

    with pytest.raises(ValueError):
        get_provider("missing")


@pytest.mark.asyncio
async def test_http_tool_backend_records_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_http_backend(call: ToolCall, settings: object) -> dict[str, object]:
        return {"ok": True, "tool": call.name, "settings": bool(settings)}

    monkeypatch.setenv("TOOL_BACKEND", "http")
    monkeypatch.setenv("TOOL_HTTP_BASE_URL", "https://tools.example.test")
    monkeypatch.setattr("src.runtime.tools._execute_http_backend", fake_http_backend)

    call = await execute_tool(ToolCall(name="lookup_customer", arguments={"customer_id": "cus_123"}))

    assert call.backend == "http"
    assert call.status == "success"
    assert call.audit["backend"] == "http"
    assert call.result["tool"] == "lookup_customer"

    async def fake_post(url: str, payload: dict[str, object], settings: object) -> dict[str, object]:
        return {"url": url, "payload": payload, "settings": bool(settings)}

    monkeypatch.setattr("src.runtime.tools._post_json_with_retries", fake_post)
    result = await _execute_http_backend(
        ToolCall(name="search_knowledge_base", arguments={"query": "general"}),
        RuntimeSettings(tool_backend="http", tool_http_base_url="https://tools.example.test"),
    )
    assert result["url"] == "https://tools.example.test/tools/search_knowledge_base"


@pytest.mark.asyncio
async def test_mcp_tool_backend_and_backend_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(url: str, payload: dict[str, object], settings: object) -> dict[str, object]:
        return {
            "result": {
                "url": url,
                "name": payload["params"]["name"],  # type: ignore[index]
                "settings": bool(settings),
            }
        }

    monkeypatch.setenv("TOOL_BACKEND", "mcp")
    monkeypatch.setenv("TOOL_MCP_ENDPOINT", "https://mcp.example.test/messages")
    monkeypatch.setattr("src.runtime.tools._post_json_with_retries", fake_post)
    call = await execute_tool(ToolCall(name="create_ticket", arguments={"priority": "high"}))

    assert call.backend == "mcp"
    assert call.status == "success"
    assert call.result["name"] == "create_ticket"

    monkeypatch.setenv("TOOL_BACKEND", "http")
    monkeypatch.delenv("TOOL_HTTP_BASE_URL", raising=False)
    failed = await execute_tool(ToolCall(name="lookup_customer", arguments={}))
    assert failed.status == "error"
    assert "TOOL_HTTP_BASE_URL" in failed.error

    monkeypatch.setenv("TOOL_BACKEND", "mcp")
    monkeypatch.delenv("TOOL_MCP_ENDPOINT", raising=False)
    mcp_failed = await execute_tool(ToolCall(name="lookup_customer", arguments={}))
    assert mcp_failed.status == "error"
    assert "TOOL_MCP_ENDPOINT" in mcp_failed.error

    async def fake_non_result_post(
        url: str,
        payload: dict[str, object],
        settings: object,
    ) -> dict[str, object]:
        return {"ok": True, "url": url, "payload": payload, "settings": bool(settings)}

    monkeypatch.setattr("src.runtime.tools._post_json_with_retries", fake_non_result_post)
    raw_mcp = await _execute_mcp_backend(
        ToolCall(name="lookup_customer", arguments={}),
        RuntimeSettings(tool_backend="mcp", tool_mcp_endpoint="https://mcp.example.test/messages"),
    )
    assert raw_mcp["ok"] is True


@pytest.mark.asyncio
async def test_post_json_with_retries_uses_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]) -> FakeResponse:
            assert url == "https://tools.example.test/tools/search"
            assert json["tool"] == "search"
            return FakeResponse()

    monkeypatch.setattr("src.runtime.tools.httpx.AsyncClient", FakeClient)
    result = await _post_json_with_retries(
        "https://tools.example.test/tools/search",
        {"tool": "search"},
        RuntimeSettings(tool_backend="http", tool_timeout_seconds=2, tool_retries=0),
    )

    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_post_json_with_retries_reports_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> FailingClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]) -> object:
            raise httpx.ConnectError("network down")

    import httpx

    monkeypatch.setattr("src.runtime.tools.httpx.AsyncClient", FailingClient)
    with pytest.raises(httpx.ConnectError):
        await _post_json_with_retries(
            "https://tools.example.test/tools/search",
            {"tool": "search"},
            RuntimeSettings(tool_backend="http", tool_timeout_seconds=2, tool_retries=0),
        )

    with pytest.raises(RuntimeError):
        await _post_json_with_retries(
            "https://tools.example.test/tools/search",
            {"tool": "search"},
            RuntimeSettings(tool_backend="http", tool_retries=-1),
        )


def test_tool_backend_settings_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNTIME_MODE", "bad")
    with pytest.raises(ProductionConfigurationError):
        load_settings()

    monkeypatch.setenv("RUNTIME_MODE", "demo")
    monkeypatch.setenv("TOOL_BACKEND", "invalid")
    with pytest.raises(ProductionConfigurationError):
        load_settings()


def test_missing_agent_config_and_json_guardrail() -> None:
    with pytest.raises(FileNotFoundError):
        AgentExecutor("missing-agent")

    executor = AgentExecutor("customer-support-agent")
    executor.config.guardrails = Guardrails(required_output_format="json")
    with pytest.raises(GuardrailViolation):
        executor._apply_output_guardrails("plain text", [])
