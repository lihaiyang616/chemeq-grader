"""DeepSeek / OpenAI-compatible pricing helpers.

Prices are intentionally kept in one small table and are labelled with the date
they were checked.  They change; the UI shows the estimate and the raw token
counts so the teacher can verify against the provider's bill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

USD_CNY = 7.2
PRICING_NOTE = "按 2026-10 DeepSeek 官方价估算；峰时价格翻倍，以账单为准。"


@dataclass(frozen=True)
class Price:
    input_per_mtok_usd: float
    output_per_mtok_usd: float
    cache_hit_per_mtok_usd: float = 0.0


# Off-peak prices.  Peak hours are 01:00-04:00 and 06:00-10:00 UTC on weekdays.
PRICES: dict[str, Price] = {
    "deepseek-flash": Price(0.15, 0.60, 0.003),
    "deepseek-v4-flash": Price(0.15, 0.60, 0.003),
    "glm-4v-flash": Price(0.0, 0.0, 0.0),
}


def is_peak(now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    hour = now.hour
    return 1 <= hour < 4 or 6 <= hour < 10


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_hit_tokens: int = 0,
    now: datetime | None = None,
) -> float:
    price = PRICES.get(model)
    if price is None:
        return 0.0
    multiplier = 2.0 if is_peak(now) else 1.0
    miss = max(0, prompt_tokens - cache_hit_tokens)
    usd = (
        miss / 1_000_000 * price.input_per_mtok_usd
        + cache_hit_tokens / 1_000_000 * price.cache_hit_per_mtok_usd
        + completion_tokens / 1_000_000 * price.output_per_mtok_usd
    ) * multiplier
    return round(usd * USD_CNY, 6)


def cost_breakdown(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_hit_tokens: int = 0,
    now: datetime | None = None,
) -> dict[str, float | str | bool]:
    return {
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cache_hit_tokens": cache_hit_tokens,
        "peak": is_peak(now),
        "cost_cny": estimate_cost(
            model, prompt_tokens, completion_tokens, cache_hit_tokens, now
        ),
        "note": PRICING_NOTE,
    }
