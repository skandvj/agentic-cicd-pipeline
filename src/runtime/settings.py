"""Runtime configuration and production readiness checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml

RuntimeMode = Literal["demo", "production"]
ToolBackend = Literal["mock", "http", "mcp"]


@dataclass(frozen=True)
class RuntimeSettings:
    mode: RuntimeMode = "demo"
    environment: str = "development"
    database_url: str | None = None
    redis_url: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    tool_backend: ToolBackend = "mock"
    tool_http_base_url: str | None = None
    tool_mcp_endpoint: str | None = None
    tool_timeout_seconds: float = 10.0
    tool_retries: int = 1

    @property
    def is_production(self) -> bool:
        return self.mode == "production"


class ProductionConfigurationError(RuntimeError):
    """Raised when production mode is requested without required live configuration."""


def load_settings() -> RuntimeSettings:
    raw_mode = os.getenv("RUNTIME_MODE", "demo").strip().lower()
    if raw_mode not in {"demo", "production"}:
        raise ProductionConfigurationError("RUNTIME_MODE must be either 'demo' or 'production'")
    raw_tool_backend = os.getenv("TOOL_BACKEND", "mock").strip().lower()
    if raw_tool_backend not in {"mock", "http", "mcp"}:
        raise ProductionConfigurationError("TOOL_BACKEND must be one of: mock, http, mcp")
    return RuntimeSettings(
        mode=cast(RuntimeMode, raw_mode),
        environment=os.getenv("ENVIRONMENT", "development"),
        database_url=_blank_to_none(os.getenv("DATABASE_URL")),
        redis_url=_blank_to_none(os.getenv("REDIS_URL")),
        openai_api_key=_blank_to_none(os.getenv("OPENAI_API_KEY")),
        anthropic_api_key=_blank_to_none(os.getenv("ANTHROPIC_API_KEY")),
        tool_backend=cast(ToolBackend, raw_tool_backend),
        tool_http_base_url=_blank_to_none(os.getenv("TOOL_HTTP_BASE_URL")),
        tool_mcp_endpoint=_blank_to_none(os.getenv("TOOL_MCP_ENDPOINT")),
        tool_timeout_seconds=float(os.getenv("TOOL_TIMEOUT_SECONDS", "10")),
        tool_retries=int(os.getenv("TOOL_RETRIES", "1")),
    )


def validate_production_settings(repo_root: Path, settings: RuntimeSettings | None = None) -> None:
    resolved = settings or load_settings()
    if not resolved.is_production:
        return

    missing: list[str] = []
    if not resolved.database_url:
        missing.append("DATABASE_URL")
    if not resolved.redis_url:
        missing.append("REDIS_URL")

    providers = _configured_providers(repo_root)
    if "openai" in providers and not resolved.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if "anthropic" in providers and not resolved.anthropic_api_key:
        missing.append("ANTHROPIC_API_KEY")
    if resolved.tool_backend == "mock":
        missing.append("TOOL_BACKEND=http|mcp")
    if resolved.tool_backend == "http" and not resolved.tool_http_base_url:
        missing.append("TOOL_HTTP_BASE_URL")
    if resolved.tool_backend == "mcp" and not resolved.tool_mcp_endpoint:
        missing.append("TOOL_MCP_ENDPOINT")

    if missing:
        joined = ", ".join(sorted(set(missing)))
        raise ProductionConfigurationError(
            f"Production mode requires live configuration for: {joined}. "
            "Set RUNTIME_MODE=demo for local deterministic development."
        )


def _configured_providers(repo_root: Path) -> set[str]:
    providers: set[str] = set()
    agent_root = repo_root / "agents"
    if not agent_root.exists():
        return providers
    for config_path in agent_root.glob("*/agent.yaml"):
        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        provider = raw.get("provider")
        if isinstance(provider, str):
            providers.add(provider)
    return providers


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value
