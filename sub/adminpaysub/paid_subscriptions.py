from __future__ import annotations

import html
import re
from datetime import datetime, timezone
import time

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID
from loader import bot
from sub.adminpaysub.paid_settings_store import (
    DEFAULT_PAID_GRACE_SECONDS,
    DEFAULT_PAID_LIMIT_IP,
    DEFAULT_PAID_LIMIT_GB,
    DEFAULT_PAID_PAYMENT_AMOUNT,
    DEFAULT_PAID_PAYMENT_URL,
    DEFAULT_PAID_PAYMENT_SECONDS,
    DEFAULT_PAID_EXPIRY_TIME_MS,
    DEFAULT_PAID_MAX_DEVICES,
    DEFAULT_PAID_TRIAL_SECONDS,
    DEFAULT_PAID_FLOW,
    format_duration,
    load_paid_settings,
    parse_duration_to_seconds,
    save_paid_settings,
)
from sub.adminpaysub.paid_storage import (
    build_paid_subscription,
    create_paid_request,
    delete_paid_request,
    delete_paid_subscription,
    extend_paid_subscription,
    clear_paid_request_block,
    get_paid_request,
    get_paid_request_by_id,
    get_paid_request_block,
    get_paid_subscription,
    has_paid_subscription,
    load_paid_subscriptions,
    list_paid_request_blocks,
    paid_subscription_status,
    load_paid_requests,
    save_paid_subscriptions,
    set_paid_request_block,
    shift_paid_subscription_timeline,
    set_paid_subscription,
)
from sub.states import PaidSubSettings
from sub.adminpaysub.storage import (
    add_device_to_user_key,
    create_user_with_inbound,
    delete_user_completely,
    get_users_by_subscription_type,
    load_vpn_users,
    save_vpn_users,
    set_user_flow,
    set_user_limit_gb,
    set_user_limit_ip,
    set_user_max_devices,
    set_user_note,
    set_user_username,
)
from sub.utils import is_admin
from sub.api import api_add_client, api_del_client_by_email, api_get_client, api_get_inbounds, api_update_client
from sub.instructions import happ_instruction


router = Router()


def _log_paid(message: str) -> None:
    print(f"[PAID SUB] {message}")


def _paid_user_key(user_id: int) -> str:
    return f"paid_{int(user_id)}"


def _extract_paid_user_id(user_key: str) -> int | None:
    key = str(user_key or "")
    if key.isdigit():
        return int(key)
    if key.startswith("paid_"):
        suffix = key[len("paid_"):]
        if suffix.isdigit():
            return int(suffix)
    return None


def _sanitize_email_slug(text: str) -> str:
    slug = re.sub(r"[^\w-]+", "_", (text or "").strip().lower())
    slug = slug.strip("_")
    return slug or "paid"


def _format_dt(ts: int | None) -> str:
    value = int(ts or 0)
    if value <= 0:
        return "не задано"
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M")


def _parse_expiry_date(raw: str | None) -> int:
    text = (raw or "").strip()
    if not text or text == "-":
        return DEFAULT_PAID_EXPIRY_TIME_MS
    return int(datetime.strptime(text, "%d.%m.%Y").timestamp() * 1000)


def _parse_limit_gb(raw: str | None) -> float:
    text = (raw or "").strip()
    if not text or text == "-":
        return DEFAULT_PAID_LIMIT_GB
    return float(text)


def _format_limit_gb(value) -> str:
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0
    return "∞" if number <= 0 else str(number)


def _plural_ru(value: int, one: str, few: str, many: str) -> str:
    value = abs(int(value))
    if value % 10 == 1 and value % 100 != 11:
        return one
    if value % 10 in {2, 3, 4} and value % 100 not in {12, 13, 14}:
        return few
    return many


def _format_trial_remaining(subscription: dict) -> str:
    ends_at = int(subscription.get("trial_ends_at") or 0)
    now = int(datetime.now(tz=timezone.utc).timestamp())
    remaining = max(0, ends_at - now)
    days, remainder = divmod(remaining, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    clock = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{days} дн {clock}" if days else clock


def _format_active_remaining(subscription: dict) -> str:
    ends_at = int(subscription.get("paid_ends_at") or 0)
    now = int(datetime.now(tz=timezone.utc).timestamp())
    remaining = max(0, ends_at - now)
    days, remainder = divmod(remaining, 86400)
    hours, _ = divmod(remainder, 3600)
    if days and hours:
        return f"{days} {_plural_ru(days, 'день', 'дня', 'дней')} {hours} {_plural_ru(hours, 'час', 'часа', 'часов')}"
    if days:
        return f"{days} {_plural_ru(days, 'день', 'дня', 'дней')}"
    if hours:
        return f"{hours} {_plural_ru(hours, 'час', 'часа', 'часов')}"
    minutes = max(0, remainder // 60)
    if minutes:
        return f"{minutes} {_plural_ru(minutes, 'минута', 'минуты', 'минут')}"
    return "менее минуты"


def _remaining_seconds(subscription: dict) -> int:
    status = paid_subscription_status(subscription)
    now = int(datetime.now(tz=timezone.utc).timestamp())
    if status in {"active", "grace", "pending_payment", "frozen"}:
        return max(0, int(subscription.get("paid_ends_at") or 0) - now)
    return max(0, int(subscription.get("trial_ends_at") or 0) - now)


def _format_duration_ru(seconds: int | None) -> str:
    total = int(seconds or 0)
    if total <= 0:
        return "не задано"
    units = [
        (365 * 24 * 3600, "год", "года", "лет"),
        (30 * 24 * 3600, "месяц", "месяца", "месяцев"),
        (24 * 3600, "день", "дня", "дней"),
        (3600, "час", "часа", "часов"),
        (60, "минута", "минуты", "минут"),
        (1, "секунда", "секунды", "секунд"),
    ]
    for unit_seconds, one, few, many in units:
        if total % unit_seconds == 0:
            value = total // unit_seconds
            return f"{value} {_plural_ru(value, one, few, many)}"
    return f"{total} сек"


def _format_short_dt(ts: int | None) -> str:
    value = int(ts or 0)
    if value <= 0:
        return "Не активирован"
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone().strftime("%d.%m.%Y • %H:%M")


def _format_short_date(ts: int | None) -> str:
    value = int(ts or 0)
    if value <= 0:
        return "не задано"
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone().strftime("%d.%m.%Y")


def _format_last_activity(ts: int | None) -> str:
    value = int(ts or 0)
    if value <= 0:
        return "не задано"
    dt = datetime.fromtimestamp(value, tz=timezone.utc).astimezone()
    today = datetime.now(tz=timezone.utc).astimezone().date()
    if dt.date() == today:
        return f"Сегодня {dt.strftime('%H:%M')}"
    return dt.strftime("%d.%m.%Y %H:%M")


def _format_remaining_verbose(seconds: int | None) -> str:
    total = max(0, int(seconds or 0))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds_left = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} {_plural_ru(days, 'день', 'дня', 'дней')}")
    if hours:
        parts.append(f"{hours} {_plural_ru(hours, 'час', 'часа', 'часов')}")
    if minutes:
        parts.append(f"{minutes} {_plural_ru(minutes, 'минута', 'минуты', 'минут')}")
    if not parts:
        parts.append(f"{seconds_left} {_plural_ru(seconds_left, 'секунда', 'секунды', 'секунд')}")
    return " ".join(parts)


def _current_tariff_label(subscription: dict) -> str:
    status = paid_subscription_status(subscription)
    if status == "frozen":
        return "Заморожена"
    if status in {"active", "grace", "pending_payment"}:
        return "Premium"
    if status == "expired":
        return "Требует продления"
    return "Пробный доступ"


def _current_tariff_icon(subscription: dict) -> str:
    status = paid_subscription_status(subscription)
    if status == "frozen":
        return "❄️"
    if status in {"active", "grace", "pending_payment"}:
        return "👑"
    if status == "expired":
        return "⚪"
    return "🟢"


def _subscription_status_ru(subscription: dict) -> str:
    status = paid_subscription_status(subscription)
    labels = {
        "trial": "Пробный",
        "active": "Активна",
        "grace": "На продлении",
        "frozen": "Заморожена",
        "expired": "Истекла",
        "pending_payment": "Ожидает оплаты",
        "blocked": "Заблокирована",
        "disabled": "Отключена",
        "cancelled": "Отменена",
        "canceled": "Отменена",
    }
    return labels.get(status, status.capitalize() or "Неизвестно")


def _format_remaining_or_duration(ends_at: int | None, duration_seconds: int | None) -> str:
    now = int(datetime.now(tz=timezone.utc).timestamp())
    ends_value = int(ends_at or 0)
    if ends_value > now:
        return format_duration(max(0, ends_value - now))
    return format_duration(duration_seconds)


def _parse_limit_ip(raw: str | None) -> int:
    text = (raw or "").strip()
    if not text or text == "-":
        return DEFAULT_PAID_LIMIT_IP
    return max(1, int(text))


def _parse_max_devices(raw: str | None) -> int:
    text = (raw or "").strip()
    if not text or text == "-":
        return DEFAULT_PAID_MAX_DEVICES
    return max(1, int(text))


def _paid_subscriptions_kb(users: dict) -> InlineKeyboardMarkup:
    rows = []
    for user_key, info in sorted(users.items()):
        display_name = str(info.get("note") or info.get("username") or "").strip()
        if user_key.startswith("anon_"):
            label = "💳 Без TG ID"
        elif user_key.startswith("paid_"):
            label = f"💳 {display_name or user_key[len('paid_'):]}"
        else:
            label = f"💳 {display_name or user_key}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"paidsub_{user_key}")])
    rows.append([
        InlineKeyboardButton(text="📥 Запросы", callback_data="adminpaysub_requests"),
        InlineKeyboardButton(text="🔇 Заглушки", callback_data="adminpaysub_blocks"),
    ])
    rows.append([
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="adminpaysub_settings"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _paid_request_kb(request_id: str, block: dict | None = None) -> InlineKeyboardMarkup:
    mute_label = "🔊 Разблокировать" if block else "🔇 Заглушить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выдать", callback_data=f"paidreq_ok_{request_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"paidreq_no_{request_id}"),
            ],
            [InlineKeyboardButton(text=mute_label, callback_data=f"paidreq_mute_{request_id}")],
            [InlineKeyboardButton(text="⬅️ К запросам", callback_data="adminpaysub_requests")],
        ]
    )


def _paid_requests_data() -> dict:
    return load_paid_requests()


def _paid_request_label(request: dict) -> str:
    user_id = int(request.get("user_id") or 0)
    username = str(request.get("username") or "").strip()
    first_name = str(request.get("first_name") or "").strip()
    last_name = str(request.get("last_name") or "").strip()
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    base = f"{user_id}"
    if username:
        base += f" @{username}"
    elif full_name:
        base += f" {full_name}"
    return base


def _paid_request_kind_label(kind: str) -> str:
    return {
        "access": "триал",
        "renew": "продление",
        "payment_check": "оплата",
    }.get(str(kind or "").lower(), str(kind or "запрос"))


