"""
RainyModel routing logic.

Determines which upstream to use based on model alias and policy.
Routes: FREE (HF/ollamafreeapi) -> INTERNAL (Ollama) -> DIRECT (DeepSeek/Gemini/OpenAI/Claude/xAI) -> PREMIUM (OpenRouter)
"""

import os
import time
from typing import Any


class RainyModelRouter:
    TIER_FREE_OLLAMAFREE = "free-ollamafree"
    TIER_FREE_HF = "free-hf"
    TIER_INTERNAL = "internal"
    TIER_DIRECT_DEEPSEEK = "direct-deepseek"
    TIER_DIRECT_GEMINI = "direct-gemini"
    TIER_DIRECT_OPENAI = "direct-openai"
    TIER_DIRECT_CLAUDE = "direct-claude"
    TIER_DIRECT_XAI = "direct-xai"
    TIER_PREMIUM = "premium"

    # All direct tiers ordered by cost (cheapest first)
    _DIRECT_TIERS_BY_COST = [
        "direct-deepseek",
        "direct-gemini",
        "direct-openai",
        "direct-xai",
        "direct-claude",
    ]

    # Direct tiers ordered by quality (best first, for premium policy)
    _DIRECT_TIERS_BY_QUALITY = [
        "direct-claude",
        "direct-openai",
        "direct-xai",
        "direct-gemini",
        "direct-deepseek",
    ]

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

    def _classify_tier(self, params: dict, desc: str) -> str:
        api_base = params.get("api_base", "")
        model = params.get("model", "")

        # Free tiers
        if "ollamafreeapi" in api_base or "ollamafree" in desc:
            return self.TIER_FREE_OLLAMAFREE

        if (
            "huggingface" in api_base
            or "hf" in desc
            or model.startswith("huggingface/")
        ):
            return self.TIER_FREE_HF

        # Direct API tiers (check model prefix and description)
        if model.startswith("deepseek/") or "deepseek" in desc:
            return self.TIER_DIRECT_DEEPSEEK

        if model.startswith("gemini/") or "gemini" in desc:
            return self.TIER_DIRECT_GEMINI

        if (
            model.startswith("gpt-")
            or model.startswith("o1")
            or model.startswith("o3")
            or "direct-openai" in desc
            or "openai direct" in desc
        ):
            return self.TIER_DIRECT_OPENAI

        if (
            model.startswith("claude-")
            or model.startswith("anthropic/")
            or "direct-claude" in desc
            or "claude direct" in desc
        ):
            return self.TIER_DIRECT_CLAUDE

        if model.startswith("xai/") or "direct-xai" in desc or "xai direct" in desc:
            return self.TIER_DIRECT_XAI

        # OpenRouter (premium aggregator)
        if "openrouter" in model or "premium" in desc:
            return self.TIER_PREMIUM

        # Internal Ollama
        ollama_primary = os.getenv("OLLAMA_PRIMARY_URL", "164.92.147.36:11434")
        ollama_secondary = os.getenv("OLLAMA_SECONDARY_URL", "178.128.196.3:11434")
        ollama_base = os.getenv("OLLAMA_BASE_URL", "localhost:11434")
        if (
            ollama_primary in api_base
            or ollama_secondary in api_base
            or ollama_base in api_base
            or "internal" in desc
            or "ollama" in desc
        ):
            return self.TIER_INTERNAL

        return self.TIER_PREMIUM

    def _tier_to_route(self, tier: str) -> str:
        if tier in (self.TIER_FREE_OLLAMAFREE, self.TIER_FREE_HF):
            return "free"
        if tier == self.TIER_INTERNAL:
            return "internal"
        if tier.startswith("direct-"):
            return "direct"
        return "premium"

    def _tier_to_upstream(self, tier: str) -> str:
        mapping = {
            self.TIER_FREE_OLLAMAFREE: "ollamafreeapi",
            self.TIER_FREE_HF: "hf",
            self.TIER_INTERNAL: "ollama",
            self.TIER_DIRECT_DEEPSEEK: "deepseek",
            self.TIER_DIRECT_GEMINI: "gemini",
            self.TIER_DIRECT_OPENAI: "openai",
            self.TIER_DIRECT_CLAUDE: "claude",
            self.TIER_DIRECT_XAI: "xai",
            self.TIER_PREMIUM: "openrouter",
        }
        return mapping.get(tier, "openrouter")

    def mark_hf_credits_exhausted(self, duration_seconds: int = 86400):
        self._hf_credits_exhausted_until = time.time() + duration_seconds

    def _is_hf_available(self) -> bool:
        return time.time() > self._hf_credits_exhausted_until

    def _get_tier_order(self, policy: str) -> list[str]:
        if policy == "uncensored":
            # Internal Ollama first (no censorship), then free, then direct, then premium
            return [
                self.TIER_INTERNAL,
                self.TIER_FREE_OLLAMAFREE,
                self.TIER_DIRECT_DEEPSEEK,
                self.TIER_DIRECT_XAI,
                self.TIER_FREE_HF,
                self.TIER_DIRECT_GEMINI,
                self.TIER_DIRECT_OPENAI,
                self.TIER_DIRECT_CLAUDE,
                self.TIER_PREMIUM,
            ]
        if policy == "premium":
            # Best quality first (direct APIs preferred over OpenRouter)
            return [
                *self._DIRECT_TIERS_BY_QUALITY,
                self.TIER_PREMIUM,
                self.TIER_FREE_HF,
                self.TIER_FREE_OLLAMAFREE,
                self.TIER_INTERNAL,
            ]
        if policy == "free":
            # Free only, then internal, then direct (cheapest first), then premium
            return [
                self.TIER_FREE_HF,
                self.TIER_FREE_OLLAMAFREE,
                self.TIER_INTERNAL,
                *self._DIRECT_TIERS_BY_COST,
                self.TIER_PREMIUM,
            ]
        # auto (default): FREE → INTERNAL → DIRECT (cheapest) → PREMIUM
        return [
            self.TIER_FREE_HF,
            self.TIER_FREE_OLLAMAFREE,
            self.TIER_INTERNAL,
            *self._DIRECT_TIERS_BY_COST,
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
