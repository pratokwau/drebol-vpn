from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from sub.helpers import parse_clients
from sub.adminsub.storage import (
    DEFAULT_EXPIRY_TIME_MS,
    DEFAULT_FLOW,
    DEFAULT_LIMIT_GB,
    DEFAULT_LIMIT_IP,
    DEFAULT_MAX_DEVICES,
    ensure_anon_user_for_client,
    load_vpn_users,
)
from sub.utils import cache, CLIENTS_PAGE_SIZE, _cache


def admin_menu_kb(configured: bool) -> InlineKeyboardMarkup:
    status = "✅ Настроено" if configured else "⚠️ Не настроено"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔧 XUI: {status}", callback_data="xui_settings")],
            [InlineKeyboardButton(text="📡 Инбаунды", callback_data="xui_inbounds")],
        ]
    )


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Изменить URL", callback_data="xui_set_url")],
            [InlineKeyboardButton(text="🔐 Изменить токен", callback_data="xui_set_token")],
            [InlineKeyboardButton(text="📡 Порт подписки", callback_data="xui_set_sub_port")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="xui_back")],
        ]
    )


def inbounds_kb(inbounds: list[dict], *, show_settings: bool = True) -> InlineKeyboardMarkup:
    rows = []
    for ib in inbounds:
        ib_id = ib.get("id")
        protocol = str(ib.get("protocol", "?")).upper()
        port = ib.get("port", "?")
        remark = ib.get("remark") or f"{protocol}:{port}"
        clients_count = len(parse_clients(ib))
        enabled = "✅" if ib.get("enable", True) else "❌"
        h = cache(f"ib_{ib_id}", {"id": ib_id})
        prefix = f"{enabled} " if show_settings else ""
        rows.append([InlineKeyboardButton(text=f"{prefix}{remark} | {protocol}:{port} | 👥{clients_count}", callback_data=f"xui_ib_{h}")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="xui_inbounds")])
    if show_settings:
        rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data="xui_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clients_kb(inbound: dict, page: int = 0) -> InlineKeyboardMarkup:
    ib_id = inbound.get("id")
    clients = [
        cl for cl in parse_clients(inbound)
        if not str(cl.get("email", "")).startswith("paid_")
    ]
    current_emails = {str(cl.get("email", "")).strip() for cl in clients if str(cl.get("email", "")).strip()}
    vpn_users = load_vpn_users()
    grouped: dict[str, dict] = {}
    bound_emails = set()

    for user_key, info in vpn_users.items():
        if str(user_key).startswith("paid_") or str(info.get("subscription_type", "")).lower() == "paid":
            continue
        stored_devices = [
            dict(device)
            for device in info.get("devices", [])
        ]
        current_devices = [
            device
            for device in stored_devices
            if int(device.get("ib_id", 0) or 0) == int(ib_id or 0) and device.get("email") in current_emails
        ]
        should_show_user = bool(current_devices) or int(info.get("default_ib_id", 0) or 0) == int(ib_id or 0)
        if not should_show_user:
            continue
        grouped[str(user_key)] = {**info, "devices": current_devices}
        bound_emails.update(device.get("email") for device in current_devices if device.get("email"))

    for cl in clients:
        email = str(cl.get("email", "") or "").strip()
        if not email or email in bound_emails:
            continue
        anon_key = ensure_anon_user_for_client(int(ib_id or 0), str(cl.get("id", "") or ""), email)
        entry = grouped.setdefault(anon_key, {"subscription_type": "admin", "username": "", "note": "", "admin_disabled": False, "devices": []})
        entry["devices"] = [
            d for d in entry.get("devices", [])
            if not (d.get("ib_id") == ib_id and d.get("email") == email)
        ]
        entry["devices"].append({"ib_id": ib_id, "uuid": cl.get("id", ""), "email": email})
        bound_emails.add(email)

    items = []
    for user_key, info in sorted(grouped.items()):
        if str(user_key).startswith("paid_") or str(info.get("subscription_type", "")).lower() == "paid":
            continue
        username = info.get("username", "")
        note = info.get("note", "")
        n_devices = len([d for d in info.get("devices", []) if d.get("ib_id") == ib_id])
        prefix = "🚫" if info.get("admin_disabled", False) else "👤"
        label_name = next((d.get("label") for d in info.get("devices", []) if d.get("ib_id") == ib_id and d.get("label")), "")
        if user_key.startswith("anon_"):
            id_part = "Без TG ID"
        else:
            username_part = f" @{username}" if username else " (без username)"
            id_part = f"{user_key}{username_part}"
        note_suffix = f" • 📝{(label_name or note)[:15]}" if (label_name or note) else ""
        device_suffix = f" ({n_devices} устр.)" if n_devices else " (0 устр.)"
        items.append(("user", user_key, f"{prefix} {id_part}{device_suffix}{note_suffix}"))
    total = len(items)
    total_pages = (total + CLIENTS_PAGE_SIZE - 1) // CLIENTS_PAGE_SIZE or 1
    page = max(0, min(page, total_pages - 1))
    start = page * CLIENTS_PAGE_SIZE
    end = start + CLIENTS_PAGE_SIZE
    page_items = items[start:end]

    buttons = []
    for item_type, key, label in page_items:
        uk_hash = cache(f"uk_{key}", {"user_key": key, "ib_id": ib_id})
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"xui_usr_{uk_hash}")])

    ib_h = cache(f"ib_{ib_id}", {"id": ib_id})
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"xui_ibpg_{ib_h}_{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="none"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"xui_ibpg_{ib_h}_{page+1}"))
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="➕ Добавить пользователя", callback_data=f"xui_adduser_{ib_h}")])
    buttons.append([InlineKeyboardButton(text="⚙️ Настройки инбаунда", callback_data=f"xui_ibsettings_{ib_h}")])
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"xui_ib_{ib_h}"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="xui_inbounds"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def client_actions_kb(client_hash: str, enabled: bool, owner_user_key: str = "") -> InlineKeyboardMarkup:
    info = _cache.get(client_hash, {})
    ib_id = info.get("ib_id")
    ib_h = cache(f"ib_{ib_id}", {"id": ib_id})
    toggle_text = "❌ Отключить" if enabled else "✅ Включить"
    buttons = [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"xui_tog_{client_hash}")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data=f"xui_inst_{client_hash}")],
    ]
    if not owner_user_key:
        buttons.append([InlineKeyboardButton(text="📱 Привязать TG ID", callback_data=f"xui_bind_{client_hash}")])
    buttons.append([InlineKeyboardButton(text="📝 Изменить заметку", callback_data=f"xui_clnote_{client_hash}")])
    buttons.append([InlineKeyboardButton(text="🗑 Удалить устройство", callback_data=f"xui_del_{client_hash}")])
    if owner_user_key:
        uk_h = cache(f"uk_{owner_user_key}", {"user_key": owner_user_key, "ib_id": ib_id})
        back_cb = f"xui_usr_{uk_h}"
    else:
        back_cb = f"xui_ib_{ib_h}"
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"xui_cl_{client_hash}"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def flow_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ xtls-rprx-vision", callback_data="xui_flow_xtls")],
        [InlineKeyboardButton(text="⬜ Без flow", callback_data="xui_flow_none")],
    ])


