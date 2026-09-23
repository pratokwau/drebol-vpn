from telegram import Update
from telegram.ext import ContextTypes
from keyboards import back_main


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧭 <b>Команды</b>\n\n"
        "<blockquote>/start — главное меню и ваша подписка\n"
        "/help — эта подсказка</blockquote>\n\n"
        "<i>Всё остальное — кнопками в меню.</i>",
        parse_mode="HTML",
        reply_markup=back_main(),
    )
