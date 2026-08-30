import subprocess
from telegram.ext import ContextTypes
from config import INSTALL_DIR, load_config
from keyboards import admin_keyboard, back_admin, documents_keyboard, channel_keyboard
from states import AWAITING_CHANNEL, AWAITING_PRIVACY_URL, AWAITING_TERMS_URL


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
