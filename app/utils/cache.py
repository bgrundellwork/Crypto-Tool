import time
from typing import Any


# Simple in-memory cache
_cache: dict[str, tuple[float, Any]] = {}


def get_cache(key: str, ttl: int) -> Any | None:
    """
    Return cached value if it exists and is not expired.
    """
    if key not in _cache:
        return None

    timestamp, value = _cache[key]

    # Check if cache has expired
    if time.time() - timestamp > ttl:
        del _cache[key]
        return None

    return value


def set_cache(key: str, value: Any) -> None:
    """
    Store value in cache with current timestamp.
    """
    _cache[key] = (time.time(), value)
