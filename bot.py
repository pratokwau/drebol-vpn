import logging

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, TypeHandler, filters,
)

logger = logging.getLogger(__name__)


async def _on_error(update, context):
    """Логирует ошибку обработчика и показывает алерт, вместо мёртвой кнопки."""
    logger.exception("Ошибка обработчика: %s", context.error)
    try:
        from core.database import log_error
        err = context.error
        # log_error сам чистит токены и режет до 300/500 символов
        await log_error("bot", "error",
                        f"{type(err).__name__}: {err}" if err else "неизвестная ошибка")
    except Exception:
        pass
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

    # Бот поддержки — доп. сервис: при каждом старте основного бота
    # переставить его unit (с PartOf) и перезапустить, чтобы он всегда
    # был на свежем коде после обновы. Не блокирует запуск основного бота.
    try:
        if load_config().get("support_bot_token"):
            from services.support_service import ensure_support_bot_running
            _ok, _detail = await ensure_support_bot_running()
            print(f"[support-bot] ensure: {_ok} {_detail}")
    except Exception as e:
        print(f"[support-bot] ensure failed: {e}")

    if app.job_queue:
        from functools import wraps

        def _gated(fn, key):
            """Оборачивает фоновую задачу тумблером из настроек синхронизации.

            Тумблер читается на каждом тике, поэтому выключение в админке
            («⏰ Синхронизация») срабатывает без перезапуска бота.
            """
            @wraps(fn)
            async def _wrapper(ctx):
                from handlers.morning import job_enabled
                if not job_enabled(key):
                    return
                return await fn(ctx)
            return _wrapper

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
            Выключается тумблером «healthcheck» в настройках синхронизации
            (тогда же останавливается и запись падений в статистику).
            """
            from handlers.morning import job_enabled
            if not job_enabled("healthcheck"):
                return
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

            # История падений — в таблицу downtime_events, для экрана
            # «📉 Падения и сбои». Узлы и подписки пишем только пока
            # панель отвечает: иначе их состояние неизвестно, а не «упали».
            import time as _time
            from core.database import record_downtime_status
            _now = int(_time.time())
            if "downtime_since" not in cfg:
                cfg["downtime_since"] = _now
                save_config(cfg)
            await record_downtime_status(
                "panel", "service", panel_ok,
                str(r["panel"].get("error") or ""), now=_now)
            if panel_ok:
                await record_downtime_status(
                    "sub", "service", sub_ok,
                    str(r["sub"].get("error") or ""), now=_now)
                for _n in r["nodes"]:
                    if _n["enabled"]:
                        await record_downtime_status(
                            f"node:{_n['tag']}", "node", _n["reachable"],
                            str(_n.get("error") or ""), now=_now)
            alerts = []
            changed = False

            # Сайт и страница подписки — своим путём через Caddy,
            # независимо от панели.
            from services.panel import probe_sites
            _sites = await probe_sites()
            for _target, _st in _sites.items():
                await record_downtime_status(
                    _target, "site", _st["ok"],
                    str(_st.get("error") or ""), now=_now)
            # переходы сайтов — в алерты: раньше о них молчали,
            # а падение сайта админ узнавал от клиентов
            _site_labels = {
                "site:vpn.drbl.tech": "Сайт vpn.drbl.tech",
                "site:key.drbl.tech": "Страница подписки key.drbl.tech",
            }
            _down_before = set(cfg.get("sites_down") or [])
            _down_now = {t for t, st in _sites.items() if not st["ok"]}
            if _down_now != _down_before:
                cfg["sites_down"] = sorted(_down_now)
                changed = True
                for _t in sorted(_down_now - _down_before):
                    alerts.append(
                        f"🔴 <b>{_site_labels.get(_t, _t)} недоступен!</b>")
                for _t in sorted(_down_before - _down_now):
                    alerts.append(
                        f"🟢 <b>{_site_labels.get(_t, _t)} снова доступен.</b>")

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
            # состояние (panel_healthy и т.п.) пишем всегда, а отправку
            # алертов можно выключить в настройках синхронизации
            from handlers.morning import alerts_enabled
            if not alerts_enabled():
                return
            for text in alerts:
                try:
                    await ctx.bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML")
                    await send_log(ctx.bot, text)
                except Exception:
                    pass

        app.job_queue.run_repeating(_healthcheck_job, interval=300, first=60)

        async def _platega_poll_job(ctx):
            """Опрашивает выставленные счета и засчитывает оплату.

            Колбэк Platega обычно подтверждает оплату мгновенно, а опрос —
            страховка, если колбэк не дойдёт. Двойное начисление исключено:
            подтверждение проходит атомарный claim — кто первым перевёл
            счёт из pending в paid, тот и начисляет.
            """
            import services.platega_api as pg
            from core.database import (
                get_pending_payments, set_payment_status, expire_stale_payments,
                set_partial_refunded,
            )
            if not pg.is_configured():
                return

            # счёт Platega живёт 15 минут (expiresIn 00:15:00) — раньше
            # этого срока оплату ещё можно дождаться, дальше опрашивать
            # нечего; гасим с запасом вдвое
            await expire_stale_payments(pg.INVOICE_TTL_MINUTES * 2)
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

            from types import SimpleNamespace
            from handlers.payments import confirm_provider_payment, finalize_refund
            for p, r in zip([p for p in pending if p[3]], statuses):
                if isinstance(r, Exception):
                    continue
                if not r.get("ok"):
                    if r.get("not_found"):
                        await set_payment_status(p[0], "error", "платёж не найден")
                    continue
                status = r.get("status")
                if status == pg.STATUS_PAID:
                    await confirm_provider_payment(ctx.bot, p)
                elif status == pg.STATUS_CANCELED:
                    await set_payment_status(p[0], "canceled")
                elif status == pg.STATUS_CHARGEBACKED:
                    # возврат пришёл без колбэка — доводим до конца
                    await finalize_refund(SimpleNamespace(bot=ctx.bot), p[0])
                elif status == pg.STATUS_PARTIALLY_REFUNDED:
                    raw = r.get("raw") or {}
                    refunded = raw.get("refundedAmount")
                    if refunded is not None:
                        try:
                            await set_partial_refunded(p[0], int(float(refunded)))
                        except (TypeError, ValueError):
                            pass

        poll_every = int(load_config().get("invoice_poll_seconds", 60) or 60)
        app.job_queue.run_repeating(_platega_poll_job, interval=poll_every, first=30)

        # Напоминание об оплате серверов больше не живёт отдельным
        # run_daily в 23:00 — оно теперь часть утренней синхронизации
        # (время — только там, в 09:00) и включается тумблером
        # «server_reminder» в настройках синхронизации.

        # Утренняя синхронизация: сводка, сверка Platega, операторы —
        # каждый день в 09:00 МСК (время меняется в настройках админки).
        from handlers.morning import schedule_morning_sync
        schedule_morning_sync(app)


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
        app.job_queue.run_repeating(
            _gated(site_sync_tick, "site_sync"), interval=120, first=300)

        # после обновления с GitHub — один раз проверить, поменялся ли сайт
        from web.site_deploy import site_update_pending_job
        app.job_queue.run_once(site_update_pending_job, when=15)

        from features.fraud import fraud_tick
        app.job_queue.run_repeating(fraud_tick, interval=1800, first=420)

        from features.blacklist import blacklist_sync_tick
        bl_hours = int(load_config().get("blacklist_sync_hours", 6) or 6)
        app.job_queue.run_repeating(
            _gated(blacklist_sync_tick, "blacklist_sync"),
            interval=bl_hours * 3600, first=120)

        from features.blacklist import blacklist_expire_tick
        app.job_queue.run_repeating(blacklist_expire_tick, interval=300, first=150)

        from features.winback import winback_tick
        app.job_queue.run_repeating(winback_tick, interval=3600, first=600)

        from web.webapi import sessions_tick
        app.job_queue.run_repeating(sessions_tick, interval=24 * 3600, first=900)

        # синхронизация с панелью по расписанию: тик каждые 15 минут
        # проверяет, подошло ли время, и запускает сверку, если пора
        from services.remnawave import panel_sync_tick
        app.job_queue.run_repeating(
            _gated(panel_sync_tick, "panel_sync"), interval=900, first=900)

    # Личный кабинет: http-api для сайта и мини-приложения.
    # Бота отдаём в API, чтобы оно само слало коды сброса пароля в чат.
    from web.webapi import start_server
    started = await start_server(app.bot)
    if started.get("ok"):
        print(f"Кабинет слушает порт {started.get('port')}")

    # бот поднялся целиком — одна запись в журнал системных событий
    try:
        from config import ADMIN_ID
        from core.database import log_activity
        await log_activity(ADMIN_ID, "ev:bot_started", "запуск бота", is_admin=True)
    except Exception:
        pass



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
    # /h123 — открыть запись истории подписок прямо из ленты «Логов»
    from handlers.control import hist_command, activity_command, error_command
    app.add_handler(MessageHandler(filters.Regex(r"^/h\d+$"), hist_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/a\d+$"), activity_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/e\d+$"), error_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_media))
    app.add_error_handler(_on_error)

    print("Бот запущен...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
