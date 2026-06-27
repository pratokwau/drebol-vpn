from __future__ import annotations

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command

from xui.api import api_get_inbounds
from xui.keyboards import inbounds_kb
from xui.utils import is_admin
from xui.views import render_inbound, render_inbounds


router = Router()
@router.message(Command("adminxui"))
async def cmd_adminxui(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    await message.answer(
        "⚙️ <b>Админ XUI</b>\n\n"
        "Здесь доступен только список инбаундов.",
        parse_mode=ParseMode.HTML,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="📡 Инбаунды", callback_data="xui_inbounds")]
            ]
        ),
    )


@router.callback_query(F.data == "xui_inbounds")
async def cb_inbounds(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await render_inbounds(call.message)


@router.callback_query(F.data.startswith("xui_ib_"))
async def cb_inbound(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    ib_hash = call.data[len("xui_ib_") :]
    # Пока используем кэш только для id, чтобы не усложнять стартовый каркас.
    if len(ib_hash) != 8:
        return await call.answer("Некорректный инбаунд", show_alert=True)
    from xui.utils import _cache

    info = _cache.get(ib_hash, {})
    inbound_id = info.get("id")
    if inbound_id is None:
        return await call.answer("Инбаунд не найден", show_alert=True)
    inbounds, err = await api_get_inbounds()
    inbound = next((ib for ib in inbounds if ib.get("id") == inbound_id), None)
    if not inbound:
        return await call.answer(f"Инбаунд не найден: {err}", show_alert=True)
    await render_inbound(call, inbound)
    await call.answer()


@router.callback_query(F.data.startswith("xui_cl_"))
async def cb_client(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer("Карточка клиента будет добавлена следующим шагом.")
