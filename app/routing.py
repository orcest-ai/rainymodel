"""
RainyModel routing logic.

Determines which upstream to use based on model alias and policy.
Routes: FREE (ollamafreeapi/HF) -> INTERNAL (Ollama) -> PREMIUM (OpenRouter/OpenAI/Anthropic/xAI/DeepSeek/Gemini)
"""

import os
import time
from typing import Any


class RainyModelRouter:
    TIER_FREE_OLLAMAFREE = "free-ollamafree"
    TIER_FREE_HF = "free-hf"
    TIER_INTERNAL = "internal"
    TIER_PREMIUM = "premium"
    TIER_PREMIUM_OPENAI = "premium-openai"
    TIER_PREMIUM_ANTHROPIC = "premium-anthropic"
    TIER_PREMIUM_XAI = "premium-xai"
    TIER_PREMIUM_DEEPSEEK = "premium-deepseek"
    TIER_PREMIUM_GEMINI = "premium-gemini"

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

    _PREMIUM_TIERS = frozenset({
        "premium", "premium-openai", "premium-anthropic",
        "premium-xai", "premium-deepseek", "premium-gemini",
    })

    def _classify_tier(self, params: dict, desc: str) -> str:
        api_base = params.get("api_base", "")
        model = params.get("model", "")

        if "ollamafreeapi" in api_base or "ollamafree" in desc:
            return self.TIER_FREE_OLLAMAFREE

        if "huggingface" in api_base or "hf" in desc or model.startswith("huggingface/"):
            return self.TIER_FREE_HF

        if model.startswith("openai/") and not api_base:
            return self.TIER_PREMIUM_OPENAI
        if model.startswith("anthropic/") or model.startswith("claude"):
            return self.TIER_PREMIUM_ANTHROPIC
        if model.startswith("xai/"):
            return self.TIER_PREMIUM_XAI
        if model.startswith("deepseek/"):
            return self.TIER_PREMIUM_DEEPSEEK
        if model.startswith("gemini/"):
            return self.TIER_PREMIUM_GEMINI

        if "openrouter" in model:
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

    _UPSTREAM_MAP = {
        "free-ollamafree": "ollamafreeapi",
        "free-hf": "hf",
        "internal": "ollama",
        "premium": "openrouter",
        "premium-openai": "openai",
        "premium-anthropic": "anthropic",
        "premium-xai": "xai",
        "premium-deepseek": "deepseek",
        "premium-gemini": "gemini",
    }

    def _tier_to_upstream(self, tier: str) -> str:
        return self._UPSTREAM_MAP.get(tier, "openrouter")

    def mark_hf_credits_exhausted(self, duration_seconds: int = 86400):
        self._hf_credits_exhausted_until = time.time() + duration_seconds

    def _is_hf_available(self) -> bool:
        return time.time() > self._hf_credits_exhausted_until

    _ALL_PREMIUM_TIERS = [
        TIER_PREMIUM,
        TIER_PREMIUM_OPENAI,
        TIER_PREMIUM_ANTHROPIC,
        TIER_PREMIUM_XAI,
        TIER_PREMIUM_DEEPSEEK,
        TIER_PREMIUM_GEMINI,
    ]

    def _get_tier_order(self, policy: str) -> list[str]:
        if policy == "uncensored":
            return [
                self.TIER_INTERNAL,
                self.TIER_FREE_HF,
                *self._ALL_PREMIUM_TIERS,
            ]
        if policy == "premium":
            return [
                *self._ALL_PREMIUM_TIERS,
                self.TIER_FREE_HF,
                self.TIER_INTERNAL,
            ]
        if policy == "free":
            return [
                self.TIER_FREE_HF,
                self.TIER_INTERNAL,
                *self._ALL_PREMIUM_TIERS,
            ]
        # auto: FREE → INTERNAL → PREMIUM
        return [
            self.TIER_FREE_HF,
            self.TIER_INTERNAL,
            *self._ALL_PREMIUM_TIERS,
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
