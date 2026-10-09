"""Budget solver tests: hand-verifiable cases."""

from mcoptimizer.models import Coupon, MenuItem, Nutrition
from mcoptimizer.solvers.budget import solve_budget
from mcoptimizer.solvers.common import UtilityWeights


def make_item(item_id, price, protein=0.0, cal=0.0, category="burger"):
    return MenuItem(
        item_id=item_id,
        name=item_id,
        price_cents=price,
        category=category,
        nutrition=Nutrition(protein_g=protein, calories_kcal=cal),
    )


W = UtilityWeights(protein=1.0, calories=0.0, satiety=0.0, main_bonus=0.0, drink_bonus=0.0)


def test_zero_budget_returns_nothing():
    items = [make_item("a", 100)]
    assert solve_budget(items, [], [], budget_cents=0, weights=W) == []


def test_single_item_over_budget():
    items = [make_item("a", 1000)]
    assert solve_budget(items, [], [], budget_cents=500, weights=W) == []


def test_picks_highest_utility_within_budget():
    # a: 10 protein / 500c ; b: 30 protein / 900c ; budget 1000
    # optimal: b (30) beats a+a (20)
    items = [make_item("a", 500, protein=10), make_item("b", 900, protein=30)]
    results = solve_budget(items, [], [], budget_cents=1000, top_k=1, weights=W)
    assert len(results) == 1
    r = results[0]
    assert [(l.item.item_id, l.quantity) for l in r.lines] == [("b", 1)]
    assert r.total_cents == 900


def test_respects_quantity_cap():
    # cap = max_per_person(2) * people(1) = 2 per item
    items = [make_item("a", 100, protein=50)]
    results = solve_budget(items, [], [], budget_cents=10000, top_k=1, weights=W)
    assert sum(l.quantity for l in results[0].lines) == 2


def test_free_coupon_unit_included():
    items = [make_item("a", 500, protein=10), make_item("cone", 500, protein=3, category="dessert")]
    coupons = [Coupon(coupon_id="FREE", title="free cone", kind="free_item", item_id="cone")]
    results = solve_budget(items, coupons, [], budget_cents=500, top_k=1, weights=W)
    r = results[0]
    ids = {l.item.item_id for l in r.lines}
    assert "cone" in ids
    assert r.total_cents == 500  # cone was free


def test_discount_item_coupon_saves_money():
    items = [make_item("big", 2500, protein=26)]
    coupons = [
        Coupon(
            coupon_id="D",
            title="big special",
            kind="discount_item",
            item_id="big",
            special_price_cents=1990,
        )
    ]
    results = solve_budget(items, coupons, [], budget_cents=2500, top_k=1, weights=W)
    r = results[0]
    # one unit via coupon at 1990
    coupon_lines = [ln for ln in r.lines if ln.applied_coupon_id == "D"]
    assert coupon_lines and coupon_lines[0].unit_price_cents == 1990
    assert r.saved_cents > 0


def test_threshold_off_applied_post_hoc():
    items = [make_item("a", 1600, protein=10)]
    coupons = [
        Coupon(
            coupon_id="T",
            title="30-5",
            kind="threshold_off",
            threshold_cents=3000,
            off_cents=500,
        )
    ]
    results = solve_budget(items, coupons, [], budget_cents=3200, top_k=1, weights=W)
    r = results[0]
    # two units = 3200 >= 3000 -> minus 500
    assert sum(l.quantity for l in r.lines) == 2
    assert r.total_cents == 2700


def test_top_k_distinct_signatures():
    items = [
        make_item("a", 500, protein=10),
        make_item("b", 600, protein=11),
        make_item("c", 700, protein=12),
    ]
    results = solve_budget(items, [], [], budget_cents=1500, top_k=3, weights=W)
    sigs = {r.signature() for r in results}
    assert len(sigs) == len(results)


def test_promotion_applies_without_coupon(sample_promotions):
    items = [make_item("a", 2000, protein=10)]
    results = solve_budget(items, [], sample_promotions, budget_cents=4000, top_k=1, weights=W)
    r = results[0]
    # 2 x 2000 = 4000 >= 3900 -> 满39减6
    assert r.total_cents == 3400
    assert any("满39减6" in n for n in r.notes)


def test_sample_menu_smoke(sample_items, sample_coupons, sample_promotions):
    results = solve_budget(
        sample_items, sample_coupons, sample_promotions, budget_cents=3000, people=2, top_k=3
    )
    assert results, "sample data should yield solutions"
    for r in results:
        assert r.total_cents <= 3000
        assert r.totals is not None
