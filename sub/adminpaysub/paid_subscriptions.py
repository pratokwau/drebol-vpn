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
    get_paid_request,
    get_paid_request_by_id,
    get_paid_subscription,
    has_paid_subscription,
    paid_subscription_status,
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


def _current_tariff_label(subscription: dict) -> str:
    status = paid_subscription_status(subscription)
    if status in {"active", "grace", "pending_payment"}:
        return "Premium"
    if status == "expired":
        return "Требует продления"
    return "Пробный доступ"


def _current_tariff_icon(subscription: dict) -> str:
    status = paid_subscription_status(subscription)
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
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="adminpaysub_settings"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _paid_request_kb(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выдать", callback_data=f"paidreq_ok_{request_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"paidreq_no_{request_id}"),
            ],
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


def _paid_payment_kb(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Оплата проверена", callback_data=f"paidpay_ok_{request_id}"),
                InlineKeyboardButton(text="❌ Оплата не найдена", callback_data=f"paidpay_no_{request_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ К запросам", callback_data="adminpaysub_requests")],
        ]
    )


def _paid_settings_kb() -> InlineKeyboardMarkup:
    settings = load_paid_settings()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🧪 Trial: {format_duration(settings['trial_seconds'])}", callback_data="paidset_trial_seconds")],
            [InlineKeyboardButton(text=f"⏳ Оплата: {format_duration(settings['payment_seconds'])}", callback_data="paidset_payment_seconds")],
            [InlineKeyboardButton(text=f"💰 Сумма: {settings['payment_amount']} ₽", callback_data="paidset_payment_amount")],
            [InlineKeyboardButton(text=f"🕒 Grace: {format_duration(settings['grace_seconds'])}", callback_data="paidset_grace_seconds")],
            [InlineKeyboardButton(text=f"🔗 Оплата: {'задана' if settings['payment_url'] else 'не задана'}", callback_data="paidset_payment_url")],
            [
                InlineKeyboardButton(text=f"📱 Лимит устройств: {settings['max_devices']}", callback_data="paidset_max_devices"),
                InlineKeyboardButton(text="По дефолту", callback_data="paiddef_max_devices"),
            ],
            [
                InlineKeyboardButton(text=f"💾 Лимит ГБ: {_format_limit_gb(settings['limit_gb'])}", callback_data="paidset_limit_gb"),
                InlineKeyboardButton(text="По дефолту", callback_data="paiddef_limit_gb"),
            ],
            [
                InlineKeyboardButton(text=f"🌐 Лимит IP: {settings['limit_ip']}", callback_data="paidset_limit_ip"),
                InlineKeyboardButton(text="По дефолту", callback_data="paiddef_limit_ip"),
            ],
            [
                InlineKeyboardButton(text=f"⚡ Flow: {settings['flow']}", callback_data="paidset_flow"),
                InlineKeyboardButton(text="По дефолту", callback_data="paiddef_flow"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adminpaysub_back")],
        ]
    )


def _paid_setting_prompt(field: str) -> str:
    if field == "trial_seconds":
        return "Введите длительность trial любым форматом: <code>12 часов</code>, <code>1 день</code>, <code>1 месяц</code>. Можно <code>-</code> для значения по умолчанию."
    if field == "payment_seconds":
        return "Введите срок платной подписки любым форматом: <code>12 часов</code>, <code>1 день</code>, <code>1 месяц</code>. Можно <code>-</code> для значения по умолчанию."
    if field == "payment_amount":
        return "Введите сумму оплаты в рублях или <code>-</code> для значения по умолчанию."
    if field == "grace_seconds":
        return "Введите время на оплату любым форматом: <code>12 часов</code>, <code>1 день</code>, <code>36 часов</code>. Можно <code>-</code> для значения по умолчанию."
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
        f"🧪 Trial: <b>{format_duration(settings['trial_seconds'])}</b>\n"
        f"⏳ Оплата: <b>{format_duration(settings['payment_seconds'])}</b>\n"
        f"💰 Сумма: <b>{settings['payment_amount']} ₽</b>\n"
        f"🕒 Grace: <b>{format_duration(settings['grace_seconds'])}</b>\n"
        f"🔗 Ссылка: <b>{'задана' if settings['payment_url'] else 'не задана'}</b>\n"
        f"📱 Лимит устройств: <b>{settings['max_devices']}</b>\n"
        f"💾 Лимит ГБ: <b>{_format_limit_gb(settings['limit_gb'])}</b>\n"
        f"🌐 Лимит IP: <b>{settings['limit_ip']}</b>\n"
        f"⚡ Flow: <b>{settings['flow']}</b>"
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
    settings = load_paid_settings()
    title = "Новая заявка на первичный триал доступ" if kind == "access" else "Пользователь сообщил об оплате"
    text = _admin_paid_request_text(request, settings, title)
    markup = _paid_request_kb(request_id) if kind == "access" else _paid_payment_kb(request_id)
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await call.answer()


