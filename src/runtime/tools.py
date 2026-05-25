"""Tool execution backends for demo, HTTP, and MCP integrations."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .models import ToolCall
from .settings import RuntimeSettings, load_settings

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


async def search_knowledge_base(args: dict[str, Any]) -> dict[str, str]:
    query = str(args.get("query", "")).lower()
    await asyncio.sleep(0)
    if "password" in query or "reset" in query:
        return {
            "article_id": "KB-RESET-001",
            "title": "Resetting your password",
            "answer": "Use Forgot password on the sign-in page, then follow the emailed reset link.",
        }
    if "billing" in query or "invoice" in query:
        return {
            "article_id": "KB-BILLING-014",
            "title": "Billing and invoices",
            "answer": "Invoices are available from Settings > Billing for workspace admins.",
        }
    return {
        "article_id": "KB-GENERAL-002",
        "title": "General troubleshooting",
        "answer": "Check workspace status, refresh the browser, and confirm your role permissions.",
    }


async def lookup_customer(args: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0)
    return {
        "customer_id": args.get("customer_id", "unknown"),
        "plan": "Business",
        "account_status": "active",
        "open_tickets": 1,
    }


async def create_ticket(args: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0)
    return {
        "ticket_id": "SUP-1042",
        "subject": args.get("subject", "Support request"),
        "priority": args.get("priority", "medium"),
        "status": "created",
    }


async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0)
    query = args.get("query", "")
    return {
        "query": query,
        "results": [
            {
                "title": "Recent funding and product expansion",
                "url": "https://example.com/company-news",
                "summary": "The company announced a new enterprise product line and hiring plans.",
            }
        ],
    }


async def crm_lookup(args: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0)
    return {
        "account": args.get("account", "Acme Corp"),
        "stage": "Evaluation",
        "arr": 85000,
        "owner": "sales@example.com",
    }


async def company_research(args: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0)
    company = args.get("company", "target company")
    return {
        "company": company,
        "industry": "B2B SaaS",
        "signals": ["new executive hire", "security initiative", "expanding support team"],
    }


TOOL_REGISTRY: dict[str, ToolHandler] = {
    "search_knowledge_base": search_knowledge_base,
    "lookup_customer": lookup_customer,
    "create_ticket": create_ticket,
    "web_search": web_search,
    "crm_lookup": crm_lookup,
    "company_research": company_research,
}


async def execute_tool(call: ToolCall) -> ToolCall:
    settings = load_settings()
    started = time.perf_counter()
    backend = settings.tool_backend
    status = "success"
    error: str | None = None
    try:
        result = await _execute_with_backend(call, settings)
    except Exception as exc:  # noqa: BLE001 - tool failures must be captured in traces
        status = "error"
        error = str(exc)
        result = {"error": error}
    return call.model_copy(
        update={
            "result": result,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "backend": backend,
            "status": status,
            "error": error,
            "audit": {
                "backend": backend,
                "attempts": max(1, settings.tool_retries + 1),
                "tool": call.name,
            },
        }
    )


async def _execute_with_backend(call: ToolCall, settings: RuntimeSettings) -> Any:
    if settings.tool_backend == "mock":
        return await _execute_mock_backend(call)
    if settings.tool_backend == "http":
        return await _execute_http_backend(call, settings)
    return await _execute_mcp_backend(call, settings)


async def _execute_mock_backend(call: ToolCall) -> Any:
    handler = TOOL_REGISTRY.get(call.name)
    if handler is None:
        return {"error": f"tool '{call.name}' is not registered"}
    return await handler(call.arguments)


async def _execute_http_backend(call: ToolCall, settings: RuntimeSettings) -> Any:
    if not settings.tool_http_base_url:
        raise RuntimeError("TOOL_HTTP_BASE_URL is required for TOOL_BACKEND=http")
    url = f"{settings.tool_http_base_url.rstrip('/')}/tools/{call.name}"
    payload = {"tool": call.name, "arguments": call.arguments}
    return await _post_json_with_retries(url, payload, settings)


async def _execute_mcp_backend(call: ToolCall, settings: RuntimeSettings) -> Any:
    if not settings.tool_mcp_endpoint:
        raise RuntimeError("TOOL_MCP_ENDPOINT is required for TOOL_BACKEND=mcp")
    payload = {
        "jsonrpc": "2.0",
        "id": f"tool-{call.name}",
        "method": "tools/call",
        "params": {"name": call.name, "arguments": call.arguments},
    }
    response = await _post_json_with_retries(settings.tool_mcp_endpoint, payload, settings)
    if isinstance(response, dict) and "result" in response:
        return response["result"]
    return response


async def _post_json_with_retries(url: str, payload: dict[str, Any], settings: RuntimeSettings) -> Any:
    last_error: Exception | None = None
    for _attempt in range(settings.tool_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.tool_timeout_seconds) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return response.json()
        except Exception as exc:  # noqa: BLE001 - retry transport and upstream errors uniformly
            last_error = exc
            await asyncio.sleep(0)
    if last_error is None:
        raise RuntimeError("tool backend request failed without an exception")
    raise last_error
