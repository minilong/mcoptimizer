"""mcoptimizer CLI.

Commands:
  fetch      pull store/menu/coupon data via mcd-mcp into the local cache
  budget     maximize eating utility within a budget
  nutrition  cheapest order meeting nutrition constraints
  coupon     best coupon usage for a wishlist
  ladder     value-for-money ranking (protein/calories per yuan)
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console

from . import __version__
from .config import load_settings
from .ladder import METRIC_LABELS, rank_items, render_markdown
from .report import render_result, render_results_markdown
from .repository import Repository
from .solvers.budget import solve_budget
from .solvers.common import UtilityWeights
from .solvers.coupon import solve_coupon

app = typer.Typer(
    name="mcoptimizer",
    help="麦门点单最优化引擎 —— 基于麦当劳官方 MCP 真实数据的背包/ILP 求解器",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


def _check_real_mode(demo: bool) -> None:
    if demo:
        return
    settings = load_settings(demo=False)
    if not settings.has_token:
        err_console.print(
            "[red]未找到 MCD_MCP_TOKEN 环境变量。[/red]\n"
            "提示：加 [bold]--demo[/bold] 可立即用内置示例数据体验全部功能；\n"
            "真实模式请先在 https://mcp.mcd.cn 申请 token，并 "
            "`export MCD_MCP_TOKEN=...`（Windows: setx MCD_MCP_TOKEN ...）。"
        )
        raise typer.Exit(code=2)


def _repo(demo: bool) -> Repository:
    _check_real_mode(demo)
    return Repository(load_settings(demo=demo))


def _print_source(source: str) -> None:
    if source == "demo":
        err_console.print("[dim]数据源：内置示例数据（--demo）[/dim]")
    else:
        err_console.print(f"[dim]数据源：{source}[/dim]")


@app.command()
def version() -> None:
    """Print version."""
    console.print(__version__)


@app.command()
def fetch(
    city: str = typer.Option("上海", "--city", help="城市名"),
    keyword: str = typer.Option("", "--keyword", "-k", help="门店关键词（如商圈名）"),
    delivery: bool = typer.Option(False, "--delivery", help="外送场景"),
    refresh: bool = typer.Option(False, "--refresh", help="绕过缓存强制拉取"),
) -> None:
    """通过 mcd-mcp 拉取门店/菜单/券/营养数据到本地缓存。"""
    _check_real_mode(demo=False)
    from . import mcp_adapter

    summary = mcp_adapter.fetch_and_cache(
        load_settings(demo=False),
        city=city,
        keyword=keyword,
        delivery=delivery,
        refresh=refresh,
    )
    console.print(summary)


@app.command()
def budget(
    amount: float = typer.Argument(..., help="预算金额（元）"),
    people: int = typer.Option(1, "--people", "-p", help="用餐人数"),
    top: int = typer.Option(3, "--top", "-k", help="输出方案数"),
    w_protein: float = typer.Option(1.0, "--w-protein", help="蛋白质权重"),
    w_cal: float = typer.Option(1.0, "--w-cal", help="热量权重"),
    w_satiety: float = typer.Option(2.0, "--w-satiety", help="饱腹感权重"),
    demo: bool = typer.Option(False, "--demo", help="使用内置示例数据"),
    md: bool = typer.Option(False, "--md", help="输出 Markdown（便于分享）"),
    store: str | None = typer.Option(None, "--store", help="门店编码（真实模式）"),
    city: str = typer.Option("上海", "--city", help="城市名（真实模式）"),
    keyword: str = typer.Option("", "--keyword", help="门店关键词（真实模式）"),
) -> None:
    """预算内效用最大化：给定预算和人数，求最优搭配。"""
    repo = _repo(demo)
    data = repo.load_menu(store_code=store, city=city, keyword=keyword)
    _print_source(data.source)

    budget_cents = round(amount * 100)
    results = solve_budget(
        data.items,
        data.coupons,
        data.promotions,
        budget_cents=budget_cents,
        people=people,
        top_k=top,
        weights=UtilityWeights(protein=w_protein, calories=w_cal, satiety=w_satiety),
    )
    if not results:
        err_console.print("[yellow]预算内找不到任何可行组合，试试提高预算。[/yellow]")
        raise typer.Exit(code=2)

    console.print(f"[bold]预算 ¥{amount:g} ｜ {people} 人用餐[/bold]\n")
    if md:
        console.print(render_results_markdown(results))
    else:
        for idx, r in enumerate(results, 1):
            render_result(console, r, rank=idx)


@app.command()
def nutrition(
    protein: float = typer.Option(0.0, "--protein", help="蛋白质下限 (g)"),
    max_cal: float = typer.Option(10000.0, "--max-cal", help="热量上限 (kcal)"),
    max_fat: float | None = typer.Option(None, "--max-fat", help="脂肪上限 (g)"),
    people: int = typer.Option(1, "--people", "-p", help="用餐人数"),
    top: int = typer.Option(3, "--top", "-k", help="输出方案数"),
    include_unknown: bool = typer.Option(False, "--include-unknown", help="包含无营养数据的餐品"),
    demo: bool = typer.Option(False, "--demo", help="使用内置示例数据"),
    md: bool = typer.Option(False, "--md", help="输出 Markdown"),
    store: str | None = typer.Option(None, "--store", help="门店编码（真实模式）"),
    city: str = typer.Option("上海", "--city", help="城市名（真实模式）"),
    keyword: str = typer.Option("", "--keyword", help="门店关键词（真实模式）"),
) -> None:
    """营养约束下费用最小（ILP，PuLP/CBC 求解）。"""
    try:
        from .solvers.nutrition import solve_nutrition
    except ImportError:
        err_console.print("[red]需要安装 PuLP：pip install 'mcoptimizer[ilp]'[/red]")
        raise typer.Exit(code=2) from None

    repo = _repo(demo)
    data = repo.load_menu(store_code=store, city=city, keyword=keyword)
    _print_source(data.source)

    results, warnings = solve_nutrition(
        data.items,
        data.coupons,
        min_protein=protein,
        max_calories=max_cal,
        max_fat=max_fat,
        people=people,
        top_k=top,
        include_unknown=include_unknown,
    )
    for w in warnings:
        err_console.print(f"[yellow]{w}[/yellow]")
    if not results:
        err_console.print("[yellow]约束无可行解，试试放宽条件。[/yellow]")
        raise typer.Exit(code=2)

    console.print(
        f"[bold]营养约束：蛋白质 ≥ {protein:g}g ｜ 热量 ≤ {max_cal:g}kcal"
        + (f" ｜ 脂肪 ≤ {max_fat:g}g" if max_fat else "")
        + "[/bold]\n"
    )
    if md:
        console.print(render_results_markdown(results))
    else:
        for idx, r in enumerate(results, 1):
            render_result(console, r, rank=idx)


@app.command()
def coupon(
    items: str = typer.Option(
        ..., "--items", "-i", help='心愿单，如 "巨无霸x1,中薯条x2,可口可乐(中)x2"'
    ),
    demo: bool = typer.Option(False, "--demo", help="使用内置示例数据"),
    md: bool = typer.Option(False, "--md", help="输出 Markdown"),
    store: str | None = typer.Option(None, "--store", help="门店编码（真实模式）"),
    city: str = typer.Option("上海", "--city", help="城市名（真实模式）"),
    keyword: str = typer.Option("", "--keyword", help="门店关键词（真实模式）"),
) -> None:
    """心愿单的最优用券方案（DFS + 分支限界）。"""
    repo = _repo(demo)
    data = repo.load_menu(store_code=store, city=city, keyword=keyword)
    _print_source(data.source)

    by_name = {i.name: i for i in data.items}
    wishlist: list[tuple] = []
    for part in items.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "x" in part:
            name, qty_s = part.rsplit("x", 1)
            qty = int(qty_s)
        else:
            name, qty = part, 1
        item = by_name.get(name.strip())
        if item is None:
            candidates = [n for n in by_name if name.strip() in n]
            hint = f"，你是不是想要：{'、'.join(candidates[:5])}" if candidates else ""
            err_console.print(f"[red]找不到餐品「{name.strip()}」{hint}[/red]")
            raise typer.Exit(code=2)
        wishlist.append((item, qty))

    result = solve_coupon(wishlist, data.coupons, data.promotions)
    if result is None:
        err_console.print("[yellow]心愿单为空。[/yellow]")
        raise typer.Exit(code=2)

    if md:
        console.print(render_results_markdown([result]))
    else:
        render_result(console, result)
    if not demo:
        console.print("[dim]提示：最终金额以门店实际结算为准（可用 calculate-price 验价）。[/dim]")


@app.command()
def ladder(
    metric: str = typer.Option(
        "protein-per-yuan",
        "--metric",
        "-m",
        help="protein-per-yuan / cal-per-yuan / satiety-per-yuan",
    ),
    top: int = typer.Option(15, "--top", "-k", help="展示数量"),
    fmt: str = typer.Option("table", "--format", "-f", help="table / md"),
    demo: bool = typer.Option(False, "--demo", help="使用内置示例数据"),
    store: str | None = typer.Option(None, "--store", help="门店编码（真实模式）"),
    city: str = typer.Option("上海", "--city", help="城市名（真实模式）"),
    keyword: str = typer.Option("", "--keyword", help="门店关键词（真实模式）"),
) -> None:
    """性价比天梯：按每元蛋白质/热量对菜单排序。"""
    if metric not in METRIC_LABELS:
        err_console.print(f"[red]未知指标 {metric}，可选：{list(METRIC_LABELS)}[/red]")
        raise typer.Exit(code=2)

    repo = _repo(demo)
    data = repo.load_menu(store_code=store, city=city, keyword=keyword)
    _print_source(data.source)

    rows = rank_items(data.items, metric, top=top)  # type: ignore[arg-type]
    if fmt == "md":
        console.print(render_markdown(rows, metric))  # type: ignore[arg-type]
        return

    from rich.table import Table

    table = Table(title=f"麦门性价比天梯 ｜ {METRIC_LABELS[metric]}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("餐品", style="bold")
    table.add_column("价格", justify="right")
    table.add_column(METRIC_LABELS[metric], justify="right", style="green")
    for idx, (item, value) in enumerate(rows, 1):
        price = f"¥{item.price_cents / 100:g}"
        metric_str = "—" if value is None else (f"{value:.2f}" if value != float("inf") else "∞")
        table.add_row(str(idx), item.name, price, metric_str)
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(main())
