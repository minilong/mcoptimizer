"""Coupon solver tests."""

from mcoptimizer.models import Coupon, MenuItem, Nutrition, Promotion
from mcoptimizer.solvers.coupon import solve_coupon


def make_item(item_id, price, category="burger"):
    return MenuItem(
        item_id=item_id,
        name=item_id,
        price_cents=price,
        category=category,
        nutrition=Nutrition(protein_g=10, calories_kcal=400),
    )


def test_no_coupon_plain_price():
    wishlist = [(make_item("a", 1000), 2)]
    r = solve_coupon(wishlist, [], [])
    assert r.total_cents == 2000
    assert r.saved_cents == 0


def test_free_item_applies_to_one_unit():
    wishlist = [(make_item("cone", 500, "dessert"), 2)]
    coupons = [Coupon(coupon_id="F", title="free cone", kind="free_item", item_id="cone")]
    r = solve_coupon(wishlist, coupons, [])
    assert r.total_cents == 500  # one free, one paid
    assert r.saved_cents == 500


def test_exclusive_coupons_not_stacked():
    item = make_item("big", 2500)
    coupons = [
        Coupon(
            coupon_id="A", title="30-5", kind="threshold_off", threshold_cents=2000, off_cents=500
        ),
        Coupon(
            coupon_id="B", title="30-8", kind="threshold_off", threshold_cents=2000, off_cents=800
        ),
    ]
    r = solve_coupon([(item, 1)], coupons, [])
    # both non-stackable -> only the better one (B) applies
    assert r.total_cents == 2500 - 800


def test_stackable_combines():
    item = make_item("big", 2500)
    coupons = [
        Coupon(
            coupon_id="A",
            title="30-5",
            kind="threshold_off",
            threshold_cents=2000,
            off_cents=500,
            stackable=True,
        ),
        Coupon(
            coupon_id="B",
            title="30-8",
            kind="threshold_off",
            threshold_cents=2000,
            off_cents=800,
            stackable=True,
        ),
    ]
    r = solve_coupon([(item, 1)], coupons, [])
    assert r.total_cents == 2500 - 1300


def test_threshold_not_met():
    item = make_item("small", 500)
    coupons = [
        Coupon(
            coupon_id="A", title="30-5", kind="threshold_off", threshold_cents=3000, off_cents=500
        )
    ]
    r = solve_coupon([(item, 1)], coupons, [])
    assert r.total_cents == 500


def test_promotion_only_without_coupon():
    item = make_item("big", 4000)
    promos = [Promotion(promo_id="P", title="满39减6", threshold_cents=3900, off_cents=600)]
    r_no_coupon = solve_coupon([(item, 1)], [], promos)
    assert r_no_coupon.total_cents == 3400

    coupons = [
        Coupon(
            coupon_id="A", title="30-5", kind="threshold_off", threshold_cents=3000, off_cents=500
        )
    ]
    r_coupon = solve_coupon([(item, 1)], coupons, promos)
    # solver explores both branches and keeps the cheaper one:
    # coupon-only 3500 vs no-coupon+promotion 3400 -> 3400 wins
    assert r_coupon.total_cents == 3400


def test_sample_data_wishlist(sample_items, sample_coupons, sample_promotions):
    by_id = {i.item_id: i for i in sample_items}
    wishlist = [(by_id["bigmac"], 1), (by_id["fries_m"], 1), (by_id["coke_m"], 1)]
    r = solve_coupon(wishlist, sample_coupons, sample_promotions)
    assert r.total_cents <= sum(i.price_cents * q for i, q in wishlist)
    assert r.notes, "sample coupons should produce savings notes"