def _paid_block_label(block: dict) -> str:
    user_id = int(block.get("user_id") or 0)
    kind = _paid_request_kind_label(block.get("kind") or "access")
    until_at = _format_short_dt(block.get("until_at"))
    return f"{user_id} • {kind} • до {until_at}"


def _paid_requests_overview_kb(requests: dict) -> InlineKeyboardMarkup:
    trial_count = sum(1 for request in requests.values() if str(request.get("kind") or "access") == "access")
    payment_count = sum(1 for request in requests.values() if str(request.get("kind") or "") == "payment_check")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🧪 Триал-запросы ({trial_count})", callback_data="adminpaysub_requests_trial")],
            [InlineKeyboardButton(text=f"💳 Запросы оплаты ({payment_count})", callback_data="adminpaysub_requests_payment")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adminpaysub_back")],
        ]
    )


def _paid_requests_list_kb(requests: dict, *, kind: str) -> InlineKeyboardMarkup:
    rows = []
    for request in sorted(requests.values(), key=lambda item: int(item.get("user_id") or 0), reverse=True):
        if str(request.get("kind") or "access") != kind:
            continue
        request_id = str(request.get("request_id") or "")
        if not request_id:
            continue
        prefix = "🧪" if kind == "access" else "💳"
        rows.append([InlineKeyboardButton(text=f"{prefix} {_paid_request_label(request)}", callback_data=f"paidreq_view_{request_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adminpaysub_requests")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _paid_blocks_overview_kb(blocks: dict) -> InlineKeyboardMarkup:
    trial_count = sum(1 for block in blocks.values() if str(block.get("kind") or "") == "access")
    payment_count = sum(1 for block in blocks.values() if str(block.get("kind") or "") in {"renew", "payment_check"})
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🧪 Блок триала ({trial_count})", callback_data="adminpaysub_blocks_trial")],
            [InlineKeyboardButton(text=f"💳 Блок оплаты ({payment_count})", callback_data="adminpaysub_blocks_payment")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adminpaysub_back")],
        ]
    )


def _paid_blocks_list_kb(blocks: dict, *, kind: str) -> InlineKeyboardMarkup:
    rows = []
    for block in sorted(blocks.values(), key=lambda item: int(item.get("until_at") or 0), reverse=True):
        if str(block.get("kind") or "") != kind:
            continue
        user_id = int(block.get("user_id") or 0)
        if not user_id:
            continue
        rows.append([InlineKeyboardButton(text=f"🔇 {_paid_block_label(block)}", callback_data=f"paidblock_view_{user_id}_{kind}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adminpaysub_blocks")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _paid_payment_kb(request_id: str, block: dict | None = None) -> InlineKeyboardMarkup:
    mute_label = "🔊 Разблокировать" if block else "🔇 Заглушить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Оплата проверена", callback_data=f"paidpay_ok_{request_id}"),
                InlineKeyboardButton(text="❌ Оплата не найдена", callback_data=f"paidpay_no_{request_id}"),
            ],
            [InlineKeyboardButton(text=mute_label, callback_data=f"paidreq_mute_{request_id}")],
            [InlineKeyboardButton(text="⬅️ К запросам", callback_data="adminpaysub_requests")],
        ]
    )


def _paid_subscription_actions_kb(user_key: str, subscription: dict) -> InlineKeyboardMarkup:
    is_frozen = paid_subscription_status(subscription) == "frozen"
    freeze_label = "❄️ Разморозить" if is_frozen else "❄️ Заморозить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="adminpaysub_back"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"paidsub_settings_{user_key}"),
            ],
            [
                InlineKeyboardButton(text="➕ Добавить срок", callback_data=f"paidsub_addtime_{user_key}"),
                InlineKeyboardButton(text=freeze_label, callback_data=f"paidsub_freeze_{user_key}"),
            ],
        ]
    )


def _paid_subscription_settings_kb(user_key: str, subscription: dict) -> InlineKeyboardMarkup:
    status = paid_subscription_status(subscription)
    freeze_label = "❄️ Разморозить" if status == "frozen" else "❄️ Заморозить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"📱 Устройства: {int(subscription.get('max_devices') or 1)}", callback_data=f"paidsubset_max_{user_key}"),
                InlineKeyboardButton(text=f"🌐 IP: {int(subscription.get('limit_ip') or 2)}", callback_data=f"paidsubset_ip_{user_key}"),
            ],
            [
                InlineKeyboardButton(text=f"💾 Трафик: {_format_limit_gb(subscription.get('limit_gb'))}", callback_data=f"paidsubset_gb_{user_key}"),
                InlineKeyboardButton(text=f"⚡ Flow: {str(subscription.get('flow') or DEFAULT_PAID_FLOW)}", callback_data=f"paidsubset_flow_{user_key}"),
            ],
            [
                InlineKeyboardButton(text="➕ Добавить срок", callback_data=f"paidsub_addtime_{user_key}"),
                InlineKeyboardButton(text=freeze_label, callback_data=f"paidsub_freeze_{user_key}"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"paidsub_{user_key}")],
        ]
    )


def _paid_settings_kb() -> InlineKeyboardMarkup:
    settings = load_paid_settings()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🧪 Пробный период: {format_duration(settings['trial_seconds'])}", callback_data="paidset_trial_seconds")],
            [InlineKeyboardButton(text=f"⏳ Период оплаты: {format_duration(settings['payment_seconds'])}", callback_data="paidset_payment_seconds")],
            [InlineKeyboardButton(text=f"💰 Сумма: {settings['payment_amount']} ₽", callback_data="paidset_payment_amount")],
            [InlineKeyboardButton(text=f"🕒 Время на продление: {format_duration(settings['grace_seconds'])}", callback_data="paidset_grace_seconds")],
            [InlineKeyboardButton(text=f"🔗 Ссылка на оплату: {'задана' if settings['payment_url'] else 'не задана'}", callback_data="paidset_payment_url")],
            [
                InlineKeyboardButton(text=f"📱 Лимит устройств: {settings['max_devices']}", callback_data="paidset_max_devices"),
                InlineKeyboardButton(text="По умолчанию", callback_data="paiddef_max_devices"),
            ],
            [
                InlineKeyboardButton(text=f"💾 Лимит ГБ: {_format_limit_gb(settings['limit_gb'])}", callback_data="paidset_limit_gb"),
                InlineKeyboardButton(text="По умолчанию", callback_data="paiddef_limit_gb"),
            ],
            [
                InlineKeyboardButton(text=f"🌐 Лимит IP: {settings['limit_ip']}", callback_data="paidset_limit_ip"),
                InlineKeyboardButton(text="По умолчанию", callback_data="paiddef_limit_ip"),
            ],
            [
                InlineKeyboardButton(text=f"⚡ Параметр flow: {settings['flow']}", callback_data="paidset_flow"),
                InlineKeyboardButton(text="По умолчанию", callback_data="paiddef_flow"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adminpaysub_back")],
        ]
    )


def _paid_setting_prompt(field: str) -> str:
    if field == "trial_seconds":
        return "Введите длительность пробного периода любым форматом: <code>12 часов</code>, <code>1 день</code>, <code>1 месяц</code>. Можно <code>-</code> для значения по умолчанию."
    if field == "payment_seconds":
        return "Введите срок платной подписки любым форматом: <code>12 часов</code>, <code>1 день</code>, <code>1 месяц</code>. Можно <code>-</code> для значения по умолчанию."
    if field == "payment_amount":
        return "Введите сумму оплаты в рублях или <code>-</code> для значения по умолчанию."
    if field == "grace_seconds":
        return "Введите время на продление любым форматом: <code>12 часов</code>, <code>1 день</code>, <code>36 часов</code>. Можно <code>-</code> для значения по умолчанию."
    if field == "payment_url":
        return "Введите ссылку на оплату или <code>-</code>, чтобы очистить её."
    if field == "max_devices":
        return "Введите лимит устройств или <code>-</code> для значения по умолчанию."
    if field == "limit_gb":
        return "Введите лимит ГБ или <code>-</code> для значения по умолчанию."
    if field == "limit_ip":
        return "Введите лимит IP или <code>-</code> для значения по умолчанию."
    if field == "flow":
        return "Введите flow или <code>-</code> для значения по умолчанию."
    return "Введите значение."


def _paid_setting_default(field: str):
    defaults = {
        "trial_seconds": DEFAULT_PAID_TRIAL_SECONDS,
        "payment_seconds": DEFAULT_PAID_PAYMENT_SECONDS,
        "payment_amount": DEFAULT_PAID_PAYMENT_AMOUNT,
        "grace_seconds": DEFAULT_PAID_GRACE_SECONDS,
        "max_devices": DEFAULT_PAID_MAX_DEVICES,
        "limit_gb": DEFAULT_PAID_LIMIT_GB,
        "limit_ip": DEFAULT_PAID_LIMIT_IP,
        "flow": DEFAULT_PAID_FLOW,
        "payment_url": DEFAULT_PAID_PAYMENT_URL,
    }
    return defaults.get(field)


async def _show_paid_settings(call_or_message, *, edit: bool = True):
    settings = load_paid_settings()
    text = (
        "⚙️ <b>Настройки платных подписок</b>\n\n"
        f"🧪 Пробный период: <b>{format_duration(settings['trial_seconds'])}</b>\n"
        f"⏳ Период оплаты: <b>{format_duration(settings['payment_seconds'])}</b>\n"
        f"💰 Сумма: <b>{settings['payment_amount']} ₽</b>\n"
        f"🕒 Время на продление: <b>{format_duration(settings['grace_seconds'])}</b>\n"
        f"🔗 Ссылка на оплату: <b>{'задана' if settings['payment_url'] else 'не задана'}</b>\n"
        f"📱 Лимит устройств: <b>{settings['max_devices']}</b>\n"
        f"💾 Лимит ГБ: <b>{_format_limit_gb(settings['limit_gb'])}</b>\n"
        f"🌐 Лимит IP: <b>{settings['limit_ip']}</b>\n"
        f"⚡ Параметр flow: <b>{settings['flow']}</b>"
    )
    markup = _paid_settings_kb()
    if edit and isinstance(call_or_message, types.CallbackQuery):
        try:
            await call_or_message.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            await call_or_message.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return
    if edit:
        await call_or_message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await call_or_message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def render_paid_subscriptions(message_or_call):
    users = get_users_by_subscription_type("paid")
    text = (
        "💳 <b>Платные подписки</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"📦 Подписок: <b>{len(users)}</b>\n\n"
        + ("Выберите подписку:" if users else "Пока нет платных подписок.")
    )
    markup = _paid_subscriptions_kb(users)
    if isinstance(message_or_call, types.CallbackQuery):
        try:
            await message_or_call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            await message_or_call.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return
    await message_or_call.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _show_paid_request_details(call: types.CallbackQuery, request_id: str) -> None:
    request = get_paid_request_by_id(request_id)
    if not request:
        await call.answer("Запрос не найден", show_alert=True)
        return
    kind = str(request.get("kind") or "access")
    user_id = int(request.get("user_id") or 0)
    settings = load_paid_settings()
    title = "Новая заявка на первичный триал доступ" if kind == "access" else "Пользователь сообщил об оплате"
    block = get_paid_request_block(user_id, kind)
    text = _admin_paid_request_text(request, settings, title)
    if block:
        text += "\n\n" + _paid_request_block_text(user_id, kind, block)
    markup = _paid_request_kb(request_id, block) if kind == "access" else _paid_payment_kb(request_id, block)
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await call.answer()


