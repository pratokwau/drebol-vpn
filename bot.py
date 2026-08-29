from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import BOT_TOKEN
from database import init_db
from handlers.start import start
from handlers.help import help_cmd
from handlers.callbacks import callback_router
from handlers.messages import handle_text


async def post_init(app: Application):
    await init_db()
    from adminsub.handlers import sync_usernames
    from config import load_config

    async def _sync_job(ctx):
        from datetime import datetime
        cfg = load_config()
        if not cfg.get("auto_update_usernames", False):
            return
        days = int(cfg.get("auto_update_days", 2))
        last_run_str = cfg.get("auto_update_last_run")
        if last_run_str:
            try:
                last_run = datetime.strptime(last_run_str, "%d.%m.%Y %H:%M")
                if (datetime.now() - last_run).days < days:
                    return
            except Exception:
                pass
        await sync_usernames(ctx)

    if app.job_queue:
        app.job_queue.run_repeating(_sync_job, interval=24 * 3600, first=300)

        from paidsub.handlers import check_expired_subs, paid_sync_usernames
        app.job_queue.run_repeating(check_expired_subs, interval=10, first=10)

        async def _paid_sync_job(ctx):
            from datetime import datetime
            cfg = load_config()
            if not cfg.get("paid_auto_update_usernames", False):
                return
            days = int(cfg.get("paid_auto_update_days", 2))
            last_run_str = cfg.get("paid_auto_update_last_run")
            if last_run_str:
                try:
                    last_run = datetime.strptime(last_run_str, "%d.%m.%Y %H:%M")
                    if (datetime.now() - last_run).days < days:
                        return
                except Exception:
                    pass
            await paid_sync_usernames(ctx)

        app.job_queue.run_repeating(_paid_sync_job, interval=24 * 3600, first=300)


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Бот запущен...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
