"""Typed runtime contracts used by the server, executor, and evals."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ProviderName = Literal["openai", "anthropic"]


class ToolParameter(BaseModel):
    type: str = "string"
    required: bool = False
    enum: list[str] | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, ToolParameter] = Field(default_factory=dict)


class Guardrails(BaseModel):
    max_tool_calls: int = 5
    blocked_patterns: list[str] = Field(default_factory=list)
    require_citation: bool = False
    required_output_format: str | None = None


class AgentConfig(BaseModel):
    provider: ProviderName
    model: str
    system_prompt: str
    tools: list[ToolSpec] = Field(default_factory=list)
    guardrails: Guardrails = Field(default_factory=Guardrails)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=32768)

    @field_validator("tools")
    @classmethod
    def tool_names_must_be_unique(cls, tools: list[ToolSpec]) -> list[ToolSpec]:
        names = [tool.name for tool in tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        return tools


class InvokeRequest(BaseModel):
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    latency_ms: float = 0.0


class AgentResponse(BaseModel):
    output: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    latency_ms: float
    tokens_used: int
    cost_cents: float
    trace_id: str


class ProviderRequest(BaseModel):
    messages: list[dict[str, str]]
    tools: list[ToolSpec] = Field(default_factory=list)
    config: AgentConfig


class ProviderResult(BaseModel):
    output: str
    requested_tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int
    output_tokens: int
    cost_cents: float

    @property
    def tokens_used(self) -> int:
        return self.input_tokens + self.output_tokens


class EvalCase(BaseModel):
    id: str
    input: str
    expected_output: str | None = None
    scorer: str | None = None
    keywords: list[str] = Field(default_factory=list)
    max_latency_ms: float | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class EvalCaseResult(BaseModel):
    id: str
    input: str
    expected: str | None = None
    actual: str
    score: float
    passed: bool
    latency_ms: float
    tokens_used: int
    cost_cents: float
    reasoning: str = ""


class EvalResult(BaseModel):
    agent_id: str
    suite: str
    accuracy: float
    pass_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    total_cost_cents: float
    cases: list[EvalCaseResult]
    baseline_comparison: dict[str, Any] = Field(default_factory=dict)

