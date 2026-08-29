from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def paid_subs_list_keyboard(rows, page: int, total_pages: int, presets_ready: bool) -> InlineKeyboardMarkup:
    kb = []
    for row in rows:
        sub_id, tg_id, email, expire, total_gb, _ = row
        traffic = f"{total_gb}ГБ" if total_gb > 0 else "∞"
        tg_label = f"tg:{tg_id} · " if tg_id else ""
        kb.append([InlineKeyboardButton(
            f"{tg_label}{email} · до {expire} · {traffic}",
            callback_data=f"paid_sub_view:{sub_id}",
        )])
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"paid_subs_page:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"paid_subs_page:{page + 1}"))
        kb.append(nav)

    create_label = "➕ Создать подписку" if presets_ready else "➕ Создать (сначала настройки)"
    kb.append([InlineKeyboardButton(create_label, callback_data="paid_create_sub")])
    kb.append([InlineKeyboardButton("⚙️ Настройки", callback_data="paid_sub_presets")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)


def paid_presets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Дата окончания", callback_data="paid_preset_expire")],
        [InlineKeyboardButton("🌐 Лимит IP", callback_data="paid_preset_ip")],
        [InlineKeyboardButton("🖥 Лимит HWID", callback_data="paid_preset_hwid")],
        [InlineKeyboardButton("📶 Трафик (ГБ)", callback_data="paid_preset_traffic")],
        [InlineKeyboardButton("📡 Инбаунды подписки", callback_data="paid_inbounds_menu")],
        [InlineKeyboardButton("◀️ Назад к подпискам", callback_data="paid_subs")],
    ])


def paid_inbounds_keyboard(inbounds: list, selected_ids: list) -> InlineKeyboardMarkup:
    kb = []
    selected_set = set(int(i) for i in selected_ids)
    for inb in inbounds:
        ib_id = inb.get("id")
        protocol = inb.get("protocol", "?")
        tag = inb.get("tag") or inb.get("remark") or f"#{ib_id}"
        port = inb.get("port", "")
        mark = "✅" if ib_id in selected_set else "🔘"
        kb.append([InlineKeyboardButton(
            f"{mark} {tag} ({protocol}:{port})",
            callback_data=f"paid_toggle_inbound:{ib_id}",
        )])
    kb.append([InlineKeyboardButton("◀️ Назад к настройкам", callback_data="paid_sub_presets")])
    return InlineKeyboardMarkup(kb)


def paid_sub_view_keyboard(sub_id: int, enabled: bool = True) -> InlineKeyboardMarkup:
    toggle_label = "⏸ Отключить" if enabled else "▶️ Включить"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"paid_sub_toggle:{sub_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"paid_sub_delete:{sub_id}")],
        [InlineKeyboardButton("◀️ К списку", callback_data="paid_subs")],
    ])
