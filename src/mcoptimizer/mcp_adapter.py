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
    item_id = str(_first_key(d, "productCode", "code", "itemId", "id") or "")
    return MenuItem(
        item_id=item_id,
        name=str(_first_key(d, "productName", "name", "product_name") or item_id),
        price_cents=_to_cents(_first_key(d, "price", "priceCents", "salePrice")),
        category=_first_key(d, "categoryName", "category", "type"),
        nutrition=nutrition_map.get(item_id),
        is_combo=bool(_first_key(d, "isCombo", "is_combo", "combo") or False),
    )


def normalize_coupon(d: dict) -> Coupon | None:
    kind_raw = str(_first_key(d, "couponType", "kind", "type") or "").lower()
    kind_map = {
        "free_item": "free_item",
        "free": "free_item",
        "discount_item": "discount_item",
        "special": "discount_item",
        "threshold_off": "threshold_off",
        "cash": "threshold_off",
        "discount_rate": "discount_rate",
        "rate": "discount_rate",
        "discount": "discount_rate",
    }
    kind = kind_map.get(kind_raw)
    if kind is None:
        return None
    return Coupon(
        coupon_id=str(_first_key(d, "couponId", "id", "coupon_id") or ""),
        title=str(_first_key(d, "title", "couponName", "name") or ""),
        kind=kind,  # type: ignore[arg-type]
        item_id=_first_key(d, "productCode", "itemId", "item_id"),
        special_price_cents=_to_cents(_first_key(d, "specialPrice", "specialPriceCents")),
        threshold_cents=_to_cents(_first_key(d, "threshold", "thresholdCents", "minSpend")),
        off_cents=_to_cents(_first_key(d, "off", "offCents", "reduceAmount")),
        rate=_first_key(d, "rate", "discountRate"),
        stackable=bool(_first_key(d, "stackable", "canStack") or False),
        valid_until=_first_key(d, "validUntil", "endTime", "expireTime"),
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


async def _fetch_stores_async(settings: Settings, lat: float, lon: float) -> list[Store]:
    async with _Caller(settings) as caller:
        payload = await caller.call("query-nearby-stores", {"latitude": lat, "longitude": lon})
    rows = _unwrap_list(payload)
    return [normalize_store(d) for d in rows]


def fetch_stores(settings: Settings, lat: float = 31.2304, lon: float = 121.4737) -> list[Store]:
    return asyncio.run(_fetch_stores_async(settings, lat, lon))


async def _fetch_menu_data_async(
    settings: Settings,
    store_code: str | None,
    be_code: str | None,
    order_type: int,
    be_type: int,
    refresh: bool = False,
) -> MenuData:
    async with _Caller(settings, refresh=refresh) as caller:
        store: Store | None = None
        if store_code is None:
            stores_payload = await caller.call(
                "query-nearby-stores", {"latitude": 31.2304, "longitude": 121.4737}
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

    nutrition_map: dict[str, Nutrition] = {}
    for d in _unwrap_list(nutrition_payload):
        iid = str(_first_key(d, "productCode", "code", "itemId", "id") or "")
        if not iid:
            continue
        nutrition_map[iid] = Nutrition(
            protein_g=float(_first_key(d, "protein", "proteinG", "protein_g") or 0),
            calories_kcal=float(_first_key(d, "calories", "kcal", "caloriesKcal") or 0),
            fat_g=float(_first_key(d, "fat", "fatG", "fat_g") or 0),
            carbs_g=float(_first_key(d, "carbs", "carbsG", "carbohydrate") or 0),
            sodium_mg=_first_key(d, "sodium", "sodiumMg"),
        )

    items = [
        normalize_item(d, nutrition_map)
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
) -> MenuData:
    return asyncio.run(_fetch_menu_data_async(settings, store_code, be_code, order_type, be_type))


def fetch_and_cache(
    settings: Settings, lat: float, lon: float, delivery: bool, refresh: bool
) -> str:
    order_type = 2 if delivery else 1
    be_type = 2 if delivery else 1
    data = asyncio.run(
        _fetch_menu_data_async(settings, None, None, order_type, be_type, refresh=refresh)
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
