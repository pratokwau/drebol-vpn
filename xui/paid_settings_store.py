from __future__ import annotations

from pathlib import Path

from storage import _read_json, _write_json

PAID_SETTINGS_FILE = Path("data/paid_settings.json")

DEFAULT_PAID_TRIAL_DAYS = 10
DEFAULT_PAID_PAYMENT_DAYS = 30
DEFAULT_PAID_PAYMENT_AMOUNT = 70
DEFAULT_PAID_GRACE_HOURS = 36
DEFAULT_PAID_PAYMENT_URL = ""


def load_paid_settings() -> dict:
    raw = _read_json(PAID_SETTINGS_FILE, {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "trial_days": int(raw.get("trial_days", DEFAULT_PAID_TRIAL_DAYS) or DEFAULT_PAID_TRIAL_DAYS),
        "payment_days": int(raw.get("payment_days", DEFAULT_PAID_PAYMENT_DAYS) or DEFAULT_PAID_PAYMENT_DAYS),
        "payment_amount": int(raw.get("payment_amount", DEFAULT_PAID_PAYMENT_AMOUNT) or DEFAULT_PAID_PAYMENT_AMOUNT),
        "grace_hours": int(raw.get("grace_hours", DEFAULT_PAID_GRACE_HOURS) or DEFAULT_PAID_GRACE_HOURS),
        "payment_url": str(raw.get("payment_url", DEFAULT_PAID_PAYMENT_URL) or ""),
    }


def save_paid_settings(data: dict) -> None:
    payload = {
        "trial_days": int(data.get("trial_days", DEFAULT_PAID_TRIAL_DAYS) or DEFAULT_PAID_TRIAL_DAYS),
        "payment_days": int(data.get("payment_days", DEFAULT_PAID_PAYMENT_DAYS) or DEFAULT_PAID_PAYMENT_DAYS),
        "payment_amount": int(data.get("payment_amount", DEFAULT_PAID_PAYMENT_AMOUNT) or DEFAULT_PAID_PAYMENT_AMOUNT),
        "grace_hours": int(data.get("grace_hours", DEFAULT_PAID_GRACE_HOURS) or DEFAULT_PAID_GRACE_HOURS),
        "payment_url": str(data.get("payment_url", DEFAULT_PAID_PAYMENT_URL) or ""),
    }
    _write_json(PAID_SETTINGS_FILE, payload)

