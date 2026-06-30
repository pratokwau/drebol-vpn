from __future__ import annotations

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command

from sub.api import api_get_client, api_update_client
from sub.adminpaysub.paid_settings_store import format_duration
from sub.instructions import happ_instruction
from sub.keyboards import myvpn_device_kb, myvpn_main_kb
from sub.adminsub.storage import get_vpn_user, user_settings_ready
from sub.utils import is_admin


router = Router()


def _has_admin_vpn_access(user_data: dict | None) -> bool:
    return bool(
        user_data
        and str(user_data.get("subscription_type", "")).lower() != "paid"
    )


def _device_cache_key(ib_id: int, email: str) -> str:
    from sub.utils import cache

    return cache(f"mvd_{ib_id}_{email}", {"email": email, "ib_id": ib_id})


def _format_short_dt(ts: int | None) -> str:
    from datetime import datetime

    if not ts:
        return "Не задано"
    try:
        return datetime.fromtimestamp(int(ts) / 1000).strftime("%d.%m.%Y • %H:%M")
    except Exception:
        return "Не задано"


def _format_remaining_vpn(expiry_time_ms: int | None) -> str:
    from datetime import datetime

    if not expiry_time_ms or int(expiry_time_ms) >= 2523456000000:
        return "∞"
    remaining = max(0, int(expiry_time_ms) - int(datetime.now().timestamp() * 1000))
    if remaining <= 0:
        return "00:00:00"
    return format_duration(max(0, remaining // 1000))


async def _load_synced_user_data(user_id: int) -> dict | None:
    user_data = get_vpn_user(user_id)
    if not user_data:
        return None
    if _has_admin_vpn_access(user_data):
        try:
            from sub.views import sync_user_devices_with_panel

            if await sync_user_devices_with_panel(str(user_id)):
                user_data = get_vpn_user(user_id) or user_data
        except Exception:
            pass
    return user_data


def _find_device(user_data: dict, dev_hash: str) -> dict | None:
    for d in user_data.get("devices", []):
        if _device_cache_key(int(d.get("ib_id", 0) or 0), d.get("email", "")) == dev_hash:
            return d
    return None


async def _render_vpn(message: types.Message, user_data: dict):
    devices = user_data.get("devices", [])
    admin_disabled = bool(user_data.get("admin_disabled", False))
    settings_ready = user_settings_ready(user_data)
    max_devices = int(user_data.get("max_devices") or 1)
    limit_ip = int(user_data.get("limit_ip") or 2)
    limit_gb = user_data.get("limit_gb")
    flow = str(user_data.get("flow") or "xtls-rprx-vision")
    expiry_time_ms = int(user_data.get("expiry_time_ms") or 0)
    remaining = _format_remaining_vpn(expiry_time_ms)
    expiry_text = _format_short_dt(expiry_time_ms)
    traffic_text = "∞" if limit_gb in (None, "", 0, 0.0) else str(limit_gb)
    lines = [
        "🔐 <b>Информация о вашем VPN</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "<b>👑 Текущий тариф</b>",
        "Админский доступ",
        "",
        "<b>⏳ Осталось</b>",
        remaining,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "<b>💎 Параметры тарифа</b>",
        "",
        f"📱 До {max_devices} устройств",
        f"🌐 До {limit_ip} IP одновременно",
        f"♾ {'Безлимитный' if traffic_text == '∞' else traffic_text + ' ГБ'} трафик",
        f"⚡ Flow: <b>{flow}</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "<b>📅 Доступ до</b>",
        expiry_text,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if not settings_ready:
        lines.extend(["⚙️ Профиль ещё не настроен администратором.", ""])
    elif not devices:
        lines.extend(["Пока нет подключённых устройств.", ""])
    else:
        lines.extend(["Выберите устройство ниже, чтобы открыть управление.", ""])
        for idx, device in enumerate(devices, 1):
            state = "включено" if device.get("enabled", True) else "выключено"
            label = device.get("label") or device.get("email") or "устройство"
            lines.append(f"{idx}. <b>{label}</b> — {state}")
        lines.append("")
    lines.extend(["💙 Спасибо, что пользуетесь нашим VPN!"])
    if admin_disabled:
        lines.append("")
        lines.append("🚫 Доступ сейчас отключён администратором.")
    await message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=myvpn_main_kb(devices, admin_disabled, settings_ready=settings_ready),
    )


async def _render_vpn_info(call_or_msg, user_data: dict):
    devices = user_data.get("devices", [])
    admin_disabled = bool(user_data.get("admin_disabled", False))
    settings_ready = user_settings_ready(user_data)
    max_devices = int(user_data.get("max_devices") or 1)
    limit_ip = int(user_data.get("limit_ip") or 2)
    limit_gb = user_data.get("limit_gb")
    flow = str(user_data.get("flow") or "xtls-rprx-vision")
    expiry_time_ms = int(user_data.get("expiry_time_ms") or 0)
    remaining = _format_remaining_vpn(expiry_time_ms)
    expiry_text = _format_short_dt(expiry_time_ms)
    traffic_text = "∞" if limit_gb in (None, "", 0, 0.0) else str(limit_gb)
    text = (
        "🔐 <b>Мой VPN</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>👑 Текущий тариф</b>\n"
        "Админский доступ\n\n"
        "<b>⏳ Осталось</b>\n"
        f"{remaining}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>💎 Параметры тарифа</b>\n\n"
        f"📱 До {max_devices} устройств\n"
        f"🌐 До {limit_ip} IP одновременно\n"
        f"♾ {'Безлимитный' if traffic_text == '∞' else traffic_text + ' ГБ'} трафик\n"
        f"⚡ Flow: <b>{flow}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>📅 Доступ до</b>\n"
        f"{expiry_text}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>📱 Устройства</b>\n"
        f"{len(devices)} подключено\n"
    )
    markup = myvpn_main_kb(devices, admin_disabled, settings_ready=settings_ready)
    if isinstance(call_or_msg, types.CallbackQuery):
        try:
            await call_or_msg.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            await call_or_msg.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await call_or_msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


@router.message(Command("vpn"))
async def cmd_vpn(message: types.Message):
    user_data = await _load_synced_user_data(message.from_user.id)
    if not _has_admin_vpn_access(user_data):
        await message.answer("⛔ У вас пока нет доступа к /vpn. Администратор должен сначала настроить профиль.")
        return
    if user_data.get("admin_disabled"):
        await message.answer("⛔ Ваш доступ временно отключён администратором.")
        return
    await _render_vpn(message, user_data)


@router.callback_query(F.data == "myvpn_refresh")
async def cb_vpn_refresh(call: types.CallbackQuery):
    user_data = await _load_synced_user_data(call.from_user.id)
    if not _has_admin_vpn_access(user_data):
        return await call.answer("Нет доступа", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("Доступ отключён администратором", show_alert=True)
    await call.answer()
    await _render_vpn(call.message, user_data)


@router.callback_query(F.data == "myvpn_info")
async def cb_vpn_info(call: types.CallbackQuery):
    user_data = await _load_synced_user_data(call.from_user.id)
    if not _has_admin_vpn_access(user_data):
        return await call.answer("Нет доступа", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("Доступ отключён администратором", show_alert=True)
    await call.answer()
    await _render_vpn_info(call, user_data)


@router.callback_query(F.data == "myvpn_inst_main")
async def cb_vpn_inst_main(call: types.CallbackQuery):
    user_data = await _load_synced_user_data(call.from_user.id)
    if not _has_admin_vpn_access(user_data):
        return await call.answer("Нет доступа", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("Доступ отключён администратором", show_alert=True)
    device = next((item for item in user_data.get("devices", []) if item.get("ib_id") is not None), None)
    if not device:
        return await call.answer("⛔ Инструкция пока недоступна.", show_alert=True)
    inbound_id = int(device.get("ib_id", 0) or 0)
    client = await api_get_client(str(device.get("email", "")))
    sub_id = str((client or {}).get("subId") or device.get("email", ""))
    await call.answer()
    await call.message.edit_text(
        happ_instruction(sub_id, inbound_id),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=myvpn_main_kb(user_data.get("devices", []), bool(user_data.get("admin_disabled", False)), settings_ready=user_settings_ready(user_data)),
    )


@router.callback_query(F.data.startswith("myvpn_dev_"))
async def cb_vpn_device(call: types.CallbackQuery):
    user_data = await _load_synced_user_data(call.from_user.id)
    if not _has_admin_vpn_access(user_data) or not user_data.get("has_vpn_access"):
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
    user_data = await _load_synced_user_data(call.from_user.id)
    if not _has_admin_vpn_access(user_data) or not user_data.get("has_vpn_access"):
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
    user_data = await _load_synced_user_data(call.from_user.id)
    if not _has_admin_vpn_access(user_data):
        return await call.answer("Нет доступа", show_alert=True)
    payload = call.data[len("myvpn_inst_"):]
    sub_id = None
    inbound_id = None
    if user_data:
        for d in user_data.get("devices", []):
            if _device_cache_key(int(d.get("ib_id", 0) or 0), d.get("email", "")) == payload:
                inbound_id = int(d.get("ib_id", 0) or 0)
                client = await api_get_client(str(d.get("email", "")))
                sub_id = str((client or {}).get("subId") or d.get("email", ""))
                break
    await call.answer()
    await call.message.answer(happ_instruction(sub_id, inbound_id), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
