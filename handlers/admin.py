import subprocess
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import INSTALL_DIR, load_config, save_config
from keyboards import admin_keyboard, back_admin, documents_keyboard, channel_keyboard
from states import (
    AWAITING_CHANNEL, AWAITING_PRIVACY_URL, AWAITING_TERMS_URL,
    AWAITING_FIND_USER, AWAITING_LOG_CHANNEL,
    AWAITING_WINBACK_DAYS, AWAITING_WINBACK_PERCENT, AWAITING_REVIEW_DAYS,
    AWAITING_DM_USER,
)


async def handle_admin_panel(query):
    from database import get_unread_tickets_count
    unread = await get_unread_tickets_count()
    badge = f"\n\n🔴 Непрочитанных тикетов: <b>{unread}</b>" if unread else ""
    await query.edit_message_text(
        "⚙️ <b>Панель администратора</b>\n\nВыбери действие:" + badge,
        parse_mode="HTML",
        reply_markup=admin_keyboard(unread),
    )


async def handle_dashboard(query):
    from database import get_dashboard_stats
    s = await get_dashboard_stats()
    cfg = load_config()
    price = cfg.get("paid_price", 0) or 0
    revenue_est = s["payments_confirmed"] * price

    text = (
        "📊 <b>Статистика</b>\n\n"
        "<b>👥 Пользователи</b>\n"
        f"Всего: <b>{s['users_total']}</b>\n"
        f"Сегодня: <b>+{s['users_today']}</b> · за неделю: <b>+{s['users_week']}</b>\n\n"
        "<b>💳 Платные подписки</b>\n"
        f"Активные: <b>{s['paid_active']}</b> · истёкшие: <b>{s['paid_expired']}</b>\n"
        f"На триале: <b>{s['trial_active']}</b> · платящих: <b>{s['paying']}</b>\n"
        f"Всего записей: <b>{s['paid_total']}</b>\n\n"
        "<b>⏳ Ожидают действия</b>\n"
        f"Заявок на оплату: <b>{s['payment_pending']}</b>\n"
        f"Запросов на триал: <b>{s['requests_pending']}</b>\n"
        f"Непрочитанных тикетов: <b>{s['unread_tickets']}</b>\n\n"
        "<b>💰 Оплаты</b>\n"
        f"Подтверждено всего: <b>{s['payments_confirmed']}</b> · сегодня: <b>{s['payments_today']}</b>\n"
        f"Выдано триалов: <b>{s['trials_approved']}</b>\n"
        f"Оценка выручки: <b>~{revenue_est} ₽</b> <i>(по тек. цене {price}₽)</i>\n\n"
        "<b>🎁 Прочее</b>\n"
        f"Рефералов: <b>{s['ref_total']}</b> (с бонусом: {s['ref_rewarded']})\n"
        f"Промокодов активно: <b>{s['promos_active']}</b> · активаций: <b>{s['promo_uses']}</b>\n"
        f"Админских подписок: <b>{s['admin_subs']}</b>"
    )
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Оплаты по дням", callback_data="payment_stats:30")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="dashboard")],
            [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
        ]),
    )


async def handle_healthcheck(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from xui_api import get_inbounds
    import json
    await query.edit_message_text("🩺 Проверяю серверы...")
    result = await get_inbounds()
    back = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Проверить снова", callback_data="healthcheck")],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ])
    if not result["success"]:
        await query.edit_message_text(
            "🩺 <b>Здоровье серверов</b>\n\n"
            "🔴 <b>Панель недоступна!</b>\n"
            f"<code>{result['error']}</code>",
            parse_mode="HTML", reply_markup=back,
        )
        return
    inbounds = result["inbounds"]
    if not inbounds:
        await query.edit_message_text(
            "🩺 <b>Здоровье серверов</b>\n\n"
            "🟢 Панель доступна, но инбаундов нет.",
            parse_mode="HTML", reply_markup=back,
        )
        return
    lines = ["🩺 <b>Здоровье серверов</b>\n", "🟢 Панель доступна\n"]
    up_count = 0
    for inb in inbounds:
        enable = inb.get("enable", True)
        tag = inb.get("tag") or inb.get("remark") or f"#{inb.get('id')}"
        protocol = inb.get("protocol", "?")
        port = inb.get("port", "")
        # число клиентов
        clients = 0
        cs = inb.get("clientStats")
        if isinstance(cs, list):
            clients = len(cs)
        else:
            try:
                settings = json.loads(inb.get("settings") or "{}")
                clients = len(settings.get("clients") or [])
            except Exception:
                clients = 0
        icon = "🟢" if enable else "🔴"
        if enable:
            up_count += 1
        lines.append(f"{icon} <b>{tag}</b> ({protocol}:{port}) · 👤 {clients}")
    lines.append(f"\nАктивных инбаундов: <b>{up_count}/{len(inbounds)}</b>")
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML", reply_markup=back,
    )


