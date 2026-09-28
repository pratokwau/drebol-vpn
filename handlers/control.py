"""Раздел «Контроль»: что происходит в боте и на VPN.

• лента — каждое нажатие, команда и вид сообщения в боте;
• важные события — регистрации, триалы, оплаты, возвраты, отключения;
• история подписок — то, что делали с подписками: раньше она жила отдельным
  разделом в «Платных подписках», теперь это вкладка здесь;
• аудит админки — кто из своих что нажимал, с отдельной вкладкой помощников;
• кто сейчас онлайн на VPN и кто сколько потратил трафика;
• ежедневная сводка админу.

VPN-данные здесь только живые и суммарные: онлайн и счётчики трафика берутся
у панели в момент просмотра. История подключений, IP и посещённых сайтов не
собирается — это противоречило бы обещанию «без логов».
"""

from __future__ import annotations

import html as _html
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config

PER_PAGE = 30
# Телеграм режет сообщение на 4096 символах — держим запас под заголовок и кнопки
TEXT_BUDGET = 3500

# Подписи действий по началу callback-данных
CB_LABELS = {
    # пользователь
    "back_start": "🏠 Главное меню",
    "check_sub": "📢 Проверка подписки на канал",
    "my_paid_sub": "👤 Моя подписка",
    "renew_sub": "💳 Открыл продление",
    "pay_invoice": "🧾 Создал счёт",
    "tariff_pick": "💳 Смотрит тариф",
    "enter_promo": "🎟 Ввод промокода",
    "remove_promo": "🎟 Убрал промокод",
    "qr_code": "📱 QR-код",
    "app_add": "📲 Добавляет в приложение",
    "copy_sub": "📋 Скопировал ссылку",
    "reissue_key": "🔁 Перевыпуск ключа",
    "reissue_do": "🔁 Подтвердил перевыпуск",
    "remind_settings": "⏰ Напоминания",
    "fraud_menu": "🕵 Повторные триалы",
    "site_menu": "🌐 Сайт",
    "backup_menu": "💾 Бэкап",
    "rw_menu": "🆕 Remnawave",
    "rw_test": "🔌 Проверка Remnawave",
    "rw_notify_go": "📨 Рассылка новых ссылок",
    "backup_export": "📤 Выгрузка базы",
    "backup_apply": "♻️ Восстановление из бэкапа",
    "site_logo": "🖼 Логотип сайта",
    "site_deploy": "🚀 Разворачивает сайт",
    "site_check": "🩺 Проверка сайта",
    "site_auto": "⚡ Автообновление сайта",
    "site_delete": "🗑 Удаляет сайт",
    "fraud_scan": "🕵 Ручная проверка",
    "fraud_ok": "🙈 Пара не фрод",
    "support_open": "💬 Открыл поддержку",
    "support_settings": "💬 Настройки поддержки",
    "support_mode": "💬 Сменил режим поддержки",
    "support_contact": "👤 Аккаунт поддержки",
    "support_topic": "💬 Тема обращения",
    "support_write": "✍️ Пишет в поддержку",
    "support_close": "✅ Закрыл свой вопрос",
    "ticket_close": "✅ Закрыл тикет",
    "ticket_send": "⚡ Ответил шаблоном",
    "quick_menu": "⚡ Шаблоны ответов",
    "support_page": "💬 Листал поддержку",
    "support_files": "📎 Файлы поддержки",
    "referral": "👥 Рефералы",
    "info": "ℹ️ Инфо",
    "prices": "💰 Цены",
    "how_to": "❓ Как подключиться",
    "about": "📕 О сервисе",
    "my_sub": "📋 Админская подписка",
    "news_no_channel": "📰 Новости",
    # админ — действия, которые что-то меняют
    "paid_approve": "✅ Одобрил триал",
    "paid_reject": "❌ Отклонил триал",
    "refund_do": "💸 Возврат",
    # бан, удаления, вкл/выкл подписок и техработ идут через «Точно?» —
    # их подписи в handlers/confirm.py (CONFIRM_TITLES)
    "unban_user": "✅ Разбан",
    "bcast_send": "📣 Отправил рассылку",
    "paid_bulk_apply": "📦 Массовое изменение срока",
    "paid_bulk_limits_apply": "📱 Массовая смена лимита устройств",
    "my_devices": "📱 Свои устройства",
    "dev_buy_menu": "➕ Открыл докуп устройств",
    "dev_buy": "💳 Счёт на устройства",
    "dev_del": "🗑 Отключил своё устройство",
    "paid_devices": "📱 Смотрел устройства подписки",
    "paid_ips": "🌐 Смотрел IP подписки",
    "paid_hwid_del": "🗑 Убрал устройство",
    "paid_hwid_clear": "🧹 Очистка устройств",
    "fraud_stop": "🚫 Закрыл триал за повтор",
    "helper_perm": "👥 Сменил права помощника",
    "sub_hwid_clear": "🧹 Очистка устройств (админская)",
    "sub_reissue": "🔁 Перевыпуск ключа (админская)",
    "subs_names_sync": "🔄 Сверил ники с панелью",
    "sub_hwid_del": "📱 Отключил устройство (админская)",
    "bl_add_apply": "⛔ Заблокировал (ЧС или бан)",
    "bl_sync": "🔄 Обновил общий ЧС",
    "bl_bans": "🚫 Смотрел баны",
    "promo_give_do": "🎁 Выдал промокод",
    "promo_seg_do": "📤 Раздал промокоды",
    "promo_income": "📊 Что принесли промокоды",
    "mnt_feature": "⏸ Выключатель функции",
    "tariff_toggle": "💰 Тариф вкл/выкл",
    "tariff_del_ok": "🗑 Удалил тариф",
    "promo_toggle": "🎟 Промокод вкл/выкл",
    "helper_add": "👥 Добавление помощника",
    "ctl_ch_toggle": "🆘 Помощь с подключением вкл/выкл",
    "ctl_menu": "🛰 Открыл контроль",
    "act_feed": "📜 Смотрел ленту",
    "ctl_online": "🔌 Смотрел, кто онлайн",
    "ctl_traffic": "📊 Смотрел трафик",
    "ctl_digest_now": "📤 Сводка вручную",
    "ctl_digest_toggle": "📨 Сводка вкл/выкл",
    "ctl_digest_hour": "🕘 Время сводки",
    "dashboard": "📊 Смотрел статистику",
    "paid_subs": "💳 Список подписок",
    "paid_sub_view": "💳 Открыл подписку",
    "paid_sub_extend": "➕ Добавил срок",
    "paid_sub_reduce": "➖ Убавил срок",
    "paid_sub_settings": "⚙️ Настройки подписки",
    "paid_sub_edit_expire": "📅 Правил дату окончания",
    "paid_sub_edit_hwid": "🖥 Правил лимит устройств",
    "paid_sub_edit_traffic": "📶 Правил трафик",
    "paid_sub_edit_trial": "🆓 Правил пробный период",
    "paid_create_sub": "➕ Создание подписки",
    "paid_create_type": "➕ Выбрал тариф для выдачи",
    "paid_bulk_menu": "⚡ Массовые действия",
    "paid_sub_presets": "⚙️ Настройки подписок",
    "paid_preset_trial": "🆓 Правил пробный период",
    "paid_preset_hwid": "🖥 Правил лимит устройств",
    "paid_preset_traffic": "📶 Правил общий трафик",
    "paid_device_price": "📱 Цена устройства",
    "paid_device_max": "📱 Максимум докупа",
    "toggle_auto_trial": "⚡ Авто-триал вкл/выкл",
    "tariffs_menu": "🏷 Тарифы",
    "tariff_add": "🏷 Добавление тарифа",
    "tariff_view": "🏷 Открыл тариф",
    "pay_provider_menu": "💳 Платёжка",
    "payments": "💰 Оплаты",
    "payment_view": "💰 Открыл платёж",
    "refund_menu": "💸 Возвраты",
    "promo_menu": "🎟 Промокоды",
    "promo_view": "🎟 Открыл промокод",
    "promo_create": "➕ Создание промокода",
    "promo_batch": "🎬 Партия промокодов",
    "promo_give": "🎁 Выдача промокода",
    "promo_seg": "📤 Раздача сегменту",
    "promo_clean": "🧹 Чистка промокодов",
    "promo_uses": "👥 Кто применял промокод",
    "referral_settings": "👥 Рефералы",
    "bl_menu": "⛔ Чёрный список",
    "bl_view": "⛔ Открыл карточку блокировок",
    "bl_new": "⛔ Начал блокировку",
    "bl_ban": "🚫 Начал бан",
    "bl_unban": "✅ Разбан",
    "bl_reason": "📝 Выбрал причину блокировки",
    "bl_term": "⏳ Выбрал срок блокировки",
    "bl_check": "🔍 Проверка в ЧС",
    "bl_remote_toggle": "🌐 Общий ЧС вкл/выкл",
    "fraud_list": "🕵 Список находок",
    "fraud_pair": "🕵 Открыл находку",
    "fraud_ip_toggle": "🌐 Адрес как улика вкл/выкл",
    "winback_settings": "🎯 Winback",
    "winback_test": "📨 Пример письма winback",
    "toggle_winback": "🎯 Winback вкл/выкл",
    "toggle_winback_paid": "👤 Winback: кому писать",
    "set_winback_days": "1️⃣ Срок первой волны",
    "set_winback_percent": "1️⃣ Скидка первой волны",
    "set_winback_days2": "2️⃣ Срок второй волны",
    "set_winback_percent2": "2️⃣ Скидка второй волны",
    "set_winback_life": "⏳ Срок промокода winback",
    "remind_test": "📨 Пример напоминания",
    "toggle_remind": "⏰ Напоминания вкл/выкл",
    "toggle_remind_trials": "🆓 Напоминания пробным",
    "set_remind_first": "1️⃣ Первое напоминание",
    "set_remind_second": "2️⃣ Второе напоминание",
    "set_remind_third": "3️⃣ Третье напоминание",
    "set_remind_quiet": "🌙 Тихие часы",
    "helpers_menu": "👥 Помощники",
    "helper_card": "👥 Открыл помощника",
    "helper_panel": "🧰 Панель помощника",
    "subs_menu": "🛠 Админские подписки",
    "sub_view": "🛠 Открыл админскую подписку",
    "sub_create": "➕ Создание админской подписки",
    "broadcast": "📣 Рассылка",
    "log_channel": "🧾 Лог-канал",
    "documents": "📕 Документы",
    "mnt_menu": "⏸ Техработы",
    # работа в поддержке — в аудите видно, кто из помощников что открывал
    "admin_panel": "⚙️ Открыл панель",
    "ticket_list": "🎫 Тикеты",
    "ticket_view": "🎫 Открыл тикет",
    "ticket_reply": "✏️ Начал ответ в тикет",
    "find_user": "🔍 Поиск юзера",
    "user_profile": "👤 Открыл профиль",
    "user_activity": "📜 Действия юзера",
    "dm_user": "📌 Начал сообщение юзеру",
}

