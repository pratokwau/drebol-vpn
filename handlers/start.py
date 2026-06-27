from __future__ import annotations

import re

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from xui.api import api_add_client, api_del_client_by_email, api_get_client, api_get_inbounds, api_update_client
from xui.keyboards import myvpn_device_kb, myvpn_main_kb
from xui.storage import (
    add_device_to_user,
    get_vpn_user,
    load_vpn_users,
    remove_device_from_user,
    set_user_vpn_access,
    user_settings_ready,
)
from xui.states import XuiVpnAddDevice
from xui.utils import is_admin


router = Router()


def _device_cache_key(ib_id: int, email: str) -> str:
    from xui.utils import cache

    return cache(f"mvd_{ib_id}_{email}", {"email": email, "ib_id": ib_id})


def _sanitize_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip().lower())
    return slug.strip("_") or "device"


async def _render_vpn(message: types.Message, user_data: dict):
    devices = user_data.get("devices", [])
    max_devices = int(user_data.get("max_devices", 1) or 1)
    admin_disabled = bool(user_data.get("admin_disabled", False))
    settings_ready = user_settings_ready(user_data)
    can_add = settings_ready and (not admin_disabled) and (len(devices) < max_devices)
    lines = ["🔐 <b>Ваш VPN</b>", ""]
    if not settings_ready:
        lines.append("⚙️ Доступ появится после настройки профиля администратором.")
    elif not devices:
        lines.append("У вас пока нет устройств.")
    else:
        for idx, device in enumerate(devices, 1):
            lines.append(f"{idx}. <code>{device.get('email', '?')}</code>")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=myvpn_main_kb(devices, max_devices, admin_disabled, can_add, settings_ready=settings_ready))


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id

    text = (
        "<b>drebol-vpn</b> приветствует вас!\n\n"
        "• /start — Главное меню\n"
        "• /cancel — Отмена действия"
    )
    user_data = get_vpn_user(user_id)
    if user_data and user_settings_ready(user_data):
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
    if not user_data or not user_settings_ready(user_data):
        await message.answer("⛔ У вас пока нет доступа к /vpn. Администратор должен сначала настроить профиль.")
        return
    if user_data.get("admin_disabled"):
        await message.answer("⛔ Ваш доступ временно отключён администратором.")
        return
    await _render_vpn(message, user_data)