async def handle_channel_menu(query):
    cfg = load_config()
    channel_url = cfg.get("channel_url")
    sub_enabled = cfg.get("force_subscribe", False)
    channel_line = f"📢 Канал: <code>{channel_url}</code>" if channel_url else "📢 Канал: <i>не задан</i>"
    sub_line = "🔔 Обязательная подписка: <b>включена</b>" if sub_enabled else "🔕 Обязательная подписка: <b>выключена</b>"
    await query.edit_message_text(
        "📢 <b>Управление каналом</b>\n\n"
        f"{channel_line}\n{sub_line}",
        parse_mode="HTML",
        reply_markup=channel_keyboard(),
    )


async def handle_set_channel(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_CHANNEL
    await query.edit_message_text(
        "📢 <b>Установка канала</b>\n\n"
        "Отправь ссылку на Telegram-канал (например: <code>https://t.me/mychannel</code>):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_documents_menu(query):
    await query.edit_message_text(
        "📄 <b>Документы</b>\n\n"
        "Здесь можно задать ссылки на юридические документы:",
        parse_mode="HTML",
        reply_markup=documents_keyboard(),
    )


async def handle_set_privacy_url(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_PRIVACY_URL
    await query.edit_message_text(
        "📋 <b>Политика конфиденциальности</b>\n\nОтправь ссылку на документ:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_set_terms_url(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_TERMS_URL
    await query.edit_message_text(
        "📄 <b>Пользовательское соглашение</b>\n\nОтправь ссылку на документ:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_git_update(query):
    await query.edit_message_text("⏳ Обновляю бота с GitHub...")
    try:
        result = subprocess.run(
            ["git", "-C", INSTALL_DIR, "pull"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            await query.edit_message_text(
                f"❌ Ошибка git pull:\n<code>{result.stderr.strip()}</code>",
                parse_mode="HTML",
                reply_markup=back_admin(),
            )
            return
        output = result.stdout.strip()
        await query.edit_message_text(
            f"✅ Обновление загружено:\n<code>{output}</code>\n\nПерезапускаю бота...",
            parse_mode="HTML",
        )
        subprocess.Popen(
            ["systemctl", "restart", "drebol-vpn"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        await query.edit_message_text("❌ Таймаут при обновлении. Попробуй позже.", reply_markup=back_admin())
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}", reply_markup=back_admin())


# ── Найти юзера ──────────────────────────────────────────────────────────────

async def handle_find_user(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_FIND_USER
    await query.edit_message_text(
        "🔍 <b>Найти пользователя</b>\n\n"
        "Введи Telegram ID пользователя:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_user_profile(query_or_msg, tg_id: int, edit=True):
    from database import get_user_info, is_banned, get_user_review
    from paidsub.storage import (
        get_paid_sub_by_tg_id, get_referral_stats, get_muted_until,
    )
    import aiosqlite
    from database import DB_PATH

    user_info = await get_user_info(tg_id)
    if not user_info:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")]])
        text = f"❌ Пользователь <code>{tg_id}</code> не найден в базе."
        if edit:
            await query_or_msg.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        else:
            await query_or_msg.reply_text(text, parse_mode="HTML", reply_markup=kb)
        return

    _, first_name, username = user_info
    uname = f"@{username}" if username else f"id{tg_id}"
    banned = await is_banned(tg_id)

    lines = [
        f"👤 <b>Профиль пользователя</b>\n",
        f'📛 <a href="tg://user?id={tg_id}">{first_name}</a> ({uname})',
        f"🆔 TG ID: <code>{tg_id}</code>",
    ]

    if banned:
        lines.append("🚫 <b>ЗАБАНЕН</b>")

    # Подписка
    sub = await get_paid_sub_by_tg_id(tg_id)
    if sub:
        status = sub[11] if len(sub) > 11 else "active"
        status_labels = {"active": "🟢 активна", "renewal": "🟡 ожидает продления", "expired": "🔴 истекла"}
        lines.append(f"\n💳 Подписка: <b>{status_labels.get(status, status)}</b>")
        lines.append(f"📅 До: <b>{sub[6]}</b>")
        times = sub[12] if len(sub) > 12 else 0
        lines.append(f"🏷 Тип: {'оплаченная' if times > 0 else 'пробная'} (продлений: {times})")
    else:
        lines.append("\n💳 Подписка: <b>нет</b>")

    # Мьют
    muted = await get_muted_until(tg_id)
    if muted:
        lines.append(f"🔇 Заглушён до: <b>{muted}</b>")

    # Рефералы
    ref_stats = await get_referral_stats(tg_id)
    if ref_stats["total"] > 0:
        lines.append(f"\n👥 Приглашено: <b>{ref_stats['total']}</b> (с бонусом: {ref_stats['rewarded']})")

    # Тикеты
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM support_messages WHERE user_id = ? AND from_admin = 0", (tg_id,)
        ) as cur:
            ticket_count = (await cur.fetchone())[0]
    if ticket_count > 0:
        lines.append(f"🎫 Сообщений в поддержку: <b>{ticket_count}</b>")

    # Отзыв
    review = await get_user_review(tg_id)
    if review:
        stars = "⭐️" * review[2]
        lines.append(f"\n⭐️ Оценка: {stars}")
        if review[3]:
            lines.append(f"💬 {review[3][:100]}")

    # История
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM paid_sub_history WHERE tg_id = ?", (tg_id,)
        ) as cur:
            history_count = (await cur.fetchone())[0]
    if history_count:
        lines.append(f"\n📜 Записей в истории: <b>{history_count}</b>")

    # Кнопки
    kb_rows = []
    if sub:
        kb_rows.append([InlineKeyboardButton("💳 К подписке", callback_data=f"paid_sub_view:{sub[0]}")])
    if ticket_count > 0:
        kb_rows.append([InlineKeyboardButton("🎫 Переписка", callback_data=f"ticket_view:{tg_id}:1")])
    if history_count > 0:
        kb_rows.append([InlineKeyboardButton("🕐 История", callback_data=f"user_history:{tg_id}:1")])
    if banned:
        kb_rows.append([InlineKeyboardButton("🔓 Разбанить", callback_data=f"unban_user:{tg_id}")])
    else:
        kb_rows.append([InlineKeyboardButton("🚫 Забанить", callback_data=f"ban_user:{tg_id}")])
    kb_rows.append([
        InlineKeyboardButton("📌 Написать", callback_data=f"dm_user:{tg_id}"),
        InlineKeyboardButton("🔇 Заглушить", callback_data=f"paid_mute_user:{tg_id}"),
    ])
    kb_rows.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    kb = InlineKeyboardMarkup(kb_rows)

    text = "\n".join(lines)
    if edit:
        await query_or_msg.edit_message_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    else:
        await query_or_msg.reply_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)


_ACTION_LABELS_ADMIN = {
    "sub_created": "📦 Создана",
    "trial_approved": "🆓 Триал",
    "trial_rejected": "❌ Триал отклонён",
    "payment_confirmed": "💰 Оплата",
    "payment_rejected": "❌ Оплата отклонена",
    "promo_used": "🎟 Промокод",
    "referral_bonus": "🎁 Реф. бонус",
    "referral_invited_bonus": "🎁 Бонус приглашённого",
    "sub_enabled": "▶️ Включена",
    "sub_disabled": "⏸ Приостановлена",
    "sub_deleted": "🗑 Удалена",
    "sub_frozen": "❄️ Заморожена",
    "user_unmuted": "🔊 Разблокирован",
}


async def handle_user_history(query, tg_id: int, page: int = 1):
    from database import get_user_info
    from paidsub.storage import get_user_history
    rows, total_pages = await get_user_history(tg_id, page)
    u = await get_user_info(tg_id)
    name = u[1] if u else str(tg_id)

    if not rows:
        await query.edit_message_text(
            f"🕐 <b>История — {name}</b>\n\nЗаписей нет.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Профиль", callback_data=f"user_profile:{tg_id}")],
            ]),
        )
        return

    lines = [f"🕐 <b>История — {name}</b> (<code>{tg_id}</code>)\n"]
    for entry_id, _, action, details, created_at in rows:
        label = _ACTION_LABELS_ADMIN.get(action, action)
        ts = created_at[:16] if created_at else ""
        detail_line = f"\n     <i>{details[:100]}</i>" if details else ""
        lines.append(f"{label} · {ts}{detail_line}")

    kb = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"user_history:{tg_id}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"user_history:{tg_id}:{page + 1}"))
        kb.append(nav)
    kb.append([InlineKeyboardButton("◀️ Профиль", callback_data=f"user_profile:{tg_id}")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_ban_user(query, tg_id: int):
    from database import ban_user
    from log_channel import send_log
    await ban_user(tg_id)
    await send_log(query._bot, f"🚫 Забанен: <code>{tg_id}</code>")
    await query.answer(f"🚫 Пользователь {tg_id} забанен", show_alert=True)
    await handle_user_profile(query, tg_id)


async def handle_unban_user(query, tg_id: int):
    from database import unban_user
    from log_channel import send_log
    await unban_user(tg_id)
    await send_log(query._bot, f"🔓 Разбанен: <code>{tg_id}</code>")
    await query.answer(f"🔓 Пользователь {tg_id} разбанен", show_alert=True)
    await handle_user_profile(query, tg_id)


# ── Лог-канал ────────────────────────────────────────────────────────────────

async def handle_log_channel_settings(query):
    cfg = load_config()
    channel_id = cfg.get("log_channel_id")
    if channel_id:
        status_line = f"📢 Канал: <code>{channel_id}</code>"
    else:
        status_line = "📢 Канал: <i>не задан</i>"
    await query.edit_message_text(
        f"🧾 <b>Лог-канал</b>\n\n"
        f"{status_line}\n\n"
        "Бот будет дублировать ключевые события (оплаты, регистрации, алерты) в этот канал/чат.\n\n"
        "Отправь ID канала или чата (число, напр. <code>-1001234567890</code>).\n"
        "Бот должен быть админом в канале.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Изменить", callback_data="set_log_channel")],
            *([
                [InlineKeyboardButton("🗑 Отключить", callback_data="clear_log_channel")],
            ] if channel_id else []),
            [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
        ]),
    )


async def handle_set_log_channel(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_LOG_CHANNEL
    await query.edit_message_text(
        "🧾 <b>Лог-канал</b>\n\n"
        "Отправь ID канала или чата (число, напр. <code>-1001234567890</code>):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_clear_log_channel(query):
    cfg = load_config()
    cfg.pop("log_channel_id", None)
    save_config(cfg)
    await query.answer("🗑 Лог-канал отключён", show_alert=True)
    await handle_log_channel_settings(query)


# ── Winback ──────────────────────────────────────────────────────────────────

async def handle_winback_settings(query):
    cfg = load_config()
    enabled = cfg.get("winback_enabled", False)
    days = cfg.get("winback_days", 3)
    percent = cfg.get("winback_percent", 20)
    status = "ВКЛ ✅" if enabled else "ВЫКЛ ❌"
    await query.edit_message_text(
        "🎯 <b>Winback — возврат ушедших</b>\n\n"
        f"📌 Статус: <b>{status}</b>\n"
        f"📅 Через дней после истечения: <b>{days}</b>\n"
        f"💯 Скидка: <b>{percent}%</b>\n\n"
        "Автоматически отправляет спец-предложение со скидкой "
        "пользователям, чья подписка истекла.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔴 Выключить" if enabled else "🟢 Включить",
                callback_data="toggle_winback",
            )],
            [InlineKeyboardButton("📅 Дней до отправки", callback_data="set_winback_days")],
            [InlineKeyboardButton("💯 Размер скидки %", callback_data="set_winback_percent")],
            [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
        ]),
    )


async def handle_toggle_winback(query):
    cfg = load_config()
    cfg["winback_enabled"] = not cfg.get("winback_enabled", False)
    save_config(cfg)
    await handle_winback_settings(query)


async def handle_set_winback_days(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_WINBACK_DAYS
    cfg = load_config()
    current = cfg.get("winback_days", 3)
    await query.edit_message_text(
        f"📅 <b>Дней до отправки Winback</b>\n\n"
        f"Сейчас: <b>{current}</b>\n\n"
        "Введи число дней после истечения подписки:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_set_winback_percent(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_WINBACK_PERCENT
    cfg = load_config()
    current = cfg.get("winback_percent", 20)
    await query.edit_message_text(
        f"💯 <b>Скидка Winback</b>\n\n"
        f"Сейчас: <b>{current}%</b>\n\n"
        "Введи размер скидки в % (от 1 до 100):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Отзывы (админ) ──────────────────────────────────────────────────────────

async def handle_reviews_menu(query, page: int = 1):
    from database import get_reviews_stats, get_reviews_list, get_user_info
    stats = await get_reviews_stats()
    rows, total_pages = await get_reviews_list(page)

    cfg = load_config()
    review_days = cfg.get("review_request_days", 0)
    review_status = f"ВКЛ (через {review_days} дн.)" if review_days > 0 else "ВЫКЛ"

    stars_bar = ""
    for rating, count in stats["breakdown"]:
        stars_bar += f"{'⭐️' * rating} — <b>{count}</b>\n"

    lines = [
        "⭐️ <b>Отзывы пользователей</b>\n",
        f"📊 Всего: <b>{stats['total']}</b> · Средняя: <b>{stats['avg']}/5</b>",
        f"📩 Авто-запрос: <b>{review_status}</b>\n",
    ]
    if stars_bar:
        lines.append(stars_bar)

    kb = []
    for r_id, tg_id, rating, text, created_at in rows:
        u = await get_user_info(tg_id)
        name = u[1] if u else str(tg_id)
        stars = "⭐️" * rating
        ts = created_at[5:16] if created_at else ""
        preview = ""
        if text:
            preview = f" · {text[:20]}…" if len(text) > 20 else f" · {text}"
        kb.append([InlineKeyboardButton(
            f"{stars} {name} · {ts}{preview}",
            callback_data=f"review_view:{r_id}",
        )])

    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"reviews_page:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"reviews_page:{page + 1}"))
        kb.append(nav)

    kb.append([InlineKeyboardButton("⏱ Настроить авто-запрос", callback_data="set_review_days")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_review_view(query, review_id: int):
    from database import get_user_info
    import aiosqlite
    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, tg_id, rating, text, created_at FROM reviews WHERE id = ?",
            (review_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        await query.answer("Отзыв не найден", show_alert=True)
        return
    _, tg_id, rating, text, created_at = row
    u = await get_user_info(tg_id)
    name = u[1] if u else str(tg_id)
    uname = f"@{u[2]}" if u and u[2] else f"id{tg_id}"
    stars = "⭐️" * rating
    review_text = text if text else "<i>без текста</i>"
    await query.edit_message_text(
        f"⭐️ <b>Отзыв</b>\n\n"
        f'👤 <a href="tg://user?id={tg_id}">{name}</a> ({uname})\n'
        f"🆔 <code>{tg_id}</code>\n"
        f"📊 Оценка: {stars}\n"
        f"🕐 {created_at}\n\n"
        f"💬 {review_text}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Профиль юзера", callback_data=f"user_profile:{tg_id}")],
            [InlineKeyboardButton("◀️ К отзывам", callback_data="reviews_menu")],
        ]),
        disable_web_page_preview=True,
    )


async def handle_set_review_days(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_REVIEW_DAYS
    cfg = load_config()
    current = cfg.get("review_request_days", 0)
    cur_str = f"{current} дн." if current > 0 else "выключено"
    await query.edit_message_text(
        f"⏱ <b>Авто-запрос отзыва</b>\n\n"
        f"Сейчас: <b>{cur_str}</b>\n\n"
        "Через сколько дней после активации подписки запрашивать отзыв?\n"
        "Введи число дней (0 — выключить):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Написать юзеру ─────────────────────────────────────────────────────────

async def handle_dm_user(query, tg_id: int, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_DM_USER
    context.user_data["dm_target"] = tg_id
    from database import get_user_info
    u = await get_user_info(tg_id)
    name = u[1] if u else str(tg_id)
    await query.edit_message_text(
        f"📌 <b>Сообщение для {name}</b> (<code>{tg_id}</code>)\n\n"
        "Напиши текст сообщения одним сообщением:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К профилю", callback_data=f"user_profile:{tg_id}")],
        ]),
    )


# ── Статистика оплат по дням ────────────────────────────────────────────────

async def handle_payment_stats(query, days: int = 30):
    from database import get_payments_by_day
    rows = await get_payments_by_day(days)
    cfg = load_config()
    price = cfg.get("paid_price", 0) or 0

    if not rows:
        await query.edit_message_text(
            f"📊 <b>Оплаты за {days} дн.</b>\n\nНет данных.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="dashboard")],
            ]),
        )
        return

    max_cnt = max(r[1] for r in rows)
    total = sum(r[1] for r in rows)
    bar_width = 12

    lines = [f"📊 <b>Оплаты за {days} дн.</b>\n"]
    for date_str, cnt in rows:
        short_date = date_str[5:]  # MM-DD
        filled = int(cnt / max_cnt * bar_width) if max_cnt > 0 else 0
        bar = "▓" * filled + "░" * (bar_width - filled)
        lines.append(f"<code>{short_date} {bar}</code> {cnt}")

    revenue = total * price
    lines.append(f"\n💰 Всего: <b>{total}</b> оплат")
    if price > 0:
        lines.append(f"💵 Оценка выручки: <b>~{revenue} ₽</b>")

    toggle_days = 7 if days == 30 else 30
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"📅 За {toggle_days} дн.",
                callback_data=f"payment_stats:{toggle_days}",
            )],
            [InlineKeyboardButton("◀️ Назад", callback_data="dashboard")],
        ]),
    )
