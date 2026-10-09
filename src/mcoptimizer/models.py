"""Core data models.

All prices are stored in cents (fen) as integers to avoid float errors,
matching the mcd-mcp `calculate-price` convention. Display layer converts
to yuan only at render time.

Field names loosely mirror mcd-mcp responses, but everything is Optional
where the upstream payload is not guaranteed, and extra fields are allowed
for forward compatibility.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Store(_Base):
    store_code: str
    be_code: str | None = None
    name: str = ""
    address: str | None = None
    distance_m: int | None = None
    supports_delivery: bool = False


class Nutrition(_Base):
    protein_g: float = 0.0
    calories_kcal: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    sodium_mg: float | None = None

    def __add__(self, other: Nutrition) -> Nutrition:
        return Nutrition(
            protein_g=self.protein_g + other.protein_g,
            calories_kcal=self.calories_kcal + other.calories_kcal,
            fat_g=self.fat_g + other.fat_g,
            carbs_g=self.carbs_g + other.carbs_g,
            sodium_mg=(
                None
                if self.sodium_mg is None or other.sodium_mg is None
                else self.sodium_mg + other.sodium_mg
            ),
        )

    def scale(self, factor: int) -> Nutrition:
        return Nutrition(
            protein_g=self.protein_g * factor,
            calories_kcal=self.calories_kcal * factor,
            fat_g=self.fat_g * factor,
            carbs_g=self.carbs_g * factor,
            sodium_mg=None if self.sodium_mg is None else self.sodium_mg * factor,
        )


class MenuItem(_Base):
    item_id: str
    name: str
    price_cents: int
    category: str | None = None  # burger / snack / drink / dessert / breakfast ...
    nutrition: Nutrition | None = None  # None = upstream has no data for this item
    is_combo: bool = False
    combo_components: list[str] = []
    max_per_person: int = 2  # sane bound for knapsack


class Coupon(_Base):
    coupon_id: str
    title: str
    kind: Literal["free_item", "discount_item", "threshold_off", "discount_rate"]
    # free_item:      get `item_id` free (one per coupon)
    # discount_item:  get `item_id` at `special_price_cents`
    # threshold_off:  spend `threshold_cents`, get `off_cents` off
    # discount_rate:  spend `threshold_cents`, pay `rate` of the bill
    item_id: str | None = None
    special_price_cents: int | None = None
    threshold_cents: int | None = None
    off_cents: int | None = None
    rate: float | None = None
    stackable: bool = False  # default: mutually exclusive within one order
    valid_until: str | None = None


class Promotion(_Base):
    promo_id: str
    title: str
    threshold_cents: int
    off_cents: int
    stackable_with_coupon: bool = False


class OrderLine(_Base):
    item: MenuItem
    quantity: int
    unit_price_cents: int  # effective unit price after coupon (if any)
    applied_coupon_id: str | None = None


class OptimizationResult(_Base):
    mode: Literal["budget", "nutrition", "coupon"]
    lines: list[OrderLine]
    people: int = 1
    total_cents: int
    original_cents: int
    saved_cents: int = 0
    totals: Nutrition | None = None
    utility: float = 0.0
    notes: list[str] = []

    def signature(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted((line.item.item_id, line.quantity) for line in self.lines))


class CandidateSet(_Base):
    store: Store | None = None
    results: list[OptimizationResult] = []
