"""Coupon-mode solver: optimal coupon usage for a given wishlist.

DFS + branch & bound over coupon-to-item assignments:

- free_item / discount_item coupons bind to their target item (one unit);
- threshold_off / discount_rate coupons apply to the post-item subtotal;
- non-stackable coupons are mutually exclusive (default, matching most
  in-store rules);
- promotions apply only when no coupon is used (conservative default).

Modeling assumptions (documented in MCP_INTEGRATION.md): threshold is
evaluated on the subtotal BEFORE coupon discounts; authoritative pricing
should be confirmed with mcd-mcp `calculate-price`.
"""

from __future__ import annotations

from ..models import Coupon, MenuItem, OptimizationResult, OrderLine, Promotion
from .common import sum_nutrition


def _item_deal_options(
    wishlist: list[tuple[MenuItem, int]], coupons: list[Coupon]
) -> list[tuple[Coupon, MenuItem]]:
    """(coupon, item) pairs where the coupon gives a deal on a wished item."""
    wanted = {i.item_id: i for i, _ in wishlist}
    options = []
    for c in coupons:
        if c.kind in ("free_item", "discount_item") and c.item_id in wanted:
            options.append((c, wanted[c.item_id]))
    return options


def solve_coupon(
    wishlist: list[tuple[MenuItem, int]],
    coupons: list[Coupon],
    promotions: list[Promotion],
) -> OptimizationResult | None:
    if not wishlist:
        return None

    original = sum(i.price_cents * q for i, q in wishlist)
    deal_options = _item_deal_options(wishlist, coupons)
    bill_coupons = [c for c in coupons if c.kind in ("threshold_off", "discount_rate")]

    best: dict | None = None

    def evaluate(chosen_deals: list[tuple[Coupon, MenuItem]], chosen_bill: list[Coupon]) -> None:
        nonlocal best
        # effective unit price per item (coupon applies to one unit)
        deal_price: dict[str, int] = {}
        deal_coupon: dict[str, str] = {}
        for c, item in chosen_deals:
            deal_price[item.item_id] = (
                0 if c.kind == "free_item" else (c.special_price_cents or item.price_cents)
            )
            deal_coupon[item.item_id] = c.coupon_id

        lines: list[OrderLine] = []
        subtotal = 0
        for item, qty in wishlist:
            if item.item_id in deal_price and qty >= 1:
                # one unit at deal price, rest at list price
                lines.append(
                    OrderLine(
                        item=item,
                        quantity=1,
                        unit_price_cents=deal_price[item.item_id],
                        applied_coupon_id=deal_coupon[item.item_id],
                    )
                )
                subtotal += deal_price[item.item_id]
                if qty > 1:
                    lines.append(
                        OrderLine(
                            item=item,
                            quantity=qty - 1,
                            unit_price_cents=item.price_cents,
                        )
                    )
                    subtotal += item.price_cents * (qty - 1)
            else:
                lines.append(OrderLine(item=item, quantity=qty, unit_price_cents=item.price_cents))
                subtotal += item.price_cents * qty

        final = subtotal
        notes: list[str] = [f"已用「{c.title}」" for c, _ in chosen_deals]
        for c in chosen_bill:
            if c.kind == "threshold_off" and subtotal >= (c.threshold_cents or 0):
                final -= c.off_cents or 0
                notes.append(f"已用「{c.title}」，减 ¥{(c.off_cents or 0) / 100:.1f}")
            elif c.kind == "discount_rate" and subtotal >= (c.threshold_cents or 0):
                discounted = round(subtotal * (c.rate or 1.0))
                if discounted < final:
                    notes.append(f"已用「{c.title}」，减 ¥{(final - discounted) / 100:.1f}")
                    final = discounted

        coupon_used = bool(chosen_deals or chosen_bill)
        if not coupon_used:
            applicable = [p for p in promotions if subtotal >= p.threshold_cents]
            if applicable:
                promo = max(applicable, key=lambda p: p.off_cents)
                final -= promo.off_cents
                notes.append(f"触发门店活动「{promo.title}」，减 ¥{promo.off_cents / 100:.1f}")

        final = max(final, 0)
        if best is None or final < best["final"]:
            best = {"final": final, "lines": lines, "notes": notes}

    def dfs(idx: int, deals: list[tuple[Coupon, MenuItem]], bills: list[Coupon]) -> None:
        if idx == len(deal_options) + len(bill_coupons):
            evaluate(deals, bills)
            return
        # option index into combined space
        if idx < len(deal_options):
            coupon, item = deal_options[idx]
            # skip
            dfs(idx + 1, deals, bills)
            # take (non-stackable coupons are mutually exclusive across the
            # whole order; at most one deal per item)
            conflict = (not coupon.stackable) and (
                any(not c.stackable for c, _ in deals) or any(not b.stackable for b in bills)
            )
            item_taken = any(it.item_id == item.item_id for _, it in deals)
            if not conflict and not item_taken:
                dfs(idx + 1, deals + [(coupon, item)], bills)
        else:
            coupon = bill_coupons[idx - len(deal_options)]
            dfs(idx + 1, deals, bills)
            conflict = (not coupon.stackable) and (
                any(not c.stackable for c, _ in deals) or any(not b.stackable for b in bills)
            )
            if not conflict:
                dfs(idx + 1, deals, bills + [coupon])

    dfs(0, [], [])

    if best is None:  # pragma: no cover - evaluate always runs at least once
        return None

    return OptimizationResult(
        mode="coupon",
        lines=best["lines"],
        people=1,
        total_cents=best["final"],
        original_cents=original,
        saved_cents=original - best["final"],
        totals=sum_nutrition([(l.item, l.quantity) for l in best["lines"]]),
        utility=float(-best["final"]),
        notes=best["notes"],
    )
