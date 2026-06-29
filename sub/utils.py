from __future__ import annotations

import hashlib

from config import ADMIN_ID


_callback_cache: dict[str, object] = {}
_cache = _callback_cache
CLIENTS_PAGE_SIZE = 10


def is_admin(user_id: int) -> bool:
    return int(user_id) == int(ADMIN_ID)


def get_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


def cache(key: str, value) -> str:
    h = get_hash(key)
    _callback_cache[h] = value
    return h


def format_bytes(value: int) -> str:
    value = int(value or 0)
    if value < 1024:
        return f"{value} B"
    if value < 1024**2:
        return f"{value / 1024:.1f} KB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} MB"
    return f"{value / 1024**3:.2f} GB"
