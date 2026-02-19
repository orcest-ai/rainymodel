"""
RainyModel - Intelligent LLM routing proxy for the Orcest AI ecosystem.

Routes requests through: FREE (ollamafreeapi/HF) -> INTERNAL (Ollama) -> PREMIUM (OpenRouter)
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Any

import litellm
import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from litellm import Router

from app.routing import RainyModelRouter

LITELLM_CONFIG_PATH = os.getenv(
    "LITELLM_CONFIG_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "litellm_config.yaml"),
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
    if auth.startswith("Bearer "):
        return auth[7:] == master_key
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

    start_time = time.time()
    route_info = {"route": "unknown", "upstream": "unknown", "model": "unknown"}

    deployments = _rm_router.get_ordered_deployments(model, policy)
    last_error = None

    for dep in deployments:
        route_info = dep["route_info"]
        params = dep["litellm_params"].copy()
        params["messages"] = body.get("messages", [])
        if body.get("temperature") is not None:
            params["temperature"] = body["temperature"]
        if body.get("max_tokens") is not None:
            params["max_tokens"] = body["max_tokens"]
        if body.get("stream") is not None:
            params["stream"] = body["stream"]
        if body.get("top_p") is not None:
            params["top_p"] = body["top_p"]

        try:
            response = await litellm.acompletion(**params)
            elapsed = time.time() - start_time

            if hasattr(response, "model_dump"):
                result = response.model_dump()
            else:
                result = dict(response)

            headers = {
                "x-rainymodel-route": route_info["route"],
                "x-rainymodel-upstream": route_info["upstream"],
                "x-rainymodel-model": route_info["model"],
                "x-rainymodel-latency-ms": str(int(elapsed * 1000)),
            }
            if last_error is not None:
                headers["x-rainymodel-fallback-reason"] = str(type(last_error).__name__)

            return JSONResponse(content=result, headers=headers)
        except Exception as e:
            last_error = e
            continue

    elapsed = time.time() - start_time
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "message": f"All upstreams failed for {model}: {last_error!s}" if last_error else f"No deployments found for {model}",
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
