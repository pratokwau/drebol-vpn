from __future__ import annotations

import html

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from xui.paid_storage import get_paid_subscription, has_paid_subscription
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
        await message.answer(
            "⛔ У вас пока нет платной подписки.\n\n"
            "Если вы хотите получить доступ, дождитесь выдачи trial или оплаты.",
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
