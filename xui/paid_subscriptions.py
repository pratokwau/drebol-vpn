from __future__ import annotations

from aiogram import Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command

from xui.utils import is_admin


router = Router()


@router.message(Command("sub"))
async def cmd_sub(message: types.Message):
    await message.answer(
        "💳 <b>Платные подписки</b>\n\n"
        "Этот раздел будет использоваться для управления trial, оплатой и продлением.\n"
        "Пока он выделен отдельно от админской подписки.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("adminpaysub"))
async def cmd_adminpaysub(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer(
        "💳 <b>Админка платных подписок</b>\n\n"
        "Этот раздел уже отдельно выделен под trial, оплату, продление и проверки платежей.\n"
        "Сюда позже подключим управление тарифами и статусами.",
        parse_mode=ParseMode.HTML,
    )
