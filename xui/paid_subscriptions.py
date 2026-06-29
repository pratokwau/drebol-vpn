from __future__ import annotations

import html

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID
from loader import bot
from xui.paid_settings_store import (
    DEFAULT_PAID_GRACE_HOURS,
    DEFAULT_PAID_PAYMENT_AMOUNT,
    DEFAULT_PAID_PAYMENT_DAYS,
    DEFAULT_PAID_PAYMENT_URL,
    DEFAULT_PAID_TRIAL_DAYS,
    load_paid_settings,
    save_paid_settings,
)
from xui.paid_storage import (
    create_paid_request,
    delete_paid_request,
    get_paid_request,
    get_paid_request_by_id,
    get_paid_subscription,
    has_paid_subscription,
    set_paid_subscription,
)
from xui.storage import get_users_by_subscription_type, load_vpn_users
from xui.states import PaidSubSettings
from xui.utils import is_admin


router = Router()


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


def _paid_settings_kb() -> InlineKeyboardMarkup:
    settings = load_paid_settings()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🧪 Trial: {settings['trial_days']} дней", callback_data="paidset_trial_days"),
                InlineKeyboardButton(text="По дефолту", callback_data="paiddef_trial_days"),
            ],
            [
                InlineKeyboardButton(text=f"⏳ Оплата: {settings['payment_days']} дней", callback_data="paidset_payment_days"),
                InlineKeyboardButton(text="По дефолту", callback_data="paiddef_payment_days"),
            ],
            [
                InlineKeyboardButton(text=f"💰 Сумма: {settings['payment_amount']} ₽", callback_data="paidset_payment_amount"),
                InlineKeyboardButton(text="По дефолту", callback_data="paiddef_payment_amount"),
            ],
            [
                InlineKeyboardButton(text=f"🕒 Grace: {settings['grace_hours']} ч", callback_data="paidset_grace_hours"),
                InlineKeyboardButton(text="По дефолту", callback_data="paiddef_grace_hours"),
            ],
            [InlineKeyboardButton(text=f"🔗 Оплата: {'задана' if settings['payment_url'] else 'не задана'}", callback_data="paidset_payment_url")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adminpaysub_back")],
        ]
    )


def _paid_setting_prompt(field: str) -> str:
    if field == "trial_days":
        return "Введите длительность trial в днях или <code>-</code> для значения по умолчанию."
    if field == "payment_days":
        return "Введите срок платной подписки в днях или <code>-</code> для значения по умолчанию."
    if field == "payment_amount":
        return "Введите сумму оплаты в рублях или <code>-</code> для значения по умолчанию."
    if field == "grace_hours":
        return "Введите время на оплату после окончания trial в часах или <code>-</code>."
    if field == "payment_url":
        return "Введите ссылку на оплату или <code>-</code>, чтобы очистить её."
    return "Введите значение."


