from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import load_config


# ── Цвета кнопок (Bot API 9.4) ───────────────────────────────────────────────
# Кнопок в боте больше четырёхсот, поэтому цвет назначается одним правилом по
# callback_data, а не руками в каждом месте. Красим только осмысленные действия:
# опасные — красным, подтверждающие — зелёным, главные целевые — синим.
# Навигация, настройки и переключатели остаются обычными, иначе рябит в глазах.

_DANGER_EXACT = {
    "clear_log_channel", "git_update", "bl_add", "bl_add_apply", "paid_bulk_reduce",
    "support_open",
}
_DANGER_PREFIX = (
    "paid_sub_delete:", "sub_delete:", "promo_delete:", "tariff_del:", "tariff_del_ok:",
    "ban_user:", "paid_mute_user:", "bl_add_for:", "bl_readd:", "bl_stop:", "helper_del:",
    "paid_reject:", "reject_payment:", "refund_start:", "refund_do:",
    "paid_sub_reduce:", "paid_sub_freeze:", "paid_hwid_del:", "paid_hwid_clear:",
    "paid_ips_clear:",
)
_SUCCESS_EXACT = {
    "check_sub", "i_paid", "bcast_send", "paid_bulk_extend", "paid_fix_renew_apply",
    "promo_seg_do",
}
_SUCCESS_PREFIX = (
    "confirm_payment:", "paid_approve:", "unban_user:", "paid_unmute_user:",
    "bl_del:", "promo_give_do:", "paid_sub_extend:",
)
_PRIMARY_EXACT = {
    "my_paid_sub", "renew_sub", "pay_invoice", "enter_promo",
    "qr_code", "copy_sub", "reissue_key", "buy", "prices", "how_to",
    "admin_panel", "dev_buy_menu", "my_devices",
}
_PRIMARY_PREFIX = ("pay_invoice:", "dev_buy:", "tariff_pick:")


def style_for(data: str | None) -> str | None:
    """Цвет кнопки по её действию. None — обычная кнопка."""
    if not data:
        return None
    confirmed = data.startswith("ok:")   # «Да» на экране подтверждения
    key = data[3:] if confirmed else data
    if key in _DANGER_EXACT or key.startswith(_DANGER_PREFIX):
        return "danger"
    if confirmed:
        return "success"
    if key in _SUCCESS_EXACT or key.startswith(_SUCCESS_PREFIX):
        return "success"
    if key in _PRIMARY_EXACT or key.startswith(_PRIMARY_PREFIX):
        return "primary"
    return None


def enable_button_colors() -> None:
    """Включает раскраску всех кнопок бота. Вызывается один раз при старте.

    Библиотека 21.9 о поле style не знает, поэтому оно уходит через api_kwargs —
    to_dict() отправляет их как есть. Там, где стиль задан руками, он в силе.
    Чтобы отключить цвета целиком, достаточно убрать вызов в bot.py.
    """
    if getattr(InlineKeyboardButton, "_drebol_colors", False):
        return
    original = InlineKeyboardButton.__init__

    def coloured(self, text, *args, api_kwargs=None, **kwargs):
        style = (api_kwargs or {}).get("style") or style_for(kwargs.get("callback_data"))
        if style:
            api_kwargs = {**(api_kwargs or {}), "style": style}
        original(self, text, *args, api_kwargs=api_kwargs, **kwargs)

    InlineKeyboardButton.__init__ = coloured
    InlineKeyboardButton._drebol_colors = True


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
    rows.append([InlineKeyboardButton("👤 Моя подписка", callback_data="my_paid_sub")])
    # продлить можно в любой момент — остаток не сгорает
    if paid_sub_status and on("payments"):
        rows.append([InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")])
    if has_sub:
        rows.append([InlineKeyboardButton("📋 Админская подписка", callback_data="my_sub")])
    if paid_sub_status and on("referral"):
        rows.append([InlineKeyboardButton("👥 Пригласить друга", callback_data="referral")])
    if on("support"):
        rows.append([news_btn, InlineKeyboardButton("💬 Поддержка", callback_data="support_open")])
    else:
        rows.append([news_btn])
    rows.append([InlineKeyboardButton("ℹ️ Инфо", callback_data="info")])
    if is_admin:
        rows.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel")])
    elif is_helper:
        rows.append([InlineKeyboardButton("🛡 Панель поддержки", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


# ── Админка ───────────────────────────────────────────────────────────────────

def admin_keyboard(unread_tickets: int = 0) -> InlineKeyboardMarkup:
    tickets_label = f"🎫 Тикеты 🔴{unread_tickets}" if unread_tickets else "🎫 Тикеты"
    # включённые техработы должны бросаться в глаза, чтобы про них не забыли
    import maintenance as mnt
    mnt_label = "🛠 Техработы: ВКЛЮЧЕНЫ 🔴" if mnt.is_maintenance() else "🛠 Техработы и функции"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data="dashboard")],
        [InlineKeyboardButton("💰 Оплаты", callback_data="payments:paid:1")],
        [InlineKeyboardButton("🛰 Контроль", callback_data="ctl_menu")],
        [InlineKeyboardButton("💳 Платные подписки", callback_data="paid_subs")],
        [InlineKeyboardButton("📋 Админские подписки", callback_data="admin_subs")],
        [InlineKeyboardButton("🔍 Найти юзера", callback_data="find_user")],
        [InlineKeyboardButton("📣 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton(tickets_label, callback_data="ticket_list:1")],
        [InlineKeyboardButton("👥 Помощники", callback_data="helpers_menu")],
        [InlineKeyboardButton("⛔ Чёрный список", callback_data="bl_menu")],
        [InlineKeyboardButton("🎯 Winback", callback_data="winback_settings")],
        [InlineKeyboardButton("🖥 Серверы и 3x-UI", callback_data="xui_settings")],
        [InlineKeyboardButton(mnt_label, callback_data="mnt_menu")],
        [InlineKeyboardButton("🔄 Обновиться с GitHub", callback_data="git_update")],
        [InlineKeyboardButton("📢 Управление каналом", callback_data="channel_menu")],
        [
            InlineKeyboardButton("📄 Документы", callback_data="documents_menu"),
            InlineKeyboardButton("🧾 Лог-канал", callback_data="log_channel_settings"),
        ],
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

def support_keyboard(page: int, total_pages: int, has_files: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"support_page:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"support_page:{page + 1}"))
        rows.append(nav)
    if has_files:
        rows.append([InlineKeyboardButton("📎 Показать файлы", callback_data="support_files")])
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


def ticket_view_keyboard(user_id: int, page: int, total_pages: int, has_files: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"ticket_view:{user_id}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"ticket_view:{user_id}:{page + 1}"))
        rows.append(nav)
    if has_files:
        rows.append([InlineKeyboardButton("📎 Файлы", callback_data=f"ticket_files:{user_id}")])
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
        [InlineKeyboardButton("🩺 Здоровье серверов", callback_data="healthcheck")],
        [InlineKeyboardButton("🖧 Узлы", callback_data="nodes_menu")],
        [InlineKeyboardButton("🔌 Тест соединения", callback_data="test_xui")],
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
