"""Capacity and cost model. All unit prices and volumes are INPUTS: fill them from your
contracts and from Phase 0 measurements; nothing here is a vendor price."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TierProfile:
    share: float                 # fraction of questions routed to this tier
    llm_calls: float             # mean LLM calls per answer
    in_tokens: float             # mean input tokens per answer (all calls)
    out_tokens: float            # mean output tokens per answer
    wh_seconds: float            # mean warehouse compute seconds per answer
    cache_hit: float = 0.0       # fraction served from result cache (no warehouse cost)


@dataclass(frozen=True)
class Prices:
    usd_per_m_in: float
    usd_per_m_out: float
    usd_per_wh_second: float


def cost_per_answer(t: TierProfile, p: Prices) -> float:
    llm = t.in_tokens / 1e6 * p.usd_per_m_in + t.out_tokens / 1e6 * p.usd_per_m_out
    wh = t.wh_seconds * (1 - t.cache_hit) * p.usd_per_wh_second
    return llm + wh


def monthly(tiers: dict[str, TierProfile], prices: Prices, questions_per_month: int):
    out = {name: cost_per_answer(t, prices) * t.share * questions_per_month
           for name, t in tiers.items()}
    out["total"] = sum(out.values())
    return out


def peak_qps(questions_per_month: int, business_days: int = 21, busy_hours: float = 6,
             peak_factor: float = 3.0) -> float:
    return questions_per_month / (business_days * busy_hours * 3600) * peak_factor


def warehouse_sessions(peak: float, tiers: dict[str, TierProfile]) -> float:
    """Little's law: concurrent warehouse queries = arrival rate x mean time in warehouse."""
    mean_s = sum(t.share * t.wh_seconds * (1 - t.cache_hit) for t in tiers.values())
    return peak * mean_s
