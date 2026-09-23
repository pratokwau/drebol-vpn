"""Чёрный список: общий из GitHub плюс свои правки.

Кто в списке, не может взять триал, оплатить или продлить подписку — бот
показывает причину и оставляет только поддержку, чтобы можно было оспорить.

• общий список BEDOLAGA-DEV/VPN-BLACKLIST бот обновляет сам;
• админ добавляет своих и снимает любых. Снятие человека из общего списка
  запоминается исключением — иначе следующее обновление вернуло бы его;
• при внесении подписка останавливается сразу, остаток срока запоминается
  и возвращается, если человека убрать из списка;
• найденным в общем списке триал останавливается сам, а оплаченную подписку
  бот не трогает — пишет админу: человек заплатил, решать ему.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID, load_config, save_config
from states import AWAITING_BL_ADD, AWAITING_BL_CHECK, AWAITING_BL_REASON

DEFAULT_URL = "https://raw.githubusercontent.com/BEDOLAGA-DEV/VPN-BLACKLIST/main/blacklist.txt"
DEFAULT_REASON = "Нарушение правил сервиса"
DATE_FMT = "%d.%m.%Y %H:%M:%S"
PER_PAGE = 10

# Что человеку из ЧС остаётся: только поддержка
USER_ALLOWED = {"support_open", "support_files"}
USER_ALLOWED_PREFIXES = ("support_page:",)

LIST_TABS = {"ours": "Твои", "manual": "Вручную", "allow": "Исключения"}
LIST_TITLES = {
    "ours": "👥 Твои пользователи в ЧС",
    "manual": "✍️ Добавлены вручную",
    "allow": "✅ Исключения из общего списка",
}


# ── Список ───────────────────────────────────────────────────────────────────

def remote_on() -> bool:
    return bool(load_config().get("blacklist_remote_enabled", True))


def source_url() -> str:
    url = (load_config().get("blacklist_url") or DEFAULT_URL).strip()
    # ссылку на страницу файла в GitHub превращаем в ссылку на сам файл
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/(.+)", url)
    return f"https://raw.githubusercontent.com/{m[1]}/{m[2]}/{m[3]}" if m else url


def parse_list(text: str) -> dict[int, str]:
    """«206090793 # Шаринг подписок» → {206090793: "Шаринг подписок"}."""
    out: dict[int, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head, _, reason = line.partition("#")
        parts = head.split()
        if not parts or not parts[0].isdigit():
            continue
        tg_id = int(parts[0])
        if not out.get(tg_id):
            out[tg_id] = reason.strip()[:500]
    return out


def public_reason(reason: str | None) -> str:
    """Причина для самого человека — без ссылок на чужие чаты."""
    text = re.sub(r"https?://\S+", " ", reason or "")
    text = re.sub(r"(?i)^\s*причина(\s+бана)?\s*:\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .,;:—-")
    text = re.sub(r"(?i)^и\s+", "", text)
    return (text[:1].upper() + text[1:]) if text else DEFAULT_REASON


async def entry(tg_id: int) -> dict | None:
    """Действующая запись ЧС: {source: manual|remote, reason, since} или None."""
    if tg_id == ADMIN_ID:
        return None
    from database import bl_lookup
    info = await bl_lookup(tg_id)
    if info["manual"]:
        return {"source": "manual", "reason": info["manual"][0], "since": info["manual"][1]}
    if info["remote_listed"] and not info["allowed"] and remote_on():
        return {"source": "remote", "reason": info["remote"] or "", "since": None}
    return None


async def is_blacklisted(tg_id: int) -> bool:
    return await entry(tg_id) is not None


async def blacklisted_ids() -> set[int]:
    from database import bl_effective_ids
    ids = await bl_effective_ids(remote_on())
    ids.discard(ADMIN_ID)
    return ids


# ── Что видит человек из ЧС ──────────────────────────────────────────────────

def user_may(data: str) -> bool:
    return data in USER_ALLOWED or data.startswith(USER_ALLOWED_PREFIXES)


def blocked_view(reason: str | None):
    import maintenance as mnt
    text = ("⛔ <b>Доступ к сервису закрыт</b>\n\n"
            f"<blockquote>Причина: {html.escape(public_reason(reason))}</blockquote>")
    if not mnt.feature_enabled("support"):
        return text, None
    return (text + "\n\n<i>Если это ошибка — напишите в поддержку.</i>",
            InlineKeyboardMarkup([[InlineKeyboardButton("💬 Поддержка", callback_data="support_open")]]))


async def show_blocked(e: dict, query=None, message=None):
    text, kb = blocked_view(e["reason"])
    if query:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def _tell(bot, tg_id: int, text: str, kb=None):
    try:
        await bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass


async def _notify_blocked(bot, tg_id: int, reason: str):
    text, kb = blocked_view(reason)
    await _tell(bot, tg_id, text, kb)


async def _notify_restored(bot, tg_id: int, res: dict):
    from database import get_user_info
    if not await get_user_info(tg_id):
        return  # ботом не пользовался — сообщать некому
    text = "✅ <b>Доступ восстановлен</b>"
    if res.get("paid_until"):
        text += (f"\n\n<blockquote>📅 Подписка снова работает до "
                 f"<b>{res['paid_until']}</b></blockquote>")
    await _tell(bot, tg_id, text)


async def _log(bot, text: str):
    from log_channel import send_log
    await send_log(bot, text)


# ── Подписки ─────────────────────────────────────────────────────────────────

async def stop_subs(tg_id: int, reason: str) -> dict:
    """Останавливает подписки из-за ЧС и запоминает остаток срока.

    Статус сразу «истекла»: обычная проверка сроков тогда не шлёт «продлите
    подписку» и не переносит клиента — он просто выключен в панели.
    """
    from adminsub.storage import get_sub_by_tg_id
    from database import bl_hold_set
    from paidsub.storage import (
        add_history, get_paid_sub_by_tg_id, parse_sub_date, set_expire_date, update_paid_sub_field,
    )
    from paidsub.time_parser import fmt_duration
    from xui_api import get_client_info, toggle_client, update_client_expire

    out = {"paid": None, "admin": False, "errors": []}
    now = datetime.now()
    row = await get_paid_sub_by_tg_id(tg_id)
    if row and row[11] != "expired":
        exp = parse_sub_date(row[6])
        remaining = max(0, int((exp - now).total_seconds())) if exp else 0
        now_str = now.strftime(DATE_FMT)
        await bl_hold_set(tg_id, "paid", row[0], remaining)
        await set_expire_date(row[0], now_str)
        await update_paid_sub_field(row[0], "status", "expired")
        await update_client_expire(row[2], now_str)
        r = await toggle_client(row[2], False)
        if not r.get("success"):
            out["errors"].append(str(r.get("error") or "?"))
        kept = f"сохранён остаток {fmt_duration(remaining)}" if remaining else "срок уже вышел"
        await add_history(tg_id, "blacklisted", f"Подписка остановлена, {kept}\nПричина: {reason[:200]}")
        out["paid"] = remaining
    else:
        await add_history(tg_id, "blacklisted", f"Причина: {reason[:200]}")

    asub = await get_sub_by_tg_id(tg_id)
    if asub:
        info = await get_client_info(asub[2])
        if info.get("success") and info.get("enabled", True):
            await bl_hold_set(tg_id, "admin", asub[0], 0)
            r = await toggle_client(asub[2], False)
            if r.get("success"):
                out["admin"] = True
            else:
                out["errors"].append(str(r.get("error") or "?"))
    return out


async def restore_subs(tg_id: int) -> dict:
    """Возвращает остановленное из-за ЧС: остаток срока и включённого клиента."""
    from adminsub.storage import get_sub
    from database import bl_hold_take
    from paidsub.storage import add_history, get_paid_sub, set_expire_date, update_paid_sub_field
    from paidsub.time_parser import fmt_duration
    from xui_api import get_client_info, move_client_inbound, toggle_client, update_client_expire

    out = {"paid_until": None, "admin": False, "errors": []}
    for kind, sub_id, remaining in await bl_hold_take(tg_id):
        if kind == "admin":
            row = await get_sub(sub_id)
            if row and row[1] == tg_id:
                r = await toggle_client(row[2], True)
                out["admin"] = bool(r.get("success"))
            continue
        row = await get_paid_sub(sub_id)
        if not row or row[1] != tg_id or remaining <= 0:
            continue
        until = (datetime.now() + timedelta(seconds=remaining)).strftime(DATE_FMT)
        await set_expire_date(sub_id, until)
        await update_paid_sub_field(sub_id, "status", "active")
        await update_client_expire(row[2], until)
        info = await get_client_info(row[2])
        if info.get("success") and not info.get("enabled", True):
            r = await toggle_client(row[2], True)
            if not r.get("success"):
                out["errors"].append(str(r.get("error") or "?"))
        # как при оплате: вернуть на основные инбаунды, если клиента переносили
        inbound_ids = load_config().get("paid_preset_inbound_ids") or []
        if inbound_ids:
            await move_client_inbound(row[2], inbound_ids)
        await add_history(tg_id, "unblacklisted", f"Возвращён остаток {fmt_duration(remaining)}\nДо: {until}")
        out["paid_until"] = until
    if not out["paid_until"]:
        await add_history(tg_id, "unblacklisted", "Снят с чёрного списка")
    return out


async def restore_unlisted(bot) -> list[int]:
    """Возвращает остановленное тем, кто больше не в ЧС (ушёл из общего списка)."""
    from database import bl_holds
    done = []
    for tg_id in sorted({h[0] for h in await bl_holds()}):
        if await is_blacklisted(tg_id):
            continue
        res = await restore_subs(tg_id)
        await _notify_restored(bot, tg_id, res)
        done.append(tg_id)
    return done


# ── Действия админа ──────────────────────────────────────────────────────────

async def blacklist_add(bot, tg_id: int, reason: str) -> dict:
    from database import bl_add_manual
    await bl_add_manual(tg_id, reason)
    res = await stop_subs(tg_id, reason)
    await _notify_blocked(bot, tg_id, reason)
    await _log(bot, f"⛔ В чёрный список: <code>{tg_id}</code> — {html.escape(reason[:200])}")
    return res


async def blacklist_remove(bot, tg_id: int) -> dict:
    from database import bl_remove
    await bl_remove(tg_id)
    res = await restore_subs(tg_id)
    await _notify_restored(bot, tg_id, res)
    await _log(bot, f"✅ Убран из чёрного списка: <code>{tg_id}</code>")
    return res


async def blacklist_readd(bot, tg_id: int) -> dict | None:
    """Снимает исключение: запись общего списка снова действует."""
    from database import bl_unallow
    await bl_unallow(tg_id)
    e = await entry(tg_id)
    if not e:
        return None
    res = await stop_subs(tg_id, e["reason"])
    await _notify_blocked(bot, tg_id, e["reason"])
    await _log(bot, f"⛔ Снова в чёрном списке: <code>{tg_id}</code>")
    return res


async def blacklist_stop(bot, tg_id: int) -> dict | None:
    """Останавливает подписку того, кто уже в ЧС (например, нашёлся в общем списке)."""
    e = await entry(tg_id)
    if not e:
        return None
    res = await stop_subs(tg_id, e["reason"])
    await _notify_blocked(bot, tg_id, e["reason"])
    return res


# ── Обновление общего списка ─────────────────────────────────────────────────

async def sync_remote(bot, full_scan: bool = False) -> dict:
    """Скачивает общий список и применяет его к своим пользователям.

    full_scan — считать новыми все записи (после включения списка).
    """
    import aiohttp
    from database import bl_remote_subs, bl_replace_remote

    report = {"ok": False, "error": None, "total": 0, "added": 0, "removed": 0,
              "trials_stopped": [], "paid_found": [], "restored": []}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(source_url(), timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                text = await resp.text()
        entries = parse_list(text)
        if not entries:
            # пустой или битый файл не должен разом снять всех с ЧС
            raise RuntimeError("в файле не нашлось ни одного ID")
    except Exception as ex:
        report["error"] = (str(ex) if isinstance(ex, RuntimeError) else f"{type(ex).__name__}: {ex}")[:200]
        cfg = load_config()
        cfg["blacklist_last_error"] = report["error"]
        save_config(cfg)
        return report

    added, removed = await bl_replace_remote(entries)
    if full_scan:
        added = set(entries)
    cfg = load_config()
    cfg["blacklist_synced_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    cfg.pop("blacklist_last_error", None)
    save_config(cfg)
    report.update(ok=True, total=len(entries), added=len(added), removed=len(removed))
    if not remote_on():
        return report

    seen = set()
    for tg_id, status, times_renewed in await bl_remote_subs():
        if tg_id in seen or tg_id not in added:
            continue
        seen.add(tg_id)
        if status not in ("active", "renewal"):
            continue
        e = await entry(tg_id)
        if not e or e["source"] != "remote":
            continue
        if times_renewed:
            # человек заплатил — останавливать или нет, решает админ
            report["paid_found"].append(tg_id)
        else:
            await stop_subs(tg_id, e["reason"])
            await _notify_blocked(bot, tg_id, e["reason"])
            report["trials_stopped"].append(tg_id)

    report["restored"] = await restore_unlisted(bot)
    return report


async def send_report(bot, r: dict):
    """Сообщение админу — только если обновление что-то поменяло у своих."""
    if not r.get("ok") or not (r["trials_stopped"] or r["paid_found"] or r["restored"]):
        return
    from database import get_user_info
    lines = ["🌐 <b>Общий чёрный список обновлён</b>\n",
             f"Записей: {r['total']} (+{r['added']} / −{r['removed']})"]
    if r["trials_stopped"]:
        lines.append(f"⛔ Остановлены триалы твоих пользователей: <b>{len(r['trials_stopped'])}</b>")
    if r["restored"]:
        lines.append(f"✅ Ушли из общего списка, остаток срока возвращён: <b>{len(r['restored'])}</b>")
    kb = []
    if r["paid_found"]:
        lines.append(f"\n💳 В списке нашлись клиенты с оплаченной подпиской: <b>{len(r['paid_found'])}</b>.\n"
                     "Подписку бот не трогал — человек заплатил. Открой и реши: "
                     "остановить или сделать исключение.")
        for tg_id in r["paid_found"][:8]:
            u = await get_user_info(tg_id)
            kb.append([InlineKeyboardButton(f"💳 {(u[1] if u and u[1] else tg_id)}"[:40],
                                            callback_data=f"bl_view:{tg_id}")])
    kb.append([InlineKeyboardButton("⛔ К чёрному списку", callback_data="bl_menu")])
    try:
        await bot.send_message(chat_id=ADMIN_ID, text="\n".join(lines), parse_mode="HTML",
                               reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        pass


async def blacklist_sync_tick(context):
    if not remote_on():
        return
    r = await sync_remote(context.bot)
    await send_report(context.bot, r)


# ── Экраны админки ───────────────────────────────────────────────────────────

def _who_line(u, tg_id) -> str:
    if not u:
        return f"<code>{tg_id}</code> · ботом не пользовался"
    name = html.escape(u[1] or str(tg_id))
    return (f"{name} (@{html.escape(u[2])})" if u[2] else name) + f" · <code>{tg_id}</code>"


def _result_note(head: str, res: dict | None) -> str:
    from paidsub.time_parser import fmt_duration
    parts = [head]
    if res:
        if res.get("paid") is not None:
            parts.append(f"Подписка остановлена, остаток {fmt_duration(res['paid'])} сохранён."
                         if res["paid"] else "Подписка остановлена.")
        if res.get("admin"):
            parts.append("Админская подписка " + ("включена." if "paid_until" in res else "выключена."))
        if res.get("paid_until"):
            parts.append(f"Подписка снова работает до {res['paid_until']}.")
        if res.get("errors"):
            parts.append("⚠️ Панель не ответила — проверь клиента вручную: "
                         + html.escape("; ".join(res["errors"]))[:150])
    return "<i>" + " ".join(parts) + "</i>"


async def _send(target, text: str, kb, edit: bool = True):
    if edit:
        await target.edit_message_text(text, parse_mode="HTML", reply_markup=kb,
                                       disable_web_page_preview=True)
    else:
        await target.reply_text(text, parse_mode="HTML", reply_markup=kb,
                                disable_web_page_preview=True)


async def handle_bl_menu(query, context=None, note: str = ""):
    if context:
        context.user_data.pop("state", None)
        context.user_data.pop("bl_pending", None)
    from database import bl_counts
    cfg = load_config()
    on = remote_on()
    c = await bl_counts(on)
    lines = ["⛔ <b>Чёрный список</b>", ""]
    if note:
        lines += [note, ""]
    synced = cfg.get("blacklist_synced_at") or "ещё не обновлялся"
    stats = [
        f"👥 Твоих пользователей в ЧС: <b>{c['ours']}</b>"
        + (f"  ·  с подпиской: <b>{c['ours_active']}</b>" if c["ours_active"] else ""),
        f"✍️ Вручную: <b>{c['manual']}</b>  ·  исключений: <b>{c['allow']}</b>",
        f"🌐 Общий список: <b>{'вкл' if on else 'выкл'}</b>  ·  записей: <b>{c['remote']}</b>",
        f"🔄 Обновлён: {synced}",
    ]
    lines.append("<blockquote>" + "\n".join(stats) + "</blockquote>")
    if cfg.get("blacklist_last_error"):
        lines.append(f"\n⚠️ Последнее обновление не удалось: "
                     f"<code>{html.escape(cfg['blacklist_last_error'])}</code>")
    lines.append("\n<i>Кто в списке, не может взять триал, оплатить или продлить подписку — "
                 "бот показывает причину и оставляет только поддержку.</i>")
    kb = [
        [InlineKeyboardButton("➕ Внести в ЧС", callback_data="bl_add"),
         InlineKeyboardButton("🔍 Проверить ID", callback_data="bl_check")],
        [InlineKeyboardButton("👥 Твои пользователи в ЧС", callback_data="bl_list:ours:1")],
        [InlineKeyboardButton("✍️ Вручную", callback_data="bl_list:manual:1"),
         InlineKeyboardButton("✅ Исключения", callback_data="bl_list:allow:1")],
        [InlineKeyboardButton("🔄 Обновить общий", callback_data="bl_sync"),
         InlineKeyboardButton(f"🌐 Общий · {'вкл ✅' if on else 'выкл'}",
                              callback_data="bl_remote_toggle")],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)


async def handle_bl_list(query, scope: str, page: int = 1):
    from database import bl_list
    if scope not in LIST_TITLES:
        scope = "ours"
    rows, pages = await bl_list(scope, remote_on(), page, PER_PAGE)
    page = min(max(1, page), pages)
    lines = [f"⛔ <b>{LIST_TITLES[scope]}</b>", f"<i>стр. {page} из {pages} · нажми на человека, чтобы открыть</i>"]
    if not rows:
        lines = [lines[0], "", "<blockquote>Пусто.</blockquote>"]
    kb = []
    for tg_id, fn, _un, reason, src in rows:
        icon = {"manual": "✍️", "remote": "🌐", "allow": "✅"}.get(src, "•")
        label = f"{icon} {fn or tg_id} · {public_reason(reason)}"
        kb.append([InlineKeyboardButton(label[:60], callback_data=f"bl_view:{tg_id}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"bl_list:{scope}:{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"bl_list:{scope}:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(("• " if k == scope else "") + t, callback_data=f"bl_list:{k}:1")
               for k, t in LIST_TABS.items()])
    kb.append([InlineKeyboardButton("◀️ К чёрному списку", callback_data="bl_menu")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_bl_view(target, tg_id: int, edit: bool = True, note: str = ""):
    from database import bl_holds, bl_lookup, get_user_info
    from paidsub.storage import get_paid_sub_by_tg_id
    from paidsub.time_parser import fmt_duration
    u = await get_user_info(tg_id)
    info = await bl_lookup(tg_id)
    e = await entry(tg_id)
    holds = {h[1]: h[3] for h in await bl_holds(tg_id)}
    sub = await get_paid_sub_by_tg_id(tg_id)
    sub_live = bool(sub) and sub[11] in ("active", "renewal")

    lines = ["⛔ <b>Чёрный список</b>", ""]
    if note:
        lines += [note, ""]
    lines.append(f"👤 {_who_line(u, tg_id)}")
    card = []
    if e:
        card.append("📌 Статус: <b>в чёрном списке</b>")
        card.append(f"📝 Причина: {html.escape(e['reason'] or '—')}")
        card.append("🌐 Источник: общий список" if e["source"] == "remote"
                    else "✍️ Внесён вручную" + (f" {e['since'][:16]}" if e.get("since") else ""))
        card.append(f"👁 Человек видит: «{html.escape(public_reason(e['reason']))}»")
    elif info["allowed"]:
        card.append("📌 Статус: <b>исключение</b> — есть в общем списке, но ты разрешил")
        card.append(f"📝 Причина в общем списке: {html.escape(info['remote'] or '—')}")
    elif info["remote_listed"]:
        card.append("📌 Статус: есть в общем списке, но он выключен")
    else:
        card.append("📌 Статус: <b>не в чёрном списке</b>")
    if "paid" in holds:
        card.append(f"💳 Подписка остановлена из-за ЧС · сохранён остаток: <b>{fmt_duration(holds['paid'])}</b>"
                    if holds["paid"] else "💳 Подписка остановлена из-за ЧС · остатка не было")
    elif sub_live:
        card.append(f"💳 Подписка действует до <b>{sub[6]}</b>")
    elif sub:
        card.append("💳 Подписка закончилась")
    else:
        card.append("💳 Подписки нет")
    lines += ["", "<blockquote>" + "\n".join(card) + "</blockquote>"]

    kb = []
    if e:
        kb.append([InlineKeyboardButton("✅ Убрать из ЧС" if e["source"] == "manual"
                                        else "✅ Убрать (исключение)", callback_data=f"bl_del:{tg_id}")])
        if sub_live:
            kb.append([InlineKeyboardButton("⛔ Остановить подписку", callback_data=f"bl_stop:{tg_id}")])
    elif info["allowed"]:
        kb.append([InlineKeyboardButton("⛔ Вернуть в ЧС", callback_data=f"bl_readd:{tg_id}")])
    else:
        kb.append([InlineKeyboardButton("⛔ Внести в ЧС", callback_data=f"bl_add_for:{tg_id}")])
    tail = [InlineKeyboardButton("◀️ К списку", callback_data="bl_menu")]
    if u:
        tail.insert(0, InlineKeyboardButton("👤 Профиль", callback_data=f"user_profile:{tg_id}"))
    kb.append(tail)
    await _send(target, "\n".join(lines), InlineKeyboardMarkup(kb), edit)


def _cancel(cb: str = "bl_menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=cb)]])


async def handle_bl_add_start(query, context):
    context.user_data["state"] = AWAITING_BL_ADD
    await query.edit_message_text(
        "➕ <b>Внести в чёрный список</b>\n\n"
        "Пришли ID или @username и через пробел причину:\n"
        "<blockquote><code>123456789 Шаринг подписки</code></blockquote>\n\n"
        "<i>Причину увидит сам человек — ссылки бот из неё уберёт.</i>",
        parse_mode="HTML", reply_markup=_cancel(),
    )


async def handle_bl_add_for(query, context, tg_id: int):
    from database import get_user_info
    context.user_data["state"] = AWAITING_BL_REASON
    context.user_data["bl_target"] = tg_id
    await query.edit_message_text(
        f"⛔ <b>Внести в чёрный список</b>\n\n"
        f"<blockquote>👤 {_who_line(await get_user_info(tg_id), tg_id)}</blockquote>\n\n"
        "<i>Напиши причину одним сообщением — её увидит сам человек.</i>",
        parse_mode="HTML", reply_markup=_cancel(f"bl_view:{tg_id}"),
    )


async def handle_bl_check_start(query, context):
    context.user_data["state"] = AWAITING_BL_CHECK
    await query.edit_message_text(
        "🔍 <b>Проверить в чёрном списке</b>\n\n<i>Пришли ID или @username.</i>",
        parse_mode="HTML", reply_markup=_cancel(),
    )


async def _resolve(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    from database import find_user_by_username
    u = await find_user_by_username(token)
    return u[0] if u else None


async def _add_question(tg_id: int, reason: str) -> str:
    from database import get_user_info
    from paidsub.storage import get_paid_sub_by_tg_id
    sub = await get_paid_sub_by_tg_id(tg_id)
    if sub and sub[11] in ("active", "renewal"):
        sub_line = (f"💳 Подписка до <b>{sub[6]}</b> остановится сразу. Остаток срока сохранится "
                    "и вернётся, если убрать человека из ЧС.")
    else:
        sub_line = "💳 Действующей подписки нет — просто не сможет взять триал и оплатить."
    return (f"⛔ <b>Внести в чёрный список?</b>\n\n"
            f"<blockquote>👤 {_who_line(await get_user_info(tg_id), tg_id)}\n"
            f"📝 Причина: {html.escape(reason)}\n{sub_line}</blockquote>\n\n"
            f"<i>Человек получит сообщение, что доступ закрыт: «{html.escape(public_reason(reason))}».</i>")


async def handle_bl_input(update, context, state: str, text: str):
    from handlers.confirm import confirm_keyboard
    msg = update.message
    if state == AWAITING_BL_CHECK:
        tg_id = await _resolve(text.split()[0]) if text.split() else None
        if not tg_id:
            await msg.reply_text("🔍 <b>Не нашёл</b>\n\n<i>Пришли числовой ID или @username пользователя бота.</i>",
                                 parse_mode="HTML", reply_markup=_cancel())
            return
        context.user_data.pop("state", None)
        await handle_bl_view(msg, tg_id, edit=False)
        return

    if state == AWAITING_BL_ADD:
        parts = text.split(maxsplit=1)
        tg_id = await _resolve(parts[0]) if parts else None
        reason = parts[1] if len(parts) > 1 else ""
    else:
        tg_id, reason = context.user_data.get("bl_target"), text
    if not tg_id:
        await msg.reply_text("🔍 <b>Не нашёл</b>\n\n<i>Пришли числовой ID или @username пользователя бота "
                             "и через пробел причину.</i>", parse_mode="HTML", reply_markup=_cancel())
        return
    if tg_id == ADMIN_ID:
        await msg.reply_text("🙃 <b>Себя в чёрный список внести нельзя</b>", parse_mode="HTML",
                             reply_markup=_cancel())
        return
    reason = reason.strip()[:300] or DEFAULT_REASON
    context.user_data.pop("state", None)
    context.user_data.pop("bl_target", None)
    # вносим только после «Да» — подписка остановится сразу
    context.user_data["bl_pending"] = {"tg_id": tg_id, "reason": reason}
    await msg.reply_text(
        await _add_question(tg_id, reason), parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=confirm_keyboard("⛔ Да, внести в ЧС", "bl_add_apply", f"bl_view:{tg_id}", "bl_menu"),
    )


async def handle_bl_add_apply(query, context):
    pending = context.user_data.pop("bl_pending", None)
    if not pending:
        # уже внесён или бот перезапускался — начать заново
        await handle_bl_menu(query, context)
        return
    res = await blacklist_add(context.bot, pending["tg_id"], pending["reason"])
    await handle_bl_view(query, pending["tg_id"], note=_result_note("⛔ Внесён в чёрный список.", res))


async def handle_bl_del(query, context, tg_id: int):
    res = await blacklist_remove(context.bot, tg_id)
    await handle_bl_view(query, tg_id, note=_result_note("✅ Убран из чёрного списка.", res))


async def handle_bl_stop(query, context, tg_id: int):
    res = await blacklist_stop(context.bot, tg_id)
    head = "⛔ Готово." if res is not None else "Человек уже не в ЧС — ничего не менял."
    await handle_bl_view(query, tg_id, note=_result_note(head, res))


async def handle_bl_readd(query, context, tg_id: int):
    res = await blacklist_readd(context.bot, tg_id)
    head = ("⛔ Снова в чёрном списке." if res is not None
            else "В общем списке его уже нет — вносить нечего.")
    await handle_bl_view(query, tg_id, note=_result_note(head, res))


async def handle_bl_sync_now(query, context):
    await query.edit_message_text("🔄 Обновляю общий список…")
    r = await sync_remote(context.bot)
    if r["ok"]:
        note = f"<i>✅ Обновлено: {r['total']} записей (+{r['added']} / −{r['removed']}).</i>"
        await send_report(context.bot, r)
    else:
        note = f"<i>⚠️ Не удалось обновить: {html.escape(r['error'] or '?')}</i>"
    await handle_bl_menu(query, context, note=note)


async def handle_bl_remote_toggle(query, context):
    cfg = load_config()
    turn_on = not cfg.get("blacklist_remote_enabled", True)
    cfg["blacklist_remote_enabled"] = turn_on
    save_config(cfg)
    if turn_on:
        await query.edit_message_text("🔄 Включаю и обновляю общий список…")
        r = await sync_remote(context.bot, full_scan=True)
        await send_report(context.bot, r)
        note = ("<i>🌐 Общий список включён и обновлён.</i>" if r["ok"]
                else f"<i>🌐 Включён, но обновить не удалось: {html.escape(r['error'] or '?')}</i>")
    else:
        restored = await restore_unlisted(context.bot)
        note = "<i>🌐 Общий список выключен." + (
            f" Возвращены остановленные из-за него подписки: {len(restored)}.</i>" if restored else "</i>")
    await handle_bl_menu(query, context, note=note)
