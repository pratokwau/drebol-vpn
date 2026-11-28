"""Проверка наших доменов и IP по спискам блокировок РКН.

Экран в админке «🌐 Проверка операторов»: Cheburcheck
(services/cheburcheck.py) — статус доменов и IP прямых хостов по
спискам блокировок: цель в списках или нет, заблокированные
подсети, счётчики жалоб.

Запросы к Cheburcheck идут по одному, с паузами и повторами при
лимитах (HTTP 429) — проверка занимает от ~30 секунд до пары
минут, зато каждая цель доводится до окончательного ответа, а не
остаётся «не проверенной». Сначала показываем «⏳ Проверяю…»,
потом таблицу.

Настройки («⚙️ Настройки»): какие домены проверять (IP прямых
хостов проверяются всегда). Хранятся в config.json, ключ
"netcheck": {"domains": [подписи], "operators": [подписи]} — поле
operators осталось от Globalping-эпохи и нужно только веб-админке;
здесь оно не трогается. Хотя бы один домен остаётся включённым
всегда.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config
import services.cheburcheck as cc
import services.globalping as gp  # только OPERATORS для веб-админки


def get_netcheck_selection() -> tuple[list[tuple[str, str]],
                                      list[tuple[str, str]]]:
    """Включённые домены (и legacy-операторы для веб-админки).

    Возвращает пару (домены, операторы): домены — из
    services.cheburcheck.TARGETS по config.json, операторы —
    полный список Globalping, который по-прежнему читает
    веб-админка. Телеграм-проверка операторов не использует.
    """
    cfg = load_config().get("netcheck") or {}
    dom_labels = set(cfg.get("domains") or [])
    op_labels = set(cfg.get("operators") or [])
    domains = [(label, d) for label, d in cc.TARGETS
               if not dom_labels or label in dom_labels]
    operators = [(label, a) for label, a in gp.OPERATORS
                 if not op_labels or label in op_labels]
    return (domains or cc.TARGETS, operators or gp.OPERATORS)


def _save_selection(domains: list[str], operators: list[str]) -> None:
    cfg = load_config()
    cfg["netcheck"] = {"domains": domains, "operators": operators}
    save_config(cfg)


def _render(results: list[dict]) -> str:
    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m %H:%M")
    ok, blocked, unknown, error = cc.summarize(results)
    lines = ["🌐 <b>Проверка операторов</b>",
             f"<i>Проверено {now} МСК · Cheburcheck · списки блокировок РКН</i>",
             ""]
    problems: list[str] = []
    for r in results:
        head = f"<b>{r['label']}</b> — {r['shown']}"
        state = r.get("state")
        if state == "ok":
            tail = "✅ не в списках"
            if r.get("complaints"):
                tail += f" · ⚠️ жалоб за 14 дней: {r['complaints']}"
            lines.append(f"{head}\n{tail}")
        elif state == "blocked":
            tail = "❌ <b>в списках блокировок</b>"
            if r.get("subnets"):
                tail += " · подсети: " + ", ".join(
                    str(s) for s in r["subnets"][:3])
            lines.append(f"{head}\n{tail}")
            problems.append(r["label"])
        elif state == "unknown":
            lines.append(f"{head}\n❔ нет данных в базе Cheburcheck")
        else:
            lines.append(f"{head}\n⚠️ не проверено ({r.get('error') or 'ошибка'})")
        lines.append("")
    if problems:
        lines.append("❌ <b>В списках блокировок:</b> " + ", ".join(problems))
    elif error == 0:
        lines.append(f"✅ <b>В списках никого нет.</b> Чисто: {ok} · "
                     f"нет данных: {unknown}")
    else:
        lines.append(f"✅ Чисто: {ok} · ❔ нет данных: {unknown} · "
                     f"⚠️ не проверено: {error}")
    return "\n".join(lines).strip()


def _settings_keyboard(note: str = "") -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура экрана настроек (только домены)."""
    sel_domains, _ = get_netcheck_selection()
    sel_dom = {label for label, _ in sel_domains}
    lines = ["⚙️ <b>Настройки проверки</b>", "",
             "<i>Выбери, какие домены проверять. IP прямых хостов "
             "(Германия, Швеция, Латвия, Германия-2) проверяются "
             "всегда. Хотя бы один домен остаётся включённым.</i>", "",
             "<b>Домены:</b>"]
    for label, domain in cc.TARGETS:
        mark = "✅" if label in sel_dom else "⬜"
        lines.append(f"{mark} {label} — {domain}")
    if note:
        lines.append("")
        lines.append(f"⚠️ {note}")

    def b(text, cb):
        return InlineKeyboardButton(text, callback_data=cb)

    rows = []
    dom_row = []
    for i, (label, _) in enumerate(cc.TARGETS):
        mark = "✅" if label in sel_dom else "⬜"
        dom_row.append(b(f"{mark} {label}", f"netcheck_toggle:domain:{i}"))
        if len(dom_row) == 2:
            rows.append(dom_row)
            dom_row = []
    if dom_row:
        rows.append(dom_row)
    rows.append([b("🔄 Проверить сейчас", "netcheck_run")])
    rows.append([b("◀️ Назад", "netcheck_menu")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def handle_netcheck_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    """Экран «Проверка операторов»: что проверяется и кнопка запуска."""
    if context:
        context.user_data.pop("state", None)
    domains, _ = get_netcheck_selection()
    targets = ", ".join(d for _, d in domains)
    lines = [
        "🌐 <b>Проверка операторов</b>", "",
        "<i>Проверка по спискам блокировок РКН через Cheburcheck: "
        "домены и IP наших серверов — в списках они или нет.</i>",
        "",
        f"Домены: {targets}",
        "Плюс IP прямых хостов: Германия, Швеция, Латвия, Германия-2 "
        "(адреса определяются по именам хостов в момент проверки).", "",
        "<i>Запросы идут по одному с паузами — Cheburcheck режет "
        "частые запросы лимитом, поэтому проверка занимает от "
        "~30 секунд до пары минут, но дожидается окончательного "
        "ответа по каждой цели. «❔ нет данных» значит, что цели "
        "нет в базе Cheburcheck — это не блокировка.</i>",
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
    """Экран настроек: вкл/выкл домены проверки."""
    text, markup = _settings_keyboard()
    await query.edit_message_text(
        text, parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=markup,
    )


async def handle_netcheck_toggle(query, context: ContextTypes.DEFAULT_TYPE,
                                 kind: str, idx: int):
    """Переключает домен в настройках и перерисовывает экран.

    kind="operator" — наследие Globalping-эпохи (кнопки на старых
    сообщениях): просто перерисовываем экран, операторы больше
    не настраиваются.
    """
    note = ""
    if kind == "domain":
        domains, operators = get_netcheck_selection()
        labels = [label for label, _ in domains]
        all_labels = [label for label, _ in cc.TARGETS]
        if 0 <= idx < len(all_labels):
            toggled = all_labels[idx]
            if toggled in labels and len(labels) <= 1:
                note = "Должен остаться хотя бы один домен."
            else:
                labels = ([l for l in labels if l != toggled]
                          if toggled in labels else labels + [toggled])
                _save_selection(labels,
                                [label for label, _ in operators])
    text, markup = _settings_keyboard(note)
    await query.edit_message_text(
        text, parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=markup,
    )


async def handle_netcheck_run(query, context: ContextTypes.DEFAULT_TYPE):
    """Запускает проверку и показывает таблицу результатов."""
    await query.edit_message_text(
        "⏳ <b>Проверяю по спискам блокировок…</b>\n\n"
        "<i>Запросы идут по одному: от ~30 секунд до пары минут. "
        "При лимите Cheburcheck жду и повторяю, пока каждая цель "
        "не даст окончательный ответ.</i>",
        parse_mode="HTML",
    )
    domains, _ = get_netcheck_selection()
    try:
        results = await cc.check_all(domains)
    except Exception as exc:  # сеть легла, Cheburcheck недоступен и т.п.
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
