from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import BOT_TOKEN
from database import init_db
from handlers.start import start
from handlers.help import help_cmd
from handlers.callbacks import callback_router
from handlers.messages import handle_text, handle_media


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

        async def _healthcheck_job(ctx):
            from config import ADMIN_ID, load_config, save_config
            from xui_api import test_connection
            cfg = load_config()
            if not cfg.get("xui_url") or not cfg.get("xui_token"):
                return
            result = await test_connection()
            healthy = bool(result.get("success"))
            prev = cfg.get("xui_healthy", True)
            if healthy != prev:
                cfg["xui_healthy"] = healthy
                save_config(cfg)
                from log_channel import send_log
                try:
                    if healthy:
                        await ctx.bot.send_message(
                            chat_id=ADMIN_ID,
                            text="🟢 <b>Панель 3x-UI снова доступна.</b>",
                            parse_mode="HTML",
                        )
                        await send_log(ctx.bot, "🟢 Панель 3x-UI снова доступна.")
                    else:
                        await ctx.bot.send_message(
                            chat_id=ADMIN_ID,
                            text=(
                                "🔴 <b>Панель 3x-UI недоступна!</b>\n\n"
                                f"<code>{result.get('error', '?')}</code>"
                            ),
                            parse_mode="HTML",
                        )
                        await send_log(ctx.bot,
                            f"🔴 Панель 3x-UI недоступна!\n<code>{result.get('error', '?')}</code>"
                        )
                except Exception:
                    pass

        app.job_queue.run_repeating(_healthcheck_job, interval=300, first=60)

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

        async def _winback_job(ctx):
            from config import load_config
            from datetime import datetime, timedelta
            cfg = load_config()
            if not cfg.get("winback_enabled", False):
                return
            days = cfg.get("winback_days", 3)
            percent = cfg.get("winback_percent", 20)
            from database import is_winback_sent, mark_winback_sent
            from paidsub.storage import get_expired_paid_subs
            from log_channel import send_log
            subs = await get_expired_paid_subs()
            now = datetime.now()
            for row in subs:
                sub_id, tg_id, email, uuid_val, sub_id_str, sub_url, expire_str, status, times_renewed, ind_renew = row
                if status != "expired" or not tg_id:
                    continue
                for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                    try:
                        expire_dt = datetime.strptime(expire_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
                if (now - expire_dt).days < days:
                    continue
                if await is_winback_sent(tg_id):
                    continue
                # Создаём персональный промокод
                code = f"BACK{tg_id}"
                from paidsub.storage import get_promo, create_promo
                if not await get_promo(code):
                    await create_promo(code, percent, None)
                await mark_winback_sent(tg_id)
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    await ctx.bot.send_message(
                        chat_id=tg_id,
                        text=(
                            f"🎯 <b>Мы скучаем!</b>\n\n"
                            f"Ваша подписка истекла. Вернитесь со скидкой <b>{percent}%</b>!\n\n"
                            f"🎟 Ваш промокод: <b>{code}</b>\n\n"
                            f"Используйте его при продлении подписки."
                        ),
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")]
                        ]),
                    )
                    await send_log(ctx.bot,
                        f"🎯 Winback отправлен: <code>{tg_id}</code> · промокод <b>{code}</b> (−{percent}%)"
                    )
                except Exception:
                    pass

        app.job_queue.run_repeating(_winback_job, interval=3600, first=600)

        async def _review_request_job(ctx):
            from config import load_config
            from datetime import datetime
            cfg = load_config()
            review_days = cfg.get("review_request_days", 0)
            if review_days <= 0:
                return
            from database import is_review_requested, mark_review_requested, get_user_review
            from paidsub.storage import get_all_paid_subs_with_tg
            subs = await get_all_paid_subs_with_tg()
            now = datetime.now()
            for row in subs:
                sub_id, tg_id, email, uuid_val, sub_id_str, expire_date, *_ = row
                if not tg_id:
                    continue
                if await is_review_requested(tg_id):
                    continue
                if await get_user_review(tg_id):
                    continue
                # Проверяем дату создания подписки
                import aiosqlite
                from database import DB_PATH
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute(
                        "SELECT created_at FROM paid_subs WHERE id = ?", (sub_id,)
                    ) as cur:
                        r = await cur.fetchone()
                if not r:
                    continue
                for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                    try:
                        created_dt = datetime.strptime(r[0][:19] if r[0] else "", fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
                if (now - created_dt).days < review_days:
                    continue
                await mark_review_requested(tg_id)
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    await ctx.bot.send_message(
                        chat_id=tg_id,
                        text=(
                            "⭐️ <b>Как вам Drebol VPN?</b>\n\n"
                            "Мы хотим стать лучше! Оцените наш сервис:"
                        ),
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("1⭐", callback_data="rate:1"),
                                InlineKeyboardButton("2⭐", callback_data="rate:2"),
                                InlineKeyboardButton("3⭐", callback_data="rate:3"),
                                InlineKeyboardButton("4⭐", callback_data="rate:4"),
                                InlineKeyboardButton("5⭐", callback_data="rate:5"),
                            ],
                        ]),
                    )
                except Exception:
                    pass

        app.job_queue.run_repeating(_review_request_job, interval=3600, first=900)


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
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_media))

    print("Бот запущен...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
