import subprocess
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID, INSTALL_DIR, load_config
from keyboards import admin_keyboard, back_admin

AWAITING_CHANNEL = "awaiting_channel"


def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


async def handle_admin_panel(query):
    cfg = load_config()
    channel_url = cfg.get("channel_url", "")
    channel_info = f"\n📢 Канал: <code>{channel_url}</code>" if channel_url else "\n📢 Канал: не задан"
    await query.edit_message_text(
        f"⚙️ <b>Панель администратора</b>{channel_info}\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


async def handle_set_channel(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_CHANNEL
    await query.edit_message_text(
        "📢 <b>Установка канала</b>\n\n"
        "Отправь ссылку на Telegram-канал (например: <code>https://t.me/mychannel</code>):",
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
        await query.edit_message_text(
            "❌ Таймаут при обновлении. Попробуй позже.",
            reply_markup=back_admin(),
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}", reply_markup=back_admin())
