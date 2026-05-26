"""FastAPI runtime for invoking version-controlled agents."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from src.dashboard.metrics import record_invocation
from src.dashboard.traces import router as traces_router
from src.dashboard.traces import trace_store
from src.runtime.agent_executor import REPO_ROOT, AgentExecutor, GuardrailViolation
from src.runtime.models import AgentResponse, InvokeRequest
from src.runtime.settings import load_settings, validate_production_settings

SETTINGS = load_settings()


@asynccontextmanager
async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
    validate_production_settings(REPO_ROOT, SETTINGS)
    yield


app = FastAPI(title="Agentic CI/CD Runtime", version="0.1.0", lifespan=lifespan)
app.include_router(traces_router)
_EXECUTOR_CACHE: dict[str, AgentExecutor] = {}
PUBLIC_DIR = REPO_ROOT / "public"


def agent_root() -> Path:
    return REPO_ROOT / "agents"


def available_agent_ids() -> list[str]:
    if not agent_root().exists():
        return []
    return sorted(path.name for path in agent_root().iterdir() if (path / "agent.yaml").exists())


@app.get("/", include_in_schema=False)
async def public_index() -> FileResponse:
    return _public_file("index.html")


@app.get("/styles.css", include_in_schema=False)
async def public_styles() -> FileResponse:
    return _public_file("styles.css")


@app.get("/app.js", include_in_schema=False)
async def public_script() -> FileResponse:
    return _public_file("app.js")


def _public_file(name: str) -> FileResponse:
    path = PUBLIC_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"public asset '{name}' not found")
    return FileResponse(path)


def get_executor(agent_id: str) -> AgentExecutor:
    if agent_id not in available_agent_ids():
        raise HTTPException(status_code=404, detail=f"agent '{agent_id}' not found")
    executor = _EXECUTOR_CACHE.get(agent_id)
    if executor is None:
        executor = AgentExecutor(agent_id=agent_id)
        _EXECUTOR_CACHE[agent_id] = executor
    return executor


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "mode": SETTINGS.mode,
        "environment": SETTINGS.environment,
        "agents": available_agent_ids(),
    }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/v1/agents")
async def list_agents() -> list[dict[str, object]]:
    return [
        {"agent_id": agent_id, "config": get_executor(agent_id).config_as_dict()}
        for agent_id in available_agent_ids()
    ]


@app.get("/v1/agents/{agent_id}/config")
async def get_agent_config(agent_id: str) -> dict[str, object]:
    return get_executor(agent_id).config_as_dict()


@app.post("/v1/agents/{agent_id}/reload")
async def reload_agent(agent_id: str) -> dict[str, object]:
    executor = get_executor(agent_id)
    executor.reload()
    return {"agent_id": agent_id, "status": "reloaded", "config": executor.config_as_dict()}


@app.post("/v1/agents/{agent_id}/invoke", response_model=None)
async def invoke_agent(
    agent_id: str,
    request: InvokeRequest,
    accept: str | None = Header(default=None),
) -> Response:
    executor = get_executor(agent_id)
    if accept == "text/event-stream":
        return StreamingResponse(_stream_response(executor, request), media_type="text/event-stream")
    try:
        response = await executor.invoke(request)
    except GuardrailViolation as exc:
        record_invocation(agent_id, "guardrail", 0.0, 0.0, executor.config.model)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_invocation(agent_id, "ok", response.latency_ms, response.cost_cents, executor.config.model)
    trace_store.record_trace(agent_id, request, response)
    return JSONResponse(response.model_dump(mode="json"))


async def _stream_response(executor: AgentExecutor, request: InvokeRequest) -> AsyncIterator[str]:
    response: AgentResponse = await executor.invoke(request)
    words = response.output.split()
    for word in words:
        await asyncio.sleep(0)
        yield f"data: {word}\n\n"
    yield f"event: metadata\ndata: {response.model_dump_json()}\n\n"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.runtime.server:app", host="0.0.0.0", port=8000, reload=False)
