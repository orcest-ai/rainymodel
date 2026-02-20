"""
RainyModel Analytics Engine — in-memory metrics collection and aggregation.

Tracks every request through the routing pipeline and provides real-time
performance, financial, and volume analytics for the dashboard.
"""

import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class RequestRecord:
    """Single completed (or failed) request."""

    timestamp: float
    model_alias: str  # rainymodel/auto, /chat, /code, /agent
    upstream: str  # hf, ollama, openrouter, openai, anthropic, …
    route: str  # free, internal, premium
    actual_model: str
    policy: str  # auto, premium, free, uncensored
    latency_ms: int
    success: bool
    status_code: int
    is_stream: bool
    input_tokens: int = 0
    output_tokens: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    fallback_from: Optional[str] = None


# Estimated cost per 1 M tokens  (input_rate, output_rate)  in USD.
COST_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "openai": (2.50, 10.00),
    "anthropic": (3.00, 15.00),
    "xai": (2.00, 10.00),
    "deepseek": (0.27, 1.10),
    "gemini": (0.10, 0.40),
    "openrouter": (1.00, 5.00),
    "hf": (0.0, 0.0),
    "ollama": (0.0, 0.0),
    "ollamafreeapi": (0.0, 0.0),
}


def _pctl(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    idx = min(int(len(sorted_vals) * p), len(sorted_vals) - 1)
    return sorted_vals[idx]


def _cost(upstream: str, inp: int, out: int) -> float:
    r = COST_PER_1M_TOKENS.get(upstream, (1.0, 5.0))
    return (inp * r[0] + out * r[1]) / 1_000_000


class MetricsCollector:
    """Thread-safe, bounded, in-memory metrics store."""

    def __init__(self, max_records: int = 50_000, max_logs: int = 10_000):
        self._lock = threading.Lock()
        self._records: deque[RequestRecord] = deque(maxlen=max_records)
        self._logs: deque[dict] = deque(maxlen=max_logs)
        self._start_time = time.time()

    # ── recording ──────────────────────────────────────────────

    def record(self, rec: RequestRecord) -> None:
        with self._lock:
            self._records.append(rec)

    def log(self, level: str, message: str, **extra: Any) -> None:
        with self._lock:
            self._logs.append(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "level": level,
                    "msg": message,
                    **extra,
                }
            )

    # ── snapshots (always copy under lock, compute outside) ───

    def _snap(self) -> list[RequestRecord]:
        with self._lock:
            return list(self._records)

    # ── overview ───────────────────────────────────────────────

    def get_overview(self) -> dict:
        recs = self._snap()
        uptime = int(time.time() - self._start_time)
        if not recs:
            return {
                "uptime_s": uptime,
                "total": 0,
                "ok": 0,
                "err": 0,
                "success_pct": 0,
                "avg_ms": 0,
                "med_ms": 0,
                "p95_ms": 0,
                "p99_ms": 0,
                "min_ms": 0,
                "max_ms": 0,
                "rpm": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0,
                "providers": 0,
                "stream_pct": 0,
            }
        ok = [r for r in recs if r.success]
        lats = sorted(r.latency_ms for r in recs)
        now = time.time()
        recent = sum(1 for r in recs if now - r.timestamp < 60)
        inp = sum(r.input_tokens for r in recs)
        out = sum(r.output_tokens for r in recs)
        return {
            "uptime_s": uptime,
            "total": len(recs),
            "ok": len(ok),
            "err": len(recs) - len(ok),
            "success_pct": round(len(ok) / len(recs) * 100, 2),
            "avg_ms": int(statistics.mean(lats)),
            "med_ms": int(statistics.median(lats)),
            "p95_ms": _pctl(lats, 0.95),
            "p99_ms": _pctl(lats, 0.99),
            "min_ms": lats[0],
            "max_ms": lats[-1],
            "rpm": recent,
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
            "cost_usd": round(sum(_cost(r.upstream, r.input_tokens, r.output_tokens) for r in recs), 4),
            "providers": len({r.upstream for r in recs}),
            "stream_pct": round(sum(1 for r in recs if r.is_stream) / len(recs) * 100, 1),
        }

    # ── per-provider ───────────────────────────────────────────

    def get_providers(self) -> list[dict]:
        recs = self._snap()
        groups: dict[str, list[RequestRecord]] = defaultdict(list)
        for r in recs:
            groups[r.upstream].append(r)
        out = []
        for up, rs in sorted(groups.items()):
            ok = [r for r in rs if r.success]
            lats = sorted(r.latency_ms for r in rs)
            inp = sum(r.input_tokens for r in rs)
            otp = sum(r.output_tokens for r in rs)
            out.append(
                {
                    "upstream": up,
                    "requests": len(rs),
                    "ok": len(ok),
                    "err": len(rs) - len(ok),
                    "success_pct": round(len(ok) / len(rs) * 100, 1),
                    "avg_ms": int(statistics.mean(lats)),
                    "p95_ms": _pctl(lats, 0.95),
                    "min_ms": lats[0],
                    "max_ms": lats[-1],
                    "input_tokens": inp,
                    "output_tokens": otp,
                    "cost_usd": round(_cost(up, inp, otp), 6),
                }
            )
        return out

    # ── per-model alias ────────────────────────────────────────

    def get_models(self) -> list[dict]:
        recs = self._snap()
        groups: dict[str, list[RequestRecord]] = defaultdict(list)
        for r in recs:
            groups[r.model_alias].append(r)
        out = []
        for m, rs in sorted(groups.items()):
            ok = [r for r in rs if r.success]
            lats = sorted(r.latency_ms for r in rs)
            out.append(
                {
                    "model": m,
                    "requests": len(rs),
                    "success_pct": round(len(ok) / len(rs) * 100, 1) if rs else 0,
                    "avg_ms": int(statistics.mean(lats)) if lats else 0,
                }
            )
        return out

    # ── financial ──────────────────────────────────────────────

    def get_financial(self) -> dict:
        recs = self._snap()
        if not recs:
            return {
                "total_cost_usd": 0,
                "avg_cost_per_req": 0,
                "breakdown": [],
                "tier_dist": {"free": 0, "internal": 0, "premium": 0},
                "saving_pct": 0,
            }
        groups: dict[str, list[RequestRecord]] = defaultdict(list)
        for r in recs:
            groups[r.upstream].append(r)
        breakdown = []
        total = 0.0
        for up, rs in sorted(groups.items()):
            inp = sum(r.input_tokens for r in rs)
            otp = sum(r.output_tokens for r in rs)
            c = _cost(up, inp, otp)
            total += c
            breakdown.append(
                {
                    "upstream": up,
                    "requests": len(rs),
                    "input_tokens": inp,
                    "output_tokens": otp,
                    "cost_usd": round(c, 6),
                    "cost_per_req": round(c / len(rs), 6) if rs else 0,
                }
            )
        free_n = sum(1 for r in recs if r.route == "free")
        int_n = sum(1 for r in recs if r.route == "internal")
        prem_n = sum(1 for r in recs if r.route == "premium")
        return {
            "total_cost_usd": round(total, 4),
            "avg_cost_per_req": round(total / len(recs), 6),
            "breakdown": breakdown,
            "tier_dist": {"free": free_n, "internal": int_n, "premium": prem_n},
            "saving_pct": round((free_n + int_n) / len(recs) * 100, 1) if recs else 0,
        }

    # ── timeseries ─────────────────────────────────────────────

    def get_timeseries(self, bucket_min: int = 5) -> dict:
        recs = self._snap()
        if not recs:
            return {"buckets": [], "bucket_min": bucket_min}
        sz = bucket_min * 60
        cutoff = time.time() - 86400
        filtered = [r for r in recs if r.timestamp > cutoff]
        if not filtered:
            return {"buckets": [], "bucket_min": bucket_min}
        groups: dict[int, list[RequestRecord]] = defaultdict(list)
        for r in filtered:
            groups[int(r.timestamp // sz) * sz].append(r)
        buckets = []
        for ts in sorted(groups):
            rs = groups[ts]
            ok = sum(1 for r in rs if r.success)
            lats = [r.latency_ms for r in rs]
            buckets.append(
                {
                    "t": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "reqs": len(rs),
                    "ok": ok,
                    "err": len(rs) - ok,
                    "avg_ms": int(statistics.mean(lats)) if lats else 0,
                    "tokens": sum(r.input_tokens + r.output_tokens for r in rs),
                }
            )
        return {"buckets": buckets, "bucket_min": bucket_min}

    # ── errors ─────────────────────────────────────────────────

    def get_errors(self) -> list[dict]:
        recs = self._snap()
        errs = [r for r in recs if not r.success]
        by_type: dict[str, int] = defaultdict(int)
        for r in errs:
            by_type[r.error_type or "Unknown"] += 1
        return [{"type": k, "count": v} for k, v in sorted(by_type.items(), key=lambda x: -x[1])]

    # ── policies ───────────────────────────────────────────────

    def get_policies(self) -> list[dict]:
        recs = self._snap()
        by_p: dict[str, int] = defaultdict(int)
        for r in recs:
            by_p[r.policy] += 1
        return [{"policy": k, "count": v} for k, v in sorted(by_p.items(), key=lambda x: -x[1])]

    # ── fallbacks ──────────────────────────────────────────────

    def get_fallbacks(self) -> dict:
        recs = self._snap()
        fb = [r for r in recs if r.fallback_from]
        chains: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in fb:
            chains[r.fallback_from or "?"][r.upstream] += 1
        rows = []
        for frm, tos in chains.items():
            for to, cnt in tos.items():
                rows.append({"from": frm, "to": to, "count": cnt})
        return {
            "total": len(recs),
            "fallback_count": len(fb),
            "fallback_pct": round(len(fb) / len(recs) * 100, 1) if recs else 0,
            "chains": sorted(rows, key=lambda x: -x["count"]),
        }

    # ── request log ────────────────────────────────────────────

    def get_request_log(self, limit: int = 200) -> list[dict]:
        recs = self._snap()
        out = []
        for r in recs[-limit:]:
            out.append(
                {
                    "ts": datetime.fromtimestamp(r.timestamp, tz=timezone.utc).isoformat(),
                    "alias": r.model_alias,
                    "upstream": r.upstream,
                    "route": r.route,
                    "model": r.actual_model,
                    "policy": r.policy,
                    "ms": r.latency_ms,
                    "ok": r.success,
                    "code": r.status_code,
                    "stream": r.is_stream,
                    "in_tok": r.input_tokens,
                    "out_tok": r.output_tokens,
                    "err": r.error_type,
                    "fb": r.fallback_from,
                }
            )
        out.reverse()
        return out

    # ── system log ─────────────────────────────────────────────

    def get_system_log(self, limit: int = 200, level: str | None = None) -> list[dict]:
        with self._lock:
            logs = list(self._logs)
        if level:
            logs = [l for l in logs if l.get("level") == level.upper()]
        return logs[-limit:]


# ── singleton ──────────────────────────────────────────────────
collector = MetricsCollector()
