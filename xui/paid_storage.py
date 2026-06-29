from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from xui.paid_settings_store import DAY, HOUR

PAID_SUBSCRIPTIONS_FILE = Path("data/paid_subscriptions.json")
PAID_REQUESTS_FILE = Path("data/paid_requests.json")


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
    if not isinstance(raw, dict):
        return {}
    changed = False
    for info in raw.values():
        if not isinstance(info, dict):
            continue
        if "trial_seconds" not in info and info.get("trial_days") is not None:
            info["trial_seconds"] = int(info.get("trial_days") or 0) * DAY
            changed = True
        if "payment_seconds" not in info and info.get("payment_days") is not None:
            info["payment_seconds"] = int(info.get("payment_days") or 0) * DAY
            changed = True
        if "grace_seconds" not in info and info.get("grace_hours") is not None:
            info["grace_seconds"] = int(info.get("grace_hours") or 0) * HOUR
            changed = True
    if changed:
        save_paid_subscriptions(raw)
    return raw


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
    now = int(time.time())
    trial_ends_at = int(info.get("trial_ends_at") or 0)
    paid_ends_at = int(info.get("paid_ends_at") or 0)
    grace_ends_at = int(info.get("grace_ends_at") or 0)
    if status == "trial" and trial_ends_at and now > trial_ends_at:
        if grace_ends_at and now <= grace_ends_at:
            status = "grace"
        else:
            status = "expired"
    if status == "pending_payment" and grace_ends_at and now > grace_ends_at:
        status = "expired"
    if status == "expired":
        return bool(paid_ends_at and now <= paid_ends_at)
    return bool(info.get("active", True)) or status in {"trial", "active", "grace", "pending_payment"}


def paid_subscription_status(info: dict) -> str:
    status = str(info.get("status", "") or "active").lower()
    now = int(time.time())
    trial_ends_at = int(info.get("trial_ends_at") or 0)
    paid_ends_at = int(info.get("paid_ends_at") or 0)
    grace_ends_at = int(info.get("grace_ends_at") or 0)
    if status in {"blocked", "disabled", "cancelled", "canceled"}:
        return "blocked"
    if status == "trial" and trial_ends_at and now > trial_ends_at:
        if grace_ends_at and now <= grace_ends_at:
            return "grace"
        return "expired"
    if status in {"active", "pending_payment"} and paid_ends_at and now > paid_ends_at:
        if grace_ends_at and now <= grace_ends_at:
            return "grace"
        return "expired"
    return status


def load_paid_requests() -> dict:
    raw = _read_json(PAID_REQUESTS_FILE, {})
    return raw if isinstance(raw, dict) else {}


def save_paid_requests(data: dict) -> None:
    _write_json(PAID_REQUESTS_FILE, data)


def get_paid_request(user_id: int) -> dict | None:
    return load_paid_requests().get(str(user_id))


def create_paid_request(
    user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
    *,
    kind: str = "access",
) -> tuple[str, dict]:
    data = load_paid_requests()
    key = str(user_id)
    request_id = data.get(key, {}).get("request_id") or secrets.token_hex(6)
    request = {
        "request_id": request_id,
        "user_id": int(user_id),
        "username": username or "",
        "first_name": first_name or "",
        "last_name": last_name or "",
        "kind": str(kind or "access"),
        "status": "pending",
    }
    data[key] = request
    save_paid_requests(data)
    return request_id, request


def delete_paid_request(user_id: int) -> None:
    data = load_paid_requests()
    key = str(user_id)
    if key in data:
        data.pop(key, None)
        save_paid_requests(data)


def get_paid_request_by_id(request_id: str) -> dict | None:
    for request in load_paid_requests().values():
        if str(request.get("request_id", "")) == str(request_id):
            return request
    return None


def set_paid_subscription(user_id: int, data: dict) -> None:
    all_data = load_paid_subscriptions()
    all_data[str(user_id)] = data
    save_paid_subscriptions(all_data)


def build_paid_subscription(settings: dict, *, kind: str = "access", source: dict | None = None) -> dict:
    now = int(time.time())
    trial_seconds = int(settings.get("trial_seconds") or 0)
    payment_seconds = int(settings.get("payment_seconds") or 0)
    grace_seconds = int(settings.get("grace_seconds") or 0)
    payment_amount = int(settings.get("payment_amount") or 0)
    max_devices = int(settings.get("max_devices") or 0)
    payment_url = str(settings.get("payment_url") or "")
    source = source or {}
    return {
        "subscription_type": "paid",
        "status": "trial" if kind == "access" else "active",
        "active": True,
        "trial_seconds": trial_seconds,
        "payment_seconds": payment_seconds,
        "payment_amount": payment_amount,
        "max_devices": max_devices,
        "payment_url": payment_url,
        "grace_seconds": grace_seconds,
        "created_at": now,
        "trial_ends_at": now + trial_seconds if trial_seconds else 0,
        "paid_ends_at": 0,
        "grace_ends_at": now + trial_seconds + grace_seconds if trial_seconds and grace_seconds else 0,
        "last_request_kind": str(kind or "access"),
        "source_request_id": str(source.get("request_id") or ""),
    }


def extend_paid_subscription(info: dict, settings: dict, *, from_now: bool = False) -> dict:
    now = int(time.time())
    current_end = int(info.get("paid_ends_at") or 0)
    base = now if from_now or current_end < now else current_end
    payment_seconds = int(settings.get("payment_seconds") or 0)
    grace_seconds = int(settings.get("grace_seconds") or 0)
    info["max_devices"] = int(settings.get("max_devices") or info.get("max_devices") or 0)
    info["status"] = "active"
    info["active"] = True
    info["paid_ends_at"] = base + payment_seconds if payment_seconds else base
    info["grace_ends_at"] = info["paid_ends_at"] + grace_seconds if grace_seconds else info["paid_ends_at"]
    return info
