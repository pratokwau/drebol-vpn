from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import load_config


# ── Главное меню ──────────────────────────────────────────────────────────────

def main_keyboard(is_admin: bool, has_sub: bool = False, paid_sub_status: str = "",
                  is_helper: bool = False) -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_url = cfg.get("channel_url")

    news_btn = (
        InlineKeyboardButton("📣 Новости", url=channel_url)
        if channel_url
        else InlineKeyboardButton("📣 Новости", callback_data="news_no_channel")
    )

    # выключенные в техработах функции прячем от пользователей; админ видит всё
    import core.maintenance as mnt

    def on(key: str) -> bool:
        return is_admin or mnt.feature_enabled(key)

    rows = []
    # Эмодзи подобраны в одну «семью»: ключи и замок — про доступ, карта и люди —
    # про действия, дальше служебное. Разнобой в меню сильнее всего бросается в глаза.
    rows.append([InlineKeyboardButton(
        "🔐 Моя подписка" if paid_sub_status else "🎁 Получить подписку",
        callback_data="my_paid_sub")])
    # вторым рядом — то, за чем приходят чаще всего; парой, чтобы меню было короче
    pair = []
    # продлить можно в любой момент — остаток не сгорает
    if paid_sub_status and on("payments"):
        pair.append(InlineKeyboardButton("💳 Продлить", callback_data="renew_sub"))
    if paid_sub_status and on("referral"):
        pair.append(InlineKeyboardButton("🎁 Пригласить друга", callback_data="referral"))
    if pair:
        rows.append(pair)
    if has_sub:
        rows.append([InlineKeyboardButton("🪪 Админская подписка", callback_data="my_sub")])
    info_btn = InlineKeyboardButton("ℹ️ Инфо", callback_data="info")
    if on("support"):
        # кнопка открывает экран со ссылкой на отдельного бота поддержки
        from handlers.support import support_button
        rows.append([support_button(text="🛟 Поддержка", force=is_admin), info_btn])
    else:
        rows.append([info_btn])
    rows.append([news_btn])
    if is_admin:
        rows.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel")])
    elif is_helper:
        rows.append([InlineKeyboardButton("🛡 Панель поддержки", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


# ── Админка ───────────────────────────────────────────────────────────────────

def admin_keyboard() -> InlineKeyboardMarkup:
    # включённые техработы должны бросаться в глаза, чтобы про них не забыли
    import core.maintenance as mnt
    mnt_label = "🔴 Техработы ВКЛЮЧЕНЫ" if mnt.is_maintenance() else "🛠 Техработы и функции"

    def b(text, cb):
        return InlineKeyboardButton(text, callback_data=cb)

    # время сводки — прямо в подписи кнопки, чтобы было видно настройку
    sync_time = (load_config().get("morning_sync") or {}).get("time", "09:00")

    # Кнопки сгруппированы по смыслу и стоят парами — так вся админка
    # помещается на один экран телефона без прокрутки
    return InlineKeyboardMarkup([
        # сводка и деньги
        [b("📊 Статистика", "dashboard"), b("💰 Финансы", "pay_provider_menu")],
        # люди и подписки
        [b("🔍 Найти юзера", "find_user"), b("📜 Логи", "ctl_menu")],
        [b("💳 Платные подписки", "paid_subs"), b("📋 Админские", "admin_subs")],
        # общение
        [b("📣 Рассылка", "broadcast"), b("👥 Помощники", "helpers_menu")],
        [b("📢 Канал", "channel_menu")],
        # удержание и защита
        [b("🎯 Возврат ушедших", "winback_settings"), b("⏰ Напоминания", "remind_settings")],
        [b("⛔ Чёрный список", "bl_menu"), b("🕵 Повторные триалы", "fraud_menu")],
        # инфраструктура
        [b("🖥 Панель и узлы", "rw_menu"), b("🌐 Веб-доступ", "web_menu")],
        [b("🌐 Проверка операторов", "netcheck_menu")],
        [b("💾 Бэкап и перенос", "backup_menu"), b("📄 Документы", "documents_menu")],
        [b("🛟 Поддержка и логи", "support_group_settings")],
        [b(mnt_label, "mnt_menu")],
        [b("🔄 Обновиться с GitHub", "git_update")],
        [b(f"⏰ Синхронизация · {sync_time}", "morning_menu")],
        [b("◀️ Назад", "back_start")],
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
    refund_label = "↩️ Изменить политику возврата" if cfg.get("refund_url") else "↩️ Политика возврата"
    rules_label = "📏 Изменить правила использования" if cfg.get("rules_url") else "📏 Правила использования"
    consent_label = "🔏 Изменить согласие на обработку" if cfg.get("consent_url") else "🔏 Согласие на обработку данных"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(privacy_label, callback_data="set_privacy_url")],
        [InlineKeyboardButton(terms_label, callback_data="set_terms_url")],
        [InlineKeyboardButton(refund_label, callback_data="set_refund_url")],
        [InlineKeyboardButton(rules_label, callback_data="set_rules_url")],
        [InlineKeyboardButton(consent_label, callback_data="set_consent_url")],
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
