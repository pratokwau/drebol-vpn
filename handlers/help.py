from telegram import Update
from telegram.ext import ContextTypes
from keyboards import back_main


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Доступные команды:*\n"
        "/start — главное меню\n"
        "/help — список команд",
        parse_mode="Markdown",
        reply_markup=back_main(),
    )