EVENT_LABELS = {
    "registered": "🆕 Регистрация",
    "period_ended": "⏳ Кончился период",
    "expired": "🔴 Подписка отключена",
    "trial_approved": "🆓 Выдан триал",
    "trial_rejected": "❌ Отклонён триал",
    "sub_created": "✨ Создана подписка",
    "payment_confirmed": "💰 Оплата",
    "payment_rejected": "❌ Отклонена оплата",
    "payment_refunded": "↩️ Возврат",
    "promo_used": "🎟 Применён промокод",
    "referral_bonus": "🎁 Реферальный бонус",
    "referral_invited_bonus": "🎁 Бонус приглашённого",
    "sub_expired": "📦 Срок подписки кончился",
    "sub_extended": "➕ Продлён срок",
    "sub_reduced": "➖ Убавлен срок",
    "settings_changed": "⚙️ Изменены условия",
    "user_muted": "🔇 Заглушён",
    "connect_help": "🆘 Подсказка: не подключился",
    "blacklisted": "⛔ Внесён в ЧС",
    "unblacklisted": "✅ Убран из ЧС",
    "promo_issued": "🎁 Выдан промокод",
    "promo_days": "🎁 Начислены дни по промокоду",
}

STATE_LABELS = {
    "awaiting_support_msg": "✉️ Написал в поддержку",
    "awaiting_promo_code": "🎟 Ввёл промокод",
    "awaiting_admin_reply": "✉️ Ответил в тикет",
    "awaiting_dm_user": "📌 Написал юзеру",
    "awaiting_find_user": "🔍 Искал юзера",
    "awaiting_support_contact": "👤 Ввёл аккаунт поддержки",
    "awaiting_helper_id": "👥 Ввёл помощника",
    "awaiting_bl_add": "⛔ Ввод для ЧС",
    "awaiting_bl_reason": "⛔ Причина для ЧС",
    "awaiting_bl_check": "🔍 Проверка в ЧС",
    "awaiting_promo_give_user": "🎁 Кому выдать промокод",
    "awaiting_promo_custom": "🎁 Своя величина промокода",
}

