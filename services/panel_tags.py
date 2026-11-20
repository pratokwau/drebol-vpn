"""Теги пользователей в панели Remnawave по статусу подписки.

У каждого клиента панели есть поле tag. Бот держит его в соответствии
со статусом человека, чтобы в панели было видно, кто есть кто, без сверки
с базой бота:

    BANNED  — человек в чёрном списке;
    TRIAL   — активная пробная подписка (платная строка, ещё ни одной оплаты);
    PAID    — активная оплаченная подписка (замороженная — тоже PAID:
              заморозка — это пауза в панели, статус в базе остаётся active);
    ADMIN   — активная админская подписка;
    EXPIRED — активной подписки нет.

Приоритет — как в списке сверху: тег один, побеждает самый «сильный»
статус. У человека может быть два клиента в панели (платный paid_<id>
и админский <id>) — тег ставится всем его клиентам одинаковый.

Обновление — двумя путями: точечно при смене статуса (хуки в сервисах
подписок и ЧС зовут refresh_user_tag) и вручную кнопкой «Применить ко
всем» в админке. Периодической синхронизации тегов нет — как и вся
синхронизация с панелью, массовая часть здесь только ручная.

Всё best-effort: ошибка панели не должна ронять оплату, выдачу или бан,
поэтому refresh_user_tag никогда не бросает исключений — только лог.
"""

import logging
from datetime import datetime

log = logging.getLogger(__name__)

TAG_BANNED = "BANNED"
TAG_TRIAL = "TRIAL"
TAG_PAID = "PAID"
TAG_ADMIN = "ADMIN"
TAG_EXPIRED = "EXPIRED"

ALL_TAGS = (TAG_BANNED, TAG_TRIAL, TAG_PAID, TAG_ADMIN, TAG_EXPIRED)

TAG_LABELS = {
    TAG_BANNED: "⛔ BANNED — чёрный список",
    TAG_TRIAL: "🧪 TRIAL — пробная подписка",
    TAG_PAID: "💳 PAID — оплаченная подписка",
    TAG_ADMIN: "🛡 ADMIN — админская подписка",
    TAG_EXPIRED: "💤 EXPIRED — активной подписки нет",
}


def compute_tag(state: dict) -> str:
    """Тег по снимку состояния человека. Чистая функция.

    state: {"banned": bool,
            "paid":  None | {"active": bool, "renewed": int},
            "admin": None | {"active": bool}}
    """
    if state.get("banned"):
        return TAG_BANNED
    paid = state.get("paid")
    if paid and paid.get("active"):
        return TAG_TRIAL if int(paid.get("renewed") or 0) == 0 else TAG_PAID
    admin = state.get("admin")
    if admin and admin.get("active"):
        return TAG_ADMIN
    return TAG_EXPIRED


def _expire_active(expire_str, now=None) -> bool:
    """Срок ещё не вышел? Дата — текстом «дд.мм.гггг чч:мм:сс»."""
    if not expire_str:
        return False
    from paidsub.storage import parse_sub_date
    dt = parse_sub_date(expire_str)
    return bool(dt and dt > (now or datetime.now()))


async def gather_state(tg_id: int) -> dict:
    """Снимок состояния человека из базы бота и ЧС."""
    state = {"banned": False, "paid": None, "admin": None}
    try:
        from features.blacklist import entry as bl_entry
        state["banned"] = await bl_entry(tg_id) is not None
    except Exception:
        log.exception("panel_tags: не прочитался ЧС для %s", tg_id)
    from paidsub.storage import get_paid_sub_by_tg_id
    row = await get_paid_sub_by_tg_id(tg_id)
    if row:
        status = row[11] if len(row) > 11 else None
        renewed = row[12] if len(row) > 12 else 0
        state["paid"] = {
            "active": status == "active" and _expire_active(row[6]),
            "renewed": int(renewed or 0),
        }
    from adminsub.storage import get_sub_by_tg_id
    arow = await get_sub_by_tg_id(tg_id)
    if arow:
        state["admin"] = {"active": _expire_active(arow[6])}
    return state


async def _panel_names(tg_id: int) -> list[str]:
    """Имена всех клиентов человека в панели (платный и админский)."""
    from services.panel import _name
    names = []
    from paidsub.storage import get_paid_sub_by_tg_id
    row = await get_paid_sub_by_tg_id(tg_id)
    if row and row[2]:
        names.append(_name(row[2]))
    from adminsub.storage import get_sub_by_tg_id
    arow = await get_sub_by_tg_id(tg_id)
    if arow and arow[2]:
        n = _name(arow[2])
        if n not in names:
            names.append(n)
    return names


