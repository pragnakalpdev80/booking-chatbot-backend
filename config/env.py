import os
from typing import Any


class AppEnv:
    @staticmethod
    def get(key: str, default: Any = None) -> str:
        val = os.environ.get(key, default)
        if val is None:
            raise RuntimeError(f"Missing required environment variable: {key}")
        return val

    @staticmethod
    def get_bool(key: str, default: bool = False) -> bool:
        val = os.environ.get(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "yes", "t")

    @staticmethod
    def get_int(key: str, default: int = 0) -> int:
        val = os.environ.get(key)
        if val is None:
            return default
        return int(val)
