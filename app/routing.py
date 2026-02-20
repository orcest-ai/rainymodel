"""
RainyModel routing logic.

Determines which upstream to use based on model alias and policy.
Routes: FREE (ollamafreeapi/HF) -> INTERNAL (Ollama) -> PREMIUM (OpenRouter)

Supports direct provider access via:
  rainymodel/openrouter/<model>
  rainymodel/huggingface/<model>
  rainymodel/ollama/<model>
  rainymodel/ollamafreeapi/<model>
"""

import os
import time
from typing import Any


# Direct provider routing: prefix -> (litellm model prefix, api_base env/default, api_key env)
DIRECT_PROVIDERS = {
    "openrouter": {
        "litellm_prefix": "openrouter/",
        "api_key_env": "OPENROUTER_API_KEY",
        "timeout": 120,
        "route": "premium",
        "upstream": "openrouter",
    },
    "huggingface": {
        "litellm_prefix": "huggingface/",
        "api_base": "https://router.huggingface.co/v1",
        "api_key_env": "HF_TOKEN",
        "timeout": 90,
        "route": "free",
        "upstream": "hf",
    },
    "ollama": {
        "litellm_prefix": "openai/",
        "api_base_env": "OLLAMA_PRIMARY_URL",
        "api_base_default": "http://164.92.147.36:11434",
        "api_key_env": "OLLAMA_API_KEY",
        "api_key_default": "ollama",
        "timeout": 120,
        "route": "internal",
        "upstream": "ollama",
    },
    "ollamafreeapi": {
        "litellm_prefix": "openai/",
        "api_base_env": "OLLAMAFREE_API_BASE",
        "api_base_default": "https://ollamafreeapi.orcest.ai",
        "api_key_env": "OLLAMAFREE_API_KEY",
        "api_key_default": "sk-free",
        "timeout": 120,
        "route": "free",
        "upstream": "ollamafreeapi",
    },
}


