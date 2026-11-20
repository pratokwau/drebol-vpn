from telegram import InlineKeyboardButton, InlineKeyboardMarkup


ADMIN_TABS = {
    "all": ("📋", "Все"),
    "active": ("🟢", "Активные"),
    "soon": ("⏳", "Скоро кончатся"),
    "expired": ("🔴", "Истёкшие"),
}

ADMIN_SORT_LABELS = {"new": "новые сверху", "expire": "по сроку", "name": "по имени"}
ADMIN_SORT_NEXT = {"new": "expire", "expire": "name", "name": "new"}


def subs_list_keyboard(rows, page: int, total_pages: int, presets_ready: bool,
                       scope: str = "all", sort: str = "new",
                       counts: dict = None) -> InlineKeyboardMarkup:
    counts = counts or {}
    kb = []
    for row in rows:
        sub_id, tg_id, email, expire, total_gb, _ = row
        traffic = f"{total_gb} ГБ" if total_gb > 0 else "∞"
        name = str(email or "") or f"tg:{tg_id}"
        kb.append([InlineKeyboardButton(
            f"👤 {name} · до {str(expire)[:10]} · {traffic}",
            callback_data=f"sub_view:{sub_id}",
        )])
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"subs_page:{scope}:{sort}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"subs_page:{scope}:{sort}:{page + 1}"))
        kb.append(nav)

    def tab(key):
        icon, _label = ADMIN_TABS[key]
        count = counts.get(key)
        text = f"{icon} {count}" if count is not None else icon
        return InlineKeyboardButton(("• " if key == scope else "") + text,
                                    callback_data=f"subs_page:{key}:{sort}:1")

    kb.append([tab(k) for k in ADMIN_TABS])
    kb.append([InlineKeyboardButton(
        f"🔀 Сортировка: {ADMIN_SORT_LABELS.get(sort, sort)}",
        callback_data=f"subs_page:{scope}:{ADMIN_SORT_NEXT.get(sort, 'new')}:1")])

    create_label = "➕ Создать подписку" if presets_ready else "➕ Создать (сначала настройки)"
    kb.append([InlineKeyboardButton(create_label, callback_data="create_sub")])
    kb.append([InlineKeyboardButton("🔎 Поиск подписки", callback_data="admin_sub_search")])
    kb.append([InlineKeyboardButton("⚙️ Настройки подписок", callback_data="sub_presets")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)


def presets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Дата окончания", callback_data="preset_expire")],
        [InlineKeyboardButton("🖥 Лимит устройств", callback_data="preset_hwid")],
        [InlineKeyboardButton("📶 Трафик (ГБ)", callback_data="preset_traffic")],
        [InlineKeyboardButton("📡 LTE-трафик (ГБ/мес)", callback_data="preset_lte")],
        # доступ к серверам задают сквады панели
        [InlineKeyboardButton("🗂 Сквады Remnawave", callback_data="rw_squads")],
        [InlineKeyboardButton("🔄 Обновить ники в панели", callback_data="subs_names_sync")],
        [InlineKeyboardButton("◀️ Назад к подпискам", callback_data="admin_subs")],
    ])






def sub_view_keyboard(sub_id: int, enabled: bool = True) -> InlineKeyboardMarkup:
    toggle_label = "⏸ Отключить" if enabled else "▶️ Включить"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"sub_toggle:{sub_id}"),
         InlineKeyboardButton("❄️ Заморозить", callback_data=f"sub_freeze:{sub_id}")],
        [
            InlineKeyboardButton("➕ Добавить срок", callback_data=f"sub_extend:{sub_id}"),
            InlineKeyboardButton("➖ Убавить срок", callback_data=f"sub_reduce:{sub_id}"),
        ],
        [
            InlineKeyboardButton("📱 Устройства", callback_data=f"sub_devices:{sub_id}"),
            InlineKeyboardButton("🌐 IP-адреса", callback_data=f"sub_ips:{sub_id}"),
        ],
        [InlineKeyboardButton("📜 История", callback_data=f"sub_history:{sub_id}"),
         InlineKeyboardButton("🔁 Перевыпустить ключ", callback_data=f"sub_reissue:{sub_id}")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data=f"sub_settings:{sub_id}"),
         InlineKeyboardButton("🗑 Удалить", callback_data=f"sub_delete:{sub_id}")],
        [InlineKeyboardButton("◀️ К списку", callback_data="admin_subs")],
    ])


def sub_settings_keyboard(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Дата окончания", callback_data=f"sub_edit_expire:{sub_id}")],
        [InlineKeyboardButton("🖥 Лимит устройств", callback_data=f"sub_edit_hwid:{sub_id}")],
        [InlineKeyboardButton("📶 Трафик (ГБ)", callback_data=f"sub_edit_traffic:{sub_id}")],
        [InlineKeyboardButton("📡 LTE-трафик (ГБ/мес)", callback_data=f"sub_edit_lte:{sub_id}")],
        [InlineKeyboardButton("◀️ Назад к подписке", callback_data=f"sub_view:{sub_id}")],
    ])