def _paid_request_block_text(user_id: int, kind: str, block: dict | None) -> str:
    title = "триала" if kind == "access" else "оплаты"
    if block:
        until_at = _format_short_dt(block.get("until_at"))
        admin_id = int(block.get("blocked_by") or 0)
        return (
            f"🔇 <b>Заглушка {title}</b>\n\n"
            f"Пользователь: <code>{user_id}</code>\n"
            f"Действует до: <b>{until_at}</b>\n"
            + (f"Заглушил: <code>{admin_id}</code>\n" if admin_id else "")
            + "\nПока заглушка активна, пользователь не сможет отправить этот запрос."
        )
    return (
        f"🔇 <b>Заглушка {title}</b>\n\n"
        f"Пользователь: <code>{user_id}</code>\n"
        "Сейчас запрос не заглушен.\n"
        "Нажмите кнопку ниже, чтобы временно заблокировать отправку."
    )


def _paid_request_block_kb(user_id: int, kind: str, block: dict | None) -> InlineKeyboardMarkup:
    rows = []
    if block:
        rows.append([InlineKeyboardButton(text="🔊 Разблокировать", callback_data=f"paidblock_clear_{user_id}_{kind}")])
    else:
        rows.append([InlineKeyboardButton(text="🔇 Заглушить", callback_data=f"paidblock_mute_{user_id}_{kind}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adminpaysub_requests")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _paid_block_remaining(block: dict | None) -> str:
    if not block:
        return "не задано"
    return _format_remaining_verbose(int(block.get("until_at") or 0) - int(time.time()))


def _paid_block_user_message(kind: str, block: dict | None) -> str:
    title = "триал" if kind == "access" else "оплата"
    if not block:
        return "⛔ <b>Запрос временно заглушен.</b>"
    return (
        f"⛔ <b>Запрос на {title} временно заглушен.</b>\n\n"
        f"Осталось: <b>{_paid_block_remaining(block)}</b>\n"
        "Попробуй позже."
    )


def _paid_block_alert_text(kind: str, block: dict | None) -> str:
    title = "триал" if kind == "access" else "оплата"
    if not block:
        return f"Запрос на {title} временно заглушен"
    return f"Запрос на {title} заглушен ещё { _paid_block_remaining(block) }"


async def _open_paid_request_block_prompt(call: types.CallbackQuery, user_id: int, kind: str) -> None:
    await call.message.edit_text(
        f"🔇 <b>Заглушить {_paid_request_kind_label(kind)}</b>\n\n"
        f"Пользователь: <code>{user_id}</code>\n\n"
        "Отправь время блокировки любым форматом: <code>2 минуты</code>, <code>5 дней</code>, <code>1 час</code>.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )


def _parse_paid_request_block_target(data: str) -> tuple[int, str]:
    parts = str(data or "").split("_")
    if len(parts) < 4:
        return 0, "access"
    try:
        user_id = int(parts[2])
    except Exception:
        user_id = 0
    kind = "_".join(parts[3:]) or "access"
    return user_id, kind


async def _sync_paid_subscription_devices(
    user_id: int,
    subscription: dict,
    *,
    enabled: bool,
    expire_from_subscription: bool = True,
    limit_ip: int | None = None,
    limit_gb: float | None = None,
    flow: str | None = None,
) -> None:
    user_key = _paid_user_key(user_id)
    info = load_vpn_users().get(user_key, {})
    expiry_time_ms = int(subscription.get("expiry_time_ms") or 0)
    if expire_from_subscription and not expiry_time_ms:
        for field in ("grace_ends_at", "paid_ends_at", "trial_ends_at"):
            value = int(subscription.get(field) or 0)
            if value > 0:
                expiry_time_ms = value * 1000
                break
    target_limit_ip = int(limit_ip if limit_ip is not None else subscription.get("limit_ip") or 0)
    target_limit_gb = float(limit_gb if limit_gb is not None else subscription.get("limit_gb") or 0)
    target_flow = str(flow if flow is not None else subscription.get("flow") or "")
    for device in info.get("devices", []):
        email = str(device.get("email") or "")
        if not email:
            continue
        client = await api_get_client(email)
        if not client:
            continue
        if expiry_time_ms > 0:
            client["expiryTime"] = expiry_time_ms
        client["enable"] = bool(enabled)
        client["limitIp"] = target_limit_ip
        client["totalGB"] = 0 if target_limit_gb <= 0 else int(target_limit_gb * 1024 ** 3)
        client["flow"] = target_flow
        await api_update_client(email, client)


def _subscription_action_target(subscription: dict) -> tuple[str, int]:
    status = paid_subscription_status(subscription)
    if status == "trial":
        base = int(subscription.get("trial_ends_at") or 0)
    else:
        base = int(subscription.get("paid_ends_at") or 0)
    if base <= 0:
        base = int(subscription.get("grace_ends_at") or 0)
    return status, base


def _apply_paid_subscription_extension(subscription: dict, seconds: int) -> dict:
    delta = max(0, int(seconds))
    if delta <= 0:
        return subscription
    status = paid_subscription_status(subscription)
    now = int(time.time())
    if status == "trial":
        current_end = int(subscription.get("trial_ends_at") or 0)
        base = current_end if current_end > now else now
        subscription["trial_ends_at"] = base + delta
        if int(subscription.get("grace_ends_at") or 0) > 0:
            subscription["grace_ends_at"] = int(subscription["grace_ends_at"]) + delta
    elif status in {"active", "grace", "pending_payment", "frozen"}:
        current_end = int(subscription.get("paid_ends_at") or 0)
        base = current_end if current_end > now else now
        if current_end <= 0:
            base = now
        subscription["paid_ends_at"] = base + delta
        if int(subscription.get("grace_ends_at") or 0) > 0:
            subscription["grace_ends_at"] = int(subscription["grace_ends_at"] or 0) + delta
        else:
            grace_seconds = int(subscription.get("grace_seconds") or 0)
            subscription["grace_ends_at"] = subscription["paid_ends_at"] + grace_seconds if grace_seconds else subscription["paid_ends_at"]
    else:
        subscription["paid_ends_at"] = now + delta
        grace_seconds = int(subscription.get("grace_seconds") or 0)
        subscription["grace_ends_at"] = subscription["paid_ends_at"] + grace_seconds if grace_seconds else subscription["paid_ends_at"]
        if int(subscription.get("trial_ends_at") or 0) > 0:
            subscription["trial_ends_at"] = int(subscription["trial_ends_at"]) + delta
        subscription["status"] = "active"
        subscription["active"] = True
    subscription["last_activity_at"] = now
    return subscription


def _paid_subscription_detail_payload(user_key: str) -> tuple[str, InlineKeyboardMarkup] | None:
    info = load_vpn_users().get(user_key)
    if not info or str(info.get("subscription_type", "")).lower() != "paid":
        return None
    username = str(info.get("username") or "").strip()
    note = str(info.get("note") or "").strip()
    tg_id = str(_extract_paid_user_id(user_key) or info.get("tg_id") or user_key).strip()
    user_id = _extract_paid_user_id(user_key)
    subscription = get_paid_subscription(user_id) if user_id is not None else info
    display_name = username or note or user_key
    devices = info.get("devices", [])
    max_devices = int((subscription or info).get("max_devices") or 1)
    device_count = len(devices)
    limit_ip = int((subscription or info).get("limit_ip") or 2)
    limit_gb_value = _format_limit_gb((subscription or info).get("limit_gb"))
    limit_gb = "Безлимитный" if limit_gb_value == "∞" else limit_gb_value
    total_paid = int((subscription or info).get("total_paid_amount") or 0)
    renewals_count = int((subscription or info).get("renewals_count") or 0)
    created_at = _format_short_date((subscription or info).get("created_at") or 0)
    last_activity_at = _format_last_activity((subscription or info).get("last_activity_at") or 0)
    text = (
        "🛡️ <b>Карточка VPN-подписки</b>\n\n"
        "👤 <b>Пользователь</b>\n"
        f"🆔 <code>{html.escape(str(tg_id))}</code>\n"
        f"🏷 {('@' + html.escape(username)) if username else '—'}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 <b>Тариф</b>\n"
        f"{_current_tariff_icon(subscription or info)} {_current_tariff_label(subscription or info)}\n\n"
        "🟢 <b>Статус</b>\n"
        f"{_subscription_status_ru(subscription or info)}\n\n"
        "⏳ <b>Осталось</b>\n"
        f"{_format_remaining_verbose(_remaining_seconds(subscription or info))}\n\n"
        "📅 <b>Активна до</b>\n"
        f"{_format_short_dt((subscription or info).get('paid_ends_at') or (subscription or info).get('trial_ends_at'))}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚙️ <b>Параметры</b>\n\n"
        f"📱 Устройств: <b>{device_count} / {max_devices}</b>\n"
        f"🌐 IP-лимит: <b>{limit_ip}</b>\n"
        f"♾ Трафик: <b>{limit_gb}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 <b>Статистика</b>\n\n"
        f"📅 Создана: <b>{created_at}</b>\n"
        f"🔄 Продлений: <b>{renewals_count}</b>\n"
        f"💰 Оплачено: <b>{total_paid} ₽</b>\n"
        f"🕒 Последняя активность: <b>{last_activity_at}</b>"
    )
    if note:
        text += f"\n\n📝 Заметка: <i>{html.escape(note)}</i>"
    return text, _paid_subscription_actions_kb(user_key, subscription or info)


def _paid_subscription_settings_payload(user_key: str) -> tuple[str, InlineKeyboardMarkup] | None:
    info = load_vpn_users().get(user_key)
    if not info or str(info.get("subscription_type", "")).lower() != "paid":
        return None
    subscription = get_paid_subscription(_extract_paid_user_id(user_key)) if _extract_paid_user_id(user_key) is not None else info
    if not subscription:
        subscription = info
    return (
        "⚙️ <b>Настройки подписки</b>\n\n"
        "Здесь меняются только параметры выбранного клиента.\n"
        "Системные настройки находятся в общем меню платных подписок.\n\n"
        f"📱 Устройства: <b>{int(subscription.get('max_devices') or 1)}</b>\n"
        f"🌐 IP-лимит: <b>{int(subscription.get('limit_ip') or 2)}</b>\n"
        f"💾 Трафик: <b>{'Безлимитный' if _format_limit_gb(subscription.get('limit_gb')) == '∞' else _format_limit_gb(subscription.get('limit_gb'))}</b>\n"
        f"⚡ Flow: <b>{html.escape(str(subscription.get('flow') or DEFAULT_PAID_FLOW))}</b>",
        _paid_subscription_settings_kb(user_key, subscription),
    )


async def _render_paid_subscription_detail(call: types.CallbackQuery, user_key: str) -> None:
    payload = _paid_subscription_detail_payload(user_key)
    if not payload:
        await call.answer("Подписка не найдена", show_alert=True)
        return
    text, markup = payload
    await call.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )
    await call.answer()


def _subscription_summary(subscription: dict) -> str:
    status = paid_subscription_status(subscription)
    if status == "frozen":
        return (
            "Заморожена"
        )
    is_premium = status in {"active", "grace", "pending_payment"}
    plan_label = _current_tariff_label(subscription)
    remaining = _format_active_remaining(subscription) if is_premium else _format_trial_remaining(subscription)
    trial_ends = _format_short_dt(subscription.get("trial_ends_at"))
    paid_ends = _format_short_dt(subscription.get("paid_ends_at"))
    grace_ends = _format_short_dt(subscription.get("grace_ends_at"))
    if is_premium:
        return (
            "🔐 Ваша VPN-подписка\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "👑 Текущий тариф\n"
            f"{plan_label}\n\n"
            "⏳ До окончания\n"
            f"{remaining}\n\n"
            "📅 Действует до\n"
            f"{paid_ends}"
        )
    payment_amount = int(subscription.get("payment_amount") or 0)
    payment_seconds = _format_duration_ru(subscription.get("payment_seconds"))
    grace_seconds = _format_duration_ru(subscription.get("grace_seconds"))
    max_devices = int(subscription.get("max_devices") or 1)
    limit_ip = int(subscription.get("limit_ip") or 2)
    limit_gb = _format_limit_gb(subscription.get("limit_gb"))
    return (
        "🔐 Ваша VPN-подписка\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🟢 Текущий тариф\n"
        f"{plan_label}\n\n"
        "⏳ Осталось\n"
        f"{remaining}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 Параметры тарифа\n\n"
        f"💰 Стоимость: {payment_amount} ₽\n"
        f"🗓 Срок подписки: {payment_seconds}\n"
        f"🔄 Продление: {grace_seconds}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ Возможности\n\n"
        f"📱 До {max_devices} устройства\n"
        f"🌐 До {limit_ip} IP одновременно\n"
        f"♾ Безлимитный трафик\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📅 Пробный доступ\n"
        f"{trial_ends}\n\n"
        "👑 Платная подписка\n"
        f"{paid_ends}\n\n"
        "🕒 Доступ действует до\n"
        f"{grace_ends}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💙 Спасибо, что пользуетесь нашим VPN!"
    )


def _paid_user_info_text(subscription: dict) -> str:
    status = paid_subscription_status(subscription)
    is_premium = status in {"active", "grace", "pending_payment"}
    tariff_icon = "👑" if is_premium else "🟢"
    tariff_label = "Premium" if is_premium else "Пробный доступ"
    if is_premium:
        remaining = _format_active_remaining(subscription)
        remaining_title = "До окончания"
    elif status == "expired":
        remaining = "00:00:00"
        remaining_title = "Осталось"
        tariff_label = "Требует продления"
        tariff_icon = "🟢"
    else:
        remaining = _format_trial_remaining(subscription)
        remaining_title = "Осталось"
    payment_amount = int(subscription.get("payment_amount") or 0)
    payment_seconds = _format_duration_ru(subscription.get("payment_seconds"))
    grace_seconds = _format_duration_ru(subscription.get("grace_seconds"))
    max_devices = int(subscription.get("max_devices") or 1)
    limit_ip = int(subscription.get("limit_ip") or 2)
    trial_ends = _format_short_dt(subscription.get("trial_ends_at"))
    paid_ends = _format_short_dt(subscription.get("paid_ends_at"))
    grace_ends = _format_short_dt(subscription.get("grace_ends_at"))
    return (
        f"<b>ℹ️ Информация о вашей подписке</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{tariff_icon} Текущий тариф</b>\n"
        f"{tariff_label}\n\n"
        f"<b>⏳ {remaining_title}</b>\n"
        f"{remaining}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>💎 Параметры тарифа</b>\n\n"
        f"💰 Стоимость: {payment_amount} ₽\n"
        f"🗓 Срок подписки: {payment_seconds}\n"
        f"🔄 Продление: {grace_seconds}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>⚡ Возможности</b>\n\n"
        f"📱 До {max_devices} устройства\n"
        f"🌐 До {limit_ip} IP одновременно\n"
        "♾ Безлимитный трафик\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>📅 Пробный доступ</b>\n"
        f"{trial_ends}\n\n"
        f"<b>👑 Платная подписка</b>\n"
        f"{paid_ends}\n\n"
        f"<b>🕒 Доступ действует до</b>\n"
        f"{grace_ends}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>💙 Спасибо, что пользуетесь нашим VPN!</b>"
    )


def _paid_user_kb(user_id: int, subscription: dict | None, request: dict | None = None) -> InlineKeyboardMarkup:
    rows = []
    paid_user = load_vpn_users().get(_paid_user_key(user_id), {})
    request_kind = str((request or {}).get("kind") or "").lower()
    access_block = get_paid_request_block(user_id, "access")
    payment_block = get_paid_request_block(user_id, "payment_check") or get_paid_request_block(user_id, "renew")
    renew_requested = request is not None and subscription is not None and request_kind in {"renew", "payment_check"}
    if not subscription:
        if access_block:
            rows.append([InlineKeyboardButton(text="🔇 Триал заглушен", callback_data="paiduser_blocked_access")])
        else:
            rows.append([InlineKeyboardButton(text="💳 Получить подписку", callback_data="paiduser_request")])
    else:
        rows.append([InlineKeyboardButton(text="ℹ️ Информация о подписке", callback_data="paiduser_info")])
        if renew_requested:
            rows.append([InlineKeyboardButton(text="⏳ Заявка на продление отправлена", callback_data="paiduser_wait")])
        else:
            if payment_block and paid_subscription_status(subscription) not in {"trial", "active", "grace", "pending_payment"}:
                rows.append([InlineKeyboardButton(text="🔇 Продление заглушено", callback_data="paiduser_blocked_payment")])
            else:
                rows.append([InlineKeyboardButton(text="💳 Продлить подписку", callback_data=f"paiduser_renew_{user_id}")])
        if paid_user.get("devices"):
            rows.append([InlineKeyboardButton(text="📖 Инструкция", callback_data="paiduser_inst")])
    if request:
        if not subscription:
            rows = [[InlineKeyboardButton(text="⏳ Заявка уже отправлена", callback_data="paiduser_wait")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _paid_user_info_kb(user_id: int, subscription: dict | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="paiduser_back")],
        ]
    )


def _paid_payment_info_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Оплатил", callback_data=f"paiduser_paid_{user_id}"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="paiduser_back"),
            ],
        ]
    )


