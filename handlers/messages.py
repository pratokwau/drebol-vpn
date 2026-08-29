from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID, load_config, save_config
from database import add_support_message, get_support_messages
from keyboards import back_admin, support_keyboard, cancel_admin
from states import (
    AWAITING_CHANNEL, AWAITING_BROADCAST,
    AWAITING_SUPPORT_MSG, AWAITING_ADMIN_REPLY,
    AWAITING_PRIVACY_URL, AWAITING_TERMS_URL,
    AWAITING_XUI_URL, AWAITING_XUI_LOGIN, AWAITING_XUI_PASS,
    AWAITING_XUI_SUB_PORT, AWAITING_XUI_SUB_PATH, AWAITING_XUI_INBOUND_ID,
    AWAITING_SUB_EXPIRE, AWAITING_SUB_IP_LIMIT,
    AWAITING_SUB_HWID_LIMIT, AWAITING_SUB_TRAFFIC,
)
from handlers.broadcast import do_broadcast


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
    # Ниже только обработчики для АДМИНИСТРАТОРА
    # ══════════════════════════════════════════════════════════════════════════

    # ── Канал ─────────────────────────────────────────────────────────────────
    if state == AWAITING_CHANNEL:
        if not text.startswith("http"):
            await update.message.reply_text(
                "❌ Некорректная ссылка.", parse_mode="HTML", reply_markup=back_admin()
            )
            return
        _save_cfg("channel_url", text)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Канал сохранён: <code>{text}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Рассылка ──────────────────────────────────────────────────────────────
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

    # ── Политика / Соглашение ─────────────────────────────────────────────────
    if state == AWAITING_PRIVACY_URL:
        if not text.startswith("http"):
            await update.message.reply_text("❌ Некорректная ссылка.", reply_markup=back_admin())
            return
        _save_cfg("privacy_url", text)
        context.user_data.pop("state", None)
        await update.message.reply_text("✅ Политика конфиденциальности сохранена.", reply_markup=back_admin())
        return

    if state == AWAITING_TERMS_URL:
        if not text.startswith("http"):
            await update.message.reply_text("❌ Некорректная ссылка.", reply_markup=back_admin())
            return
        _save_cfg("terms_url", text)
        context.user_data.pop("state", None)
        await update.message.reply_text("✅ Пользовательское соглашение сохранено.", reply_markup=back_admin())
        return

    # ── Ответ на тикет ────────────────────────────────────────────────────────
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

    # ── Параметры 3x-UI ───────────────────────────────────────────────────────
    if state == AWAITING_XUI_URL:
        if not text.startswith("http"):
            await update.message.reply_text("❌ URL должен начинаться с http.", reply_markup=back_admin())
            return
        _save_cfg("xui_url", text.rstrip("/"))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ URL панели сохранён: <code>{text}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_XUI_LOGIN:
        _save_cfg("xui_login", text)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Логин сохранён: <code>{text}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_XUI_PASS:
        _save_cfg("xui_password", text)
        context.user_data.pop("state", None)
        await update.message.reply_text("✅ Пароль сохранён.", reply_markup=back_admin())
        return

    if state == AWAITING_XUI_SUB_PORT:
        if not text.isdigit():
            await update.message.reply_text("❌ Порт должен быть числом.", reply_markup=back_admin())
            return
        _save_cfg("xui_sub_port", text)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Порт подписки: <code>{text}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_XUI_SUB_PATH:
        path = text if text.startswith("/") else f"/{text}"
        path = path if path.endswith("/") else f"{path}/"
        _save_cfg("xui_sub_path", path)
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ Путь подписки: <code>{path}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    if state == AWAITING_XUI_INBOUND_ID:
        if not text.isdigit():
            await update.message.reply_text("❌ ID должен быть числом.", reply_markup=back_admin())
            return
        _save_cfg("xui_inbound_id", int(text))
        context.user_data.pop("state", None)
        await update.message.reply_text(f"✅ ID инбаунда: <code>{text}</code>", parse_mode="HTML", reply_markup=back_admin())
        return

    # ── Мастер создания подписки ──────────────────────────────────────────────
    if state == AWAITING_SUB_EXPIRE:
        try:
            datetime.strptime(text, "%d.%m.%Y")
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат. Введи дату как <code>дд.мм.гггг</code>",
                parse_mode="HTML", reply_markup=cancel_admin(),
            )
            return
        context.user_data["new_sub"] = {"expire": text}
        context.user_data["state"] = AWAITING_SUB_IP_LIMIT
        await update.message.reply_text(
            "✅ Дата: <b>" + text + "</b>\n\n"
            "<b>Шаг 2/4</b> — Лимит IP\n\n"
            "Введи число (0 = безлимит):",
            parse_mode="HTML", reply_markup=cancel_admin(),
        )
        return

    if state == AWAITING_SUB_IP_LIMIT:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=cancel_admin())
            return
        context.user_data["new_sub"]["limit_ip"] = int(text)
        context.user_data["state"] = AWAITING_SUB_HWID_LIMIT
        await update.message.reply_text(
            f"✅ Лимит IP: <b>{text}</b>\n\n"
            "<b>Шаг 3/4</b> — Лимит HWID\n\n"
            "Введи число (0 = безлимит):",
            parse_mode="HTML", reply_markup=cancel_admin(),
        )
        return

    if state == AWAITING_SUB_HWID_LIMIT:
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.", reply_markup=cancel_admin())
            return
        context.user_data["new_sub"]["limit_hwid"] = int(text)
        context.user_data["state"] = AWAITING_SUB_TRAFFIC
        await update.message.reply_text(
            f"✅ Лимит HWID: <b>{text}</b>\n\n"
            "<b>Шаг 4/4</b> — Лимит трафика\n\n"
            'Введи число в <b>ГБ</b> или <b>-</b> для безлимита:',
            parse_mode="HTML", reply_markup=cancel_admin(),
        )
        return

    if state == AWAITING_SUB_TRAFFIC:
        if text == "-":
            total_gb = 0
        elif text.isdigit() and int(text) > 0:
            total_gb = int(text)
        else:
            await update.message.reply_text(
                '❌ Введи число в ГБ или <b>-</b> для безлимита.',
                parse_mode="HTML", reply_markup=cancel_admin(),
            )
            return

        sub_data = context.user_data.pop("new_sub", {})
        context.user_data.pop("state", None)
        sub_data["total_gb"] = total_gb

        msg = await update.message.reply_text("⏳ Создаю подписку в панели...")

        from xui_api import create_client
        result = await create_client(
            expire_date=sub_data["expire"],
            limit_ip=sub_data.get("limit_ip", 0),
            limit_hwid=sub_data.get("limit_hwid", 0),
            total_gb=total_gb,
        )

        if result["success"]:
            traffic_str = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"
            await msg.edit_text(
                "✅ <b>Подписка создана!</b>\n\n"
                f"📅 До: <b>{result['expire']}</b>\n"
                f"📶 Трафик: <b>{traffic_str}</b>\n"
                f"🔗 Ссылка подписки:\n<code>{result['sub_url']}</code>",
                parse_mode="HTML",
                reply_markup=back_admin(),
            )
        else:
            await msg.edit_text(
                f"❌ Ошибка: {result['error']}",
                reply_markup=back_admin(),
            )
        return


def _save_cfg(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
