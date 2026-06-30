from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from sub.adminpaysub.paid_settings_store import DAY, HOUR, DEFAULT_PAID_EXPIRY_TIME_MS

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
        if "renewals_count" not in info:
            info["renewals_count"] = 0
            changed = True
        if "total_paid_amount" not in info:
            info["total_paid_amount"] = 0
            changed = True
        if "last_activity_at" not in info:
            info["last_activity_at"] = int(info.get("created_at") or 0)
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
    status = paid_subscription_status(info)
    if status in {"blocked", "disabled", "cancelled", "canceled", "expired", "frozen"}:
        return False
    return bool(info.get("active", True)) or status in {"trial", "active", "grace", "pending_payment"}


def paid_subscription_status(info: dict) -> str:
    status = str(info.get("status", "") or "active").lower()
    now = int(time.time())
    trial_ends_at = int(info.get("trial_ends_at") or 0)
    paid_ends_at = int(info.get("paid_ends_at") or 0)
    grace_ends_at = int(info.get("grace_ends_at") or 0)
    if status in {"blocked", "disabled", "cancelled", "canceled"}:
        return "blocked"
    if status == "frozen":
        return "frozen"
    if status == "trial" and trial_ends_at and now > trial_ends_at:
        if grace_ends_at and now <= grace_ends_at:
            return "grace"
        return "expired"
    if status in {"active", "pending_payment"} and paid_ends_at and now > paid_ends_at:
        if grace_ends_at and now <= grace_ends_at:
            return "grace"
        return "expired"
    return status


def refresh_paid_subscription_state(info: dict, *, now: int | None = None) -> tuple[dict, list[str]]:
    now = int(time.time() if now is None else now)
    events: list[str] = []
    status = paid_subscription_status(info)
    trial_ends_at = int(info.get("trial_ends_at") or 0)
    paid_ends_at = int(info.get("paid_ends_at") or 0)
    grace_ends_at = int(info.get("grace_ends_at") or 0)

    trial_is_expired = bool(trial_ends_at and now >= trial_ends_at)
    paid_is_expired = bool(paid_ends_at and now >= paid_ends_at)
    grace_is_expired = bool(grace_ends_at and now >= grace_ends_at)

    if trial_is_expired and not info.get("trial_expired_notified_at"):
        events.append("trial_expired")
    if paid_ends_at and paid_is_expired and not info.get("payment_expired_notified_at"):
        events.append("payment_expired")
    if grace_is_expired and not info.get("grace_expired_notified_at") and status in {"trial", "grace", "expired"}:
        events.append("grace_expired")

    if status == "frozen":
        return info, events

    if status == "trial" and trial_is_expired:
        if grace_ends_at and not grace_is_expired:
            info["status"] = "grace"
            info["active"] = True
        else:
            info["status"] = "expired"
            info["active"] = False
    elif status in {"active", "pending_payment"} and paid_is_expired:
        if grace_ends_at and not grace_is_expired:
            info["status"] = "grace"
            info["active"] = True
        else:
            info["status"] = "expired"
            info["active"] = False
    elif status == "grace" and grace_is_expired:
        info["status"] = "expired"
        info["active"] = False

    return info, events


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


def delete_paid_subscription(user_id: int) -> None:
    all_data = load_paid_subscriptions()
    key = str(user_id)
    if key in all_data:
        all_data.pop(key, None)
        save_paid_subscriptions(all_data)


def build_paid_subscription(settings: dict, *, kind: str = "access", source: dict | None = None) -> dict:
    now = int(time.time())
    trial_seconds = int(settings.get("trial_seconds") or 0)
    payment_seconds = int(settings.get("payment_seconds") or 0)
    grace_seconds = int(settings.get("grace_seconds") or 0)
    payment_amount = int(settings.get("payment_amount") or 0)
    max_devices = int(settings.get("max_devices") or 0)
    limit_ip = int(settings.get("limit_ip") or 0)
    limit_gb = float(settings.get("limit_gb") or 0)
    flow = str(settings.get("flow") or "")
    payment_url = str(settings.get("payment_url") or "")
    source = source or {}
    expiry_time_ms = int((now + max(1, trial_seconds) + (grace_seconds if kind == "access" else 0)) * 1000) if kind == "access" else int(
        settings.get("expiry_time_ms") or DEFAULT_PAID_EXPIRY_TIME_MS
    )
    return {
        "subscription_type": "paid",
        "status": "trial" if kind == "access" else "active",
        "active": True,
        "trial_seconds": trial_seconds,
        "payment_seconds": payment_seconds,
        "payment_amount": payment_amount,
        "max_devices": max_devices,
        "limit_ip": limit_ip,
        "limit_gb": limit_gb,
        "expiry_time_ms": expiry_time_ms,
        "flow": flow,
        "payment_url": payment_url,
        "grace_seconds": grace_seconds,
        "created_at": now,
        "trial_ends_at": now + trial_seconds if trial_seconds else 0,
        "paid_ends_at": 0,
        "grace_ends_at": now + trial_seconds + grace_seconds if trial_seconds and grace_seconds else 0,
        "last_request_kind": str(kind or "access"),
        "source_request_id": str(source.get("request_id") or ""),
        "renewals_count": 0,
        "total_paid_amount": 0,
        "last_activity_at": now,
    }


def extend_paid_subscription(info: dict, settings: dict, *, from_now: bool = False) -> dict:
    now = int(time.time())
    current_end = int(info.get("paid_ends_at") or 0)
    base = now if from_now or current_end < now else current_end
    payment_seconds = int(settings.get("payment_seconds") or 0)
    grace_seconds = int(settings.get("grace_seconds") or 0)
    info["trial_expired_notified_at"] = int(info.get("trial_expired_notified_at") or now)
    info.pop("payment_expired_notified_at", None)
    info.pop("grace_expired_notified_at", None)
    info["max_devices"] = int(settings.get("max_devices") or info.get("max_devices") or 0)
    info["limit_ip"] = int(settings.get("limit_ip") or info.get("limit_ip") or 0)
    info["limit_gb"] = float(settings.get("limit_gb") or info.get("limit_gb") or 0)
    info["expiry_time_ms"] = int(settings.get("expiry_time_ms") or info.get("expiry_time_ms") or DEFAULT_PAID_EXPIRY_TIME_MS)
    info["flow"] = str(settings.get("flow") or info.get("flow") or "")
    info["status"] = "active"
    info["active"] = True
    info["paid_ends_at"] = base + payment_seconds if payment_seconds else base
    info["grace_ends_at"] = info["paid_ends_at"] + grace_seconds if grace_seconds else info["paid_ends_at"]
    info["expiry_time_ms"] = int(info["grace_ends_at"] * 1000) if info.get("grace_ends_at") else int(info["paid_ends_at"] * 1000)
    info["last_activity_at"] = now
    return info


def shift_paid_subscription_timeline(info: dict, seconds: int) -> dict:
    delta = int(seconds or 0)
    if delta == 0:
        return info
    for field in ("trial_ends_at", "paid_ends_at", "grace_ends_at"):
        value = int(info.get(field) or 0)
        if value > 0:
            info[field] = value + delta
    expiry_time_ms = int(info.get("expiry_time_ms") or 0)
    if expiry_time_ms > 0:
        info["expiry_time_ms"] = expiry_time_ms + delta * 1000
    return info
