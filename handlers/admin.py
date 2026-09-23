import subprocess
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import INSTALL_DIR, load_config, save_config
from keyboards import admin_keyboard, back_admin, documents_keyboard, channel_keyboard
from states import (
    AWAITING_CHANNEL, AWAITING_PRIVACY_URL, AWAITING_TERMS_URL,
    AWAITING_FIND_USER, AWAITING_LOG_CHANNEL,
    AWAITING_WINBACK_DAYS, AWAITING_WINBACK_PERCENT,
    AWAITING_DM_USER,
)


async def handle_admin_panel(query):
    from database import get_unread_tickets_count
    unread = await get_unread_tickets_count()
    # короткая сводка дня прямо на входе — чтобы не ходить в статистику ради цифр
    summary = ""
    try:
        from database import get_dashboard_stats
        s = await get_dashboard_stats()
        todo = []
        if s["payment_pending"]:
            todo.append(f"💰 заявок на оплату: <b>{s['payment_pending']}</b>")
        if s["requests_pending"]:
            todo.append(f"🆕 запросов на триал: <b>{s['requests_pending']}</b>")
        if unread:
            todo.append(f"🎫 открытых тикетов: <b>{unread}</b>")
        summary = (
            "\n\n<blockquote>"
            f"👥 Пользователей: <b>{s['users_total']}</b>  ·  сегодня <b>+{s['users_today']}</b>\n"
            f"💳 Активных подписок: <b>{s['paid_active']}</b>  ·  платящих <b>{s['paying_active']}</b>\n"
            f"💵 Сегодня: <b>{s['revenue_today']} ₽</b>  ·  оплат <b>{s['payments_today']}</b>"
            "</blockquote>"
        )
        if todo:
            summary += "\n\n⏳ <b>Ждут вас</b>\n" + "\n".join(todo)
    except Exception:
        if unread:
            summary = f"\n\n🔴 Открытых тикетов: <b>{unread}</b>"
    await query.edit_message_text(
        "🛠 <b>Админка</b>" + summary,
        parse_mode="HTML",
        reply_markup=admin_keyboard(unread),
    )


async def handle_dashboard(query):
    from database import get_dashboard_stats
    from xui_api import count_panel_clients
    s = await get_dashboard_stats()
    cfg = load_config()
    price = cfg.get("paid_price", 0) or 0

    # Выручка: точная сумма из истории + оценка по оплатам без сохранённой суммы
    unknown_pays = s["payments_confirmed"] - s["revenue_known"]
    revenue = s["revenue_total"] + unknown_pays * price
    if unknown_pays > 0:
        revenue_note = f" <i>(точно по {s['revenue_known']} из {s['payments_confirmed']}, остальное ~{price}₽)</i>"
    else:
        revenue_note = ""

    # Сверка базы с панелью 3x-UI
    db_paid = s["paid_total"]
    db_admin = s["admin_subs"]
    db_all = db_paid + db_admin
    panel = await count_panel_clients()
    if panel.get("success"):
        p_total, p_paid, p_other = panel["total"], panel["paid"], panel["other"]
        if p_total == db_all and p_paid == db_paid:
            sync_line = "✅ База и панель совпадают"
        else:
            sync_line = (
                f"⚠️ Расхождение: платных {p_paid} vs {db_paid} · "
                f"прочих {p_other} vs {db_admin}"
            )
        panel_block = (
            "🖥 <b>Панель 3x-UI</b>\n<blockquote>"
            f"Клиентов в панели: <b>{p_total}</b>  (платных {p_paid} · прочих {p_other})\n"
            f"Записей в базе: <b>{db_all}</b>  (платных {db_paid} · админских {db_admin})\n"
            f"{sync_line}</blockquote>\n\n"
        )
    else:
        panel_block = (
            "🖥 <b>Панель 3x-UI</b>\n<blockquote>"
            f"🔴 Панель недоступна — сверка не выполнена\n"
            f"Записей в базе: <b>{db_all}</b>  (платных {db_paid} · админских {db_admin})"
            "</blockquote>\n\n"
        )

    other_line = f" · прочие: <b>{s['paid_other']}</b>" if s["paid_other"] else ""

    text = (
        "📊 <b>Статистика</b>\n\n"
        "💰 <b>Деньги</b>\n<blockquote>"
        f"Выручка всего: <b>{revenue} ₽</b>{revenue_note}\n"
        f"Сегодня: <b>{s['revenue_today']} ₽</b>  ·  оплат <b>{s['payments_today']}</b>\n"
        f"Подтверждено оплат: <b>{s['payments_confirmed']}</b>  ·  триалов выдано <b>{s['trials_issued']}</b>"
        "</blockquote>\n\n"
        "👥 <b>Пользователи</b>\n<blockquote>"
        f"Всего: <b>{s['users_total']}</b>\n"
        f"Сегодня: <b>+{s['users_today']}</b>  ·  за неделю: <b>+{s['users_week']}</b>"
        "</blockquote>\n\n"
        "💳 <b>Подписки</b>\n<blockquote>"
        f"Активные: <b>{s['paid_active']}</b>  ·  истёкшие: <b>{s['paid_expired']}</b>{other_line}\n"
        f"Из активных: триал <b>{s['trial_active']}</b>  ·  платящих <b>{s['paying_active']}</b>\n"
        f"Оплачивали хоть раз: <b>{s['paying_total']}</b>  ·  всего записей <b>{s['paid_total']}</b>"
        "</blockquote>\n\n"
        f"{panel_block}"
        "⏳ <b>Ждут действия</b>\n<blockquote>"
        f"Заявок на оплату: <b>{s['payment_pending']}</b>\n"
        f"Запросов на триал: <b>{s['requests_pending']}</b>\n"
        f"Открытых тикетов: <b>{s['unread_tickets']}</b>"
        "</blockquote>\n\n"
        "🎁 <b>Прочее</b>\n<blockquote>"
        f"Рефералов: <b>{s['ref_total']}</b>  (с бонусом {s['ref_rewarded']})\n"
        f"Промокодов активно: <b>{s['promos_active']}</b>  ·  активаций <b>{s['promo_uses']}</b>\n"
        f"Админских подписок: <b>{s['admin_subs']}</b>"
        "</blockquote>"
    )
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Оплаты по дням", callback_data="payment_stats:30"),
             InlineKeyboardButton("🔄 Обновить", callback_data="dashboard")],
            [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
        ]),
    )


