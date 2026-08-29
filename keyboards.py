from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import load_config


def main_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    cfg = load_config()
    rows = [
        [InlineKeyboardButton("🛒 Купить VPN", callback_data="buy")],
        [InlineKeyboardButton("ℹ️ О сервисе", callback_data="about")],
    ]
    if cfg.get("channel_url"):
        rows.append([InlineKeyboardButton("📢 Наш канал", url=cfg["channel_url"])])
    if is_admin:
        rows.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_label = "📢 Изменить канал" if cfg.get("channel_url") else "📢 Установить канал"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновиться с GitHub", callback_data="git_update")],
        [InlineKeyboardButton(channel_label, callback_data="set_channel")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_start")],
    ])


def back_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад", callback_data="back_start")]
    ])


def back_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")]
    ])
