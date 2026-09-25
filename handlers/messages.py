from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID, load_config, save_config
from database import add_support_message, get_support_messages
from keyboards import back_admin, support_keyboard
from states import (
    AWAITING_CHANNEL, AWAITING_BROADCAST, AWAITING_BROADCAST_BUTTONS, AWAITING_BROADCAST_PHOTO,
    AWAITING_SUPPORT_MSG, AWAITING_ADMIN_REPLY,
    AWAITING_PRIVACY_URL, AWAITING_TERMS_URL,
    AWAITING_XUI_URL, AWAITING_XUI_TOKEN,
    AWAITING_XUI_SUB_PORT, AWAITING_XUI_SUB_PATH,
    AWAITING_PRESET_EXPIRE, AWAITING_PRESET_IP,
    AWAITING_PRESET_HWID, AWAITING_PRESET_TRAFFIC,
    AWAITING_SUB_TG_ID, AWAITING_AUTO_UPDATE_DAYS,
    AWAITING_SUB_EDIT_EXPIRE, AWAITING_SUB_EDIT_IP,
    AWAITING_SUB_EDIT_HWID, AWAITING_SUB_EDIT_TRAFFIC,
    AWAITING_PAID_SUB_TG_ID,
    AWAITING_PAID_PRESET_IP, AWAITING_PAID_PRESET_HWID,
    AWAITING_PAID_PRESET_TRAFFIC,
    AWAITING_PAID_TRIAL_PERIOD, AWAITING_PAID_PAY_PERIOD,
    AWAITING_PAID_RENEW_TIME, AWAITING_PAID_PRICE, AWAITING_PAID_PAY_URL,
    AWAITING_PAID_SUB_EXTEND,
    AWAITING_PAID_SUB_EDIT_EXPIRE, AWAITING_PAID_SUB_EDIT_IP,
    AWAITING_PAID_SUB_EDIT_HWID, AWAITING_PAID_SUB_EDIT_TRAFFIC,
    AWAITING_PAID_SUB_EDIT_TRIAL, AWAITING_PAID_SUB_EDIT_PAY_PERIOD,
    AWAITING_PAID_SUB_EDIT_RENEW_TIME, AWAITING_PAID_SUB_EDIT_PRICE,
    AWAITING_PAID_SUB_EDIT_PAY_URL, AWAITING_PAID_MUTE_USER,
    AWAITING_PAID_AUTO_UPDATE_DAYS,
    AWAITING_REFERRAL_BONUS, AWAITING_REFERRAL_INVITED_BONUS,
    AWAITING_PAID_SUB_REDUCE,
    AWAITING_PAID_BULK_EXTEND, AWAITING_PAID_BULK_REDUCE, AWAITING_PAID_FIX_RENEW,
    AWAITING_PAID_BULK_IP, AWAITING_PAID_BULK_HWID,
    AWAITING_DEVICE_PRICE, AWAITING_DEVICE_MAX,
    AWAITING_PROMO_CODE, AWAITING_PROMO_NEW_CODE,
    AWAITING_PROMO_NEW_PERCENT, AWAITING_PROMO_NEW_EXPIRE,
    AWAITING_FIND_USER, AWAITING_LOG_CHANNEL,
    AWAITING_WINBACK_DAYS, AWAITING_WINBACK_PERCENT,
    AWAITING_REMIND_FIRST, AWAITING_REMIND_SECOND, AWAITING_QUICK_REPLY,
    AWAITING_SITE_HOST, AWAITING_SITE_USER, AWAITING_SITE_PASS,
    AWAITING_SITE_DOMAIN, AWAITING_SITE_LOGO, AWAITING_BACKUP_FILE,
    AWAITING_DM_USER,
    AWAITING_PLATEGA_MERCHANT, AWAITING_PLATEGA_SECRET,
    AWAITING_TARIFF_NAME, AWAITING_TARIFF_PERIOD, AWAITING_TARIFF_PRICE,
    AWAITING_TARIFF_EDIT_NAME, AWAITING_TARIFF_EDIT_PERIOD, AWAITING_TARIFF_EDIT_PRICE,
    AWAITING_NODE_HOST, AWAITING_MAINTENANCE_TEXT, AWAITING_HELPER_ID,
    AWAITING_BL_ADD, AWAITING_BL_REASON, AWAITING_BL_CHECK,
    AWAITING_PROMO_GIVE_USER, AWAITING_PROMO_CUSTOM,
)


