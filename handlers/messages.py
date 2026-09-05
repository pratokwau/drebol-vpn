from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID, load_config, save_config
from database import add_support_message, get_support_messages
from keyboards import back_admin, support_keyboard
from states import (
    AWAITING_CHANNEL, AWAITING_BROADCAST,
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
    AWAITING_PAID_BULK_EXTEND, AWAITING_PAID_BULK_REDUCE,
    AWAITING_PROMO_CODE, AWAITING_PROMO_NEW_CODE,
    AWAITING_PROMO_NEW_PERCENT, AWAITING_PROMO_NEW_EXPIRE,
    AWAITING_FIND_USER, AWAITING_LOG_CHANNEL,
    AWAITING_WINBACK_DAYS, AWAITING_WINBACK_PERCENT,
    AWAITING_REVIEW_DAYS, AWAITING_USER_REVIEW,
    AWAITING_DM_USER,
)
from handlers.broadcast import do_broadcast


def _save(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user = update.effective_user
    text = update.message.text.strip()
    is_admin = user.id == ADMIN_ID

    # ── Юзер пишет в поддержку ───────────────────────────────────────────────
    if state == AWAITING_SUPPORT_MSG and not is_admin:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from database import get_unread_tickets_count
        await add_support_message(user.id, text, from_admin=False)
        _, total_pages = await get_support_messages(user.id)
        await update.message.reply_text(
            "✅ Сообщение отправлено в поддержку! Мы ответим как можно скорее.",
            reply_markup=support_keyboard(total_pages, total_pages),
        )
        from log_channel import send_log
        await send_log(context.bot,
            f"📩 Обращение в поддержку: {user.first_name} (<code>{user.id}</code>)"
        )
        uname = f"@{user.username}" if user.username else f"id{user.id}"
        unread = await get_unread_tickets_count()
        preview = text if len(text) <= 500 else text[:500] + "…"
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"📩 <b>Новое обращение в поддержку</b>\n\n"
                f'👤 <a href="tg://user?id={user.id}">{user.first_name}</a> ({uname})\n'
                f"🆔 <code>{user.id}</code>\n"
                f"🔴 Всего непрочитанных тикетов: <b>{unread}</b>\n\n"
                f"💬 {preview}"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Ответить", callback_data=f"ticket_reply:{user.id}")],
                [InlineKeyboardButton("👀 Открыть переписку", callback_data=f"ticket_view:{user.id}:1")],
            ]),
        )
        return

    # ── Бан-чек ───────────────────────────────────────────────────────────────
    if not is_admin:
        from database import is_banned
        if await is_banned(user.id):
            await update.message.reply_text("🚫 Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return

    # ── Юзер пишет отзыв ────────────────────────────────────────────────────
    if state == AWAITING_USER_REVIEW:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from database import add_review
        from log_channel import send_log
        rating = context.user_data.pop("pending_rating", 5)
        context.user_data.pop("state", None)
        review_text = text[:500]
        await add_review(user.id, rating, review_text)
        stars = "⭐️" * rating
        await send_log(context.bot,
            f"⭐️ Новый отзыв: {stars} от {user.first_name} (<code>{user.id}</code>)\n"
            f"💬 {review_text[:200]}"
        )
        await update.message.reply_text(
            f"✅ Спасибо за отзыв!\n\n{stars}\n💬 {review_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")],
            ]),
        )
        return

    # ── Юзер вводит промокод ─────────────────────────────────────────────────
    if state == AWAITING_PROMO_CODE:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from paidsub.handlers import validate_promo
        from paidsub.storage import get_paid_sub_by_tg_id, update_paid_sub_field
        context.user_data.pop("state", None)
        code = text.strip().upper()
        row = await get_paid_sub_by_tg_id(user.id)
        if not row:
            await update.message.reply_text(
                "❌ У вас нет активной подписки для применения промокода.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")]
                ]),
            )
            return
        promo, err = await validate_promo(code, user.id)
        if err:
            await update.message.reply_text(
                err,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎟 Ещё раз", callback_data="enter_promo")],
                    [InlineKeyboardButton("◀️ К оплате", callback_data="renew_sub")],
                ]),
            )
            return
        await update_paid_sub_field(row[0], "pending_promo", promo[1])
        await update.message.reply_text(
            f"✅ Промокод <b>{promo[1]}</b> применён — скидка <b>−{promo[2]}%</b>!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К оплате", callback_data="renew_sub")]
            ]),
        )
        return

    if not is_admin:
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

    if state == AWAITING_BROADCAST:
        context.user_data.pop("state", None)
        from database import get_users_by_segment
        from handlers.broadcast import SEGMENTS
        segment = context.user_data.pop("bcast_segment", "all")
        user_ids = await get_users_by_segment(segment)
        seg_label = SEGMENTS.get(segment, "Все")
        msg = await update.message.reply_text(f"⏳ Отправляю рассылку ({seg_label}) — {len(user_ids)} получателям...")
        ok, fail = await do_broadcast(context.bot, text, segment)
        await msg.edit_text(
            f"✅ Рассылка завершена.\n\n"
            f"🎯 Сегмент: {seg_label}\n"
            f"👥 Получателей: {len(user_ids)}\n"
            f"📨 Доставлено: {ok}\n❌ Ошибок: {fail}",
            reply_markup=back_admin(),
        )
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
        delivered = True
        try:
            await context.bot.send_message(
                chat_id=reply_to,
                text=f"🛡 <b>Ответ поддержки:</b>\n\n{text}",
                parse_mode="HTML",
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
        from paidsub.handlers import do_create_paid_sub
        sent = await update.message.reply_text("⏳ Создаю подписку...")

        async def _edit_paid(txt, **kw):
            await sent.edit_text(txt, reply_markup=back_admin(), **kw)

        await do_create_paid_sub(sent, tg_id, context, _edit_paid)
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
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>3 дня</code>, <code>12 часов</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        _save("paid_renew_time", seconds)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Время на продление: <b>{fmt_duration(seconds)}</b>", parse_mode="HTML", reply_markup=back_admin())
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
                await update_paid_sub_field(sub_id, "expire_date", new_expire_str)
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
                await update_paid_sub_field(sub_id, "expire_date", new_expire_str)
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
        sent = await update.message.reply_text("⏳ Применяю ко всем подпискам...")
        from paidsub.handlers import bulk_shift_expire
        from paidsub.time_parser import fmt_duration as fmt_dur
        result = await bulk_shift_expire(seconds, direction, context)
        action = "добавлен" if direction > 0 else "убавлен"
        await sent.edit_text(
            f"✅ <b>Массовое действие завершено</b>\n\n"
            f"Срок {action} на <b>{fmt_dur(seconds)}</b>\n"
            f"📊 Обработано: <b>{result['updated']}/{result['total']}</b>\n"
            + (f"❌ Ошибок: <b>{result['errors']}</b>" if result['errors'] else ""),
            parse_mode="HTML", reply_markup=back_admin(),
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
            from paidsub.storage import update_paid_sub_field, get_paid_sub
            await update_paid_sub_field(sub_id, "expire_date", text)
            await update_paid_sub_field(sub_id, "status", "active")
            r = await get_paid_sub(sub_id)
            if r:
                from xui_api import update_client_expire
                await update_client_expire(r[2], text)
                from paidsub.storage import add_history
                await add_history(r[1], "settings_changed", f"Подписка #{sub_id}: дата окончания → {text}")
        await update.message.reply_text(f"✅ Дата окончания обновлена: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_SUB_EDIT_IP:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field, get_paid_sub, add_history
            await update_paid_sub_field(sub_id, "limit_ip", int(text))
            r = await get_paid_sub(sub_id)
            if r:
                await add_history(r[1], "settings_changed", f"Подписка #{sub_id}: лимит IP → {text}")
        await update.message.reply_text(f"✅ Лимит IP обновлён: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_SUB_EDIT_HWID:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field, get_paid_sub, add_history
            await update_paid_sub_field(sub_id, "limit_hwid", int(text))
            r = await get_paid_sub(sub_id)
            if r:
                await add_history(r[1], "settings_changed", f"Подписка #{sub_id}: лимит HWID → {text}")
        await update.message.reply_text(f"✅ Лимит HWID обновлён: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
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
        seconds = parse_duration(text)
        if not seconds:
            await update.message.reply_text(
                "❌ Не удалось распознать. Примеры: <code>3 дня</code>, <code>12 часов</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field
            await update_paid_sub_field(sub_id, "ind_renew_time", seconds)
        from paidsub.time_parser import fmt_duration as fmt_dur
        await update.message.reply_text(f"✅ Время на продление: <b>{fmt_dur(seconds)}</b>", parse_mode="HTML", reply_markup=back_admin())
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

    # ── Авто-запрос отзыва: дни ─────────────────────────────────────────────
    if state == AWAITING_REVIEW_DAYS:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число (0 = выключить).", reply_markup=back_admin())
            return
        _save("review_request_days", int(text))
        context.user_data.pop("state", None)
        val = int(text)
        label = f"через {val} дн." if val > 0 else "выключено"
        await update.message.reply_text(f"✅ Авто-запрос отзыва: <b>{label}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Сообщение юзеру из профиля ─────────────────────────────────────────────
    if state == AWAITING_DM_USER:
        dm_target = context.user_data.pop("dm_target", None)
        context.user_data.pop("state", None)
        if dm_target:
            try:
                await context.bot.send_message(
                    chat_id=dm_target,
                    text=f"📌 <b>Сообщение от администратора:</b>\n\n{text}",
                    parse_mode="HTML",
                )
                from log_channel import send_log
                await send_log(context.bot,
                    f"📌 Админ → <code>{dm_target}</code>: {text[:100]}"
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

    # ── Юзер отправляет файл в поддержку ────────────────────────────────────
    if state == AWAITING_SUPPORT_MSG and not is_admin:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from database import get_unread_tickets_count, get_support_messages, count_support_files
        text_to_save = caption if caption else fallback_label
        await add_support_message(user.id, text_to_save, from_admin=False,
                                  file_id=file_id, file_type=file_type)
        _, total_pages = await get_support_messages(user.id)
        has_files = (await count_support_files(user.id)) > 0
        await msg.reply_text(
            "✅ Файл отправлен в поддержку! Мы ответим как можно скорее.",
            reply_markup=support_keyboard(total_pages, total_pages, has_files),
        )
        from log_channel import send_log
        await send_log(context.bot,
            f"📩 Файл в поддержку: {user.first_name} (<code>{user.id}</code>) — {fallback_label}"
        )
        uname = f"@{user.username}" if user.username else f"id{user.id}"
        unread = await get_unread_tickets_count()
        if file_type == "photo":
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=(
                    f"📩 <b>Файл от пользователя</b>\n\n"
                    f'👤 <a href="tg://user?id={user.id}">{user.first_name}</a> ({uname})\n'
                    f"🆔 <code>{user.id}</code>\n"
                    f"🔴 Непрочитанных: <b>{unread}</b>"
                    + (f"\n\n💬 {caption}" if caption else "")
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Ответить", callback_data=f"ticket_reply:{user.id}")],
                    [InlineKeyboardButton("👀 Открыть переписку", callback_data=f"ticket_view:{user.id}:1")],
                ]),
            )
        else:
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=file_id,
                caption=(
                    f"📩 <b>Файл от пользователя</b>\n\n"
                    f'👤 <a href="tg://user?id={user.id}">{user.first_name}</a> ({uname})\n'
                    f"🆔 <code>{user.id}</code>\n"
                    f"🔴 Непрочитанных: <b>{unread}</b>"
                    + (f"\n\n💬 {caption}" if caption else "")
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Ответить", callback_data=f"ticket_reply:{user.id}")],
                    [InlineKeyboardButton("👀 Открыть переписку", callback_data=f"ticket_view:{user.id}:1")],
                ]),
            )
        return

    # ── Админ отправляет файл как ответ ─────────────────────────────────────
    if state == AWAITING_ADMIN_REPLY and is_admin:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        reply_to = context.user_data.pop("reply_to", None)
        context.user_data.pop("state", None)
        if not reply_to:
            await msg.reply_text("❌ Пользователь не найден.", reply_markup=back_admin())
            return
        text_to_save = caption if caption else fallback_label
        await add_support_message(reply_to, text_to_save, from_admin=True,
                                  file_id=file_id, file_type=file_type)
        delivered = True
        try:
            if file_type == "photo":
                await context.bot.send_photo(
                    chat_id=reply_to,
                    photo=file_id,
                    caption=f"🛡 <b>Ответ поддержки:</b>" + (f"\n\n{caption}" if caption else ""),
                    parse_mode="HTML",
                )
            else:
                await context.bot.send_document(
                    chat_id=reply_to,
                    document=file_id,
                    caption=f"🛡 <b>Ответ поддержки:</b>" + (f"\n\n{caption}" if caption else ""),
                    parse_mode="HTML",
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
