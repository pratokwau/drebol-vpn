from __future__ import annotations

import re
from pathlib import Path

from storage import _read_json, _write_json

PAID_SETTINGS_FILE = Path("data/paid_settings.json")

SECOND = 1
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
DAY = 24 * HOUR
WEEK = 7 * DAY
MONTH = 30 * DAY
YEAR = 365 * DAY

DEFAULT_PAID_TRIAL_SECONDS = 10 * DAY
DEFAULT_PAID_PAYMENT_SECONDS = 30 * DAY
DEFAULT_PAID_PAYMENT_AMOUNT = 70
DEFAULT_PAID_GRACE_SECONDS = 36 * HOUR
DEFAULT_PAID_MAX_DEVICES = 1
DEFAULT_PAID_PAYMENT_URL = ""


def parse_duration_to_seconds(raw: str | int | float | None) -> int:
    if raw is None:
        raise ValueError("empty duration")
    if isinstance(raw, (int, float)):
        if raw < 0:
            raise ValueError("duration must be positive")
        return int(raw)
    text = str(raw).strip().lower().replace(",", ".")
    if not text or text == "-":
        raise ValueError("empty duration")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-zа-яё]+)?", text)
    if not match:
        raise ValueError("invalid duration")
    value = float(match.group(1))
    unit = (match.group(2) or "s").strip()

    multipliers = {
        "s": SECOND,
        "sec": SECOND,
        "secs": SECOND,
        "second": SECOND,
        "seconds": SECOND,
        "сек": SECOND,
        "секунда": SECOND,
        "секунды": SECOND,
        "секунд": SECOND,
        "m": MINUTE,
        "min": MINUTE,
        "mins": MINUTE,
        "minute": MINUTE,
        "minutes": MINUTE,
        "мин": MINUTE,
        "минута": MINUTE,
        "минуты": MINUTE,
        "минут": MINUTE,
        "h": HOUR,
        "hr": HOUR,
        "hrs": HOUR,
        "hour": HOUR,
        "hours": HOUR,
        "ч": HOUR,
        "час": HOUR,
        "часа": HOUR,
        "часов": HOUR,
        "d": DAY,
        "day": DAY,
        "days": DAY,
        "д": DAY,
        "день": DAY,
        "дня": DAY,
        "дней": DAY,
        "w": WEEK,
        "week": WEEK,
        "weeks": WEEK,
        "н": WEEK,
        "нед": WEEK,
        "неделя": WEEK,
        "недели": WEEK,
        "недель": WEEK,
        "mo": MONTH,
        "mon": MONTH,
        "month": MONTH,
        "months": MONTH,
        "мес": MONTH,
        "месяц": MONTH,
        "месяца": MONTH,
        "месяцев": MONTH,
        "y": YEAR,
        "yr": YEAR,
        "year": YEAR,
        "years": YEAR,
        "г": YEAR,
        "год": YEAR,
        "года": YEAR,
        "лет": YEAR,
    }
    if unit not in multipliers:
        raise ValueError("unknown duration unit")
    return max(1, int(value * multipliers[unit]))


def format_duration(seconds: int | None) -> str:
    total = int(seconds or 0)
    if total <= 0:
        return "не задано"
    units = [
        (YEAR, "год"),
        (MONTH, "мес"),
        (WEEK, "нед"),
        (DAY, "дн"),
        (HOUR, "ч"),
        (MINUTE, "мин"),
        (SECOND, "сек"),
    ]
    for unit_seconds, label in units:
        if total % unit_seconds == 0:
            value = total // unit_seconds
            if label == "мес":
                return f"{value} мес"
            if label == "нед":
                return f"{value} нед"
            if label == "дн":
                return f"{value} дн"
            return f"{value} {label}"
    return f"{total} сек"


def load_paid_settings() -> dict:
    raw = _read_json(PAID_SETTINGS_FILE, {})
    if not isinstance(raw, dict):
        raw = {}
    trial_seconds = raw.get("trial_seconds")
    payment_seconds = raw.get("payment_seconds")
    grace_seconds = raw.get("grace_seconds")
    if trial_seconds is None and raw.get("trial_days") is not None:
        trial_seconds = int(raw.get("trial_days") or DEFAULT_PAID_TRIAL_SECONDS // DAY) * DAY
    if payment_seconds is None and raw.get("payment_days") is not None:
        payment_seconds = int(raw.get("payment_days") or DEFAULT_PAID_PAYMENT_SECONDS // DAY) * DAY
    if grace_seconds is None and raw.get("grace_hours") is not None:
        grace_seconds = int(raw.get("grace_hours") or DEFAULT_PAID_GRACE_SECONDS // HOUR) * HOUR
    return {
        "trial_seconds": int(trial_seconds or DEFAULT_PAID_TRIAL_SECONDS),
        "payment_seconds": int(payment_seconds or DEFAULT_PAID_PAYMENT_SECONDS),
        "payment_amount": int(raw.get("payment_amount", DEFAULT_PAID_PAYMENT_AMOUNT) or DEFAULT_PAID_PAYMENT_AMOUNT),
        "grace_seconds": int(grace_seconds or DEFAULT_PAID_GRACE_SECONDS),
        "max_devices": int(raw.get("max_devices", DEFAULT_PAID_MAX_DEVICES) or DEFAULT_PAID_MAX_DEVICES),
        "payment_url": str(raw.get("payment_url", DEFAULT_PAID_PAYMENT_URL) or ""),
    }


def save_paid_settings(data: dict) -> None:
    payload = {
        "trial_seconds": int(data.get("trial_seconds", DEFAULT_PAID_TRIAL_SECONDS) or DEFAULT_PAID_TRIAL_SECONDS),
        "payment_seconds": int(data.get("payment_seconds", DEFAULT_PAID_PAYMENT_SECONDS) or DEFAULT_PAID_PAYMENT_SECONDS),
        "payment_amount": int(data.get("payment_amount", DEFAULT_PAID_PAYMENT_AMOUNT) or DEFAULT_PAID_PAYMENT_AMOUNT),
        "grace_seconds": int(data.get("grace_seconds", DEFAULT_PAID_GRACE_SECONDS) or DEFAULT_PAID_GRACE_SECONDS),
        "max_devices": int(data.get("max_devices", DEFAULT_PAID_MAX_DEVICES) or DEFAULT_PAID_MAX_DEVICES),
        "payment_url": str(data.get("payment_url", DEFAULT_PAID_PAYMENT_URL) or ""),
    }
    _write_json(PAID_SETTINGS_FILE, payload)