FEED_TITLES = {
    "all": "📜 Лента действий",
    "important": "⭐ Важные события",
    "admin": "⚙️ Аудит админки",
    "helpers": "👥 Помощники",
    "subs": "💳 История подписок",
}

# Подписи записей истории подписок (они же были в «Платных подписках»)
HIST_LABELS = {
    "trial_approved": "✅ Пробный одобрен",
    "trial_rejected": "❌ Пробный отклонён",
    "payment_confirmed": "✅ Оплата подтверждена",
    "payment_rejected": "❌ Оплата отклонена",
    "payment_refunded": "↩️ Возврат платежа",
    "sub_created": "🆕 Подписка создана",
    "sub_extended": "➕ Срок добавлен",
    "sub_reduced": "➖ Срок убавлен",
    "sub_frozen": "🧊 Заморожена",
    "sub_enabled": "▶️ Включена",
    "sub_disabled": "⏸ Отключена",
    "sub_deleted": "🗑 Удалена",
    "bulk_extended": "⚡➕ Массово: срок добавлен",
    "bulk_reduced": "⚡➖ Массово: срок убавлен",
    "settings_changed": "⚙️ Изменены настройки",
    "referral_bonus": "🎁 Реферальный бонус",
    "referral_invited_bonus": "🎁 Бонус приглашённого",
    "promo_used": "🎟 Промокод применён",
    "promo_issued": "🎁 Выдан промокод",
    "promo_days": "🎁 Начислены дни по промокоду",
    "blacklisted": "⛔ Внесён в ЧС",
    "unblacklisted": "✅ Убран из ЧС",
    "devices_bought": "📱 Докупил устройства",
    "key_reissued": "🔁 Перевыпущен ключ",
}


def _esc(value) -> str:
    return _html.escape(str(value)) if value is not None else ""


def _who(first_name, username, tg_id) -> str:
    name = _esc(first_name or tg_id)
    return f"{name} (@{_esc(username)})" if username else name


def _short_ts(ts: str) -> str:
    """ts уже в местном времени: запросы переводят его из UTC."""
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").strftime("%d.%m %H:%M")
    except Exception:
        return (ts or "")[:16]


def _fmt_bytes(value) -> str:
    b = float(value or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if b < 1024:
            return f"{int(b)} {unit}" if unit == "Б" else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.2f} ТБ"


def _arg_tail(rest: str) -> str:
    """Хвост кнопки: к чему она относилась — номер подписки, ID человека, код."""
    parts = [p for p in rest.split(":")[1:] if p]
    # последняя «1» почти всегда номер страницы, а не смысл действия
    if len(parts) > 1 and parts[-1] == "1":
        parts = parts[:-1]
    if not parts:
        return ""
    return " · <code>" + _esc(":".join(parts))[:40] + "</code>"


