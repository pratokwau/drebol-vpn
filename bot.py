import os
import json
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
INSTALL_DIR = "/root/drebol-vpn"
CONFIG_FILE = os.path.join(INSTALL_DIR, "config.json")

# Состояния ожидания ввода от админа
AWAITING_CHANNEL = "awaiting_channel"


# ---------- Config helpers ----------

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_config(data: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------- Keyboard builders ----------

def main_keyboard(is_adm: bool) -> InlineKeyboardMarkup:
    cfg = load_config()
    rows = [
        [InlineKeyboardButton("🛒 Купить VPN", callback_data="buy")],
        [InlineKeyboardButton("ℹ️ О сервисе", callback_data="about")],
    ]
    if cfg.get("channel_url"):
        rows.append([InlineKeyboardButton("📢 Наш канал", url=cfg["channel_url"])])
    if is_adm:
        rows.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_label = "📢 Изменить канал" if cfg.get("channel_url") else "📢 Установить канал"
    rows = [
        [InlineKeyboardButton("🔄 Обновиться с GitHub", callback_data="git_update")],
        [InlineKeyboardButton(channel_label, callback_data="set_channel")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_start")],
    ]
    return InlineKeyboardMarkup(rows)


def back_to_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")]
    ])


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад", callback_data="back_start")]
    ])


# ---------- Helpers ----------

def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


async def show_main_menu(target, user, is_adm: bool):
    text = (
        f"Привет, {user.first_name}! 👋\n\n"
        "Добро пожаловать в *Drebol VPN* — быстрый и надёжный VPN.\n\n"
        "Выбери действие:"
    )
    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(text, parse_mode="Markdown", reply_markup=main_keyboard(is_adm))
    else:
        await target.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard(is_adm))


async def show_admin_panel(query):
    cfg = load_config()
    channel_info = f"\n📢 Канал: {cfg['channel_url']}" if cfg.get("channel_url") else "\n📢 Канал: не задан"
    await query.edit_message_text(
        f"⚙️ *Панель администратора*{channel_info}\n\nВыбери действие:",
        parse_mode="Markdown",
        reply_markup=admin_keyboard(),
    )


# ---------- Handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("state", None)
    await show_main_menu(update.message, update.effective_user, is_admin(update))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Доступные команды:*\n"
        "/start — главное меню\n"
        "/help — список команд",
        parse_mode="Markdown",
        reply_markup=back_to_main_keyboard(),
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    adm = is_admin(update)

    if data == "back_start":
        context.user_data.pop("state", None)
        await show_main_menu(query, update.effective_user, adm)

    elif data == "admin_panel":
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        await show_admin_panel(query)

    elif data == "buy":
        await query.edit_message_text(
            "🛒 *Покупка VPN*\n\nРаздел в разработке.",
            parse_mode="Markdown",
            reply_markup=back_to_main_keyboard(),
        )

    elif data == "about":
        await query.edit_message_text(
            "ℹ️ *О сервисе*\n\nDrebol VPN — быстрый и надёжный VPN-сервис.",
            parse_mode="Markdown",
            reply_markup=back_to_main_keyboard(),
        )

    elif data == "set_channel":
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        context.user_data["state"] = AWAITING_CHANNEL
        await query.edit_message_text(
            "📢 *Установка канала*\n\n"
            "Отправь ссылку на Telegram-канал (например: `https://t.me/mychannel`):",
            parse_mode="Markdown",
            reply_markup=back_to_admin_keyboard(),
        )

    elif data == "git_update":
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        await query.edit_message_text("⏳ Обновляю бота с GitHub...")
        try:
            result = subprocess.run(
                ["git", "-C", INSTALL_DIR, "pull"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                await query.edit_message_text(
                    f"❌ Ошибка git pull:\n`{result.stderr.strip()}`",
                    parse_mode="Markdown",
                    reply_markup=back_to_admin_keyboard(),
                )
                return
            output = result.stdout.strip()
            await query.edit_message_text(
                f"✅ Обновление загружено:\n`{output}`\n\nПерезапускаю бота...",
                parse_mode="Markdown",
            )
            subprocess.Popen(
                ["systemctl", "restart", "drebol-vpn"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            await query.edit_message_text(
                "❌ Таймаут при обновлении. Попробуй позже.",
                reply_markup=back_to_admin_keyboard(),
            )
        except Exception as e:
            await query.edit_message_text(
                f"❌ Ошибка: {e}",
                reply_markup=back_to_admin_keyboard(),
            )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")

    if state == AWAITING_CHANNEL and is_admin(update):
        url = update.message.text.strip()
        if not url.startswith("https://t.me/") and not url.startswith("http"):
            await update.message.reply_text(
                "❌ Некорректная ссылка. Должна начинаться с `https://t.me/`",
                parse_mode="Markdown",
                reply_markup=back_to_admin_keyboard(),
            )
            return
        cfg = load_config()
        cfg["channel_url"] = url
        save_config(cfg)
        context.user_data.pop("state", None)
        await update.message.reply_text(
            f"✅ Канал сохранён: {url}\n\nТеперь кнопка *📢 Наш канал* появится в главном меню.",
            parse_mode="Markdown",
            reply_markup=back_to_admin_keyboard(),
        )


# ---------- Entry point ----------

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("Бот запущен...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