class RainyModelRouter:
    TIER_FREE_OLLAMAFREE = "free-ollamafree"
    TIER_FREE_HF = "free-hf"
    TIER_INTERNAL = "internal"
    TIER_PREMIUM = "premium"

    # Known alias modes (non-passthrough)
    KNOWN_MODES = {"auto", "chat", "code", "agent", "document"}

    def __init__(self, model_list: list[dict[str, Any]]):
        self._deployments: dict[str, list[dict[str, Any]]] = {}
        self._hf_credits_exhausted_until: float = 0

        for entry in model_list:
            name = entry.get("model_name", "")
            params = entry.get("litellm_params", {})
            info = entry.get("model_info", {})
            desc = info.get("description", "").lower()

            tier = self._classify_tier(params, desc)

            deployment = {
                "litellm_params": params,
                "model_info": info,
                "tier": tier,
                "route_info": {
                    "route": self._tier_to_route(tier),
                    "upstream": self._tier_to_upstream(tier),
                    "model": params.get("model", name),
                },
            }

            self._deployments.setdefault(name, []).append(deployment)

    @staticmethod
    def parse_direct_provider(model: str) -> tuple[str, str] | None:
        """Parse a direct provider model string.

        Returns (provider_key, downstream_model) or None if not a direct route.
        E.g. 'rainymodel/openrouter/anthropic/claude-sonnet-4'
             -> ('openrouter', 'anthropic/claude-sonnet-4')
        """
        if not model.startswith("rainymodel/"):
            return None

        rest = model[len("rainymodel/"):]  # e.g. 'openrouter/anthropic/claude-sonnet-4'

        for provider_key in DIRECT_PROVIDERS:
            prefix = provider_key + "/"
            if rest.startswith(prefix):
                downstream = rest[len(prefix):]
                if downstream:
                    return (provider_key, downstream)
        return None

    @staticmethod
    def build_direct_deployment(provider_key: str, downstream_model: str) -> dict[str, Any]:
        """Build a single deployment dict for direct provider access."""
        cfg = DIRECT_PROVIDERS[provider_key]
        litellm_model = cfg["litellm_prefix"] + downstream_model

        params: dict[str, Any] = {
            "model": litellm_model,
            "timeout": cfg["timeout"],
        }

        # API base
        if "api_base" in cfg:
            params["api_base"] = cfg["api_base"]
        elif "api_base_env" in cfg:
            default = cfg.get("api_base_default", "")
            base = os.getenv(cfg["api_base_env"], default)
            if base:
                params["api_base"] = base.rstrip("/") + "/v1"

        # API key
        if "api_key_env" in cfg:
            default_key = cfg.get("api_key_default", "")
            params["api_key"] = os.getenv(cfg["api_key_env"], default_key)

        return {
            "litellm_params": params,
            "model_info": {"description": f"Direct {provider_key} access"},
            "tier": "direct",
            "route_info": {
                "route": cfg["route"],
                "upstream": cfg["upstream"],
                "model": litellm_model,
            },
        }

    def is_known_alias(self, model: str) -> bool:
        """Check if model is a known RainyModel alias (auto/chat/code/agent/document)."""
        if not model.startswith("rainymodel/"):
            return False
        mode = model[len("rainymodel/"):]
        return mode in self.KNOWN_MODES

    def _classify_tier(self, params: dict, desc: str) -> str:
        api_base = params.get("api_base", "")
        model = params.get("model", "")

        if "ollamafreeapi" in api_base or "ollamafree" in desc:
            return self.TIER_FREE_OLLAMAFREE

        if "huggingface" in api_base or "hf" in desc or model.startswith("huggingface/"):
            return self.TIER_FREE_HF

        if "openrouter" in model or "premium" in desc:
            return self.TIER_PREMIUM

        ollama_primary = os.getenv("OLLAMA_PRIMARY_URL", "164.92.147.36:11434")
        ollama_secondary = os.getenv("OLLAMA_SECONDARY_URL", "178.128.196.3:11434")
        ollama_base = os.getenv("OLLAMA_BASE_URL", "localhost:11434")
        if (ollama_primary in api_base or ollama_secondary in api_base
                or ollama_base in api_base or "internal" in desc or "ollama" in desc):
            return self.TIER_INTERNAL

        return self.TIER_PREMIUM

    def _tier_to_route(self, tier: str) -> str:
        if tier in (self.TIER_FREE_OLLAMAFREE, self.TIER_FREE_HF):
            return "free"
        if tier == self.TIER_INTERNAL:
            return "internal"
        return "premium"

    def _tier_to_upstream(self, tier: str) -> str:
        if tier == self.TIER_FREE_OLLAMAFREE:
            return "ollamafreeapi"
        if tier == self.TIER_FREE_HF:
            return "hf"
        if tier == self.TIER_INTERNAL:
            return "ollama"
        return "openrouter"

    def mark_hf_credits_exhausted(self, duration_seconds: int = 86400):
        self._hf_credits_exhausted_until = time.time() + duration_seconds

    def _is_hf_available(self) -> bool:
        return time.time() > self._hf_credits_exhausted_until

    def _get_tier_order(self, policy: str) -> list[str]:
        if policy == "uncensored":
            return [
                self.TIER_INTERNAL,
                self.TIER_FREE_HF,
                self.TIER_PREMIUM,
            ]
        if policy == "premium":
            return [
                self.TIER_PREMIUM,
                self.TIER_FREE_HF,
                self.TIER_INTERNAL,
            ]
        if policy == "free":
            return [
                self.TIER_FREE_HF,
                self.TIER_INTERNAL,
                self.TIER_PREMIUM,
            ]
        return [
            self.TIER_FREE_HF,
            self.TIER_INTERNAL,
            self.TIER_PREMIUM,
        ]

    def get_ordered_deployments(
        self, model: str, policy: str = "auto"
    ) -> list[dict[str, Any]]:
        deployments = self._deployments.get(model, [])
        if not deployments:
            return []

        order = self._get_tier_order(policy)
        result: list[dict[str, Any]] = []

        for tier in order:
            if tier == self.TIER_FREE_HF and not self._is_hf_available():
                continue
            for dep in deployments:
                if dep["tier"] == tier and dep not in result:
                    result.append(dep)

        for dep in deployments:
            if dep not in result:
                result.append(dep)

        return result

    def select_deployment(
        self, model: str, policy: str = "auto"
    ) -> dict[str, Any] | None:
        ordered = self.get_ordered_deployments(model, policy)
        return ordered[0] if ordered else None

    @staticmethod
    def list_direct_providers() -> list[dict[str, Any]]:
        """Return metadata about available direct provider routes."""
        result = []
        for key, cfg in DIRECT_PROVIDERS.items():
            result.append({
                "provider": key,
                "prefix": f"rainymodel/{key}/",
                "route": cfg["route"],
                "upstream": cfg["upstream"],
                "description": f"Direct access to {key} models",
            })
        return result
