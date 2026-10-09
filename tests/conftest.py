import json
from importlib import resources

import pytest

from mcoptimizer.models import Coupon, MenuItem, Promotion, Store


def _load(name):
    text = resources.files("mcoptimizer.sample_data").joinpath(name).read_text(encoding="utf-8")
    return json.loads(text)


@pytest.fixture
def sample_items() -> list[MenuItem]:
    return [MenuItem.model_validate(d) for d in _load("menu.json")]


@pytest.fixture
def sample_coupons() -> list[Coupon]:
    return [Coupon.model_validate(d) for d in _load("coupons.json")]


@pytest.fixture
def sample_promotions() -> list[Promotion]:
    return [Promotion.model_validate(d) for d in _load("promotions.json")]


@pytest.fixture
def sample_stores() -> list[Store]:
    return [Store.model_validate(d) for d in _load("stores.json")]
