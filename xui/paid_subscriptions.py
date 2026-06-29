from __future__ import annotations

from aiogram import Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command

from xui.paid_storage import get_paid_subscription, has_paid_subscription
from xui.utils import is_admin
from xui.views import render_inbounds


router = Router()


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
    await render_inbounds(message, show_settings=False)
