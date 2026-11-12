"""Проверка доступности наших доменов у российских операторов.

Экран в админке «🌐 Проверка операторов»: кнопка запускает живую
проверку через Globalping — HTTP HEAD с проб на домашних сетях
МТС, МегаФона, Билайна, T2 и Ростелекома. Проверка занимает
10–30 секунд: сначала показываем «⏳ Проверяю…», потом таблицу.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import services.globalping as gp

_SHORT_OP = {
    "МТС": "МТС",
    "МегаФон": "МегаФон",
    "Билайн": "Билайн",
    "T2": "T2",
    "Ростелеком": "РТК",
}


def _op_cell(label: str, op: dict) -> str:
    short = _SHORT_OP.get(label, label)
    state = op.get("state")
    if state == "ok":
        ms = op.get("ms")
        tail = f" · {ms}мс" if ms else ""
        return f"{short} ✅{op.get('code') or ''}{tail}"
    if state == "no_probe":
        return f"{short} —"
    if state == "error":
        return f"{short} ⚠️{op.get('code') or ''}"
    return f"{short} ❌"


def _render(results: list[dict]) -> str:
    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m %H:%M")
    ok, blocked, no_probe, error = gp.summarize(results)
    lines = ["🌐 <b>Доступность у операторов</b>",
             f"<i>Проверено {now} МСК · Globalping · HTTP HEAD</i>", ""]
    problems: list[str] = []
    for r in results:
        ops = r.get("operators")
        if not ops:
            lines.append(f"<b>{r['label']}</b> — {r['domain']}")
            lines.append(f"⚠️ {r.get('error') or 'не проверено'}")
            lines.append("")
            continue
        lines.append(f"<b>{r['label']}</b> — {r['domain']}")
        lines.append(" · ".join(_op_cell(label, op)
                                for label, op in ops.items()))
        lines.append("")
        for label, op in ops.items():
            if op.get("state") == "blocked":
                problems.append(f"{r['label']} — {label}")
            elif op.get("state") == "error":
                problems.append(f"{r['label']} — {label} "
                                f"(ошибка {op.get('code')})")
    if problems:
        lines.append("⚠️ <b>Проблемы:</b> " + ", ".join(problems))
    elif blocked == 0 and no_probe == 0 and error == 0:
        lines.append("✅ <b>Всё доступно со всех операторов.</b>")
    else:
        lines.append(f"✅ Доступно: {ok} · ❌ Недоступно: {blocked} · "
                     f"⚠️ Ошибка сервера: {error} · — без пробы: {no_probe}")
    return "\n".join(lines).strip()


async def handle_netcheck_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    """Экран «Проверка операторов»: что проверяется и кнопка запуска."""
    if context:
        context.user_data.pop("state", None)
    targets = ", ".join(d for _, d in gp.TARGETS)
    operators = ", ".join(label for label, _ in gp.OPERATORS)
    lines = [
        "🌐 <b>Проверка операторов</b>", "",
        "<i>Живая проверка через Globalping: HTTP-запрос с домашних "
        "сетей операторов — так, как сайт видят обычные пользователи.</i>",
        "",
        f"Домены: {targets}",
        f"Операторы: {operators}", "",
        "<i>Проверка занимает 10–30 секунд. «—» значит, что у "
        "Globalping сейчас нет онлайн-пробы в этой сети — это не блок, "
        "просто повтори позже.</i>",
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Проверить сейчас",
                                  callback_data="netcheck_run")],
            [InlineKeyboardButton("◀️ Назад в админку",
                                  callback_data="admin_panel")],
        ]),
    )


async def handle_netcheck_run(query, context: ContextTypes.DEFAULT_TYPE):
    """Запускает проверку и показывает таблицу результатов."""
    await query.edit_message_text(
        "⏳ <b>Проверяю доступность…</b>\n\n"
        "<i>Это занимает 10–30 секунд — жду ответы проб.</i>",
        parse_mode="HTML",
    )
    try:
        results = await gp.check_all()
    except Exception as exc:  # сеть легла, Globalping недоступен и т.п.
        await query.edit_message_text(
            "❌ <b>Не удалось проверить</b>\n\n"
            f"<blockquote><code>{exc}</code></blockquote>\n\n"
            "<i>Попробуй ещё раз через минуту.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз",
                                      callback_data="netcheck_run"),
                 InlineKeyboardButton("◀️ Назад",
                                      callback_data="netcheck_menu")],
            ]),
        )
        return
    await query.edit_message_text(
        _render(results), parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Проверить ещё раз",
                                  callback_data="netcheck_run"),
             InlineKeyboardButton("◀️ Назад",
                                  callback_data="netcheck_menu")],
        ]),
    )
