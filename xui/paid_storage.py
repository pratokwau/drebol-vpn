from __future__ import annotations

import json
from pathlib import Path

PAID_SUBSCRIPTIONS_FILE = Path("data/paid_subscriptions.json")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, value) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_paid_subscriptions() -> dict:
    raw = _read_json(PAID_SUBSCRIPTIONS_FILE, {})
    return raw if isinstance(raw, dict) else {}


def save_paid_subscriptions(data: dict) -> None:
    _write_json(PAID_SUBSCRIPTIONS_FILE, data)


def get_paid_subscription(tg_id: int) -> dict | None:
    return load_paid_subscriptions().get(str(tg_id))


def has_paid_subscription(tg_id: int) -> bool:
    info = get_paid_subscription(tg_id)
    if not info:
        return False
    status = str(info.get("status", "") or "").lower()
    if status in {"blocked", "disabled", "cancelled", "canceled"}:
        return False
    return bool(info.get("active", True)) or status in {"trial", "active", "grace", "pending_payment"}

