from __future__ import annotations

from typing import Any


class ConfigAdapter:
    def __init__(self, config: Any):
        self._cfg = config or {}

    def get(self, key: str, default: Any = None) -> Any:
        cfg = self._cfg
        if cfg is None:
            return default
        if isinstance(cfg, dict):
            return cfg.get(key, default)
        if hasattr(cfg, key):
            try:
                return getattr(cfg, key)
            except Exception:
                pass
        if hasattr(cfg, "get"):
            try:
                return cfg.get(key, default)
            except Exception:
                pass
        try:
            return cfg[key]
        except Exception:
            return default

    def get_bool(self, key: str, default: bool) -> bool:
        val = self.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("1", "true", "yes", "on")
        return bool(val)

    def get_int(self, key: str, default: int) -> int:
        val = self.get(key, default)
        try:
            return int(val)
        except Exception:
            return default

    def get_list(self, key: str, default: list[Any]) -> list[Any]:
        val = self.get(key, default)
        return val if isinstance(val, list) else default
