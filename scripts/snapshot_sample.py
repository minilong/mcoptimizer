"""Snapshot live mcd-mcp data into sample_data/ (sanitized).

Requires MCD_MCP_TOKEN. Replaces store codes with SAMPLE prefixes so no real
store identifiers are committed.

Usage: python scripts/snapshot_sample.py
"""

from __future__ import annotations

import json
from pathlib import Path

from mcoptimizer.config import load_settings
from mcoptimizer.mcp_adapter import fetch_menu_data, fetch_stores

OUT = Path(__file__).resolve().parent.parent / "src" / "mcoptimizer" / "sample_data"


def dump(name: str, rows: list[dict]) -> None:
    path = OUT / name
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path} ({len(rows)} rows)")


def main() -> None:
    settings = load_settings(demo=False)
    assert settings.has_token, "MCD_MCP_TOKEN required"

    stores = fetch_stores(settings)
    for idx, s in enumerate(stores, 1):
        s.store_code = f"SAMPLE{idx:03d}"
        s.be_code = f"SAMPLE-BE-{idx:03d}"
        s.name = f"麦当劳(演示门店{idx})"
        s.address = None
    dump("stores.json", [s.model_dump() for s in stores])

    data = fetch_menu_data(settings)
    dump("menu.json", [i.model_dump() for i in data.items])
    dump("coupons.json", [c.model_dump() for c in data.coupons])
    dump("promotions.json", [p.model_dump() for p in data.promotions])


if __name__ == "__main__":
    main()
