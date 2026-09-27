from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def paid_subs_list_keyboard(rows, page: int, total_pages: int, presets_ready: bool) -> InlineKeyboardMarkup:
    kb = []
    for row in rows:
        sub_id, tg_id, email, expire, total_gb, _ = row
        traffic = f"{total_gb} ГБ" if total_gb > 0 else "∞"
        # в кнопку влезает мало: имя клиента и дата без секунд
        name = str(email or "").removeprefix("paid_")
        kb.append([InlineKeyboardButton(
            f"👤 {name} · до {str(expire)[:10]} · {traffic}",
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
    kb.append([
        InlineKeyboardButton("⚡ Массовые", callback_data="paid_bulk_menu"),
        InlineKeyboardButton("📜 История", callback_data="act_feed:subs:1"),
    ])
    kb.append([
        InlineKeyboardButton("🎟 Промокоды", callback_data="promo_menu"),
        InlineKeyboardButton("👥 Рефералы", callback_data="referral_settings"),
    ])
    kb.append([InlineKeyboardButton("⚙️ Настройки подписок", callback_data="paid_sub_presets")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)


def _money_rows(b) -> list:
    return [[b("🏷 Тарифы", "tariffs_menu"), b("💳 Платёжка", "pay_provider_menu")]]


def _devices_rows(b) -> list:
    return [[b("📱 Цена устройства", "paid_device_price"),
             b("📱 Максимум докупа", "paid_device_max")]]


def paid_presets_keyboard() -> InlineKeyboardMarkup:
    from config import load_config
    cfg = load_config()
    auto_trial = cfg.get("auto_approve_trial", False)
    auto_label = "⚡ Авто-триал · вкл ✅" if auto_trial else "⚡ Авто-триал · выкл"

    def b(text, cb):
        return InlineKeyboardButton(text, callback_data=cb)

    return InlineKeyboardMarkup([
        [b(auto_label, "toggle_auto_trial")],
        # сроки
        [b("🆓 Пробный период", "paid_preset_trial")],
        # деньги — показываем то, что умеет активная платёжка
        *_money_rows(b),
        # лимиты
        [b("🖥 Лимит устройств", "paid_preset_hwid")],
        *_devices_rows(b),
        [b("📶 Трафик (ГБ)", "paid_preset_traffic")],
        # панель
        [b("👥 Сквады Remnawave", "rw_squads")],
        [b("◀️ Назад к подпискам", "paid_subs")],
    ])




def paid_sub_view_keyboard(sub_id: int, enabled: bool = True) -> InlineKeyboardMarkup:
    toggle_label = "⏸ Отключить" if enabled else "▶️ Включить"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"paid_sub_toggle:{sub_id}"),
         InlineKeyboardButton("❄️ Заморозить", callback_data=f"paid_sub_freeze:{sub_id}")],
        [
            InlineKeyboardButton("➕ Добавить срок", callback_data=f"paid_sub_extend:{sub_id}"),
            InlineKeyboardButton("➖ Убавить срок", callback_data=f"paid_sub_reduce:{sub_id}"),
        ],
        [
            InlineKeyboardButton("📱 Устройства", callback_data=f"paid_devices:{sub_id}"),
            InlineKeyboardButton("🌐 IP-адреса", callback_data=f"paid_ips:{sub_id}"),
        ],
        [InlineKeyboardButton("⚙️ Настройки", callback_data=f"paid_sub_settings:{sub_id}"),
         InlineKeyboardButton("🗑 Удалить", callback_data=f"paid_sub_delete:{sub_id}")],
        [InlineKeyboardButton("◀️ К списку", callback_data="paid_subs")],
    ])


def paid_sub_settings_keyboard(sub_id: int) -> InlineKeyboardMarkup:
    def b(text, action):
        return InlineKeyboardButton(text, callback_data=f"{action}:{sub_id}")

    return InlineKeyboardMarkup([
        [b("📅 Дата окончания", "paid_sub_edit_expire")],
        [b("🖥 Лимит устройств", "paid_sub_edit_hwid")],
        [b("📶 Трафик (ГБ)", "paid_sub_edit_traffic"), b("🆓 Пробный период", "paid_sub_edit_trial")],
        [InlineKeyboardButton("◀️ Назад к подписке", callback_data=f"paid_sub_view:{sub_id}")],
    ])


def approve_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Одобрить", callback_data=f"paid_approve:{tg_id}"),
         InlineKeyboardButton("❌ Отклонить", callback_data=f"paid_reject:{tg_id}")],
    ])