async def _show_paid_settings(call_or_message, *, edit: bool = True):
    settings = load_paid_settings()
    text = (
        "⚙️ <b>Настройки платных подписок</b>\n\n"
        f"🧪 Trial: <b>{settings['trial_days']} дней</b>\n"
        f"⏳ Оплата: <b>{settings['payment_days']} дней</b>\n"
        f"💰 Сумма: <b>{settings['payment_amount']} ₽</b>\n"
        f"🕒 Grace: <b>{settings['grace_hours']} ч</b>\n"
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


@router.message(Command("sub"))
async def cmd_sub(message: types.Message):
    user_id = message.from_user.id
    subscription = get_paid_subscription(user_id) or {}
    if not has_paid_subscription(user_id):
        request = get_paid_request(user_id)
        if request:
            await message.answer(
                "⏳ <b>Заявка уже отправлена админу.</b>\n\n"
                "Как только он подтвердит доступ, я пришлю уведомление.",
                parse_mode=ParseMode.HTML,
            )
            return
        request_id, _ = create_paid_request(
            user_id,
            username=message.from_user.username or "",
            first_name=message.from_user.first_name or "",
            last_name=message.from_user.last_name or "",
        )
        await message.answer(
            "✅ <b>Заявка на платную подписку отправлена админу.</b>\n\n"
            "Ожидай подтверждения, я сообщу тебе, когда доступ будет выдан.",
            parse_mode=ParseMode.HTML,
        )
        admin_text = (
            "💳 <b>Новая заявка на платную подписку</b>\n\n"
            f"👤 TG: <code>{user_id}</code>\n"
            f"👤 Username: <code>{html.escape(message.from_user.username or 'нет')}</code>\n"
            f"🆔 Request: <code>{request_id}</code>\n\n"
            "Выберите действие:"
        )
        if ADMIN_ID:
            await bot.send_message(
                ADMIN_ID,
                admin_text,
                parse_mode=ParseMode.HTML,
                reply_markup=_paid_request_kb(request_id),
            )
        return
    status = str(subscription.get("status") or "active").capitalize()
    trial_days = subscription.get("trial_days")
    payment_days = subscription.get("payment_days")
    amount = subscription.get("payment_amount")
    paid_until = subscription.get("paid_until")
    payment_url = subscription.get("payment_url") or load_paid_settings().get("payment_url") or DEFAULT_PAID_PAYMENT_URL
    await message.answer(
        "💳 <b>Платная подписка</b>\n\n"
        f"📌 Статус: <b>{status}</b>\n"
        f"🧪 Trial: <b>{trial_days if trial_days is not None else 'не задан'}</b>\n"
        f"⏳ Продление: <b>{payment_days if payment_days is not None else 'не задано'}</b>\n"
        f"💰 Сумма: <b>{amount if amount is not None else 'не задана'}</b>\n"
        f"🔗 Оплата: <b>{html.escape(str(payment_url)) if payment_url else 'не задана'}</b>\n"
        f"📅 Активна до: <b>{paid_until if paid_until is not None else 'не задано'}</b>\n\n"
        "Здесь позже появится управление оплатой, продлением и перевыпуском доступа.",
        parse_mode=ParseMode.HTML,
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
    if field not in {"trial_days", "payment_days", "payment_amount", "grace_hours", "payment_url"}:
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
    if field == "trial_days":
        settings["trial_days"] = DEFAULT_PAID_TRIAL_DAYS
    elif field == "payment_days":
        settings["payment_days"] = DEFAULT_PAID_PAYMENT_DAYS
    elif field == "payment_amount":
        settings["payment_amount"] = DEFAULT_PAID_PAYMENT_AMOUNT
    elif field == "grace_hours":
        settings["grace_hours"] = DEFAULT_PAID_GRACE_HOURS
    else:
        return await call.answer("Неизвестная настройка", show_alert=True)
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
        if field in {"trial_days", "payment_days", "payment_amount", "grace_hours"}:
            if raw == "-":
                defaults = {
                    "trial_days": DEFAULT_PAID_TRIAL_DAYS,
                    "payment_days": DEFAULT_PAID_PAYMENT_DAYS,
                    "payment_amount": DEFAULT_PAID_PAYMENT_AMOUNT,
                    "grace_hours": DEFAULT_PAID_GRACE_HOURS,
                }
                settings[field] = defaults[field]
            else:
                settings[field] = int(raw)
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
    text = (
        "💳 <b>Платная подписка</b>\n\n"
        f"👤 Пользователь: <code>{html.escape(user_key)}</code>"
        + (f" (@{html.escape(username)})" if username else "")
        + "\n"
        f"📦 Тип: <b>{info.get('subscription_type', 'paid')}</b>\n"
        f"📱 Устройств: <b>{len(info.get('devices', []))}</b>"
    )
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
    settings = load_paid_settings()
    set_paid_subscription(
        user_id,
        {
            "subscription_type": "paid",
            "status": "trial",
            "active": True,
            "trial_days": int(settings["trial_days"]),
            "payment_days": int(settings["payment_days"]),
            "payment_amount": int(settings["payment_amount"]),
            "payment_url": str(settings["payment_url"]),
            "grace_hours": int(settings["grace_hours"]),
            "paid_until": "",
        },
    )
    delete_paid_request(user_id)
    await bot.send_message(
        user_id,
        "✅ <b>Твоя платная подписка выдана.</b>\n\n"
        "Сейчас доступ активирован на trial-период.\n"
        "Зайди в /sub, чтобы посмотреть статус.",
        parse_mode=ParseMode.HTML,
    )
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
