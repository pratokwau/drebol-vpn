from __future__ import annotations

import html

from aiogram import types
from aiogram.enums import ParseMode

from xui.api import api_get_client, api_get_inbounds
from xui.helpers import get_client_stats_map, parse_clients
from xui.keyboards import clients_kb, inbounds_kb, inbound_settings_kb, myvpn_device_kb, myvpn_main_kb, user_menu_kb, client_actions_kb, user_settings_kb
from xui.inbound_settings_store import get_inbound_sub_port
from xui.storage import (
    DEFAULT_MAX_DEVICES,
    DEFAULT_LIMIT_GB,
    DEFAULT_LIMIT_IP,
    DEFAULT_EXPIRY_TIME_MS,
    DEFAULT_FLOW,
    get_client_note,
    get_effective_user_setting,
    get_vpn_user,
    load_vpn_users,
    refresh_username,
    save_vpn_users,
    set_user_username,
    user_settings_ready,
)
from xui.utils import _cache, cache, format_bytes


def _format_limit_gb(value) -> str:
    if value in (None, "", 0, 0.0):
        return "∞"
    try:
        return f"{float(value):g} GB"
    except Exception:
        return "∞"


def _format_expiry_time(value) -> str:
    if value in (None, "", 0, DEFAULT_EXPIRY_TIME_MS):
        return "12.12.2050"
    try:
        from datetime import datetime

        return datetime.fromtimestamp(int(value) / 1000).strftime("%d.%m.%Y")
    except Exception:
        return str(value)


async def sync_user_devices_with_panel(user_key: str) -> bool:
    data = load_vpn_users()
    info = data.get(user_key)
    if not info:
        return False

    devices = info.get("devices", [])
    if not devices:
        return False

    try:
        panel_emails = set()
        page = 1
        while True:
            res = await api_get_inbounds()
            if not res:
                break
            inbounds, _ = res
            for ib in inbounds:
                for c in parse_clients(ib):
                    if c.get("email"):
                        panel_emails.add(c.get("email"))
            break
    except Exception:
        return False

    if not panel_emails:
        return False

    clean = [d for d in devices if d.get("email") in panel_emails]
    if len(clean) == len(devices):
        return False

    data[user_key]["devices"] = clean
    save_vpn_users(data)
    return True


def inbound_text(inbound: dict) -> str:
    protocol = str(inbound.get("protocol", "?")).upper()
    port = inbound.get("port", "?")
    remark = inbound.get("remark") or f"{protocol}:{port}"
    clients = parse_clients(inbound)
    stats_map = get_client_stats_map(inbound)
    total_up = sum(int((s or {}).get("up", 0)) for s in stats_map.values())
    total_down = sum(int((s or {}).get("down", 0)) for s in stats_map.values())
    return (
        f"📡 <b>{remark}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔌 Протокол: <b>{protocol}</b>\n"
        f"🌐 Порт: <b>{port}</b>\n"
        f"👥 Клиентов: <b>{len(clients)}</b>\n"
        f"📤 Отправлено: <b>{format_bytes(total_up)}</b>\n"
        f"📥 Получено: <b>{format_bytes(total_down)}</b>\n\n"
        f"Выберите клиента:"
    )


async def render_inbounds(message_or_call, *, show_settings: bool = True):
    inbounds, err = await api_get_inbounds()
    if not inbounds:
        text = f"❌ Не удалось загрузить инбаунды.\n<code>{err}</code>"
        if isinstance(message_or_call, types.CallbackQuery):
            try:
                return await message_or_call.message.edit_text(text, parse_mode=ParseMode.HTML)
            except Exception:
                return await message_or_call.message.answer(text, parse_mode=ParseMode.HTML)
        return await message_or_call.answer(text, parse_mode=ParseMode.HTML)
    text = (
        f"🖥 <b>3X-UI Панель</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"📡 Инбаундов: <b>{len(inbounds)}</b>\n\n"
        f"Выберите инбаунд:"
    )
    markup = inbounds_kb(inbounds, show_settings=show_settings)
    if isinstance(message_or_call, types.CallbackQuery):
        try:
            await message_or_call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            await message_or_call.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return
    await message_or_call.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def render_inbound(call, inbound: dict):
    await call.message.edit_text(
        inbound_text(inbound),
        parse_mode=ParseMode.HTML,
        reply_markup=clients_kb(inbound),
    )