def user_menu_kb(user_key: str, admin_disabled: bool, devices: list, ib_id_default: int, settings_ready: bool = True) -> InlineKeyboardMarkup:
    rows = []
    uk_h = cache(f"uk_{user_key}", {"user_key": user_key, "ib_id": ib_id_default})
    for d in devices:
        if d.get("ib_id") != ib_id_default:
            continue
        ib_id = d.get("ib_id")
        email = d.get("email", "?")
        uuid_val = d.get("uuid", "")
        h = cache(f"cl_{ib_id}_{email}", {"email": email, "uuid": uuid_val, "ib_id": ib_id, "owner_uk": user_key})
        rows.append([InlineKeyboardButton(text=f"📱 {email}", callback_data=f"xui_cl_{h}")])
    if admin_disabled:
        rows.append([InlineKeyboardButton(text="✅ Включить все", callback_data=f"xui_unblk_{uk_h}")])
    else:
        rows.append([InlineKeyboardButton(text="🚫 Отключить все", callback_data=f"xui_ublk_{uk_h}")])
    rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"xui_usetm_{uk_h}")])
    if settings_ready:
        rows.append([InlineKeyboardButton(text="➕ Добавить устройство", callback_data=f"xui_uadd_{uk_h}")])
    else:
        rows.append([InlineKeyboardButton(text="⚙️ Сначала настройте лимиты", callback_data=f"xui_uset_{uk_h}")])
    rows.append([InlineKeyboardButton(text="📝 Изменить заметку", callback_data=f"xui_unote_{uk_h}")])
    if user_key.startswith("anon_"):
        rows.append([InlineKeyboardButton(text="📱 Привязать TG ID", callback_data=f"xui_bindanon_{uk_h}")])
    else:
        rows.append([InlineKeyboardButton(text="🔓 Отвязать TG", callback_data=f"xui_uunbind_{uk_h}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить все устройства", callback_data=f"xui_udelall_{uk_h}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить пользователя", callback_data=f"xui_udel_user_{uk_h}")])
    ib_h = cache(f"ib_{ib_id_default}", {"id": ib_id_default})
    rows.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"xui_usr_{uk_h}"),
        InlineKeyboardButton(text="⬅️ К списку", callback_data=f"xui_ib_{ib_h}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_settings_kb(user_key: str, info: dict) -> InlineKeyboardMarkup:
    uk_h = cache(f"uk_{user_key}", {"user_key": user_key, "ib_id": int(info.get("default_ib_id", 0) or 0)})
    max_devices = info.get("max_devices")
    limit_gb = info.get("limit_gb")
    expiry_time = info.get("expiry_time_ms")
    limit_ip = info.get("limit_ip")
    flow = info.get("flow")
    rows = [
        [
            InlineKeyboardButton(text=f"📱 Лимит устройств: {max_devices if max_devices is not None else DEFAULT_MAX_DEVICES}", callback_data=f"xui_set_max_{uk_h}"),
            InlineKeyboardButton(text="По дефолту", callback_data=f"xui_def_max_{uk_h}"),
        ],
        [
            InlineKeyboardButton(text=f"💾 Лимит ГБ: {limit_gb if limit_gb is not None else DEFAULT_LIMIT_GB}", callback_data=f"xui_set_gb_{uk_h}"),
            InlineKeyboardButton(text="По дефолту", callback_data=f"xui_def_gb_{uk_h}"),
        ],
        [
            InlineKeyboardButton(text=f"⏳ Дата окончания: {expiry_time if expiry_time is not None else DEFAULT_EXPIRY_TIME_MS}", callback_data=f"xui_set_exp_{uk_h}"),
            InlineKeyboardButton(text="По дефолту", callback_data=f"xui_def_exp_{uk_h}"),
        ],
        [
            InlineKeyboardButton(text=f"🌐 Лимит IP: {limit_ip if limit_ip is not None else DEFAULT_LIMIT_IP}", callback_data=f"xui_set_ip_{uk_h}"),
            InlineKeyboardButton(text="По дефолту", callback_data=f"xui_def_ip_{uk_h}"),
        ],
        [
            InlineKeyboardButton(text=f"⚡ Flow: {flow if flow is not None else DEFAULT_FLOW}", callback_data=f"xui_def_flow_{uk_h}"),
            InlineKeyboardButton(text="По дефолту", callback_data=f"xui_def_flow_{uk_h}"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"xui_usr_{uk_h}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inbound_settings_kb(inbound_id: int, sub_port: str) -> InlineKeyboardMarkup:
    ib_h = cache(f"ib_{inbound_id}", {"id": inbound_id})
    current = sub_port or "не задан"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📡 Порт подписки: {current}", callback_data=f"xui_ibsubport_{ib_h}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"xui_ib_{ib_h}")],
        ]
    )


