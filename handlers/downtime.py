"""Статистика падений серверов: аптайм, простой, последние инциденты.

История пишется проверкой здоровья (bot.py, раз в 5 минут) в таблицу
downtime_events: панель, ссылки подписок, сайт, страница подписки
и каждый узел. Экран «📉 Падения и сбои» — из «Панель и узлы» и
с экрана «🩺 Здоровье узлов».
"""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config
from core.database import downtime_summary, get_downtime_events

MSK = ZoneInfo("Europe/Moscow")
WINDOW_DAYS = 30

KIND_ORDER = {"service": 0, "site": 1, "node": 2}


def target_label(target: str) -> str:
    if target == "panel":
        return "Панель"
    if target == "sub":
        return "Ссылки подписок"
    if target.startswith("site:"):
        return ("Сайт" if target == "site:vpn.drbl.tech"
                else "Страница подписки")
    if target.startswith("node:"):
        return f"Узел {target[5:]}"
    return target


def _fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, MSK).strftime("%d.%m %H:%M")


def _fmt_dur(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    if minutes:
        return f"{minutes} мин"
    return f"{seconds} с"


def _uptime_pct(downtime_sec: int, window_sec: int) -> str:
    if window_sec <= 0:
        return "—"
    pct = 100.0 * (1 - downtime_sec / window_sec)
    return f"{pct:.1f}%"


def _render(now: int, since: int, summary: dict, events: list[dict],
            current: dict[str, bool]) -> str:
    window_start = max(since, now - WINDOW_DAYS * 86400)
    window_sec = max(1, now - window_start)
    lines = ["📉 <b>Падения и сбои</b>",
             f"<i>Наблюдение с {_fmt_ts(since)} · окно "
             f"{WINDOW_DAYS} дней</i>", ""]

    # Сейчас: живы или лежат
    lines.append("<b>Сейчас:</b>")
    for target in _ordered_targets(summary, current):
        ok = current.get(target)
        icon = "🟢" if ok else ("🔴" if ok is False else "⚪️")
        tail = ""
        if ok is False and target in summary:
            open_since = summary[target].get("open_since")
            if open_since:
                tail = f" · лежит с {_fmt_ts(open_since)}"
        lines.append(f"{icon} {target_label(target)}{tail}")
    lines.append("")

    # Статистика за окно
    if not summary:
        lines.append("Пока падений не зафиксировано — статистика копится.")
    else:
        lines.append(f"<b>За {WINDOW_DAYS} дней:</b>")
        for target in _ordered_targets(summary, current):
            st = summary.get(target) or {
                "kind": "", "incidents": 0, "downtime_sec": 0,
                "open_since": None, "last_start": None, "last_end": None,
            }
            uptime = _uptime_pct(st["downtime_sec"], window_sec)
            line = (f"<b>{target_label(target)}</b> — аптайм {uptime} · "
                    f"падений: {st['incidents']} · "
                    f"простой: {_fmt_dur(st['downtime_sec'])}")
            if st.get("open_since"):
                line += " · <b>лежит сейчас</b>"
            elif st.get("last_start"):
                last = st["last_start"]
                last_end = st.get("last_end")
                span = (_fmt_ts(last) + (" — " + _fmt_ts(last_end)
                        if last_end else " — сейчас"))
                line += f"\n    последнее: {span}"
            lines.append(line)
        lines.append("")
        # Последние падения
        recent = [e for e in events
                  if int(e["started_at"]) >= window_start][:8]
        if recent:
            lines.append("<b>Последние падения:</b>")
            for ev in recent:
                start = int(ev["started_at"])
                end = (int(ev["ended_at"])
                       if ev.get("ended_at") else None)
                span = _fmt_ts(start) + (" — " + _fmt_ts(end)
                                         if end else " — сейчас")
                dur = _fmt_dur((end or now) - start)
                lines.append(f"• {span} ({dur}) · {target_label(ev['target'])}")
    return "\n".join(lines).strip()


def _ordered_targets(summary: dict, current: dict) -> list[str]:
    targets = list(dict.fromkeys(list(summary) + list(current)))
    return sorted(targets,
                  key=lambda t: (KIND_ORDER.get(
                      summary.get(t, {}).get("kind") or
                      ("node" if t.startswith("node:") else
                       "site" if t.startswith("site:") else "service"),
                      9), t))


async def handle_downtime_menu(query, context: ContextTypes.DEFAULT_TYPE):
    """Экран статистики падений: текущее состояние + история за 30 дней."""
    await query.edit_message_text("📉 Собираю статистику падений…")
    from services.panel import probe_servers, probe_sites

    now = int(time.time())
    cfg = load_config()
    since = int(cfg.get("downtime_since") or now)
    # Текущее состояние — живой пробой, а не из базы
    current: dict[str, bool] = {}
    try:
        r = await probe_servers()
        current["panel"] = bool(r["panel"]["ok"])
        if r["panel"]["ok"]:
            current["sub"] = bool(r["sub"]["ok"])
            for n in r["nodes"]:
                if n["enabled"]:
                    current[f"node:{n['tag']}"] = bool(n["reachable"])
    except Exception:
        pass
    try:
        for target, st in (await probe_sites()).items():
            current[target] = bool(st["ok"])
    except Exception:
        pass
    window_start = max(since, now - WINDOW_DAYS * 86400)
    events = await get_downtime_events(window_start)
    summary = downtime_summary(events, window_start, now)
    text = _render(now, since, summary, events, current)
    await query.edit_message_text(
        text, parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить",
                                  callback_data="rw_downtime"),
             InlineKeyboardButton("◀️ Назад",
                                  callback_data="rw_menu")],
        ]),
    )
