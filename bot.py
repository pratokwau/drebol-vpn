import os
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
INSTALL_DIR = "/root/drebol-vpn"


def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🛒 Купить VPN", callback_data="buy")],
        [InlineKeyboardButton("ℹ️ О сервисе", callback_data="about")],
    ]
    if is_admin(update):
        keyboard.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel")])

    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Добро пожаловать в *Drebol VPN* — быстрый и надёжный VPN.\n\n"
        "Выбери действие:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Доступные команды:*\n"
        "/start — главное меню\n"
        "/help — список команд",
        parse_mode="Markdown",
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "buy":
        await query.edit_message_text(
            "🛒 *Покупка VPN*\n\nРаздел в разработке.",
            parse_mode="Markdown",
        )

    elif data == "about":
        await query.edit_message_text(
            "ℹ️ *О сервисе*\n\nDrebol VPN — быстрый и надёжный VPN-сервис.",
            parse_mode="Markdown",
        )

    elif data == "admin_panel":
        if not is_admin(update):
            await query.edit_message_text("⛔ Нет доступа.")
            return
        keyboard = [
            [InlineKeyboardButton("🔄 Обновиться с GitHub", callback_data="git_update")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_start")],
        ]
        await query.edit_message_text(
            "⚙️ *Панель администратора*\n\nВыбери действие:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "git_update":
        if not is_admin(update):
            await query.edit_message_text("⛔ Нет доступа.")
            return
        await query.edit_message_text("⏳ Обновляю бота с GitHub...")
        try:
            result = subprocess.run(
                ["git", "-C", INSTALL_DIR, "pull"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                await query.edit_message_text(
                    f"❌ Ошибка git pull:\n`{result.stderr}`",
                    parse_mode="Markdown",
                )
                return
            output = result.stdout.strip()
            await query.edit_message_text(
                f"✅ Обновление загружено:\n`{output}`\n\nПерезапускаю бота...",
                parse_mode="Markdown",
            )
            # Перезапуск через systemd (запускается отдельным процессом, чтобы успел ответить)
            subprocess.Popen(
                ["systemctl", "restart", "drebol-vpn"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except subprocess.TimeoutExpired:
            await query.edit_message_text("❌ Таймаут при обновлении. Попробуй позже.")
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {e}")

    elif data == "back_start":
        user = update.effective_user
        keyboard = [
            [InlineKeyboardButton("🛒 Купить VPN", callback_data="buy")],
            [InlineKeyboardButton("ℹ️ О сервисе", callback_data="about")],
        ]
        if is_admin(update):
            keyboard.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel")])
        await query.edit_message_text(
            f"Привет, {user.first_name}! 👋\n\n"
            "Добро пожаловать в *Drebol VPN* — быстрый и надёжный VPN.\n\n"
            "Выбери действие:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    print("Бот запущен...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
