import aiosqlite
from database import DB_PATH

SUBS_PER_PAGE = 8


async def add_paid_sub(tg_id: int, email: str, uuid_val: str, sub_id: str, sub_url: str,
                       expire_date: str, limit_ip: int, limit_hwid: int, total_gb: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO paid_subs (tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (tg_id, email, uuid_val, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb))
        await db.commit()
        return cur.lastrowid


async def list_paid_subs(page: int = 1) -> tuple[list, int]:
    offset = (page - 1) * SUBS_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM paid_subs") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT id, tg_id, email, expire_date, total_gb, created_at
            FROM paid_subs
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (SUBS_PER_PAGE, offset)) as cur:
            rows = await cur.fetchall()
    total_pages = max(1, (total + SUBS_PER_PAGE - 1) // SUBS_PER_PAGE)
    return rows, total_pages


async def get_paid_sub(sub_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at
            FROM paid_subs WHERE id = ?
        """, (sub_id,)) as cur:
            return await cur.fetchone()


async def get_paid_sub_by_tg_id(tg_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at
            FROM paid_subs WHERE tg_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (tg_id,)) as cur:
            return await cur.fetchone()


async def delete_paid_sub(sub_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM paid_subs WHERE id = ?", (sub_id,))
        await db.commit()


async def get_all_paid_subs_with_tg() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, expire_date, limit_ip, limit_hwid, total_gb
            FROM paid_subs WHERE tg_id IS NOT NULL
        """) as cur:
            return await cur.fetchall()


async def update_paid_sub_field(sub_id: int, field: str, value):
    allowed = {"expire_date", "limit_ip", "limit_hwid", "total_gb", "status"}
    if field not in allowed:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE paid_subs SET {field} = ? WHERE id = ?", (value, sub_id))
        await db.commit()


async def get_expired_paid_subs() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, status
            FROM paid_subs
        """) as cur:
            return await cur.fetchall()


async def update_paid_sub_email(sub_id: int, new_email: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE paid_subs SET email = ? WHERE id = ?", (new_email, sub_id))
        await db.commit()


# ── Запросы на подписку ──────────────────────────────────────────────────────

async def add_request(tg_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO paid_sub_requests (tg_id) VALUES (?)", (tg_id,)
        )
        await db.commit()
        return cur.lastrowid


async def get_pending_request(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM paid_sub_requests WHERE tg_id = ? AND status = 'pending'",
            (tg_id,),
        ) as cur:
            return await cur.fetchone()


async def resolve_request(tg_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE paid_sub_requests SET status = ? WHERE tg_id = ? AND status = 'pending'",
            (status, tg_id),
        )
        await db.commit()
