import aiosqlite
from core.database import DB_PATH

SUBS_PER_PAGE = 8


async def add_sub(email: str, uuid_val: str, sub_id: str, sub_url: str,
                  expire_date: str, limit_ip: int, limit_hwid: int, total_gb: int,
                  tg_id: int | None = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO admin_subs (tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (tg_id, email, uuid_val, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb))
        await db.commit()
        return cur.lastrowid


# Срок хранится текстом «дд.мм.гггг чч:мм:сс» — ключ сортировки/сравнения
# собираем из него, как в платных подписках. Статуса у админских в базе нет:
# активна/истекла выводится из срока.
_EXP_KEY = ("substr(expire_date, 7, 4) || substr(expire_date, 4, 2) || "
            "substr(expire_date, 1, 2) || substr(expire_date, 11)")

ADMIN_SCOPES = {
    "all": "1 = 1",
    "active": f"{_EXP_KEY} > ?now",
    "soon": f"{_EXP_KEY} > ?now AND {_EXP_KEY} <= ?soon",
    "expired": f"{_EXP_KEY} <= ?now",
}

ADMIN_SORTS = {
    "new": "created_at DESC, id DESC",
    "expire": f"{_EXP_KEY} ASC",
    "name": "email ASC",
}

SOON_DAYS = 3


def _now_key() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d %H:%M:%S")


def _soon_key() -> str:
    from datetime import datetime, timedelta
    return (datetime.now() + timedelta(days=SOON_DAYS)).strftime("%Y%m%d %H:%M:%S")


def _scope_where(scope: str) -> tuple:
    raw = ADMIN_SCOPES.get(scope, ADMIN_SCOPES["all"])
    params = []
    if "?now" in raw:
        raw = raw.replace("?now", "?")
        params.append(_now_key())
    if "?soon" in raw:
        raw = raw.replace("?soon", "?")
        params.append(_soon_key())
    return raw, params


async def list_subs(page: int = 1, scope: str = "all", sort: str = "new") -> tuple[list, int]:
    where, params = _scope_where(scope)
    order = ADMIN_SORTS.get(sort, ADMIN_SORTS["new"])
    offset = (page - 1) * SUBS_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT COUNT(*) FROM admin_subs WHERE {where}", params) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(f"""
            SELECT id, tg_id, email, expire_date, total_gb, created_at
            FROM admin_subs
            WHERE {where}
            ORDER BY {order}
            LIMIT ? OFFSET ?
        """, params + [SUBS_PER_PAGE, offset]) as cur:
            rows = await cur.fetchall()
    total_pages = max(1, (total + SUBS_PER_PAGE - 1) // SUBS_PER_PAGE)
    return rows, total_pages


async def admin_counts() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        out = {}
        for scope in ADMIN_SCOPES:
            where, params = _scope_where(scope)
            async with db.execute(
                f"SELECT COUNT(*) FROM admin_subs WHERE {where}", params) as cur:
                out[scope] = (await cur.fetchone())[0]
        return out


async def search_admin_subs(query: str, limit: int = 20) -> list:
    """Поиск по TG ID, email, UUID, Sub ID, нику и имени владельца."""
    q = (query or "").strip().lstrip("@")
    if not q:
        return []
    async with aiosqlite.connect(DB_PATH) as db:
        if q.isdigit():
            async with db.execute(
                "SELECT id, tg_id, email, expire_date, total_gb, created_at "
                "FROM admin_subs WHERE tg_id = ? OR id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (int(q), int(q), int(limit))) as cur:
                return await cur.fetchall()
        like = f"%{q}%"
        async with db.execute(
            "SELECT id, tg_id, email, expire_date, total_gb, created_at "
            "FROM admin_subs WHERE email LIKE ? OR uuid LIKE ? OR sub_id LIKE ? "
            "OR tg_id IN (SELECT id FROM users WHERE username LIKE ? "
            "OR first_name LIKE ?) ORDER BY created_at DESC LIMIT ?",
            (like, like, like, like, like, int(limit))) as cur:
            return await cur.fetchall()


async def get_sub(sub_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at, lte_gb
            FROM admin_subs WHERE id = ?
        """, (sub_id,)) as cur:
            return await cur.fetchone()


async def get_sub_by_tg_id(tg_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at, lte_gb
            FROM admin_subs WHERE tg_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (tg_id,)) as cur:
            return await cur.fetchone()




async def delete_sub(sub_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admin_subs WHERE id = ?", (sub_id,))
        await db.commit()


async def update_sub_field(sub_id: int, field: str, value):
    allowed = {"expire_date", "limit_ip", "limit_hwid", "total_gb",
               "uuid", "sub_id", "sub_url", "lte_gb"}
    if field not in allowed:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE admin_subs SET {field} = ? WHERE id = ?", (value, sub_id))
        await db.commit()
