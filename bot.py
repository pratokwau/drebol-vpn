from config import BOT_TOKEN
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from handlers.start import start
from handlers.help import help_cmd
from handlers.callbacks import callback_router
from handlers.messages import handle_text


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Бот запущен...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
