"""Раздел «Логи»: что происходит в боте и на VPN.

• лента — каждое нажатие, команда и вид сообщения в боте;
• важные события — регистрации, триалы, оплаты, возвраты, отключения;
• история подписок — то, что делали с подписками: раньше она жила отдельным
  разделом в «Платных подписках», теперь это вкладка здесь;
• аудит админки — кто из своих что нажимал, с отдельной вкладкой помощников;
• журнал ошибок — падения бота, ошибки панели и платёжки;
• кто сейчас онлайн на VPN и кто сколько потратил трафика;
• ежедневная сводка админу.

VPN-данные здесь только живые и суммарные: онлайн и счётчики трафика берутся
у панели в момент просмотра. История подключений, IP и посещённых сайтов не
собирается — это противоречило бы обещанию «без логов».
"""

from __future__ import annotations

import html as _html
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config

logger = logging.getLogger(__name__)

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
    "web_menu": "🌐 Веб-доступ",
    "site_menu": "🌐 Сайт",
    "cab_menu": "🪪 Личный кабинет",
    "cab_toggle": "🪪 API кабинета вкл/выкл",
    "cab_check": "🩺 Проверил кабинет",
    "cab_find": "🔎 Искал адрес бота",
    "cab_public": "🔗 Адрес API кабинета",
    "cab_port": "🔌 Порт API кабинета",
    "cab_turnstile": "🔑 Капча Turnstile",
    "cab_turnstile_site": "🔑 Site key Turnstile",
    "cab_turnstile_secret": "🔒 Secret key Turnstile",
    "backup_menu": "💾 Бэкап",
    "rw_menu": "🆕 Remnawave",
    "rw_test": "🔌 Проверка Remnawave",
    "backup_export": "📤 Выгрузка базы",
    "backup_apply": "♻️ Восстановление из бэкапа",
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
    # удаления, вкл/выкл подписок и техработ идут через «Точно?» —
    # их подписи в handlers/confirm.py (CONFIRM_TITLES)
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
    "panel_names_sync": "👤 Актуализировал юзернеймы и ники в панели",
    "panel_sync": "🔄 Точечная синхронизация с панелью",
    "panel_sync_menu": "🔄 Открыл синхронизацию",
    "sub_hwid_del": "📱 Отключил устройство (админская)",
    "bl_add_apply": "⛔ Внёс в ЧС",
    "bl_sync": "🔄 Обновил общий ЧС",
    "promo_give_do": "🎁 Выдал промокод",
    "promo_seg_do": "📤 Раздал промокоды",
    "promo_income": "📊 Что принесли промокоды",
    "mnt_feature": "⏸ Выключатель функции",
    "tariff_toggle": "💰 Тариф вкл/выкл",
    "tariff_del_ok": "🗑 Удалил тариф",
    "promo_toggle": "🎟 Промокод вкл/выкл",
    "helper_add": "👥 Добавление помощника",
    "ctl_ch_toggle": "🆘 Помощь с подключением вкл/выкл",
    "ctl_menu": "📜 Открыл логи",
    "act_feed": "📜 Смотрел ленту",
    "ctl_online": "🔌 Смотрел, кто онлайн",
    "ctl_digest_now": "📤 Сводка вручную + бэкап",
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
    "gift_pick": "🎁 Подарок подписки",
    "gift_tariff": "🎁 Выбрал срок подарка",
    "gift_pay": "🎁 Оплатил подарок",
    "pay_provider_menu": "💰 Финансы",
    "anore_menu": "💳 Платёжная система",
    "servers_menu": "🖥 Серверы",
    "payments": "💰 Оплаты",
    "payment_view": "💰 Открыл платёж",
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
    "bl_reason": "📝 Выбрал причину блокировки",
    "bl_term": "⏳ Выбрал срок блокировки",
    "bl_check": "🔍 Проверка в ЧС",
    "bl_remote_toggle": "🌐 Общий ЧС вкл/выкл",
    "fraud_list": "🕵 Список находок",
    "fraud_pair": "🕵 Открыл находку",
    "fraud_ip_toggle": "🌐 Адрес как улика вкл/выкл",
    "winback_settings": "🎯 Возврат ушедших",
    "winback_test": "📨 Пример письма возврата",
    "toggle_winback": "🎯 Возврат ушедших вкл/выкл",
    "toggle_winback_paid": "👤 Возврат ушедших: кому писать",
    "set_winback_days": "1️⃣ Срок первой волны",
    "set_winback_percent": "1️⃣ Скидка первой волны",
    "set_winback_days2": "2️⃣ Срок второй волны",
    "set_winback_percent2": "2️⃣ Скидка второй волны",
    "set_winback_life": "⏳ Срок промокода возврата",
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
    "bot_started": "🟢 Бот запущен",
    "panel_sync": "🔄 Сверка с панелью",
    "panel_sync_failed": "🔴 Сверка с панелью не удалась",
    "cabinet_login": "🪪 Вход в кабинет",
    "cabinet_login_failed": "🔴 Неудачный вход в кабинет",
}