def _paid_instruction_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="paiduser_back")],
        ]
    )


def _paid_user_text(subscription: dict, payment_url: str) -> str:
    _ = payment_url
    return (
        "💳 <b>Меню управления подпиской</b>\n\n"
        "Нажмите кнопку ниже, чтобы посмотреть информацию о подписке или продлить её."
    )


def _paid_payment_text(subscription: dict, payment_url: str) -> str:
    payment_seconds = int(subscription.get("payment_seconds") or 0)
    payment_amount = int(subscription.get("payment_amount") or 0)
    payment_label = format_duration(payment_seconds)
    link = html.escape(str(payment_url or ""))
    link_html = f'<a href="{link}">{link}</a>' if link else "не задана"
    return (
        "💳 <b>Оплата подписки</b>\n\n"
        f"⏳ Срок после оплаты: <b>{payment_label}</b>\n"
        f"💰 Сумма: <b>{payment_amount} ₽</b>\n\n"
        "Перейди по ссылке ниже, в комментарии укажи свой TG ID или username.\n"
        "После оплаты нажми <b>«Оплатил»</b> — в течение 24 часов мы проверим платёж и выдадим подписку.\n\n"
        f"🔗 Ссылка на оплату: {link_html}"
    )


async def render_paid_user_menu(message_or_call, *, user_id: int, username: str = "", first_name: str = "", last_name: str = "", edit: bool = False) -> None:
    subscription = get_paid_subscription(user_id) or {}
    request = get_paid_request(user_id)
    access_block = get_paid_request_block(user_id, "access")
    payment_block = get_paid_request_block(user_id, "payment_check") or get_paid_request_block(user_id, "renew")
    if not subscription and not request:
        if access_block:
            text = _paid_block_user_message("access", access_block)
            if edit:
                await message_or_call.edit_text(text, parse_mode=ParseMode.HTML)
            else:
                await message_or_call.answer(text, parse_mode=ParseMode.HTML)
            return
        request_id, _ = create_paid_request(
            user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            kind="access",
        )
        text = (
            "✅ <b>Ваша заявка на триал доступ отправлена.</b>\n\n"
            "Ожидайте подтверждения от администратора."
        )
        if edit:
            await message_or_call.edit_text(text, parse_mode=ParseMode.HTML)
        else:
            await message_or_call.answer(text, parse_mode=ParseMode.HTML)
        settings = load_paid_settings()
        if ADMIN_ID:
            await bot.send_message(
                ADMIN_ID,
                _admin_paid_request_text(
                    {
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "last_name": last_name,
                        "request_id": request_id,
                        "kind": "access",
                    },
                    settings,
                    "Новая заявка на первичный триал доступ",
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_paid_request_kb(request_id),
            )
        return
    if request and not subscription:
        text = (
            "⏳ <b>Ваша заявка на триал доступ уже отправлена.</b>\n\n"
            "Ожидайте подтверждения от администратора."
        )
        if edit:
            await message_or_call.edit_text(text, parse_mode=ParseMode.HTML)
        else:
            await message_or_call.answer(text, parse_mode=ParseMode.HTML)
        return

    payment_url = subscription.get("payment_url") or load_paid_settings().get("payment_url") or DEFAULT_PAID_PAYMENT_URL
    if payment_block and paid_subscription_status(subscription) not in {"trial", "active", "grace", "pending_payment"}:
        payment_url = payment_url
    text = _paid_user_text(subscription, payment_url)
    if not subscription and access_block:
        text += f"\n\n⛔ <b>Триал временно заглушен.</b>\nОсталось: <b>{_paid_block_remaining(access_block)}</b>"
    elif subscription and payment_block and paid_subscription_status(subscription) not in {"trial", "active", "grace", "pending_payment"}:
        text += f"\n\n⛔ <b>Продление временно заглушено.</b>\nОсталось: <b>{_paid_block_remaining(payment_block)}</b>"
    markup = _paid_user_kb(user_id, subscription, request)
    if edit:
        await message_or_call.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await message_or_call.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


def _admin_paid_request_text(request: dict, settings: dict, title: str) -> str:
    user_id = int(request.get("user_id") or 0)
    kind = str(request.get("kind") or "access")
    first_name = str(request.get("first_name") or "").strip()
    last_name = str(request.get("last_name") or "").strip()
    username = str(request.get("username") or "").strip()
    full_name = " ".join(part for part in [first_name, last_name] if part).strip() or "не указано"
    kind_label = {
        "access": "первичный триал доступ",
        "renew": "продление подписки",
        "payment_check": "проверка оплаты",
    }.get(kind, kind)
    return (
        f"💳 <b>{title}</b>\n\n"
        f"👤 TG: <code>{user_id}</code>\n"
        f"👤 Имя: <code>{html.escape(full_name)}</code>\n"
        f"👤 Юзернейм: <code>{html.escape('@' + username) if username else 'не указан'}</code>\n"
        f"🧾 Тип заявки: <b>{html.escape(kind_label)}</b>\n"
        f"🧪 Пробный период: <b>{format_duration(settings['trial_seconds'])}</b>\n"
        f"⏳ Срок после оплаты: <b>{format_duration(settings['payment_seconds'])}</b>\n"
        f"💰 Сумма: <b>{settings['payment_amount']} ₽</b>\n"
        f"🕒 Время на продление: <b>{format_duration(settings['grace_seconds'])}</b>\n"
        f"📱 Лимит устройств: <b>{settings['max_devices']}</b>\n"
        f"💾 Лимит трафика: <b>{_format_limit_gb(settings['limit_gb'])}</b>\n"
        f"🌐 Лимит IP: <b>{settings['limit_ip']}</b>\n"
        f"⚡ Параметр подключения: <b>{settings['flow']}</b>\n"
        f"🆔 Request: <code>{html.escape(str(request.get('request_id') or ''))}</code>"
    )


async def _create_paid_device_for_user(user_id: int, settings: dict, request: dict) -> None:
    user_key = _paid_user_key(user_id)
    current = load_vpn_users().get(user_key, {})
    trial_seconds = int(settings.get("trial_seconds") or DEFAULT_PAID_TRIAL_SECONDS)
    grace_seconds = int(settings.get("grace_seconds") or DEFAULT_PAID_GRACE_SECONDS)
    trial_expiry_time_ms = int((time.time() + max(1, trial_seconds) + max(0, grace_seconds)) * 1000)
    limit_gb = float(settings.get("limit_gb") or DEFAULT_PAID_LIMIT_GB)
    expiry_time_ms = trial_expiry_time_ms
    limit_ip = int(settings.get("limit_ip") or DEFAULT_PAID_LIMIT_IP)
    flow = str(settings.get("flow") or DEFAULT_PAID_FLOW)
    username = str(request.get("username") or "").strip()
    display_name = f"{user_id} - {username or 'без юзернейма'}"
    _log_paid(
        "create_device start "
        f"user_id={user_id} user_key={user_key} "
        f"username={username!r} display_name={display_name!r} "
        f"trial={trial_seconds}s grace={grace_seconds}s "
        f"limit_gb={limit_gb} limit_ip={limit_ip} flow={flow!r}"
    )
    subscription_type = str(current.get("subscription_type") or "paid").lower()
    if subscription_type not in {"admin", "paid"}:
        subscription_type = "paid"
    if current.get("devices"):
        _log_paid(f"existing devices found user_key={user_key} count={len(current.get('devices', []))}")
        set_user_max_devices(user_key, int(settings.get("max_devices") or DEFAULT_PAID_MAX_DEVICES))
        set_user_limit_gb(user_key, limit_gb)
        set_user_limit_ip(user_key, limit_ip)
        set_user_flow(user_key, flow)
        set_user_username(user_id, username)
        set_user_note(user_id, display_name)
        updated_any = False
        valid_devices = []
        for device in current.get("devices", []):
            email = str(device.get("email") or "")
            if not email:
                continue
            client = await api_get_client(email)
            if client:
                updated_any = True
                valid_devices.append(device)
                client["totalGB"] = 0 if limit_gb <= 0 else int(limit_gb * 1024 ** 3)
                client["expiryTime"] = expiry_time_ms
                client["limitIp"] = limit_ip
                client["flow"] = flow
                _log_paid(f"updating existing device email={email!r} expiry={expiry_time_ms} limit_ip={limit_ip}")
                await api_update_client(email, client)
            else:
                _log_paid(f"stale local device without XUI record email={email!r}")
        if updated_any:
            if len(valid_devices) != len(current.get("devices", [])):
                data = load_vpn_users()
                if user_key in data:
                    data[user_key]["devices"] = valid_devices
                    save_vpn_users(data)
            return
        _log_paid(f"no live XUI devices found for user_key={user_key}, recreating device")
        data = load_vpn_users()
        if user_key in data:
            data[user_key]["devices"] = []
            save_vpn_users(data)
    inbounds, _ = await api_get_inbounds()
    _log_paid(f"inbounds loaded count={len(inbounds)}")
    inbound = next((item for item in inbounds if item.get("id") is not None), None)
    if not inbound:
        _log_paid("no inbound found, creating local user only")
        create_user_with_inbound(user_id, 0, note=display_name, subscription_type=subscription_type)
        set_user_max_devices(user_key, int(settings.get("max_devices") or DEFAULT_PAID_MAX_DEVICES))
        set_user_limit_gb(user_key, limit_gb)
        set_user_limit_ip(user_key, limit_ip)
        set_user_flow(user_key, flow)
        set_user_username(user_id, username)
        set_user_note(user_id, display_name)
        return
    inbound_id = int(inbound.get("id") or 0)
    _log_paid(f"inbound selected inbound_id={inbound_id}")
    create_user_with_inbound(user_id, inbound_id, note=display_name, subscription_type=subscription_type)
    set_user_max_devices(user_key, int(settings.get("max_devices") or DEFAULT_PAID_MAX_DEVICES))
    set_user_limit_gb(user_key, limit_gb)
    set_user_limit_ip(user_key, limit_ip)
    set_user_flow(user_key, flow)
    set_user_username(user_id, username)
    set_user_note(user_id, display_name)
    email_candidates = [
        f"{user_key}_{_sanitize_email_slug(username or display_name)}",
        f"paid_{user_id}_{_sanitize_email_slug(username or 'paid')}",
        f"paid_{user_id}",
    ]
    _log_paid(f"email candidates={email_candidates!r}")
    last_result: dict = {}
    for email in email_candidates:
        _log_paid(f"api_add_client try email={email!r} inbound_id={inbound_id} expiry_time_ms={expiry_time_ms}")
        result, client_uuid = await api_add_client(
            inbound_id,
            email,
            0,
            limit_gb,
            flow,
            expiry_time_ms=expiry_time_ms,
            limit_ip=limit_ip,
            comment=display_name,
        )
        last_result = result
        _log_paid(f"api_add_client result email={email!r} success={result.get('success')} msg={result.get('msg')!r} uuid={client_uuid!r}")
        if result.get("success"):
            _log_paid(f"device created email={email!r} uuid={client_uuid!r}")
            add_device_to_user_key(user_key, inbound_id, client_uuid, email, limit_ip=limit_ip, label=display_name)
            return
    error_msg = str(last_result.get("msg") or "Неизвестная ошибка XUI")
    _log_paid(f"device creation failed user_id={user_id} error={error_msg!r}")
    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                "❌ <b>Не удалось создать trial-устройство.</b>\n\n"
                f"TG: <code>{user_id}</code>\n"
                f"Имя: <code>{html.escape(display_name)}</code>\n"
                f"Ошибка: <code>{html.escape(error_msg)}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    raise RuntimeError(error_msg)


async def _sync_paid_user_devices_expiry(
    user_id: int,
    expiry_time_ms: int,
    *,
    enabled: bool = True,
    limit_ip: int | None = None,
    limit_gb: float | None = None,
    flow: str | None = None,
) -> None:
    info = load_vpn_users().get(_paid_user_key(user_id), {})
    target_limit_ip = int(limit_ip if limit_ip is not None else DEFAULT_PAID_LIMIT_IP)
    target_limit_gb = float(limit_gb if limit_gb is not None else DEFAULT_PAID_LIMIT_GB)
    target_flow = str(flow if flow is not None else DEFAULT_PAID_FLOW)
    for device in info.get("devices", []):
        email = str(device.get("email") or "")
        if not email:
            continue
        client = await api_get_client(email)
        if client:
            client["totalGB"] = 0 if target_limit_gb <= 0 else int(target_limit_gb * 1024 ** 3)
            client["expiryTime"] = int(expiry_time_ms)
            client["limitIp"] = target_limit_ip
            client["flow"] = target_flow
            client["enable"] = bool(enabled)
            await api_update_client(email, client)


async def _revoke_paid_user_access(user_id: int) -> None:
    paid_key = _paid_user_key(user_id)
    info = load_vpn_users().get(paid_key, {})
    for device in list(info.get("devices", [])):
        email = str(device.get("email") or "")
        if email:
            try:
                await api_del_client_by_email(email)
            except Exception:
                pass
    delete_user_completely(paid_key)
    delete_paid_subscription(user_id)


@router.message(Command("sub"))
async def cmd_sub(message: types.Message):
    await render_paid_user_menu(
        message,
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        last_name=message.from_user.last_name or "",
    )


@router.callback_query(F.data == "paiduser_refresh")
async def cb_paid_user_refresh(call: types.CallbackQuery):
    await call.answer()
    await render_paid_user_menu(
        call.message,
        user_id=call.from_user.id,
        username=call.from_user.username or "",
        first_name=call.from_user.first_name or "",
        last_name=call.from_user.last_name or "",
        edit=True,
    )


@router.callback_query(F.data == "paiduser_inst")
async def cb_paid_user_inst(call: types.CallbackQuery):
    await call.answer()
    user_info = load_vpn_users().get(_paid_user_key(call.from_user.id), {})
    device = next((item for item in user_info.get("devices", []) if item.get("ib_id") is not None), None)
    if not device:
        return await call.answer("⛔ Инструкция пока недоступна.", show_alert=True)
    inbound_id = int(device.get("ib_id", 0) or 0)
    client = await api_get_client(str(device.get("email", "")))
    sub_id = str((client or {}).get("subId") or device.get("email", ""))
    await call.message.edit_text(
        happ_instruction(sub_id, inbound_id),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=_paid_instruction_kb(),
    )


@router.callback_query(F.data == "paiduser_info")
async def cb_paid_user_info(call: types.CallbackQuery):
    await call.answer()
    subscription = get_paid_subscription(call.from_user.id) or {}
    await call.message.edit_text(
        _paid_user_info_text(subscription),
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_user_info_kb(call.from_user.id, subscription),
    )


@router.callback_query(F.data == "paiduser_back")
async def cb_paid_user_back(call: types.CallbackQuery):
    subscription = get_paid_subscription(call.from_user.id) or {}
    request = get_paid_request(call.from_user.id)
    payment_url = subscription.get("payment_url") or load_paid_settings().get("payment_url") or DEFAULT_PAID_PAYMENT_URL
    await call.answer()
    await call.message.edit_text(
        _paid_user_text(subscription, payment_url),
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_user_kb(call.from_user.id, subscription, request),
    )


@router.callback_query(F.data == "paiduser_request")
async def cb_paid_user_request(call: types.CallbackQuery):
    user_id = call.from_user.id
    access_block = get_paid_request_block(user_id, "access")
    if access_block:
        await call.answer(_paid_block_alert_text("access", access_block), show_alert=True)
        return
    if has_paid_subscription(user_id):
        return await call.answer("Подписка уже есть", show_alert=True)
    if get_paid_request(user_id):
        return await call.answer("Заявка уже отправлена", show_alert=True)
    request_id, _ = create_paid_request(
        user_id,
        username=call.from_user.username or "",
        first_name=call.from_user.first_name or "",
        last_name=call.from_user.last_name or "",
        kind="access",
    )
    settings = load_paid_settings()
    if ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            _admin_paid_request_text(
                {
                    "user_id": user_id,
                    "username": call.from_user.username or "",
                    "first_name": call.from_user.first_name or "",
                    "last_name": call.from_user.last_name or "",
                    "request_id": request_id,
                    "kind": "access",
                },
                settings,
                "Новая заявка на платную подписку",
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_paid_request_kb(request_id),
        )
    await call.answer("Заявка отправлена")
    await call.message.edit_text(
        "✅ <b>Заявка отправлена админу.</b>\n\n"
        "Я сообщу, когда доступ будет выдан.",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_user_kb(user_id, None, get_paid_request(user_id)),
    )


@router.callback_query(F.data == "paiduser_wait")
async def cb_paid_user_wait(call: types.CallbackQuery):
    await call.answer("Заявка уже отправлена", show_alert=True)


@router.callback_query(F.data == "paiduser_blocked_access")
async def cb_paid_user_blocked_access(call: types.CallbackQuery):
    block = get_paid_request_block(call.from_user.id, "access")
    await call.answer("Запрос заглушен", show_alert=True)
    if block:
        await call.message.edit_text(
            _paid_block_user_message("access", block),
            parse_mode=ParseMode.HTML,
            reply_markup=_paid_user_kb(call.from_user.id, None, get_paid_request(call.from_user.id)),
        )


@router.callback_query(F.data == "paiduser_blocked_payment")
async def cb_paid_user_blocked_payment(call: types.CallbackQuery):
    block = get_paid_request_block(call.from_user.id, "payment_check") or get_paid_request_block(call.from_user.id, "renew")
    await call.answer("Продление заглушено", show_alert=True)
    if block:
        subscription = get_paid_subscription(call.from_user.id) or {}
        await call.message.edit_text(
            _paid_block_user_message("payment_check", block),
            parse_mode=ParseMode.HTML,
            reply_markup=_paid_user_kb(call.from_user.id, subscription, get_paid_request(call.from_user.id)),
        )


@router.callback_query(F.data.startswith("paiduser_renew_"))
async def cb_paid_user_renew(call: types.CallbackQuery):
    user_id = call.from_user.id
    subscription = get_paid_subscription(user_id) or {}
    if not subscription:
        return await call.answer("Подписки нет", show_alert=True)
    payment_block = get_paid_request_block(user_id, "payment_check") or get_paid_request_block(user_id, "renew")
    if payment_block and paid_subscription_status(subscription) not in {"trial", "active", "grace", "pending_payment"}:
        return await call.answer(_paid_block_alert_text("payment_check", payment_block), show_alert=True)
    if paid_subscription_status(subscription) in {"trial", "active"}:
        await call.answer()
        await call.message.edit_text(
            "✅ <b>Продление не требуется.</b>\n\n"
            "Сейчас у тебя активный пробный период или уже оплаченная подписка.",
            parse_mode=ParseMode.HTML,
            reply_markup=_paid_user_info_kb(user_id, subscription),
        )
        return
    payment_url = subscription.get("payment_url") or load_paid_settings().get("payment_url") or DEFAULT_PAID_PAYMENT_URL
    await call.answer()
    await call.message.edit_text(
        _paid_payment_text(subscription, payment_url),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=_paid_payment_info_kb(user_id),
    )


@router.callback_query(F.data.startswith("paiduser_paid_"))
async def cb_paid_user_paid(call: types.CallbackQuery):
    user_id = call.from_user.id
    subscription = get_paid_subscription(user_id) or {}
    if not subscription:
        return await call.answer("Подписки нет", show_alert=True)
    payment_block = get_paid_request_block(user_id, "payment_check") or get_paid_request_block(user_id, "renew")
    if payment_block and paid_subscription_status(subscription) not in {"trial", "active", "grace", "pending_payment"}:
        return await call.answer(_paid_block_alert_text("payment_check", payment_block), show_alert=True)
    if paid_subscription_status(subscription) in {"trial", "active"}:
        return await call.answer("Продление не требуется", show_alert=True)
    if get_paid_request(user_id):
        return await call.answer("Заявка уже отправлена", show_alert=True)
    request_id, _ = create_paid_request(
        user_id,
        username=call.from_user.username or "",
        first_name=call.from_user.first_name or "",
        last_name=call.from_user.last_name or "",
        kind="payment_check",
    )
    settings = load_paid_settings()
    if ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            _admin_paid_request_text(
                {
                    "user_id": user_id,
                    "username": call.from_user.username or "",
                    "first_name": call.from_user.first_name or "",
                    "last_name": call.from_user.last_name or "",
                    "request_id": request_id,
                    "kind": "payment_check",
                },
                settings,
                "Пользователь сообщил об оплате",
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_paid_payment_kb(request_id),
        )
    await call.answer("Запрос отправлен")
    await call.message.edit_text(
        "✅ <b>Заявка на проверку оплаты отправлена админу.</b>\n\n"
        "Мы проверим платёж в течение 24 часов и продлим подписку после подтверждения.",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_user_kb(user_id, subscription, get_paid_request(user_id)),
    )


@router.message(Command("adminpaysub"))
async def cmd_adminpaysub(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await render_paid_subscriptions(message)


@router.callback_query(F.data == "adminpaysub_refresh")
async def cb_adminpaysub_refresh(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await render_paid_subscriptions(call)


@router.callback_query(F.data == "adminpaysub_settings")
async def cb_adminpaysub_settings(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await _show_paid_settings(call, edit=True)


@router.callback_query(F.data == "adminpaysub_requests")
async def cb_adminpaysub_requests(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    requests = _paid_requests_data()
    await call.answer()
    await call.message.edit_text(
        "📥 <b>Запросы платных подписок</b>\n\n"
        "Выбери, что посмотреть: триал-запросы или запросы на оплату.",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_requests_overview_kb(requests),
    )


@router.callback_query(F.data == "adminpaysub_requests_trial")
async def cb_adminpaysub_requests_trial(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    requests = _paid_requests_data()
    await call.answer()
    await call.message.edit_text(
        "🧪 <b>Триал-запросы</b>\n\n"
        "Ниже показаны все неподтверждённые запросы на первичный триал доступ.",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_requests_list_kb(requests, kind="access"),
    )


@router.callback_query(F.data == "adminpaysub_requests_payment")
async def cb_adminpaysub_requests_payment(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    requests = _paid_requests_data()
    await call.answer()
    await call.message.edit_text(
        "💳 <b>Запросы на оплату</b>\n\n"
        "Ниже показаны все неподтверждённые запросы на проверку оплаты.",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_requests_list_kb(requests, kind="payment_check"),
    )


@router.callback_query(F.data == "adminpaysub_blocks")
async def cb_adminpaysub_blocks(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    blocks = list_paid_request_blocks()
    await call.message.edit_text(
        "🔇 <b>Заглушки заявок</b>\n\n"
        f"Активных заглушек: <b>{len(blocks)}</b>\n\n"
        "Выберите раздел:",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_blocks_overview_kb(blocks),
    )
    await call.answer()


@router.callback_query(F.data == "adminpaysub_blocks_trial")
async def cb_adminpaysub_blocks_trial(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    blocks = list_paid_request_blocks()
    await call.message.edit_text(
        "🔇 <b>Заглушки триала</b>\n\n"
        "Нажмите на нужную запись, чтобы снять блокировку.",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_blocks_list_kb(blocks, kind="access"),
    )
    await call.answer()


@router.callback_query(F.data == "adminpaysub_blocks_payment")
async def cb_adminpaysub_blocks_payment(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    blocks = list_paid_request_blocks()
    await call.message.edit_text(
        "🔇 <b>Заглушки оплаты</b>\n\n"
        "Нажмите на нужную запись, чтобы снять блокировку.",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_blocks_list_kb(blocks, kind="payment_check"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("paidblock_view_"))
async def cb_paid_block_view(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = call.data[len("paidblock_view_"):]
    parts = payload.split("_")
    if len(parts) < 2 or not parts[0].isdigit():
        return await call.answer("Заглушка не найдена", show_alert=True)
    user_id = int(parts[0])
    kind = "_".join(parts[1:]) or "access"
    block = get_paid_request_block(user_id, kind)
    await call.message.edit_text(
        _paid_request_block_text(user_id, kind, block),
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_request_block_kb(user_id, kind, block),
    )
    await call.answer()


@router.callback_query(F.data == "adminpaysub_back")
async def cb_adminpaysub_back(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await render_paid_subscriptions(call)


@router.callback_query(F.data.startswith("paidsub_settings_"))
async def cb_paid_sub_settings(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    user_key = call.data[len("paidsub_settings_"):]
    payload = _paid_subscription_settings_payload(user_key)
    if not payload:
        return await call.answer("Подписка не найдена", show_alert=True)
    text, markup = payload
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("paidsubset_"))
async def cb_paid_sub_settings_edit(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = call.data[len("paidsubset_"):]
    if "_" not in payload:
        return await call.answer("Неизвестная настройка", show_alert=True)
    field, user_key = payload.split("_", 1)
    info = load_vpn_users().get(user_key)
    if not info or str(info.get("subscription_type", "")).lower() != "paid":
        return await call.answer("Подписка не найдена", show_alert=True)
    if field not in {"max", "gb", "ip", "flow"}:
        return await call.answer("Неизвестная настройка", show_alert=True)
    prompts = {
        "max": "Введите новый лимит устройств или <code>-</code> для значения по умолчанию.",
        "gb": "Введите новый лимит трафика или <code>-</code> для бесконечности.\n\nПример: <code>100</code>",
        "ip": "Введите новый лимит IP или <code>-</code> для значения по умолчанию.",
        "flow": "Введите новый flow или <code>-</code> для значения по умолчанию.",
    }
    await state.update_data(
        target_paid_subscription_key=user_key,
        target_paid_subscription_field=field,
    )
    await state.set_state(PaidSubSettings.waiting_subscription_value)
    await call.message.edit_text(
        f"{prompts[field]}\n\nДля выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data.startswith("paidsub_addtime_"))
async def cb_paid_sub_addtime(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    user_key = call.data[len("paidsub_addtime_"):]
    info = load_vpn_users().get(user_key)
    if not info or str(info.get("subscription_type", "")).lower() != "paid":
        return await call.answer("Подписка не найдена", show_alert=True)
    if _extract_paid_user_id(user_key) is None:
        return await call.answer("Для этой подписки действие недоступно", show_alert=True)
    await state.update_data(target_paid_action_key=user_key, target_paid_action_type="addtime")
    await state.set_state(PaidSubSettings.waiting_action_value)
    await call.message.edit_text(
        "➕ <b>Добавить срок подписке</b>\n\n"
        "Отправь, сколько нужно добавить к текущему периоду: например <code>1 день</code>, <code>12 часов</code>, <code>30 минут</code>.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.message(PaidSubSettings.waiting_request_mute_value)
async def paid_request_mute_value(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    user_id = int(data.get("target_paid_request_mute_user_id") or 0)
    kind = str(data.get("target_paid_request_mute_kind") or "access")
    if not user_id:
        await message.answer("Пользователь не найден.")
        return
    raw = (message.text or "").strip()
    try:
        seconds = parse_duration_to_seconds(raw)
    except ValueError:
        await message.answer("Некорректное значение.\n\nПример: <code>2 минуты</code>, <code>5 дней</code>, <code>1 час</code>.", parse_mode=ParseMode.HTML)
        return
    until_at = int(time.time()) + seconds
    block = set_paid_request_block(user_id, kind, until_at, admin_id=message.from_user.id)
    await state.clear()
    await message.answer(
        f"✅ Заглушка установлена до <b>{_format_short_dt(block.get('until_at'))}</b>.",
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("paidsub_freeze_"))
async def cb_paid_sub_freeze(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    user_key = call.data[len("paidsub_freeze_"):]
    info = load_vpn_users().get(user_key)
    if not info or str(info.get("subscription_type", "")).lower() != "paid":
        return await call.answer("Подписка не найдена", show_alert=True)
    user_id = _extract_paid_user_id(user_key)
    if user_id is None:
        return await call.answer("Для этой подписки действие недоступно", show_alert=True)
    subscription = get_paid_subscription(user_id) or {}
    if not subscription:
        return await call.answer("Подписка не найдена", show_alert=True)
    now = int(time.time())
    current_status = paid_subscription_status(subscription)
    data = load_paid_subscriptions()
    current = data.get(str(user_id), subscription)
    if current_status == "frozen":
        frozen_at = int(current.get("frozen_at") or now)
        delta = max(0, now - frozen_at)
        shift_paid_subscription_timeline(current, delta)
        current["status"] = str(current.get("frozen_prev_status") or "active")
        current["active"] = True
        current["last_activity_at"] = now
        current.pop("frozen_at", None)
        current.pop("frozen_prev_status", None)
        save_paid_subscriptions(data)
        await _sync_paid_subscription_devices(
            user_id,
            current,
            enabled=True,
            limit_ip=int(current.get("limit_ip") or 0),
            limit_gb=float(current.get("limit_gb") or 0),
            flow=str(current.get("flow") or DEFAULT_PAID_FLOW),
        )
        await call.answer("Подписка разморожена")
    else:
        current["frozen_at"] = now
        current["frozen_prev_status"] = current_status
        current["status"] = "frozen"
        current["active"] = False
        current["last_activity_at"] = now
        save_paid_subscriptions(data)
        await _sync_paid_subscription_devices(
            user_id,
            current,
            enabled=False,
            limit_ip=int(current.get("limit_ip") or 0),
            limit_gb=float(current.get("limit_gb") or 0),
            flow=str(current.get("flow") or DEFAULT_PAID_FLOW),
        )
        await call.answer("Подписка заморожена")
    await _render_paid_subscription_detail(call, user_key)


@router.callback_query(F.data.startswith("paidreq_view_"))
async def cb_paid_request_view(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    request_id = call.data[len("paidreq_view_"):]
    await _show_paid_request_details(call, request_id)


@router.callback_query(F.data.startswith("paidreq_mute_"))
async def cb_paid_request_mute(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    request_id = call.data[len("paidreq_mute_"):]
    request = get_paid_request_by_id(request_id)
    if not request:
        block_match = None
        for block in list_paid_request_blocks().values():
            if str(block.get("request_id") or "") == request_id:
                block_match = block
                break
        if block_match:
            user_id = int(block_match.get("user_id") or 0)
            kind = str(block_match.get("kind") or "access")
        else:
            return await call.answer("Запрос не найден", show_alert=True)
    else:
        user_id = int(request.get("user_id") or 0)
        kind = str(request.get("kind") or "access")

    block = get_paid_request_block(user_id, kind)
    if block:
        clear_paid_request_block(user_id, kind)
        await call.answer("Заглушка снята")
        if request:
            await _show_paid_request_details(call, request_id)
        else:
            blocks = list_paid_request_blocks()
            await call.message.edit_text(
                "🔇 <b>Заглушки заявок</b>\n\nБлокировка снята.",
                parse_mode=ParseMode.HTML,
                reply_markup=_paid_blocks_overview_kb(blocks),
            )
        return

    await state.update_data(target_paid_request_mute_user_id=user_id, target_paid_request_mute_kind=kind)
    await state.set_state(PaidSubSettings.waiting_request_mute_value)
    await _open_paid_request_block_prompt(call, user_id, kind)
    await call.answer()


@router.callback_query(F.data.startswith("paidblock_mute_"))
async def cb_paid_block_mute(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    user_id, kind = _parse_paid_request_block_target(call.data[len("paidblock_mute_"):])
    if not user_id:
        return await call.answer("Пользователь не найден", show_alert=True)
    await state.update_data(target_paid_request_mute_user_id=user_id, target_paid_request_mute_kind=kind)
    await state.set_state(PaidSubSettings.waiting_request_mute_value)
    await _open_paid_request_block_prompt(call, user_id, kind)
    await call.answer()


@router.callback_query(F.data.startswith("paidblock_clear_"))
async def cb_paid_block_clear(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    user_id, kind = _parse_paid_request_block_target(call.data[len("paidblock_clear_"):])
    if not user_id:
        return await call.answer("Пользователь не найден", show_alert=True)
    clear_paid_request_block(user_id, kind)
    await call.answer("Заглушка снята")
    blocks = list_paid_request_blocks()
    await call.message.edit_text(
        "🔇 <b>Заглушки заявок</b>\n\nБлокировка снята.",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_blocks_overview_kb(blocks),
    )


@router.callback_query(F.data.startswith("paidset_"))
async def cb_paid_settings_edit(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    field = call.data[len("paidset_"):]
    if field not in {"trial_seconds", "payment_seconds", "payment_amount", "grace_seconds", "payment_url", "max_devices", "limit_gb", "limit_ip", "flow"}:
        return await call.answer("Неизвестная настройка", show_alert=True)
    await state.update_data(target_paid_setting_field=field)
    await state.set_state(PaidSubSettings.waiting_value)
    await call.message.edit_text(
        f"{_paid_setting_prompt(field)}\n\nДля выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data.startswith("paiddef_"))
async def cb_paid_settings_default(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    field = call.data[len("paiddef_"):]
    settings = load_paid_settings()
    if field not in {"trial_seconds", "payment_seconds", "payment_amount", "max_devices", "limit_gb", "limit_ip", "flow", "grace_seconds", "payment_url"}:
        return await call.answer("Неизвестная настройка", show_alert=True)
    settings[field] = _paid_setting_default(field)
    save_paid_settings(settings)
    await call.answer("Применено")
    await _show_paid_settings(call, edit=True)


@router.message(PaidSubSettings.waiting_value)
async def paid_settings_value(message: types.Message, state):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    field = str(data.get("target_paid_setting_field") or "")
    if not field:
        await message.answer("Настройка не найдена.")
        return
    raw = (message.text or "").strip()
    settings = load_paid_settings()
    try:
        if field in {"trial_seconds", "payment_seconds", "payment_amount", "max_devices", "limit_gb", "limit_ip", "flow", "grace_seconds"}:
            if raw == "-":
                defaults = {
                    "trial_seconds": DEFAULT_PAID_TRIAL_SECONDS,
                    "payment_seconds": DEFAULT_PAID_PAYMENT_SECONDS,
                    "payment_amount": DEFAULT_PAID_PAYMENT_AMOUNT,
                    "max_devices": DEFAULT_PAID_MAX_DEVICES,
                    "limit_gb": DEFAULT_PAID_LIMIT_GB,
                    "limit_ip": DEFAULT_PAID_LIMIT_IP,
                    "flow": DEFAULT_PAID_FLOW,
                    "grace_seconds": DEFAULT_PAID_GRACE_SECONDS,
                }
                settings[field] = defaults[field]
            elif field == "payment_amount":
                settings[field] = int(raw)
            elif field == "max_devices":
                settings[field] = _parse_max_devices(raw)
            elif field == "limit_gb":
                settings[field] = _parse_limit_gb(raw)
            elif field == "limit_ip":
                settings[field] = _parse_limit_ip(raw)
            elif field == "flow":
                settings[field] = DEFAULT_PAID_FLOW if raw == "-" else raw
            else:
                settings[field] = parse_duration_to_seconds(raw)
        elif field == "payment_url":
            settings[field] = "" if raw == "-" else raw
        else:
            await message.answer("Неизвестная настройка.")
            return
    except ValueError:
        await message.answer("Некорректное значение.\n\nДля выхода введите /cancel")
        return
    save_paid_settings(settings)
    await state.clear()
    await _show_paid_settings(message, edit=False)


@router.message(PaidSubSettings.waiting_action_value)
async def paid_subscription_action_value(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    action_type = str(data.get("target_paid_action_type") or "")
    user_key = str(data.get("target_paid_action_key") or "")
    if action_type != "addtime" or not user_key:
        await message.answer("Действие не найдено.")
        return
    user_id = _extract_paid_user_id(user_key)
    if user_id is None:
        await message.answer("Для этой подписки действие недоступно.")
        return
    raw = (message.text or "").strip()
    try:
        seconds = parse_duration_to_seconds(raw)
    except ValueError:
        await message.answer("Некорректный срок. Пример: <code>1 день</code>, <code>12 часов</code>, <code>30 минут</code>.")
        return

    all_data = load_paid_subscriptions()
    subscription = all_data.get(str(user_id))
    if not subscription:
        await message.answer("Подписка не найдена.")
        await state.clear()
        return

    subscription = _apply_paid_subscription_extension(subscription, seconds)
    all_data[str(user_id)] = subscription
    save_paid_subscriptions(all_data)

    await _sync_paid_subscription_devices(
        user_id,
        subscription,
        enabled=paid_subscription_status(subscription) != "frozen",
        limit_ip=int(subscription.get("limit_ip") or 0),
        limit_gb=float(subscription.get("limit_gb") or 0),
        flow=str(subscription.get("flow") or DEFAULT_PAID_FLOW),
    )
    await state.clear()
    payload = _paid_subscription_detail_payload(user_key)
    if not payload:
        await message.answer("✅ Действие выполнено.")
        return
    text, markup = payload
    await message.answer(
        f"✅ Добавлено: <b>{format_duration(seconds)}</b>\n\n{text}",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


@router.message(PaidSubSettings.waiting_subscription_value)
async def paid_subscription_settings_value(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    user_key = str(data.get("target_paid_subscription_key") or "")
    field = str(data.get("target_paid_subscription_field") or "")
    if not user_key or not field:
        await message.answer("Подписка не найдена.")
        return
    info = load_vpn_users().get(user_key)
    if not info or str(info.get("subscription_type", "")).lower() != "paid":
        await message.answer("Подписка не найдена.")
        await state.clear()
        return
    raw = (message.text or "").strip()
    user_id = _extract_paid_user_id(user_key)
    subscription = get_paid_subscription(user_id) if user_id is not None else None
    current = subscription or info
    try:
        if field == "max":
            value = DEFAULT_PAID_MAX_DEVICES if raw == "-" else max(1, int(raw))
            current["max_devices"] = value
            set_user_max_devices(user_key, value)
        elif field == "gb":
            value = DEFAULT_PAID_LIMIT_GB if raw == "-" else _parse_limit_gb(raw)
            current["limit_gb"] = value
            set_user_limit_gb(user_key, value)
        elif field == "ip":
            value = DEFAULT_PAID_LIMIT_IP if raw == "-" else _parse_limit_ip(raw)
            current["limit_ip"] = value
            set_user_limit_ip(user_key, value)
        elif field == "flow":
            value = DEFAULT_PAID_FLOW if raw == "-" else raw
            current["flow"] = value
            set_user_flow(user_key, value)
        else:
            await message.answer("Неизвестная настройка.")
            return
        current["last_activity_at"] = int(time.time())
        if user_id is not None:
            all_data = load_paid_subscriptions()
            all_data[str(user_id)] = current
            save_paid_subscriptions(all_data)
        else:
            users = load_vpn_users()
            if user_key in users:
                users[user_key].update(
                    {
                        "max_devices": current.get("max_devices"),
                        "limit_gb": current.get("limit_gb"),
                        "limit_ip": current.get("limit_ip"),
                        "flow": current.get("flow"),
                        "last_activity_at": current.get("last_activity_at"),
                    }
                )
                save_vpn_users(users)
        if user_id is not None:
            await _sync_paid_subscription_devices(
                user_id,
                current,
                enabled=paid_subscription_status(current) != "frozen",
                limit_ip=int(current.get("limit_ip") or 0),
                limit_gb=float(current.get("limit_gb") or 0),
                flow=str(current.get("flow") or DEFAULT_PAID_FLOW),
            )
    except ValueError:
        await message.answer("Некорректное значение.\n\nДля выхода введите /cancel")
        return
    await state.clear()
    payload = _paid_subscription_detail_payload(user_key)
    if not payload:
        await message.answer("✅ Настройка сохранена.")
        return
    text, markup = payload
    await message.answer(
        f"✅ Настройка сохранена.\n\n{text}",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


@router.callback_query(F.data.regexp(r"^paidsub_(?!settings_|addtime_|freeze_|subset_|set_).+$"))
async def cb_paid_sub_details(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    user_key = call.data[len("paidsub_"):]
    await _render_paid_subscription_detail(call, user_key)


@router.callback_query(F.data.startswith("paidreq_ok_"))
async def cb_paid_request_ok(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    request_id = call.data[len("paidreq_ok_"):]
    request = get_paid_request_by_id(request_id)
    if not request:
        return await call.answer("Заявка не найдена", show_alert=True)
    user_id = int(request.get("user_id") or 0)
    kind = str(request.get("kind") or "access")
    settings = load_paid_settings()
    _log_paid(f"request approved by admin={call.from_user.id} user_id={user_id} kind={kind!r} request_id={request_id!r}")
    if kind in {"renew", "payment_check"}:
        existing = get_paid_subscription(user_id) or {}
        updated = extend_paid_subscription(existing, settings, from_now=(kind == "renew"))
        updated["subscription_type"] = "paid"
        updated["payment_url"] = str(settings["payment_url"])
        updated["max_devices"] = int(settings.get("max_devices") or DEFAULT_PAID_MAX_DEVICES)
        updated["limit_ip"] = int(settings.get("limit_ip") or DEFAULT_PAID_LIMIT_IP)
        updated["limit_gb"] = float(settings.get("limit_gb") or DEFAULT_PAID_LIMIT_GB)
        updated["flow"] = str(settings.get("flow") or DEFAULT_PAID_FLOW)
        updated["renewals_count"] = int(updated.get("renewals_count") or 0) + 1
        updated["total_paid_amount"] = int(updated.get("total_paid_amount") or 0) + int(settings.get("payment_amount") or DEFAULT_PAID_PAYMENT_AMOUNT)
        updated["last_activity_at"] = int(time.time())
        set_paid_subscription(user_id, updated)
        device_expiry_ms = int(updated.get("grace_ends_at") or updated.get("paid_ends_at") or 0) * 1000
        await _sync_paid_user_devices_expiry(
            user_id,
            device_expiry_ms,
            limit_ip=int(settings.get("limit_ip") or DEFAULT_PAID_LIMIT_IP),
            limit_gb=float(settings.get("limit_gb") or DEFAULT_PAID_LIMIT_GB),
            flow=str(settings.get("flow") or DEFAULT_PAID_FLOW),
        )
        user_message = (
            "✅ <b>Твоя платная подписка продлена.</b>\n\n"
            f"Новый срок окончания: <b>{_format_dt(updated.get('paid_ends_at'))}</b>\n"
            "Зайди в /sub, чтобы посмотреть статус."
        )
    else:
        try:
            await _create_paid_device_for_user(user_id, settings, request)
        except Exception as exc:
            _log_paid(f"trial creation exception user_id={user_id} exc={exc!r}")
            await call.answer("Не удалось создать устройство", show_alert=True)
            await call.message.edit_text(
                "❌ <b>Не удалось создать trial-устройство</b>\n\n"
                f"Пользователь: <code>{html.escape(str(user_id))}</code>\n"
                f"Ошибка: <code>{html.escape(str(exc))}</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        set_paid_subscription(user_id, build_paid_subscription(settings, kind="access", source=request))
        _log_paid(f"trial subscription saved user_id={user_id}")
        user_message = (
            "✅ <b>Твой триал доступ выдан.</b>\n\n"
            "Сейчас доступ активирован на trial-период.\n"
            "Зайди в /sub, чтобы посмотреть статус."
        )
    delete_paid_request(user_id)
    _log_paid(f"request removed user_id={user_id}")
    await bot.send_message(user_id, user_message, parse_mode=ParseMode.HTML)
    await call.message.edit_text(
        "✅ <b>Заявка одобрена</b>\n\n"
        f"Пользователь: <code>{html.escape(str(user_id))}</code>",
        parse_mode=ParseMode.HTML,
    )
    await call.answer("Заявка одобрена")


@router.callback_query(F.data.startswith("paidreq_no_"))
async def cb_paid_request_no(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    request_id = call.data[len("paidreq_no_"):]
    request = get_paid_request_by_id(request_id)
    if not request:
        return await call.answer("Заявка не найдена", show_alert=True)
    user_id = int(request.get("user_id") or 0)
    _log_paid(f"request denied by admin={call.from_user.id} user_id={user_id} kind={request.get('kind')!r}")
    delete_paid_request(user_id)
    try:
        await call.answer("Заявка отклонена")
    except Exception:
        pass
    await bot.send_message(
        user_id,
        "⛔ <b>Ваша заявка отклонена.</b>\n\n"
        "Если нужно, попробуйте отправить её ещё раз позже.",
        parse_mode=ParseMode.HTML,
    )
    await call.message.edit_text(
        "❌ <b>Заявка отклонена</b>\n\n"
        f"Пользователь: <code>{html.escape(str(user_id))}</code>\n"
        f"Тип: <b>{html.escape(str(request.get('kind') or 'access'))}</b>",
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("paidpay_ok_"))
async def cb_paid_payment_ok(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    request_id = call.data[len("paidpay_ok_"):]
    request = get_paid_request_by_id(request_id)
    if not request:
        return await call.answer("Заявка не найдена", show_alert=True)
    user_id = int(request.get("user_id") or 0)
    settings = load_paid_settings()
    _log_paid(f"payment confirmed by admin={call.from_user.id} user_id={user_id} request_id={request_id!r}")
    existing = get_paid_subscription(user_id) or {}
    updated = extend_paid_subscription(existing, settings, from_now=True)
    updated["subscription_type"] = "paid"
    updated["payment_url"] = str(settings["payment_url"])
    updated["status"] = "active"
    updated["max_devices"] = int(settings.get("max_devices") or DEFAULT_PAID_MAX_DEVICES)
    updated["limit_ip"] = int(settings.get("limit_ip") or DEFAULT_PAID_LIMIT_IP)
    updated["limit_gb"] = float(settings.get("limit_gb") or DEFAULT_PAID_LIMIT_GB)
    updated["flow"] = str(settings.get("flow") or DEFAULT_PAID_FLOW)
    updated["renewals_count"] = int(updated.get("renewals_count") or 0) + 1
    updated["total_paid_amount"] = int(updated.get("total_paid_amount") or 0) + int(settings.get("payment_amount") or DEFAULT_PAID_PAYMENT_AMOUNT)
    updated["last_activity_at"] = int(time.time())
    set_paid_subscription(user_id, updated)
    device_expiry_ms = int(updated.get("grace_ends_at") or updated.get("paid_ends_at") or 0) * 1000
    await _sync_paid_user_devices_expiry(
        user_id,
        device_expiry_ms,
        limit_ip=int(settings.get("limit_ip") or DEFAULT_PAID_LIMIT_IP),
        limit_gb=float(settings.get("limit_gb") or DEFAULT_PAID_LIMIT_GB),
        flow=str(settings.get("flow") or DEFAULT_PAID_FLOW),
    )
    delete_paid_request(user_id)
    await bot.send_message(
        user_id,
        "✅ <b>Оплата подтверждена.</b>\n\n"
        f"Подписка продлена до <b>{_format_dt(updated.get('paid_ends_at'))}</b>.\n"
        "Зайди в /sub, чтобы посмотреть статус.",
        parse_mode=ParseMode.HTML,
    )
    await call.message.edit_text(
        "✅ <b>Оплата проверена</b>\n\n"
        f"Пользователь: <code>{html.escape(str(user_id))}</code>",
        parse_mode=ParseMode.HTML,
    )
    await call.answer("Оплата подтверждена")


@router.callback_query(F.data.startswith("paidpay_no_"))
async def cb_paid_payment_no(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    request_id = call.data[len("paidpay_no_"):]
    request = get_paid_request_by_id(request_id)
    if not request:
        return await call.answer("Заявка не найдена", show_alert=True)
    user_id = int(request.get("user_id") or 0)
    delete_paid_request(user_id)
    await bot.send_message(
        user_id,
        "⛔ <b>Оплата не найдена.</b>\n\n"
        "Проверь платёж и попробуй ещё раз.",
        parse_mode=ParseMode.HTML,
    )
    await call.message.edit_text(
        "❌ <b>Оплата не найдена</b>\n\n"
        f"Пользователь: <code>{html.escape(str(user_id))}</code>",
        parse_mode=ParseMode.HTML,
    )
    await call.answer("Оплата не найдена")
