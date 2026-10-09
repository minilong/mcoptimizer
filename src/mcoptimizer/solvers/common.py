"""Shared helpers for solvers: utility function, coupon subset enumeration."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from ..models import Coupon, MenuItem, Nutrition

SATIETY_BY_CATEGORY = {
    "combo": 9,
    "burger": 5,
    "breakfast": 4,
    "snack": 3,
    "dessert": 2,
    "drink": 1,
}


@dataclass
class UtilityWeights:
    protein: float = 1.0
    calories: float = 1.0
    satiety: float = 2.0
    main_bonus: float = 3.0  # per-person bonus for first "main" item
    drink_bonus: float = 1.0  # per-person bonus for first drink


def item_utility(item: MenuItem, w: UtilityWeights) -> float:
    protein = item.nutrition.protein_g if item.nutrition else 0.0
    cal = item.nutrition.calories_kcal if item.nutrition else 0.0
    satiety = SATIETY_BY_CATEGORY.get(item.category or "", 1)
    return w.protein * protein + w.calories * min(cal, 600) / 100 + w.satiety * satiety


def is_main(item: MenuItem) -> bool:
    return (item.category or "") in ("burger", "combo", "breakfast")


def is_drink(item: MenuItem) -> bool:
    return (item.category or "") == "drink"


def enumerate_coupon_subsets(coupons: list[Coupon]) -> list[tuple[Coupon, ...]]:
    """Feasible coupon subsets: stackable coupons combine freely;
    non-stackable ones are mutually exclusive (at most one per order)."""
    stackable = [c for c in coupons if c.stackable]
    exclusive = [c for c in coupons if not c.stackable]

    stackable_subsets: list[tuple[Coupon, ...]] = []
    for r in range(len(stackable) + 1):
        stackable_subsets.extend(combinations(stackable, r))

    results: list[tuple[Coupon, ...]] = []
    for base in stackable_subsets:
        results.append(base)  # no exclusive coupon
        for exc in exclusive:
            results.append(base + (exc,))
    return results


def sum_nutrition(lines: list[tuple[MenuItem, int]]) -> Nutrition | None:
    total: Nutrition | None = None
    for item, qty in lines:
        if item.nutrition is None:
            continue
        contrib = item.nutrition.scale(qty)
        total = contrib if total is None else total + contrib
    return total


@dataclass
class PricedUnit:
    """One purchasable unit slot for the knapsack DP."""

    item: MenuItem
    price_cents: int
    utility: float
    coupon_id: str | None = None  # set when this unit comes from a coupon


def build_units(
    items: list[MenuItem],
    coupon_subset: tuple[Coupon, ...],
    people: int,
    weights: UtilityWeights,
    qty_cap_override: dict[str, int] | None = None,
) -> list[PricedUnit]:
    """Expand menu into 0/1 unit slots; coupon item-deals become special units.

    - Regular units: qty cap = item.max_per_person * people (override-able).
    - free_item coupon -> one unit at price 0.
    - discount_item coupon -> one unit at special price.
    - First `people` units of each main-category item get a main bonus;
      first `people` units of each drink get a drink bonus (approximates
      "everyone gets a main + a drink" without breaking DP additivity).
    """
    units: list[PricedUnit] = []
    caps = qty_cap_override or {}
    for item in items:
        cap = caps.get(item.item_id, item.max_per_person * people)
        cap = max(0, min(cap, item.max_per_person * people))
        base_u = item_utility(item, weights)
        for n in range(cap):
            u = base_u
            if is_main(item) and n < people:
                u += weights.main_bonus
            if is_drink(item) and n < people:
                u += weights.drink_bonus
            units.append(PricedUnit(item=item, price_cents=item.price_cents, utility=u))
    for coupon in coupon_subset:
        if coupon.kind in ("free_item", "discount_item") and coupon.item_id:
            target = next((i for i in items if i.item_id == coupon.item_id), None)
            if target is None:
                continue
            price = (
                0
                if coupon.kind == "free_item"
                else (coupon.special_price_cents or target.price_cents)
            )
            units.append(
                PricedUnit(
                    item=target,
                    price_cents=price,
                    utility=item_utility(target, weights),
                    coupon_id=coupon.coupon_id,
                )
            )
    return units