async def handle_healthcheck(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from xui_api import probe_servers

    await query.edit_message_text("🩺 Проверяю серверы...")
    r = await probe_servers()
    panel, sub, inbounds = r["panel"], r["sub"], r["inbounds"]

    back = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Проверить снова", callback_data="healthcheck")],
        [InlineKeyboardButton("◀️ Назад", callback_data="xui_settings")],
    ])

    lines = ["🩺 <b>Здоровье серверов</b>\n"]

    # Панель
    # ошибки панели приходят её же словами и могут содержать HTML-страницу
    from html import escape
    if panel["ok"]:
        lines.append(f"🟢 <b>Панель</b> — отвечает, {panel['ms']} мс")
    else:
        lines.append(f"🔴 <b>Панель недоступна</b>\n     <code>{escape(str(panel['error']))}</code>")

    # Подписки — отдельный сервис на своём порту, падает независимо от панели
    if sub["ok"]:
        note = "" if sub["status"] < 400 else f" (HTTP {sub['status']})"
        lines.append(f"🟢 <b>Подписки</b> — отвечают, {sub['ms']} мс{note}")
    else:
        lines.append(
            f"🔴 <b>Подписки не работают</b> — порт {sub.get('port', '?')}\n"
            f"     <code>{escape(str(sub['error']))}</code>\n"
            f"     <i>Клиенты не смогут обновить ключ.</i>"
        )

    # Инбаунды
    if panel["ok"]:
        if not inbounds:
            lines.append("\n⚪️ Инбаундов нет.")
        else:
            checkable = [i for i in inbounds if i["enabled"] and
                         (i.get("mapped") or i["reachable"])]
            up = sum(1 for i in checkable if i["reachable"])
            lines.append(f"\n<b>Инбаунды</b> — доступно {up}/{len(checkable)}")
            for i in inbounds:
                if not i["enabled"]:
                    icon, tail = "⚪️", " · выключен"
                elif i["reachable"]:
                    where = "" if not i.get("mapped") else f" · {i['host']}"
                    icon = "🟢"
                    tail = f"{where} · UDP, отказа нет" if i.get("udp") else f"{where} · {i['ms']} мс"
                elif not i.get("mapped"):
                    # проверяли по адресу панели, а инбаунд может жить на узле —
                    # это не авария, а незаданная привязка
                    icon, tail = "⚪️", " · узел не привязан"
                else:
                    icon, tail = "🔴", f" · {escape(str(i['host']))} · {escape(str(i['error']))}"
                lines.append(
                    f"{icon} <b>{i['tag']}</b> ({i['protocol']}:{i['port']}) "
                    f"· 👤 {i['clients']}{tail}"
                )
            if any(i.get("udp") for i in inbounds if i["enabled"]):
                lines.append(
                    "\n<i>UDP-инбаунды (hysteria и подобные) на чужие пакеты не отвечают, "
                    "поэтому проверяются мягко: «живым» считается всё, кроме отказа порта.</i>"
                )

    problems = []
    if not panel["ok"]:
        problems.append("панель не отвечает — бот не сможет выдавать и продлевать ключи")
    if not sub["ok"]:
        problems.append("сервис подписок лежит — выданные ключи не обновятся у клиентов")
    dead = [i["tag"] for i in inbounds
            if i["enabled"] and not i["reachable"] and i.get("mapped")]
    if dead:
        problems.append("порт не принимает соединения: " + ", ".join(dead[:5]))

    unmapped = sorted({i["prefix"] for i in inbounds
                       if i["enabled"] and not i["reachable"] and not i.get("mapped")})
    if unmapped:
        problems.append(
            "не проверены — не задан адрес узла: " + ", ".join(unmapped[:5])
            + ". Укажи в «🖧 Узлы»"
        )
    if problems:
        lines.append("\n⚠️ <b>Проблемы:</b>")
        lines += [f"• {p}" for p in problems]
    elif panel["ok"]:
        lines.append("\n✅ Всё работает.")

    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=back,
        disable_web_page_preview=True,
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
        "<i>Пришли Telegram ID пользователя одним сообщением.</i>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_user_profile(query_or_msg, tg_id: int, edit=True):
    from database import get_user_info, is_banned
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

    from html import escape
    _, first_name, username = user_info
    # имя человек задаёт сам — экранируем, иначе карточка не откроется
    first_name = escape(str(first_name or tg_id))
    uname = escape(f"@{username}" if username else f"id{tg_id}")
    banned = await is_banned(tg_id)
    # помощнику карточка без денег и без управления подпиской
    from staff import is_helper
    viewer = getattr(query_or_msg, "from_user", None)
    limited = bool(viewer) and is_helper(viewer.id)

    lines = [
        f'👤 <b><a href="tg://user?id={tg_id}">{first_name}</a></b>',
        f"{uname}  ·  <code>{tg_id}</code>",
    ]

    if banned:
        lines.append("\n🚫 <b>Забанен</b>")
    from blacklist import entry as bl_entry, public_reason
    ble = await bl_entry(tg_id)
    if ble:
        from html import escape
        src = "вручную" if ble["source"] == "manual" else "общий список"
        lines.append(f"\n⛔ <b>В чёрном списке</b> ({src})\n"
                     f"<blockquote>{escape(public_reason(ble['reason']))}</blockquote>")

    # Подписка
    sub = await get_paid_sub_by_tg_id(tg_id)
    if sub:
        status = sub[11] if len(sub) > 11 else "active"
        status_labels = {"active": "🟢 активна", "renewal": "🟡 ждёт продления", "expired": "🔴 истекла"}
        times = sub[12] if len(sub) > 12 else 0
        from xui_api import get_last_online
        from handlers.control import last_seen_text
        lo = await get_last_online(timeout=5)
        vpn = (last_seen_text(lo["last"].get(sub[2])) if lo.get("ok")
               else "<i>панель не ответила</i>")
        lines += [
            "", "💳 <b>Подписка</b>",
            "<blockquote>"
            f"Статус: <b>{status_labels.get(status, status)}</b>\n"
            f"📅 До: <b>{sub[6]}</b>\n"
            f"🏷 {'Оплаченная' if times > 0 else 'Пробная'}  ·  продлений: <b>{times}</b>\n"
            f"🔌 VPN: {vpn}"
            "</blockquote>",
        ]
    else:
        lines += ["", "💳 Подписки <b>нет</b>"]

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

    # Оплаты и история — только админу: в истории есть суммы оплат
    history_count = 0
    if not limited:
        from handlers.payments import user_payments_block
        pay_block = await user_payments_block(tg_id)
        if pay_block:
            lines.append(pay_block)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM paid_sub_history WHERE tg_id = ?", (tg_id,)
            ) as cur:
                history_count = (await cur.fetchone())[0]
        if history_count:
            lines.append(f"\n📜 Записей в истории: <b>{history_count}</b>")

    # Кнопки
    kb_rows = []
    if sub and not limited:
        kb_rows.append([InlineKeyboardButton("💳 К подписке", callback_data=f"paid_sub_view:{sub[0]}")])
    info_btns = [InlineKeyboardButton("📜 Действия", callback_data=f"user_activity:{tg_id}:1")]
    if ticket_count > 0:
        info_btns.append(InlineKeyboardButton("🎫 Переписка", callback_data=f"ticket_view:{tg_id}:1"))
    if history_count > 0:
        info_btns.append(InlineKeyboardButton("🕐 История", callback_data=f"user_history:{tg_id}:1"))
    kb_rows.append(info_btns)
    if limited:
        kb_rows.append([InlineKeyboardButton("📌 Написать", callback_data=f"dm_user:{tg_id}")])
        kb_rows.append([InlineKeyboardButton("◀️ В панель поддержки", callback_data="admin_panel")])
    else:
        if banned:
            kb_rows.append([InlineKeyboardButton("🔓 Разбанить", callback_data=f"unban_user:{tg_id}")])
        else:
            kb_rows.append([InlineKeyboardButton("🚫 Забанить", callback_data=f"ban_user:{tg_id}")])
        kb_rows.append([
            InlineKeyboardButton("🎁 Выдать промокод", callback_data=f"promo_give_for:{tg_id}"),
            InlineKeyboardButton("⛔ Чёрный список", callback_data=f"bl_view:{tg_id}"),
        ])
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
    "payment_refunded": "↩️ Возврат",
    "sub_enabled": "▶️ Включена",
    "sub_disabled": "⏸ Приостановлена",
    "sub_deleted": "🗑 Удалена",
    "sub_frozen": "❄️ Заморожена",
    "user_unmuted": "🔊 Разблокирован",
}


