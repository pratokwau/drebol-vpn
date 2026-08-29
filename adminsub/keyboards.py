from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def subs_list_keyboard(rows, page: int, total_pages: int, presets_ready: bool) -> InlineKeyboardMarkup:
    kb = []
    for sub_id, email, expire, total_gb, _ in rows:
        traffic = f"{total_gb}ГБ" if total_gb > 0 else "∞"
        kb.append([InlineKeyboardButton(
            f"{email} · до {expire} · {traffic}",
            callback_data=f"sub_view:{sub_id}",
        )])
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"subs_page:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"subs_page:{page + 1}"))
        kb.append(nav)

    create_label = "➕ Создать подписку" if presets_ready else "➕ Создать (сначала настройки)"
    kb.append([InlineKeyboardButton(create_label, callback_data="create_sub")])
    kb.append([InlineKeyboardButton("⚙️ Настройки", callback_data="sub_presets")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)


def presets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Дата окончания", callback_data="preset_expire")],
        [InlineKeyboardButton("🌐 Лимит IP", callback_data="preset_ip")],
        [InlineKeyboardButton("🖥 Лимит HWID", callback_data="preset_hwid")],
        [InlineKeyboardButton("📶 Трафик (ГБ)", callback_data="preset_traffic")],
        [InlineKeyboardButton("◀️ Назад к подпискам", callback_data="admin_subs")],
    ])


def sub_view_keyboard(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Удалить из базы", callback_data=f"sub_delete:{sub_id}")],
        [InlineKeyboardButton("◀️ К списку", callback_data="admin_subs")],
    ])
