import logging

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, TypeHandler, filters,
)

logger = logging.getLogger(__name__)


async def _on_error(update, context):
    """Логирует ошибку обработчика и показывает алерт, вместо мёртвой кнопки."""
    logger.exception("Ошибка обработчика: %s", context.error)
    if update and update.callback_query:
        try:
            await update.callback_query.answer("⚠️ Ошибка, смотри лог", show_alert=True)
        except Exception:
            pass


from config import BOT_TOKEN
from core.database import init_db
from handlers.start import start
from handlers.help import help_cmd
from handlers.callbacks import callback_router
from handlers.messages import handle_text, handle_media
from handlers.control import log_update


async def post_init(app: Application):
    await init_db()
    from config import load_config

    if app.job_queue:
        from paidsub.handlers import check_expired_subs
        app.job_queue.run_repeating(check_expired_subs, interval=10, first=10)

        from paidsub.handlers import expiry_reminder_tick
        app.job_queue.run_repeating(expiry_reminder_tick, interval=1800, first=180)

        # LTE: раз в 30 минут переводим подписки без LTE на fallback-сквад
        # и возвращаем их, когда месяц сменился или лимит вырос
        from paidsub.handlers import lte_fallback_tick
        app.job_queue.run_repeating(lte_fallback_tick, interval=1800, first=300)

        async def _healthcheck_job(ctx):
            """Следит за панелью, выдачей подписок и узлами.

            Уведомляет только при смене состояния, чтобы не спамить каждые 5 минут.
            """
            from config import ADMIN_ID, load_config, save_config
            from services.panel import probe_servers, is_configured
            from core.log_channel import send_log

            cfg = load_config()
            if not is_configured():
                return

            r = await probe_servers()
            panel_ok = r["panel"]["ok"]
            sub_ok = r["sub"]["ok"]
            dead = sorted(
                n["tag"] for n in r["nodes"] if n["enabled"] and not n["reachable"]
            )

            alerts = []
            changed = False

            if panel_ok != cfg.get("panel_healthy", True):
                cfg["panel_healthy"] = panel_ok
                changed = True
                alerts.append(
                    "🟢 <b>Панель снова доступна.</b>" if panel_ok else
                    "🔴 <b>Панель недоступна!</b>\n"
                    f"<code>{r['panel'].get('error', '?')}</code>"
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

            if panel_ok and dead != (cfg.get("dead_nodes") or []):
                prev = cfg.get("dead_nodes") or []
                cfg["dead_nodes"] = dead
                changed = True
                if dead:
                    alerts.append(
                        "🔴 <b>Не работают узлы:</b>\n" +
                        "\n".join(f"• {t}" for t in dead)
                    )
                elif prev:
                    alerts.append("🟢 <b>Все узлы снова доступны.</b>")

            if changed:
                save_config(cfg)
            for text in alerts:
                try:
                    await ctx.bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML")
                    await send_log(ctx.bot, text)
                except Exception:
                    pass

        app.job_queue.run_repeating(_healthcheck_job, interval=300, first=60)

        async def _anore_poll_job(ctx):
            """Опрашивает выставленные счета и засчитывает оплату.

            Вебхук anore обычно подтверждает оплату мгновенно, а опрос —
            страховка, если вебхук не дойдёт: тот же счёт не засчитается
            дважды, потому что подтверждение ставит статус до начисления.
            """
            import services.anore_api as an
            from core.database import (
                get_pending_payments, set_payment_status, expire_stale_payments,
            )
            if not an.is_configured():
                return

            # счёт anore живёт ограниченное время — дальше опрашивать нечего
            ttl = int(load_config().get("invoice_ttl_minutes", 60) or 60)
            await expire_stale_payments(ttl)
            pending = await get_pending_payments("anore", limit=40)
            if not pending:
                return

            # статусы читаем параллельно: последовательно 40 счетов могли бы
            # растянуться дольше, чем интервал самой задачи
            import asyncio
            statuses = await asyncio.gather(
                *[an.get_status(p[3]) for p in pending if p[3]],
                return_exceptions=True,
            )

            from handlers.payments import confirm_provider_payment
            for p, r in zip([p for p in pending if p[3]], statuses):
                if isinstance(r, Exception):
                    continue
                if not r.get("ok"):
                    if r.get("not_found"):
                        await set_payment_status(p[0], "error", "платёж не найден")
                    continue
                status = r.get("status")
                if status == an.STATUS_PAID:
                    await confirm_provider_payment(ctx.bot, p)
                elif status == an.STATUS_EXPIRED:
                    await set_payment_status(p[0], "expired")

        poll_every = int(load_config().get("invoice_poll_seconds", 60) or 60)
        app.job_queue.run_repeating(_anore_poll_job, interval=poll_every, first=30)


        async def _recovered_job(ctx):
            """После сбоя сообщает, что бот снова в строю.

            Метку оставляет сторож (scripts/notify_failure.sh). Проверяем через
            минуту после старта: в крэш-цикле бот упадёт раньше и не отчитается
            ложным «всё хорошо».
            """
            import os
            from config import ADMIN_ID
            marker = "/var/lib/drebol-vpn/crashed"
            if not os.path.exists(marker):
                return
            for path in (marker, "/var/lib/drebol-vpn/last_alert"):
                try:
                    os.remove(path)
                except OSError:
                    pass
            try:
                await ctx.bot.send_message(
                    chat_id=ADMIN_ID,
                    text="🟢 <b>Бот снова работает</b> после сбоя.",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        app.job_queue.run_once(_recovered_job, when=60)

        from handlers.control import digest_tick, purge_tick, connect_help_tick
        app.job_queue.run_repeating(digest_tick, interval=600, first=90)
        app.job_queue.run_repeating(purge_tick, interval=24 * 3600, first=3600)
        app.job_queue.run_repeating(connect_help_tick, interval=1800, first=240)

        # сайт сам подхватывает новые цены и настройки
        from web.site_deploy import site_sync_tick
        app.job_queue.run_repeating(site_sync_tick, interval=120, first=300)

        # после обновления с GitHub — один раз проверить, поменялся ли сайт
        from web.site_deploy import site_update_pending_job
        app.job_queue.run_once(site_update_pending_job, when=15)

        from features.fraud import fraud_tick
        app.job_queue.run_repeating(fraud_tick, interval=1800, first=420)

        from features.blacklist import blacklist_sync_tick
        bl_hours = int(load_config().get("blacklist_sync_hours", 6) or 6)
        app.job_queue.run_repeating(blacklist_sync_tick, interval=bl_hours * 3600, first=120)

        from features.blacklist import blacklist_expire_tick
        app.job_queue.run_repeating(blacklist_expire_tick, interval=300, first=150)

        from features.winback import winback_tick
        app.job_queue.run_repeating(winback_tick, interval=3600, first=600)

        from web.webapi import sessions_tick
        app.job_queue.run_repeating(sessions_tick, interval=24 * 3600, first=900)

        # синхронизация с панелью по расписанию: тик каждые 15 минут
        # проверяет, подошло ли время, и запускает сверку, если пора
        from services.remnawave import panel_sync_tick
        app.job_queue.run_repeating(panel_sync_tick, interval=900, first=900)

    # Личный кабинет: http-api для сайта и мини-приложения.
    # Бота отдаём в API, чтобы оно само слало коды сброса пароля в чат.
    from web.webapi import start_server
    started = await start_server(app.bot)
    if started.get("ok"):
        print(f"Кабинет слушает порт {started.get('port')}")



def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Журнал: группа -1 видит каждое событие раньше остальных обработчиков
    # и не мешает им — обработка идёт дальше как обычно.
    app.add_handler(TypeHandler(Update, log_update), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(callback_router))
    # /h123 — открыть запись истории подписок прямо из ленты «Контроля»
    from handlers.control import hist_command
    app.add_handler(MessageHandler(filters.Regex(r"^/h\d+$"), hist_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_media))
    app.add_error_handler(_on_error)

    print("Бот запущен...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
