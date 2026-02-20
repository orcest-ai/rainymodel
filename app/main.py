"""
RainyModel - Intelligent LLM routing proxy for the Orcest AI ecosystem.

Routes requests through multiple tiers:
FREE (HF/ollamafreeapi) -> INTERNAL (Ollama) -> DIRECT (DeepSeek/Gemini/OpenAI/Claude/xAI) -> PREMIUM (OpenRouter)
"""

import json
import logging
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

logger = logging.getLogger("rainymodel")

LITELLM_CONFIG_PATH = os.getenv(
    "LITELLM_CONFIG_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "config", "litellm_config.yaml"
    ),
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

    provider_count = len(
        {
            d["route_info"]["upstream"]
            for deps in _rm_router._deployments.values()
            for d in deps
        }
    )
    model_count = len(_rm_router._deployments)
    logger.info(
        "RainyModel started: %d model aliases, %d providers",
        model_count,
        provider_count,
    )

    yield
    _router = None
    _rm_router = None


app = FastAPI(
    title="RainyModel",
    description="Intelligent LLM routing proxy for the Orcest AI ecosystem",
    version="0.2.0",
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
    if auth.startswith("Bearer "):
        return auth[7:] == master_key
    return False


KNOWN_MODELS = [
    {
        "id": "rainymodel/auto",
        "object": "model",
        "owned_by": "rainymodel",
        "description": (
            "Auto routing - cheapest first. "
            "FREE (HF/OllamaFree) -> INTERNAL (Ollama) -> "
            "DIRECT (DeepSeek/Gemini/OpenAI/xAI/Claude) -> PREMIUM (OpenRouter)"
        ),
    },
    {
        "id": "rainymodel/chat",
        "object": "model",
        "owned_by": "rainymodel",
        "description": (
            "General/Persian chat - optimized for conversation. "
            "Routes through DeepSeek, Gemini Flash, GPT-4o-mini, Grok-2, Claude Haiku"
        ),
    },
    {
        "id": "rainymodel/code",
        "object": "model",
        "owned_by": "rainymodel",
        "description": (
            "Coding tasks - DeepSeek Coder, Qwen Coder, GPT-4o-mini, Claude Haiku. "
            "Specialized coding models preferred"
        ),
    },
    {
        "id": "rainymodel/agent",
        "object": "model",
        "owned_by": "rainymodel",
        "description": (
            "Agent/complex tasks - Claude Sonnet 4 (direct), GPT-4o, Gemini Pro, Grok-2. "
            "Best models first, supports tool calling"
        ),
    },
]


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "rainymodel", "version": "0.2.0"}


@app.get("/")
async def root():
    return {
        "name": "RainyModel",
        "description": "Intelligent LLM routing proxy for the Orcest AI ecosystem",
        "version": "0.2.0",
        "providers": [
            "HuggingFace",
            "OllamaFreeAPI",
            "Ollama",
            "DeepSeek",
            "Gemini",
            "OpenAI",
            "Claude",
            "xAI",
            "OpenRouter",
        ],
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


# Parameters to forward from client request to LiteLLM
_FORWARD_PARAMS = [
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
]


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
    tried_upstreams: list[str] = []

    for dep in deployments:
        route_info = dep["route_info"]
        tried_upstreams.append(route_info["upstream"])

        params = dep["litellm_params"].copy()
        params["messages"] = body.get("messages", [])

        # Forward all supported parameters
        if is_stream:
            params["stream"] = True
        for key in _FORWARD_PARAMS:
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
                headers["x-rainymodel-tried"] = ",".join(tried_upstreams[:-1])

            # Handle streaming response
            if is_stream:
                return StreamingResponse(
                    _stream_chunks(response, route_info),
                    media_type="text/event-stream",
                    headers=headers,
                )

            # Handle non-streaming response
            if hasattr(response, "model_dump"):
                result = response.model_dump()
            else:
                result = dict(response)

            return JSONResponse(content=result, headers=headers)

        except Exception as e:
            last_error = e
            logger.debug(
                "Upstream %s failed for %s: %s",
                route_info["upstream"],
                model,
                e,
            )
            continue

    elapsed = time.time() - start_time
    error_msg = (
        f"All upstreams failed for {model} (tried: {', '.join(tried_upstreams)}): {last_error!s}"
        if last_error
        else f"No deployments found for {model}"
    )
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "message": error_msg,
                "type": "upstream_error",
            }
        },
        headers={
            "x-rainymodel-route": "error",
            "x-rainymodel-upstream": "none",
            "x-rainymodel-model": model,
            "x-rainymodel-latency-ms": str(int(elapsed * 1000)),
            "x-rainymodel-tried": ",".join(tried_upstreams),
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
