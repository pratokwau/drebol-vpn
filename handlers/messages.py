from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID, load_config, save_config
from database import add_support_message, get_support_messages
from keyboards import back_admin, support_keyboard
from states import (
    AWAITING_CHANNEL, AWAITING_BROADCAST,
    AWAITING_SUPPORT_MSG, AWAITING_ADMIN_REPLY,
    AWAITING_PRIVACY_URL, AWAITING_TERMS_URL,
    AWAITING_XUI_URL, AWAITING_XUI_LOGIN, AWAITING_XUI_PASS,
    AWAITING_XUI_SUB_PORT, AWAITING_XUI_SUB_PATH,
    AWAITING_PRESET_EXPIRE, AWAITING_PRESET_IP,
    AWAITING_PRESET_HWID, AWAITING_PRESET_TRAFFIC,
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

    if state == AWAITING_XUI_LOGIN:
        _save("xui_login", text)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Логин: <code>{text}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_XUI_PASS:
        _save("xui_password", text)
        context.user_data.pop("state", None)
        await update.message.reply_text("✅ Пароль сохранён.", reply_markup=back_admin())
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