def myvpn_main_kb(devices: list, admin_disabled: bool, settings_ready: bool = True) -> InlineKeyboardMarkup:
    rows = []
    rows.append([
        InlineKeyboardButton(text="ℹ️ Информация", callback_data="myvpn_info"),
        InlineKeyboardButton(text="📖 Инструкция", callback_data="myvpn_inst_main"),
    ])
    for d in devices:
        ib_id = d.get("ib_id")
        email = d.get("email", "?")
        label = d.get("label") or email
        uuid_val = d.get("uuid", "")
        enabled = bool(d.get("enabled", True))
        h = cache(f"mvd_{ib_id}_{email}", {"email": email, "uuid": uuid_val, "ib_id": ib_id})
        icon = "✅" if enabled else "⏸"
        rows.append([InlineKeyboardButton(text=f"{icon} {label}", callback_data=f"myvpn_dev_{h}")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="myvpn_refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def myvpn_device_kb(dev_hash: str, enabled: bool, admin_disabled: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📖 Инструкция", callback_data=f"myvpn_inst_{dev_hash}")],
    ]
    if not admin_disabled:
        toggle_text = "⏸ Отключить" if enabled else "▶️ Включить"
        rows.append([InlineKeyboardButton(text=toggle_text, callback_data=f"myvpn_tog_{dev_hash}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="myvpn_refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
