"""Real-mode data adapter: mcd-mcp -> validated models, with cache + retry.

Upstream schemas are normalized best-effort here (key aliases); raw payloads
can be dumped for analysis with MCOPTIMIZER_DUMP_RAW=1.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from .cache import Cache
from .config import Settings
from .models import Coupon, MenuItem, Nutrition, Store
from .repository import MenuData

_DUMP_DIR = Path("docs/mcp-samples/raw")


def _dump_raw(tool: str, payload: Any) -> None:
    if not os.environ.get("MCOPTIMIZER_DUMP_RAW"):
        return
    try:
        _DUMP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (_DUMP_DIR / f"{stamp}_{tool.replace('/', '_')}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _first_key(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _to_cents(value: Any) -> int:
    """Upstream prices may be cents (int) or yuan (float/string)."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        return round(float(value) * 100)
    except (TypeError, ValueError):
        return 0


def _unwrap_list(payload: Any, *keys: str) -> list[dict]:
    """Dig a list out of common envelope shapes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in keys or ("data", "list", "items", "result"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = _unwrap_list(v)
                if inner:
                    return inner
    return []


def parse_nutrition_text(payload: Any) -> dict[str, Nutrition]:
    """list-nutrition-foods returns data as a CSV-ish *string*:
    "[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,...}:"
    followed by rows. Keyed by product NAME (not code)."""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if not isinstance(data, str):
        return {}
    result: dict[str, Nutrition] = {}
    for line in data.splitlines():
        line = line.strip()
        if not line or line.startswith("[") or "," not in line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9 or parts[0] == "productName":
            continue
        name = parts[0]

        def num(idx: int, parts: list[str] = parts) -> float:
            try:
                return float(parts[idx])
            except (ValueError, IndexError):
                return 0.0

        try:
            sodium: float | None = float(parts[7])
        except (ValueError, IndexError):
            sodium = None
        result[name] = Nutrition(
            protein_g=num(4),
            calories_kcal=num(3),
            fat_g=num(5),
            carbs_g=num(6),
            sodium_mg=sodium,
        )
    return result


def parse_menu(payload: Any, nutrition_by_name: dict[str, Nutrition]) -> list[MenuItem]:
    """query-meals: data.categories[].meals[].code + data.meals{code: detail}."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    details = data.get("meals") or {}
    if not isinstance(details, dict):
        return []

    category_of: dict[str, str] = {}
    for cat in data.get("categories") or []:
        cat_name = cat.get("name") or ""
        for m in cat.get("meals") or []:
            code = m.get("code")
            if code:
                category_of[str(code)] = cat_name

    items: list[MenuItem] = []
    for code, d in details.items():
        if not isinstance(d, dict):
            continue
        name = str(_first_key(d, "name", "productName") or code)
        price = _to_cents(_first_key(d, "currentPrice", "price", "originalPrice"))
        if price <= 0:
            continue
        nutrition = nutrition_by_name.get(name)
        if nutrition is None:  # loose match: nutrition name is prefix of menu name
            for n_name, n in nutrition_by_name.items():
                if name.startswith(n_name) or n_name.startswith(name):
                    nutrition = n
                    break
        tags = d.get("tags") or []
        items.append(
            MenuItem(
                item_id=str(code),
                name=name,
                price_cents=price,
                category=category_of.get(str(code)),
                nutrition=nutrition,
                is_combo=any("套餐" in str(t) for t in tags),
            )
        )
    return items


def normalize_coupon(d: dict) -> Coupon | None:
    """query-store-coupons entries: {title, couponId, couponCode, tradeDateTime,
    products: [{productCode, productName}], promotionId}.

    任选/兑换类券一律建模为 free_item（作用于首个关联商品）；无关联商品的
    券目前无法可靠推断规则，跳过并在文档中声明。"""
    products = d.get("products") or []
    if not products:
        return None
    first = products[0] if isinstance(products[0], dict) else {}
    item_id = first.get("productCode")
    if not item_id:
        return None
    valid_until = None
    trade = d.get("tradeDateTime")
    if isinstance(trade, str) and "-" in trade:
        valid_until = trade.rsplit("-", 1)[-1].strip()
    return Coupon(
        coupon_id=str(d.get("couponId") or d.get("couponCode") or ""),
        title=str(d.get("title") or ""),
        kind="free_item",
        item_id=str(item_id),
        valid_until=valid_until,
    )


def normalize_store(d: dict) -> Store:
    return Store(
        store_code=str(_first_key(d, "storeCode", "store_code", "code") or ""),
        be_code=_first_key(d, "beCode", "be_code"),
        name=str(_first_key(d, "storeName", "name", "store_name") or ""),
        address=_first_key(d, "address", "addr"),
        distance_m=_first_key(d, "distance", "distanceM", "distance_m"),
        supports_delivery=bool(_first_key(d, "supportsDelivery", "delivery") or False),
    )


def normalize_item(d: dict, nutrition_map: dict[str, Nutrition]) -> MenuItem:
    """Generic single-item normalization (kept for future shapes)."""
    item_id = str(_first_key(d, "productCode", "code", "itemId", "id") or "")
    return MenuItem(
        item_id=item_id,
        name=str(_first_key(d, "productName", "name", "product_name") or item_id),
        price_cents=_to_cents(_first_key(d, "price", "priceCents", "salePrice", "currentPrice")),
        category=_first_key(d, "categoryName", "category", "type"),
        nutrition=nutrition_map.get(item_id),
        is_combo=bool(_first_key(d, "isCombo", "is_combo", "combo") or False),
    )


