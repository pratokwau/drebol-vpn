from __future__ import annotations

import html

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID
from loader import bot
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
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="adminpaysub_refresh")])
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
    await message.answer(
        "💳 <b>Платная подписка</b>\n\n"
        f"📌 Статус: <b>{status}</b>\n"
        f"🧪 Trial: <b>{trial_days if trial_days is not None else 'не задан'}</b>\n"
        f"⏳ Продление: <b>{payment_days if payment_days is not None else 'не задано'}</b>\n"
        f"💰 Сумма: <b>{amount if amount is not None else 'не задана'}</b>\n"
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
    set_paid_subscription(
        user_id,
        {
            "subscription_type": "paid",
            "status": "trial",
            "active": True,
            "trial_days": 10,
            "payment_days": 30,
            "payment_amount": 70,
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
