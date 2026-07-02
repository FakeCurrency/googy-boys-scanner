"""Narration templates — the complete (state x direction) set.

Guardrails (spec Section 6, non-negotiable):
- Deterministic template engine. Slots are filled ONLY by computed fields —
  the engine is structurally incapable of asserting anything the data
  doesn't support. No LLM/freestyle generation anywhere in the scan path.
- Observational voice. No advice verbs (buy/sell/should). Australian English.
- Zones are always spoken as bands, never single prices.
- {stats} stays EMPTY until the backtest harness (M4) produces real numbers.
- Every narration ends with the DISCLAIMER line.
"""

DISCLAIMER = "Analysis only — not financial advice."

# Keys: (state, direction). direction: "bullish" | "bearish".
TEMPLATES = {
    ("TRAP_SET", "bullish"): (
        "{ticker} has spent {bars_in_box} sessions inside a {box_height_pct}% range. "
        "Equal lows are resting at {cluster_low}–{cluster_high} — that's where the "
        "stops are sitting. Nothing to do yet: the setup only begins if that area "
        "is swept and price closes back above it.{stats}"
    ),
    ("TRAP_SET", "bearish"): (
        "{ticker} has spent {bars_in_box} sessions inside a {box_height_pct}% range. "
        "Equal highs are resting at {cluster_low}–{cluster_high} — that's where the "
        "stops are sitting. Nothing to do yet: the setup only begins if that area "
        "is swept and price closes back below it.{stats}"
    ),
    ("SWEPT", "bullish"): (
        "{ticker} ran the {demand_low}–{demand_high} lows on {sweep_date} and closed "
        "back inside the range. The trap has been sprung. The market now has "
        "{bars_remaining} sessions to prove it with a displacement candle — range at "
        "least {tr_mult}× normal, small lower wick, close near its high. "
        "No displacement, no setup.{stats}"
    ),
    ("SWEPT", "bearish"): (
        "{ticker} ran the {demand_low}–{demand_high} highs on {sweep_date} and closed "
        "back inside the range. The trap has been sprung. The market now has "
        "{bars_remaining} sessions to prove it with a displacement candle — range at "
        "least {tr_mult}× normal, small upper wick, close near its low. "
        "No displacement, no setup.{stats}"
    ),
    ("DISPLACED", "bullish"): (
        "{ticker} printed a displacement candle today, {displacement_date} — "
        "oversized range with a close near its high — after sweeping the "
        "{demand_low}–{demand_high} lows. First draw is the {t1_low}–{t1_high} zone "
        "({t1_sources}). The continuation thesis stays valid while pullbacks hold "
        "above the {inv_soft_low}–{inv_soft_high} area; structural invalidation only "
        "on a daily close below {inv_hard_floor}.{stats}"
    ),
    ("DISPLACED", "bearish"): (
        "{ticker} printed a displacement candle today, {displacement_date} — "
        "oversized range with a close near its low — after sweeping the "
        "{demand_low}–{demand_high} highs. First draw is the {t1_low}–{t1_high} zone "
        "({t1_sources}). The continuation thesis stays valid while bounces hold "
        "below the {inv_soft_low}–{inv_soft_high} area; structural invalidation only "
        "on a daily close above {inv_hard_ceiling}.{stats}"
    ),
    ("RUNNING", "bullish"): (
        "Displacement confirmed on {displacement_date}. First draw is the "
        "{t1_low}–{t1_high} zone ({t1_sources}){t2_clause}. The continuation thesis "
        "stays valid while pullbacks hold above the {inv_soft_low}–{inv_soft_high} "
        "area — one touch of that zone and this becomes a rotation candidate "
        "instead. Structural invalidation only on a daily close below "
        "{inv_hard_floor}.{stats}"
    ),
    ("RUNNING", "bearish"): (
        "Displacement confirmed on {displacement_date}. First draw is the "
        "{t1_low}–{t1_high} zone ({t1_sources}){t2_clause}. The continuation thesis "
        "stays valid while bounces hold below the {inv_soft_low}–{inv_soft_high} "
        "area — one touch of that zone and this becomes a rotation candidate "
        "instead. Structural invalidation only on a daily close above "
        "{inv_hard_ceiling}.{stats}"
    ),
    ("STALLED", "bullish"): (
        "{ticker} touched the 50% area at {inv_soft_low}–{inv_soft_high}. The "
        "expansion thesis is finished — this is no longer a continuation setup. "
        "Structure is still intact above {inv_hard_floor}, so it moves to the "
        "rotation watchlist where deep-retracement logic applies.{stats}"
    ),
    ("STALLED", "bearish"): (
        "{ticker} touched the 50% area at {inv_soft_low}–{inv_soft_high}. The "
        "expansion thesis is finished — this is no longer a continuation setup. "
        "Structure is still intact below {inv_hard_ceiling}, so it moves to the "
        "rotation watchlist where deep-retracement logic applies.{stats}"
    ),
    ("COMPLETE", "bullish"): (
        "{ticker} closed through the far edge of its final target zone "
        "({t_final_low}–{t_final_high}). Every mapped objective from the "
        "{sweep_date} sweep has now been consumed — the cycle that began with that "
        "manipulation leg is complete, and the ticker returns to neutral until a "
        "new range forms.{stats}"
    ),
    ("COMPLETE", "bearish"): (
        "{ticker} closed through the far edge of its final target zone "
        "({t_final_low}–{t_final_high}). Every mapped objective from the "
        "{sweep_date} sweep has now been consumed — the cycle that began with that "
        "manipulation leg is complete, and the ticker returns to neutral until a "
        "new range forms.{stats}"
    ),
    ("DEAD", "bullish"): (
        "{ticker} closed below {inv_hard_floor}, through the floor of the "
        "{inv_hard_low}–{inv_hard_high} structural invalidation zone. The swept low "
        "did not hold, so the setup is void — wicks into that zone were tests, but "
        "a daily close through it is the kill rule. Back to neutral.{stats}"
    ),
    ("DEAD", "bearish"): (
        "{ticker} closed above {inv_hard_ceiling}, through the ceiling of the "
        "{inv_hard_low}–{inv_hard_high} structural invalidation zone. The swept high "
        "did not hold, so the setup is void — wicks into that zone were tests, but "
        "a daily close through it is the kill rule. Back to neutral.{stats}"
    ),
}

# Plain-English names for zone sources (used in "{t1_sources}")
SOURCE_NAMES = {
    "box_high": "the top of the range",
    "box_low": "the bottom of the range",
    "equal_highs": "a shelf of equal highs",
    "equal_lows": "a shelf of equal lows",
    "prior_high": "a prior swing high",
    "prior_low": "a prior swing low",
    "yearly_open": "the yearly open",
    "quarterly_open": "the quarterly open",
    "monthly_open": "the monthly open",
    "prior_yearly_close": "the prior yearly close",
    "fib_ext_10": "the 1.0–1.272 extension of the leg",
    "fib_ext_1618": "the 1.618–2.0 extension of the leg",
    "sweep_wick": "the manipulation wick",
}
