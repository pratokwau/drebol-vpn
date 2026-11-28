"""Проверка наших доменов и IP по блокировкам и доступности из РФ.

Экран в админке «🌐 Проверка операторов», два слоя:

1. GhostMesh (services/ghostmesh.py) — главный: живые пробы из
   ~23 российских сетей пытаются подключиться к доменам и IP
   прямых хостов. Ловит ТСПУ-блокировки по IP, которых нет в
   публичных списках (Швеция, 2026-11-28).
2. Cheburcheck (services/cheburcheck.py) — статус тех же целей
   по спискам блокировок РКН: в списках или нет, заблокированные
   подсети, счётчики жалоб.

Оба сервиса режут частые запросы лимитами, поэтому запросы идут
по одному, с паузами и повторами до окончательного ответа —
проверка занимает от ~30 секунд до пары минут. Сначала
показываем «⏳ Проверяю…», потом таблицу. Сбой одного слоя не
роняет второй — его блок показывается как недоступный.

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
import services.ghostmesh as gm
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


def _render_ghost(results: list[dict] | None) -> list[str]:
    """Блок GhostMesh: доступность целей из российских сетей."""
    lines = ["📡 <b>Доступность из России (GhostMesh)</b>"]
    if results is None:
        lines.append("⚠️ GhostMesh недоступен — проверка из "
                     "российских сетей в этот раз не удалась.")
        return lines
    problems: list[str] = []
    for r in results:
        head = f"<b>{r['label']}</b> — {r['shown']}"
        state = r.get("state")
        if state == "ok":
            tail = f"✅ доступен · проб: {r['total']}"
            if r.get("available") == 0 and r.get("tls"):
                tail += " (по голому IP только TLS-ошибки — это норма)"
            lines.append(f"{head}\n{tail}")
        elif state == "partial":
            nets = ", ".join(r.get("failed_networks", [])[:4])
            tail = (f"⚠️ <b>частично недоступен</b>: нет связи у "
                    f"{r['failed']} из {r['total']} проб")
            if nets:
                tail += f" · сети: {nets}"
            lines.append(f"{head}\n{tail}")
            problems.append(r["label"])
        elif state == "blocked":
            nets = ", ".join(r.get("failed_networks", [])[:4])
            tail = (f"❌ <b>блок ТСПУ</b>: нет связи у {r['failed']} "
                    f"из {r['total']} проб")
            if nets:
                tail += f" · сети: {nets}"
            lines.append(f"{head}\n{tail}")
            problems.append(r["label"])
        else:
            lines.append(f"{head}\n⚠️ не проверено ({r.get('error') or 'ошибка'})")
    ok, partial, blocked, error = gm.summarize(results)
    lines.append("")
    if blocked or partial:
        lines.append(f"❌ <b>Проблемы:</b> {', '.join(problems)} · "
                     f"✅ доступно: {ok} · ⚠️ не проверено: {error}")
    else:
        lines.append(f"✅ Все цели доступны из России · доступно: {ok} · "
                     f"⚠️ не проверено: {error}")
    return lines


def _render_chebur(results: list[dict] | None) -> list[str]:
    """Блок Cheburcheck: статус целей по спискам блокировок РКН."""
    lines = ["🛡 <b>Списки блокировок (Cheburcheck)</b>"]
    if results is None:
        lines.append("⚠️ Cheburcheck недоступен — статус по спискам "
                     "в этот раз не проверен.")
        return lines
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
    ok, blocked, unknown, error = cc.summarize(results)
    lines.append("")
    if blocked:
        lines.append(f"❌ <b>В списках: {blocked}</b> · ✅ чисто: {ok} · "
                     f"❔ нет данных: {unknown} · ⚠️ ошибок: {error}")
    else:
        lines.append(f"✅ В списках никого нет · чисто: {ok} · "
                     f"❔ нет данных: {unknown} · ⚠️ ошибок: {error}")
    return lines


def _render(ghost: list[dict] | None, chebur: list[dict] | None) -> str:
    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m %H:%M")
    lines = ["🌐 <b>Проверка операторов</b>",
             f"<i>Проверено {now} МСК</i>", ""]
    lines.extend(_render_ghost(ghost))
    lines.append("")
    lines.extend(_render_chebur(chebur))
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
        "<i>Два слоя. GhostMesh: живые пробы из ~23 российских "
        "сетей пытаются подключиться к нашим доменам и IP — ловит "
        "блоки ТСПУ. Cheburcheck: те же цели по спискам "
        "блокировок РКН.</i>",
        "",
        f"Домены: {targets}",
        "Плюс IP прямых хостов: Германия, Швеция, Латвия, Германия-2 "
        "(адреса определяются по именам хостов в момент проверки).", "",
        "<i>Проверка занимает от ~30 секунд до пары минут: "
        "GhostMesh реально гоняет пробы по российским сетям, а "
        "при лимитах оба сервиса ждут и повторяют до "
        "окончательного ответа по каждой цели. «❔ нет данных» у "
        "Cheburcheck значит, что цели нет в его базе — это не "
        "блокировка.</i>",
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
        "⏳ <b>Проверяю доступность и списки…</b>\n\n"
        "<i>GhostMesh гоняет пробы из российских сетей, Cheburcheck "
        "смотрит списки РКН. От ~30 секунд до пары минут: при "
        "лимитах жду и повторяю до окончательного ответа.</i>",
        parse_mode="HTML",
    )
    domains, _ = get_netcheck_selection()
    ghost = chebur = None
    try:
        ghost = await gm.check_all(domains)
    except Exception:
        ghost = None
    try:
        chebur = await cc.check_all(domains)
    except Exception:
        chebur = None
    if ghost is None and chebur is None:
        await query.edit_message_text(
            "❌ <b>Не удалось проверить</b>\n\n"
            "<i>Оба сервиса недоступны. Попробуй ещё раз через минуту.</i>",
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
        _render(ghost, chebur), parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Проверить ещё раз",
                                  callback_data="netcheck_run"),
             InlineKeyboardButton("◀️ Назад",
                                  callback_data="netcheck_menu")],
        ]),
    )
