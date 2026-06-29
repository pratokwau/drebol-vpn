from __future__ import annotations

import html
from datetime import datetime, timezone

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID
from loader import bot
from xui.paid_settings_store import (
    DEFAULT_PAID_GRACE_SECONDS,
    DEFAULT_PAID_PAYMENT_AMOUNT,
    DEFAULT_PAID_PAYMENT_URL,
    DEFAULT_PAID_PAYMENT_SECONDS,
    DEFAULT_PAID_TRIAL_SECONDS,
    format_duration,
    load_paid_settings,
    parse_duration_to_seconds,
    save_paid_settings,
)
from xui.paid_storage import (
    build_paid_subscription,
    create_paid_request,
    delete_paid_request,
    extend_paid_subscription,
    get_paid_request,
    get_paid_request_by_id,
    get_paid_subscription,
    has_paid_subscription,
    paid_subscription_status,
    set_paid_subscription,
)
from xui.states import PaidSubSettings
from xui.storage import get_users_by_subscription_type, load_vpn_users
from xui.utils import is_admin


router = Router()


def _format_dt(ts: int | None) -> str:
    value = int(ts or 0)
    if value <= 0:
        return "не задано"
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M")


def _paid_subscriptions_kb(users: dict) -> InlineKeyboardMarkup:
    rows = []
    for user_key, info in sorted(users.items()):
        if user_key.startswith("anon_"):
            label = "💳 Без TG ID"
        else:
            username = str(info.get("username") or "").strip()
            label = f"💳 TG {user_key}" + (f" (@{username})" if username else "")
        rows.append([InlineKeyboardButton(text=label, callback_data=f"paidsub_{user_key}")])
    rows.append([
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="adminpaysub_settings"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="adminpaysub_refresh"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _paid_request_kb(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выдать", callback_data=f"paidreq_ok_{request_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"paidreq_no_{request_id}"),
            ]
        ]
    )


def _paid_payment_kb(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Оплата проверена", callback_data=f"paidpay_ok_{request_id}"),
                InlineKeyboardButton(text="❌ Оплата не найдена", callback_data=f"paidpay_no_{request_id}"),
            ]
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
    return "Введите значение."