async def _set_tag_on_client(name: str, tag: str) -> str:
    """Ставит тег одному клиенту панели. Возвращает исход:
    "updated" | "unchanged" | "error: ..."."""
    import services.remnawave as rw
    cur = await rw.user_by_name(name)
    if not cur.get("ok"):
        return f"error: клиент {name} не найден в панели"
    if (cur.get("data") or {}).get("tag") == tag:
        return "unchanged"
    r = await rw.patch(name, tag=tag)
    if not r.get("ok"):
        return f"error: {name}: {r.get('error') or 'панель не приняла тег'}"
    data = r.get("data")
    if isinstance(data, dict) and "tag" in data and data.get("tag") != tag:
        return f"error: {name}: панель оставила тег {data.get('tag')!r}"
    return "updated"


async def apply_tag_to_user(tg_id: int) -> dict:
    """Считает тег человека и ставит его всем его клиентам в панели.

    Возвращает {"tg_id", "tag", "updated", "unchanged", "errors": [...]}.
    """
    state = await gather_state(tg_id)
    tag = compute_tag(state)
    res = {"tg_id": tg_id, "tag": tag, "updated": 0, "unchanged": 0,
           "errors": []}
    for name in await _panel_names(tg_id):
        try:
            out = await _set_tag_on_client(name, tag)
        except Exception as e:  # панель лежит — не роняем вызывающего
            out = f"error: {name}: {e}"
        if out == "updated":
            res["updated"] += 1
        elif out == "unchanged":
            res["unchanged"] += 1
        else:
            res["errors"].append(out)
    return res


async def refresh_user_tag(tg_id: int) -> None:
    """Хук смены статуса: обновить тег, тихо. Никогда не бросает."""
    if not tg_id:
        return
    try:
        res = await apply_tag_to_user(tg_id)
        if res["errors"]:
            log.warning("panel_tags: %s → %s, ошибки: %s",
                        tg_id, res["tag"], "; ".join(res["errors"]))
    except Exception:
        log.exception("panel_tags: не удалось обновить тег %s", tg_id)


# ── Массовое применение и счётчики ────────────────────────────────────────────

async def _all_tg_ids() -> list[int]:
    """Все люди, у кого есть хоть одна подписка, плюс все из ЧС."""
    import aiosqlite
    from core.database import DB_PATH
    ids = set()
    async with aiosqlite.connect(DB_PATH) as db:
        for table in ("paid_subs", "admin_subs"):
            async with db.execute(
                    f"SELECT DISTINCT tg_id FROM {table} "
                    "WHERE tg_id IS NOT NULL") as cur:
                ids.update(r[0] for r in await cur.fetchall())
    try:
        from features.blacklist import blacklisted_ids
        ids.update(await blacklisted_ids())
    except Exception:
        log.exception("panel_tags: не прочитался список ЧС")
    return sorted(ids)


async def _standalone_admin_subs() -> list:
    """Админские подписки без человека (tg_id IS NULL): у них свой клиент
    в панели, тег считается по их собственному сроку."""
    import aiosqlite
    from core.database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT email, expire_date FROM admin_subs "
                "WHERE tg_id IS NULL AND email IS NOT NULL") as cur:
            return await cur.fetchall()


async def tag_counters() -> dict:
    """Сколько людей в каждом статусе — по данным бота, без запросов
    в панель. Возвращает {тег: число, ..., "total": число}."""
    counts = {t: 0 for t in ALL_TAGS}
    total = 0
    for tg_id in await _all_tg_ids():
        counts[compute_tag(await gather_state(tg_id))] += 1
        total += 1
    for _email, expire in await _standalone_admin_subs():
        tag = compute_tag({"banned": False, "paid": None,
                           "admin": {"active": _expire_active(expire)}})
        counts[tag] += 1
        total += 1
    counts["total"] = total
    return counts


async def apply_all_tags() -> dict:
    """Приводит теги всех клиентов панели к статусам из базы бота.

    Возвращает сводку: people — сколько людей/подписок обработано,
    counts — сколько из них в каком теге, updated/unchanged — по клиентам
    панели, errors — число ошибок и первые примеры.
    """
    counts = {t: 0 for t in ALL_TAGS}
    res = {"people": 0, "counts": counts, "updated": 0, "unchanged": 0,
           "errors": 0, "error_samples": []}

    def _note(tag, out):
        counts[tag] += 1
        res["people"] += 1
        if out == "updated":
            res["updated"] += 1
        elif out == "unchanged":
            res["unchanged"] += 1
        else:
            res["errors"] += 1
            if len(res["error_samples"]) < 5:
                res["error_samples"].append(out)

    for tg_id in await _all_tg_ids():
        r = await apply_tag_to_user(tg_id)
        counts[r["tag"]] += 1
        res["people"] += 1
        res["updated"] += r["updated"]
        res["unchanged"] += r["unchanged"]
        res["errors"] += len(r["errors"])
        for e in r["errors"]:
            if len(res["error_samples"]) < 5:
                res["error_samples"].append(e)

    from services.panel import _name
    for email, expire in await _standalone_admin_subs():
        tag = compute_tag({"banned": False, "paid": None,
                           "admin": {"active": _expire_active(expire)}})
        try:
            out = await _set_tag_on_client(_name(email), tag)
        except Exception as e:
            out = f"error: {email}: {e}"
        _note(tag, out)
    return res
