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
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await db.execute("ALTER TABLE support_messages ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        for col in ("file_id TEXT", "file_type TEXT"):
            try:
                await db.execute(f"ALTER TABLE support_messages ADD COLUMN {col}")
            except Exception:
                pass
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
            CREATE TABLE IF NOT EXISTS paid_sub_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
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
        # миграции для существующих баз
        try:
            await db.execute("ALTER TABLE admin_subs ADD COLUMN tg_id INTEGER")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE paid_subs ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE paid_subs ADD COLUMN payment_pending INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE paid_subs ADD COLUMN times_renewed INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        for col in ("ind_trial_period", "ind_pay_period", "ind_renew_time", "ind_price", "ind_pay_url"):
            try:
                if col == "ind_pay_url":
                    await db.execute(f"ALTER TABLE paid_subs ADD COLUMN {col} TEXT")
                else:
                    await db.execute(f"ALTER TABLE paid_subs ADD COLUMN {col} INTEGER")
            except Exception:
                pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS paid_sub_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await db.execute("ALTER TABLE paid_sub_history ADD COLUMN details TEXT")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS paid_mutes (
                tg_id INTEGER PRIMARY KEY,
                muted_until TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                referred_by INTEGER NOT NULL,
                rewarded INTEGER NOT NULL DEFAULT 0,
                bonus_seconds INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # промокоды (скидка %)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                percent INTEGER NOT NULL,
                expires_at TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                tg_id INTEGER NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await db.execute("ALTER TABLE paid_subs ADD COLUMN pending_promo TEXT")
        except Exception:
            pass
        # Баны
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                tg_id INTEGER PRIMARY KEY,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Отзывы
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS review_requests (
                tg_id INTEGER PRIMARY KEY,
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Winback
        await db.execute("""
            CREATE TABLE IF NOT EXISTS winback_sent (
                tg_id INTEGER PRIMARY KEY,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
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


async def get_dashboard_stats() -> dict:
    async def _one(db, q, params=()):
        async with db.execute(q, params) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async with aiosqlite.connect(DB_PATH) as db:
        users_total = await _one(db, "SELECT COUNT(*) FROM users")
        users_today = await _one(db, "SELECT COUNT(*) FROM users WHERE date(created_at) = date('now')")
        users_week = await _one(db, "SELECT COUNT(*) FROM users WHERE created_at >= datetime('now','-7 days')")

        paid_total = await _one(db, "SELECT COUNT(*) FROM paid_subs")
        paid_active = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE status IN ('active','renewal')")
        paid_expired = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE status = 'expired'")
        trial_active = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE times_renewed = 0 AND status IN ('active','renewal')")
        paying = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE times_renewed > 0")
        payment_pending = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE payment_pending = 1")

        requests_pending = await _one(db, "SELECT COUNT(*) FROM paid_sub_requests WHERE status = 'pending'")
        admin_subs = await _one(db, "SELECT COUNT(*) FROM admin_subs")

        ref_total = await _one(db, "SELECT COUNT(*) FROM referrals")
        ref_rewarded = await _one(db, "SELECT COUNT(*) FROM referrals WHERE rewarded = 1")

        promos_active = await _one(db, "SELECT COUNT(*) FROM promo_codes WHERE active = 1")
        promo_uses = await _one(db, "SELECT COUNT(*) FROM promo_uses")

        payments_confirmed = await _one(db, "SELECT COUNT(*) FROM paid_sub_history WHERE action = 'payment_confirmed'")
        payments_today = await _one(db, "SELECT COUNT(*) FROM paid_sub_history WHERE action = 'payment_confirmed' AND date(created_at) = date('now')")
        trials_approved = await _one(db, "SELECT COUNT(*) FROM paid_sub_history WHERE action = 'trial_approved'")
        open_tickets_unread = await _one(db, "SELECT COUNT(DISTINCT user_id) FROM support_messages WHERE from_admin = 0 AND is_read = 0")

    return {
        "users_total": users_total, "users_today": users_today, "users_week": users_week,
        "paid_total": paid_total, "paid_active": paid_active, "paid_expired": paid_expired,
        "trial_active": trial_active, "paying": paying, "payment_pending": payment_pending,
        "requests_pending": requests_pending, "admin_subs": admin_subs,
        "ref_total": ref_total, "ref_rewarded": ref_rewarded,
        "promos_active": promos_active, "promo_uses": promo_uses,
        "payments_confirmed": payments_confirmed, "payments_today": payments_today,
        "trials_approved": trials_approved, "unread_tickets": open_tickets_unread,
    }


async def get_payments_by_day(days: int = 30) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT date(created_at) as d, COUNT(*) as cnt
            FROM paid_sub_history
            WHERE action = 'payment_confirmed'
              AND created_at >= datetime('now', ?)
            GROUP BY d ORDER BY d ASC
        """, (f"-{days} days",)) as cur:
            return await cur.fetchall()


async def get_users_by_segment(segment: str) -> list[int]:
    """Возвращает tg_id пользователей по сегменту для рассылки."""
    async with aiosqlite.connect(DB_PATH) as db:
        if segment == "all":
            q = "SELECT id FROM users"
        elif segment == "active":
            q = "SELECT DISTINCT tg_id FROM paid_subs WHERE tg_id IS NOT NULL AND status IN ('active','renewal')"
        elif segment == "expired":
            q = "SELECT DISTINCT tg_id FROM paid_subs WHERE tg_id IS NOT NULL AND status = 'expired'"
        elif segment == "trial":
            q = "SELECT DISTINCT tg_id FROM paid_subs WHERE tg_id IS NOT NULL AND times_renewed = 0 AND status IN ('active','renewal')"
        elif segment == "paying":
            q = "SELECT DISTINCT tg_id FROM paid_subs WHERE tg_id IS NOT NULL AND times_renewed > 0"
        elif segment == "no_sub":
            q = "SELECT id FROM users WHERE id NOT IN (SELECT tg_id FROM paid_subs WHERE tg_id IS NOT NULL)"
        elif segment == "pending_pay":
            q = "SELECT DISTINCT tg_id FROM paid_subs WHERE tg_id IS NOT NULL AND payment_pending = 1"
        else:
            q = "SELECT id FROM users"
        async with db.execute(q) as cur:
            return [r[0] for r in await cur.fetchall()]


async def add_support_message(user_id: int, text: str, from_admin: bool = False,
                              file_id: str | None = None, file_type: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO support_messages (user_id, text, from_admin, is_read, file_id, file_type) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, text, 1 if from_admin else 0, 1 if from_admin else 0, file_id, file_type),
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
            SELECT text, from_admin, created_at, file_id, file_type FROM support_messages
            WHERE user_id = ?
            ORDER BY created_at ASC
            LIMIT ? OFFSET ?
        """, (user_id, MSGS_PER_PAGE, offset)) as cur:
            msgs = await cur.fetchall()
    total_pages = max(1, (total + MSGS_PER_PAGE - 1) // MSGS_PER_PAGE)
    return msgs, total_pages


async def count_support_files(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM support_messages WHERE user_id = ? AND file_id IS NOT NULL",
            (user_id,),
        ) as cur:
            return (await cur.fetchone())[0]


async def get_support_files(user_id: int) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT file_id, file_type, from_admin, created_at FROM support_messages
            WHERE user_id = ? AND file_id IS NOT NULL
            ORDER BY created_at ASC
        """, (user_id,)) as cur:
            return await cur.fetchall()


async def mark_ticket_read(user_id: int):
    """Помечает все сообщения юзера как прочитанные админом."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE support_messages SET is_read = 1 WHERE user_id = ? AND from_admin = 0",
            (user_id,),
        )
        await db.commit()


async def get_unread_tickets_count() -> int:
    """Число тикетов с непрочитанными сообщениями."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM support_messages WHERE from_admin = 0 AND is_read = 0"
        ) as cur:
            return (await cur.fetchone())[0]


async def get_ticket_users(page: int = 1):
    offset = (page - 1) * TICKETS_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) FROM (
                SELECT user_id FROM support_messages WHERE from_admin = 0 GROUP BY user_id
            )
        """) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT
                u.id, u.first_name, u.username,
                COUNT(sm.id) AS total,
                SUM(CASE WHEN sm.from_admin = 0 AND sm.is_read = 0 THEN 1 ELSE 0 END) AS unread,
                MAX(sm.created_at) AS last_time,
                (SELECT text FROM support_messages s2 WHERE s2.user_id = u.id ORDER BY s2.id DESC LIMIT 1) AS last_text,
                (SELECT from_admin FROM support_messages s3 WHERE s3.user_id = u.id ORDER BY s3.id DESC LIMIT 1) AS last_from_admin
            FROM support_messages sm
            JOIN users u ON u.id = sm.user_id
            GROUP BY sm.user_id
            HAVING SUM(CASE WHEN sm.from_admin = 0 THEN 1 ELSE 0 END) > 0
            ORDER BY unread DESC, last_time DESC
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


# ── Баны ─────────────────────────────────────────────────────────────────────

async def ban_user(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO bans (tg_id) VALUES (?)", (tg_id,))
        await db.commit()


async def unban_user(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bans WHERE tg_id = ?", (tg_id,))
        await db.commit()


async def is_banned(tg_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM bans WHERE tg_id = ?", (tg_id,)) as cur:
            return (await cur.fetchone()) is not None


# ── Отзывы ───────────────────────────────────────────────────────────────────

async def add_review(tg_id: int, rating: int, text: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reviews (tg_id, rating, text) VALUES (?, ?, ?)",
            (tg_id, rating, text),
        )
        await db.commit()


async def get_user_review(tg_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, tg_id, rating, text, created_at FROM reviews WHERE tg_id = ? ORDER BY id DESC LIMIT 1",
            (tg_id,),
        ) as cur:
            return await cur.fetchone()


async def get_reviews_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM reviews") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("SELECT AVG(rating) FROM reviews") as cur:
            avg = (await cur.fetchone())[0] or 0
        async with db.execute(
            "SELECT rating, COUNT(*) FROM reviews GROUP BY rating ORDER BY rating DESC"
        ) as cur:
            breakdown = await cur.fetchall()
    return {"total": total, "avg": round(avg, 1), "breakdown": breakdown}


async def get_reviews_list(page: int = 1, per_page: int = 8) -> tuple[list, int]:
    offset = (page - 1) * per_page
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM reviews") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT r.id, r.tg_id, r.rating, r.text, r.created_at
            FROM reviews r ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)) as cur:
            rows = await cur.fetchall()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return rows, total_pages


async def is_review_requested(tg_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM review_requests WHERE tg_id = ?", (tg_id,)) as cur:
            return (await cur.fetchone()) is not None


async def mark_review_requested(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO review_requests (tg_id) VALUES (?)", (tg_id,))
        await db.commit()


# ── Winback ──────────────────────────────────────────────────────────────────

async def is_winback_sent(tg_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM winback_sent WHERE tg_id = ?", (tg_id,)) as cur:
            return (await cur.fetchone()) is not None


async def mark_winback_sent(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO winback_sent (tg_id) VALUES (?)", (tg_id,))
        await db.commit()