async def _show_paid_settings(call_or_message, *, edit: bool = True):
    settings = load_paid_settings()
    text = (
        "⚙️ <b>Настройки платных подписок</b>\n\n"
        f"🧪 Trial: <b>{format_duration(settings['trial_seconds'])}</b>\n"
        f"⏳ Оплата: <b>{format_duration(settings['payment_seconds'])}</b>\n"
        f"💰 Сумма: <b>{settings['payment_amount']} ₽</b>\n"
        f"🕒 Grace: <b>{format_duration(settings['grace_seconds'])}</b>\n"
        f"🔗 Ссылка: <b>{'задана' if settings['payment_url'] else 'не задана'}</b>"
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


def _subscription_summary(subscription: dict) -> str:
    status = paid_subscription_status(subscription).capitalize()
    return (
        f"📌 Статус: <b>{status}</b>\n"
        f"🧪 Trial: <b>{format_duration(subscription.get('trial_seconds'))}</b>\n"
        f"⏳ Платёжный период: <b>{format_duration(subscription.get('payment_seconds'))}</b>\n"
        f"💰 Сумма: <b>{subscription.get('payment_amount', 'не задана')} ₽</b>\n"
        f"🕒 Grace: <b>{format_duration(subscription.get('grace_seconds'))}</b>\n"
        f"📅 Trial до: <b>{_format_dt(subscription.get('trial_ends_at'))}</b>\n"
        f"📅 Платёж до: <b>{_format_dt(subscription.get('paid_ends_at'))}</b>\n"
        f"📅 Grace до: <b>{_format_dt(subscription.get('grace_ends_at'))}</b>"
    )


def _paid_user_kb(user_id: int, subscription: dict | None, request: dict | None = None) -> InlineKeyboardMarkup:
    rows = []
    if not subscription:
        rows.append([InlineKeyboardButton(text="💳 Получить подписку", callback_data="paiduser_request")])
    else:
        rows.append([InlineKeyboardButton(text="💳 Продлить подписку", callback_data=f"paiduser_renew_{user_id}")])
        rows.append([InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paiduser_paid_{user_id}")])
    if request:
        rows.insert(0, [InlineKeyboardButton(text="⏳ Заявка уже отправлена", callback_data="paiduser_wait")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="paiduser_refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_paid_request_text(request: dict, settings: dict, title: str) -> str:
    user_id = int(request.get("user_id") or 0)
    username = str(request.get("username") or "").strip() or "нет"
    kind = str(request.get("kind") or "access")
    return (
        f"💳 <b>{title}</b>\n\n"
        f"👤 TG: <code>{user_id}</code>\n"
        f"👤 Username: <code>{html.escape(username)}</code>\n"
        f"🧾 Тип: <b>{html.escape(kind)}</b>\n"
        f"🧪 Trial: <b>{format_duration(settings['trial_seconds'])}</b>\n"
        f"⏳ Платёжный период: <b>{format_duration(settings['payment_seconds'])}</b>\n"
        f"💰 Сумма: <b>{settings['payment_amount']} ₽</b>\n"
        f"🕒 Grace: <b>{format_duration(settings['grace_seconds'])}</b>\n"
        f"🆔 Request: <code>{html.escape(str(request.get('request_id') or ''))}</code>"
    )


@router.message(Command("sub"))
async def cmd_sub(message: types.Message):
    user_id = message.from_user.id
    subscription = get_paid_subscription(user_id) or {}
    request = get_paid_request(user_id)
    if not subscription and not request:
        request_id, _ = create_paid_request(
            user_id,
            username=message.from_user.username or "",
            first_name=message.from_user.first_name or "",
            last_name=message.from_user.last_name or "",
            kind="access",
        )
        await message.answer(
            "✅ <b>Заявка на платную подписку отправлена админу.</b>\n\n"
            "Ожидай подтверждения, я сообщу тебе, когда доступ будет выдан.",
            parse_mode=ParseMode.HTML,
            reply_markup=_paid_user_kb(user_id, None, get_paid_request(user_id)),
        )
        settings = load_paid_settings()
        if ADMIN_ID:
            await bot.send_message(
                ADMIN_ID,
                _admin_paid_request_text({"user_id": user_id, "username": message.from_user.username or "", "request_id": request_id, "kind": "access"}, settings, "Новая заявка на платную подписку"),
                parse_mode=ParseMode.HTML,
                reply_markup=_paid_request_kb(request_id),
            )
        return

    status = paid_subscription_status(subscription) if subscription else "none"
    payment_url = subscription.get("payment_url") or load_paid_settings().get("payment_url") or DEFAULT_PAID_PAYMENT_URL
    text = (
        "💳 <b>Платная подписка</b>\n\n"
        f"{_subscription_summary(subscription)}\n"
        f"🔗 Оплата: <b>{html.escape(str(payment_url)) if payment_url else 'не задана'}</b>\n\n"
    )
    if request:
        text += "⏳ <b>Заявка уже отправлена админу.</b>\n"
    elif status in {"expired", "grace", "pending_payment"}:
        text += "Чтобы продлить подписку, нажми «Продлить подписку», а после оплаты — «Я оплатил»."
    else:
        text += "Подписка активна. Если нужно, можно заранее отправить запрос на продление."
    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_user_kb(user_id, subscription, request),
    )


@router.callback_query(F.data == "paiduser_refresh")
async def cb_paid_user_refresh(call: types.CallbackQuery):
    subscription = get_paid_subscription(call.from_user.id) or {}
    request = get_paid_request(call.from_user.id)
    payment_url = subscription.get("payment_url") or load_paid_settings().get("payment_url") or DEFAULT_PAID_PAYMENT_URL
    await call.answer()
    await call.message.edit_text(
        "💳 <b>Платная подписка</b>\n\n"
        f"{_subscription_summary(subscription)}\n"
        f"🔗 Оплата: <b>{html.escape(str(payment_url)) if payment_url else 'не задана'}</b>",
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
            _admin_paid_request_text({"user_id": user_id, "username": call.from_user.username or "", "request_id": request_id, "kind": "access"}, settings, "Новая заявка на платную подписку"),
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


@router.callback_query(F.data.startswith("paiduser_renew_"))
async def cb_paid_user_renew(call: types.CallbackQuery):
    user_id = call.from_user.id
    subscription = get_paid_subscription(user_id) or {}
    if not subscription:
        return await call.answer("Подписки нет", show_alert=True)
    if get_paid_request(user_id):
        return await call.answer("Заявка уже отправлена", show_alert=True)
    request_id, _ = create_paid_request(
        user_id,
        username=call.from_user.username or "",
        first_name=call.from_user.first_name or "",
        last_name=call.from_user.last_name or "",
        kind="renew",
    )
    settings = load_paid_settings()
    if ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            _admin_paid_request_text({"user_id": user_id, "username": call.from_user.username or "", "request_id": request_id, "kind": "renew"}, settings, "Пользователь хочет продлить платную подписку"),
            parse_mode=ParseMode.HTML,
            reply_markup=_paid_request_kb(request_id),
        )
    await call.answer("Запрос отправлен")
    await call.message.edit_text(
        "✅ <b>Запрос на продление отправлен админу.</b>\n\n"
        "После проверки подписка будет продлена.",
        parse_mode=ParseMode.HTML,
        reply_markup=_paid_user_kb(user_id, subscription, get_paid_request(user_id)),
    )


@router.callback_query(F.data.startswith("paiduser_paid_"))
async def cb_paid_user_paid(call: types.CallbackQuery):
    user_id = call.from_user.id
    subscription = get_paid_subscription(user_id) or {}
    if not subscription:
        return await call.answer("Подписки нет", show_alert=True)
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
    payment_url = subscription.get("payment_url") or settings.get("payment_url") or DEFAULT_PAID_PAYMENT_URL
    if ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            _admin_paid_request_text({"user_id": user_id, "username": call.from_user.username or "", "request_id": request_id, "kind": "payment_check"}, settings, "Пользователь сообщил об оплате"),
            parse_mode=ParseMode.HTML,
            reply_markup=_paid_payment_kb(request_id),
        )
    await call.answer("Запрос отправлен")
    await call.message.edit_text(
        "✅ <b>Заявка на проверку оплаты отправлена админу.</b>\n\n"
        f"🔗 Оплата: <b>{html.escape(str(payment_url)) if payment_url else 'не задана'}</b>\n"
        "После проверки подписка будет продлена.",
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


@router.callback_query(F.data == "adminpaysub_back")
async def cb_adminpaysub_back(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await render_paid_subscriptions(call)


@router.callback_query(F.data.startswith("paidset_"))
async def cb_paid_settings_edit(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    field = call.data[len("paidset_"):]
    if field not in {"trial_seconds", "payment_seconds", "payment_amount", "grace_seconds", "payment_url"}:
        return await call.answer("Неизвестная настройка", show_alert=True)
    await state.update_data(target_paid_setting_field=field)
    await state.set_state(PaidSubSettings.waiting_value)
    await call.message.edit_text(
        f"{_paid_setting_prompt(field)}\n\nДля выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


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
        if field in {"trial_seconds", "payment_seconds", "payment_amount", "grace_seconds"}:
            if raw == "-":
                defaults = {
                    "trial_seconds": DEFAULT_PAID_TRIAL_SECONDS,
                    "payment_seconds": DEFAULT_PAID_PAYMENT_SECONDS,
                    "payment_amount": DEFAULT_PAID_PAYMENT_AMOUNT,
                    "grace_seconds": DEFAULT_PAID_GRACE_SECONDS,
                }
                settings[field] = defaults[field]
            elif field == "payment_amount":
                settings[field] = int(raw)
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
    text = (
        "💳 <b>Платная подписка</b>\n\n"
        f"👤 Пользователь: <code>{html.escape(user_key)}</code>"
        + (f" (@{html.escape(username)})" if username else "")
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
    if kind in {"renew", "payment_check"}:
        existing = get_paid_subscription(user_id) or {}
        updated = extend_paid_subscription(existing, settings, from_now=(kind == "renew"))
        updated["subscription_type"] = "paid"
        updated["payment_url"] = str(settings["payment_url"])
        set_paid_subscription(user_id, updated)
        user_message = (
            "✅ <b>Твоя платная подписка продлена.</b>\n\n"
            f"Новый срок окончания: <b>{_format_dt(updated.get('paid_ends_at'))}</b>\n"
            "Зайди в /sub, чтобы посмотреть статус."
        )
    else:
        set_paid_subscription(user_id, build_paid_subscription(settings, kind="access", source=request))
        user_message = (
            "✅ <b>Твоя платная подписка выдана.</b>\n\n"
            "Сейчас доступ активирован на trial-период.\n"
            "Зайди в /sub, чтобы посмотреть статус."
        )
    delete_paid_request(user_id)
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
    delete_paid_request(user_id)
    await bot.send_message(
        user_id,
        "⛔ <b>Заявка на платную подписку отклонена.</b>\n\n"
        "Если нужно, попробуй ещё раз позже.",
        parse_mode=ParseMode.HTML,
    )
    await call.message.edit_text(
        "❌ <b>Заявка отклонена</b>\n\n"
        f"Пользователь: <code>{html.escape(str(user_id))}</code>",
        parse_mode=ParseMode.HTML,
    )
    await call.answer("Заявка отклонена")


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
    existing = get_paid_subscription(user_id) or {}
    updated = extend_paid_subscription(existing, settings, from_now=True)
    updated["subscription_type"] = "paid"
    updated["payment_url"] = str(settings["payment_url"])
    updated["status"] = "active"
    set_paid_subscription(user_id, updated)
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