def _subscription_summary(subscription: dict) -> str:
    status = paid_subscription_status(subscription)
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
    if not subscription:
        rows.append([InlineKeyboardButton(text="💳 Получить подписку", callback_data="paiduser_request")])
    else:
        rows.append([InlineKeyboardButton(text="ℹ️ Информация о подписке", callback_data="paiduser_info")])
        rows.append([InlineKeyboardButton(text="💳 Продлить подписку", callback_data=f"paiduser_renew_{user_id}")])
        if paid_user.get("devices"):
            rows.append([InlineKeyboardButton(text="📖 Инструкция", callback_data="paiduser_inst")])
    if request:
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
    if not subscription and not request:
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
    text = _paid_user_text(subscription, payment_url)
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
            client["enable"] = True
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
        return await call.message.answer("⛔ Инструкция пока недоступна.")
    inbound_id = int(device.get("ib_id", 0) or 0)
    client = await api_get_client(str(device.get("email", "")))
    sub_id = str((client or {}).get("subId") or device.get("email", ""))
    await call.message.answer(
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


@router.callback_query(F.data.startswith("paiduser_renew_"))
async def cb_paid_user_renew(call: types.CallbackQuery):
    user_id = call.from_user.id
    subscription = get_paid_subscription(user_id) or {}
    if not subscription:
        return await call.answer("Подписки нет", show_alert=True)
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


@router.callback_query(F.data == "adminpaysub_back")
async def cb_adminpaysub_back(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await render_paid_subscriptions(call)


@router.callback_query(F.data.startswith("paidreq_view_"))
async def cb_paid_request_view(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    request_id = call.data[len("paidreq_view_"):]
    await _show_paid_request_details(call, request_id)


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


@router.callback_query(F.data.startswith("paidsub_"))
async def cb_paid_sub_details(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    user_key = call.data[len("paidsub_"):]
    info = load_vpn_users().get(user_key)
    if not info or str(info.get("subscription_type", "")).lower() != "paid":
        return await call.answer("Подписка не найдена", show_alert=True)
    username = str(info.get("username") or "").strip()
    note = str(info.get("note") or "").strip()
    subscription = get_paid_subscription(int(user_key)) if str(user_key).isdigit() else info
    display_name = note or username or user_key
    text = (
        "💳 <b>Платная подписка</b>\n\n"
        f"👤 Пользователь: <code>{html.escape(display_name)}</code>"
        + "\n"
        f"📦 Тип: <b>{info.get('subscription_type', 'paid')}</b>\n"
        f"📱 Устройств: <b>{len(info.get('devices', []))}</b>"
    )
    if subscription:
        text += "\n\n" + _subscription_summary(subscription)
    if note:
        text += f"\n📝 Заметка: <i>{html.escape(note)}</i>"
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_paid_subscriptions_kb(get_users_by_subscription_type("paid")))
    await call.answer()


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
        set_paid_subscription(user_id, updated)
        await _sync_paid_user_devices_expiry(
            user_id,
            int(updated.get("paid_ends_at") or 0) * 1000,
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
    set_paid_subscription(user_id, updated)
    await _sync_paid_user_devices_expiry(
        user_id,
        int(updated.get("paid_ends_at") or 0) * 1000,
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