class _Caller:
    """One connection, cache-aware calls with retry + stale fallback."""

    def __init__(self, settings: Settings, refresh: bool = False):
        self.settings = settings
        self.cache = Cache(settings.cache_dir, enabled=not settings.demo)
        self.refresh = refresh
        self.client = None

    async def __aenter__(self):
        from .mcp_client import McdMcpClient

        assert self.settings.token, "MCD_MCP_TOKEN missing"
        self.client = McdMcpClient(self.settings.mcp_url, self.settings.token)
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *exc):
        if self.client is not None:
            await self.client.__aexit__(*exc)

    async def call(self, tool: str, args: dict) -> Any:
        if not self.refresh:
            cached = self.cache.get(tool, args)
            if cached is not None:
                return cached
        last_err: Exception | None = None
        for delay in (0, 1, 3):
            if delay:
                await asyncio.sleep(delay)
            try:
                assert self.client is not None
                data = await self.client.call(tool, args)
                _dump_raw(tool, {"args": args, "payload": data})
                self.cache.put(tool, args, data)
                return data
            except Exception as err:  # noqa: BLE001 - degrade to stale cache
                last_err = err
        stale = self.cache.get_stale(tool, args)
        if stale is not None:
            return stale
        raise RuntimeError(f"mcd-mcp '{tool}' 调用失败：{last_err}") from last_err


async def _fetch_stores_async(settings: Settings, city: str, keyword: str) -> list[Store]:
    async with _Caller(settings) as caller:
        payload = await caller.call(
            "query-nearby-stores",
            {"beType": 1, "searchType": 2, "city": city, "keyword": keyword},
        )
    rows = _unwrap_list(payload)
    return [normalize_store(d) for d in rows]


def fetch_stores(settings: Settings, city: str = "上海", keyword: str = "") -> list[Store]:
    return asyncio.run(_fetch_stores_async(settings, city, keyword))


async def _fetch_menu_data_async(
    settings: Settings,
    store_code: str | None,
    be_code: str | None,
    order_type: int,
    be_type: int,
    refresh: bool = False,
    city: str = "上海",
    keyword: str = "",
) -> MenuData:
    async with _Caller(settings, refresh=refresh) as caller:
        store: Store | None = None
        if store_code is None:
            stores_payload = await caller.call(
                "query-nearby-stores",
                {"beType": 1, "searchType": 2, "city": city, "keyword": keyword},
            )
            stores = [normalize_store(d) for d in _unwrap_list(stores_payload)]
            if not stores:
                raise RuntimeError("附近没有找到麦当劳门店")
            store = stores[0]
            store_code = store.store_code
            be_code = store.be_code
        else:
            store = Store(store_code=store_code, be_code=be_code)

        args: dict[str, Any] = {"storeCode": store_code, "orderType": order_type, "beType": be_type}
        if be_code:
            args["beCode"] = be_code

        menu_payload = await caller.call("query-meals", args)
        coupons_payload = await caller.call("query-store-coupons", args)
        nutrition_payload = await caller.call("list-nutrition-foods", {})

    nutrition_by_name = parse_nutrition_text(nutrition_payload)
    items = parse_menu(menu_payload, nutrition_by_name)
    # fallback for envelope shapes the dedicated parser doesn't know
    if not items:
        items = [
            normalize_item(d, {})
            for d in _unwrap_list(menu_payload, "data", "list", "items", "meals")
        ]
        items = [i for i in items if i.item_id and i.price_cents > 0]

    coupons = []
    for d in _unwrap_list(coupons_payload):
        c = normalize_coupon(d)
        if c is not None:
            coupons.append(c)

    return MenuData(store=store, items=items, coupons=coupons, promotions=[], source="live")


def fetch_menu_data(
    settings: Settings,
    store_code: str | None = None,
    be_code: str | None = None,
    order_type: int = 1,
    be_type: int = 1,
    city: str = "上海",
    keyword: str = "",
) -> MenuData:
    return asyncio.run(
        _fetch_menu_data_async(
            settings, store_code, be_code, order_type, be_type, city=city, keyword=keyword
        )
    )


def fetch_and_cache(
    settings: Settings, city: str, keyword: str, delivery: bool, refresh: bool
) -> str:
    order_type = 2 if delivery else 1
    be_type = 2 if delivery else 1
    data = asyncio.run(
        _fetch_menu_data_async(
            settings, None, None, order_type, be_type, refresh=refresh, city=city, keyword=keyword
        )
    )
    store_label = f"{data.store.name} ({data.store.store_code})" if data.store else "?"
    lines = [
        "拉取完成：",
        f"  门店：{store_label}",
        f"  餐品：{len(data.items)} 个",
        f"  优惠券：{len(data.coupons)} 张",
        f"  缓存目录：{settings.cache_dir}",
    ]
    return "\n".join(lines)


def calculate_price(settings: Settings, lines: list[dict], **ctx) -> dict | None:
    """Authoritative price check via mcd-mcp calculate-price."""

    async def _run() -> dict:
        async with _Caller(settings) as caller:
            args = {
                "storeCode": ctx.get("store_code"),
                "orderType": ctx.get("order_type", 1),
                "beType": ctx.get("be_type", 1),
                "items": lines,
            }
            if ctx.get("be_code"):
                args["beCode"] = ctx["be_code"]
            return await caller.call("calculate-price", args)

    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001 - verification is best-effort
        return None
