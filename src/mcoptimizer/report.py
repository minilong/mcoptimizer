"""Render OptimizationResult / ladders to the terminal (rich) or Markdown."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .models import OptimizationResult


def fmt_yuan(cents: int) -> str:
    return f"¥{cents / 100:.2f}".rstrip("0").rstrip(".") if cents % 100 else f"¥{cents // 100}"


def render_result(console: Console, result: OptimizationResult, rank: int | None = None) -> None:
    title = f"方案 {rank}" if rank else "最优方案"
    table = Table(
        title=f"{title} ｜ 应付 {fmt_yuan(result.total_cents)}"
        f"（原价 {fmt_yuan(result.original_cents)}，省 {fmt_yuan(result.saved_cents)}）"
    )
    table.add_column("餐品", style="bold")
    table.add_column("数量", justify="right")
    table.add_column("单价", justify="right")
    table.add_column("小计", justify="right")
    table.add_column("优惠", style="green")
    for line in result.lines:
        tag = "券" if line.applied_coupon_id else ""
        table.add_row(
            line.item.name,
            f"x{line.quantity}",
            fmt_yuan(line.unit_price_cents),
            fmt_yuan(line.unit_price_cents * line.quantity),
            tag,
        )
    console.print(table)

    if result.totals:
        t = result.totals
        console.print(
            Text(
                f"  营养合计：蛋白质 {t.protein_g:.0f}g ｜ 热量 {t.calories_kcal:.0f}kcal"
                f" ｜ 脂肪 {t.fat_g:.0f}g ｜ 碳水 {t.carbs_g:.0f}g",
                style="dim",
            )
        )
    for note in result.notes:
        console.print(Text(f"  · {note}", style="yellow"))
    console.print()


def render_results_markdown(results: list[OptimizationResult]) -> str:
    chunks: list[str] = []
    for idx, r in enumerate(results, 1):
        lines = [
            f"### 方案 {idx} ｜ 应付 {fmt_yuan(r.total_cents)}"
            f"（原价 {fmt_yuan(r.original_cents)}，省 {fmt_yuan(r.saved_cents)}）",
            "",
            "| 餐品 | 数量 | 单价 | 小计 |",
            "|---|---:|---:|---:|",
        ]
        for line in r.lines:
            lines.append(
                f"| {line.item.name} | x{line.quantity} | {fmt_yuan(line.unit_price_cents)}"
                f" | {fmt_yuan(line.unit_price_cents * line.quantity)} |"
            )
        if r.totals:
            t = r.totals
            lines.append("")
            lines.append(
                f"> 营养合计：蛋白质 {t.protein_g:.0f}g / 热量 {t.calories_kcal:.0f}kcal"
                f" / 脂肪 {t.fat_g:.0f}g / 碳水 {t.carbs_g:.0f}g"
            )
        for note in r.notes:
            lines.append(f"> · {note}")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)
