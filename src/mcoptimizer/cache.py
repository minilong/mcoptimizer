"""JSON file cache for MCP payloads.

Key format: {tool}:{sha1(canonical args)[:12]}.json
Each entry stores {"fetched_at": epoch, "ttl": seconds, "data": ...}.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

# per-tool TTLs (seconds)
TTL_BY_TOOL = {
    "query-nearby-stores": 24 * 3600,
    "delivery-query-stores": 24 * 3600,
    "query-meals": 3600,
    "query-meal-detail": 3600,
    "query-store-coupons": 3600,
    "query-my-coupons": 3600,
    "query-promotions": 3600,
    "list-nutrition-foods": 7 * 24 * 3600,
}
DEFAULT_TTL = 3600


class Cache:
    def __init__(self, root: Path, enabled: bool = True):
        self.root = root
        self.enabled = enabled
        if enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, tool: str, args: dict[str, Any]) -> Path:
        canonical = json.dumps(args, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]
        safe_tool = tool.replace("/", "_")
        return self.root / f"{safe_tool}:{digest}.json"

    def get(self, tool: str, args: dict[str, Any]) -> Any | None:
        if not self.enabled:
            return None
        path = self._path(tool, args)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        ttl = entry.get("ttl", DEFAULT_TTL)
        if time.time() - entry.get("fetched_at", 0) > ttl:
            return None
        return entry.get("data")

    def get_stale(self, tool: str, args: dict[str, Any]) -> Any | None:
        """Return cached data regardless of TTL (fallback when MCP is down)."""
        if not self.enabled:
            return None
        path = self._path(tool, args)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("data")
        except (json.JSONDecodeError, OSError):
            return None

    def put(self, tool: str, args: dict[str, Any], data: Any) -> None:
        if not self.enabled:
            return
        entry = {
            "fetched_at": time.time(),
            "ttl": TTL_BY_TOOL.get(tool, DEFAULT_TTL),
            "data": data,
        }
        try:
            self._path(tool, args).write_text(
                json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
