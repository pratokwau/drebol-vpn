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
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at,
                   status, payment_pending, ind_trial_period, ind_pay_period, ind_renew_time, ind_price, ind_pay_url
            FROM paid_subs WHERE id = ?
        """, (sub_id,)) as cur:
            return await cur.fetchone()


async def get_paid_sub_by_tg_id(tg_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at, status, times_renewed
            FROM paid_subs WHERE tg_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (tg_id,)) as cur:
            return await cur.fetchone()


async def get_paid_sub_status(tg_id: int) -> str:
    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return ""
    return row[11] if len(row) > 11 else "active"


async def is_payment_pending(tg_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT payment_pending FROM paid_subs WHERE tg_id = ? ORDER BY created_at DESC LIMIT 1",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return bool(row and row[0])


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
    allowed = {"expire_date", "limit_ip", "limit_hwid", "total_gb", "status", "payment_pending",
                "ind_trial_period", "ind_pay_period", "ind_renew_time", "ind_price", "ind_pay_url",
                "times_renewed"}
    if field not in allowed:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE paid_subs SET {field} = ? WHERE id = ?", (value, sub_id))
        await db.commit()


async def get_expired_paid_subs() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, status, times_renewed, ind_renew_time
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


async def list_pending_requests() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT r.tg_id, r.created_at
            FROM paid_sub_requests r
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
        """) as cur:
            return await cur.fetchall()


async def list_pending_payments() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT tg_id, email, expire_date
            FROM paid_subs
            WHERE payment_pending = 1
            ORDER BY expire_date ASC
        """) as cur:
            return await cur.fetchall()


async def resolve_request(tg_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE paid_sub_requests SET status = ? WHERE tg_id = ? AND status = 'pending'",
            (status, tg_id),
        )
        await db.commit()


# ── История действий ─────────────────────────────────────────────────────────

HISTORY_PER_PAGE = 10


async def add_history(tg_id: int, action: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO paid_sub_history (tg_id, action) VALUES (?, ?)",
            (tg_id, action),
        )
        await db.commit()


async def list_history(page: int = 1) -> tuple[list, int]:
    offset = (page - 1) * HISTORY_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM paid_sub_history") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT h.id, h.tg_id, h.action, h.created_at
            FROM paid_sub_history h
            ORDER BY h.created_at DESC
            LIMIT ? OFFSET ?
        """, (HISTORY_PER_PAGE, offset)) as cur:
            rows = await cur.fetchall()
    total_pages = max(1, (total + HISTORY_PER_PAGE - 1) // HISTORY_PER_PAGE)
    return rows, total_pages


# ── Мьют ─────────────────────────────────────────────────────────────────────

async def get_muted_until(tg_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT muted_until FROM paid_mutes WHERE tg_id = ?",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row and row[0] else None


async def set_mute(tg_id: int, muted_until: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO paid_mutes (tg_id, muted_until) VALUES (?, ?)",
            (tg_id, muted_until),
        )
        await db.commit()


async def clear_mute(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM paid_mutes WHERE tg_id = ?", (tg_id,))
        await db.commit()


async def list_muted() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT tg_id, muted_until FROM paid_mutes ORDER BY muted_until DESC") as cur:
            return await cur.fetchall()
