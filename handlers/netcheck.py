"""Проверка доступности наших доменов у российских операторов.

Экран в админке «🌐 Проверка операторов»: кнопка запускает живую
проверку через Globalping — HTTP HEAD с проб на домашних сетях
МТС, МегаФона, Билайна, T2 и Ростелекома. Проверка занимает
10–30 секунд: сначала показываем «⏳ Проверяю…», потом таблицу.

Результат — в два слоя: сверху итог по операторам (галочка — все
домены доступны, крестик — есть недоступные), ниже подробная
таблица по доменам.

Настройки («⚙️ Настройки»): какие домены и операторы проверять.
Хранятся в config.json, ключ "netcheck": {"domains": [подписи],
"operators": [подписи]}. По умолчанию включены все — это и есть
готовая настройка. Хотя бы один домен и один оператор остаются
включёнными всегда.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config
import services.globalping as gp

_SHORT_OP = {
    "МТС": "МТС",
    "МегаФон": "МегаФон",
    "Билайн": "Билайн",
    "T2": "T2",
    "Ростелеком": "РТК",
}


def get_netcheck_selection() -> tuple[list[tuple[str, str]],
                                      list[tuple[str, str]]]:
    """Включённые домены и операторы из config.json (по умолчанию все)."""
    cfg = load_config().get("netcheck") or {}
    dom_labels = set(cfg.get("domains") or [])
    op_labels = set(cfg.get("operators") or [])
    domains = [(label, d) for label, d in gp.TARGETS
               if not dom_labels or label in dom_labels]
    operators = [(label, a) for label, a in gp.OPERATORS
                 if not op_labels or label in op_labels]
    return (domains or gp.TARGETS, operators or gp.OPERATORS)


def _save_selection(domains: list[str], operators: list[str]) -> None:
    cfg = load_config()
    cfg["netcheck"] = {"domains": domains, "operators": operators}
    save_config(cfg)


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
    marks = gp.summarize_operators(results)
    lines = ["🌐 <b>Доступность у операторов</b>",
             f"<i>Проверено {now} МСК · Globalping · HTTP HEAD</i>", ""]
    # Итог по операторам — галочки и крестики одним взглядом
    if marks:
        lines.append("<b>Операторы:</b> " + " · ".join(
            f"{_SHORT_OP.get(label, label)} {mark}"
            for label, mark in marks.items()))
        lines.append("")
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
    # Подписка: 502 без sub ID — норма, а не поломка
    if any(op.get("sub_id")
           for r in results for op in (r.get("operators") or {}).values()):
        lines.append("")
        lines.append("ℹ️ <i>Подписка: 502 без sub ID — это нормально. "
                     "Страница живёт только по ссылке подписки, а здесь "
                     "важно, что оператор не блокирует домен.</i>")
    return "\n".join(lines).strip()


def _settings_keyboard(domains: list[tuple[str, str]],
                       operators: list[tuple[str, str]],
                       note: str = "") -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура экрана настроек."""
    sel_domains, sel_operators = get_netcheck_selection()
    sel_dom = {label for label, _ in sel_domains}
    sel_op = {label for label, _ in sel_operators}
    lines = ["⚙️ <b>Настройки проверки</b>", "",
             "<i>Выбери, что проверять. Нажатие включает или выключает "
             "домен/оператора. Хотя бы один домен и один оператор "
             "остаются включёнными.</i>", "",
             "<b>Домены:</b>"]
    for label, domain in domains:
        mark = "✅" if label in sel_dom else "⬜"
        lines.append(f"{mark} {label} — {domain}")
    lines.append("")
    lines.append("<b>Операторы:</b>")
    for label, _ in operators:
        mark = "✅" if label in sel_op else "⬜"
        lines.append(f"{mark} {label}")
    if note:
        lines.append("")
        lines.append(f"⚠️ {note}")

    def b(text, cb):
        return InlineKeyboardButton(text, callback_data=cb)

    rows = []
    dom_row = []
    for i, (label, _) in enumerate(domains):
        mark = "✅" if label in sel_dom else "⬜"
        dom_row.append(b(f"{mark} {label}", f"netcheck_toggle:domain:{i}"))
        if len(dom_row) == 2:
            rows.append(dom_row)
            dom_row = []
    if dom_row:
        rows.append(dom_row)
    op_row = []
    for i, (label, _) in enumerate(operators):
        mark = "✅" if label in sel_op else "⬜"
        op_row.append(b(f"{mark} {label}", f"netcheck_toggle:operator:{i}"))
        if len(op_row) == 2:
            rows.append(op_row)
            op_row = []
    if op_row:
        rows.append(op_row)
    rows.append([b("🔄 Проверить сейчас", "netcheck_run")])
    rows.append([b("◀️ Назад", "netcheck_menu")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def handle_netcheck_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    """Экран «Проверка операторов»: что проверяется и кнопка запуска."""
    if context:
        context.user_data.pop("state", None)
    domains, operators = get_netcheck_selection()
    targets = ", ".join(d for _, d in domains)
    ops = ", ".join(label for label, _ in operators)
    lines = [
        "🌐 <b>Проверка операторов</b>", "",
        "<i>Живая проверка через Globalping: HTTP-запрос с домашних "
        "сетей операторов — так, как сайт видят обычные пользователи.</i>",
        "",
        f"Домены: {targets}",
        f"Операторы: {ops}", "",
        "<i>Проверка занимает 10–30 секунд. «—» значит, что у "
        "Globalping сейчас нет онлайн-пробы в этой сети — это не блок, "
        "просто повтори позже.</i>",
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Проверить сейчас",
                                  callback_data="netcheck_run")],
            [InlineKeyboardButton("⚙️ Настройки",
                                  callback_data="netcheck_settings")],
            [InlineKeyboardButton("◀️ Назад в админку",
                                  callback_data="admin_panel")],
        ]),
    )