@router.callback_query(F.data == "myvpn_refresh")
async def cb_vpn_refresh(call: types.CallbackQuery):
    user_data = get_vpn_user(call.from_user.id)
    if not user_data or not user_settings_ready(user_data):
        return await call.answer("Нет доступа", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("Доступ отключён администратором", show_alert=True)
    await call.answer()
    await _render_vpn(call.message, user_data)


@router.callback_query(F.data == "myvpn_add")
async def cb_vpn_add(call: types.CallbackQuery, state: FSMContext):
    user_data = get_vpn_user(call.from_user.id)
    if not user_data or not user_settings_ready(user_data):
        return await call.answer("Нет доступа", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("Доступ отключён администратором", show_alert=True)
    await state.update_data(vpn_user_id=call.from_user.id)
    await state.set_state(XuiVpnAddDevice.waiting_name)
    await call.message.edit_text(
        "Введите название устройства.\n\nДля выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.message(XuiVpnAddDevice.waiting_name)
async def vpn_add_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = get_vpn_user(user_id)
    if not user_data or not user_data.get("has_vpn_access"):
        return
    if user_data.get("admin_disabled"):
        await message.answer("⛔ Ваш доступ временно отключён администратором.")
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым.\n\nДля выхода введите /cancel")
        return
    await state.update_data(vpn_device_name=name)
    await state.set_state(XuiVpnAddDevice.waiting_limit_ip)
    await message.answer(
        "Введите лимит IP для этого устройства или <code>-</code> для значения по умолчанию.\n"
        "По умолчанию: <b>2</b>.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )


@router.message(XuiVpnAddDevice.waiting_limit_ip)
async def vpn_add_limit_ip(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = get_vpn_user(user_id)
    if not user_data or not user_data.get("has_vpn_access"):
        return
    if user_data.get("admin_disabled"):
        await message.answer("⛔ Ваш доступ временно отключён администратором.")
        return
    raw = (message.text or "").strip()
    limit_ip = 2
    if raw and raw != "-":
        if not raw.isdigit():
            await message.answer("Введите число или <code>-</code>.\n\nДля выхода введите /cancel", parse_mode=ParseMode.HTML)
            return
        limit_ip = max(1, int(raw))

    data = await state.get_data()
    name = str(data.get("vpn_device_name") or "device")
    devices = user_data.get("devices", [])
    if len(devices) >= int(user_data.get("max_devices", 1) or 1):
        await state.clear()
        await message.answer("⛔ Достигнут лимит устройств.")
        return
    if not devices:
        await state.clear()
        await message.answer("⛔ У вас нет базового устройства для добавления ещё одного.")
        return

    base_ib = int(devices[0].get("ib_id", 0) or 0)
    slug = _sanitize_slug(name)
    email = f"{user_id}_{slug}"
    result, client_uuid = await api_add_client(
        base_ib,
        email,
        0,
        0,
        "",
        expiry_time_ms=2523456000000,
        limit_ip=limit_ip,
    )
    if not result.get("success"):
        await state.clear()
        await message.answer(f"❌ Не удалось создать устройство.\n<code>{result.get('msg', '')}</code>", parse_mode=ParseMode.HTML)
        return

    add_device_to_user(user_id, base_ib, client_uuid, email, limit_ip=limit_ip)
    set_user_vpn_access(user_id, True)
    await state.clear()
    await message.answer(
        f"✅ Устройство <code>{email}</code> создано.\n"
        f"Лимит IP: <b>{limit_ip}</b>",
        parse_mode=ParseMode.HTML,
    )
    await _render_vpn(message, get_vpn_user(user_id) or {})


@router.callback_query(F.data.startswith("myvpn_dev_"))
async def cb_vpn_device(call: types.CallbackQuery):
    user_data = get_vpn_user(call.from_user.id)
    if not user_data or not user_data.get("has_vpn_access"):
        return await call.answer("Нет доступа", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("Доступ отключён администратором", show_alert=True)
    payload = call.data[len("myvpn_dev_"):]
    info = None
    for d in user_data.get("devices", []):
        if _device_cache_key(int(d.get("ib_id", 0) or 0), d.get("email", "")) == payload:
            info = d
            break
    if not info:
        return await call.answer("Устройство не найдено", show_alert=True)
    await call.answer()
    await call.message.answer(
        f"📱 <b>{info.get('email', '?')}</b>\n\n"
        "Управление устройством будет добавлено следующим шагом.",
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("myvpn_tog_"))
async def cb_vpn_toggle(call: types.CallbackQuery):
    user_data = get_vpn_user(call.from_user.id)
    if not user_data or not user_data.get("has_vpn_access"):
        return await call.answer("Нет доступа", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("Доступ отключён администратором", show_alert=True)
    await call.answer("Эта кнопка пока в доработке", show_alert=True)


@router.callback_query(F.data.startswith("myvpn_del_"))
async def cb_vpn_delete(call: types.CallbackQuery):
    user_data = get_vpn_user(call.from_user.id)
    if not user_data or not user_data.get("has_vpn_access"):
        return await call.answer("Нет доступа", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("Доступ отключён администратором", show_alert=True)
    await call.answer("Эта кнопка пока в доработке", show_alert=True)


@router.callback_query(F.data.startswith("myvpn_link_"))
async def cb_vpn_link(call: types.CallbackQuery):
    await call.answer("Ссылка будет добавлена следующим шагом", show_alert=True)


@router.callback_query(F.data.startswith("myvpn_inst_"))
async def cb_vpn_inst(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer("📖 Инструкция будет добавлена следующим шагом.")