def action_label(action: str, details: str | None) -> str:
    kind, _, rest = (action or "").partition(":")
    if kind == "cb":
        # опасные кнопки: нажатие только спрашивает «Точно?», действие — ok:…
        from handlers.confirm import OK_PREFIX, confirm_title
        if rest.startswith(OK_PREFIX):
            done = rest[len(OK_PREFIX):]
            return f"✅ {confirm_title(done) or _esc(done)}" + _arg_tail(done)
        title = confirm_title(rest)
        if title:
            return f"❔ {title}?" + _arg_tail(rest)
        label = CB_LABELS.get(rest.split(":")[0])
        if label:
            return label + _arg_tail(rest)
        return f"⚙️ {_esc(rest)}"
    if kind == "cmd":
        return f"▶️ /{_esc(rest)}" + (f" <code>{_esc(details)}</code>" if details else "")
    if kind == "msg":
        if details == "awaiting_support_msg" and rest in ("photo", "document"):
            return "📎 Файл в поддержку"
        if details in STATE_LABELS:
            return STATE_LABELS[details]
        if details:
            return f"✏️ Ввод ({_esc(details.replace('awaiting_', ''))})"
        return {"photo": "🖼 Фото", "document": "📎 Файл"}.get(rest, "✉️ Сообщение")
    if kind == "ev":
        return EVENT_LABELS.get(rest, f"• {_esc(rest)}")
    return _esc(action)


# ── Запись ───────────────────────────────────────────────────────────────────

async def log_update(update, context):
    """Журнал: каждое действие в боте, раньше всех остальных обработчиков.

    Хранится только тип действия — какая кнопка, команда или вид сообщения.
    Текст сообщений не сохраняется: обращения в поддержку и так лежат в тикетах.
    """
    from staff import is_staff
    from database import log_activity
    try:
        user = update.effective_user
        if not user:
            return
        action = details = None
        if update.callback_query:
            data = update.callback_query.data or ""
            if data == "noop":
                return
            action = f"cb:{data}"
        elif update.message:
            m = update.message
            if m.text and m.text.startswith("/"):
                parts = m.text.split()
                action = "cmd:" + parts[0][1:].split("@")[0]
                details = " ".join(parts[1:])[:100] or None
            else:
                kind = ("text" if m.text else "photo" if m.photo
                        else "document" if m.document else "other")
                action = f"msg:{kind}"
                details = (context.user_data or {}).get("state")
        if action:
            await log_activity(user.id, action, details, is_staff(user.id))
    except Exception:
        # журнал не должен мешать обработке
        pass


# ── Экраны ───────────────────────────────────────────────────────────────────

def _back(cb: str, label: str = "◀️ К контролю") -> list:
    return [InlineKeyboardButton(label, callback_data=cb)]


async def handle_control_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    if context:
        context.user_data.pop("state", None)
    from database import activity_summary, control_today
    from panel import get_online_emails

    s = await activity_summary()
    t = await control_today()
    online = await get_online_emails()
    cfg = load_config()

    now = [f"🟢 Заходили в бот: <b>{s['active_today']}</b> сегодня  ·  "
           f"<b>{s['active_week']}</b> за 7 дней",
           f"🖱 Действий сегодня: <b>{s['events_today']}</b>"]
    if online.get("ok"):
        now.append(f"🔌 Онлайн на VPN сейчас: <b>{len(online['emails'])}</b>")
    else:
        now.append("🔌 Онлайн на VPN: <i>панель не ответила</i>")
    lines = ["🛰 <b>Контроль</b>", "", "<blockquote>" + "\n".join(now) + "</blockquote>"]

    money = [f"💰 Оплат: <b>{t['pays']}</b> на <b>{t['amount']} ₽</b>",
             f"🆕 Новых людей: <b>{t['new_users']}</b>  ·  "
             f"🆓 выдано триалов: <b>{t['trials']}</b>",
             f"🔴 Закончились подписки: <b>{t['expired']}</b>"]
    extra = []
    if t["refunds"]:
        extra.append(f"↩️ возвратов: <b>{t['refunds']}</b>")
    if t["failed"]:
        extra.append(f"❌ незакрытых счётов: <b>{t['failed']}</b>")
    if t["tickets"]:
        extra.append(f"🎫 обращений: <b>{t['tickets']}</b>")
    if t["blocked"]:
        extra.append(f"⛔ блокировок: <b>{t['blocked']}</b>")
    if extra:
        money.append("  ·  ".join(extra))
    lines.append("\n📆 <b>Сегодня</b>\n<blockquote>" + "\n".join(money) + "</blockquote>")

    if s["top_today"]:
        lines.append("\n🔥 <b>Чаще всего сегодня</b>")
        lines.append("<blockquote>" + "\n".join(
            f"{action_label(a, None)} — {c}" for a, c in s["top_today"]) + "</blockquote>")

    if s["recent_events"]:
        lines.append("\n🕐 <b>Последние события</b>")
        ev = [f"<code>{_short_ts(ts)}</code> {_who(fn, un, tg_id)} · {action_label(action, details)}"
              for tg_id, action, details, ts, fn, un in s["recent_events"]]
        lines.append("<blockquote expandable>" + "\n".join(ev) + "</blockquote>")

    digest_on = cfg.get("digest_enabled", True)
    hour = int(cfg.get("digest_hour", 9))
    ch_label = (f"через {int(cfg.get('connect_help_hours', 3))} ч"
                if cfg.get("connect_help_enabled", True) else "выключена")
    lines.append("\n⚙️ <b>Автоматика</b>")
    lines.append("<blockquote>"
                 f"📨 Сводка в личку: <b>{f'каждый день в {hour}:00' if digest_on else 'выключена'}</b>\n"
                 f"🆘 Помощь с подключением: <b>{ch_label}</b>\n"
                 f"🗄 Журнал хранится <b>{int(cfg.get('activity_retention_days', 90))}</b> дней"
                 "</blockquote>")

    kb = [
        [InlineKeyboardButton("📜 Лента действий", callback_data="act_feed:all:1"),
         InlineKeyboardButton("⭐ Важное", callback_data="act_feed:important:1")],
        [InlineKeyboardButton("💳 История подписок", callback_data="act_feed:subs:1")],
        [InlineKeyboardButton("⚙️ Аудит админки", callback_data="act_feed:admin:1"),
         InlineKeyboardButton("👥 Помощники", callback_data="act_feed:helpers:1")],
        [
            InlineKeyboardButton("🔌 Кто онлайн", callback_data="ctl_online"),
            InlineKeyboardButton("📊 Трафик", callback_data="ctl_traffic"),
        ],
        [InlineKeyboardButton("🔍 Найти человека", callback_data="find_user"),
         InlineKeyboardButton("🆘 Помощь с подключением", callback_data="ctl_ch_menu")],
        [InlineKeyboardButton(
            "📨 Сводка · вкл ✅" if digest_on else "📨 Сводка · выкл",
            callback_data="ctl_digest_toggle",
        )],
        [
            InlineKeyboardButton("🕘 Время сводки", callback_data="ctl_digest_hour"),
            InlineKeyboardButton("📤 Сводка сейчас", callback_data="ctl_digest_now"),
        ],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


def _nav(base_cb: str, page: int, total_pages: int) -> list:
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"{base_cb}:{page - 1}"))
    if total_pages > 1:
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"{base_cb}:{page + 1}"))
    return nav