STATE_LABELS = {
    "awaiting_support_msg": "✉️ Написал в поддержку",
    "awaiting_promo_code": "🎟 Ввёл промокод",
    "awaiting_admin_reply": "✉️ Ответил в тикет",
    "awaiting_dm_user": "📌 Написал юзеру",
    "awaiting_find_user": "🔍 Искал юзера",
    "awaiting_support_contact": "👤 Ввёл аккаунт поддержки",
    "awaiting_cabinet_public": "🔗 Ввёл адрес API",
    "awaiting_cabinet_port": "🔌 Ввёл порт API",
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
    "errors": "🚨 Ошибки",
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
    from features.staff import is_staff
    from core.database import log_activity
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

def _back(cb: str, label: str = "◀️ К логам") -> list:
    return [InlineKeyboardButton(label, callback_data=cb)]


async def handle_control_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    if context:
        context.user_data.pop("state", None)
    from core.database import activity_summary, control_today
    from services.panel import get_online_emails

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
    lines = ["📜 <b>Логи</b>", "", "<blockquote>" + "\n".join(now) + "</blockquote>"]

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
    ch_label = (f"через {int(cfg.get('connect_help_hours', 3))} ч"
                if cfg.get("connect_help_enabled", True) else "выключена")
    lines.append("\n⚙️ <b>Автоматика</b>")
    lines.append("<blockquote>"
                 f"📨 Сводка в личку: <b>{f'каждый день в {digest_time_text(cfg)}, с бэкапом' if digest_on else 'выключена'}</b>\n"
                 f"🛟 Помощь с подключением: <b>{ch_label}</b>\n"
                 f"🗄 Журнал хранится <b>{int(cfg.get('activity_retention_days', 90))}</b> дней"
                 "</blockquote>")

    kb = [
        [InlineKeyboardButton("📜 Лента действий", callback_data="act_feed:all:1"),
         InlineKeyboardButton("⭐ Важное", callback_data="act_feed:important:1")],
        [InlineKeyboardButton("💳 История подписок", callback_data="act_feed:subs:1")],
        [InlineKeyboardButton("⚙️ Аудит админки", callback_data="act_feed:admin:1"),
         InlineKeyboardButton("👥 Помощники", callback_data="act_feed:helpers:1")],
        [InlineKeyboardButton("🚨 Ошибки", callback_data="act_feed:errors:1")],
        [InlineKeyboardButton("📤 Выгрузка", callback_data="log_export_menu"),
         InlineKeyboardButton("🗄 Хранение", callback_data="log_storage_menu")],
        [
            InlineKeyboardButton("🔌 Кто онлайн", callback_data="ctl_online"),
            InlineKeyboardButton("📊 Трафик", callback_data="rw_usage"),
        ],
        [InlineKeyboardButton("🔍 Найти человека", callback_data="find_user"),
         InlineKeyboardButton("🛟 Помощь с подключением", callback_data="ctl_ch_menu")],
        [InlineKeyboardButton(
            "📨 Сводка · вкл ✅" if digest_on else "📨 Сводка · выкл",
            callback_data="ctl_digest_toggle",
        )],
        [
            InlineKeyboardButton("🕘 Время сводки", callback_data="ctl_digest_hour"),
            InlineKeyboardButton("📤 Сводка сейчас + бэкап", callback_data="ctl_digest_now"),
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


# ── Фильтр ленты ───────────────────────────────────────────────────────────

LOG_KIND_LABELS = {"cb": "Кнопки", "cmd": "Команды", "msg": "Сообщения", "ev": "События"}
LOG_DATE_LABELS = {"today": "Сегодня", "yesterday": "Вчера", "week": "7 дней"}


def _log_filter(context) -> dict:
    """Фильтр ленты из user_data. Пустой фильтр — всё как раньше."""
    f = (context.user_data or {}).get("log_filter") if context else None
    return dict(f) if isinstance(f, dict) else {}


def _save_log_filter(context, f: dict):
    if context is not None:
        context.user_data["log_filter"] = dict(f)


def _filter_dates(f: dict) -> tuple[str | None, str | None]:
    """Дата фильтра → границы date_from/date_to для list_activity."""
    from datetime import date, timedelta
    d = f.get("date")
    today = date.today()
    if d == "today":
        s = today.isoformat()
        return s, s
    if d == "yesterday":
        s = (today - timedelta(days=1)).isoformat()
        return s, s
    if d == "week":
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    if d and len(d) == 10 and d[4] == "-" and d[7] == "-":
        return d, d
    return None, None


def _filter_summary(f: dict) -> str:
    """Человекочитаемая сводка активного фильтра."""
    parts = []
    if f.get("user"):
        parts.append(f"👤 {f.get('user_label') or f['user']}")
    if f.get("kind"):
        parts.append(LOG_KIND_LABELS.get(f["kind"], f["kind"]))
    if f.get("date"):
        parts.append(LOG_DATE_LABELS.get(f["date"], f["date"]))
    return " · ".join(parts)


def _log_filter_menu_parts(f: dict):
    """Текст и клавиатура меню фильтра. Общая для кнопки и ввода текстом."""
    scope = f.get("scope", "all")
    summary = _filter_summary(f)
    text = ("🔍 <b>Фильтр ленты</b>\n\n"
            f"Сейчас: <b>{_esc(summary) if summary else 'без фильтра'}</b>\n\n"
            "Фильтр действует на вкладки ленты, пока его не сбросят.")
    kind = f.get("kind")
    kind_row = [InlineKeyboardButton(
        ("• " if kind is None else "") + "Все", callback_data="act_fk:all")]
    for k, label in LOG_KIND_LABELS.items():
        kind_row.append(InlineKeyboardButton(
            ("• " if k == kind else "") + label, callback_data=f"act_fk:{k}"))
    date = f.get("date")
    date_row = [InlineKeyboardButton(
        ("• " if date is None else "") + "Все", callback_data="act_fd:all")]
    for d, label in LOG_DATE_LABELS.items():
        date_row.append(InlineKeyboardButton(
            ("• " if d == date else "") + label, callback_data=f"act_fd:{d}"))
    date_row.append(InlineKeyboardButton("📅 Дата…", callback_data="act_fd:custom"))
    user_row = []
    if f.get("user"):
        user_row.append(InlineKeyboardButton(
            f"✖️ {f.get('user_label') or f['user']}", callback_data="act_fu_clear"))
    else:
        user_row.append(InlineKeyboardButton("👤 Человек…", callback_data="act_fu"))
    kb = [
        [InlineKeyboardButton("Вид действия:", callback_data="noop")],
        kind_row,
        [InlineKeyboardButton("Дата:", callback_data="noop")],
        date_row,
        user_row,
        [InlineKeyboardButton("✅ Применить", callback_data=f"act_fapply:{scope}"),
         InlineKeyboardButton("🧹 Сбросить", callback_data="act_fclear")],
        [InlineKeyboardButton("◀️ К ленте", callback_data=f"act_feed:{scope}:1")],
    ]
    return text, InlineKeyboardMarkup(kb)


async def handle_log_filter_menu(query, context):
    """Меню фильтра ленты: вид действия, дата, человек."""
    f = _log_filter(context)
    text, kb = _log_filter_menu_parts(f)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def handle_log_filter_kind(query, context, kind: str):
    f = _log_filter(context)
    f["kind"] = kind if kind in LOG_KIND_LABELS else None
    _save_log_filter(context, f)
    await handle_log_filter_menu(query, context)


async def handle_log_filter_date(query, context, date: str):
    f = _log_filter(context)
    if date == "all":
        f.pop("date", None)
        _save_log_filter(context, f)
        await handle_log_filter_menu(query, context)
        return
    if date in LOG_DATE_LABELS:
        f["date"] = date
        _save_log_filter(context, f)
        await handle_log_filter_menu(query, context)
        return
    if date == "custom":
        from core.states import AWAITING_LOG_FILTER_DATE
        context.user_data["state"] = AWAITING_LOG_FILTER_DATE
        scope = _log_filter(context).get("scope", "all")
        await query.edit_message_text(
            "📅 <b>Дата</b>\n\nПришли дату: <code>11.11</code> или <code>11.11.2026</code>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ К фильтру", callback_data=f"act_filter:{scope}")]]),
        )


