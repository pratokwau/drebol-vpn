from __future__ import annotations

from aiogram import Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command

from xui.utils import is_admin


router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id

    text = (
        "<b>drebol-vpn</b> приветствует вас!\n\n"
        "• /start — Главное меню\n"
        "• /cancel — Отмена действия"
    )
    if is_admin(user_id):
        text += (
            "\n\n👨‍💻 <b>Администрирование</b>\n"
            "• /admin — Админ-панель\n"
            "• /adminxui — Панель 3X-UI"
        )
    else:
        text += "\n\nЭтот бот доступен всем пользователям."

    await message.answer(text, parse_mode=ParseMode.HTML)