def _fit(rows: list, budget: int = TEXT_BUDGET) -> list:
    """Обрезает список строк под лимит телеграма, сохраняя порядок."""
    out, used = [], 0
    for r in rows:
        if used + len(r) + 1 > budget:
            out.append("<i>…остальное не влезло в сообщение — листай страницы</i>")
            break
        out.append(r)
        used += len(r) + 1
    return out


def hist_label(action: str) -> str:
    return HIST_LABELS.get(action, f"• {_esc(action)}")


async def _subs_feed(page: int, tg_id: int | None = None):
    """История подписок: те же записи, что раньше жили в «Платных подписках»."""
    from paidsub.storage import get_user_history, list_history
    if tg_id:
        rows, pages = await get_user_history(tg_id, page, PER_PAGE)
        rows = [(r[0], r[1], r[2], r[3], r[4], None, None) for r in rows]
    else:
        rows, pages = await list_history(page, PER_PAGE)
    lines = []
    for entry_id, uid, action, details, ts, fn, un in rows:
        who = f"{_who(fn, un, uid)} · " if not tg_id else ""
        head = (details or "").splitlines()[0] if details else ""
        tail = f" — {_esc(head)}" if head else ""
        lines.append(f"<code>{_short_ts(ts)}</code> {who}{hist_label(action)}{tail}"
                     f" /h{entry_id}")
    return lines, pages


