"""Data access facade: sample data (demo) -> cache -> live MCP.

Real-mode MCP adaptation lives in mcp_adapter.py; this module only deals
with validated pydantic models so solvers never see raw payloads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

from .config import Settings
from .models import Coupon, MenuItem, Promotion, Store

_SAMPLE_PACKAGE = "mcoptimizer.sample_data"


def _load_sample(name: str) -> list[dict]:
    text = resources.files(_SAMPLE_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    return json.loads(text)


@dataclass
class MenuData:
    store: Store | None
    items: list[MenuItem] = field(default_factory=list)
    coupons: list[Coupon] = field(default_factory=list)
    promotions: list[Promotion] = field(default_factory=list)
    source: str = "demo"  # demo | cache | live


class Repository:
    def __init__(self, settings: Settings):
        self.settings = settings

    def load_stores(self) -> list[Store]:
        if self.settings.demo:
            return [Store.model_validate(d) for d in _load_sample("stores.json")]
        from . import mcp_adapter  # lazy: real mode only

        return mcp_adapter.fetch_stores(self.settings)

    def load_menu(
        self,
        store_code: str | None = None,
        be_code: str | None = None,
        order_type: int = 1,
        be_type: int = 1,
    ) -> MenuData:
        if self.settings.demo:
            stores = [Store.model_validate(d) for d in _load_sample("stores.json")]
            store = stores[0] if stores else None
            return MenuData(
                store=store,
                items=[MenuItem.model_validate(d) for d in _load_sample("menu.json")],
                coupons=[Coupon.model_validate(d) for d in _load_sample("coupons.json")],
                promotions=[Promotion.model_validate(d) for d in _load_sample("promotions.json")],
                source="demo",
            )
        from . import mcp_adapter

        return mcp_adapter.fetch_menu_data(
            self.settings,
            store_code=store_code,
            be_code=be_code,
            order_type=order_type,
            be_type=be_type,
        )

    def verify_price(self, result_lines: list[dict], **ctx) -> dict | None:
        """Ask mcd-mcp calculate-price for an authoritative quote (real mode)."""
        if self.settings.demo:
            return None
        from . import mcp_adapter

        return mcp_adapter.calculate_price(self.settings, result_lines, **ctx)
