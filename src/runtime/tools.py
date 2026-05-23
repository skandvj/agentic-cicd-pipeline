"""Mock tool implementations for sample agents.

Real CRM, knowledge base, and web integrations can replace this registry without
changing the executor contract.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .models import ToolCall

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
    started = time.perf_counter()
    handler = TOOL_REGISTRY.get(call.name)
    if handler is None:
        result: Any = {"error": f"tool '{call.name}' is not registered"}
    else:
        result = await handler(call.arguments)
    return call.model_copy(
        update={"result": result, "latency_ms": (time.perf_counter() - started) * 1000}
    )

