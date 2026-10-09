"""Runtime configuration.

Token is read from the environment ONLY. The CLI deliberately offers no
--token flag so secrets never land in shell history.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MCP_URL = "https://mcp.mcd.cn"


@dataclass
class Settings:
    demo: bool
    token: str | None
    mcp_url: str
    cache_dir: Path

    @property
    def has_token(self) -> bool:
        return bool(self.token)


def load_settings(demo: bool = False) -> Settings:
    return Settings(
        demo=demo,
        token=os.environ.get("MCD_MCP_TOKEN") or None,
        mcp_url=os.environ.get("MCD_MCP_URL", DEFAULT_MCP_URL),
        cache_dir=Path(
            os.environ.get(
                "MCOPTIMIZER_CACHE_DIR",
                Path.home() / ".cache" / "mcoptimizer",
            )
        ),
    )
