from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID, load_config, save_config
from keyboards import back_admin
from handlers.admin import AWAITING_CHANNEL


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user = update.effective_user

    if state == AWAITING_CHANNEL and user.id == ADMIN_ID:
        url = update.message.text.strip()
        if not url.startswith("http"):
            await update.message.reply_text(
                "❌ Некорректная ссылка. Должна начинаться с <code>https://t.me/</code>",
                parse_mode="HTML",
                reply_markup=back_admin(),
            )
            return
        cfg = load_config()
        cfg["channel_url"] = url
        save_config(cfg)
        context.user_data.pop("state", None)
        await update.message.reply_text(
            f"✅ Канал сохранён: <code>{url}</code>\n\n"
            "Кнопка <b>📢 Наш канал</b> теперь видна в главном меню.",
            parse_mode="HTML",
            reply_markup=back_admin(),
        )