async def handle_log_filter_user_prompt(query, context):
    """Просит ввести человека для фильтра: TG ID, @username или имя."""
    from core.states import AWAITING_LOG_FILTER_USER
    context.user_data["state"] = AWAITING_LOG_FILTER_USER
    scope = _log_filter(context).get("scope", "all")
    await query.edit_message_text(
        "👤 <b>Человек для фильтра</b>\n\nПришли TG ID, @username или имя.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("◀️ К фильтру", callback_data=f"act_filter:{scope}")]]),
    )


async def _apply_filter_user(context, tg_id: int):
    """Записывает человека в фильтр и возвращает (текст, клавиатуру) меню фильтра."""
    from core.database import get_user_info
    f = _log_filter(context)
    u = await get_user_info(tg_id)
    f["user"] = tg_id
    f["user_label"] = _who(u[1] if u else None, u[2] if u else None, tg_id)
    _save_log_filter(context, f)
    return _log_filter_menu_parts(f)


async def handle_log_filter_user_pick(query, context, tg_id: int):
    text, kb = await _apply_filter_user(context, tg_id)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def handle_log_filter_user_input(message, context, text: str):
    """Ввод человека для фильтра ленты: TG ID, @username или имя."""
    from core.database import get_user_info, search_users
    rows = await search_users(text, 5)
    token = text.strip().lstrip("@")
    if token.isdigit() and not rows and await get_user_info(int(token)):
        rows = [(int(token), None, None, None)]
    f = _log_filter(context)
    scope = f.get("scope", "all")
    if len(rows) == 1:
        context.user_data.pop("state", None)
        text, kb = await _apply_filter_user(context, rows[0][0])
        await message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        return
    if rows:
        kb = [[InlineKeyboardButton(_who(r[1], r[2], r[0]),
                                    callback_data=f"act_fu_pick:{r[0]}")]
              for r in rows]
        kb.append([InlineKeyboardButton("◀️ К фильтру", callback_data=f"act_filter:{scope}")])
        await message.reply_text(
            f"🔍 <b>Нашёл: {len(rows)}</b>\n\n"
            "<i>Нажми на человека, чтобы фильтровать по нему.</i>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    else:
        kb = [[InlineKeyboardButton("◀️ К фильтру", callback_data=f"act_filter:{scope}")]]
        await message.reply_text(
            "🔍 <b>Никого не нашёл</b>\n\n"
            "<i>Попробуй ID, @username или часть имени.</i>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def handle_log_filter_date_input(message, context, text: str):
    """Ввод даты фильтра: ДД.ММ или ДД.ММ.ГГГГ."""
    from datetime import date, datetime
    f = _log_filter(context)
    scope = f.get("scope", "all")
    parsed = None
    for fmt in ("%d.%m.%Y", "%d.%m"):
        try:
            parsed = datetime.strptime(text.strip(), fmt)
            break
        except ValueError:
            continue
    back = [[InlineKeyboardButton("◀️ К фильтру", callback_data=f"act_filter:{scope}")]]
    if parsed is None:
        await message.reply_text(
            "❌ <b>Не понял дату</b>\n\nПришли так: <code>11.11</code> или <code>11.11.2026</code>.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(back))
        return
    if parsed.year == 1900:
        # "%d.%m" без года — берём текущий год
        parsed = parsed.replace(year=date.today().year)
    if parsed.date() > date.today():
        await message.reply_text(
            "❌ <b>Дата в будущем.</b> Пришли дату не позже сегодня.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(back))
        return
    f["date"] = parsed.date().isoformat()
    _save_log_filter(context, f)
    context.user_data.pop("state", None)
    text, kb = _log_filter_menu_parts(f)
    await message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def handle_log_export_user_input(message, context, text: str):
    """Ввод человека для выгрузки: TG ID, @username или имя."""
    from core.database import get_user_info, search_users
    rows = await search_users(text, 5)
    token = text.strip().lstrip("@")
    if token.isdigit() and not rows and await get_user_info(int(token)):
        rows = [(int(token), None, None, None)]
    if len(rows) == 1:
        context.user_data.pop("state", None)
        await handle_export_message(message, context, "user", rows[0][0])
        return
    if rows:
        kb = [[InlineKeyboardButton(_who(r[1], r[2], r[0]),
                                    callback_data=f"log_export_pick:{r[0]}")]
              for r in rows]
        kb.append([InlineKeyboardButton("◀️ К выгрузке", callback_data="log_export_menu")])
        await message.reply_text(
            f"🔍 <b>Нашёл: {len(rows)}</b>\n\n"
            "<i>Нажми на человека, чтобы выгрузить его действия.</i>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    else:
        kb = [[InlineKeyboardButton("◀️ К выгрузке", callback_data="log_export_menu")]]
        await message.reply_text(
            "🔍 <b>Никого не нашёл</b>\n\n"
            "<i>Попробуй ID, @username или часть имени.</i>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def handle_log_filter_user_clear(query, context):
    f = _log_filter(context)
    f.pop("user", None)
    f.pop("user_label", None)
    _save_log_filter(context, f)
    await handle_log_filter_menu(query, context)


async def handle_log_filter_clear(query, context):
    f = _log_filter(context)
    scope = f.get("scope", "all")
    _save_log_filter(context, {})
    await handle_activity_feed(query, scope, 1, context)


async def handle_activity_feed(query, scope: str = "all", page: int = 1,
                               context: ContextTypes.DEFAULT_TYPE = None):
    from config import ADMIN_ID
    from core.database import list_activity, list_errors
    if scope not in FEED_TITLES:
        scope = "all"
    f = _log_filter(context) if scope not in ("subs", "errors") else {}

    if scope == "subs":
        lines, total_pages = await _subs_feed(page)
        page = min(max(1, page), total_pages)
        head = [f"<b>{FEED_TITLES[scope]}</b> — стр. {page}/{total_pages}",
                "<i>у каждой записи свой номер: /h123 — открыть подробности</i>", ""]
    elif scope == "errors":
        rows, total_pages = await list_errors(page, PER_PAGE)
        page = min(max(1, page), total_pages)
        head = [f"<b>{FEED_TITLES[scope]}</b> — стр. {page}/{total_pages}",
                "<i>у каждой записи свой номер: /e123 — открыть подробности</i>", ""]
        lines = []
        for eid, source, level, message, details, ts, tg_id in rows:
            mark = "🔴" if level == "error" else "🟡"
            lines.append(f"<code>{_short_ts(ts)}</code> {mark} [{_esc(source)}] "
                         f"{_esc(message)} /e{eid}")
    else:
        date_from, date_to = _filter_dates(f)
        rows, total_pages = await list_activity(
            scope, page, PER_PAGE,
            user_id=f.get("user"), kind=f.get("kind"),
            date_from=date_from, date_to=date_to)
        page = min(max(1, page), total_pages)
        head = [f"<b>{FEED_TITLES[scope]}</b> — стр. {page}/{total_pages}", ""]
        summary = _filter_summary(f)
        if summary:
            head.append(f"🔍 Фильтр: {summary}")
            head.append("")
        lines = []
        for eid, tg_id, action, details, ts, fn, un in rows:
            # в аудите себя не подписываем, а помощника — да
            who = "" if scope == "admin" and tg_id == ADMIN_ID else f"{_who(fn, un, tg_id)} · "
            lines.append(f"<code>{_short_ts(ts)}</code> {who}{action_label(action, details)} /a{eid}")
    if not lines:
        lines = ["Пока пусто."]

    kb = []
    nav = _nav(f"act_feed:{scope}", page, total_pages)
    if nav:
        kb.append(nav)
    if scope not in ("subs", "errors"):
        kb.append([InlineKeyboardButton("🔍 Фильтр", callback_data=f"act_filter:{scope}")])
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


async def handle_activity_entry(target, entry_id: int, edit: bool = True):
    """Подробности записи журнала действий — как /h123 для истории подписок."""
    from core.database import get_activity_entry, get_user_info
    entry = await get_activity_entry(entry_id)
    if not entry:
        if edit:
            await target.answer("Запись не найдена", show_alert=True)
        else:
            await target.reply_text("📋 Такой записи в журнале нет.")
        return
    _id, tg_id, action, details, created_at, fn, un = entry
    u = await get_user_info(tg_id) if tg_id else None
    kb = []
    if tg_id:
        kb.append([InlineKeyboardButton("👤 Профиль", callback_data=f"user_profile:{tg_id}"),
                   InlineKeyboardButton("📜 Его действия", callback_data=f"user_activity:{tg_id}:1")])
    kb.append(_back("act_feed:all:1", "◀️ К ленте"))
    text = (f"📋 <b>{action_label(action, details)}</b>\n\n"
            f"<blockquote>👤 {_who(u[1] if u else None, u[2] if u else None, tg_id)}\n"
            f"🕐 {_short_ts(created_at) if created_at else '?'}</blockquote>"
            + (f"\n\n<blockquote expandable>{_esc(details)}</blockquote>" if details else ""))
    kwargs = dict(parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
                  disable_web_page_preview=True)
    if edit:
        await target.edit_message_text(text, **kwargs)
    else:
        await target.reply_text(text, **kwargs)


async def activity_command(update, context):
    """/a123 из ленты — подробности записи журнала одним нажатием."""
    from features.staff import helper_can, is_helper
    from config import ADMIN_ID
    uid = update.effective_user.id
    if uid != ADMIN_ID and not (is_helper(uid) and helper_can("ctl_hist:0", uid)):
        return
    digits = "".join(c for c in (update.message.text or "") if c.isdigit())
    if digits:
        await handle_activity_entry(update.message, int(digits), edit=False)


async def handle_error_entry(target, entry_id: int, edit: bool = True):
    """Подробности записи журнала ошибок."""
    from core.database import get_error_entry
    entry = await get_error_entry(entry_id)
    if not entry:
        if edit:
            await target.answer("Запись не найдена", show_alert=True)
        else:
            await target.reply_text("🚨 Такой записи в журнале ошибок нет.")
        return
    _id, source, level, message, details, created_at, tg_id = entry
    mark = "🔴" if level == "error" else "🟡"
    kb = [_back("act_feed:errors:1", "◀️ К ошибкам")]
    text = (f"{mark} <b>[{_esc(source)}] {_esc(message)}</b>\n\n"
            f"<blockquote>🕐 {_short_ts(created_at) if created_at else '?'}</blockquote>"
            + (f"\n\n<blockquote expandable>{_esc(details)}</blockquote>" if details else ""))
    kwargs = dict(parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
                  disable_web_page_preview=True)
    if edit:
        await target.edit_message_text(text, **kwargs)
    else:
        await target.reply_text(text, **kwargs)


async def error_command(update, context):
    """/e123 из ленты ошибок — подробности записи одним нажатием."""
    from features.staff import helper_can, is_helper
    from config import ADMIN_ID
    uid = update.effective_user.id
    if uid != ADMIN_ID and not (is_helper(uid) and helper_can("ctl_hist:0", uid)):
        return
    digits = "".join(c for c in (update.message.text or "") if c.isdigit())
    if digits:
        await handle_error_entry(update.message, int(digits), edit=False)


# ── Выгрузка логов ───────────────────────────────────────────────────────────

EXPORT_SCOPES = {"today": "за сегодня", "user": "по человеку", "errors": "ошибки (все сохранённые)"}
EXPORT_MAX_ROWS = 5000


async def handle_export_menu(query, context=None):
    text = ("📤 <b>Выгрузка логов</b>\n\n"
            "Файл CSV: время, человек, действие, подробности.\n"
            "Не больше 5000 строк за раз.")
    kb = [
        [InlineKeyboardButton("📅 За сегодня", callback_data="log_export:today")],
        [InlineKeyboardButton("👤 По человеку…", callback_data="log_export:user")],
        [InlineKeyboardButton("🚨 Ошибки", callback_data="log_export:errors")],
        _back("ctl_menu"),
    ]
    await query.edit_message_text(text, parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


def _export_rows_to_csv(rows, kind: str) -> bytes:
    """Строки в CSV (UTF-8). Для ошибок — свои колонки."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "errors":
        w.writerow(["time", "source", "level", "message", "details"])
        for _id, source, level, message, details, ts, _tg in rows:
            w.writerow([ts, source, level, message, details or ""])
    else:
        w.writerow(["time", "user_id", "name", "action", "details"])
        for _id, tg_id, action, details, ts, fn, un in rows:
            name = f"{fn or ''} (@{un})" if un else (fn or "")
            w.writerow([ts, tg_id, name, action, details or ""])
    return buf.getvalue().encode("utf-8")


async def _build_export(kind: str, tg_id: int | None = None):
    """Собирает CSV выгрузки. Возвращает (имя файла, байты, подпись)."""
    from datetime import date
    from core.database import list_activity, list_errors
    today = date.today().isoformat()
    if kind == "errors":
        rows, _pages = await list_errors(1, EXPORT_MAX_ROWS)
        fname = f"drebol-logs-errors-{today}.csv"
        blob = _export_rows_to_csv(rows, "errors")
        note = f"🚨 Ошибки за всё время хранения: {len(rows)} строк."
    elif kind == "user" and tg_id:
        rows, _pages = await list_activity(f"user:{tg_id}", 1, EXPORT_MAX_ROWS)
        fname = f"drebol-logs-user-{tg_id}-{today}.csv"
        blob = _export_rows_to_csv(rows, "user")
        note = f"👤 Действия человека <code>{tg_id}</code>: {len(rows)} строк."
    else:
        rows, _pages = await list_activity(
            "all", 1, EXPORT_MAX_ROWS, date_from=today, date_to=today)
        fname = f"drebol-logs-today-{today}.csv"
        blob = _export_rows_to_csv(rows, "today")
        note = f"📅 Действия за сегодня: {len(rows)} строк."
    if len(rows) >= EXPORT_MAX_ROWS:
        note += f"\n<i>Показаны первые {EXPORT_MAX_ROWS} строк.</i>"
    return fname, blob, note


async def handle_export(query, context, kind: str, tg_id: int | None = None):
    """Собирает CSV и шлёт файлом. Длинная выгрузка — отдельным сообщением."""
    import io
    await query.edit_message_text(
        "📤 Собираю выгрузку...", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([_back("ctl_menu")]))
    try:
        fname, blob, note = await _build_export(kind, tg_id)
        await context.bot.send_document(
            chat_id=query.from_user.id, document=io.BytesIO(blob), filename=fname,
            caption=note, parse_mode="HTML")
    except Exception as e:
        await query.edit_message_text(
            f"❌ <b>Не отправить выгрузку</b>\n\n<code>{_esc(str(e)[:200])}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([_back("ctl_menu")]))


async def handle_export_message(message, context, kind: str, tg_id: int | None = None):
    """Выгрузка по вводу текстом: та же CSV, но отправка в ответ на сообщение."""
    import io
    await message.reply_text("📤 Собираю выгрузку...", parse_mode="HTML")
    try:
        fname, blob, note = await _build_export(kind, tg_id)
        await context.bot.send_document(
            chat_id=message.chat_id, document=io.BytesIO(blob), filename=fname,
            caption=note, parse_mode="HTML")
    except Exception as e:
        await message.reply_text(
            f"❌ <b>Не отправить выгрузку</b>\n\n<code>{_esc(str(e)[:200])}</code>",
            parse_mode="HTML")


# ── Хранение журналов ────────────────────────────────────────────────────────

RETENTION_DAYS = (30, 90, 180, 365)


async def handle_storage_menu(query, context=None):
    """Сколько хранится журнал, сколько в нём записей, размер базы."""
    from core.database import activity_stats
    cfg = load_config()
    days = int(cfg.get("activity_retention_days", 90) or 90)
    st = await activity_stats()
    lines = [
        "🗄 <b>Хранение журналов</b>",
        "",
        f"📅 Срок хранения: <b>{days} дн.</b>",
        f"📜 Записей действий: <b>{st['activity_rows']}</b>",
        f"🚨 Записей ошибок: <b>{st['error_rows']}</b>",
        f"🕐 Самая старая запись действий: "
        f"<b>{_short_ts(st['oldest_activity']) if st['oldest_activity'] else '—'}</b>",
        f"🕐 Самая старая ошибка: "
        f"<b>{_short_ts(st['oldest_error']) if st['oldest_error'] else '—'}</b>",
        f"💾 Размер базы: <b>{_fmt_bytes(st['db_bytes'])}</b>",
        "",
        "<i>Старые записи удаляются сами раз в сутки. Кнопка ниже "
        "чистит их прямо сейчас.</i>",
    ]
    kb = [
        [InlineKeyboardButton(("• " if d == days else "") + f"{d} дн.",
                              callback_data=f"log_retention:{d}")
         for d in RETENTION_DAYS],
        [InlineKeyboardButton("🧹 Очистить старые сейчас", callback_data="log_purge_now")],
        _back("ctl_menu"),
    ]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_retention_set(query, context, days: int):
    if days not in RETENTION_DAYS:
        return
    cfg = load_config()
    cfg["activity_retention_days"] = days
    save_config(cfg)
    await handle_storage_menu(query, context)


async def handle_purge_now(query, context):
    """Чистит старые записи обоих журналов и показывает, сколько удалено."""
    from core.database import purge_activity, purge_errors
    days = int(load_config().get("activity_retention_days", 90) or 90)
    removed_act = await purge_activity(days)
    removed_err = await purge_errors(days)
    await query.edit_message_text(
        f"🧹 <b>Очистка готова</b>\n\n"
        f"Удалено записей действий: <b>{removed_act}</b>\n"
        f"Удалено записей ошибок: <b>{removed_err}</b>\n"
        f"Хранятся записи за последние <b>{days} дн.</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🗄 К хранению", callback_data="log_storage_menu")],
             _back("ctl_menu")]))

async def handle_hist_entry(target, entry_id: int, edit: bool = True):
    """Подробности записи истории подписок."""
    from core.database import get_user_info
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
    from features.staff import helper_can, is_helper
    from config import ADMIN_ID
    uid = update.effective_user.id
    if uid != ADMIN_ID and not (is_helper(uid) and helper_can("ctl_hist:0", uid)):
        return
    digits = "".join(c for c in (update.message.text or "") if c.isdigit())
    if digits:
        await handle_hist_entry(update.message, int(digits), edit=False)


USER_TABS = {"all": "📜 Всё", "important": "⭐ Важное", "subs": "💳 Подписка"}


async def handle_user_activity(query, tg_id: int, page: int = 1, scope: str = "all"):
    """Что человек делал в боте — то же, что в «Логах», но про одного."""
    from core.database import get_user_info, list_activity
    if scope not in USER_TABS:
        scope = "all"
    u = await get_user_info(tg_id)
    name = _who(u[1] if u else None, u[2] if u else None, tg_id)

    if scope == "subs":
        lines, total_pages = await _subs_feed(page, tg_id)
    else:
        key = f"user_important:{tg_id}" if scope == "important" else f"user:{tg_id}"
        rows, total_pages = await list_activity(key, page, PER_PAGE)
        lines = [f"<code>{_short_ts(ts)}</code> {action_label(action, details)} /a{eid}"
                 for eid, _tg, action, details, ts, _fn, _un in rows]
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
    kb.append([InlineKeyboardButton("📜 Вся лента", callback_data="act_feed:all:1"),
               InlineKeyboardButton("👤 Профиль", callback_data=f"user_profile:{tg_id}")])
    kb.append(_back("ctl_menu"))
    await query.edit_message_text(
        "\n".join(head + _fit(lines)), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


async def handle_online(query):
    from services.panel import get_online_emails
    from core.database import users_by_emails
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


# ── Ежедневная сводка ────────────────────────────────────────────────────────

def digest_time_text(cfg: dict) -> str:
    """Время сводки одной строкой: «9:30». Минуты появились со вводом
    своего времени; у старых настроек их нет — тогда ровно час."""
    hour = int(cfg.get("digest_hour", 9) or 9)
    minute = int(cfg.get("digest_minute", 0) or 0)
    return f"{hour}:{minute:02d}"


async def build_digest(day_offset: int = 1) -> str:
    from core.database import digest_stats
    from services.panel import get_online_emails
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

    Сводка уходит одним сообщением вместе со свежим бэкапом дня: архив
    собирается в момент отправки (тот же make_archive, что и в «Бэкапе»),
    а текст сводки становится подписью к файлу. Если архив не собрался
    или подпись не влезла в лимит Telegram (1024 символа) — сводка всё
    равно уйдёт обычным текстовым сообщением, без файла.
    """
    import io
    from config import ADMIN_ID
    cfg = load_config()
    if not cfg.get("digest_enabled", True):
        return
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hour = int(cfg.get("digest_hour", 9))
    minute = int(cfg.get("digest_minute", 0) or 0)
    if (now.hour, now.minute) < (hour, minute) or cfg.get("digest_last") == today:
        return
    cfg["digest_last"] = today
    save_config(cfg)
    try:
        text = await build_digest(1)
    except Exception:
        return
    caption = (text + "\n\n💾 К сводке приложен свежий бэкап дня "
               "(внутри ключи — не пересылай).")
    try:
        from features.backup import make_archive
        blob, name, _counts = make_archive()
        if len(caption) > 1024:
            raise ValueError("подпись длиннее 1024 символов")
        await context.bot.send_document(
            chat_id=ADMIN_ID, document=io.BytesIO(blob), filename=name,
            caption=caption, parse_mode="HTML")
    except Exception:
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=text,
                                           parse_mode="HTML")
        except Exception:
            pass


async def purge_tick(context):
    """Раз в сутки чистит оба журнала: действия и ошибки — за один и тот же срок."""
    from core.database import purge_activity, purge_errors
    days = int(load_config().get("activity_retention_days", 90) or 90)
    removed_act = await purge_activity(days)
    removed_err = await purge_errors(days)
    logger.info("purge_tick: удалено %s записей действий и %s записей ошибок (старше %s дн.)",
                removed_act, removed_err, days)


async def handle_digest_toggle(query, context):
    cfg = load_config()
    cfg["digest_enabled"] = not cfg.get("digest_enabled", True)
    save_config(cfg)
    await handle_control_menu(query, context)


async def handle_digest_hour_menu(query):
    cfg = load_config()
    cur = int(cfg.get("digest_hour", 9))
    cur_min = int(cfg.get("digest_minute", 0) or 0)
    hours = [7, 8, 9, 10, 12, 15, 18, 21]
    rows = [[
        InlineKeyboardButton(("• " if h == cur else "") + f"{h}:00",
                             callback_data=f"ctl_digest_set:{h}")
        for h in hours[i:i + 4]
    ] for i in range(0, len(hours), 4)]
    rows.append([InlineKeyboardButton("⌨️ Своё время", callback_data="ctl_digest_custom")])
    rows.append(_back("ctl_menu"))
    await query.edit_message_text(
        "🕘 <b>Во сколько присылать сводку?</b>\n\n"
        f"Сейчас: <b>{cur}:{cur_min:02d}</b>\n"
        "Сводка приходит за прошедшие сутки.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_digest_custom(query, context):
    """Просит ввести своё время сводки текстом: час или час и минуты."""
    from core.states import AWAITING_DIGEST_HOUR
    context.user_data["state"] = AWAITING_DIGEST_HOUR
    await query.edit_message_text(
        "🕘 <b>Своё время сводки</b>\n\n"
        "Пришли время, когда присылать сводку: просто час "
        "(<code>9</code>) или час и минуты (<code>9:30</code>).\n\n"
        "<i>Проверка ходит каждые 10 минут, поэтому сводка придёт "
        "в первый проход после указанного времени.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([_back("ctl_digest_hour")]),
    )


def parse_digest_time(text: str) -> tuple | None:
    """«9», «09», «9:30» → (час, минуты). Всё остальное — None."""
    import re
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{1,2}))?\s*", text or "")
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if not 0 <= hour <= 23:
        return None
    if not 0 <= minute <= 59:
        return None
    return hour, minute


async def handle_digest_set_hour(query, context, hour: int):
    if not 0 <= hour <= 23:
        return
    cfg = load_config()
    cfg["digest_minute"] = 0
    cfg["digest_hour"] = hour
    save_config(cfg)
    await handle_control_menu(query, context)


async def handle_digest_now(query, context):
    """Сводка вручную: текст — в сообщении, бэкап — файлом следом.

    В отличие от плановой сводки, здесь текст нельзя сделать подписью
    к файлу: сообщение уже открыто в меню, поэтому сводка остаётся
    текстом на месте, а архив уходит отдельным сообщением сразу за ним.
    """
    import io
    from html import escape
    await query.edit_message_text("📤 Собираю сводку...")
    try:
        text = await build_digest(0)
    except Exception as e:
        await query.edit_message_text(
            f"❌ <b>Не собрать сводку</b>\n\n<code>{escape(str(e)[:200])}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([_back("ctl_menu")]),
        )
        return
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([_back("ctl_menu")]),
    )
    try:
        from features.backup import make_archive
        blob, name, _counts = make_archive()
        await context.bot.send_document(
            chat_id=query.from_user.id, document=io.BytesIO(blob), filename=name,
            caption=("💾 <b>Бэкап Drebol VPN на сегодня</b>\n\n"
                     "<i>Внутри ключи — не пересылай.</i>"),
            parse_mode="HTML")
    except Exception as e:
        await query.edit_message_text(
            text + f"\n\n⚠️ Бэкап не собрался: <code>{escape(str(e)[:150])}</code>",
            parse_mode="HTML",
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
    from core.database import connect_help_stats
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
    import core.maintenance as mnt
    from core.database import (
        recent_subs_for_connect_help, mark_connect_help, log_activity,
    )
    from features.blacklist import is_blacklisted
    from services.panel import get_last_online

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
        [InlineKeyboardButton("🔐 Моя подписка", callback_data="my_paid_sub")],
    ]
    if support_on:
        kb.append([InlineKeyboardButton("🛟 Написать в поддержку", callback_data="support_open")])
    text = (
        "🔌 <b>Получилось подключиться?</b>\n\n"
        "Похоже, VPN ещё ни разу не подключался. Настройка занимает пару минут:\n\n"
        "1. Установите приложение INCY\n"
        "2. В «🔐 Моя подписка» скопируйте ссылку\n"
        "3. Вставьте её в приложение и подключитесь\n\n"
        + ("Если не выходит — напишите нам, поможем." if support_on
           else "Подробная инструкция — по кнопке ниже.")
    )

    for tg_id in due - seen:
        if tg_id == ADMIN_ID or await is_blacklisted(tg_id):
            continue
        if not await mark_connect_help(tg_id, "sent"):
            continue
        try:
            await context.bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML",
                                           reply_markup=InlineKeyboardMarkup(kb))
            await log_activity(tg_id, "ev:connect_help")
        except Exception:
            pass
