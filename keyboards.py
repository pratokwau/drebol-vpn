from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import load_config


# ── Главное меню ──────────────────────────────────────────────────────────────

def main_keyboard(is_admin: bool, has_sub: bool = False, paid_sub_status: str = "",
                  is_helper: bool = False) -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_url = cfg.get("channel_url")

    news_btn = (
        InlineKeyboardButton("📰 Новости", url=channel_url)
        if channel_url
        else InlineKeyboardButton("📰 Новости", callback_data="news_no_channel")
    )

    # выключенные в техработах функции прячем от пользователей; админ видит всё
    import maintenance as mnt

    def on(key: str) -> bool:
        return is_admin or mnt.feature_enabled(key)

    rows = []
    # у кого подписка есть — заходит в действия с ней, у кого нет — оформляет
    rows.append([InlineKeyboardButton(
        "⚙️ Моя подписка" if paid_sub_status else "🆓 Получить подписку",
        callback_data="my_paid_sub")])
    # вторым рядом — то, за чем приходят чаще всего; парой, чтобы меню было короче
    pair = []
    # продлить можно в любой момент — остаток не сгорает
    if paid_sub_status and on("payments"):
        pair.append(InlineKeyboardButton("💳 Продлить", callback_data="renew_sub"))
    if paid_sub_status and on("referral"):
        pair.append(InlineKeyboardButton("👥 Пригласить друга", callback_data="referral"))
    if pair:
        rows.append(pair)
    if has_sub:
        rows.append([InlineKeyboardButton("📋 Админская подписка", callback_data="my_sub")])
    if on("support"):
        rows.append([InlineKeyboardButton("💬 Поддержка", callback_data="support_open"),
                     InlineKeyboardButton("ℹ️ Инфо", callback_data="info")])
    else:
        rows.append([InlineKeyboardButton("ℹ️ Инфо", callback_data="info")])
    rows.append([news_btn])
    if is_admin:
        rows.append([InlineKeyboardButton("🛠 Админка", callback_data="admin_panel")])
    elif is_helper:
        rows.append([InlineKeyboardButton("🛡 Панель поддержки", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


# ── Админка ───────────────────────────────────────────────────────────────────

def admin_keyboard(unread_tickets: int = 0) -> InlineKeyboardMarkup:
    tickets_label = f"🎫 Тикеты · 🔴 {unread_tickets}" if unread_tickets else "🎫 Тикеты"
    # включённые техработы должны бросаться в глаза, чтобы про них не забыли
    import maintenance as mnt
    mnt_label = "🔴 Техработы ВКЛЮЧЕНЫ" if mnt.is_maintenance() else "🛠 Техработы и функции"

    def b(text, cb):
        return InlineKeyboardButton(text, callback_data=cb)

    # Кнопки сгруппированы по смыслу и стоят парами — так вся админка
    # помещается на один экран телефона без прокрутки
    return InlineKeyboardMarkup([
        # сводка и деньги
        [b("📊 Статистика", "dashboard"), b("💰 Оплаты", "payments:paid:1")],
        # люди и подписки
        [b("🔍 Найти юзера", "find_user"), b("🛰 Контроль", "ctl_menu")],
        [b("💳 Платные подписки", "paid_subs"), b("📋 Админские", "admin_subs")],
        # общение
        [b(tickets_label, "ticket_list:1"), b("📣 Рассылка", "broadcast")],
        [b("👥 Помощники", "helpers_menu"), b("📢 Канал", "channel_menu")],
        # удержание и защита
        [b("🎯 Winback", "winback_settings"), b("⏰ Напоминания", "remind_settings")],
        [b("⛔ Чёрный список", "bl_menu"), b("🕵 Повторные триалы", "fraud_menu")],
        # инфраструктура
        [b("🖥 Серверы и 3x-UI", "xui_settings"), b("🌐 Сайт", "site_menu")],
        [b("💾 Бэкап и перенос", "backup_menu")],
        [b("📄 Документы", "documents_menu"), b("🧾 Лог-канал", "log_channel_settings")],
        [b(mnt_label, "mnt_menu")],
        [b("🔄 Обновиться с GitHub", "git_update")],
        [b("◀️ Главное меню", "back_start")],
    ])


def channel_keyboard() -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_label = "📢 Изменить канал" if cfg.get("channel_url") else "📢 Установить канал"
    sub_enabled = cfg.get("force_subscribe", False)
    sub_label = "🔔 Обязательная подписка · вкл" if sub_enabled else "🔕 Обязательная подписка · выкл"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(channel_label, callback_data="set_channel")],
        [InlineKeyboardButton(sub_label, callback_data="toggle_force_sub")],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ])


