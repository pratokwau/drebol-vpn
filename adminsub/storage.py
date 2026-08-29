import aiosqlite
from database import DB_PATH

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


async def list_subs(page: int = 1) -> tuple[list, int]:
    offset = (page - 1) * SUBS_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM admin_subs") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT id, tg_id, email, expire_date, total_gb, created_at
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
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at
            FROM admin_subs WHERE id = ?
        """, (sub_id,)) as cur:
            return await cur.fetchone()


async def get_sub_by_tg_id(tg_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at
            FROM admin_subs WHERE tg_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (tg_id,)) as cur:
            return await cur.fetchone()


async def delete_sub(sub_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admin_subs WHERE id = ?", (sub_id,))
        await db.commit()


async def get_all_subs_with_tg() -> list:
    """Возвращает все подписки с tg_id для проверки ников."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, expire_date, limit_ip, limit_hwid, total_gb
            FROM admin_subs WHERE tg_id IS NOT NULL
        """) as cur:
            return await cur.fetchall()


async def update_sub_email(sub_id: int, new_email: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE admin_subs SET email = ? WHERE id = ?", (new_email, sub_id))
        await db.commit()


async def update_sub_field(sub_id: int, field: str, value):
    allowed = {"expire_date", "limit_ip", "limit_hwid", "total_gb"}
    if field not in allowed:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE admin_subs SET {field} = ? WHERE id = ?", (value, sub_id))
        await db.commit()