async def handle_user_history(query, tg_id: int, page: int = 1):
    from database import get_user_info
    from paidsub.storage import get_user_history
    from html import escape
    rows, total_pages = await get_user_history(tg_id, page)
    u = await get_user_info(tg_id)
    name = escape(str(u[1] if u else tg_id))

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
        detail_line = f"\n     <i>{escape(details[:100])}</i>" if details else ""
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

async def handle_remind_settings(query):
    cfg = load_config()
    enabled = cfg.get("remind_enabled", True)
    from paidsub.time_parser import fmt_duration
    first = int(cfg.get("remind_first", 3 * 86400) or 0)
    second = int(cfg.get("remind_second", 86400) or 0)
    status = "ВКЛ ✅" if enabled else "ВЫКЛ ❌"
    await query.edit_message_text(
        "⏰ <b>Напоминания о конце подписки</b>\n\n"
        f"📌 Статус: <b>{status}</b>\n"
        f"1️⃣ Первое: за <b>{fmt_duration(first) if first else 'выключено'}</b>\n"
        f"2️⃣ Второе: за <b>{fmt_duration(second) if second else 'выключено'}</b>\n\n"
        "Бот пишет заранее, что срок подходит к концу, и зовёт продлить. "
        "Остаток при оплате не сгорает, поэтому платить заранее людям выгодно.\n"
        "Каждое напоминание уходит один раз за период; продление сбрасывает счёт.\n"
        "<i>0 выключает отдельное напоминание.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔴 Выключить" if enabled else "🟢 Включить",
                callback_data="toggle_remind",
            )],
            [InlineKeyboardButton("1️⃣ Первое напоминание", callback_data="set_remind_first")],
            [InlineKeyboardButton("2️⃣ Второе напоминание", callback_data="set_remind_second")],
            [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
        ]),
    )


async def handle_toggle_remind(query):
    cfg = load_config()
    cfg["remind_enabled"] = not cfg.get("remind_enabled", True)
    save_config(cfg)
    await handle_remind_settings(query)


async def handle_set_remind(query, context: ContextTypes.DEFAULT_TYPE, which: str):
    from states import AWAITING_REMIND_FIRST, AWAITING_REMIND_SECOND
    context.user_data["state"] = (AWAITING_REMIND_FIRST if which == "first"
                                  else AWAITING_REMIND_SECOND)
    num = "Первое" if which == "first" else "Второе"
    await query.edit_message_text(
        f"⏰ <b>{num} напоминание</b>\n\n"
        "За сколько до конца периода писать?\n"
        "Примеры: <code>3 дня</code>, <code>12 часов</code>, <code>0</code> — выключить.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="remind_settings")],
        ]),
    )


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


# ── Написать юзеру ─────────────────────────────────────────────────────────

async def handle_dm_user(query, tg_id: int, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_DM_USER
    context.user_data["dm_target"] = tg_id
    from html import escape
    from database import get_user_info
    u = await get_user_info(tg_id)
    name = escape(str(u[1] if u else tg_id))
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