def _save(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user = update.effective_user
    text = update.message.text.strip()
    is_admin = user.id == ADMIN_ID
    # Ввод помощника: ответ в тикет, поиск юзера, сообщение юзеру
    from staff import HELPER_STATES, is_helper, staff_chat_ids
    helper_input = state in HELPER_STATES and not is_admin
    if helper_input and not is_helper(user.id):
        # доступ сняли, пока ввод был не закончен
        context.user_data.pop("state", None)
        state, helper_input = None, False

    # ── Техработы и выключенные функции ─────────────────────────────────────
    if not is_admin and not helper_input:
        import maintenance as mnt
        if mnt.is_maintenance():
            context.user_data.pop("state", None)
            await mnt.show_maintenance(message=update.message)
            return
        blocked = {AWAITING_SUPPORT_MSG: "support", AWAITING_PROMO_CODE: "payments"}.get(state)
        if blocked and not mnt.feature_enabled(blocked):
            context.user_data.pop("state", None)
            await mnt.show_feature_off(blocked, message=update.message)
            return

    # ── Юзер пишет в поддержку ───────────────────────────────────────────────
    if state == AWAITING_SUPPORT_MSG and not is_admin:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from database import get_unread_tickets_count, ticket_opened, count_support_files
        from handlers.support import topic_label
        topic = context.user_data.pop("support_topic", None)
        await add_support_message(user.id, text, from_admin=False)
        await ticket_opened(user.id, topic)
        _, total_pages = await get_support_messages(user.id)
        has_files = (await count_support_files(user.id)) > 0
        await update.message.reply_text(
            "✅ <b>Сообщение отправлено</b>\n\n"
            "<i>Ответим здесь, в боте — уведомление придёт само.</i>",
            parse_mode="HTML",
            reply_markup=support_keyboard(total_pages, total_pages, has_files),
        )
        from html import escape
        from log_channel import send_log
        # имя и текст пишет человек: «<» без экранирования срывает отправку целиком
        who = escape(str(user.first_name or user.id))
        await send_log(context.bot,
            f"📩 Обращение в поддержку: {who} (<code>{user.id}</code>)"
        )
        uname = escape(f"@{user.username}" if user.username else f"id{user.id}")
        unread = await get_unread_tickets_count()
        preview = escape(text if len(text) <= 500 else text[:500] + "…")
        # админу и помощникам: если кто-то заблокировал бота, остальным всё равно дойдёт
        for chat_id in staff_chat_ids():
            if chat_id == user.id:
                continue
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"📩 <b>Новое обращение</b>\n\n"
                        f'👤 <a href="tg://user?id={user.id}">{who}</a> ({uname}) · <code>{user.id}</code>\n'
                        f"📌 {topic_label(topic or 'other')}  ·  🔴 открытых: <b>{unread}</b>\n\n"
                        f"<blockquote>{preview}</blockquote>"
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✏️ Ответить", callback_data=f"ticket_reply:{user.id}"),
                         InlineKeyboardButton("⚡ Шаблон", callback_data=f"ticket_quick:{user.id}")],
                        [InlineKeyboardButton("👀 Открыть переписку", callback_data=f"ticket_view:{user.id}:1")],
                    ]),
                )
            except Exception:
                pass
        return

    # ── Бан-чек ───────────────────────────────────────────────────────────────
    if not is_admin:
        from database import is_banned
        if await is_banned(user.id):
            await update.message.reply_text("🚫 Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return

    # ── Чёрный список: писать можно только в поддержку (она выше) ────────────
    if not is_admin and not helper_input:
        from blacklist import entry as bl_entry, show_blocked
        ble = await bl_entry(user.id)
        if ble:
            context.user_data.pop("state", None)
            await show_blocked(ble, message=update.message)
            return

    # ── Юзер вводит промокод ─────────────────────────────────────────────────
    if state == AWAITING_PROMO_CODE:
        from html import escape
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from paidsub.handlers import validate_promo
        from paidsub.storage import get_paid_sub_by_tg_id, update_paid_sub_field
        context.user_data.pop("state", None)
        code = text.strip().upper()
        row = await get_paid_sub_by_tg_id(user.id)
        if not row:
            await update.message.reply_text(
                "🎟 <b>Промокод не применён</b>\n\n"
                "<blockquote>Сначала нужна подписка — промокод действует на её оплату.</blockquote>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")]
                ]),
            )
            return
        promo, err = await validate_promo(code, user.id)
        if err:
            await update.message.reply_text(
                f"🎟 <b>Промокод не подошёл</b>\n\n<blockquote>{escape(str(err).lstrip('❌ '))}</blockquote>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎟 Ввести другой", callback_data="enter_promo"),
                     InlineKeyboardButton("◀️ К оплате", callback_data="renew_sub")],
                ]),
            )
            return
        kind = promo[8] if len(promo) > 8 else "percent"
        if kind == "days":
            # подарочные дни начисляем сразу — платить за них не нужно
            from paidsub.storage import record_promo_use
            from promos import apply_days
            days = promo[9] if len(promo) > 9 else 0
            res = await apply_days(user.id, days)
            if not res.get("ok"):
                await update.message.reply_text(
                    "😕 <b>Не получилось начислить дни</b>\n\n"
                    "<i>Промокод не сгорел — напишите в поддержку, начислим вручную.</i>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 Поддержка", callback_data="support_open")]
                    ]),
                )
                return
            await record_promo_use(promo[1], user.id)
            await update.message.reply_text(
                "🎁 <b>Подарок получен!</b>\n\n"
                f"<blockquote>➕ Начислено дней: <b>{days}</b>\n"
                f"📅 Подписка до: <b>{res['until']}</b></blockquote>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")]
                ]),
            )
            return
        await update_paid_sub_field(row[0], "pending_promo", promo[1])
        await update.message.reply_text(
            "✅ <b>Промокод применён</b>\n\n"
            f"<blockquote>🎟 {escape(str(promo[1]))}  ·  скидка <b>−{promo[2]}%</b></blockquote>\n\n"
            "<i>Скидка уже учтена в цене — выберите тариф.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 К оплате", callback_data="renew_sub")]
            ]),
        )
        return

    # дальше только админ — и помощник со своим вводом (ответ, поиск, сообщение)
    if not is_admin and not helper_input:
        return

    # ══════════════════════════════════════════════════════════════════════════
    # АДМИН
    # ══════════════════════════════════════════════════════════════════════════

    if state == AWAITING_CHANNEL:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        _channel_back = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Управление каналом", callback_data="channel_menu")]])
        if not text.startswith("http"):
            await update.message.reply_text("❌ Некорректная ссылка.", reply_markup=_channel_back)
            return
        _save("channel_url", text)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Канал сохранён: <code>{text}</code>", parse_mode="HTML", reply_markup=_channel_back)
        return

    # ── Рассылка: текст ─────────────────────────────────────────────────────
    if state == AWAITING_BROADCAST:
        from handlers.broadcast import extract_html, ask_photo
        context.user_data.pop("state", None)
        context.user_data["bcast_text"] = extract_html(update.message)
        await ask_photo(update.message, context)
        return

    # ── Рассылка: инлайн-кнопки ─────────────────────────────────────────────
    if state == AWAITING_BROADCAST_BUTTONS:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from handlers.broadcast import parse_buttons, show_preview, BUTTONS_HELP
        spec, err = parse_buttons(text)
        if err:
            await update.message.reply_text(
                f"❌ {err}\n\n{BUTTONS_HELP}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏭ Пропустить", callback_data="bcast_buttons_skip")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
                ]),
            )
            return
        context.user_data.pop("state", None)
        context.user_data["bcast_buttons"] = spec
        await show_preview(update.message, context)
        return

    if state == AWAITING_PRIVACY_URL:
        if not text.startswith("http"):
            await update.message.reply_text("❌ Некорректная ссылка.", reply_markup=back_admin())
            return
        _save("privacy_url", text)
        context.user_data.pop("state", None)
        await update.message.reply_text("✅ Политика сохранена.", reply_markup=back_admin())
        return

    if state == AWAITING_TERMS_URL:
        if not text.startswith("http"):
            await update.message.reply_text("❌ Некорректная ссылка.", reply_markup=back_admin())
            return
        _save("terms_url", text)
        context.user_data.pop("state", None)
        await update.message.reply_text("✅ Соглашение сохранено.", reply_markup=back_admin())
        return

    if state == AWAITING_ADMIN_REPLY:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        reply_to = context.user_data.pop("reply_to", None)
        context.user_data.pop("state", None)
        if not reply_to:
            await update.message.reply_text("❌ Пользователь не найден.", reply_markup=back_admin())
            return
        await add_support_message(reply_to, text, from_admin=True)
        from database import ticket_answered
        await ticket_answered(reply_to)
        delivered = True
        try:
            await context.bot.send_message(
                chat_id=reply_to,
                text=f"🛡 <b>Поддержка ответила</b>\n\n<blockquote>{text}</blockquote>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "💬 Открыть переписку", callback_data="support_open")]]),
            )
        except Exception:
            delivered = False
        status_line = "✅ Ответ отправлен." if delivered else "⚠️ Ответ сохранён, но не доставлен (юзер заблокировал бота)."
        await update.message.reply_text(
            status_line,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Ещё ответить", callback_data=f"ticket_reply:{reply_to}")],
                [InlineKeyboardButton("👀 Открыть переписку", callback_data=f"ticket_view:{reply_to}:1")],
                [InlineKeyboardButton("◀️ К тикетам", callback_data="ticket_list:1")],
            ]),
        )
        return

    # ── 3x-UI ─────────────────────────────────────────────────────────────────
    if state == AWAITING_XUI_URL:
        if not text.startswith("http"):
            await update.message.reply_text("❌ URL должен начинаться с http.", reply_markup=back_admin())
            return
        _save("xui_url", text.rstrip("/"))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ URL сохранён: <code>{text}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_XUI_TOKEN:
        _save("xui_token", text)
        context.user_data.pop("state", None)
        await update.message.reply_text("✅ Токен сохранён.", reply_markup=back_admin())
        return

    if state == AWAITING_XUI_SUB_PORT:
        if not text.isdigit():
            await update.message.reply_text("❌ Порт — только число.", reply_markup=back_admin())
            return
        _save("xui_sub_port", text)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Порт: <code>{text}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_XUI_SUB_PATH:
        path = text if text.startswith("/") else f"/{text}"
        path = path if path.endswith("/") else f"{path}/"
        _save("xui_sub_path", path)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Путь: <code>{path}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Авто-обновление: интервал дней ───────────────────────────────────────────
    if state == AWAITING_AUTO_UPDATE_DAYS:
        if not text.isdigit() or int(text) < 1:
            await update.message.reply_text("❌ Введи целое число дней (минимум 1):", reply_markup=back_admin())
            return
        _save("auto_update_days", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Интервал: <b>{text} дн.</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Создание подписки: TG ID ─────────────────────────────────────────────────
    if state == AWAITING_SUB_TG_ID:
        if not text.isdigit():
            await update.message.reply_text(
                "❌ TG ID — это число. Попробуй ещё раз:", reply_markup=back_admin()
            )
            return
        tg_id = int(text)
        context.user_data.pop("state", None)
        from adminsub.handlers import do_create_sub
        sent = await update.message.reply_text("⏳ Создаю подписку...")

        async def _edit(txt, **kw):
            await sent.edit_text(txt, reply_markup=back_admin(), **kw)

        await do_create_sub(sent, tg_id, context, _edit)
        return

    # ── Пресеты подписок ──────────────────────────────────────────────────────
    if state == AWAITING_PRESET_EXPIRE:
        try:
            datetime.strptime(text, "%d.%m.%Y")
        except ValueError:
            await update.message.reply_text("❌ Формат: <code>дд.мм.гггг</code>", parse_mode="HTML", reply_markup=back_admin())
            return
        _save("preset_expire", text)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Дата окончания: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PRESET_IP:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        _save("preset_ip", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Лимит IP: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PRESET_HWID:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        _save("preset_hwid", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Лимит HWID: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PRESET_TRAFFIC:
        if text == "-":
            val = 0
            label = "безлимит"
        elif text.isdigit():
            val = int(text)
            label = f"{val} ГБ" if val > 0 else "безлимит"
        else:
            await update.message.reply_text("❌ Число ГБ или <code>-</code>", parse_mode="HTML", reply_markup=back_admin())
            return
        _save("preset_traffic", val)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Трафик: <b>{label}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Редактирование конкретной админской подписки ────────────────────────────
    if state == AWAITING_SUB_EDIT_EXPIRE:
        try:
            datetime.strptime(text, "%d.%m.%Y")
        except ValueError:
            await update.message.reply_text("❌ Формат: <code>дд.мм.гггг</code>", parse_mode="HTML", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from adminsub.storage import update_sub_field
            await update_sub_field(sub_id, "expire_date", text)
        await update.message.reply_text(f"✅ Дата окончания обновлена: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_SUB_EDIT_IP:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from adminsub.storage import update_sub_field
            await update_sub_field(sub_id, "limit_ip", int(text))
        await update.message.reply_text(f"✅ Лимит IP обновлён: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_SUB_EDIT_HWID:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from adminsub.storage import update_sub_field
            await update_sub_field(sub_id, "limit_hwid", int(text))
        await update.message.reply_text(f"✅ Лимит HWID обновлён: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_SUB_EDIT_TRAFFIC:
        if text == "-":
            val = 0
            label = "безлимит"
        elif text.isdigit():
            val = int(text)
            label = f"{val} ГБ" if val > 0 else "безлимит"
        else:
            await update.message.reply_text("❌ Число ГБ или <code>-</code>", parse_mode="HTML", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from adminsub.storage import update_sub_field
            await update_sub_field(sub_id, "total_gb", val)
        await update.message.reply_text(f"✅ Трафик обновлён: <b>{label}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Платные подписки: TG ID ──────────────────────────────────────────────────
    if state == AWAITING_PAID_SUB_TG_ID:
        if not text.isdigit():
            await update.message.reply_text(
                "❌ TG ID — это число. Попробуй ещё раз:", reply_markup=back_admin()
            )
            return
        tg_id = int(text)
        context.user_data.pop("state", None)
        trial = context.user_data.pop("create_trial", False)
        from paidsub.handlers import do_create_paid_sub
        sent = await update.message.reply_text("⏳ Создаю подписку...")

        async def _edit_paid(txt, **kw):
            await sent.edit_text(txt, reply_markup=back_admin(), **kw)

        await do_create_paid_sub(sent, tg_id, context, _edit_paid, trial=trial)
        return

    # ── Платные подписки: время-пресеты ──────────────────────────────────────────
    from paidsub.time_parser import parse_duration, fmt_duration

    if state == AWAITING_PAID_TRIAL_PERIOD:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        _save("paid_trial_period", seconds)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Пробный период: <b>{fmt_duration(seconds)}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_PAY_PERIOD:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>30 дней</code>, <code>1 месяц</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        _save("paid_pay_period", seconds)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Период оплаты: <b>{fmt_duration(seconds)}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_RENEW_TIME:
        # Ноль выключает окно: продлить можно в любой момент,
        # а остаток срока при оплате не сгорает
        seconds = 0 if text.strip().lower() in ("0", "выкл", "нет", "off") else parse_duration(text)
        if seconds is None:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>3 дня</code>, <code>12 часов</code>, <code>0</code> — выключить.",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        _save("paid_renew_time", seconds)
        context.user_data.pop("state", None)
        from paidsub.handlers import renew_label
        await update.message.reply_text(f"✅ Время на продление: <b>{renew_label(seconds)}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state in (AWAITING_REMIND_FIRST, AWAITING_REMIND_SECOND):
        # ноль выключает конкретное напоминание, остальное — обычный срок
        seconds = 0 if text.strip().lower() in ("0", "выкл", "нет", "off") else parse_duration(text)
        if seconds is None:
            await update.message.reply_text(
                "❌ Не разобрал. Примеры: <code>3 дня</code>, <code>12 часов</code>, <code>0</code> — выключить.",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        key = "remind_first" if state == AWAITING_REMIND_FIRST else "remind_second"
        _save(key, seconds)
        context.user_data.pop("state", None)
        await update.message.reply_text(
            "✅ Напоминание: <b>"
            + (f"за {fmt_duration(seconds)}" if seconds else "выключено") + "</b>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    if state == AWAITING_SITE_LOGO:
        await update.message.reply_text("🖼 Пришли картинку файлом или фото.")
        return

    if state == AWAITING_BACKUP_FILE:
        await update.message.reply_text("📥 Пришли файл .zip с бэкапом.")
        return

    # ── Сайт на втором сервере: адрес, пользователь, пароль ──────────────────
    if state in (AWAITING_SITE_HOST, AWAITING_SITE_USER, AWAITING_SITE_PASS,
                 AWAITING_SITE_DOMAIN):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from html import escape
        from site_deploy import save_creds, check_connection
        back = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")]])

        if state == AWAITING_SITE_HOST:
            host, _, port = text.strip().replace("http://", "").strip("/").partition(":")
            if not host:
                await update.message.reply_text("❌ Пришли IP сервера.", reply_markup=back)
                return
            save_creds(site_host=host, site_port=int(port) if port.isdigit() else 22)
            context.user_data["state"] = AWAITING_SITE_USER
            await update.message.reply_text(
                "🖥 <b>Шаг 2 из 3</b>\n\nИмя пользователя — обычно <code>root</code>.",
                parse_mode="HTML", reply_markup=back)
            return

        if state == AWAITING_SITE_USER:
            save_creds(site_user=text.strip() or "root")
            context.user_data["state"] = AWAITING_SITE_PASS
            await update.message.reply_text(
                "🖥 <b>Шаг 3 из 3</b>\n\nПароль от сервера.\n"
                "<i>Сообщение с паролем удалю сразу после сохранения.</i>",
                parse_mode="HTML", reply_markup=back)
            return

        if state == AWAITING_SITE_PASS:
            save_creds(site_pass=text)
            context.user_data.pop("state", None)
            # пароль не должен остаться в переписке
            try:
                await update.message.delete()
            except Exception:
                pass
            note = await update.message.reply_text("🔌 Проверяю подключение…")
            res = await check_connection()
            if res.get("ok"):
                body = ("✅ <b>Сервер на связи</b>\n\n"
                        f"🖥 {escape(str(res.get('host', '?')))}\n"
                        f"💿 {escape(str(res.get('os', '?')))}\n\n"
                        "Теперь можно разворачивать сайт.")
            else:
                body = ("❌ <b>Не подключиться</b>\n\n"
                        f"<code>{escape(str(res.get('error'))[:300])}</code>\n\n"
                        "Проверь IP, пользователя и пароль.")
            await note.edit_text(body, parse_mode="HTML", reply_markup=back)
            return

        domain = text.strip().lower().replace("https://", "").replace("http://", "").strip("/")
        save_creds(site_domain="" if domain == "-" else domain, site_https=False)
        context.user_data.pop("state", None)
        await update.message.reply_text(
            "🌍 Домен убран." if domain == "-" else f"🌍 Домен: <b>{escape(domain)}</b>",
            parse_mode="HTML", reply_markup=back)
        return

    if state == AWAITING_QUICK_REPLY:
        from handlers.tickets import quick_replies, save_quick
        items = quick_replies()
        items.append(text)
        save_quick(items)
        context.user_data.pop("state", None)
        from html import escape as _esc
        await update.message.reply_text(
            f"✅ Шаблон добавлен:\n\n<i>{_esc(text)}</i>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    if state == AWAITING_PAID_PRICE:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число (сумма в рублях).", reply_markup=back_admin())
            return
        _save("paid_price", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Сумма: <b>{text} ₽</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_PAY_URL:
        if not text.startswith("http"):
            await update.message.reply_text("❌ Ссылка должна начинаться с http.", reply_markup=back_admin())
            return
        _save("paid_pay_url", text)
        context.user_data.pop("state", None)
        await update.message.reply_text("✅ Ссылка на оплату сохранена.", reply_markup=back_admin())
        return

    # ── Платные подписки: обычные пресеты ────────────────────────────────────────
    if state == AWAITING_PAID_PRESET_IP:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        _save("paid_preset_ip", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Лимит IP: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_PRESET_HWID:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        _save("paid_preset_hwid", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Лимит HWID: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_PRESET_TRAFFIC:
        if text == "-":
            val = 0
            label = "безлимит"
        elif text.isdigit():
            val = int(text)
            label = f"{val} ГБ" if val > 0 else "безлимит"
        else:
            await update.message.reply_text("❌ Число ГБ или <code>-</code>", parse_mode="HTML", reply_markup=back_admin())
            return
        _save("paid_preset_traffic", val)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Трафик: <b>{label}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Платные подписки: продление срока ────────────────────────────────────────
    if state == AWAITING_PAID_SUB_EXTEND:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>5 часов</code>, <code>7 дней</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import get_paid_sub, update_paid_sub_field
            row = await get_paid_sub(sub_id)
            if row:
                expire_str = row[6]
                for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                    try:
                        expire_dt = datetime.strptime(expire_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    expire_dt = datetime.now()
                if expire_dt < datetime.now():
                    expire_dt = datetime.now()
                new_expire = expire_dt + timedelta(seconds=seconds)
                new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")
                from paidsub.storage import set_expire_date
                await set_expire_date(sub_id, new_expire_str)
                await update_paid_sub_field(sub_id, "status", "active")
                from xui_api import update_client_expire, toggle_client, get_client_info, move_client_inbound
                await update_client_expire(row[2], new_expire_str)
                info = await get_client_info(row[2])
                if info.get("success") and not info.get("enabled", True):
                    await toggle_client(row[2], True)
                cfg = load_config()
                create_inbound_ids = cfg.get("paid_preset_inbound_ids") or []
                if create_inbound_ids:
                    await move_client_inbound(row[2], create_inbound_ids)
                from paidsub.time_parser import fmt_duration as fmt_dur
                await update.message.reply_text(
                    f"✅ Срок продлён на <b>{fmt_dur(seconds)}</b>\n"
                    f"📅 Новая дата: <b>{new_expire_str}</b>",
                    parse_mode="HTML", reply_markup=back_admin(),
                )
                tg_id = row[1]
                from paidsub.storage import add_history
                await add_history(
                    tg_id, "sub_extended",
                    f"Подписка #{sub_id} ({row[2]})\n"
                    f"Добавлено: {fmt_dur(seconds)}\nНовая дата: {new_expire_str}",
                )
                if tg_id:
                    try:
                        await context.bot.send_message(
                            chat_id=tg_id,
                            text=(
                                f"🎉 <b>Ваша подписка продлена!</b>\n\n"
                                f"➕ Добавлено: <b>{fmt_dur(seconds)}</b>\n"
                                f"📅 Действует до: <b>{new_expire_str}</b>"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                return
        await update.message.reply_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return

    # ── Платные подписки: убавить срок ───────────────────────────────────────────
    if state == AWAITING_PAID_SUB_REDUCE:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>5 часов</code>, <code>7 дней</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import get_paid_sub, update_paid_sub_field
            row = await get_paid_sub(sub_id)
            if row:
                expire_str = row[6]
                for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                    try:
                        expire_dt = datetime.strptime(expire_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    expire_dt = datetime.now()
                new_expire = expire_dt - timedelta(seconds=seconds)
                new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")
                from paidsub.storage import set_expire_date
                await set_expire_date(sub_id, new_expire_str)
                from xui_api import update_client_expire
                await update_client_expire(row[2], new_expire_str)
                from paidsub.time_parser import fmt_duration as fmt_dur
                await update.message.reply_text(
                    f"✅ Срок убавлен на <b>{fmt_dur(seconds)}</b>\n"
                    f"📅 Новая дата: <b>{new_expire_str}</b>",
                    parse_mode="HTML", reply_markup=back_admin(),
                )
                tg_id = row[1]
                from paidsub.storage import add_history
                await add_history(
                    tg_id, "sub_reduced",
                    f"Подписка #{sub_id} ({row[2]})\n"
                    f"Убавлено: {fmt_dur(seconds)}\nНовая дата: {new_expire_str}",
                )
                if tg_id:
                    try:
                        await context.bot.send_message(
                            chat_id=tg_id,
                            text=(
                                f"ℹ️ <b>Срок вашей подписки изменён.</b>\n\n"
                                f"➖ Убавлено: <b>{fmt_dur(seconds)}</b>\n"
                                f"📅 Действует до: <b>{new_expire_str}</b>"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                return
        await update.message.reply_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return

    # ── Починка окна оплаты ──────────────────────────────────────────────────
    if state == AWAITING_PAID_FIX_RENEW:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>1 день</code>, <code>12 часов</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        context.user_data.pop("state", None)
        from paidsub.handlers import preview_fix_renew
        await preview_fix_renew(update.message, context, seconds)
        return

    # ── Платные подписки: массовое добавление/убавление срока ─────────────────────
    if state in (AWAITING_PAID_BULK_EXTEND, AWAITING_PAID_BULK_REDUCE):
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>5 часов</code>, <code>7 дней</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        direction = 1 if state == AWAITING_PAID_BULK_EXTEND else -1
        context.user_data.pop("state", None)
        # меняет срок всем сразу — сначала спрашиваем, применяем после «Да»
        context.user_data["bulk_pending"] = {"seconds": seconds, "direction": direction}
        from paidsub.storage import count_paid_subs
        from paidsub.time_parser import fmt_duration as fmt_dur
        from handlers.confirm import confirm_keyboard
        total = await count_paid_subs()
        if direction > 0:
            question = (
                f"➕ <b>Добавить {fmt_dur(seconds)} всем подпискам?</b>\n\n"
                f"Затронет подписок: <b>{total}</b> — все, включая истёкшие: они снова включатся.\n"
                "Каждому клиенту придёт уведомление."
            )
            yes = "➕ Да, добавить всем"
        else:
            question = (
                f"➖ <b>Убавить {fmt_dur(seconds)} у всех подписок?</b>\n\n"
                f"Затронет подписок: <b>{total}</b>. У кого срок уйдёт в прошлое — подписка закончится."
            )
            yes = "➖ Да, убавить всем"
        await update.message.reply_text(
            question, parse_mode="HTML",
            reply_markup=confirm_keyboard(yes, "paid_bulk_apply", "paid_bulk_menu", "paid_subs"),
        )
        return

    # ── Платные подписки: индивидуальные настройки ──────────────────────────────
    if state == AWAITING_PAID_SUB_EDIT_EXPIRE:
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            await update.message.reply_text(
                "❌ Формат: <code>дд.мм.гггг</code>, <code>дд.мм.гггг чч:мм</code> или <code>дд.мм.гггг чч:мм:сс</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field, get_paid_sub, set_expire_date
            await set_expire_date(sub_id, text)
            await update_paid_sub_field(sub_id, "status", "active")
            r = await get_paid_sub(sub_id)
            if r:
                from xui_api import update_client_expire
                await update_client_expire(r[2], text)
                from paidsub.storage import add_history
                await add_history(r[1], "settings_changed", f"Подписка #{sub_id}: дата окончания → {text}")
        await update.message.reply_text(f"✅ Дата окончания обновлена: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state in (AWAITING_DEVICE_PRICE, AWAITING_DEVICE_MAX):
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        context.user_data.pop("state", None)
        if state == AWAITING_DEVICE_PRICE:
            _save("device_price", int(text))
            off = " — докуп выключен" if not int(text) else ""
            await update.message.reply_text(
                f"✅ Цена устройства: <b>{text} ₽</b>{off}",
                parse_mode="HTML", reply_markup=back_admin())
        else:
            _save("device_max_extra", int(text))
            await update.message.reply_text(
                f"✅ Максимум докупа: <b>{text}</b> устройств",
                parse_mode="HTML", reply_markup=back_admin())
        return

    if state in (AWAITING_PAID_BULK_IP, AWAITING_PAID_BULK_HWID):
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число. <code>0</code> — без ограничения.",
                                            parse_mode="HTML", reply_markup=back_admin())
            return
        kind = "ip" if state == AWAITING_PAID_BULK_IP else "hwid"
        context.user_data.pop("state", None)
        from paidsub.handlers import preview_bulk_limits
        await preview_bulk_limits(update.message, context, kind, int(text))
        return

    if state == AWAITING_PAID_SUB_EDIT_IP:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        panel_note = ""
        if sub_id:
            from paidsub.storage import update_paid_sub_field, get_paid_sub, add_history
            from xui_api import update_client_limits
            await update_paid_sub_field(sub_id, "limit_ip", int(text))
            r = await get_paid_sub(sub_id)
            if r:
                # без этого лимит менялся только в базе, а панель жила со старым
                res = await update_client_limits(r[2], limit_ip=int(text))
                if not res.get("success"):
                    panel_note = f"\n⚠️ Панель не приняла: <code>{res.get('error', '?')}</code>"
                await add_history(r[1], "settings_changed", f"Подписка #{sub_id}: лимит IP → {text}")
        await update.message.reply_text(f"✅ Лимит IP обновлён: <b>{text}</b>{panel_note}",
                                        parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_SUB_EDIT_HWID:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        panel_note = ""
        if sub_id:
            from paidsub.storage import (update_paid_sub_field, get_paid_sub,
                                         add_history, get_paid_sub_by_tg_id)
            from xui_api import update_client_limits
            r = await get_paid_sub(sub_id)
            # оплаченные устройства идут сверх лимита, который ставит админ
            extra = 0
            if r and r[1]:
                by_tg = await get_paid_sub_by_tg_id(r[1])
                extra = int(by_tg[18] or 0) if by_tg and len(by_tg) > 18 else 0
            target = int(text) + extra if int(text) else 0
            await update_paid_sub_field(sub_id, "limit_hwid", target)
            if r:
                res = await update_client_limits(r[2], limit_hwid=target)
                if not res.get("success"):
                    panel_note = f"\n⚠️ Панель не приняла: <code>{res.get('error', '?')}</code>"
                if extra and target:
                    panel_note = f"\n📱 Плюс оплаченные устройства: <b>+{extra}</b>" + panel_note
                await add_history(r[1], "settings_changed",
                                  f"Подписка #{sub_id}: лимит HWID → {target}")
        await update.message.reply_text(f"✅ Лимит HWID обновлён: <b>{text}</b>{panel_note}",
                                        parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_SUB_EDIT_TRAFFIC:
        if text == "-":
            val = 0
            label = "безлимит"
        elif text.isdigit():
            val = int(text)
            label = f"{val} ГБ" if val > 0 else "безлимит"
        else:
            await update.message.reply_text("❌ Число ГБ или <code>-</code>", parse_mode="HTML", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field, get_paid_sub, add_history
            await update_paid_sub_field(sub_id, "total_gb", val)
            r = await get_paid_sub(sub_id)
            if r:
                await add_history(r[1], "settings_changed", f"Подписка #{sub_id}: трафик → {label}")
        await update.message.reply_text(f"✅ Трафик обновлён: <b>{label}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Платные подписки: индивидуальные время-настройки ─────────────────────────
    if state == AWAITING_PAID_SUB_EDIT_TRIAL:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>5 часов</code>, <code>7 дней</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field
            await update_paid_sub_field(sub_id, "ind_trial_period", seconds)
        from paidsub.time_parser import fmt_duration as fmt_dur
        await update.message.reply_text(f"✅ Пробный период: <b>{fmt_dur(seconds)}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_SUB_EDIT_PAY_PERIOD:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>30 дней</code>, <code>1 месяц</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field
            await update_paid_sub_field(sub_id, "ind_pay_period", seconds)
        from paidsub.time_parser import fmt_duration as fmt_dur
        await update.message.reply_text(f"✅ Период оплаты: <b>{fmt_dur(seconds)}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_SUB_EDIT_RENEW_TIME:
        seconds = 0 if text.strip().lower() in ("0", "выкл", "нет", "off") else parse_duration(text)
        if seconds is None:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>3 дня</code>, <code>12 часов</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        from paidsub.time_parser import fmt_duration as fmt_dur
        note = ""
        if sub_id:
            from paidsub.storage import update_paid_sub_field, get_paid_sub, sub_settings, add_history
            row = await get_paid_sub(sub_id)
            if row:
                old_renew = sub_settings(row)["renew_time"]
                await update_paid_sub_field(sub_id, "ind_renew_time", seconds)
                # expire_date = конец периода + время на оплату. Сам пробный/оплаченный
                # период трогать нельзя, поэтому сдвигаем только окно оплаты.
                expire_dt = None
                for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                    try:
                        expire_dt = datetime.strptime(row[6], fmt)
                        break
                    except ValueError:
                        continue
                if expire_dt:
                    period_end = expire_dt - timedelta(seconds=old_renew)
                    new_expire = period_end + timedelta(seconds=seconds)
                    new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")
                    await update_paid_sub_field(sub_id, "expire_date", new_expire_str)
                    from xui_api import update_client_expire
                    await update_client_expire(row[2], new_expire_str)
                    note = (
                        f"\n📅 Период заканчивается: <b>{period_end.strftime('%d.%m.%Y %H:%M:%S')}</b>\n"
                        f"⏳ Оплатить до: <b>{new_expire_str}</b>"
                    )
                    await add_history(
                        row[1], "settings_changed",
                        f"Подписка #{sub_id}: время на оплату → {fmt_dur(seconds)}\n"
                        f"Оплатить до: {new_expire_str}",
                    )
            else:
                await update_paid_sub_field(sub_id, "ind_renew_time", seconds)
        from paidsub.handlers import renew_label
        await update.message.reply_text(
            f"✅ Время на продление: <b>{renew_label(seconds)}</b>{note}",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    if state == AWAITING_PAID_SUB_EDIT_PRICE:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число (сумма в рублях).", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field
            await update_paid_sub_field(sub_id, "ind_price", int(text))
        await update.message.reply_text(f"✅ Сумма: <b>{text} ₽</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_SUB_EDIT_PAY_URL:
        if not text.startswith("http"):
            await update.message.reply_text("❌ Ссылка должна начинаться с http.", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field
            await update_paid_sub_field(sub_id, "ind_pay_url", text)
        await update.message.reply_text("✅ Ссылка на оплату сохранена.", reply_markup=back_admin())
        return

    # ── Платные подписки: авто-обновление ников ──────────────────────────────────
    if state == AWAITING_PAID_AUTO_UPDATE_DAYS:
        if not text.isdigit() or int(text) < 1:
            await update.message.reply_text("❌ Введи целое число дней (минимум 1):", reply_markup=back_admin())
            return
        _save("paid_auto_update_days", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Интервал: <b>{text} дн.</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Реферальный бонус ───────────────────────────────────────────────────────
    if state == AWAITING_REFERRAL_BONUS:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>1 день</code>, <code>12 часов</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        _save("referral_bonus", seconds)
        context.user_data.pop("state", None)
        await update.message.reply_text(
            f"✅ Бонус за реферала: <b>{fmt_duration(seconds)}</b>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    if state == AWAITING_REFERRAL_INVITED_BONUS:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>1 день</code>, <code>12 часов</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        _save("referral_invited_bonus", seconds)
        context.user_data.pop("state", None)
        await update.message.reply_text(
            f"✅ Бонус приглашённому: <b>{fmt_duration(seconds)}</b>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    # ── Создание промокода ───────────────────────────────────────────────────────
    if state == AWAITING_PROMO_NEW_CODE:
        from paidsub.storage import get_promo
        code = text.strip().upper()
        if not code or len(code) > 32 or " " in code:
            await update.message.reply_text(
                "❌ Код без пробелов, до 32 символов. Попробуй ещё раз:",
                reply_markup=back_admin(),
            )
            return
        if await get_promo(code):
            await update.message.reply_text("❌ Такой промокод уже существует.", reply_markup=back_admin())
            return
        context.user_data["new_promo"] = {"code": code}
        context.user_data["state"] = AWAITING_PROMO_NEW_PERCENT
        await update.message.reply_text(
            f"🎟 Код: <b>{code}</b>\n\nТеперь введи размер скидки в % (число от 1 до 100):",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    if state == AWAITING_PROMO_NEW_PERCENT:
        if not text.isdigit() or not (1 <= int(text) <= 100):
            await update.message.reply_text("❌ Введи число от 1 до 100:", reply_markup=back_admin())
            return
        context.user_data.setdefault("new_promo", {})["percent"] = int(text)
        context.user_data["state"] = AWAITING_PROMO_NEW_EXPIRE
        await update.message.reply_text(
            f"💯 Скидка: <b>{text}%</b>\n\n"
            "Введи дату окончания действия промокода в формате <code>дд.мм.гггг</code>\n"
            "или отправь <code>-</code> — без срока действия:",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    if state == AWAITING_PROMO_NEW_EXPIRE:
        from paidsub.storage import create_promo
        expires_at = None
        if text.strip() != "-":
            try:
                datetime.strptime(text.strip(), "%d.%m.%Y")
                expires_at = text.strip()
            except ValueError:
                await update.message.reply_text(
                    "❌ Формат: <code>дд.мм.гггг</code> или <code>-</code>",
                    parse_mode="HTML", reply_markup=back_admin(),
                )
                return
        data = context.user_data.pop("new_promo", {})
        context.user_data.pop("state", None)
        code = data.get("code")
        percent = data.get("percent")
        if not code or not percent:
            await update.message.reply_text("❌ Данные потеряны, начни заново.", reply_markup=back_admin())
            return
        ok = await create_promo(code, percent, expires_at)
        if not ok:
            await update.message.reply_text("❌ Не удалось создать промокод.", reply_markup=back_admin())
            return
        exp_line = f"📅 Действует до: <b>{expires_at}</b>" if expires_at else "📅 Без срока действия"
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        await update.message.reply_text(
            f"✅ <b>Промокод создан!</b>\n\n"
            f"🎟 <b>{code}</b> · скидка <b>−{percent}%</b>\n{exp_line}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎟 К промокодам", callback_data="promo_menu")],
            ]),
        )
        return

    # ── Найти юзера ───────────────────────────────────────────────────────────
    if state == AWAITING_FIND_USER:
        if not text.isdigit():
            await update.message.reply_text("❌ TG ID — это число.", reply_markup=back_admin())
            return
        context.user_data.pop("state", None)
        from handlers.admin import handle_user_profile
        await handle_user_profile(update.message, int(text), edit=False)
        return

    # ── Новый помощник ────────────────────────────────────────────────────────
    if state == AWAITING_HELPER_ID and is_admin:
        from staff import handle_helper_input
        await handle_helper_input(update, context, text)
        return

    # ── Чёрный список: внести, причина, проверить ────────────────────────────
    if state in (AWAITING_BL_ADD, AWAITING_BL_REASON, AWAITING_BL_CHECK) and is_admin:
        from blacklist import handle_bl_input
        await handle_bl_input(update, context, state, text)
        return

    # ── Выдача промокода: кому и какая награда ───────────────────────────────
    if state in (AWAITING_PROMO_GIVE_USER, AWAITING_PROMO_CUSTOM) and is_admin:
        from promos import handle_promo_input
        await handle_promo_input(update, context, state, text)
        return

    # ── Лог-канал ────────────────────────────────────────────────────────────
    if state == AWAITING_LOG_CHANNEL:
        try:
            channel_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ Введи числовой ID (напр. -1001234567890).", reply_markup=back_admin())
            return
        _save("log_channel_id", channel_id)
        context.user_data.pop("state", None)
        try:
            await context.bot.send_message(chat_id=channel_id, text="✅ Лог-канал подключён!", parse_mode="HTML")
            await update.message.reply_text(f"✅ Лог-канал: <code>{channel_id}</code>", parse_mode="HTML", reply_markup=back_admin())
        except Exception as e:
            await update.message.reply_text(
                f"⚠️ ID сохранён (<code>{channel_id}</code>), но тестовое сообщение не отправлено.\n"
                f"Убедись, что бот — админ канала.\n\n<code>{e}</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
        return

    # ── Winback: дни ─────────────────────────────────────────────────────────
    if state == AWAITING_WINBACK_DAYS:
        if not text.isdigit() or int(text) < 1:
            await update.message.reply_text("❌ Введи целое число дней (минимум 1).", reply_markup=back_admin())
            return
        _save("winback_days", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Winback через <b>{text} дн.</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Winback: процент ─────────────────────────────────────────────────────
    if state == AWAITING_WINBACK_PERCENT:
        if not text.isdigit() or not (1 <= int(text) <= 100):
            await update.message.reply_text("❌ Введи число от 1 до 100.", reply_markup=back_admin())
            return
        _save("winback_percent", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Скидка Winback: <b>{text}%</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Адрес узла ───────────────────────────────────────────────────────────
    if state == AWAITING_MAINTENANCE_TEXT:
        from maintenance import apply_maintenance_text
        await apply_maintenance_text(update.message, context)
        return

    if state == AWAITING_NODE_HOST:
        from handlers.xui_settings import apply_node_host
        await apply_node_host(update.message, context, text)
        return

    # ── Тарифы ───────────────────────────────────────────────────────────────
    if state in (AWAITING_TARIFF_NAME, AWAITING_TARIFF_PERIOD, AWAITING_TARIFF_PRICE):
        from handlers.tariffs import apply_new_step
        context.user_data.pop("state", None)
        await apply_new_step(update.message, context, state, text)
        return

    if state in (AWAITING_TARIFF_EDIT_NAME, AWAITING_TARIFF_EDIT_PERIOD,
                 AWAITING_TARIFF_EDIT_PRICE):
        from handlers.tariffs import apply_edit
        await apply_edit(update.message, context, state, text)
        return

    # ── Ключи платёжной системы ──────────────────────────────────────────────
    if state in (AWAITING_PLATEGA_MERCHANT, AWAITING_PLATEGA_SECRET):
        context.user_data.pop("state", None)
        from handlers.payprovider import apply_credential
        field = ("platega_merchant_id" if state == AWAITING_PLATEGA_MERCHANT
                 else "platega_secret")
        await apply_credential(update.message, context, field, text)
        return

    # ── Сообщение юзеру из профиля ─────────────────────────────────────────────
    if state == AWAITING_DM_USER:
        dm_target = context.user_data.pop("dm_target", None)
        context.user_data.pop("state", None)
        if dm_target:
            try:
                await context.bot.send_message(
                    chat_id=dm_target,
                    text=f"📌 <b>Сообщение от Drebol VPN</b>\n\n<blockquote>{text}</blockquote>",
                    parse_mode="HTML",
                )
                from html import escape
                from log_channel import send_log
                await send_log(context.bot,
                    f"📌 Админ → <code>{dm_target}</code>: {escape(text[:100])}"
                )
                await update.message.reply_text(
                    f"✅ Сообщение отправлено пользователю <code>{dm_target}</code>.",
                    parse_mode="HTML", reply_markup=back_admin(),
                )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Не удалось отправить: <code>{e}</code>",
                    parse_mode="HTML", reply_markup=back_admin(),
                )
        return

    # ── Мьют пользователя (ставь в конец админских) ──────────────────────────────
    if state == AWAITING_PAID_MUTE_USER:
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>5 часов</code>, <code>7 дней</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        mute_tg_id = context.user_data.pop("mute_tg_id", None)
        context.user_data.pop("state", None)
        if mute_tg_id:
            from paidsub.storage import set_mute, add_history
            muted_until = (datetime.now() + timedelta(seconds=seconds)).strftime("%d.%m.%Y %H:%M:%S")
            await set_mute(mute_tg_id, muted_until)
            await add_history(
                mute_tg_id, "user_muted",
                f"Заглушён до {muted_until}\nСрок: {fmt_duration(seconds)}",
            )
            await update.message.reply_text(
                f"🔇 Пользователь <code>{mute_tg_id}</code> заглушён до <b>{muted_until}</b>\n"
                f"({fmt_duration(seconds)})",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        await update.message.reply_text("❌ Пользователь не найден.", reply_markup=back_admin())
        return


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user = update.effective_user
    is_admin = user.id == ADMIN_ID
    msg = update.message
    from staff import is_helper, staff_chat_ids
    helper_reply = state == AWAITING_ADMIN_REPLY and not is_admin
    if helper_reply and not is_helper(user.id):
        # доступ сняли, пока ответ был не закончен
        context.user_data.pop("state", None)
        state, helper_reply = None, False

    if not is_admin and not helper_reply:
        import maintenance as mnt
        if mnt.is_maintenance():
            context.user_data.pop("state", None)
            await mnt.show_maintenance(message=msg)
            return
        if state == AWAITING_SUPPORT_MSG and not mnt.feature_enabled("support"):
            context.user_data.pop("state", None)
            await mnt.show_feature_off("support", message=msg)
            return

    if msg.photo:
        file_id = msg.photo[-1].file_id
        file_type = "photo"
        fallback_label = "🖼 Фото"
    elif msg.document:
        file_id = msg.document.file_id
        file_type = "document"
        fname = msg.document.file_name or "файл"
        fallback_label = f"📎 {fname}"
    else:
        return

    caption = msg.caption or ""

    # ── Файл с бэкапом ──────────────────────────────────────────────────────
    if is_admin and state == AWAITING_BACKUP_FILE:
        from backup import offer_restore
        context.user_data.pop("state", None)
        if not msg.document:
            await msg.reply_text("📥 Пришли именно файл .zip, который выгружал бот.")
            return
        note = await msg.reply_text("📥 Проверяю архив…")
        tg_file = await context.bot.get_file(file_id)
        blob = bytes(await tg_file.download_as_bytearray())
        try:
            await note.delete()
        except Exception:
            pass
        await offer_restore(msg, context, blob)
        return

    # ── Логотип для сайта ───────────────────────────────────────────────────
    if is_admin and state == AWAITING_SITE_LOGO:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from site_deploy import process_logo, save_logo
        context.user_data.pop("state", None)
        tg_file = await context.bot.get_file(file_id)
        raw = bytes(await tg_file.download_as_bytearray())
        ready = process_logo(raw)
        save_logo(ready)
        await msg.reply_text(
            "🖼 <b>Логотип сохранён</b>\n\n"
            "Нажми «Обновить сайт» — он поедет на страницу.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить сайт", callback_data="site_deploy")],
                [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
            ]),
        )
        return

    # ── Картинка для рассылки ───────────────────────────────────────────────
    if is_admin and msg.photo and state in (AWAITING_BROADCAST_PHOTO, AWAITING_BROADCAST):
        from handlers.broadcast import accept_photo, accept_photo_with_text
        if state == AWAITING_BROADCAST_PHOTO:
            await accept_photo(msg, context)
        else:
            # фото прислали вместо текста — подпись станет текстом рассылки
            await accept_photo_with_text(msg, context)
        return

    # ── Юзер отправляет файл в поддержку ────────────────────────────────────
    if state == AWAITING_SUPPORT_MSG and not is_admin:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from database import get_unread_tickets_count, get_support_messages, count_support_files
        from database import ticket_opened
        text_to_save = caption if caption else fallback_label
        await add_support_message(user.id, text_to_save, from_admin=False,
                                  file_id=file_id, file_type=file_type)
        await ticket_opened(user.id, context.user_data.pop("support_topic", None))
        _, total_pages = await get_support_messages(user.id)
        has_files = (await count_support_files(user.id)) > 0
        await msg.reply_text(
            "✅ <b>Файл отправлен</b>\n\n"
            "<i>Ответим здесь, в боте — уведомление придёт само.</i>",
            parse_mode="HTML",
            reply_markup=support_keyboard(total_pages, total_pages, has_files),
        )
        from html import escape
        from log_channel import send_log
        # имя и подпись к файлу задаёт человек — экранируем, иначе уведомление не уйдёт
        who = escape(str(user.first_name or user.id))
        await send_log(context.bot,
            f"📩 Файл в поддержку: {who} (<code>{user.id}</code>) — {escape(fallback_label)}"
        )
        uname = escape(f"@{user.username}" if user.username else f"id{user.id}")
        unread = await get_unread_tickets_count()
        notice = (
            f"📩 <b>Файл в поддержку</b>\n\n"
            f'👤 <a href="tg://user?id={user.id}">{who}</a> ({uname}) · <code>{user.id}</code>\n'
            f"🔴 Открытых: <b>{unread}</b>"
            + (f"\n\n<blockquote>{escape(caption)}</blockquote>" if caption else "")
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Ответить", callback_data=f"ticket_reply:{user.id}")],
            [InlineKeyboardButton("👀 Открыть переписку", callback_data=f"ticket_view:{user.id}:1")],
        ])
        # админу и помощникам: если кто-то заблокировал бота, остальным всё равно дойдёт
        for chat_id in staff_chat_ids():
            if chat_id == user.id:
                continue
            try:
                if file_type == "photo":
                    await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=notice,
                                                 parse_mode="HTML", reply_markup=kb)
                else:
                    await context.bot.send_document(chat_id=chat_id, document=file_id, caption=notice,
                                                    parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass
        return

    # ── Админ отправляет файл как ответ ─────────────────────────────────────
    if state == AWAITING_ADMIN_REPLY and (is_admin or helper_reply):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        reply_to = context.user_data.pop("reply_to", None)
        context.user_data.pop("state", None)
        if not reply_to:
            await msg.reply_text("❌ Пользователь не найден.", reply_markup=back_admin())
            return
        text_to_save = caption if caption else fallback_label
        await add_support_message(reply_to, text_to_save, from_admin=True,
                                  file_id=file_id, file_type=file_type)
        from database import ticket_answered
        await ticket_answered(reply_to)
        delivered = True
        try:
            if file_type == "photo":
                await context.bot.send_photo(
                    chat_id=reply_to,
                    photo=file_id,
                    caption="🛡 <b>Поддержка ответила</b>" + (f"\n\n<blockquote>{caption}</blockquote>" if caption else ""),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "💬 Открыть переписку", callback_data="support_open")]]),
                )
            else:
                await context.bot.send_document(
                    chat_id=reply_to,
                    document=file_id,
                    caption="🛡 <b>Поддержка ответила</b>" + (f"\n\n<blockquote>{caption}</blockquote>" if caption else ""),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "💬 Открыть переписку", callback_data="support_open")]]),
                )
        except Exception:
            delivered = False
        status_line = "✅ Файл отправлен." if delivered else "⚠️ Файл сохранён, но не доставлен."
        await msg.reply_text(
            status_line,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Ещё ответить", callback_data=f"ticket_reply:{reply_to}")],
                [InlineKeyboardButton("👀 Открыть переписку", callback_data=f"ticket_view:{reply_to}:1")],
                [InlineKeyboardButton("◀️ К тикетам", callback_data="ticket_list:1")],
            ]),
        )
        return
