import pytest

from nl2data_ref.capacity import Prices, TierProfile, cost_per_answer, monthly, peak_qps, warehouse_sessions

TIERS = {
    "tier1": TierProfile(share=0.6, llm_calls=2, in_tokens=6_000, out_tokens=400, wh_seconds=2, cache_hit=0.3),
    "tier2": TierProfile(share=0.25, llm_calls=2, in_tokens=4_000, out_tokens=300, wh_seconds=1.5, cache_hit=0.5),
    "tier3": TierProfile(share=0.15, llm_calls=8, in_tokens=60_000, out_tokens=4_000, wh_seconds=10),
}
PRICES = Prices(usd_per_m_in=3.0, usd_per_m_out=15.0, usd_per_wh_second=0.001)


def test_cost_per_answer_formula():
    t = TIERS["tier3"]
    assert cost_per_answer(t, PRICES) == pytest.approx(0.06 * 3 + 0.004 * 15 + 10 * 0.001)


def test_monthly_total_is_sum():
    m = monthly(TIERS, PRICES, 100_000)
    assert m["total"] == pytest.approx(sum(v for k, v in m.items() if k != "total"))


def test_little_law_sessions():
    q = peak_qps(100_000)
    assert q == pytest.approx(100_000 / (21 * 6 * 3600) * 3)
    assert warehouse_sessions(q, TIERS) < 5
