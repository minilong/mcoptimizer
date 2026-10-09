"""Ladder tests."""

from mcoptimizer.ladder import rank_items, render_markdown
from mcoptimizer.models import MenuItem, Nutrition


def make_item(item_id, price, protein=None, category="burger"):
    nutrition = None if protein is None else Nutrition(protein_g=protein, calories_kcal=300)
    return MenuItem(
        item_id=item_id, name=item_id, price_cents=price, category=category, nutrition=nutrition
    )


def test_protein_per_yuan_ranking():
    a = make_item("a", 1000, protein=10)  # 1.0 g/yuan
    b = make_item("b", 1000, protein=25)  # 2.5
    c = make_item("c", 2500, protein=50)  # 2.0
    rows = rank_items([a, b, c], "protein-per-yuan", top=3)
    assert [i.item_id for i, _ in rows] == ["b", "c", "a"]


def test_missing_nutrition_sorted_last():
    a = make_item("a", 1000, protein=10)
    ghost = make_item("ghost", 100, protein=None)
    rows = rank_items([ghost, a], "protein-per-yuan", top=2)
    assert rows[0][0].item_id == "a"
    assert rows[1][1] is None


def test_zero_price_is_infinite_value():
    free = make_item("free", 0, protein=5)
    paid = make_item("paid", 100, protein=50)
    rows = rank_items([paid, free], "protein-per-yuan", top=2)
    assert rows[0][0].item_id == "free"
    assert rows[0][1] == float("inf")


def test_markdown_render():
    a = make_item("a", 1000, protein=10)
    md = render_markdown(rank_items([a], "protein-per-yuan", top=1), "protein-per-yuan")
    assert "| 1 | a | 10.0 | 1.00 |" in md


def test_sample_menu_ladder(sample_items):
    rows = rank_items(sample_items, "protein-per-yuan", top=5)
    assert len(rows) == 5
    values = [v for _, v in rows]
    assert values == sorted(values, reverse=True)
