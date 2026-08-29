from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import load_config


# ── Главное меню ──────────────────────────────────────────────────────────────

def main_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    cfg = load_config()
    rows = [
        [InlineKeyboardButton("📦 Моя подписка", callback_data="my_sub")],
        [
            InlineKeyboardButton("📰 Новости", callback_data="news"),
            InlineKeyboardButton("💬 Поддержка", callback_data="support_page:1"),
        ],
        [
            InlineKeyboardButton("❓ Как подключиться?", callback_data="how_to"),
            InlineKeyboardButton("ℹ️ О сервисе", callback_data="about"),
        ],
    ]
    if cfg.get("channel_url"):
        rows.append([InlineKeyboardButton("📢 Наш канал", url=cfg["channel_url"])])
    if is_admin:
        rows.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


# ── Админка ───────────────────────────────────────────────────────────────────

def admin_keyboard() -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_label = "📢 Изменить канал" if cfg.get("channel_url") else "📢 Установить канал"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📣 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton("🎫 Тикеты", callback_data="ticket_list:1")],
        [InlineKeyboardButton("🔄 Обновиться с GitHub", callback_data="git_update")],
        [InlineKeyboardButton(channel_label, callback_data="set_channel")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_start")],
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
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])
    return InlineKeyboardMarkup(rows)


# ── Тикеты (админ) ────────────────────────────────────────────────────────────

def ticket_list_keyboard(ticket_rows, page: int, total_pages: int) -> InlineKeyboardMarkup:
    keyboard = []
    for user_id, first_name, username, cnt, _ in ticket_rows:
        label = f"{first_name} (@{username}) · {cnt} сообщ." if username else f"{first_name} · {cnt} сообщ."
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


# ── Общие ─────────────────────────────────────────────────────────────────────

def back_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_start")]])


def back_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")]])


def cancel_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="admin_panel")]])