async def handle_activity_feed(query, scope: str = "all", page: int = 1):
    from config import ADMIN_ID
    from database import list_activity
    if scope not in FEED_TITLES:
        scope = "all"

    if scope == "subs":
        lines, total_pages = await _subs_feed(page)
        page = min(max(1, page), total_pages)
        head = [f"<b>{FEED_TITLES[scope]}</b> — стр. {page}/{total_pages}",
                "<i>у каждой записи свой номер: /h123 — открыть подробности</i>", ""]
    else:
        rows, total_pages = await list_activity(scope, page, PER_PAGE)
        page = min(max(1, page), total_pages)
        head = [f"<b>{FEED_TITLES[scope]}</b> — стр. {page}/{total_pages}", ""]
        lines = []
        for tg_id, action, details, ts, fn, un in rows:
            # в аудите себя не подписываем, а помощника — да
            who = "" if scope == "admin" and tg_id == ADMIN_ID else f"{_who(fn, un, tg_id)} · "
            lines.append(f"<code>{_short_ts(ts)}</code> {who}{action_label(action, details)}")
    if not lines:
        lines = ["Пока пусто."]

    kb = []
    nav = _nav(f"act_feed:{scope}", page, total_pages)
    if nav:
        kb.append(nav)
    keys = list(FEED_TITLES)
    for chunk in (keys[:3], keys[3:]):
        if chunk:
            kb.append([InlineKeyboardButton(("• " if key == scope else "")
                                            + FEED_TITLES[key].split(" ", 1)[1],
                                            callback_data=f"act_feed:{key}:1")
                       for key in chunk])
    kb.append(_back("ctl_menu"))
    await query.edit_message_text(
        "\n".join(head + _fit(lines)), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


async def handle_hist_entry(target, entry_id: int, edit: bool = True):
    """Подробности записи истории подписок."""
    from database import get_user_info
    from paidsub.storage import get_history_entry
    entry = await get_history_entry(entry_id)
    if not entry:
        if edit:
            await target.answer("Запись не найдена", show_alert=True)
        else:
            await target.reply_text("📋 Такой записи в истории нет.")
        return
    _id, tg_id, action, details, created_at = entry
    u = await get_user_info(tg_id) if tg_id else None
    kb = []
    if tg_id:
        kb.append([InlineKeyboardButton("👤 Профиль", callback_data=f"user_profile:{tg_id}"),
                   InlineKeyboardButton("📜 Его действия", callback_data=f"user_activity:{tg_id}:1")])
    kb.append(_back("act_feed:subs:1", "◀️ К истории"))
    text = (f"📋 <b>{hist_label(action)}</b>\n\n"
            f"<blockquote>👤 {_who(u[1] if u else None, u[2] if u else None, tg_id)}\n"
            f"🕐 {_short_ts(created_at) if created_at else '?'}</blockquote>"
            + (f"\n\n<blockquote expandable>{_esc(details)}</blockquote>" if details else ""))
    kwargs = dict(parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
                  disable_web_page_preview=True)
    if edit:
        await target.edit_message_text(text, **kwargs)
    else:
        await target.reply_text(text, **kwargs)


async def hist_command(update, context):
    """/h123 из ленты истории — подробности записи одним нажатием."""
    from staff import helper_can, is_helper
    from config import ADMIN_ID
    uid = update.effective_user.id
    if uid != ADMIN_ID and not (is_helper(uid) and helper_can("ctl_hist:0", uid)):
        return
    digits = "".join(c for c in (update.message.text or "") if c.isdigit())
    if digits:
        await handle_hist_entry(update.message, int(digits), edit=False)


USER_TABS = {"all": "📜 Всё", "important": "⭐ Важное", "subs": "💳 Подписка"}


async def handle_user_activity(query, tg_id: int, page: int = 1, scope: str = "all"):
    """Что человек делал в боте — то же, что в «Контроле», но про одного."""
    from database import get_user_info, list_activity
    if scope not in USER_TABS:
        scope = "all"
    u = await get_user_info(tg_id)
    name = _who(u[1] if u else None, u[2] if u else None, tg_id)

    if scope == "subs":
        lines, total_pages = await _subs_feed(page, tg_id)
    else:
        key = f"user_important:{tg_id}" if scope == "important" else f"user:{tg_id}"
        rows, total_pages = await list_activity(key, page, PER_PAGE)
        lines = [f"<code>{_short_ts(ts)}</code> {action_label(action, details)}"
                 for _tg, action, details, ts, _fn, _un in rows]
    page = min(max(1, page), total_pages)
    head = [f"📜 <b>{USER_TABS[scope]}: {name}</b>",
            f"🆔 <code>{tg_id}</code> · стр. {page}/{total_pages}", ""]
    if not lines:
        lines = ["Записей пока нет."]

    kb = [[InlineKeyboardButton(("• " if k == scope else "") + label,
                                callback_data=f"user_feed:{tg_id}:{k}:1")
           for k, label in USER_TABS.items()]]
    nav = _nav(f"user_feed:{tg_id}:{scope}", page, total_pages)
    if nav:
        kb.insert(0, nav)
    kb.append([InlineKeyboardButton("🛰 Вся лента", callback_data="act_feed:all:1"),
               InlineKeyboardButton("👤 Профиль", callback_data=f"user_profile:{tg_id}")])
    kb.append(_back("ctl_menu"))
    await query.edit_message_text(
        "\n".join(head + _fit(lines)), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


async def handle_online(query):
    from panel import get_online_emails
    from database import users_by_emails
    await query.edit_message_text("🔌 Спрашиваю панель...")
    r = await get_online_emails()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="ctl_online")],
        _back("ctl_menu"),
    ])
    if not r.get("ok"):
        await query.edit_message_text(
            f"🔌 <b>Кто онлайн</b>\n\n❌ Панель не ответила:\n<code>{_esc(r.get('error'))}</code>",
            parse_mode="HTML", reply_markup=kb)
        return

    emails = r["emails"]
    known = await users_by_emails(emails)
    lines = [f"🔌 <b>Онлайн на VPN: {len(emails)}</b>\n",
             "<i>Живые данные панели, в журнал не сохраняются.</i>\n"]
    if not emails:
        lines.append("Сейчас никто не подключён.")
    for email in emails[:60]:
        if email in known:
            tg_id, fn, un = known[email]
            lines.append(f"🟢 {_who(fn, un, tg_id)} · <code>{tg_id}</code>")
        else:
            lines.append(f"🟢 <code>{_esc(email)}</code>")
    if len(emails) > 60:
        lines.append(f"…и ещё {len(emails) - 60}")
    # имена людей длинные: держим сообщение в рамках телеграма
    await query.edit_message_text("\n".join(_fit(lines, TEXT_BUDGET)), parse_mode="HTML",
                                  reply_markup=kb)


