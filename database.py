import os
import aiosqlite
from config import INSTALL_DIR

DB_PATH = os.path.join(INSTALL_DIR, "bot.db")
MSGS_PER_PAGE = 5
TICKETS_PER_PAGE = 8


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                from_admin INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admin_subs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                email TEXT NOT NULL,
                uuid TEXT NOT NULL,
                sub_id TEXT NOT NULL,
                sub_url TEXT NOT NULL,
                expire_date TEXT NOT NULL,
                limit_ip INTEGER NOT NULL DEFAULT 0,
                limit_hwid INTEGER NOT NULL DEFAULT 0,
                total_gb INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS paid_subs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                email TEXT NOT NULL,
                uuid TEXT NOT NULL,
                sub_id TEXT NOT NULL,
                sub_url TEXT NOT NULL,
                expire_date TEXT NOT NULL,
                limit_ip INTEGER NOT NULL DEFAULT 0,
                limit_hwid INTEGER NOT NULL DEFAULT 0,
                total_gb INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # миграция для существующих баз
        try:
            await db.execute("ALTER TABLE admin_subs ADD COLUMN tg_id INTEGER")
        except Exception:
            pass
        # убираем :443/:80 из существующих sub_url
        from xui_api import strip_default_port
        async with db.execute("SELECT id, sub_url FROM admin_subs") as cur:
            rows = await cur.fetchall()
        for row_id, old_url in rows:
            new_url = strip_default_port(old_url)
            if new_url != old_url:
                await db.execute("UPDATE admin_subs SET sub_url = ? WHERE id = ?", (new_url, row_id))
        await db.commit()


async def upsert_user(user_id: int, first_name: str, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (id, first_name, username) VALUES (?, ?, ?)
        """, (user_id, first_name, username or ""))
        await db.execute("""
            UPDATE users SET first_name = ?, username = ? WHERE id = ?
        """, (first_name, username or "", user_id))
        await db.commit()


async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM users") as cur:
            return [r[0] for r in await cur.fetchall()]


async def add_support_message(user_id: int, text: str, from_admin: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO support_messages (user_id, text, from_admin) VALUES (?, ?, ?)",
            (user_id, text, 1 if from_admin else 0),
        )
        await db.commit()


async def get_support_messages(user_id: int, page: int = 1):
    offset = (page - 1) * MSGS_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM support_messages WHERE user_id = ?", (user_id,)
        ) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT text, from_admin, created_at FROM support_messages
            WHERE user_id = ?
            ORDER BY created_at ASC
            LIMIT ? OFFSET ?
        """, (user_id, MSGS_PER_PAGE, offset)) as cur:
            msgs = await cur.fetchall()
    total_pages = max(1, (total + MSGS_PER_PAGE - 1) // MSGS_PER_PAGE)
    return msgs, total_pages


async def get_ticket_users(page: int = 1):
    offset = (page - 1) * TICKETS_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(DISTINCT user_id) FROM support_messages WHERE from_admin = 0
        """) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT u.id, u.first_name, u.username, COUNT(sm.id), MAX(sm.created_at)
            FROM support_messages sm
            JOIN users u ON u.id = sm.user_id
            WHERE sm.from_admin = 0
            GROUP BY sm.user_id
            ORDER BY MAX(sm.created_at) DESC
            LIMIT ? OFFSET ?
        """, (TICKETS_PER_PAGE, offset)) as cur:
            rows = await cur.fetchall()
    total_pages = max(1, (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE)
    return rows, total_pages


async def get_user_info(user_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, first_name, username FROM users WHERE id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone()
