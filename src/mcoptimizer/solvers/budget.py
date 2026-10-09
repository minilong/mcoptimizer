"""Budget-mode solver: maximize utility within a budget.

Approach (see docs/algorithms.md):
1. Enumerate feasible coupon subsets (stackable free + at most one exclusive).
2. free_item / discount_item coupons become special-priced unit slots.
3. 0/1 knapsack DP over cents: dp[c] = best utility with exact spend c.
4. threshold_off / discount_rate coupons and promotions are applied as
   post-processing on the winning combo (documented approximation: this can
   miss "buy more to reach the threshold" solutions, but keeps the DP
   substructure clean and explainable).
5. Top-K: re-run with the previous winner's top-utility item capped one
   unit lower to force diversity (approximate, not strictly k-th best).
"""

from __future__ import annotations

from ..models import (
    Coupon,
    MenuItem,
    OptimizationResult,
    OrderLine,
    Promotion,
)
from .common import (
    PricedUnit,
    UtilityWeights,
    build_units,
    enumerate_coupon_subsets,
    sum_nutrition,
)


def _knapsack(units: list[PricedUnit], budget_cents: int) -> tuple[float, list[PricedUnit]]:
    """0/1 knapsack over integer cents. Returns (utility, chosen units).

    Free units (price 0) are always taken. All prices are scaled down by
    their GCD with the budget to shrink the DP table (menu prices are
    typically multiples of 10 cents).
    """
    from functools import reduce
    from math import gcd

    free_units = [u for u in units if u.price_cents == 0]
    priced = [u for u in units if u.price_cents > 0]
    free_utility = sum(u.utility for u in free_units)

    if not priced:
        return free_utility, list(free_units)

    scale = reduce(gcd, (u.price_cents for u in priced), budget_cents)
    scale = max(scale, 1)
    cap = budget_cents // scale

    NEG = float("-inf")
    dp = [NEG] * (cap + 1)
    dp[0] = 0.0
    # parent[c] = (prev_c, unit_index) for trace-back
    parent: list[tuple[int, int] | None] = [None] * (cap + 1)

    for idx, unit in enumerate(priced):
        p = unit.price_cents // scale
        u = unit.utility
        if p > cap:
            continue
        for c in range(cap, p - 1, -1):
            prev = dp[c - p]
            if prev == NEG:
                continue
            cand = prev + u
            if cand > dp[c]:
                dp[c] = cand
                parent[c] = (c - p, idx)

    best_c = max(range(cap + 1), key=lambda c: dp[c])
    if dp[best_c] == NEG:
        return free_utility, list(free_units)
    chosen: list[PricedUnit] = list(free_units)
    c = best_c
    while c > 0 and parent[c] is not None:
        prev_c, idx = parent[c]  # type: ignore[misc]
        chosen.append(priced[idx])
        c = prev_c
    return dp[best_c] + free_utility, chosen


def _apply_post_discounts(
    subtotal_cents: int,
    coupon_subset: tuple[Coupon, ...],
    promotions: list[Promotion],
    coupon_used: bool,
) -> tuple[int, list[str]]:
    """Apply threshold_off / discount_rate coupons and promotions.
    Returns (final_cents, notes)."""
    notes: list[str] = []
    final = subtotal_cents
    for coupon in coupon_subset:
        if coupon.kind == "threshold_off" and coupon.threshold_cents is not None:
            if subtotal_cents >= coupon.threshold_cents:
                final -= coupon.off_cents or 0
                notes.append(f"已用「{coupon.title}」，减 ¥{(coupon.off_cents or 0) / 100:.1f}")
        elif coupon.kind == "discount_rate" and coupon.threshold_cents is not None:
            if subtotal_cents >= coupon.threshold_cents:
                discounted = round(subtotal_cents * (coupon.rate or 1.0))
                notes.append(
                    f"已用「{coupon.title}」，减 ¥{(subtotal_cents - discounted) / 100:.1f}"
                )
                final = min(final, discounted)
    # promotions: pick the single best applicable one, only when no coupon used
    if not coupon_used:
        applicable = [p for p in promotions if subtotal_cents >= p.threshold_cents]
        if applicable:
            best = max(applicable, key=lambda p: p.off_cents)
            final -= best.off_cents
            notes.append(f"触发门店活动「{best.title}」，减 ¥{best.off_cents / 100:.1f}")
    return max(final, 0), notes


def _build_result(
    chosen: list[PricedUnit],
    coupon_subset: tuple[Coupon, ...],
    promotions: list[Promotion],
    people: int,
    utility: float,
) -> OptimizationResult:
    # aggregate units into lines
    agg: dict[tuple[str, str | None], OrderLine] = {}
    for unit in chosen:
        key = (unit.item.item_id, unit.coupon_id)
        if key in agg:
            agg[key].quantity += 1
        else:
            agg[key] = OrderLine(
                item=unit.item,
                quantity=1,
                unit_price_cents=unit.price_cents,
                applied_coupon_id=unit.coupon_id,
            )
    lines = sorted(agg.values(), key=lambda ln: -ln.unit_price_cents * ln.quantity)
    subtotal = sum(l.unit_price_cents * l.quantity for l in lines)
    original = sum(l.item.price_cents * l.quantity for l in lines)

    coupon_used = bool(coupon_subset)
    final, notes = _apply_post_discounts(subtotal, coupon_subset, promotions, coupon_used)

    item_coupon_notes = [
        f"已用「{c.title}」"
        for c in coupon_subset
        if c.kind in ("free_item", "discount_item")
        and any(l.applied_coupon_id == c.coupon_id for l in lines)
    ]
    notes = item_coupon_notes + notes

    totals = sum_nutrition([(l.item, l.quantity) for l in lines])
    saved = original - final
    return OptimizationResult(
        mode="budget",
        lines=lines,
        people=people,
        total_cents=final,
        original_cents=original,
        saved_cents=saved,
        totals=totals,
        utility=utility,
        notes=notes,
    )


def solve_budget(
    items: list[MenuItem],
    coupons: list[Coupon],
    promotions: list[Promotion],
    budget_cents: int,
    people: int = 1,
    top_k: int = 3,
    weights: UtilityWeights | None = None,
) -> list[OptimizationResult]:
    weights = weights or UtilityWeights()
    subsets = enumerate_coupon_subsets(coupons)

    def best_once(qty_cap_override: dict[str, int] | None) -> OptimizationResult | None:
        best: OptimizationResult | None = None
        for subset in subsets:
            units = build_units(items, subset, people, weights, qty_cap_override)
            utility, chosen = _knapsack(units, budget_cents)
            if not chosen:
                continue
            result = _build_result(chosen, subset, promotions, people, utility)
            if best is None or (result.utility, -result.total_cents) > (
                best.utility,
                -best.total_cents,
            ):
                best = result
        return best

    results: list[OptimizationResult] = []
    seen: set[tuple[tuple[str, int], ...]] = set()
    cap_override: dict[str, int] = {}

    for _ in range(max(1, top_k)):
        candidate = best_once(cap_override)
        if candidate is None:
            break
        sig = candidate.signature()
        if sig not in seen:
            seen.add(sig)
            results.append(candidate)
        # force diversity next round: cap the highest-utility line one lower
        top_line = max(candidate.lines, key=lambda ln: ln.quantity)
        cap_override[top_line.item.item_id] = top_line.quantity - 1
        if cap_override[top_line.item.item_id] < 0:
            break

    return results
