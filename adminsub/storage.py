import aiosqlite
from database import DB_PATH

SUBS_PER_PAGE = 8


async def add_sub(email: str, uuid_val: str, sub_id: str, sub_url: str,
                  expire_date: str, limit_ip: int, limit_hwid: int, total_gb: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO admin_subs (email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (email, uuid_val, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb))
        await db.commit()
        return cur.lastrowid


async def list_subs(page: int = 1) -> tuple[list, int]:
    offset = (page - 1) * SUBS_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM admin_subs") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT id, email, expire_date, total_gb, created_at
            FROM admin_subs
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (SUBS_PER_PAGE, offset)) as cur:
            rows = await cur.fetchall()
    total_pages = max(1, (total + SUBS_PER_PAGE - 1) // SUBS_PER_PAGE)
    return rows, total_pages


async def get_sub(sub_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at
            FROM admin_subs WHERE id = ?
        """, (sub_id,)) as cur:
            return await cur.fetchone()


async def delete_sub(sub_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admin_subs WHERE id = ?", (sub_id,))
        await db.commit()