async def handle_traffic(query):
    from panel import get_traffic_snapshot
    from database import users_by_emails
    await query.edit_message_text("📊 Считаю трафик...")
    r = await get_traffic_snapshot()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="ctl_traffic")],
        _back("ctl_menu"),
    ])
    if not r.get("ok"):
        await query.edit_message_text(
            f"📊 <b>Трафик</b>\n\n❌ Панель не ответила:\n<code>{_esc(r.get('error'))}</code>",
            parse_mode="HTML", reply_markup=kb)
        return

    clients = r["clients"]
    total = sum(up + down for up, down in clients.values())
    top = sorted(clients.items(), key=lambda kv: kv[1][0] + kv[1][1], reverse=True)[:10]
    known = await users_by_emails([e for e, _ in top])

    lines = [
        "📊 <b>Трафик</b>\n",
        f"Всего по всем клиентам: <b>{_fmt_bytes(total)}</b> · клиентов: <b>{len(clients)}</b>",
        "<i>Счётчики панели с последнего сброса.</i>\n",
        "<b>Топ-10:</b>",
    ]
    for i, (email, (up, down)) in enumerate(top, 1):
        who = _who(*known[email][1:], known[email][0]) if email in known else f"<code>{_esc(email)}</code>"
        lines.append(f"{i}. {who} — <b>{_fmt_bytes(up + down)}</b> (⬆{_fmt_bytes(up)} ⬇{_fmt_bytes(down)})")
    await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)


# ── Ежедневная сводка ────────────────────────────────────────────────────────

async def build_digest(day_offset: int = 1) -> str:
    from database import digest_stats
    from panel import get_online_emails
    d = await digest_stats(day_offset)
    online = await get_online_emails()

    head = "за сегодня (на текущий момент)" if day_offset == 0 else f"за {d['label']}"
    lines = [
        f"📊 <b>Сводка {head}</b>\n",
        f"🆕 Новых пользователей: <b>{d['new_users']}</b>",
        f"🟢 Заходили в бот: <b>{d['active']}</b> · действий: <b>{d['actions']}</b>",
        f"🆓 Выдано триалов: <b>{d['trials']}</b>",
        f"💰 Оплат: <b>{d['paid_cnt']}</b> на <b>{d['paid_sum']} ₽</b>",
    ]
    if d["ref_cnt"]:
        # Оплаты считаются по дню оплаты, возвраты — по дню возврата,
        # поэтому без итога цифра расходилась бы с разделом «Оплаты»
        lines.append(f"↩️ Возвратов: <b>{d['ref_cnt']}</b> на <b>{d['ref_sum']} ₽</b>")
        lines.append(f"🧾 Итого за день: <b>{(d['paid_sum'] or 0) - (d['ref_sum'] or 0)} ₽</b>")
    lines.append(f"⏳ Кончился период: <b>{d['ended']}</b> · 🔴 отключено: <b>{d['expired']}</b>")
    lines.append(f"💬 В поддержку: <b>{d['sup_msgs']}</b> сообщ. от <b>{d['sup_users']}</b> чел.")
    on_line = (f"<b>{len(online['emails'])}</b>" if online.get("ok")
               else "<i>панель не ответила</i>")
    lines.append(f"\n🔌 Сейчас онлайн: {on_line} · активных подписок: <b>{d['active_subs']}</b>")
    return "\n".join(lines)


async def digest_tick(context):
    """Раз в 10 минут: пора ли слать сводку за вчера.

    Не планируем задачу на точное время — так сводка не потеряется, если в
    назначенный час бот лежал: уйдёт, как только он поднимется.
    """
    from config import ADMIN_ID
    cfg = load_config()
    if not cfg.get("digest_enabled", True):
        return
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    if now.hour < int(cfg.get("digest_hour", 9)) or cfg.get("digest_last") == today:
        return
    cfg["digest_last"] = today
    save_config(cfg)
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=await build_digest(1),
                                       parse_mode="HTML")
    except Exception:
        pass


async def purge_tick(context):
    from database import purge_activity
    days = int(load_config().get("activity_retention_days", 90) or 90)
    await purge_activity(days)


async def handle_digest_toggle(query, context):
    cfg = load_config()
    cfg["digest_enabled"] = not cfg.get("digest_enabled", True)
    save_config(cfg)
    await handle_control_menu(query, context)


async def handle_digest_hour_menu(query):
    cur = int(load_config().get("digest_hour", 9))
    hours = [7, 8, 9, 10, 12, 15, 18, 21]
    rows = [[
        InlineKeyboardButton(("• " if h == cur else "") + f"{h}:00",
                             callback_data=f"ctl_digest_set:{h}")
        for h in hours[i:i + 4]
    ] for i in range(0, len(hours), 4)]
    rows.append(_back("ctl_menu"))
    await query.edit_message_text(
        "🕘 <b>Во сколько присылать сводку?</b>\n\nСводка приходит за прошедшие сутки.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_digest_set_hour(query, context, hour: int):
    if not 0 <= hour <= 23:
        return
    cfg = load_config()
    cfg["digest_hour"] = hour
    save_config(cfg)
    await handle_control_menu(query, context)


async def handle_digest_now(query, context):
    await query.edit_message_text("📤 Собираю сводку...")
    text = await build_digest(0)
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([_back("ctl_menu")]),
    )


# ── Помощь с подключением ────────────────────────────────────────────────────

