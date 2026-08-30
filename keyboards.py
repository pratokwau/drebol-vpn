from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import load_config


# ── Главное меню ──────────────────────────────────────────────────────────────

def main_keyboard(is_admin: bool, has_sub: bool = False, paid_sub_status: str = "") -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_url = cfg.get("channel_url")

    news_btn = (
        InlineKeyboardButton("📰 Новости", url=channel_url)
        if channel_url
        else InlineKeyboardButton("📰 Новости", callback_data="news_no_channel")
    )

    rows = []
    rows.append([InlineKeyboardButton("👤 Моя подписка", callback_data="my_paid_sub")])
    if paid_sub_status in ("renewal", "expired"):
        rows.append([InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")])
    if has_sub:
        rows.append([InlineKeyboardButton("📋 Админская подписка", callback_data="my_sub")])
    rows.append([InlineKeyboardButton("👥 Пригласить друга", callback_data="referral")])
    rows.append([news_btn, InlineKeyboardButton("💬 Поддержка", callback_data="support_open")])
    rows.append([
        InlineKeyboardButton("❓ Как подключиться?", callback_data="how_to"),
        InlineKeyboardButton("ℹ️ О сервисе", callback_data="about"),
    ])
    if is_admin:
        rows.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


# ── Админка ───────────────────────────────────────────────────────────────────

def admin_keyboard(unread_tickets: int = 0) -> InlineKeyboardMarkup:
    tickets_label = f"🎫 Тикеты 🔴{unread_tickets}" if unread_tickets else "🎫 Тикеты"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Платные подписки", callback_data="paid_subs")],
        [InlineKeyboardButton("📋 Админские подписки", callback_data="admin_subs")],
        [InlineKeyboardButton("📣 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton(tickets_label, callback_data="ticket_list:1")],
        [InlineKeyboardButton("🔧 Параметры 3x-UI", callback_data="xui_settings")],
        [InlineKeyboardButton("🔄 Обновиться с GitHub", callback_data="git_update")],
        [InlineKeyboardButton("📢 Управление каналом", callback_data="channel_menu")],
        [InlineKeyboardButton("📄 Документы", callback_data="documents_menu")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_start")],
    ])


def channel_keyboard() -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_label = "📢 Изменить канал" if cfg.get("channel_url") else "📢 Установить канал"
    sub_enabled = cfg.get("force_subscribe", False)
    sub_label = "🔔 Обязательная подписка: ВКЛ" if sub_enabled else "🔕 Обязательная подписка: ВЫКЛ"
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

def support_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"support_page:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"support_page:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data=f"support_page:{page}")])
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])
    return InlineKeyboardMarkup(rows)


# ── Тикеты (админ) ────────────────────────────────────────────────────────────

def _ticket_badge(unread: int, last_from_admin: int) -> str:
    if unread and unread > 0:
        return f"🔴{unread}"
    if last_from_admin:
        return "✅"
    return "💬"


def ticket_list_keyboard(ticket_rows, page: int, total_pages: int) -> InlineKeyboardMarkup:
    keyboard = []
    for row in ticket_rows:
        user_id, first_name, username, total, unread, last_time, last_text, last_from_admin = row
        badge = _ticket_badge(unread, last_from_admin)
        name = first_name or str(user_id)
        uname = f" @{username}" if username else ""
        preview = (last_text or "").replace("\n", " ")
        if len(preview) > 22:
            preview = preview[:22] + "…"
        who = "🛡" if last_from_admin else "👤"
        label = f"{badge} {name}{uname} · {who}{preview}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"ticket_view:{user_id}:1")])

    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"ticket_list:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"ticket_list:{page + 1}"))
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)


def ticket_view_keyboard(user_id: int, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"ticket_view:{user_id}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"ticket_view:{user_id}:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton("✏️ Ответить", callback_data=f"ticket_reply:{user_id}")])
    rows.append([InlineKeyboardButton("◀️ К тикетам", callback_data="ticket_list:1")])
    return InlineKeyboardMarkup(rows)


# ── 3x-UI настройки ──────────────────────────────────────────────────────────

def xui_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 URL панели", callback_data="set_xui_url")],
        [InlineKeyboardButton("🔑 API Токен", callback_data="set_xui_token")],
        [InlineKeyboardButton("🔌 Порт подписки", callback_data="set_xui_sub_port")],
        [InlineKeyboardButton("📂 Путь подписки", callback_data="set_xui_sub_path")],
        [InlineKeyboardButton("🔌 Тест соединения", callback_data="test_xui")],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ])


# ── Общие ─────────────────────────────────────────────────────────────────────

def back_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_start")]])


def back_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")]])


def cancel_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="admin_panel")]])
