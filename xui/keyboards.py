from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from xui.utils import cache


def admin_menu_kb(configured: bool) -> InlineKeyboardMarkup:
    status = "✅ Настроено" if configured else "⚠️ Не настроено"
    rows = [
        [InlineKeyboardButton(text=f"🔧 XUI: {status}", callback_data="xui_settings")],
        [InlineKeyboardButton(text="📡 Инбаунды", callback_data="xui_inbounds")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Изменить URL", callback_data="xui_set_url")],
            [InlineKeyboardButton(text="🔐 Изменить токен", callback_data="xui_set_token")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="xui_back")],
        ]
    )


def inbounds_kb(inbounds: list[dict], *, show_settings: bool = True) -> InlineKeyboardMarkup:
    rows = []
    for inbound in inbounds:
        inbound_id = inbound.get("id")
        protocol = str(inbound.get("protocol", "?")).upper()
        port = inbound.get("port", "?")
        remark = inbound.get("remark") or f"{protocol}:{port}"
        clients = inbound.get("clientStats") or inbound.get("settings", {}).get("clients", [])
        h = cache(f"ib_{inbound_id}", {"id": inbound_id})
        rows.append([InlineKeyboardButton(text=f"{remark} | {protocol}:{port} | 👥 {len(clients)}", callback_data=f"xui_ib_{h}")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="xui_inbounds")])
    if show_settings:
        rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data="xui_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clients_kb(inbound: dict) -> InlineKeyboardMarkup:
    clients = inbound.get("settings", {}).get("clients", [])
    rows = []
    for idx, client in enumerate(clients):
        email = client.get("email") or f"client-{idx+1}"
        enabled = "✅" if client.get("enable", True) else "❌"
        h = cache(f"cl_{inbound.get('id')}_{email}", {"email": email, "inbound_id": inbound.get("id")})
        rows.append([InlineKeyboardButton(text=f"{enabled} {email}", callback_data=f"xui_cl_{h}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="xui_inbounds")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
