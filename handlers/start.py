from __future__ import annotations

from aiogram import Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command

from xui.storage import get_vpn_user
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
    user_data = get_vpn_user(user_id)
    if user_data and user_data.get("has_vpn_access"):
        text += "\n• /vpn — Управление VPN"
    if is_admin(user_id):
        text += (
            "\n\n👨‍💻 <b>Администрирование</b>\n"
            "• /admin — Админ-панель\n"
            "• /adminxui — Панель 3X-UI"
        )
    else:
        text += "\n\nЭтот бот доступен всем пользователям."

    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("vpn"))
async def cmd_vpn(message: types.Message):
    user_data = get_vpn_user(message.from_user.id)
    if not user_data or not user_data.get("has_vpn_access"):
        await message.answer("⛔ У вас пока нет доступа к /vpn.")
        return

    devices = user_data.get("devices", [])
    if not devices:
        await message.answer("У вас нет активных устройств.")
        return

    lines = ["🔐 <b>Ваш VPN</b>", ""]
    for idx, device in enumerate(devices, 1):
        email = device.get("email", "?")
        lines.append(f"{idx}. <code>{email}</code>")
    lines.append("")
    lines.append("Управление устройствами мы сейчас подключим следующим шагом.")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
