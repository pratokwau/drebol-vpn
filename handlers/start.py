from __future__ import annotations

from aiogram import Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command

from config import ADMIN_ID
from loader import is_authorized
from xui.utils import is_admin


router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if not is_authorized(user_id):
        await message.answer("⛔ Доступ запрещён.")
        return

    text = (
        "<b>drebol</b> приветствует вас!\n\n"
        "• /start — Главное меню\n"
        "• /cancel — Отмена действия"
    )
    if is_admin(user_id):
        text += "\n\n👨‍💻 <b>Администрирование</b>\n• /adminxui — Панель 3X-UI"

    await message.answer(text, parse_mode=ParseMode.HTML)