CONNECT_HELP_HOURS = (1, 3, 6, 12, 24)


def last_seen_text(ms) -> str:
    """Подпись к времени последнего подключения из панели: мс, 0 — ни разу."""
    if ms is None:
        return "<i>клиента нет в панели</i>"
    if ms <= 0:
        return "⚪️ подключений ещё не было"
    ago = datetime.now().timestamp() - ms / 1000
    if ago < 120:
        return "🟢 в сети"
    if ago < 3600:
        span = f"{int(ago // 60)} мин"
    elif ago < 48 * 3600:
        span = f"{int(ago // 3600)} ч"
    else:
        span = f"{int(ago // 86400)} дн."
    return f"последнее подключение {span} назад"


async def handle_connect_help_menu(query, context=None):
    from database import connect_help_stats
    cfg = load_config()
    on = cfg.get("connect_help_enabled", True)
    hours = int(cfg.get("connect_help_hours", 3))
    st = await connect_help_stats()
    text = (
        "🆘 <b>Помощь с подключением</b>\n\n"
        f"Если человек получил подписку, а VPN за <b>{hours} ч</b> ни разу не "
        "подключился, бот один раз пишет ему: как подключиться и кнопка в поддержку.\n\n"
        f"📌 Статус: <b>{'ВКЛ ✅' if on else 'ВЫКЛ ❌'}</b>\n"
        f"📨 Отправлено за 7 дней: <b>{st['week']}</b> · всего: <b>{st['total']}</b>\n\n"
        "<i>Подключение бот узнаёт у панели. Хранит только отметку "
        "«подключался хоть раз» — без времени и адресов.</i>"
    )
    rows = [
        [InlineKeyboardButton("🔴 Выключить" if on else "🟢 Включить",
                              callback_data="ctl_ch_toggle")],
        [InlineKeyboardButton(("• " if h == hours else "") + f"{h} ч",
                              callback_data=f"ctl_ch_set:{h}")
         for h in CONNECT_HELP_HOURS],
        _back("ctl_menu"),
    ]
    await query.edit_message_text(text, parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(rows))


async def handle_connect_help_toggle(query, context):
    cfg = load_config()
    cfg["connect_help_enabled"] = not cfg.get("connect_help_enabled", True)
    save_config(cfg)
    await handle_connect_help_menu(query, context)


async def handle_connect_help_set(query, context, hours: int):
    if hours not in CONNECT_HELP_HOURS:
        return
    cfg = load_config()
    cfg["connect_help_hours"] = hours
    save_config(cfg)
    await handle_connect_help_menu(query, context)


async def connect_help_tick(context):
    """Раз в полчаса: кому из новых подписчиков помочь с подключением.

    Смотрим только подписки последних двух суток сверх задержки — после
    выкладки бот не напишет тем, кто получил подписку давно. Кто хоть раз
    подключался, отмечается и больше не проверяется: после оплаты бот
    пересоздаёт клиента в панели, и её счётчик подключений обнуляется.
    """
    from config import ADMIN_ID
    import maintenance as mnt
    from database import (
        recent_subs_for_connect_help, mark_connect_help, log_activity, is_banned,
    )
    from blacklist import is_blacklisted
    from panel import get_last_online

    cfg = load_config()
    if not cfg.get("connect_help_enabled", True) or mnt.is_maintenance():
        return
    hours = int(cfg.get("connect_help_hours", 3))
    rows = await recent_subs_for_connect_help(hours + 48)
    if not rows:
        return
    r = await get_last_online()
    if not r.get("ok"):
        return
    last = r["last"]

    # записей подписки у человека может быть несколько — решаем по человеку
    seen, due = set(), set()
    for tg_id, email, status, age in rows:
        ms = last.get(email)
        if ms is None:
            continue  # клиента нет в панели — судить не по чему
        if ms > 0:
            seen.add(tg_id)
        elif status == "active" and (age or 0) >= hours * 3600:
            due.add(tg_id)

    for tg_id in seen:
        await mark_connect_help(tg_id, "seen")

    support_on = mnt.feature_enabled("support")
    kb = [
        [InlineKeyboardButton("❓ Как подключиться", callback_data="how_to")],
        [InlineKeyboardButton("👤 Моя подписка", callback_data="my_paid_sub")],
    ]
    if support_on:
        kb.append([InlineKeyboardButton("💬 Написать в поддержку", callback_data="support_open")])
    text = (
        "🔌 <b>Получилось подключиться?</b>\n\n"
        "Похоже, VPN ещё ни разу не подключался. Настройка занимает пару минут:\n\n"
        "1. Установите приложение INCY\n"
        "2. В «👤 Моя подписка» скопируйте ссылку\n"
        "3. Вставьте её в приложение и подключитесь\n\n"
        + ("Если не выходит — напишите нам, поможем." if support_on
           else "Подробная инструкция — по кнопке ниже.")
    )

    for tg_id in due - seen:
        if tg_id == ADMIN_ID or await is_banned(tg_id) or await is_blacklisted(tg_id):
            continue
        if not await mark_connect_help(tg_id, "sent"):
            continue
        try:
            await context.bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML",
                                           reply_markup=InlineKeyboardMarkup(kb))
            await log_activity(tg_id, "ev:connect_help")
        except Exception:
            pass
