"""
SSO authentication module for RainyModel.

Verifies JWT tokens issued by login.orcest.ai (the Orcest SSO/OIDC provider).
Supports two authentication methods:
  - Bearer token from SSO (JWT verified against login.orcest.ai/api/token/verify)
  - Legacy API key for backward compatibility (RAINYMODEL_MASTER_KEY)

Also provides /auth/callback for browser-based OAuth2 authorization-code flow
and /auth/logout for session termination.
"""

import os
import time
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuration (populated from environment at import time; can be overridden)
# ---------------------------------------------------------------------------

SSO_ISSUER: str = os.getenv("SSO_ISSUER", "https://login.orcest.ai")
SSO_CLIENT_ID: str = os.getenv("SSO_CLIENT_ID", "")
SSO_CLIENT_SECRET: str = os.getenv("SSO_CLIENT_SECRET", "")
SSO_CALLBACK_URL: str = os.getenv("SSO_CALLBACK_URL", "https://rm.orcest.ai/auth/callback")

# ---------------------------------------------------------------------------
# Token verification cache  (token -> {payload, expires_at})
# TTL = 5 minutes to reduce round-trips to the SSO issuer.
# ---------------------------------------------------------------------------

_TOKEN_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_TTL_SECONDS: int = 300  # 5 minutes


def _prune_cache() -> None:
    """Remove expired entries from the token cache."""
    now = time.time()
    expired = [k for k, v in _TOKEN_CACHE.items() if v["expires_at"] <= now]
    for k in expired:
        del _TOKEN_CACHE[k]


async def verify_sso_token(token: str) -> dict[str, Any] | None:
    """Verify a JWT token against the SSO issuer's token-verify endpoint.

    Returns the decoded token payload dict on success, or ``None`` if the
    token is invalid / expired / the SSO service is unreachable.

    Results are cached for up to ``_CACHE_TTL_SECONDS`` seconds.
    """
    _prune_cache()

    # Cache hit ----------------------------------------------------------------
    cached = _TOKEN_CACHE.get(token)
    if cached is not None and cached["expires_at"] > time.time():
        return cached["payload"]

    # Cache miss -- call the SSO issuer ----------------------------------------
    verify_url = f"{SSO_ISSUER.rstrip('/')}/api/token/verify"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                verify_url,
                json={"token": token},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            return None

        payload = resp.json()
        # The SSO service returns the decoded claims on success.  Any
        # truthy JSON body is treated as valid.
        if not payload:
            return None

        _TOKEN_CACHE[token] = {
            "payload": payload,
            "expires_at": time.time() + _CACHE_TTL_SECONDS,
        }
        return payload

    except (httpx.HTTPError, Exception):
        return None


async def exchange_code_for_token(code: str) -> dict[str, Any] | None:
    """Exchange an OAuth2 authorization code for an access/ID token.

    Performs the standard ``authorization_code`` grant against the SSO
    issuer's token endpoint.  Returns the full token response dict on
    success or ``None`` on failure.
    """
    token_url = f"{SSO_ISSUER.rstrip('/')}/api/token"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": SSO_CALLBACK_URL,
                    "client_id": SSO_CLIENT_ID,
                    "client_secret": SSO_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code != 200:
            return None
        return resp.json()
    except (httpx.HTTPError, Exception):
        return None


def get_sso_login_url(state: str = "") -> str:
    """Build the SSO authorization URL that the browser should redirect to."""
    base = f"{SSO_ISSUER.rstrip('/')}/authorize"
    params = (
        f"?response_type=code"
        f"&client_id={SSO_CLIENT_ID}"
        f"&redirect_uri={SSO_CALLBACK_URL}"
        f"&scope=openid+profile+email"
    )
    if state:
        params += f"&state={state}"
    return base + params


def get_sso_logout_url(redirect_url: str = "") -> str:
    """Build the SSO end-session / logout URL."""
    base = f"{SSO_ISSUER.rstrip('/')}/logout"
    if redirect_url:
        base += f"?redirect_uri={redirect_url}"
    return base


def extract_user_from_payload(payload: dict[str, Any]) -> str:
    """Return a human-readable user identifier from the SSO token payload.

    Tries ``preferred_username``, ``email``, and ``sub`` in that order.
    """
    return (
        payload.get("preferred_username")
        or payload.get("email")
        or payload.get("sub")
        or "unknown"
    )
