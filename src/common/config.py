"""Config loading with attribute access and threshold provenance.

Everything a reviewer might argue with (a threshold, a seed, a coefficient)
must be readable from config/config.yaml rather than grepped out of code.
`Config.cite()` exists so a proxy can attach its own source paper to its
output record without the calling code hardcoding a citation string.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "config.yaml"


class Config:
    def __init__(self, data: dict, source: Path):
        self._data = data
        self.source = source

    # -- access ---------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, dotted: str, default: Any = None) -> Any:
        """cfg.get('proxies.freeboard.min_safe_m') -> 25"""
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def require(self, dotted: str) -> Any:
        """Same as get(), but a missing threshold is a hard error.

        Used by the proxy engine so a typo'd config key surfaces immediately
        instead of silently degrading a hazard flag to None.
        """
        sentinel = object()
        value = self.get(dotted, sentinel)
        if value is sentinel:
            raise KeyError(f"required config key missing: {dotted} (in {self.source})")
        return value

    def cite(self, dotted: str) -> dict:
        """Return {source, tier} for a threshold group.

        Stage 4 pass criterion: every numeric proxy states its source paper and
        confidence tier in the *output*, not just the docs.
        """
        node = self.get(dotted, {})
        if not isinstance(node, dict):
            node = {}
        return {
            "source": node.get("source", "unsourced - see docs/DECISIONS.md"),
            "confidence_tier": node.get("tier", "derived"),
        }

    def as_dict(self) -> dict:
        return self._data

    # -- resolved paths -------------------------------------------------
    def path(self, key: str) -> Path:
        return REPO_ROOT / self.require(f"paths.{key}")


@functools.lru_cache(maxsize=4)
def load_config(path: str | Path = DEFAULT_CONFIG) -> Config:
    path = Path(path)
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return Config(data, path)
