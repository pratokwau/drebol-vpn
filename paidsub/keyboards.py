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
    kb.append([InlineKeyboardButton("📬 Запросы", callback_data="paid_requests")])
    kb.append([
        InlineKeyboardButton("📜 История", callback_data="paid_history"),
        InlineKeyboardButton("🔇 Заглушённые", callback_data="paid_muted_list"),
    ])
    kb.append([InlineKeyboardButton("👥 Рефералы", callback_data="referral_settings")])
    kb.append([InlineKeyboardButton("⚙️ Настройки", callback_data="paid_sub_presets")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)


def paid_presets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆓 Пробный период", callback_data="paid_preset_trial")],
        [InlineKeyboardButton("💰 Период оплаты", callback_data="paid_preset_pay_period")],
        [InlineKeyboardButton("⏳ Время на продление", callback_data="paid_preset_renew")],
        [InlineKeyboardButton("💵 Сумма подписки", callback_data="paid_preset_price")],
        [InlineKeyboardButton("🔗 Ссылка на оплату", callback_data="paid_preset_pay_url")],
        [InlineKeyboardButton("🌐 Лимит IP", callback_data="paid_preset_ip")],
        [InlineKeyboardButton("🖥 Лимит HWID", callback_data="paid_preset_hwid")],
        [InlineKeyboardButton("📶 Трафик (ГБ)", callback_data="paid_preset_traffic")],
        [InlineKeyboardButton("📡 Инбаунды создания", callback_data="paid_inbounds_menu")],
        [InlineKeyboardButton("📡 Инбаунды окончания", callback_data="paid_inbounds_expire_menu")],
        [InlineKeyboardButton("⏰ Авто-обновление ников", callback_data="paid_auto_update_settings")],
        [InlineKeyboardButton("◀️ Назад к подпискам", callback_data="paid_subs")],
    ])


def paid_inbounds_keyboard(inbounds: list, selected_ids: list, mode: str = "create") -> InlineKeyboardMarkup:
    kb = []
    selected_set = set(int(i) for i in selected_ids)
    prefix = "paid_toggle_inbound" if mode == "create" else "paid_toggle_inbound_expire"
    for inb in inbounds:
        ib_id = inb.get("id")
        protocol = inb.get("protocol", "?")
        tag = inb.get("tag") or inb.get("remark") or f"#{ib_id}"
        port = inb.get("port", "")
        mark = "✅" if ib_id in selected_set else "🔘"
        kb.append([InlineKeyboardButton(
            f"{mark} {tag} ({protocol}:{port})",
            callback_data=f"{prefix}:{ib_id}",
        )])
    kb.append([InlineKeyboardButton("◀️ Назад к настройкам", callback_data="paid_sub_presets")])
    return InlineKeyboardMarkup(kb)


def paid_sub_view_keyboard(sub_id: int, enabled: bool = True) -> InlineKeyboardMarkup:
    toggle_label = "⏸ Отключить" if enabled else "▶️ Включить"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"paid_sub_toggle:{sub_id}")],
        [
            InlineKeyboardButton("🧊 Заморозить", callback_data=f"paid_sub_freeze:{sub_id}"),
            InlineKeyboardButton("➕ Добавить срок", callback_data=f"paid_sub_extend:{sub_id}"),
        ],
        [InlineKeyboardButton("⚙️ Настройки", callback_data=f"paid_sub_settings:{sub_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"paid_sub_delete:{sub_id}")],
        [InlineKeyboardButton("◀️ К списку", callback_data="paid_subs")],
    ])


def paid_sub_settings_keyboard(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Дата окончания", callback_data=f"paid_sub_edit_expire:{sub_id}")],
        [InlineKeyboardButton("🌐 Лимит IP", callback_data=f"paid_sub_edit_ip:{sub_id}")],
        [InlineKeyboardButton("🖥 Лимит HWID", callback_data=f"paid_sub_edit_hwid:{sub_id}")],
        [InlineKeyboardButton("📶 Трафик (ГБ)", callback_data=f"paid_sub_edit_traffic:{sub_id}")],
        [InlineKeyboardButton("🆓 Пробный период", callback_data=f"paid_sub_edit_trial:{sub_id}")],
        [InlineKeyboardButton("💰 Период оплаты", callback_data=f"paid_sub_edit_pay_period:{sub_id}")],
        [InlineKeyboardButton("⏳ Время на продление", callback_data=f"paid_sub_edit_renew:{sub_id}")],
        [InlineKeyboardButton("💵 Сумма подписки", callback_data=f"paid_sub_edit_price:{sub_id}")],
        [InlineKeyboardButton("🔗 Ссылка на оплату", callback_data=f"paid_sub_edit_pay_url:{sub_id}")],
        [InlineKeyboardButton("◀️ Назад к подписке", callback_data=f"paid_sub_view:{sub_id}")],
    ])


def paid_history_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    kb = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"paid_history_page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"paid_history_page:{page + 1}"))
    if total_pages > 1:
        kb.append(nav)
    kb.append([InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")])
    return InlineKeyboardMarkup(kb)


def approve_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Одобрить", callback_data=f"paid_approve:{tg_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"paid_reject:{tg_id}")],
        [InlineKeyboardButton("🔇 Заглушить", callback_data=f"paid_mute_user:{tg_id}")],
    ])


def payment_approve_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f"confirm_payment:{tg_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_payment:{tg_id}")],
        [InlineKeyboardButton("🔇 Заглушить", callback_data=f"paid_mute_user:{tg_id}")],
    ])


def paid_auto_update_keyboard(enabled: bool, days: int) -> InlineKeyboardMarkup:
    toggle_label = "🔔 Выключить" if enabled else "🔕 Включить"
    status = f"{'ВКЛ ✅' if enabled else 'ВЫКЛ ❌'} · каждые {days} дн."
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Статус: {status}", callback_data="noop")],
        [InlineKeyboardButton(toggle_label, callback_data="paid_toggle_auto_update")],
        [InlineKeyboardButton("📝 Изменить интервал (дней)", callback_data="paid_set_auto_update_days")],
        [InlineKeyboardButton("🔄 Обновить сейчас", callback_data="paid_run_sync_now")],
        [InlineKeyboardButton("◀️ Назад к настройкам", callback_data="paid_sub_presets")],
    ])


def muted_list_keyboard(muted_rows: list) -> InlineKeyboardMarkup:
    kb = []
    for tg_id, muted_until in muted_rows:
        kb.append([InlineKeyboardButton(
            f"🔇 {tg_id} · до {muted_until}",
            callback_data=f"paid_unmute_user:{tg_id}",
        )])
    kb.append([InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")])
    return InlineKeyboardMarkup(kb)
