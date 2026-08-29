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
        await add_support_message(user.id, text, from_admin=False)
        _, total_pages = await get_support_messages(user.id)
        await update.message.reply_text(
            "✅ Сообщение отправлено в поддержку! Мы ответим как можно скорее.",
            reply_markup=support_keyboard(total_pages, total_pages),
        )
        uname = f"@{user.username}" if user.username else f"id{user.id}"
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 Новое обращение от {user.first_name} ({uname}):\n\n{text}",
        )
        return

    if not is_admin:
        return

    # ══════════════════════════════════════════════════════════════════════════
    # АДМИН
    # ══════════════════════════════════════════════════════════════════════════

    if state == AWAITING_CHANNEL:
        if not text.startswith("http"):
            await update.message.reply_text("❌ Некорректная ссылка.", reply_markup=back_admin())
            return
        _save("channel_url", text)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Канал сохранён: <code>{text}</code>", parse_mode="HTML", reply_markup=back_admin())
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
        reply_to = context.user_data.pop("reply_to", None)
        context.user_data.pop("state", None)
        if not reply_to:
            await update.message.reply_text("❌ Пользователь не найден.", reply_markup=back_admin())
            return
        await add_support_message(reply_to, text, from_admin=True)
        try:
            await context.bot.send_message(
                chat_id=reply_to,
                text=f"🛡 <b>Ответ поддержки:</b>\n\n{text}",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await update.message.reply_text("✅ Ответ отправлен.", reply_markup=back_admin())
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
                for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
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
                new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M")
                await update_paid_sub_field(sub_id, "expire_date", new_expire_str)
                from xui_api import date_to_ms, get_client_info
                from paidsub.time_parser import fmt_duration as fmt_dur
                await update.message.reply_text(
                    f"✅ Срок продлён на <b>{fmt_dur(seconds)}</b>\n"
                    f"📅 Новая дата: <b>{new_expire_str}</b>",
                    parse_mode="HTML", reply_markup=back_admin(),
                )
                return
        await update.message.reply_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return

    # ── Платные подписки: индивидуальные настройки ──────────────────────────────
    if state == AWAITING_PAID_SUB_EDIT_EXPIRE:
        for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            await update.message.reply_text(
                "❌ Формат: <code>дд.мм.гггг</code> или <code>дд.мм.гггг чч:мм</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field
            await update_paid_sub_field(sub_id, "expire_date", text)
        await update.message.reply_text(f"✅ Дата окончания обновлена: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_SUB_EDIT_IP:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field
            await update_paid_sub_field(sub_id, "limit_ip", int(text))
        await update.message.reply_text(f"✅ Лимит IP обновлён: <b>{text}</b>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_PAID_SUB_EDIT_HWID:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=back_admin())
            return
        sub_id = context.user_data.pop("edit_sub_id", None)
        context.user_data.pop("state", None)
        if sub_id:
            from paidsub.storage import update_paid_sub_field
            await update_paid_sub_field(sub_id, "limit_hwid", int(text))
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
            from paidsub.storage import update_paid_sub_field
            await update_paid_sub_field(sub_id, "total_gb", val)
        await update.message.reply_text(f"✅ Трафик обновлён: <b>{label}</b>", parse_mode="HTML", reply_markup=back_admin())
        return
