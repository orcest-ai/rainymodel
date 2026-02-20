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
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from litellm import Router

from app.routing import RainyModelRouter
from app.sso_auth import (
    SSO_CALLBACK_URL,
    SSO_CLIENT_ID,
    SSO_CLIENT_SECRET,
    SSO_ISSUER,
    exchange_code_for_token,
    extract_user_from_payload,
    get_sso_login_url,
    get_sso_logout_url,
    verify_sso_token,
)

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


async def _check_auth(request: Request) -> dict[str, Any] | None:
    """Authenticate the request via master key, SSO JWT, or session cookie.

    Returns a dict ``{"user": "<identifier>", "method": "<auth_method>"}``
    on success, or ``None`` when the request cannot be authenticated.

    Authentication is attempted in this order:
      1. ``Authorization: Bearer <RAINYMODEL_MASTER_KEY>`` (legacy API key)
      2. ``Authorization: Bearer <SSO JWT>`` (verified against SSO issuer)
      3. ``rainymodel_token`` cookie (browser sessions from /auth/callback)
    """
    token: str | None = None

    # --- Extract bearer token from header ------------------------------------
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # 1) Legacy master-key check ----------------------------------------------
    master_key = os.getenv("RAINYMODEL_MASTER_KEY", "")
    if token and master_key and token == master_key:
        return {"user": "master-key", "method": "master_key"}

    # 2) SSO JWT verification -------------------------------------------------
    if token:
        payload = await verify_sso_token(token)
        if payload is not None:
            return {
                "user": extract_user_from_payload(payload),
                "method": "sso_bearer",
            }

    # 3) Cookie-based auth (browser sessions) ---------------------------------
    cookie_token = request.cookies.get("rainymodel_token")
    if cookie_token:
        payload = await verify_sso_token(cookie_token)
        if payload is not None:
            return {
                "user": extract_user_from_payload(payload),
                "method": "sso_cookie",
            }

    return None


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


# ---------------------------------------------------------------------------
# SSO / OAuth2 browser-flow endpoints
# ---------------------------------------------------------------------------


@app.get("/auth/login")
async def auth_login():
    """Redirect the browser to the SSO login page."""
    return RedirectResponse(url=get_sso_login_url())


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """OAuth2 authorization-code callback.

    Exchanges the ``code`` query parameter for an access token, sets a
    session cookie, and redirects the user to the root page.
    """
    code = request.query_params.get("code")
    if not code:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing authorization code"},
        )

    token_data = await exchange_code_for_token(code)
    if token_data is None:
        return JSONResponse(
            status_code=401,
            content={"error": "Failed to exchange authorization code"},
        )

    access_token = token_data.get("access_token", "")
    if not access_token:
        return JSONResponse(
            status_code=401,
            content={"error": "No access_token in SSO response"},
        )

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="rainymodel_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=3600,  # 1 hour
        path="/",
    )
    return response


@app.get("/auth/logout")
async def auth_logout():
    """Clear the session cookie and redirect to the SSO logout endpoint."""
    sso_logout = get_sso_logout_url(redirect_url="https://rm.orcest.ai")
    response = RedirectResponse(url=sso_logout, status_code=302)
    response.delete_cookie(key="rainymodel_token", path="/")
    return response


@app.get("/v1/models")
async def list_models(request: Request):
    auth_info = await _check_auth(request)
    if auth_info is None:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    return JSONResponse(
        content={"object": "list", "data": KNOWN_MODELS},
        headers={"x-rainymodel-user": auth_info["user"]},
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    auth_info = await _check_auth(request)
    if auth_info is None:
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
                "x-rainymodel-user": auth_info["user"],
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
