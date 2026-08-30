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