def documents_keyboard() -> InlineKeyboardMarkup:
    cfg = load_config()
    privacy_label = "📋 Изменить политику конф." if cfg.get("privacy_url") else "📋 Политика конфиденциальности"
    terms_label = "📄 Изменить польз. соглашение" if cfg.get("terms_url") else "📄 Пользовательское соглашение"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(privacy_label, callback_data="set_privacy_url")],
        [InlineKeyboardButton(terms_label, callback_data="set_terms_url")],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ])


# ── Поддержка (юзер) ──────────────────────────────────────────────────────────

def support_keyboard(page: int, total_pages: int, has_files: bool = False,
                     can_close: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"support_page:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"support_page:{page + 1}"))
        rows.append(nav)
    extra = [InlineKeyboardButton("🔄 Обновить", callback_data=f"support_page:{page}")]
    if has_files:
        extra.insert(0, InlineKeyboardButton("📎 Файлы", callback_data="support_files"))
    if can_close:
        extra.append(InlineKeyboardButton("✅ Вопрос решён", callback_data="support_close"))
    rows.append(extra)
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])
    return InlineKeyboardMarkup(rows)


def support_topics_keyboard(topics: dict) -> InlineKeyboardMarkup:
    """Темы обращения: по две в ряд, чтобы экран не растягивался."""
    rows, pair = [], []
    for key, t in topics.items():
        pair.append(InlineKeyboardButton(f"{t['emoji']} {t['name']}",
                                         callback_data=f"support_topic:{key}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])
    return InlineKeyboardMarkup(rows)


# ── Тикеты (админ) ────────────────────────────────────────────────────────────

_TICKET_TABS = (("open", "🔴 Открытые"), ("answered", "✅ Отвеченные"),
                ("closed", "🗂 Закрытые"))


def ticket_list_keyboard(ticket_rows, page: int, total_pages: int,
                         status: str = "open") -> InlineKeyboardMarkup:
    keyboard = []
    # Подробности видно в тексте сообщения, поэтому кнопка короткая:
    # номер, имя и сколько человек ждёт
    row_btns = []
    for i, row in enumerate(ticket_rows, 1):
        user_id, first_name = row[0], row[1]
        t_status, waiting = row[8], row[10]
        name = (first_name or str(user_id))[:12]
        mark = {"open": "🔴", "answered": "✅", "closed": "🗂"}.get(t_status, "💬")
        label = f"{i}. {mark} {name}"
        if t_status == "open" and waiting:
            from handlers.tickets import fmt_wait
            label += f" · {fmt_wait(waiting)}"
        row_btns.append(InlineKeyboardButton(label, callback_data=f"ticket_view:{user_id}:1"))
        if len(row_btns) == 2:
            keyboard.append(row_btns)
            row_btns = []
    if row_btns:
        keyboard.append(row_btns)

    tabs = [InlineKeyboardButton(("• " if status == key else "") + label,
                                 callback_data=f"ticket_tab:{key}:1")
            for key, label in _TICKET_TABS]
    keyboard.append(tabs)

    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"ticket_tab:{status}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"ticket_tab:{status}:{page + 1}"))
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("⚡ Шаблоны", callback_data="quick_menu")])
    keyboard.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)


def ticket_view_keyboard(user_id: int, page: int, total_pages: int,
                         has_files: bool = False, closed: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"ticket_view:{user_id}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"ticket_view:{user_id}:{page + 1}"))
        rows.append(nav)
    rows.append([
        InlineKeyboardButton("✏️ Ответить", callback_data=f"ticket_reply:{user_id}"),
        InlineKeyboardButton("⚡ Шаблон", callback_data=f"ticket_quick:{user_id}"),
    ])
    second = [InlineKeyboardButton("👤 Профиль", callback_data=f"user_profile:{user_id}")]
    if has_files:
        second.insert(0, InlineKeyboardButton("📎 Файлы", callback_data=f"ticket_files:{user_id}"))
    if not closed:
        second.append(InlineKeyboardButton("✅ Закрыть", callback_data=f"ticket_close:{user_id}"))
    rows.append(second)
    rows.append([InlineKeyboardButton("◀️ К тикетам", callback_data="ticket_list:1")])
    return InlineKeyboardMarkup(rows)


# ── 3x-UI настройки ──────────────────────────────────────────────────────────

def xui_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🩺 Здоровье серверов", callback_data="healthcheck"),
         InlineKeyboardButton("🖧 Узлы", callback_data="nodes_menu")],
        [InlineKeyboardButton("🌐 URL панели", callback_data="set_xui_url"),
         InlineKeyboardButton("🔑 API-токен", callback_data="set_xui_token")],
        [InlineKeyboardButton("🔌 Порт подписки", callback_data="set_xui_sub_port"),
         InlineKeyboardButton("📂 Путь подписки", callback_data="set_xui_sub_path")],
        [InlineKeyboardButton("📡 Проверить соединение", callback_data="test_xui")],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ])


# ── Общие ─────────────────────────────────────────────────────────────────────

def back_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_start")]])


def back_info() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="info")]])


def back_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")]])


def cancel_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="admin_panel")]])
