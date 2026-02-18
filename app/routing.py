"""
RainyModel routing logic.

Determines which upstream to use based on model alias and policy.
Routes: FREE (ollamafreeapi/HF) -> INTERNAL (Ollama) -> PREMIUM (OpenRouter)
"""

import os
import time
from typing import Any


class RainyModelRouter:
    TIER_FREE_OLLAMAFREE = "free-ollamafree"
    TIER_FREE_HF = "free-hf"
    TIER_INTERNAL = "internal"
    TIER_PREMIUM = "premium"

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

        if "ollamafreeapi" in api_base or "ollamafree" in desc:
            return self.TIER_FREE_OLLAMAFREE

        if "huggingface" in api_base or "hf" in desc or model.startswith("huggingface/"):
            return self.TIER_FREE_HF

        if "openrouter" in model or "premium" in desc:
            return self.TIER_PREMIUM

        ollama_base = os.getenv("OLLAMA_BASE_URL", "localhost:11434")
        if ollama_base in api_base or "internal" in desc or "ollama" in desc:
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

    def select_deployment(
        self, model: str, policy: str = "auto"
    ) -> dict[str, Any] | None:
        deployments = self._deployments.get(model, [])
        if not deployments:
            return None

        if policy == "uncensored":
            order = [
                self.TIER_INTERNAL,
                self.TIER_FREE_OLLAMAFREE,
                self.TIER_FREE_HF,
                self.TIER_PREMIUM,
            ]
        elif policy == "premium":
            order = [
                self.TIER_PREMIUM,
                self.TIER_FREE_OLLAMAFREE,
                self.TIER_FREE_HF,
                self.TIER_INTERNAL,
            ]
        elif policy == "free":
            order = [
                self.TIER_FREE_OLLAMAFREE,
                self.TIER_FREE_HF,
                self.TIER_INTERNAL,
                self.TIER_PREMIUM,
            ]
        else:
            order = [
                self.TIER_FREE_OLLAMAFREE,
                self.TIER_FREE_HF,
                self.TIER_INTERNAL,
                self.TIER_PREMIUM,
            ]

        for tier in order:
            if tier == self.TIER_FREE_HF and not self._is_hf_available():
                continue
            for dep in deployments:
                if dep["tier"] == tier:
                    return dep

        return deployments[0] if deployments else None
