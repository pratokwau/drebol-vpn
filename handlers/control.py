"""Раздел «Контроль»: что происходит в боте и на VPN.

• лента — каждое нажатие, команда и вид сообщения в боте;
• важные события — регистрации, триалы, оплаты, возвраты, отключения;
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

PER_PAGE = 15

# Подписи действий по началу callback-данных
CB_LABELS = {
    # пользователь
    "back_start": "🏠 Главное меню",
    "check_sub": "📢 Проверка подписки на канал",
    "my_paid_sub": "👤 Моя подписка",
    "renew_sub": "💳 Открыл продление",
    "pay_invoice": "🧾 Создал счёт",
    "tariff_pick": "💳 Смотрит тариф",
    "i_paid": "✅ Нажал «Я оплатил»",
    "enter_promo": "🎟 Ввод промокода",
    "remove_promo": "🎟 Убрал промокод",
    "qr_code": "📱 QR-код",
    "copy_sub": "📋 Скопировал ссылку",
    "reissue_key": "🔁 Перевыпуск ключа",
    "reissue_do": "🔁 Подтвердил перевыпуск",
    "remind_settings": "⏰ Напоминания",
    "fraud_menu": "🕵 Повторные триалы",
    "site_menu": "🌐 Сайт",
    "backup_menu": "💾 Бэкап",
    "rw_menu": "🆕 Remnawave",
    "rw_test": "🔌 Проверка Remnawave",
    "rw_migrate_go": "🚚 Перенос клиентов",
    "rw_notify_go": "📨 Рассылка новых ссылок",
    "rw_marks_go": "🧹 Снял метки переезда",
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
    "confirm_payment": "💰 Подтвердил оплату",
    "reject_payment": "❌ Отклонил оплату",
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
    "bl_add_apply": "⛔ Внёс в ЧС",
    "bl_sync": "🔄 Обновил общий ЧС",
    "promo_give_do": "🎁 Выдал промокод",
    "promo_seg_do": "📤 Раздал промокоды",
    "promo_income": "📊 Что принесли промокоды",
    "mnt_feature": "⏸ Выключатель функции",
    "pay_provider_set": "💳 Сменил платёжную систему",
    "tariff_toggle": "💰 Тариф вкл/выкл",
    "tariff_del_ok": "🗑 Удалил тариф",
    "promo_toggle": "🎟 Промокод вкл/выкл",
    "helper_add": "👥 Добавление помощника",
    "ctl_ch_toggle": "🆘 Помощь с подключением вкл/выкл",
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


def action_label(action: str, details: str | None) -> str:
    kind, _, rest = (action or "").partition(":")
    if kind == "cb":
        # опасные кнопки: нажатие только спрашивает «Точно?», действие — ok:…
        from handlers.confirm import OK_PREFIX, confirm_title
        if rest.startswith(OK_PREFIX):
            return f"✅ {confirm_title(rest[len(OK_PREFIX):]) or _esc(rest)}"
        title = confirm_title(rest)
        if title:
            return f"❔ {title}?"
        return CB_LABELS.get(rest.split(":")[0], f"⚙️ {_esc(rest)}")
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
    from database import activity_summary
    from panel import get_online_emails

    s = await activity_summary()
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
        [InlineKeyboardButton("⚙️ Аудит админки", callback_data="act_feed:admin:1")],
        [
            InlineKeyboardButton("🔌 Кто онлайн", callback_data="ctl_online"),
            InlineKeyboardButton("📊 Трафик", callback_data="ctl_traffic"),
        ],
        [InlineKeyboardButton("🆘 Помощь с подключением", callback_data="ctl_ch_menu")],
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


async def handle_activity_feed(query, scope: str = "all", page: int = 1):
    from config import ADMIN_ID
    from database import list_activity
    if scope not in FEED_TITLES:
        scope = "all"
    rows, total_pages = await list_activity(scope, page, PER_PAGE)

    lines = [f"<b>{FEED_TITLES[scope]}</b> — стр. {page}/{total_pages}\n"]
    if not rows:
        lines.append("Пока пусто.")
    for tg_id, action, details, ts, fn, un in rows:
        # в аудите себя не подписываем, а помощника — да
        who = "" if scope == "admin" and tg_id == ADMIN_ID else f"{_who(fn, un, tg_id)} · "
        lines.append(f"<code>{_short_ts(ts)}</code> {who}{action_label(action, details)}")

    kb = []
    nav = _nav(f"act_feed:{scope}", page, total_pages)
    if nav:
        kb.append(nav)
    kb.append([
        InlineKeyboardButton(("• " if key == scope else "") + title.split(" ", 1)[1],
                             callback_data=f"act_feed:{key}:1")
        for key, title in FEED_TITLES.items()
    ])
    kb.append(_back("ctl_menu"))
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


async def handle_user_activity(query, tg_id: int, page: int = 1):
    from database import list_activity, get_user_info
    rows, total_pages = await list_activity(f"user:{tg_id}", page, PER_PAGE)
    u = await get_user_info(tg_id)
    name = _who(u[1] if u else None, u[2] if u else None, tg_id)

    lines = [f"📜 <b>Действия: {name}</b>", f"🆔 <code>{tg_id}</code> · стр. {page}/{total_pages}\n"]
    if not rows:
        lines.append("Действий пока нет.")
    for _tg, action, details, ts, _fn, _un in rows:
        lines.append(f"<code>{_short_ts(ts)}</code> {action_label(action, details)}")

    kb = []
    nav = _nav(f"user_activity:{tg_id}", page, total_pages)
    if nav:
        kb.append(nav)
    kb.append(_back(f"user_profile:{tg_id}", "◀️ К профилю"))
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
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
    await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)


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
