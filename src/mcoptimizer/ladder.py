"""Value-for-money ladder: rank menu items by nutrition-per-yuan metrics."""

from __future__ import annotations

from typing import Literal

from .models import MenuItem
from .solvers.common import SATIETY_BY_CATEGORY

Metric = Literal["protein-per-yuan", "cal-per-yuan", "satiety-per-yuan"]

METRIC_LABELS = {
    "protein-per-yuan": "蛋白质/元 (g)",
    "cal-per-yuan": "热量/元 (kcal)",
    "satiety-per-yuan": "饱腹感/元",
}


def metric_value(item: MenuItem, metric: Metric) -> float | None:
    """None means 'cannot compute' (missing nutrition data)."""
    price_yuan = item.price_cents / 100
    if metric == "protein-per-yuan":
        if item.nutrition is None:
            return None
        return item.nutrition.protein_g / price_yuan if price_yuan > 0 else float("inf")
    if metric == "cal-per-yuan":
        if item.nutrition is None:
            return None
        return item.nutrition.calories_kcal / price_yuan if price_yuan > 0 else float("inf")
    satiety = SATIETY_BY_CATEGORY.get(item.category or "", 1)
    return satiety / price_yuan if price_yuan > 0 else float("inf")


def rank_items(
    items: list[MenuItem], metric: Metric, top: int = 15
) -> list[tuple[MenuItem, float | None]]:
    scored = [(item, metric_value(item, metric)) for item in items]
    scored.sort(key=lambda pair: (pair[1] is None, -(pair[1] or 0)))
    return scored[:top]


def render_markdown(rows: list[tuple[MenuItem, float | None]], metric: Metric) -> str:
    label = METRIC_LABELS[metric]
    lines = [
        f"| 排名 | 餐品 | 价格(元) | {label} |",
        "|---:|---|---:|---:|",
    ]
    for idx, (item, value) in enumerate(rows, 1):
        price = f"{item.price_cents / 100:.1f}"
        metric_str = "—" if value is None else (f"{value:.2f}" if value != float("inf") else "∞")
        lines.append(f"| {idx} | {item.name} | {price} | {metric_str} |")
    return "\n".join(lines)
