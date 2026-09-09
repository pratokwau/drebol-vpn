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
            """Следит за панелью, сервисом подписок и портами инбаундов.

            Уведомляет только при смене состояния, чтобы не спамить каждые 5 минут.
            """
            from config import ADMIN_ID, load_config, save_config
            from xui_api import probe_servers
            from log_channel import send_log

            cfg = load_config()
            if not cfg.get("xui_url") or not cfg.get("xui_token"):
                return

            r = await probe_servers()
            panel_ok = r["panel"]["ok"]
            sub_ok = r["sub"]["ok"]
            dead = sorted(
                i["tag"] for i in r["inbounds"] if i["enabled"] and not i["reachable"]
            )

            alerts = []
            changed = False

            if panel_ok != cfg.get("xui_healthy", True):
                cfg["xui_healthy"] = panel_ok
                changed = True
                alerts.append(
                    "🟢 <b>Панель 3x-UI снова доступна.</b>" if panel_ok else
                    f"🔴 <b>Панель 3x-UI недоступна!</b>\n<code>{r['panel'].get('error', '?')}</code>"
                )

            # панель может отвечать, пока выдача подписок лежит — следим отдельно
            if panel_ok and sub_ok != cfg.get("sub_healthy", True):
                cfg["sub_healthy"] = sub_ok
                changed = True
                alerts.append(
                    "🟢 <b>Сервис подписок снова работает.</b>" if sub_ok else
                    f"🔴 <b>Сервис подписок не отвечает!</b>\n"
                    f"Порт {r['sub'].get('port', '?')} — <code>{r['sub'].get('error', '?')}</code>\n"
                    f"Клиенты не смогут обновить ключ."
                )

            if panel_ok and dead != (cfg.get("dead_inbounds") or []):
                prev = cfg.get("dead_inbounds") or []
                cfg["dead_inbounds"] = dead
                changed = True
                if dead:
                    alerts.append(
                        "🔴 <b>Инбаунд не принимает соединения:</b>\n" +
                        "\n".join(f"• {t}" for t in dead)
                    )
                elif prev:
                    alerts.append("🟢 <b>Все инбаунды снова доступны.</b>")

            if changed:
                save_config(cfg)
            for text in alerts:
                try:
                    await ctx.bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML")
                    await send_log(ctx.bot, text)
                except Exception:
                    pass

        app.job_queue.run_repeating(_healthcheck_job, interval=300, first=60)

        async def _platega_poll_job(ctx):
            """Опрашивает выставленные счета и засчитывает оплату.

            Колбэки Platega требуют публичный HTTPS с валидным сертификатом,
            поэтому статус выясняем опросом — не зависит от занятости 443.
            """
            import platega_api as pg
            from database import (
                get_pending_payments, set_payment_status, expire_stale_payments,
            )
            if not pg.is_configured():
                return

            # счёт Platega живёт 30 минут — дальше опрашивать нечего
            ttl = int(load_config().get("invoice_ttl_minutes", 60) or 60)
            await expire_stale_payments(ttl)
            pending = await get_pending_payments("platega", limit=40)
            if not pending:
                return

            # статусы читаем параллельно: последовательно 40 счетов могли бы
            # растянуться дольше, чем интервал самой задачи
            import asyncio
            statuses = await asyncio.gather(
                *[pg.get_status(p[3]) for p in pending if p[3]],
                return_exceptions=True,
            )

            from paidsub.handlers import apply_paid_payment
            for (pay_id, tg_id, _prov, ext_id, amount, period, promo, _created), r in zip(
                [p for p in pending if p[3]], statuses
            ):
                if isinstance(r, Exception):
                    continue
                if not r.get("ok"):
                    if r.get("not_found"):
                        await set_payment_status(pay_id, "error", "транзакция не найдена")
                    continue

                status = r.get("status")
                if status == pg.STATUS_CONFIRMED:
                    # статус ставим до начисления: если начисление упадёт,
                    # повторный проход не выдаст второй период за один платёж
                    await set_payment_status(pay_id, "paid")
                    try:
                        res = await apply_paid_payment(
                            tg_id, amount, ctx, promo_code=promo,
                            source="Platega", period_seconds=period,
                        )
                        if not res.get("ok"):
                            await set_payment_status(pay_id, "paid", res.get("error"))
                            from config import ADMIN_ID
                            await ctx.bot.send_message(
                                chat_id=ADMIN_ID,
                                text=(
                                    "⚠️ <b>Оплата получена, но не засчитана</b>\n\n"
                                    f"👤 <code>{tg_id}</code> · {amount} ₽\n"
                                    f"<code>{res.get('error')}</code>\n\n"
                                    "Продли подписку вручную."
                                ),
                                parse_mode="HTML",
                            )
                    except Exception as e:
                        await set_payment_status(pay_id, "paid", str(e)[:120])
                elif status in (pg.STATUS_CANCELED, pg.STATUS_CHARGEBACKED):
                    await set_payment_status(pay_id, status.lower())

        poll_every = int(load_config().get("invoice_poll_seconds", 60) or 60)
        app.job_queue.run_repeating(_platega_poll_job, interval=poll_every, first=30)

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
