"""
RainyModel - Intelligent LLM routing proxy for the Orcest AI ecosystem.

Routes requests through: FREE (ollamafreeapi/HF) -> INTERNAL (Ollama) -> PREMIUM (OpenRouter)
"""

import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import litellm
import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from litellm import Router

from app.routing import RainyModelRouter

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_LITELLM_CONFIG_CANDIDATES = [
    os.getenv("LITELLM_CONFIG_PATH", ""),
    os.path.join(_PROJECT_ROOT, "config", "litellm_config.yaml"),
    "/app/config/litellm_config.yaml",
]

LITELLM_CONFIG_PATH = next(
    (p for p in _LITELLM_CONFIG_CANDIDATES if p and os.path.isfile(p)),
    os.path.join(_PROJECT_ROOT, "config", "litellm_config.yaml"),
)

litellm.drop_params = True
litellm.set_verbose = os.getenv("RAINYMODEL_DEBUG", "false").lower() == "true"

_router: Router | None = None
_rm_router: RainyModelRouter | None = None


def _expand_env(obj: Any) -> Any:
    if isinstance(obj, str):
        while "${" in obj:
            start = obj.index("${")
            end = obj.index("}", start)
            token = obj[start + 2 : end]
            if ":-" in token:
                var_name, default = token.split(":-", 1)
            else:
                var_name, default = token, ""
            obj = obj[:start] + os.getenv(var_name, default) + obj[end + 1 :]
        return obj
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(i) for i in obj]
    return obj


def _load_config() -> dict:
    with open(LITELLM_CONFIG_PATH) as f:
        raw = yaml.safe_load(f)
    return _expand_env(raw)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _router, _rm_router
    cfg = _load_config()
    model_list = cfg.get("model_list", [])
    router_settings = cfg.get("router_settings", {})

    _router = Router(
        model_list=model_list,
        num_retries=router_settings.get("num_retries", 3),
        timeout=router_settings.get("timeout", 120),
        retry_after=router_settings.get("retry_after", 5),
        allowed_fails=router_settings.get("allowed_fails", 2),
        cooldown_time=router_settings.get("cooldown_time", 60),
    )
    _rm_router = RainyModelRouter(model_list=model_list)
    yield
    _router = None
    _rm_router = None


app = FastAPI(
    title="RainyModel",
    description="Intelligent LLM routing proxy for the Orcest AI ecosystem",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _check_auth(request: Request) -> bool:
    master_key = os.getenv("RAINYMODEL_MASTER_KEY", "")
    if not master_key:
        return True
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:]
    if token == master_key:
        return True
    # Accept additional known service keys (comma-separated in env var)
    extra_keys = os.getenv("RAINYMODEL_SERVICE_KEYS", "")
    if extra_keys:
        for key in extra_keys.split(","):
            if token == key.strip():
                return True
    # Accept default Orcide IDE key for out-of-box integration
    orcide_key = os.getenv("RAINYMODEL_ORCIDE_KEY", "sk-rm-orcide-default")
    if token == orcide_key:
        return True
    return False


KNOWN_MODELS = [
    {
        "id": "rainymodel/auto",
        "object": "model",
        "owned_by": "rainymodel",
        "description": "Auto routing - cheapest/free first, then internal, then premium",
    },
    {
        "id": "rainymodel/chat",
        "object": "model",
        "owned_by": "rainymodel",
        "description": "General/Persian chat - optimized for conversation",
    },
    {
        "id": "rainymodel/code",
        "object": "model",
        "owned_by": "rainymodel",
        "description": "Coding tasks - Qwen Coder models preferred",
    },
    {
        "id": "rainymodel/agent",
        "object": "model",
        "owned_by": "rainymodel",
        "description": "Agent/complex tasks - long context + tool-capable models",
    },
]


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "rainymodel", "version": "0.1.0"}


@app.get("/")
async def root():
    return {
        "name": "RainyModel",
        "description": "Intelligent LLM routing proxy for the Orcest AI ecosystem",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": {
            "models": "/v1/models",
            "chat_completions": "/v1/chat/completions",
            "health": "/health",
        },
    }


@app.get("/v1/models")
async def list_models(request: Request):
    if not _check_auth(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    return {
        "object": "list",
        "data": KNOWN_MODELS,
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if not _check_auth(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    if _router is None or _rm_router is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Service not ready"},
        )

    body = await request.json()
    model = body.get("model", "rainymodel/auto")

    if not model.startswith("rainymodel/"):
        model = "rainymodel/auto"
    body["model"] = model

    policy = request.headers.get("X-RainyModel-Policy", "auto")
    is_stream = body.get("stream", False)

    start_time = time.time()
    route_info = {"route": "unknown", "upstream": "unknown", "model": "unknown"}

    deployments = _rm_router.get_ordered_deployments(model, policy)
    last_error = None

    for dep in deployments:
        route_info = dep["route_info"]
        params = dep["litellm_params"].copy()
        params["messages"] = body.get("messages", [])
        if is_stream:
            params["stream"] = True
        for key in (
            "temperature",
            "max_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "stop",
            "n",
            "tools",
            "tool_choice",
            "response_format",
            "seed",
        ):
            val = body.get(key)
            if val is not None:
                params[key] = val

        try:
            response = await litellm.acompletion(**params)
            elapsed = time.time() - start_time

            headers = {
                "x-rainymodel-route": route_info["route"],
                "x-rainymodel-upstream": route_info["upstream"],
                "x-rainymodel-model": route_info["model"],
                "x-rainymodel-latency-ms": str(int(elapsed * 1000)),
            }
            if last_error is not None:
                headers["x-rainymodel-fallback-reason"] = type(last_error).__name__

            if is_stream:
                return StreamingResponse(
                    _stream_chunks(response, route_info),
                    media_type="text/event-stream",
                    headers=headers,
                )

            if hasattr(response, "model_dump"):
                result = response.model_dump()
            else:
                result = dict(response)

            return JSONResponse(content=result, headers=headers)
        except Exception as e:
            last_error = e
            continue

    elapsed = time.time() - start_time
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "message": f"All upstreams failed for {model}: {last_error!s}"
                if last_error
                else f"No deployments found for {model}",
                "type": "upstream_error",
            }
        },
        headers={
            "x-rainymodel-route": "error",
            "x-rainymodel-upstream": "none",
            "x-rainymodel-model": model,
            "x-rainymodel-latency-ms": str(int(elapsed * 1000)),
        },
    )


async def _stream_chunks(response, route_info: dict):
    """Yield SSE chunks from a LiteLLM streaming response."""
    try:
        async for chunk in response:
            if hasattr(chunk, "model_dump"):
                data = chunk.model_dump()
            else:
                data = dict(chunk)
            yield f"data: {json.dumps(data)}\n\n"
    except Exception as e:
        error_data = {
            "error": {
                "message": f"Stream interrupted from {route_info['upstream']}: {e!s}",
                "type": "stream_error",
            }
        }
        yield f"data: {json.dumps(error_data)}\n\n"
    yield "data: [DONE]\n\n"
