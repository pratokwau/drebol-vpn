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
    get_vpn_user,
    user_settings_ready,
)
from xui.utils import is_admin


router = Router()


def _device_cache_key(ib_id: int, email: str) -> str:
    from xui.utils import cache

    return cache(f"mvd_{ib_id}_{email}", {"email": email, "ib_id": ib_id})


def _find_device(user_data: dict, dev_hash: str) -> dict | None:
    for d in user_data.get("devices", []):
        if _device_cache_key(int(d.get("ib_id", 0) or 0), d.get("email", "")) == dev_hash:
            return d
    return None


def _sanitize_slug(text: str) -> str:
    slug = re.sub(r"[^\w-]+", "_", text.strip().lower(), flags=re.UNICODE)
    return slug.strip("_") or "device"


async def _render_vpn(message: types.Message, user_data: dict):
    devices = user_data.get("devices", [])
    admin_disabled = bool(user_data.get("admin_disabled", False))
    settings_ready = user_settings_ready(user_data)
    lines = ["🔐 <b>Ваш VPN</b>", ""]
    if not settings_ready:
        lines.append("⚙️ Сначала администратор должен настроить ваш профиль.")
    elif not devices:
        lines.append("У вас пока нет подключённых устройств.")
    else:
        active_count = sum(1 for device in devices if device.get("enabled", True))
        lines.append(f"📱 Устройств: <b>{len(devices)}</b>")
        lines.append(f"✅ Активных: <b>{active_count}</b>")
        lines.append("")
        for idx, device in enumerate(devices, 1):
            state = "включено" if device.get("enabled", True) else "выключено"
            lines.append(f"{idx}. <code>{device.get('email', '?')}</code> — {state}")
    if settings_ready:
        lines.append("")
        lines.append("Выберите устройство ниже, чтобы открыть управление.")
    if admin_disabled:
        lines.append("")
        lines.append("🚫 Доступ сейчас отключён администратором.")
    await message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=myvpn_main_kb(devices, admin_disabled, settings_ready=settings_ready),
    )


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
    client = await api_get_client(str(info.get("email", "")))
    enabled = bool(client.get("enable", True)) if client else bool(info.get("enabled", True))
    dev_hash = _device_cache_key(int(info.get("ib_id", 0) or 0), str(info.get("email", "")))
    await call.message.answer(
        f"📱 <b>{info.get('email', '?')}</b>\n\n"
        f"Статус: <b>{'включено' if enabled else 'выключено'}</b>\n"
        "Здесь можно включать и выключать устройство, а также открыть инструкцию.",
        parse_mode=ParseMode.HTML,
        reply_markup=myvpn_device_kb(dev_hash, enabled, bool(user_data.get("admin_disabled", False))),
    )


@router.callback_query(F.data.startswith("myvpn_tog_"))
async def cb_vpn_toggle(call: types.CallbackQuery):
    user_data = get_vpn_user(call.from_user.id)
    if not user_data or not user_data.get("has_vpn_access"):
        return await call.answer("Нет доступа", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("Доступ отключён администратором", show_alert=True)
    payload = call.data[len("myvpn_tog_"):]
    dev = _find_device(user_data, payload)
    if not dev:
        return await call.answer("Устройство не найдено", show_alert=True)
    email = dev.get("email", "")
    if not email:
        return await call.answer("Устройство не найдено", show_alert=True)
    client = await api_get_client(email)
    if not client:
        return await call.answer("Не удалось загрузить устройство", show_alert=True)
    client["enable"] = not bool(client.get("enable", True))
    result = await api_update_client(email, client)
    if not result.get("success", True):
        return await call.answer(result.get("msg", "Не удалось обновить устройство"), show_alert=True)
    await call.answer("Состояние обновлено")
    await _render_vpn(call.message, get_vpn_user(call.from_user.id) or {})


@router.callback_query(F.data.startswith("myvpn_inst_"))
async def cb_vpn_inst(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer(
        "📖 <b>Инструкция</b>\n\n"
        "1. Нажмите на нужное устройство.\n"
        "2. Используйте кнопку включения или отключения.\n"
        "3. При необходимости откройте это сообщение еще раз через кнопку «Инструкция».\n\n"
        "Если устройство не подключается, напишите администратору.",
        parse_mode=ParseMode.HTML,
    )
