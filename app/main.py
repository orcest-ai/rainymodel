"""
RainyModel - Intelligent LLM routing proxy for the Orcest AI ecosystem.

Routes requests through: FREE (ollamafreeapi/HF) -> INTERNAL (Ollama) -> PREMIUM (OpenRouter)
Supports AUTO mode with provider auto-discovery and rate limiting.
"""

import json
import logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import litellm
import yaml
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from litellm import Router

from app.routing import RainyModelRouter

logger = logging.getLogger("rainymodel")

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
_rate_limits: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 60  # requests per window


def _check_rate_limit(api_key: str) -> bool:
    """Return True if the request is within the rate limit, False otherwise."""
    now = time.time()
    _rate_limits[api_key] = [t for t in _rate_limits[api_key] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[api_key]) >= RATE_LIMIT_MAX:
        return False
    _rate_limits[api_key].append(now)
    return True


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------
def _audit_log(event: str, details: dict):
    """Emit a structured JSON audit log entry to stdout via the logger."""
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": event,
        **details,
    }
    logger.info(json.dumps(log_entry))

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
    provider_status = {}
    env_checks = {
        "huggingface": "HF_TOKEN",
        "ollama": "OLLAMA_BASE_URL",
        "ollamafreeapi": "OLLAMAFREE_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "xai": "XAI_API_KEY",
    }
    for provider, env_var in env_checks.items():
        provider_status[provider] = "configured" if os.environ.get(env_var) else "not_configured"
    return {
        "status": "healthy",
        "service": "rainymodel",
        "version": "0.1.0",
        "providers": provider_status,
    }


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
            "providers": "/v1/providers",
            "auto_config": "/v1/auto/config",
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


@app.get("/v1/providers")
async def list_providers(auth: str = Depends(_check_auth)):
    """List all configured providers and their availability."""
    providers = {}
    env_mappings = {
        "ollama": {"key": "OLLAMA_API_KEY", "base": "OLLAMA_BASE_URL", "name": "Ollama"},
        "openrouter": {"key": "OPENROUTER_API_KEY", "base": None, "name": "OpenRouter"},
        "huggingface": {"key": "HF_TOKEN", "base": None, "name": "HuggingFace"},
        "ollamafreeapi": {"key": "OLLAMAFREE_API_KEY", "base": "OLLAMAFREE_API_BASE", "name": "OllamaFreeAPI"},
        "openai": {"key": "OPENAI_API_KEY", "base": "OPENAI_API_BASE", "name": "OpenAI"},
        "anthropic": {"key": "ANTHROPIC_API_KEY", "base": None, "name": "Anthropic/Claude"},
        "deepseek": {"key": "DEEPSEEK_API_KEY", "base": None, "name": "DeepSeek"},
        "gemini": {"key": "GEMINI_API_KEY", "base": None, "name": "Google Gemini"},
        "groq": {"key": "GROQ_API_KEY", "base": None, "name": "Groq"},
        "xai": {"key": "XAI_API_KEY", "base": None, "name": "xAI/Grok"},
    }
    for provider_id, config in env_mappings.items():
        has_key = bool(os.environ.get(config["key"]))
        has_base = config["base"] is None or bool(os.environ.get(config["base"]))
        providers[provider_id] = {
            "name": config["name"],
            "configured": has_key and has_base,
            "base_url": os.environ.get(config.get("base", ""), "") if config.get("base") else None,
        }
    _audit_log("list_providers", {"provider_count": len(providers)})
    return {"providers": providers}


@app.get("/v1/auto/config")
async def auto_config(auth: str = Depends(_check_auth)):
    """AUTO mode: return recommended configuration based on available providers."""
    available = []
    # Check each provider
    if os.environ.get("HF_TOKEN"):
        available.append({"tier": "free", "provider": "huggingface"})
    if os.environ.get("OLLAMA_BASE_URL"):
        available.append({"tier": "internal", "provider": "ollama"})
    if os.environ.get("OLLAMAFREE_API_KEY"):
        available.append({"tier": "free", "provider": "ollamafreeapi"})
    if os.environ.get("OPENROUTER_API_KEY"):
        available.append({"tier": "premium", "provider": "openrouter"})
    if os.environ.get("OPENAI_API_KEY"):
        available.append({"tier": "premium", "provider": "openai"})
    if os.environ.get("ANTHROPIC_API_KEY"):
        available.append({"tier": "premium", "provider": "anthropic"})

    _audit_log("auto_config", {"available_providers": len(available)})
    return {
        "default_model": "rainymodel/auto",
        "default_policy": "auto",
        "available_providers": available,
        "recommended_models": KNOWN_MODELS,
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if not _check_auth(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    # --- Rate limiting ---
    auth_header = request.headers.get("Authorization", "")
    api_key = auth_header[7:] if auth_header.startswith("Bearer ") else "anonymous"
    if not _check_rate_limit(api_key):
        _audit_log("rate_limited", {"api_key_hash": hash(api_key), "model": "unknown"})
        return JSONResponse(
            status_code=429,
            content={"error": {"message": "Rate limit exceeded. Try again later.", "type": "rate_limit_error"}},
        )

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
    provider_override = request.headers.get("X-RainyModel-Provider")
    is_stream = body.get("stream", False)

    _audit_log("chat_completion_request", {
        "model": model,
        "policy": policy,
        "provider_override": provider_override,
        "stream": is_stream,
        "api_key_hash": hash(api_key),
    })

    start_time = time.time()
    route_info = {"route": "unknown", "upstream": "unknown", "model": "unknown"}

    deployments = _rm_router.get_ordered_deployments(
        model, policy, provider_override=provider_override,
    )
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
                _audit_log("chat_completion_success", {
                    "model": model,
                    "route": route_info["route"],
                    "upstream": route_info["upstream"],
                    "latency_ms": int(elapsed * 1000),
                    "stream": True,
                })
                return StreamingResponse(
                    _stream_chunks(response, route_info),
                    media_type="text/event-stream",
                    headers=headers,
                )

            if hasattr(response, "model_dump"):
                result = response.model_dump()
            else:
                result = dict(response)

            _audit_log("chat_completion_success", {
                "model": model,
                "route": route_info["route"],
                "upstream": route_info["upstream"],
                "latency_ms": int(elapsed * 1000),
                "stream": False,
            })
            return JSONResponse(content=result, headers=headers)
        except Exception as e:
            last_error = e
            continue

    elapsed = time.time() - start_time
    _audit_log("chat_completion_failure", {
        "model": model,
        "error": str(last_error) if last_error else "no deployments",
        "latency_ms": int(elapsed * 1000),
    })
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
