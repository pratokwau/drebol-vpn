from __future__ import annotations

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID
from xui.api import api_get_inbounds
from xui.config_runtime import get_xui_token, get_xui_url
from xui.keyboards import admin_menu_kb, settings_kb
from xui.utils import cache, is_admin
from xui.views import render_inbound, render_inbounds
from storage import load_xui_settings, save_xui_settings


router = Router()


class XuiSettings(StatesGroup):
    url = State()
    token = State()


@router.message(Command("adminxui"))
async def cmd_adminxui(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    configured = bool(get_xui_url() and get_xui_token())
    await message.answer(
        "⚙️ <b>Админ XUI</b>\n\n"
        "Тут можно настроить подключение к панели и открыть список инбаундов.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu_kb(configured),
    )


@router.callback_query(F.data == "xui_settings")
async def cb_settings(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.message.edit_text(
        "⚙️ <b>Настройки XUI</b>\n\n"
        "Здесь можно изменить URL панели и API токен.",
        parse_mode=ParseMode.HTML,
        reply_markup=settings_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "xui_set_url")
async def cb_set_url(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(XuiSettings.url)
    await call.message.edit_text(
        "Отправь <b>URL панели</b> следующим сообщением.",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data == "xui_set_token")
async def cb_set_token(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(XuiSettings.token)
    await call.message.edit_text(
        "Отправь <b>API токен</b> следующим сообщением.",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data == "xui_back")
async def cb_back(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.clear()
    configured = bool(get_xui_url() and get_xui_token())
    await call.message.edit_text(
        "⚙️ <b>Админ XUI</b>\n\n"
        "Тут можно настроить подключение к панели и открыть список инбаундов.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu_kb(configured),
    )
    await call.answer()


@router.message(XuiSettings.url)
async def set_url(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = load_xui_settings()
    data["XUI_URL"] = message.text.strip()
    save_xui_settings(data)
    await state.clear()
    await message.answer("✅ URL сохранён.")


@router.message(XuiSettings.token)
async def set_token(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = load_xui_settings()
    data["XUI_TOKEN"] = message.text.strip()
    save_xui_settings(data)
    await state.clear()
    await message.answer("✅ Токен сохранён.")


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
