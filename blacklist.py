"""Чёрный список: общий из GitHub плюс свои правки.

Кто в списке, не может взять триал, оплатить или продлить подписку — бот
показывает причину и оставляет только поддержку, чтобы можно было оспорить.

• общий список BEDOLAGA-DEV/VPN-BLACKLIST бот обновляет сам;
• админ добавляет своих и снимает любых. Снятие человека из общего списка
  запоминается исключением — иначе следующее обновление вернуло бы его;
• блокировка бывает срочной: бот снимет её сам, когда срок выйдет, и вернёт
  подписку с сохранённым остатком;
• при внесении подписка останавливается сразу, остаток срока запоминается
  и возвращается, если человека убрать из списка;
• найденным в общем списке триал останавливается сам, а оплаченную подписку
  бот не трогает — пишет админу: человек заплатил, решать ему;
• рядом живёт бан в боте — он закрывает бота целиком, тоже с причиной,
  сроком и автором. Всё, что ставили и снимали, видно в карточке человека.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID, load_config, save_config
from states import (
    AWAITING_BL_ADD, AWAITING_BL_CHECK, AWAITING_BL_REASON, AWAITING_BL_UNTIL,
)

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
    """Действующая запись ЧС: {source, reason, since, until, by_id} или None."""
    if tg_id == ADMIN_ID:
        return None
    from database import bl_lookup
    info = await bl_lookup(tg_id)
    if info["manual"]:
        reason, since, until, by_id = info["manual"]
        # у временной записи вышел срок — держать уже нельзя, уборка снимет её сама
        if not _passed(until):
            return {"source": "manual", "reason": reason, "since": since,
                    "until": until, "by_id": by_id}
    elif info["remote_listed"] and not info["allowed"] and remote_on():
        return {"source": "remote", "reason": info["remote"] or "",
                "since": None, "until": None, "by_id": None}
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


def blocked_view(reason: str | None, until_local: str | None = None):
    text = ("⛔ <b>Доступ к сервису закрыт</b>\n\n"
            f"<blockquote>Причина: {html.escape(public_reason(reason))}</blockquote>")
    if until_local:
        text += (f"\n\n<blockquote>⏳ Доступ вернётся сам: "
                 f"<b>{fmt_until(until_local)}</b></blockquote>")
    from handlers.support import support_button
    btn = support_button()
    if not btn:
        return text, None
    return (text + "\n\n<i>Если это ошибка — напишите в поддержку.</i>",
            InlineKeyboardMarkup([[btn]]))


async def show_blocked(e: dict, query=None, message=None):
    text, kb = blocked_view(e["reason"], e.get("until"))
    if query:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def _tell(bot, tg_id: int, text: str, kb=None):
    try:
        await bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass


async def _notify_blocked(bot, tg_id: int, reason: str, until_local: str | None = None):
    text, kb = blocked_view(reason, until_local)
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
    from panel import get_client_info, toggle_client, update_client_expire

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
    from panel import get_client_info, toggle_client, update_client_expire

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


# ── Срок блокировки ──────────────────────────────────────────────────────────

# Быстрые причины: чаще всего блокируют за это, печатать руками незачем
QUICK_REASONS = [
    "Повторные пробные периоды",
    "Шаринг ключа",
    "Возврат платежа",
    "Спам и реклама",
    "Оскорбления в поддержке",
]

# Сроки: код → (подпись, секунды). 0 — бессрочно
TERMS = [("forever", "♾ Навсегда", 0), ("1d", "1 день", 86400),
         ("7d", "7 дней", 7 * 86400), ("30d", "30 дней", 30 * 86400)]
TERM_SECONDS = {code: secs for code, _label, secs in TERMS}


def _offset() -> timedelta:
    """Насколько местное время впереди UTC — sqlite сравнивает сроки в UTC."""
    return datetime.now() - datetime.utcnow()


def until_utc(seconds: int) -> str | None:
    """Момент снятия блокировки для базы. 0 секунд — бессрочно."""
    if not seconds:
        return None
    return (datetime.utcnow() + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


def _to_local(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return (datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
                + _offset()).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def fmt_until(local_raw: str | None) -> str:
    """Местный срок в человеческий вид: «04.10.2026 12:00 · осталось 7 дней»."""
    from paidsub.time_parser import fmt_duration_precise
    if not local_raw:
        return "бессрочно"
    try:
        d = datetime.strptime(local_raw[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return local_raw[:16]
    left = int((d - datetime.now()).total_seconds())
    tail = f" · осталось {fmt_duration_precise(left)}" if left > 0 else " · срок вышел"
    return d.strftime("%d.%m.%Y %H:%M") + tail


def term_line(until_db: str | None) -> str:
    """Срок из базы (UTC) в человеческий вид."""
    return fmt_until(_to_local(until_db))


def _passed(local_raw: str | None) -> bool:
    if not local_raw:
        return False
    try:
        return datetime.strptime(local_raw[:19], "%Y-%m-%d %H:%M:%S") <= datetime.now()
    except ValueError:
        return False


# ── Действия админа ──────────────────────────────────────────────────────────

async def blacklist_add(bot, tg_id: int, reason: str, until: str | None = None,
                        by_id: int | None = None) -> dict:
    from database import bl_add_manual, bl_log
    await bl_add_manual(tg_id, reason, until, by_id)
    await bl_log(tg_id, "added", reason, by_id)
    res = await stop_subs(tg_id, reason)
    await _notify_blocked(bot, tg_id, reason, _to_local(until))
    await _log(bot, f"⛔ В чёрный список: <code>{tg_id}</code> — {html.escape(reason[:200])}"
                    f" · {term_line(until)}")
    return res


async def blacklist_remove(bot, tg_id: int, by_id: int | None = None,
                           auto: bool = False) -> dict:
    from database import bl_log, bl_remove
    await bl_remove(tg_id)
    await bl_log(tg_id, "expired" if auto else "removed",
                 "срок блокировки вышел" if auto else None, by_id)
    res = await restore_subs(tg_id)
    await _notify_restored(bot, tg_id, res)
    await _log(bot, ("⏳ Срок в ЧС вышел, доступ вернул сам: " if auto
                     else "✅ Убран из чёрного списка: ") + f"<code>{tg_id}</code>")
    return res


async def blacklist_readd(bot, tg_id: int, by_id: int | None = None) -> dict | None:
    """Снимает исключение: запись общего списка снова действует."""
    from database import bl_log, bl_unallow
    await bl_unallow(tg_id)
    e = await entry(tg_id)
    if not e:
        return None
    await bl_log(tg_id, "readded", e["reason"], by_id)
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
    await _notify_blocked(bot, tg_id, e["reason"], e.get("until"))
    return res


# ── Бан в боте ───────────────────────────────────────────────────────────────

def ban_view(reason: str | None, until_local: str | None = None) -> str:
    text = "🚫 <b>Аккаунт заблокирован</b>"
    if reason:
        text += f"\n\n<blockquote>Причина: {html.escape(public_reason(reason))}</blockquote>"
    if until_local:
        text += f"\n\n<blockquote>⏳ Блокировка снимется сама: <b>{fmt_until(until_local)}</b></blockquote>"
    return text + "\n\n<i>Если это ошибка — свяжитесь с администратором.</i>"


async def banned_view(tg_id: int) -> str:
    """Текст для забаненного: с причиной и сроком, если они заданы."""
    from database import ban_entry
    b = await ban_entry(tg_id) or {}
    return ban_view(b.get("reason"), b.get("until"))


async def ban(bot, tg_id: int, reason: str | None = None, until: str | None = None,
              by_id: int | None = None):
    """Бан в боте: человек вообще не может пользоваться ботом."""
    from database import ban_user, bl_log
    await ban_user(tg_id, reason, until, by_id)
    await bl_log(tg_id, "banned", reason, by_id)
    await _tell(bot, tg_id, ban_view(reason, _to_local(until)))
    await _log(bot, f"🚫 Забанен в боте: <code>{tg_id}</code>"
                    + (f" — {html.escape(reason[:200])}" if reason else "")
                    + f" · {term_line(until)}")


async def unban(bot, tg_id: int, by_id: int | None = None, auto: bool = False):
    from database import bl_log, unban_user
    await unban_user(tg_id)
    await bl_log(tg_id, "unbanned", "срок бана вышел" if auto else None, by_id)
    await _tell(bot, tg_id, "✅ <b>Блокировка снята</b>\n\n"
                            "<i>Бот снова работает — откройте /start.</i>")
    await _log(bot, ("⏳ Срок бана вышел, разбанил сам: " if auto
                     else "✅ Разбанен в боте: ") + f"<code>{tg_id}</code>")


async def blacklist_expire_tick(context):
    """Снимает временные блокировки, у которых вышел срок."""
    from database import bans_expired_now, bl_expired_now
    for tg_id, _reason in await bl_expired_now():
        await blacklist_remove(context.bot, tg_id, auto=True)
    for tg_id in await bans_expired_now():
        await unban(context.bot, tg_id, auto=True)


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

HIST_WORDS = {
    "added": "внесён в ЧС", "removed": "снят с ЧС", "expired": "снят по сроку",
    "readded": "возвращён в ЧС", "banned": "забанен", "unbanned": "разбанен",
}


def _who_line(u, tg_id) -> str:
    if not u:
        return f"<code>{tg_id}</code> · ботом не пользовался"
    name = html.escape(u[1] or str(tg_id))
    return (f"{name} (@{html.escape(u[2])})" if u[2] else name) + f" · <code>{tg_id}</code>"


def _by_line(by_id) -> str:
    if not by_id:
        return "неизвестно кто"
    return "ты" if int(by_id) == ADMIN_ID else f"помощник <code>{by_id}</code>"


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
    from database import bl_counts, bl_stats
    from paidsub.time_parser import fmt_duration
    cfg = load_config()
    on = remote_on()
    c = await bl_counts(on)
    st = await bl_stats()
    lines = ["⛔ <b>Чёрный список и баны</b>", ""]
    if note:
        lines += [note, ""]
    synced = cfg.get("blacklist_synced_at") or "ещё не обновлялся"
    who = [
        f"👥 Твоих пользователей в ЧС: <b>{c['ours']}</b>"
        + (f"  ·  с подпиской: <b>{c['ours_active']}</b>" if c["ours_active"] else ""),
        f"✍️ Вручную: <b>{c['manual']}</b> (бессрочно <b>{st['forever']}</b> · "
        f"со сроком <b>{st['temporary']}</b>)  ·  исключений: <b>{c['allow']}</b>",
        f"🚫 Забанены в боте: <b>{st['banned']}</b>"
        + (f" (со сроком <b>{st['banned_temp']}</b>)" if st["banned_temp"] else ""),
        f"🌐 Общий список: <b>{'вкл' if on else 'выкл'}</b>  ·  записей: <b>{c['remote']}</b>",
        f"🔄 Обновлён: {synced}",
    ]
    lines.append("<blockquote>" + "\n".join(who) + "</blockquote>")
    month = [f"📆 За 30 дней: заблокировано <b>{st['added_30d']}</b> · "
             f"снято <b>{st['removed_30d']}</b>"]
    if st["held"]:
        month.append(f"🧊 Подписок на паузе: <b>{st['held']}</b> · "
                     f"сохранено срока: <b>{fmt_duration(st['held_seconds'])}</b>")
    lines.append("<blockquote>" + "\n".join(month) + "</blockquote>")
    if cfg.get("blacklist_last_error"):
        lines.append(f"\n⚠️ Последнее обновление не удалось: "
                     f"<code>{html.escape(cfg['blacklist_last_error'])}</code>")
    lines.append("\n<i>ЧС закрывает покупки и подписку, оставляя поддержку. "
                 "Бан закрывает бота целиком. Оба можно поставить на срок — "
                 "снимутся сами.</i>")
    kb = [
        [InlineKeyboardButton("➕ Внести в ЧС", callback_data="bl_add"),
         InlineKeyboardButton("🔍 Проверить ID", callback_data="bl_check")],
        [InlineKeyboardButton("👥 Твои пользователи в ЧС", callback_data="bl_list:ours:1")],
        [InlineKeyboardButton("✍️ Вручную", callback_data="bl_list:manual:1"),
         InlineKeyboardButton("✅ Исключения", callback_data="bl_list:allow:1")],
        [InlineKeyboardButton(f"🚫 Баны в боте · {st['banned']}", callback_data="bl_bans:1")],
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


async def handle_bl_bans(query, page: int = 1):
    """Кто закрыт в боте целиком."""
    from database import bans_list
    rows, pages, total = await bans_list(page, PER_PAGE)
    page = min(max(1, page), pages)
    lines = ["🚫 <b>Баны в боте</b>",
             f"<i>всего {total} · стр. {page} из {pages} · нажми, чтобы открыть</i>"]
    if not rows:
        lines = [lines[0], "", "<blockquote>Никто не забанен.</blockquote>"]
    kb = []
    for tg_id, fn, _un, reason, until in rows:
        term = "♾ навсегда" if not until else ("⏳ " + fmt_until(until).split(" · ")[0])
        label = f"👤 {fn or tg_id} · {term}" + (f" · {public_reason(reason)}" if reason else "")
        kb.append([InlineKeyboardButton(label[:60], callback_data=f"bl_view:{tg_id}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"bl_bans:{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"bl_bans:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("◀️ К чёрному списку", callback_data="bl_menu")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_bl_view(target, tg_id: int, edit: bool = True, note: str = ""):
    from database import (
        ban_entry, bl_history, bl_holds, bl_lookup, bl_times_listed, get_user_info,
    )
    from paidsub.storage import get_paid_sub_by_tg_id
    from paidsub.time_parser import fmt_duration
    u = await get_user_info(tg_id)
    info = await bl_lookup(tg_id)
    e = await entry(tg_id)
    b = await ban_entry(tg_id)
    holds = {h[1]: h[3] for h in await bl_holds(tg_id)}
    sub = await get_paid_sub_by_tg_id(tg_id)
    sub_live = bool(sub) and sub[11] in ("active", "renewal")

    lines = ["⛔ <b>Блокировки человека</b>", ""]
    if note:
        lines += [note, ""]
    lines.append(f"👤 {_who_line(u, tg_id)}")

    card = []
    if e:
        card.append("📌 Статус: <b>в чёрном списке</b>")
        card.append(f"📝 Причина: {html.escape(e['reason'] or '—')}")
        if e["source"] == "remote":
            card.append("🌐 Источник: общий список")
        else:
            card.append(f"⏳ Срок: <b>{fmt_until(e.get('until'))}</b>")
            card.append("✍️ Внёс: " + _by_line(e.get("by_id"))
                        + (f" · {e['since'][:16]}" if e.get("since") else ""))
        card.append(f"👁 Человек видит: «{html.escape(public_reason(e['reason']))}»")
    elif info["allowed"]:
        card.append("📌 Статус: <b>исключение</b> — есть в общем списке, но ты разрешил")
        card.append(f"📝 Причина в общем списке: {html.escape(info['remote'] or '—')}")
    elif info["remote_listed"]:
        card.append("📌 Статус: есть в общем списке, но он выключен")
    else:
        card.append("📌 Статус: <b>не в чёрном списке</b>")
    lines += ["", "<blockquote>" + "\n".join(card) + "</blockquote>"]

    ban_card = []
    if b:
        ban_card.append("🚫 Бан в боте: <b>стоит</b> — бот для человека закрыт целиком")
        if b["reason"]:
            ban_card.append(f"📝 Причина: {html.escape(b['reason'])}")
        ban_card.append(f"⏳ Срок: <b>{fmt_until(b['until'])}</b>")
        ban_card.append("✍️ Забанил: " + _by_line(b["by_id"])
                        + (f" · {b['since'][:16]}" if b.get("since") else ""))
    else:
        ban_card.append("🚫 Бан в боте: <b>нет</b>")
    lines += ["", "<blockquote>" + "\n".join(ban_card) + "</blockquote>"]

    sub_card = []
    if "paid" in holds:
        sub_card.append(f"💳 Подписка остановлена из-за ЧС · сохранён остаток: "
                        f"<b>{fmt_duration(holds['paid'])}</b>"
                        if holds["paid"] else "💳 Подписка остановлена из-за ЧС · остатка не было")
    elif sub_live:
        sub_card.append(f"💳 Подписка действует до <b>{sub[6]}</b>")
    elif sub:
        sub_card.append("💳 Подписка закончилась")
    else:
        sub_card.append("💳 Подписки нет")
    lines += ["", "<blockquote>" + "\n".join(sub_card) + "</blockquote>"]

    hist = await bl_history(tg_id, 5)
    if hist:
        times = await bl_times_listed(tg_id)
        rows = [f"🕘 Попадал в ЧС: <b>{times}</b> " + _plural_times(times)]
        for action, reason, _by, when in hist:
            word = HIST_WORDS.get(action, action)
            tail = f" — {html.escape(public_reason(reason))}" if reason else ""
            rows.append(f"• {when[8:10]}.{when[5:7]} {when[11:16]} — {word}{tail}"[:120])
        lines += ["", "<blockquote>" + "\n".join(rows) + "</blockquote>"]

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
    kb.append([InlineKeyboardButton("✅ Разбанить", callback_data=f"bl_unban:{tg_id}") if b
               else InlineKeyboardButton("🚫 Забанить в боте", callback_data=f"bl_ban:{tg_id}")])
    tail = [InlineKeyboardButton("◀️ К списку", callback_data="bl_menu")]
    if u:
        tail.insert(0, InlineKeyboardButton("👤 Профиль", callback_data=f"user_profile:{tg_id}"))
    kb.append(tail)
    await _send(target, "\n".join(lines), InlineKeyboardMarkup(kb), edit)


def _plural_times(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "раз"
    return "раза" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "раз"


def _cancel(cb: str = "bl_menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=cb)]])


# ── Внесение: кого → за что → на сколько → «Да» ──────────────────────────────

async def handle_bl_add_start(query, context):
    context.user_data["state"] = AWAITING_BL_ADD
    await query.edit_message_text(
        "➕ <b>Внести в чёрный список</b>\n\n"
        "Пришли ID или @username — причину и срок выберешь кнопками:\n"
        "<blockquote><code>123456789</code></blockquote>\n\n"
        "<i>Можно сразу с причиной: <code>123456789 Шаринг ключа</code>.</i>",
        parse_mode="HTML", reply_markup=_cancel(),
    )


async def handle_bl_check_start(query, context):
    context.user_data["state"] = AWAITING_BL_CHECK
    await query.edit_message_text(
        "🔍 <b>Проверить в чёрном списке</b>\n\n<i>Пришли ID или @username.</i>",
        parse_mode="HTML", reply_markup=_cancel(),
    )


async def handle_bl_new(target, context, kind: str, tg_id: int, edit: bool = True):
    """Шаг 1: за что. kind — bl (чёрный список) или ban (бан в боте)."""
    from database import get_user_info
    context.user_data.pop("state", None)
    context.user_data["bl_pending"] = {"kind": kind, "tg_id": tg_id}
    head = ("⛔ <b>Внести в чёрный список</b>" if kind == "bl"
            else "🚫 <b>Забанить в боте</b>")
    what = ("Не сможет купить и продлить, подписка встанет на паузу, останется поддержка."
            if kind == "bl" else "Бот перестанет отвечать вообще — ни меню, ни поддержки.")
    kb = [[InlineKeyboardButton(r, callback_data=f"bl_reason:{i}")]
          for i, r in enumerate(QUICK_REASONS)]
    kb.append([InlineKeyboardButton("✍️ Своя причина", callback_data="bl_reason:own")])
    kb.append([InlineKeyboardButton("❌ Отмена", callback_data=f"bl_view:{tg_id}")])
    await _send(target,
                f"{head}\n\n<blockquote>👤 {_who_line(await get_user_info(tg_id), tg_id)}\n"
                f"{what}</blockquote>\n\n<b>За что?</b>\n"
                "<i>Причину увидит сам человек — ссылки бот из неё уберёт.</i>",
                InlineKeyboardMarkup(kb), edit)


async def handle_bl_reason(query, context, choice: str):
    pending = context.user_data.get("bl_pending")
    if not pending:
        await handle_bl_menu(query, context)
        return
    if choice == "own":
        context.user_data["state"] = AWAITING_BL_REASON
        await query.edit_message_text(
            "✍️ <b>Своя причина</b>\n\n<i>Напиши причину одним сообщением — "
            "её увидит сам человек.</i>", parse_mode="HTML",
            reply_markup=_cancel(f"bl_view:{pending['tg_id']}"),
        )
        return
    try:
        pending["reason"] = QUICK_REASONS[int(choice)]
    except (ValueError, IndexError):
        pending["reason"] = DEFAULT_REASON
    await handle_bl_term_ask(query, context)


async def handle_bl_term_ask(target, context, edit: bool = True):
    """Шаг 2: на сколько."""
    pending = context.user_data.get("bl_pending")
    if not pending:
        await _send(target, "⛔ <b>Начни заново</b>", _cancel(), edit)
        return
    context.user_data.pop("state", None)
    head = ("⛔ <b>Внести в чёрный список</b>" if pending["kind"] == "bl"
            else "🚫 <b>Забанить в боте</b>")
    kb = [[InlineKeyboardButton(label, callback_data=f"bl_term:{code}")]
          for code, label, _s in TERMS]
    kb.append([InlineKeyboardButton("✍️ Свой срок", callback_data="bl_term:own")])
    kb.append([InlineKeyboardButton("❌ Отмена", callback_data=f"bl_view:{pending['tg_id']}")])
    await _send(target,
                f"{head}\n\n<blockquote>📝 Причина: "
                f"{html.escape(pending.get('reason') or DEFAULT_REASON)}</blockquote>\n\n"
                "<b>На сколько?</b>\n<i>Временную блокировку бот снимет сам, "
                "подписку вернёт с сохранённым остатком.</i>",
                InlineKeyboardMarkup(kb), edit)


async def handle_bl_term(query, context, code: str):
    pending = context.user_data.get("bl_pending")
    if not pending:
        await handle_bl_menu(query, context)
        return
    if code == "own":
        context.user_data["state"] = AWAITING_BL_UNTIL
        await query.edit_message_text(
            "✍️ <b>Свой срок</b>\n\n"
            "<blockquote>Напиши, на сколько: <code>3 дня</code>, <code>2 недели</code>, "
            "<code>6 месяцев</code>.</blockquote>", parse_mode="HTML",
            reply_markup=_cancel(f"bl_view:{pending['tg_id']}"),
        )
        return
    pending["until"] = until_utc(TERM_SECONDS.get(code, 0))
    await handle_bl_confirm(query, context)


async def handle_bl_confirm(target, context, edit: bool = True):
    """Шаг 3: вопрос перед делом — подписка встанет сразу."""
    from database import get_user_info
    from handlers.confirm import confirm_keyboard
    from paidsub.storage import get_paid_sub_by_tg_id
    pending = context.user_data.get("bl_pending")
    if not pending:
        await _send(target, "⛔ <b>Начни заново</b>", _cancel(), edit)
        return
    tg_id = pending["tg_id"]
    reason = pending.get("reason") or DEFAULT_REASON
    term = term_line(pending.get("until"))
    if pending["kind"] == "ban":
        text = (f"🚫 <b>Забанить в боте?</b>\n\n"
                f"<blockquote>👤 {_who_line(await get_user_info(tg_id), tg_id)}\n"
                f"📝 Причина: {html.escape(reason)}\n"
                f"⏳ Срок: <b>{term}</b>\n"
                "🤐 Бот перестанет отвечать совсем — даже поддержка закроется.</blockquote>\n\n"
                "<i>Подписку бан не трогает: срок продолжит идти.</i>")
        yes = "🚫 Да, забанить"
    else:
        sub = await get_paid_sub_by_tg_id(tg_id)
        if sub and sub[11] in ("active", "renewal"):
            sub_line = (f"💳 Подписка до <b>{sub[6]}</b> остановится сразу. Остаток срока "
                        "сохранится и вернётся при снятии.")
        else:
            sub_line = "💳 Действующей подписки нет — просто не сможет взять триал и оплатить."
        text = (f"⛔ <b>Внести в чёрный список?</b>\n\n"
                f"<blockquote>👤 {_who_line(await get_user_info(tg_id), tg_id)}\n"
                f"📝 Причина: {html.escape(reason)}\n"
                f"⏳ Срок: <b>{term}</b>\n{sub_line}</blockquote>\n\n"
                f"<i>Человек получит сообщение, что доступ закрыт: "
                f"«{html.escape(public_reason(reason))}».</i>")
        yes = "⛔ Да, внести в ЧС"
    await _send(target, text,
                confirm_keyboard(yes, "bl_add_apply", f"bl_view:{tg_id}", "bl_menu"), edit)


async def handle_bl_add_apply(query, context):
    pending = context.user_data.pop("bl_pending", None)
    if not pending:
        # бот перезапускался — начать заново
        await handle_bl_menu(query, context)
        return
    tg_id = pending["tg_id"]
    reason = pending.get("reason") or DEFAULT_REASON
    until = pending.get("until")
    by_id = getattr(getattr(query, "from_user", None), "id", None)
    if pending["kind"] == "ban":
        await ban(context.bot, tg_id, reason, until, by_id)
        note = "<i>🚫 Забанен в боте. " + term_line(until).capitalize() + ".</i>"
        await handle_bl_view(query, tg_id, note=note)
        return
    res = await blacklist_add(context.bot, tg_id, reason, until, by_id)
    await handle_bl_view(query, tg_id,
                         note=_result_note(f"⛔ Внесён в чёрный список ({term_line(until)}).", res))


# ── Снятие ───────────────────────────────────────────────────────────────────

async def handle_bl_del(query, context, tg_id: int):
    by_id = getattr(getattr(query, "from_user", None), "id", None)
    res = await blacklist_remove(context.bot, tg_id, by_id)
    await handle_bl_view(query, tg_id, note=_result_note("✅ Убран из чёрного списка.", res))


async def handle_bl_stop(query, context, tg_id: int):
    res = await blacklist_stop(context.bot, tg_id)
    head = "⛔ Готово." if res is not None else "Человек уже не в ЧС — ничего не менял."
    await handle_bl_view(query, tg_id, note=_result_note(head, res))


async def handle_bl_readd(query, context, tg_id: int):
    by_id = getattr(getattr(query, "from_user", None), "id", None)
    res = await blacklist_readd(context.bot, tg_id, by_id)
    head = ("⛔ Снова в чёрном списке." if res is not None
            else "В общем списке его уже нет — вносить нечего.")
    await handle_bl_view(query, tg_id, note=_result_note(head, res))


async def handle_bl_unban(query, context, tg_id: int):
    by_id = getattr(getattr(query, "from_user", None), "id", None)
    await unban(context.bot, tg_id, by_id)
    await handle_bl_view(query, tg_id, note="<i>✅ Разбанен — бот снова ему отвечает.</i>")


# ── Ввод текстом ─────────────────────────────────────────────────────────────

async def _resolve(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    from database import find_user_by_username
    u = await find_user_by_username(token)
    return u[0] if u else None


async def handle_bl_input(update, context, state: str, text: str):
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

    if state == AWAITING_BL_UNTIL:
        from paidsub.time_parser import parse_duration
        pending = context.user_data.get("bl_pending")
        if not pending:
            context.user_data.pop("state", None)
            await msg.reply_text("⛔ <b>Начни заново</b>", parse_mode="HTML", reply_markup=_cancel())
            return
        secs = parse_duration(text)
        if not secs:
            await msg.reply_text("⏳ <b>Не понял срок</b>\n\n"
                                 "<i>Напиши так: <code>3 дня</code>, <code>2 недели</code>, "
                                 "<code>6 месяцев</code>.</i>", parse_mode="HTML",
                                 reply_markup=_cancel(f"bl_view:{pending['tg_id']}"))
            return
        pending["until"] = until_utc(secs)
        context.user_data.pop("state", None)
        await handle_bl_confirm(msg, context, edit=False)
        return

    if state == AWAITING_BL_ADD:
        parts = text.split(maxsplit=1)
        tg_id = await _resolve(parts[0]) if parts else None
        reason = (parts[1].strip() if len(parts) > 1 else "")[:300]
        if not tg_id:
            await msg.reply_text("🔍 <b>Не нашёл</b>\n\n<i>Пришли числовой ID или @username "
                                 "пользователя бота.</i>", parse_mode="HTML", reply_markup=_cancel())
            return
        if tg_id == ADMIN_ID:
            await msg.reply_text("🙃 <b>Себя в чёрный список внести нельзя</b>", parse_mode="HTML",
                                 reply_markup=_cancel())
            return
        context.user_data.pop("state", None)
        if reason:
            context.user_data["bl_pending"] = {"kind": "bl", "tg_id": tg_id, "reason": reason}
            await handle_bl_term_ask(msg, context, edit=False)
        else:
            await handle_bl_new(msg, context, "bl", tg_id, edit=False)
        return

    # AWAITING_BL_REASON — своя причина для уже выбранного человека
    pending = context.user_data.get("bl_pending")
    if not pending:
        context.user_data.pop("state", None)
        await msg.reply_text("⛔ <b>Начни заново</b>", parse_mode="HTML", reply_markup=_cancel())
        return
    if pending["tg_id"] == ADMIN_ID:
        await msg.reply_text("🙃 <b>Себя заблокировать нельзя</b>", parse_mode="HTML",
                             reply_markup=_cancel())
        return
    pending["reason"] = text.strip()[:300] or DEFAULT_REASON
    context.user_data.pop("state", None)
    await handle_bl_term_ask(msg, context, edit=False)


# ── Общий список ─────────────────────────────────────────────────────────────

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
