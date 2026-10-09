"""Nutrition-mode solver: cheapest order meeting nutrition constraints.

ILP via PuLP/CBC (lazy-imported so budget/ladder/demo paths need no PuLP):

- x_i in {0..cap}: quantity of each item
- z_j in {0,1}:    whether discount/threshold coupon j is applied
- objective: minimize total cost including coupon savings
- threshold coupons linearized with big-M
- Top-K via integer cuts (exclude previous solution, re-solve) — strictly
  the 2nd/3rd best, unlike budget mode's approximate Top-K.

Items without nutrition data are excluded by default (a 0-protein ghost
would pollute the solution); --include-unknown re-adds them.
"""

from __future__ import annotations

from ..models import Coupon, MenuItem, OptimizationResult, OrderLine
from .common import sum_nutrition


def _solve_once(
    items: list[MenuItem],
    coupons: list[Coupon],
    min_protein: float,
    max_calories: float,
    max_fat: float | None,
    people: int,
    forbidden: list[dict[str, int]],
) -> tuple[dict[str, int], dict[str, str], int] | None:
    """Returns ({item_id: qty}, {item_id: coupon_id}, total_cents) or None."""
    import pulp  # lazy import

    prob = pulp.LpProblem("mcd_nutrition", pulp.LpMinimize)

    caps = {i.item_id: max(1, i.max_per_person * people) for i in items}
    x = {
        i.item_id: pulp.LpVariable(
            f"x_{i.item_id}", lowBound=0, upBound=caps[i.item_id], cat="Integer"
        )
        for i in items
    }
    item_by_id = {i.item_id: i for i in items}

    # coupon variables
    z: dict[str, pulp.LpVariable] = {}
    usable: list[Coupon] = []
    for c in coupons:
        if (
            c.kind == "discount_item"
            and c.item_id in item_by_id
            and c.special_price_cents is not None
        ):
            usable.append(c)
            z[c.coupon_id] = pulp.LpVariable(f"z_{c.coupon_id}", cat="Binary")
        elif c.kind == "threshold_off" and c.threshold_cents and c.off_cents:
            usable.append(c)
            z[c.coupon_id] = pulp.LpVariable(f"z_{c.coupon_id}", cat="Binary")

    # mutually exclusive coupons (non-stackable): at most one active
    exclusive = [c for c in usable if not c.stackable]
    if len(exclusive) > 1:
        prob += pulp.lpSum(z[c.coupon_id] for c in exclusive) <= 1

    subtotal = pulp.lpSum(item_by_id[iid].price_cents * x[iid] for iid in x)

    savings = []
    for c in usable:
        if c.kind == "discount_item":
            # saving applies to at most one unit of the item, and only if bought
            save_per = item_by_id[c.item_id].price_cents - c.special_price_cents
            savings.append(save_per * z[c.coupon_id])
            prob += z[c.coupon_id] <= x[c.item_id]
        else:  # threshold_off
            savings.append(c.off_cents * z[c.coupon_id])
            prob += subtotal >= c.threshold_cents * z[c.coupon_id]

    prob += subtotal - pulp.lpSum(savings), "total_cost"

    # nutrition constraints
    prob += (
        (
            pulp.lpSum(
                (item_by_id[iid].nutrition.protein_g if item_by_id[iid].nutrition else 0) * x[iid]
                for iid in x
            )
            >= min_protein
        ),
        "min_protein",
    )
    prob += (
        (
            pulp.lpSum(
                (item_by_id[iid].nutrition.calories_kcal if item_by_id[iid].nutrition else 0)
                * x[iid]
                for iid in x
            )
            <= max_calories
        ),
        "max_calories",
    )
    if max_fat is not None:
        prob += (
            (
                pulp.lpSum(
                    (item_by_id[iid].nutrition.fat_g if item_by_id[iid].nutrition else 0) * x[iid]
                    for iid in x
                )
                <= max_fat
            ),
            "max_fat",
        )

    # integer cuts from previous rounds: forbid exact previous quantity
    # vectors. For each item i with previous qty p_i, introduce binaries
    # d_i (x_i >= p_i + 1) and e_i (x_i <= p_i - 1); require at least one
    # item to differ: sum(d_i + e_i) >= 1. Exact, no valid solution lost.
    for rnd, prev in enumerate(forbidden):
        dev_up, dev_down = [], []
        for iid, xi in x.items():
            p = prev.get(iid, 0)
            cap = caps[iid]
            d = pulp.LpVariable(f"d_{rnd}_{iid}", cat="Binary")
            e = pulp.LpVariable(f"e_{rnd}_{iid}", cat="Binary")
            prob += xi >= p + 1 - (cap + 1) * (1 - d)
            prob += xi <= p - 1 + (cap + 1) * (1 - e)
            dev_up.append(d)
            dev_down.append(e)
        prob += pulp.lpSum(dev_up + dev_down) >= 1, f"cut_{rnd}"

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if status != pulp.LpStatusOptimal:
        return None

    qty = {iid: int(round(v.value() or 0)) for iid, v in x.items()}
    qty = {iid: q for iid, q in qty.items() if q > 0}
    coupon_map: dict[str, str] = {}
    for c in usable:
        if (z[c.coupon_id].value() or 0) > 0.5 and c.kind == "discount_item":
            coupon_map[c.item_id] = c.coupon_id
    total = int(round(pulp.value(prob.objective)))
    return qty, coupon_map, total


def solve_nutrition(
    items: list[MenuItem],
    coupons: list[Coupon],
    min_protein: float = 0.0,
    max_calories: float = 10_000.0,
    max_fat: float | None = None,
    people: int = 1,
    top_k: int = 3,
    include_unknown: bool = False,
) -> tuple[list[OptimizationResult], list[str]]:
    warnings: list[str] = []
    known, unknown = [], []
    for i in items:
        (known if i.nutrition is not None else unknown).append(i)
    if unknown and not include_unknown:
        warnings.append(
            f"{len(unknown)} 个餐品缺少营养数据，已从营养模式排除（--include-unknown 可强制包含）"
        )
    pool = items if include_unknown else known

    results: list[OptimizationResult] = []
    forbidden: list[dict[str, int]] = []

    for _ in range(max(1, top_k)):
        solved = _solve_once(pool, coupons, min_protein, max_calories, max_fat, people, forbidden)
        if solved is None:
            break
        qty, coupon_map, total = solved
        # expand caps-aware forbidden vector
        caps_vec = {i.item_id: qty.get(i.item_id, 0) for i in pool}
        forbidden.append(caps_vec)

        lines: list[OrderLine] = []
        for iid, q in sorted(qty.items(), key=lambda kv: -kv[1]):
            item = next(i for i in pool if i.item_id == iid)
            coupon_id = coupon_map.get(iid)
            unit_price = item.price_cents
            if coupon_id:
                cpn = next(c for c in coupons if c.coupon_id == coupon_id)
                unit_price = cpn.special_price_cents or item.price_cents
            lines.append(
                OrderLine(
                    item=item,
                    quantity=q,
                    unit_price_cents=unit_price,
                    applied_coupon_id=coupon_id,
                )
            )
        original = sum(l.item.price_cents * l.quantity for l in lines)
        notes = [f"已用「{c.title}」" for c in coupons if c.coupon_id in coupon_map.values()]
        results.append(
            OptimizationResult(
                mode="nutrition",
                lines=lines,
                people=people,
                total_cents=total,
                original_cents=original,
                saved_cents=original - total,
                totals=sum_nutrition([(l.item, l.quantity) for l in lines]),
                utility=float(-total),
                notes=notes,
            )
        )

    return results, warnings
