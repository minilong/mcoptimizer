"""Nutrition solver tests (PuLP ILP)."""

import pytest

from mcoptimizer.models import Coupon, MenuItem, Nutrition
from mcoptimizer.solvers.nutrition import solve_nutrition

pulp = pytest.importorskip("pulp")


def make_item(item_id, price, protein=0.0, cal=0.0, fat=0.0, category="burger"):
    return MenuItem(
        item_id=item_id,
        name=item_id,
        price_cents=price,
        category=category,
        nutrition=Nutrition(protein_g=protein, calories_kcal=cal, fat_g=fat),
    )


def test_cheapest_feasible():
    # need >= 30g protein, <= 1000 kcal
    # a: 30p/500kcal/1000c ; b: 15p/300kcal/400c -> two b = 30p/600kcal/800c cheaper
    items = [
        make_item("a", 1000, protein=30, cal=500),
        make_item("b", 400, protein=15, cal=300),
    ]
    results, _ = solve_nutrition(items, [], min_protein=30, max_calories=1000, top_k=1)
    assert results
    r = results[0]
    assert r.total_cents == 800
    assert {ln.item.item_id: ln.quantity for ln in r.lines} == {"b": 2}


def test_infeasible_returns_empty():
    items = [make_item("a", 1000, protein=10, cal=500)]
    results, _ = solve_nutrition(items, [], min_protein=1000, max_calories=100, top_k=1)
    assert results == []


def test_top_k_strictly_distinct_and_ordered():
    items = [
        make_item("a", 500, protein=20, cal=300),
        make_item("b", 600, protein=20, cal=300),
        make_item("c", 700, protein=20, cal=300),
    ]
    results, _ = solve_nutrition(items, [], min_protein=20, max_calories=1000, top_k=3)
    assert len(results) == 3
    costs = [r.total_cents for r in results]
    assert costs == sorted(costs)
    sigs = {r.signature() for r in results}
    assert len(sigs) == 3


def test_excludes_items_without_nutrition_by_default():
    with_n = make_item("a", 500, protein=25, cal=400)
    without_n = MenuItem(item_id="ghost", name="ghost", price_cents=100, category="burger")
    results, warnings = solve_nutrition(
        [with_n, without_n], [], min_protein=20, max_calories=1000, top_k=1
    )
    assert any("缺少营养数据" in w for w in warnings)
    assert all(ln.item.item_id == "a" for ln in results[0].lines)


def test_discount_coupon_reduces_cost():
    items = [make_item("big", 2500, protein=30, cal=500)]
    coupons = [
        Coupon(
            coupon_id="D",
            title="big special",
            kind="discount_item",
            item_id="big",
            special_price_cents=1990,
        )
    ]
    results, _ = solve_nutrition(items, coupons, min_protein=25, max_calories=1000, top_k=1)
    assert results[0].total_cents == 1990
    assert results[0].lines[0].applied_coupon_id == "D"


def test_sample_menu_smoke(sample_items, sample_coupons):
    results, _ = solve_nutrition(
        sample_items, sample_coupons, min_protein=40, max_calories=800, top_k=2
    )
    assert results
    for r in results:
        assert r.totals is not None
        assert r.totals.protein_g >= 40
        assert r.totals.calories_kcal <= 800
