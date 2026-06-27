from __future__ import annotations

import asyncio
from datetime import datetime

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from loader import bot
from xui.api import api_add_client, api_get_client, api_get_inbounds
from xui.helpers import parse_clients
from xui.keyboards import flow_choice_kb
from xui.storage import DEFAULT_MAX_DEVICES, add_device_to_user, create_user, get_vpn_user, save_vpn_users, set_user_vpn_access
from xui.utils import is_admin
from xui.views import _refresh_client_view, _show_user_menu, render_inbound, render_inbounds


router = Router()


class XuiAddClient(StatesGroup):
    tg_id = State()
    max_devices = State()
    limit_gb = State()
    expiry = State()
    flow = State()


def _default_or_value(raw: str | None, default, parser):
    text = (raw or "").strip()
    if not text or text == "-":
        return default
    return parser(text)


def _parse_expiry_date(raw: str | None) -> int:
    text = (raw or "").strip()
    if not text or text == "-":
        return 2523456000000
    dt = datetime.strptime(text, "%d.%m.%Y")
    return int(dt.timestamp() * 1000)
@router.message(Command("adminxui"))
async def cmd_adminxui(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    await render_inbounds(message, show_settings=False)


@router.callback_query(F.data == "xui_inbounds")
async def cb_inbounds(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await render_inbounds(call.message, show_settings=False)


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
    await _refresh_client_view(call, call.data[len("xui_cl_"):])
    await call.answer()


@router.callback_query(F.data.startswith("xui_usr_"))
async def cb_user(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_usr_"):], {})
    user_key = payload.get("user_key")
    ib_id = payload.get("ib_id", 0)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    await _show_user_menu(call.message, str(user_key), int(ib_id or 0), edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("xui_adduser_"))
async def cb_add_user(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_adduser_"):], {})
    ib_id = payload.get("id")
    if not ib_id:
        return await call.answer("Инбаунд не найден", show_alert=True)
    await state.update_data(xui_ib_id=int(ib_id))
    await state.set_state(XuiAddClient.tg_id)
    await call.message.edit_text(
        "Введите <b>TG ID</b> пользователя.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.message(XuiAddClient.tg_id)
async def add_user_tg_id(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой TG ID.\n\nДля выхода введите /cancel")
        return
    await state.update_data(xui_tg_id=int(raw))
    await state.set_state(XuiAddClient.max_devices)
    await message.answer(
        "Введите лимит устройств или отправьте <code>-</code> для значения по умолчанию.\n"
        f"По умолчанию: <b>{DEFAULT_MAX_DEVICES}</b>.\n\n"
        "Для выхода введите /cancel"
    )


@router.message(XuiAddClient.max_devices)
async def add_user_max_devices(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw and raw != "-":
        try:
            max_devices = max(1, int(raw))
        except ValueError:
            await message.answer("Введите число или <code>-</code>.\n\nДля выхода введите /cancel", parse_mode=ParseMode.HTML)
            return
    else:
        max_devices = DEFAULT_MAX_DEVICES
    await state.update_data(xui_max_devices=max_devices)
    await state.set_state(XuiAddClient.limit_gb)
    await message.answer(
        "Введите лимит ГБ или отправьте <code>-</code> для бесконечности.\n"
        "Пример: <code>100</code>\n\n"
        "Для выхода введите /cancel"
    , parse_mode=ParseMode.HTML)


@router.message(XuiAddClient.limit_gb)
async def add_user_limit_gb(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw and raw != "-":
        try:
            limit_gb = float(raw)
        except ValueError:
            await message.answer("Введите число или <code>-</code>.\n\nДля выхода введите /cancel", parse_mode=ParseMode.HTML)
            return
    else:
        limit_gb = 0.0
    await state.update_data(xui_limit_gb=limit_gb)
    await state.set_state(XuiAddClient.expiry)
    await message.answer(
        "Введите дату окончания в формате <code>дд.мм.гггг</code> или отправьте <code>-</code> для дефолта.\n"
        "Дефолт: <b>12.12.2050</b>.\n\n"
        "Для выхода введите /cancel"
        , parse_mode=ParseMode.HTML
    )


@router.message(XuiAddClient.expiry)
async def add_user_expiry(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw and raw != "-":
        try:
            expiry_time = _parse_expiry_date(raw)
        except ValueError:
            await message.answer(
                "Нужен формат <code>дд.мм.гггг</code> или <code>-</code>.\n\nДля выхода введите /cancel",
                parse_mode=ParseMode.HTML,
            )
            return
    else:
        expiry_time = 2523456000000

    data = await state.get_data()
    tg_id = int(data["xui_tg_id"])
    max_devices = int(data.get("xui_max_devices", DEFAULT_MAX_DEVICES))
    limit_gb = float(data.get("xui_limit_gb", 0))
    ib_id = int(data.get("xui_ib_id", 0))

    result, client_uuid = await api_add_client(
        ib_id,
        f"{tg_id}_{ib_id}",
        0,
        limit_gb,
        "",
        expiry_time_ms=expiry_time,
    )
    if not result.get("success"):
        await message.answer(f"❌ Не удалось добавить пользователя.\n<code>{result.get('msg', '')}</code>", parse_mode=ParseMode.HTML)
        return

    create_user(tg_id, max_devices=max_devices)
    add_device_to_user(tg_id, ib_id, client_uuid, f"{tg_id}_{ib_id}")
    set_user_vpn_access(tg_id, True)

    try:
        await bot.send_message(
            tg_id,
            "✅ <b>Вам был добавлен VPN.</b>\n\n"
            "Теперь в /start доступна команда /vpn для управления устройством.",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await state.clear()
    await message.answer("✅ Пользователь добавлен и уведомление отправлено.")