async def handle_netcheck_settings(query,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Экран настроек: вкл/выкл домены и операторы."""
    text, markup = _settings_keyboard(gp.TARGETS, gp.OPERATORS)
    await query.edit_message_text(
        text, parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=markup,
    )


async def handle_netcheck_toggle(query, context: ContextTypes.DEFAULT_TYPE,
                                 kind: str, idx: int):
    """Переключает домен/оператора в настройках и перерисовывает экран."""
    domains, operators = get_netcheck_selection()
    note = ""
    if kind == "domain":
        labels = [label for label, _ in domains]
        all_labels = [label for label, _ in gp.TARGETS]
        if idx < 0 or idx >= len(all_labels):
            return
        toggled = all_labels[idx]
        if toggled in labels and len(labels) <= 1:
            note = "Должен остаться хотя бы один домен."
        else:
            labels = ([l for l in labels if l != toggled]
                      if toggled in labels else labels + [toggled])
            _save_selection(labels,
                            [label for label, _ in operators])
    else:
        labels = [label for label, _ in operators]
        all_labels = [label for label, _ in gp.OPERATORS]
        if idx < 0 or idx >= len(all_labels):
            return
        toggled = all_labels[idx]
        if toggled in labels and len(labels) <= 1:
            note = "Должен остаться хотя бы один оператор."
        else:
            labels = ([l for l in labels if l != toggled]
                      if toggled in labels else labels + [toggled])
            _save_selection([label for label, _ in domains], labels)
    text, markup = _settings_keyboard(gp.TARGETS, gp.OPERATORS, note)
    await query.edit_message_text(
        text, parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=markup,
    )


async def handle_netcheck_run(query, context: ContextTypes.DEFAULT_TYPE):
    """Запускает проверку и показывает таблицу результатов."""
    await query.edit_message_text(
        "⏳ <b>Проверяю доступность…</b>\n\n"
        "<i>Это занимает 10–30 секунд — жду ответы проб.</i>",
        parse_mode="HTML",
    )
    domains, operators = get_netcheck_selection()
    try:
        results = await gp.check_all(domains, operators)
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
