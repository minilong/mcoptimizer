"""Generate docs/demo-output.svg: a recorded rich render of the demo commands.

Usage: python scripts/make_demo_image.py
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from mcoptimizer.config import load_settings
from mcoptimizer.ladder import rank_items
from mcoptimizer.report import render_result
from mcoptimizer.repository import Repository
from mcoptimizer.solvers.budget import solve_budget

OUT = Path(__file__).resolve().parent.parent / "docs" / "demo-output.svg"

console = Console(record=True, width=88)

repo = Repository(load_settings(demo=True))
data = repo.load_menu()

console.print("[bold cyan]$ mcoptimizer budget 30 --people 2 --demo[/bold cyan]\n")
results = solve_budget(data.items, data.coupons, data.promotions, 3000, people=2, top_k=2)
for idx, r in enumerate(results, 1):
    render_result(console, r, rank=idx)

console.print("[bold cyan]$ mcoptimizer ladder --demo --top 8[/bold cyan]\n")
from rich.table import Table  # noqa: E402

rows = rank_items(data.items, "protein-per-yuan", top=8)
table = Table(title="麦门性价比天梯 ｜ 蛋白质/元 (g)")
table.add_column("#", justify="right", style="dim")
table.add_column("餐品", style="bold")
table.add_column("价格", justify="right")
table.add_column("蛋白质/元 (g)", justify="right", style="green")
for idx, (item, value) in enumerate(rows, 1):
    table.add_row(str(idx), item.name, f"¥{item.price_cents / 100:g}", f"{value:.2f}")
console.print(table)

console.save_svg(str(OUT), title="mcoptimizer demo")
print(f"saved -> {OUT}")
