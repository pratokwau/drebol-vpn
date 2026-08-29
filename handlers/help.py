from telegram import Update
from telegram.ext import ContextTypes
from keyboards import back_main


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Доступные команды:</b>\n"
        "/start — главное меню\n"
        "/help — список команд",
        parse_mode="HTML",
        reply_markup=back_main(),
    )
