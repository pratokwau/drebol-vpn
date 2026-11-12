"""Утренняя синхронизация: сводка, сверка Platega, проверка операторов,
алерты — всё в одно время (по умолчанию 09:00 МСК, меняется в настройках).

Сводка приходит админу в личку каждый день: вчерашняя выручка нетто,
новые пользователи, возвраты, деньги за месяц, заканчивающиеся подписки,
тикеты, падения за сутки. Сверка с Platega — в той же сводке. Проверка
операторов — только когда пора (раз в 2 дня, дата последней проверки
хранится в конфиге). Алерты о падениях — сразу, как только что-то легло,
и тоже выключаются здесь.
"""

import re
from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import ADMIN_ID, load_config, save_config

TZ = ZoneInfo("Europe/Moscow")
JOB_NAME = "morning_sync"
DEFAULTS = {
    "time": "09:00",
    "enabled": True,
    "reconcile": True,
    "netcheck": True,
    "netcheck_days": 2,
    "netcheck_last_run": None,
    "alerts": True,
}

_FALL_LABELS = {
    "panel": "Панель",
    "sub": "Ссылки подписок",
    "site:vpn.drbl.tech": "Сайт",
    "site:key.drbl.tech": "Страница подписки",
}


def get_morning_cfg() -> dict:
    """Настройки синхронизации: дефолты + то, что задал админ."""
    cfg = load_config().get("morning_sync") or {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    return out


def save_morning_cfg(patch: dict) -> dict:
    """Сохраняет часть настроек, возвращает полные."""
    cfg = load_config()
    cur = dict(cfg.get("morning_sync") or {})
    cur.update(patch)
    cfg["morning_sync"] = cur
    save_config(cfg)
    return get_morning_cfg()


def parse_time(text: str) -> tuple[int, int] | None:
    """«9:00», «09:00», «9.30» -> (9, 0). Иначе None."""
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", text or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h, mi


def alerts_enabled() -> bool:
    """Выключатель алертов о падениях (читает проверку здоровья)."""
    return bool(get_morning_cfg().get("alerts", True))


def schedule_morning_sync(application) -> None:
    """(Пере)создаёт ежедневную задачу по настройкам.

    Вызывать при старте бота и при каждом изменении времени/включения.
    Старая задача удаляется, чтобы не было двух сводок.
    """
    jq = getattr(application, "job_queue", None)
    if jq is None:
        return
    for job in jq.get_jobs_by_name(JOB_NAME):
        job.schedule_removal()
    cfg = get_morning_cfg()
    if not cfg.get("enabled"):
        return
    parsed = parse_time(cfg.get("time") or "") or (9, 0)
    jq.run_daily(
        morning_sync_job,
        time=dtime(parsed[0], parsed[1], tzinfo=TZ),
        name=JOB_NAME,
    )


def _fall_label(f: dict) -> str:
    target = f.get("target") or ""
    if target.startswith("node:"):
        return f"Узел {target[5:]}"
    return _FALL_LABELS.get(target, target)


async def _reconcile_section() -> str:
    """Сверка с Platega одной секцией сводки (только отчёт, без исправлений)."""
    import services.platega_api as pg
    if not pg.is_configured():
        return "🔍 Сверка с Platega: ⚠️ Platega не настроена."
    try:
        from handlers.reconcile import run_reconciliation
        res = await run_reconciliation()
    except Exception as exc:
        return f"🔍 Сверка с Platega: ❌ не удалось проверить: <code>{exc}</code>"
    if res["checked"] == 0:
        return "🔍 Сверка с Platega: счетов за 60 дней нет."
    if not res["issues"]:
        return (f"🔍 Сверка с Platega: ✅ всё сходится "
                f"({res['checked']} счетов).")
    lines = [f"🔍 Сверка с Platega: ⚠️ расхождений "
             f"<b>{len(res['issues'])}</b>"]
    if res["impact"]:
        lines.append(f"💸 Прибыль завышена на: <b>{res['impact']} ₽</b>")
    for row, iss in res["issues"][:5]:
        lines.append(f"• #{row[0]} · {row[3]} ₽ · {iss['text']}")
    if len(res["issues"]) > 5:
        lines.append(f"• …и ещё {len(res['issues']) - 5}")
    lines.append("<i>Исправить: 💰 Финансы → 🔍 Сверка с Platega.</i>")
    return "\n".join(lines)


async def _netcheck_section(cfg: dict) -> tuple[str | None, bool]:
    """Проверка операторов, если пора. Возвращает (текст, запускалась ли)."""
    days = int(cfg.get("netcheck_days") or 2)
    last = cfg.get("netcheck_last_run")
    if last:
        try:
            if (date.today() - date.fromisoformat(str(last))).days < days:
                return None, False
        except ValueError:
            pass
    try:
        import services.globalping as gp
        from handlers.netcheck import get_netcheck_selection
        domains, operators = get_netcheck_selection()
        results = await gp.check_all(domains, operators)
    except Exception as exc:
        return (f"🌐 Проверка операторов: ❌ не удалось проверить: "
                f"<code>{exc}</code>"), True
    marks = gp.summarize_operators(results)
    ok, blocked, _no_probe, error = gp.summarize(results)
    line = ("🌐 Проверка операторов: " +
            " · ".join(f"{label} {mark}" for label, mark in marks.items()))
    problems = [f"{r['label']} — {label}"
                for r in results
                for label, op in (r.get("operators") or {}).items()
                if op.get("state") == "blocked"]
    if problems:
        line += "\n🔴 <b>Заблокировано:</b> " + ", ".join(problems)
    elif blocked == 0 and error == 0:
        line += "\n✅ Всё доступно."
    return line, True


async def morning_sync_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ежедневная сводка админу: цифры + сверка + операторы (если пора)."""
    cfg = get_morning_cfg()
    if not cfg.get("enabled"):
        return
    lines = [f"🌅 <b>Утренняя сводка</b> · "
             f"{datetime.now(TZ).strftime('%d.%m')}", ""]
    try:
        import time as _time
        from core.database import (
            finance_summary, get_dashboard_stats,
            get_digest_stats, get_downtime_events,
            get_unread_tickets_count,
        )
        from paidsub.storage import count_paid_soon
        from handlers.finance import current_period
        d = await get_digest_stats()
        fin = await finance_summary(current_period())
        s = await get_dashboard_stats()
        unread = await get_unread_tickets_count()
        soon = await count_paid_soon()
        falls = await get_downtime_events(int(_time.time()) - 86400)
        open_falls = [f for f in falls if not f.get("ended_at")]
        lines.append(
            f"💵 Вчера: <b>{d['revenue_yesterday']} ₽</b> · "
            f"оплат {d['payments_yesterday']} · "
            f"новых {d['users_yesterday']}")
        if d["refunds_yesterday"]:
            lines.append(
                f"↩️ Возвраты вчера: <b>{d['refunds_yesterday']} ₽</b>")
        lines.append(
            f"💹 Месяц: доход <b>{fin['income']} ₽</b> · "
            f"прибыль <b>{fin['profit']} ₽</b>")
        if fin.get("refunds"):
            lines.append(
                f"↩️ Возвраты за месяц: <b>{fin['refunds']} ₽</b>")
        lines.append(
            f"👥 Пользователей: <b>{s['users_total']}</b> · "
            f"активных подписок <b>{s['paid_active']}</b>")
        if soon:
            lines.append(f"⏳ Заканчиваются (3 дня): <b>{soon}</b>")
        if unread:
            lines.append(f"🎫 Открытых тикетов: <b>{unread}</b>")
        if open_falls:
            lines.append("🔴 Сейчас лежит: " +
                         ", ".join(_fall_label(f) for f in open_falls))
        elif falls:
            lines.append(
                f"📉 Падений за сутки: <b>{len(falls)}</b> (все закрыты)")
    except Exception as exc:
        lines.append(f"⚠️ Сводку собрать не удалось: <code>{exc}</code>")
    if cfg.get("reconcile"):
        lines.append("")
        lines.append(await _reconcile_section())
    if cfg.get("netcheck"):
        section, ran = await _netcheck_section(cfg)
        if section:
            lines.append("")
            lines.append(section)
        if ran:
            save_morning_cfg(
                {"netcheck_last_run": date.today().isoformat()})
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID, text="\n".join(lines), parse_mode="HTML")
    except Exception:
        pass


def _toggle_label(on: bool) -> str:
    return "✅ вкл" if on else "❌ выкл"


async def handle_morning_menu(query,
                              context: ContextTypes.DEFAULT_TYPE):
    """Экран настроек синхронизации."""
    cfg = get_morning_cfg()
    lines = [
        "⏰ <b>Синхронизация</b>", "",
        f"🕘 Время: <b>{cfg['time']}</b> МСК · каждый день",
        f"🌅 Сводка: <b>{_toggle_label(cfg['enabled'])}</b>",
        f"🔍 Сверка с Platega: <b>{_toggle_label(cfg['reconcile'])}</b>",
        f"🌐 Проверка операторов: <b>{_toggle_label(cfg['netcheck'])}</b>"
        f" · раз в {cfg['netcheck_days']} дн.",
        f"🔔 Алерты о падениях: <b>{_toggle_label(cfg['alerts'])}</b>",
        "",
        "<i>Сводка приходит тебе в личку. Проверка операторов — только "
        "когда пора. Алерты — сразу, как только что-то легло.</i>",
    ]
    kb = [
        [InlineKeyboardButton("🕘 Изменить время",
                              callback_data="morning_set_time")],
        [InlineKeyboardButton(
            f"🌅 Сводка: {_toggle_label(cfg['enabled'])}",
            callback_data="morning_toggle:enabled")],
        [InlineKeyboardButton(
            f"🔍 Сверка Platega: {_toggle_label(cfg['reconcile'])}",
            callback_data="morning_toggle:reconcile")],
        [InlineKeyboardButton(
            f"🌐 Операторы: {_toggle_label(cfg['netcheck'])}",
            callback_data="morning_toggle:netcheck")],
        [InlineKeyboardButton(
            f"🔔 Алерты: {_toggle_label(cfg['alerts'])}",
            callback_data="morning_toggle:alerts")],
        [InlineKeyboardButton("▶️ Запустить сейчас",
                              callback_data="morning_run_now")],
        [InlineKeyboardButton("◀️ Назад в админку",
                              callback_data="admin_panel")],
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb))


async def handle_morning_toggle(query, context: ContextTypes.DEFAULT_TYPE,
                                key: str):
    """Переключатель в настройках синхронизации."""
    if key not in ("enabled", "reconcile", "netcheck", "alerts"):
        return
    cfg = get_morning_cfg()
    save_morning_cfg({key: not cfg.get(key, True)})
    if key == "enabled":
        schedule_morning_sync(context.application)
    await handle_morning_menu(query, context)


async def handle_morning_set_time(query, context: ContextTypes.DEFAULT_TYPE):
    """Просит прислать время сводки."""
    from core.states import AWAITING_MORNING_TIME
    context.user_data["state"] = AWAITING_MORNING_TIME
    await query.edit_message_text(
        "🕘 <b>Во сколько присылать сводку?</b>\n\n"
        "Пришли время в формате <b>ЧЧ:ММ</b> (МСК), например "
        "<code>09:00</code> или <code>08:30</code>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Отмена",
                                 callback_data="morning_menu")]]),
    )


async def apply_morning_time(message, context) -> str | None:
    """Применяет введённое время. Возвращает «ЧЧ:ММ» или None при ошибке."""
    parsed = parse_time(message.text or "")
    if not parsed:
        return None
    new_time = f"{parsed[0]:02d}:{parsed[1]:02d}"
    save_morning_cfg({"time": new_time})
    schedule_morning_sync(context.application)
    context.user_data.pop("state", None)
    return new_time


async def handle_morning_run_now(query, context: ContextTypes.DEFAULT_TYPE):
    """Запускает сводку прямо сейчас (для проверки)."""
    await query.edit_message_text("⏳ Собираю сводку…")
    await morning_sync_job(context)
    await handle_morning_menu(query, context)
    try:
        await query.answer("✅ Сводка отправлена")
    except Exception:
        pass