async def render_inbound_settings(call_or_msg, inbound: dict):
    inbound_id = int(inbound.get("id", 0) or 0)
    sub_port = get_inbound_sub_port(inbound_id)
    text = (
        "⚙️ <b>Настройки инбаунда</b>\n\n"
        f"📡 Инбаунд: <code>{inbound.get('remark') or inbound.get('id')}</code>\n"
        f"🔗 Порт подписки: <b>{sub_port or 'не задан'}</b>\n\n"
        "Нажмите на порт подписки, чтобы изменить его."
    )
    markup = inbound_settings_kb(inbound_id, sub_port)
    if isinstance(call_or_msg, types.CallbackQuery):
        try:
            await call_or_msg.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            await call_or_msg.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return
    await call_or_msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _show_user_menu(call_or_msg, user_key: str, ib_id_default: int = 0, edit: bool = True):
    data = load_vpn_users()
    info = data.get(user_key)
    if not info:
        text = "❌ Пользователь не найден"
        return await call_or_msg.edit_text(text) if edit else await call_or_msg.answer(text)

    devices = info.get("devices", [])
    if devices:
        seen = set()
        deduped = []
        for d in devices:
            em = d.get("email")
            if em not in seen:
                seen.add(em)
                deduped.append(d)
        if len(deduped) != len(devices):
            data[user_key]["devices"] = deduped
            save_vpn_users(data)
            devices = deduped

    if not ib_id_default and devices:
        ib_id_default = devices[0]["ib_id"]

    username = info.get("username", "")
    if not user_key.startswith("anon_") and not username:
        try:
            username = await refresh_username(int(user_key))
        except Exception:
            pass

    note = info.get("note", "")
    max_devs = get_effective_user_setting(info, "max_devices")
    admin_disabled = info.get("admin_disabled", False)
    settings_ready = user_settings_ready(info)

    inbounds, _ = await api_get_inbounds()
    total_up = 0
    total_down = 0
    active_count = 0
    devs_in_ib = [d for d in devices if d.get("ib_id") == ib_id_default]
    for d in devs_in_ib:
        ib = next((i for i in inbounds if i.get("id") == d.get("ib_id")), None)
        if not ib:
            continue
        cl = next((c for c in parse_clients(ib) if c.get("email") == d.get("email")), None)
        if cl and cl.get("enable", True):
            active_count += 1
        stats_map = get_client_stats_map(ib)
        s = stats_map.get(d.get("email"), {})
        total_up += s.get("up", 0)
        total_down += s.get("down", 0)

    status = "🚫 Заблокировано" if admin_disabled else (
        f"✅ Активен ({active_count}/{len(devs_in_ib)})" if devs_in_ib else "📭 Нет устройств"
    )
    if user_key.startswith("anon_"):
        header = "👤 <b>Пользователь без TG ID</b>"
    else:
        username_str = f" (@{username})" if username else ""
        header = f"👤 <b>TG: {user_key}</b>{username_str}"
    note_str = f"\n📝 Заметка: <i>{html.escape(note)}</i>" if note else ""
    text = (
        f"{header}{note_str}\n\n"
        f"📌 Статус: {status}\n"
        f"📱 Устройств: <b>{len(devs_in_ib)} / {max_devs}</b>\n"
        f"📤 Общий: <b>{format_bytes(total_up)}</b>\n"
        f"📥 Общий: <b>{format_bytes(total_down)}</b>"
    )
    if not settings_ready:
        text += (
            "\n\n⚙️ <b>Настройки не завершены</b>\n"
            f"• Лимит ГБ: <code>{info.get('limit_gb', DEFAULT_LIMIT_GB)}</code>\n"
            f"• Дата окончания: <code>{info.get('expiry_time_ms', DEFAULT_EXPIRY_TIME_MS)}</code>\n"
            f"• Лимит IP: <code>{info.get('limit_ip', DEFAULT_LIMIT_IP)}</code>\n"
            f"• Flow: <code>{info.get('flow', DEFAULT_FLOW)}</code>\n"
            f"• Лимит устройств: <code>{info.get('max_devices', DEFAULT_MAX_DEVICES)}</code>"
        )
    elif devs_in_ib:
        text += "\n\nВыберите устройство или действие:"
    kb = user_menu_kb(user_key, admin_disabled, devices, ib_id_default, settings_ready=settings_ready)
    if edit:
        await call_or_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await call_or_msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def _show_user_settings(call_or_msg, user_key: str, edit: bool = True):
    data = load_vpn_users()
    info = data.get(user_key)
    if not info:
        text = "❌ Пользователь не найден"
        return await call_or_msg.edit_text(text) if edit else await call_or_msg.answer(text)
    text = (
        "⚙️ <b>Настройки пользователя</b>\n\n"
        f"👤 TG: <code>{user_key}</code>\n"
        f"📱 Лимит устройств: <b>{get_effective_user_setting(info, 'max_devices')}</b>\n"
        f"💾 Лимит ГБ: <b>{_format_limit_gb(info.get('limit_gb', DEFAULT_LIMIT_GB))}</b>\n"
        f"⏳ Дата окончания: <b>{_format_expiry_time(info.get('expiry_time_ms', DEFAULT_EXPIRY_TIME_MS))}</b>\n"
        f"🌐 Лимит IP: <b>{info.get('limit_ip', DEFAULT_LIMIT_IP)}</b>\n"
        f"⚡ Flow: <b>{info.get('flow', DEFAULT_FLOW)}</b>"
    )
    kb = user_settings_kb(user_key, info)
    if edit:
        await call_or_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await call_or_msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def _refresh_client_view(call: types.CallbackQuery, cl_h: str):
    info = _cache.get(cl_h, {})
    email = info.get("email", "?")
    ib_id = info.get("ib_id")
    inbounds, _ = await api_get_inbounds()
    inbound = next((ib for ib in inbounds if ib.get("id") == ib_id), None)
    if not inbound:
        return

    owner_user_key = info.get("owner_uk", "")
    if owner_user_key:
        await sync_user_devices_with_panel(str(owner_user_key))

    client = await api_get_client(email)
    if not client:
        return

    stats_map = get_client_stats_map(inbound)
    stats = stats_map.get(email, {})
    enabled = client.get("enable", True)
    up = format_bytes(stats.get("up", 0))
    down = format_bytes(stats.get("down", 0))
    total = stats.get("total", 0)
    total_str = format_bytes(total) if total > 0 else "∞"
    expiry = client.get("expiryTime", 0)
    expiry_str = "∞" if not expiry or expiry == 0 else f"{expiry}"
    status = "✅ Активен" if enabled else "❌ Отключён"

    if not owner_user_key:
        for uk, uinfo in load_vpn_users().items():
            for d in uinfo.get("devices", []):
                if d.get("ib_id") == ib_id and d.get("email") == email:
                    owner_user_key = uk
                    break
            if owner_user_key:
                break

    note = get_client_note(ib_id, email) if not owner_user_key else ""
    text = f"👤 <b>{email}</b>\n\n"
    if owner_user_key:
        if owner_user_key.startswith("anon_"):
            text += "👥 Владелец: <i>без TG</i>\n"
        else:
            text += f"👥 Владелец: TG <code>{owner_user_key}</code>\n"
    text += (
        f"📌 Статус: {status}\n"
        f"📤 Отправлено: <b>{up}</b>\n"
        f"📥 Получено: <b>{down}</b>\n"
        f"💾 Лимит: <b>{total_str}</b>\n"
        f"⏳ Срок: <b>{expiry_str}</b>"
    )
    if note:
        text += f"\n📝 Заметка: <i>{html.escape(note)}</i>"
    try:
        await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=client_actions_kb(cl_h, enabled, owner_user_key))
    except Exception:
        pass
