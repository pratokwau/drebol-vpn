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
    AWAITING_REFERRAL_BONUS,
    AWAITING_PAID_SUB_REDUCE,
    AWAITING_PAID_BULK_EXTEND, AWAITING_PAID_BULK_REDUCE,
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
        from database import get_all_user_ids
        user_ids = await get_all_user_ids()
        msg = await update.message.reply_text(f"⏳ Отправляю рассылку {len(user_ids)} пользователям...")
        ok, fail = await do_broadcast(context.bot, text)
        await msg.edit_text(
            f"✅ Рассылка завершена.\n\n👥 В базе: {len(user_ids)}\n📨 Доставлено: {ok}\n❌ Ошибок: {fail}",
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

    # ── Мьют пользователя ───────────────────────────────────────────────────────
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
