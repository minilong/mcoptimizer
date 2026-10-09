"""Demo-mode end-to-end: repository loads sample data without any network."""

from mcoptimizer.config import load_settings
from mcoptimizer.repository import Repository
from mcoptimizer.solvers.budget import solve_budget
from mcoptimizer.solvers.coupon import solve_coupon


def test_demo_menu_loads():
    repo = Repository(load_settings(demo=True))
    data = repo.load_menu()
    assert data.source == "demo"
    assert len(data.items) >= 20
    assert len(data.coupons) >= 3
    assert data.store is not None
    assert all(i.price_cents > 0 for i in data.items if not i.is_combo)


def test_demo_stores_load():
    repo = Repository(load_settings(demo=True))
    stores = repo.load_stores()
    assert len(stores) >= 1
    assert stores[0].store_code.startswith("SAMPLE")


def test_demo_full_pipeline():
    repo = Repository(load_settings(demo=True))
    data = repo.load_menu()
    results = solve_budget(data.items, data.coupons, data.promotions, 3000, people=2, top_k=3)
    assert results

    by_id = {i.item_id: i for i in data.items}
    r = solve_coupon([(by_id["bigmac"], 1)], data.coupons, data.promotions)
    assert r.total_cents <= by_id["bigmac"].price_cents


def test_verify_price_is_none_in_demo():
    repo = Repository(load_settings(demo=True))
    assert repo.verify_price([]) is None
