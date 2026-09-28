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
        # period_end — конец пробного/оплаченного периода. Хранится явно.
        # Раньше он вычислялся как expire_date − время_на_оплату, поэтому правка
        # времени на оплату двигала конец периода задним числом у всех подписок.
        try:
            await db.execute("ALTER TABLE paid_subs ADD COLUMN period_end TEXT")
        except Exception:
            pass

        from config import load_config as _load_cfg
        try:
            _cfg = _load_cfg()
        except Exception:
            _cfg = {}

        # Фиксируем текущие общие настройки в подписках, созданных до этого механизма.
        # Дальше правка общих настроек не должна менять условия уже выданных подписок.
        # Срок и цену платного периода теперь задают тарифы, поэтому из общих
        # настроек переносим только пробный период.
        for _col, _key in (
            ("ind_trial_period", "paid_trial_period"),
        ):
            _val = _cfg.get(_key)
            if _val:
                try:
                    await db.execute(
                        f"UPDATE paid_subs SET {_col} = ? WHERE {_col} IS NULL", (_val,)
                    )
                except Exception:
                    pass

        # Окна оплаты больше нет: конец периода всегда совпадает с датой
        # окончания, а подписки, ждавшие продления, снова активны до своей даты.
        # Правки идемпотентные: гонять их каждый запуск безопасно, зато база
        # чинится сама, даже если конфиг потеряется или запись делали руками.
        for _fix in (
            "UPDATE paid_subs SET ind_renew_time = 0 "
            "WHERE ind_renew_time IS NOT NULL AND ind_renew_time != 0",
            "UPDATE paid_subs SET status = 'active' WHERE status = 'renewal'",
            "UPDATE paid_subs SET period_end = expire_date "
            "WHERE period_end IS NULL OR period_end != expire_date",
        ):
            try:
                await db.execute(_fix)
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
        # Промокоды: личные (привязаны к человеку), общий лимит использований,
        # тип награды — скидка в % или подаренные дни.
        for col, decl in (
            ("owner_tg_id", "INTEGER"),          # NULL — код для всех
            ("max_uses", "INTEGER NOT NULL DEFAULT 0"),   # 0 — без лимита
            ("kind", "TEXT NOT NULL DEFAULT 'percent'"),  # percent | days
            ("days", "INTEGER NOT NULL DEFAULT 0"),
            ("note", "TEXT"),                    # за что выдан, видит только админ
            ("source", "TEXT NOT NULL DEFAULT 'manual'"),  # manual|personal|segment|winback
            ("first_only", "INTEGER NOT NULL DEFAULT 0"),  # 1 — только тем, кто ещё не платил
        ):
            try:
                await db.execute(f"ALTER TABLE promo_codes ADD COLUMN {col} {decl}")
            except Exception:
                pass
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_promo_owner ON promo_codes(owner_tg_id)")
        # Журнал действий в боте: тип действия без содержимого сообщений.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(created_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(tg_id, created_at)")
        # Помощь с подключением: кому уже написали и кто подключался хоть раз.
        # Время ставим только у отправленных подсказок — для отметки
        # «подключался» ни время, ни адрес подключения не храним.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS connect_help (
                tg_id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                created_at TIMESTAMP
            )
        """)
        # Чёрный список: общий (из GitHub, перезаписывается при обновлении),
        # ручные записи админа и исключения из общего. Удержания — остаток
        # срока подписки, остановленной из-за ЧС, чтобы вернуть его при снятии.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS blacklist_remote (tg_id INTEGER PRIMARY KEY, reason TEXT)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist_manual (
                tg_id INTEGER PRIMARY KEY,
                reason TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist_allow (
                tg_id INTEGER PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist_hold (
                tg_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                sub_id INTEGER NOT NULL,
                remaining INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tg_id, kind)
            )
        """)
        # Тарифы: варианты продления, которые видит клиент.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tariffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                period_seconds INTEGER NOT NULL,
                price INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Платежи через платёжную систему.
        # Сумма и период кладутся снимком: правка тарифа не должна задним
        # числом менять уже созданный счёт.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                external_id TEXT,
                amount INTEGER NOT NULL,
                period_seconds INTEGER,
                promo_code TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                pay_url TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_external "
            "ON payments(provider, external_id)"
        )
        # Докуп устройств: счёт бывает за срок ('period') и за слоты ('devices'),
        # extra — сколько устройств куплено. Слоты живут вместе с подпиской.
        for table, col, decl in (
            ("payments", "kind", "TEXT NOT NULL DEFAULT 'period'"),
            ("payments", "extra", "INTEGER NOT NULL DEFAULT 0"),
            ("paid_subs", "extra_devices", "INTEGER NOT NULL DEFAULT 0"),
            # какое напоминание о скором конце уже отправлено: 0 — ни одного
            ("paid_subs", "remind_stage", "INTEGER NOT NULL DEFAULT 0"),
        ):
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except Exception:
                pass
        # Тикет — одна переписка с человеком. Статус и тема живут здесь,
        # сами сообщения остаются в support_messages.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                user_id INTEGER PRIMARY KEY,
                topic TEXT NOT NULL DEFAULT 'other',
                status TEXT NOT NULL DEFAULT 'open',
                waiting_since TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            )
        """)
        # Переписки, начатые до появления статусов, заводим как открытые:
        # иначе они пропали бы из списка «открытые»
        await db.execute("""
            INSERT OR IGNORE INTO tickets (user_id, topic, status, waiting_since, updated_at)
            SELECT sm.user_id, 'other',
                   CASE WHEN MAX(CASE WHEN sm.from_admin = 0 THEN sm.id ELSE 0 END) >
                             MAX(CASE WHEN sm.from_admin = 1 THEN sm.id ELSE 0 END)
                        THEN 'open' ELSE 'answered' END,
                   MAX(sm.created_at), MAX(sm.created_at)
            FROM support_messages sm GROUP BY sm.user_id
        """)

        # Отпечатки подписок: с каких устройств и адресов они работают.
        # Нужны, чтобы заметить второй триал с того же телефона.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS device_seen (
                email TEXT NOT NULL,
                tg_id INTEGER,
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(email, kind, value)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_seen_value ON device_seen(kind, value)"
        )
        # Найденные пары аккаунтов: одну пару показываем админу один раз
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fraud_pairs (
                tg_a INTEGER NOT NULL,
                tg_b INTEGER NOT NULL,
                kind TEXT,
                value TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tg_a, tg_b)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)"
        )
        # поля возврата: отзывать ли срок и когда возврат завершился
        for _col in ("refund_revoke INTEGER", "refunded_at TIMESTAMP"):
            try:
                await db.execute(f"ALTER TABLE payments ADD COLUMN {_col}")
            except Exception:
                pass
        # Баны. until — временный бан, снимется сам; by — кто забанил
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                tg_id INTEGER PRIMARY KEY,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for _col in ("reason TEXT", "until TIMESTAMP", "by_id INTEGER"):
            try:
                await db.execute(f"ALTER TABLE bans ADD COLUMN {_col}")
            except Exception:
                pass
        # Чёрный список: срок и автор записи
        for _col in ("until TIMESTAMP", "by_id INTEGER"):
            try:
                await db.execute(f"ALTER TABLE blacklist_manual ADD COLUMN {_col}")
            except Exception:
                pass
        # Журнал: кого, когда и за что вносили и снимали
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                by_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_bl_log_user ON blacklist_log(tg_id, created_at)")
        # Winback: stage — какая волна уже уходила человеку
        await db.execute("""
            CREATE TABLE IF NOT EXISTS winback_sent (
                tg_id INTEGER PRIMARY KEY,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await db.execute(
                "ALTER TABLE winback_sent ADD COLUMN stage INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass
        # убираем :443/:80 из существующих sub_url
        from panel import strip_default_port
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


async def get_dashboard_stats() -> dict:
    async def _one(db, q, params=()):
        async with db.execute(q, params) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    import re

    async with aiosqlite.connect(DB_PATH) as db:
        # локальная дата сервера — чтобы «сегодня» совпадало с реальными сутками,
        # а не с UTC-сутками, в которых SQLite пишет CURRENT_TIMESTAMP
        today_local = await _one(db, "SELECT date('now','localtime')")

        users_total = await _one(db, "SELECT COUNT(*) FROM users")
        users_today = await _one(db, "SELECT COUNT(*) FROM users WHERE date(created_at,'localtime') = date('now','localtime')")
        users_week = await _one(db, "SELECT COUNT(*) FROM users WHERE created_at >= datetime('now','-7 days')")

        paid_total = await _one(db, "SELECT COUNT(*) FROM paid_subs")
        paid_active = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE status IN ('active','renewal')")
        paid_expired = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE status = 'expired'")
        # обе метрики считаем по одному срезу — только активные, иначе сумма не сходится с paid_active
        trial_active = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE times_renewed = 0 AND status IN ('active','renewal')")
        paying_active = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE times_renewed > 0 AND status IN ('active','renewal')")
        paying_total = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE times_renewed > 0")
        paid_other = await _one(db, "SELECT COUNT(*) FROM paid_subs WHERE status NOT IN ('active','renewal','expired')")

        admin_subs = await _one(db, "SELECT COUNT(*) FROM admin_subs")

        ref_total = await _one(db, "SELECT COUNT(*) FROM referrals")
        ref_rewarded = await _one(db, "SELECT COUNT(*) FROM referrals WHERE rewarded = 1")

        promos_active = await _one(db, "SELECT COUNT(*) FROM promo_codes WHERE active = 1")
        promo_uses = await _one(db, "SELECT COUNT(*) FROM promo_uses")

        payments_confirmed = await _one(db, "SELECT COUNT(*) FROM paid_sub_history WHERE action = 'payment_confirmed'")
        payments_today = await _one(db, "SELECT COUNT(*) FROM paid_sub_history WHERE action = 'payment_confirmed' AND date(created_at,'localtime') = date('now','localtime')")
        # триалы считаем по факту создания подписки — покрывает и авто-выдачу,
        # и одобрение админом, и ручное создание из админки
        trials_issued = await _one(db, "SELECT COUNT(*) FROM paid_sub_history WHERE action = 'sub_created' AND details LIKE '%пробный период%'")
        open_tickets_unread = await _one(db, "SELECT COUNT(DISTINCT user_id) FROM support_messages WHERE from_admin = 0 AND is_read = 0")

        # реальная выручка из истории: details содержит "Сумма: N ₽"
        async with db.execute("""
            SELECT details, date(created_at,'localtime') FROM paid_sub_history
            WHERE action = 'payment_confirmed'
        """) as cur:
            pay_rows = await cur.fetchall()

    revenue_total = 0
    revenue_today = 0
    revenue_known = 0
    for details, day in pay_rows:
        m = re.search(r"Сумма:\s*(\d+)", details or "")
        if not m:
            continue
        amount = int(m.group(1))
        revenue_known += 1
        revenue_total += amount
        if day == today_local:
            revenue_today += amount

    return {
        "users_total": users_total, "users_today": users_today, "users_week": users_week,
        "paid_total": paid_total, "paid_active": paid_active, "paid_expired": paid_expired,
        "paid_other": paid_other,
        "trial_active": trial_active, "paying_active": paying_active, "paying_total": paying_total,
        "admin_subs": admin_subs,
        "ref_total": ref_total, "ref_rewarded": ref_rewarded,
        "promos_active": promos_active, "promo_uses": promo_uses,
        "payments_confirmed": payments_confirmed, "payments_today": payments_today,
        "trials_issued": trials_issued, "unread_tickets": open_tickets_unread,
        "revenue_total": revenue_total, "revenue_today": revenue_today,
        "revenue_known": revenue_known,
    }


async def control_today() -> dict:
    """Что произошло за сегодня: деньги, люди, подписки, сбои."""
    today = "date(?1, 'localtime') = date('now', 'localtime')"
    async with aiosqlite.connect(DB_PATH) as db:
        async def one(q, args=()):
            async with db.execute(q, args) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

        pays, amount = 0, 0
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments "
            f"WHERE status = 'paid' AND {today.replace('?1', 'COALESCE(paid_at, created_at)')}"
        ) as cur:
            pays, amount = await cur.fetchone()
        return {
            "pays": pays, "amount": amount,
            "refunds": await one(
                "SELECT COUNT(*) FROM payments WHERE status = 'refunded' AND "
                + today.replace("?1", "COALESCE(refunded_at, created_at)")),
            "failed": await one(
                "SELECT COUNT(*) FROM payments WHERE status IN ('canceled','expired','error') "
                "AND " + today.replace("?1", "created_at")),
            "new_users": await one(
                "SELECT COUNT(*) FROM users WHERE " + today.replace("?1", "created_at")),
            "trials": await one(
                "SELECT COUNT(*) FROM activity_log WHERE action = 'ev:trial_approved' AND "
                + today.replace("?1", "created_at")),
            "expired": await one(
                "SELECT COUNT(*) FROM activity_log WHERE action = 'ev:expired' AND "
                + today.replace("?1", "created_at")),
            "tickets": await one(
                "SELECT COUNT(DISTINCT user_id) FROM support_messages "
                "WHERE from_admin = 0 AND " + today.replace("?1", "created_at")),
            "blocked": await one(
                "SELECT COUNT(*) FROM blacklist_log WHERE action IN ('added','readded','banned') "
                "AND " + today.replace("?1", "created_at")),
        }


async def search_users(needle: str, limit: int = 12) -> list:
    """Поиск людей: по ID, @username, имени или имени клиента в панели."""
    needle = (needle or "").strip().lstrip("@")
    if not needle:
        return []
    like = f"%{needle.lower()}%"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT u.id, u.first_name, u.username,
                   (SELECT status FROM paid_subs p WHERE p.tg_id = u.id
                    ORDER BY p.id DESC LIMIT 1)
            FROM users u
            WHERE CAST(u.id AS TEXT) LIKE ?
               OR lower(u.username) LIKE ?
               OR lower(u.first_name) LIKE ?
               OR EXISTS (SELECT 1 FROM paid_subs p
                          WHERE p.tg_id = u.id AND lower(p.email) LIKE ?)
            ORDER BY (CAST(u.id AS TEXT) = ?) DESC, u.created_at DESC
            LIMIT ?
        """, (like, like, like, like, needle, int(limit))) as cur:
            return await cur.fetchall()


async def recent_visitors(limit: int = 6) -> list:
    """Кто заходил в бота последним — для быстрых кнопок в поиске."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT a.tg_id, u.first_name, u.username, MAX(a.created_at)
            FROM activity_log a LEFT JOIN users u ON u.id = a.tg_id
            WHERE a.is_admin = 0
            GROUP BY a.tg_id ORDER BY MAX(a.id) DESC LIMIT ?
        """, (int(limit),)) as cur:
            return await cur.fetchall()


async def get_payments_by_day(days: int = 30) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT date(created_at,'localtime') as d, COUNT(*) as cnt
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
            SELECT text, from_admin, datetime(created_at, 'localtime'), file_id, file_type
            FROM support_messages
            WHERE user_id = ?
            ORDER BY created_at ASC
            LIMIT ? OFFSET ?
        """, (user_id, MSGS_PER_PAGE, offset)) as cur:
            msgs = await cur.fetchall()
    total_pages = max(1, (total + MSGS_PER_PAGE - 1) // MSGS_PER_PAGE)
    return msgs, total_pages


# ── Тарифы ───────────────────────────────────────────────────────────────────

async def add_tariff(name: str, period_seconds: int, price: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM tariffs") as cur:
            order = (await cur.fetchone())[0]
        cur = await db.execute(
            "INSERT INTO tariffs (name, period_seconds, price, sort_order) VALUES (?, ?, ?, ?)",
            (name, period_seconds, price, order),
        )
        await db.commit()
        return cur.lastrowid


async def list_tariffs(only_active: bool = False) -> list[tuple]:
    q = "SELECT id, name, period_seconds, price, active, sort_order FROM tariffs"
    if only_active:
        q += " WHERE active = 1"
    q += " ORDER BY sort_order ASC, id ASC"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q) as cur:
            return await cur.fetchall()


async def get_tariff(tariff_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, name, period_seconds, price, active, sort_order "
            "FROM tariffs WHERE id = ?", (tariff_id,)
        ) as cur:
            return await cur.fetchone()


async def update_tariff_field(tariff_id: int, field: str, value):
    if field not in {"name", "period_seconds", "price", "active", "sort_order"}:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE tariffs SET {field} = ? WHERE id = ?", (value, tariff_id))
        await db.commit()


async def delete_tariff(tariff_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tariffs WHERE id = ?", (tariff_id,))
        await db.commit()


# ── Платежи ──────────────────────────────────────────────────────────────────

async def add_payment(tg_id: int, provider: str, external_id: str, amount: int,
                      period_seconds: int | None, pay_url: str,
                      promo_code: str | None = None,
                      kind: str = "period", extra: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO payments (tg_id, provider, external_id, amount,
                                  period_seconds, promo_code, status, pay_url, kind, extra)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """, (tg_id, provider, external_id, amount, period_seconds, promo_code,
              pay_url, kind, int(extra)))
        await db.commit()
        return cur.lastrowid


async def get_pending_payments(provider: str | None = None, limit: int = 50) -> list[tuple]:
    """Счета, ожидающие оплаты — их опрашивает фоновая задача."""
    # kind и extra в конце: старые распаковки по индексам продолжают работать
    q = """SELECT id, tg_id, provider, external_id, amount, period_seconds,
                  promo_code, created_at, kind, extra
           FROM payments WHERE status = 'pending'"""
    params: list = []
    if provider:
        q += " AND provider = ?"
        params.append(provider)
    q += " ORDER BY id ASC LIMIT ?"
    params.append(limit)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, params) as cur:
            return await cur.fetchall()


async def get_payment(payment_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, provider, external_id, amount, period_seconds,
                   promo_code, status, pay_url, created_at, paid_at
            FROM payments WHERE id = ?
        """, (payment_id,)) as cur:
            return await cur.fetchone()


async def get_active_payment(tg_id: int, provider: str) -> tuple | None:
    """Последний неоплаченный счёт юзера — чтобы не плодить дубли."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, provider, external_id, amount, period_seconds,
                   promo_code, status, pay_url, created_at, kind, extra
            FROM payments
            WHERE tg_id = ? AND provider = ? AND status = 'pending'
            ORDER BY id DESC LIMIT 1
        """, (tg_id, provider)) as cur:
            return await cur.fetchone()


async def set_payment_status(payment_id: int, status: str, error: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if status == "paid":
            await db.execute(
                "UPDATE payments SET status = ?, paid_at = CURRENT_TIMESTAMP, error = ? "
                "WHERE id = ?", (status, error, payment_id)
            )
        else:
            await db.execute(
                "UPDATE payments SET status = ?, error = ? WHERE id = ?",
                (status, error, payment_id)
            )
        await db.commit()


async def expire_stale_payments(minutes: int = 60) -> int:
    """Гасит счета, по которым так и не заплатили.

    Счёт в платёжной системе живёт ограниченное время (у Platega — 30 минут),
    после чего опрашивать его бессмысленно. Берём запас вдвое, чтобы не
    потерять оплату, подтверждённую у самого края срока.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            UPDATE payments SET status = 'expired'
            WHERE status = 'pending'
              AND created_at < datetime('now', ?)
        """, (f"-{minutes} minutes",))
        await db.commit()
        return cur.rowcount or 0


async def payments_summary() -> dict:
    """Сводка по деньгам. Считаем только фактически оплаченные счета."""
    async def _row(db, q, params=()):
        async with db.execute(q, params) as cur:
            return await cur.fetchone()

    paid = "status = 'paid'"
    async with aiosqlite.connect(DB_PATH) as db:
        def period(expr):
            return (f"SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments "
                    f"WHERE {paid} AND {expr}")

        today = await _row(db, period(
            "date(COALESCE(paid_at, created_at), 'localtime') = date('now', 'localtime')"))
        week = await _row(db, period(
            "COALESCE(paid_at, created_at) >= datetime('now', '-7 days')"))
        month = await _row(db, period(
            "COALESCE(paid_at, created_at) >= datetime('now', '-30 days')"))
        total = await _row(db, f"SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments WHERE {paid}")
        pending = await _row(db, "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments WHERE status = 'pending'")
        failed = await _row(db, "SELECT COUNT(*) FROM payments WHERE status IN ('canceled','expired','error')")
        refunds = await _row(db, "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments WHERE status IN ('refunded','refund_pending','chargebacked')")

        async with db.execute(
            f"SELECT provider, COUNT(*), COALESCE(SUM(amount), 0) FROM payments "
            f"WHERE {paid} GROUP BY provider ORDER BY 3 DESC"
        ) as cur:
            by_provider = await cur.fetchall()

        async with db.execute(
            f"SELECT COUNT(DISTINCT tg_id) FROM payments WHERE {paid}"
        ) as cur:
            payers = (await cur.fetchone())[0]

    cnt_total, sum_total = total
    return {
        "today": today, "week": week, "month": month,
        "total_count": cnt_total, "total_sum": sum_total,
        "pending_count": pending[0], "pending_sum": pending[1],
        "failed_count": failed[0],
        "refund_count": refunds[0], "refund_sum": refunds[1],
        "by_provider": by_provider,
        "payers": payers,
        "avg": round(sum_total / cnt_total) if cnt_total else 0,
    }


async def list_payments(page: int = 1, status: str = "paid",
                        per_page: int = 8) -> tuple[list, int]:
    """Платежи с пагинацией. status='all' — все подряд."""
    offset = (page - 1) * per_page
    where, params = "", []
    if status == "paid":
        where = "WHERE p.status = 'paid'"
    elif status == "pending":
        where = "WHERE p.status = 'pending'"
    elif status == "failed":
        where = "WHERE p.status IN ('canceled','expired','error')"
    elif status == "refunds":
        where = "WHERE p.status IN ('refunded','refund_pending','chargebacked')"

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT COUNT(*) FROM payments p {where}", params) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(f"""
            SELECT p.id, p.tg_id, p.provider, p.amount, p.status,
                   datetime(COALESCE(p.paid_at, p.created_at), 'localtime') AS ts,
                   u.first_name, u.username, p.promo_code, p.period_seconds
            FROM payments p
            LEFT JOIN users u ON u.id = p.tg_id
            {where}
            ORDER BY p.id DESC LIMIT ? OFFSET ?
        """, params + [per_page, offset]) as cur:
            rows = await cur.fetchall()
    return rows, max(1, (total + per_page - 1) // per_page)


async def get_payment_full(payment_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT p.id, p.tg_id, p.provider, p.external_id, p.amount,
                   p.period_seconds, p.promo_code, p.status, p.pay_url,
                   p.error, datetime(p.created_at, 'localtime'), datetime(p.paid_at, 'localtime'),
                   u.first_name, u.username
            FROM payments p
            LEFT JOIN users u ON u.id = p.tg_id
            WHERE p.id = ?
        """, (payment_id,)) as cur:
            return await cur.fetchone()


async def user_payments(tg_id: int, limit: int = 10) -> tuple[list, int, int]:
    """Оплаты конкретного юзера: строки, всего оплат, сумма."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments "
            "WHERE tg_id = ? AND status = 'paid'", (tg_id,)
        ) as cur:
            cnt, total = await cur.fetchone()
        async with db.execute("""
            SELECT id, provider, amount, status,
                   datetime(COALESCE(paid_at, created_at), 'localtime'), promo_code
            FROM payments WHERE tg_id = ?
            ORDER BY id DESC LIMIT ?
        """, (tg_id, limit)) as cur:
            rows = await cur.fetchall()
    return rows, cnt, total


async def mark_refund_pending(payment_id: int, revoke: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payments SET status = 'refund_pending', refund_revoke = ? WHERE id = ?",
            (1 if revoke else 0, payment_id),
        )
        await db.commit()


async def claim_refund(payment_id: int) -> bool:
    """Переводит платёж в «возвращён». True — если перевёл именно этот вызов.

    Довести возврат могут одновременно и кнопка, и фоновая сверка: атомарный
    переход не даёт отозвать срок дважды за один возврат.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE payments SET status = 'refunded', refunded_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status != 'refunded'", (payment_id,),
        )
        await db.commit()
        return (cur.rowcount or 0) > 0


async def get_refund_revoke(payment_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT refund_revoke FROM payments WHERE id = ?", (payment_id,)
        ) as cur:
            r = await cur.fetchone()
    return r[0] if r else None


async def get_refund_watchlist(days: int = 30, limit: int = 100) -> list[tuple]:
    """Платежи, у которых может появиться возврат.

    О возврате из личного кабинета Platega бот узнаёт, только перечитав статус
    оплаченной транзакции. Сначала — возвраты в обработке, затем свежие оплаты.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, external_id, amount, period_seconds, status
            FROM payments
            WHERE provider = 'platega'
              AND external_id IS NOT NULL
              AND (status = 'refund_pending'
                   OR (status = 'paid'
                       AND COALESCE(paid_at, created_at) >= datetime('now', ?)))
            ORDER BY CASE status WHEN 'refund_pending' THEN 0 ELSE 1 END, id DESC
            LIMIT ?
        """, (f"-{days} days", limit)) as cur:
            return await cur.fetchall()


# ── Журнал действий ──────────────────────────────────────────────────────────

async def log_activity(tg_id: int, action: str, details: str | None = None,
                       is_admin: bool = False):
    """Одна запись журнала. Ошибки глотаем: журнал не должен ломать бота."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO activity_log (tg_id, is_admin, action, details) VALUES (?, ?, ?, ?)",
                (tg_id, 1 if is_admin else 0, str(action)[:120],
                 str(details)[:200] if details else None),
            )
            await db.commit()
    except Exception:
        pass


def _activity_where(scope: str):
    from config import ADMIN_ID
    if scope == "important":
        return "a.action LIKE 'ev:%'", []
    if scope == "admin":
        return "a.is_admin = 1", []
    if scope == "helpers":
        # только помощники: сам админ в этой вкладке не мешает
        return "a.is_admin = 1 AND a.tg_id != ?", [ADMIN_ID]
    if scope.startswith("user_important:"):
        return "a.tg_id = ? AND a.action LIKE 'ev:%'", [int(scope.split(":", 1)[1])]
    if scope.startswith("user:"):
        return "a.tg_id = ?", [int(scope.split(":", 1)[1])]
    return "a.is_admin = 0", []


async def list_activity(scope: str = "all", page: int = 1, per_page: int = 15):
    """Журнал с пагинацией. Время отдаём в местном поясе."""
    where, params = _activity_where(scope)
    offset = (page - 1) * per_page
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT COUNT(*) FROM activity_log a WHERE {where}", params) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(f"""
            SELECT a.tg_id, a.action, a.details, datetime(a.created_at, 'localtime'),
                   u.first_name, u.username
            FROM activity_log a LEFT JOIN users u ON u.id = a.tg_id
            WHERE {where}
            ORDER BY a.id DESC LIMIT ? OFFSET ?
        """, params + [per_page, offset]) as cur:
            rows = await cur.fetchall()
    return rows, max(1, (total + per_page - 1) // per_page)


async def activity_summary() -> dict:
    today = "date(created_at, 'localtime') = date('now', 'localtime')"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT COUNT(DISTINCT tg_id), COUNT(*) FROM activity_log WHERE is_admin = 0 AND {today}"
        ) as cur:
            active_today, events_today = await cur.fetchone()
        async with db.execute(
            "SELECT COUNT(DISTINCT tg_id) FROM activity_log "
            "WHERE is_admin = 0 AND created_at >= datetime('now', '-7 days')"
        ) as cur:
            active_week = (await cur.fetchone())[0]
        async with db.execute(
            f"SELECT action FROM activity_log WHERE is_admin = 0 AND {today} AND action NOT LIKE 'ev:%'"
        ) as cur:
            actions = [r[0] for r in await cur.fetchall()]
        async with db.execute("""
            SELECT a.tg_id, a.action, a.details, datetime(a.created_at, 'localtime'),
                   u.first_name, u.username
            FROM activity_log a LEFT JOIN users u ON u.id = a.tg_id
            WHERE a.action LIKE 'ev:%' ORDER BY a.id DESC LIMIT 5
        """) as cur:
            recent = await cur.fetchall()

    counts = {}
    for a in actions:
        kind, _, rest = a.partition(":")
        key = f"{kind}:{rest.split(':')[0]}"
        counts[key] = counts.get(key, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
    return {"active_today": active_today, "events_today": events_today,
            "active_week": active_week, "top_today": top, "recent_events": recent}


async def users_by_emails(emails: list) -> dict:
    """email клиента в панели → (tg_id, имя, username)."""
    emails = [e for e in emails if e]
    if not emails:
        return {}
    marks = ",".join("?" * len(emails))
    out = {}
    async with aiosqlite.connect(DB_PATH) as db:
        for table in ("paid_subs", "admin_subs"):
            async with db.execute(f"""
                SELECT s.email, s.tg_id, u.first_name, u.username
                FROM {table} s LEFT JOIN users u ON u.id = s.tg_id
                WHERE s.email IN ({marks})
            """, emails) as cur:
                for email, tg_id, fn, un in await cur.fetchall():
                    out.setdefault(email, (tg_id, fn, un))
    return out


async def recent_subs_for_connect_help(window_hours: int) -> list[tuple]:
    """Свежие подписки, по которым ещё не решили, помогать ли с подключением.

    (tg_id, email, status, возраст подписки в секундах)
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT s.tg_id, s.email, s.status,
                   CAST((julianday('now') - julianday(s.created_at)) * 86400 AS INTEGER)
            FROM paid_subs s
            WHERE s.tg_id IS NOT NULL
              AND s.created_at >= datetime('now', ?)
              AND s.tg_id NOT IN (SELECT tg_id FROM connect_help)
        """, (f"-{int(window_hours)} hours",)) as cur:
            return await cur.fetchall()


async def mark_connect_help(tg_id: int, kind: str) -> bool:
    """Отметка: 'seen' — подключался, 'sent' — ему написали.

    True, если отметка новая: два прохода не напишут одному человеку дважды.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO connect_help (tg_id, kind, created_at) "
            "VALUES (?, ?, CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP END)",
            (tg_id, kind, kind),
        )
        await db.commit()
        return cur.rowcount == 1


async def connect_help_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN created_at >= datetime('now', '-7 days') THEN 1 ELSE 0 END)
            FROM connect_help WHERE kind = 'sent'
        """) as cur:
            total, week = await cur.fetchone()
    return {"total": total or 0, "week": week or 0}


async def find_user_by_username(username: str) -> tuple | None:
    """(id, first_name, username) по @username без учёта регистра."""
    name = username.strip().lstrip("@")
    if not name:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, first_name, username FROM users WHERE lower(username) = lower(?)", (name,)
        ) as cur:
            return await cur.fetchone()


# ── Чёрный список ────────────────────────────────────────────────────────────

async def bl_lookup(tg_id: int) -> dict:
    """Всё про ID: ручная запись, запись общего списка, исключение."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT reason, datetime(created_at, 'localtime'), "
            "datetime(until, 'localtime'), by_id FROM blacklist_manual WHERE tg_id = ?",
            (tg_id,),
        ) as cur:
            manual = await cur.fetchone()
        async with db.execute("SELECT reason FROM blacklist_remote WHERE tg_id = ?", (tg_id,)) as cur:
            remote = await cur.fetchone()
        async with db.execute("SELECT 1 FROM blacklist_allow WHERE tg_id = ?", (tg_id,)) as cur:
            allowed = await cur.fetchone() is not None
    return {"manual": manual, "remote_listed": remote is not None,
            "remote": remote[0] if remote else None, "allowed": allowed}


async def bl_replace_remote(entries: dict) -> tuple[set, set]:
    """Перезаписывает общий список одной транзакцией: (новые ID, пропавшие ID)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT tg_id FROM blacklist_remote") as cur:
            old = {r[0] for r in await cur.fetchall()}
        await db.execute("DELETE FROM blacklist_remote")
        await db.executemany("INSERT INTO blacklist_remote (tg_id, reason) VALUES (?, ?)",
                             list(entries.items()))
        await db.commit()
    new = set(entries)
    return new - old, old - new


async def bl_add_manual(tg_id: int, reason: str, until: str | None = None,
                        by_id: int | None = None):
    """until — до какого момента (ISO-строка) держать в ЧС. None — бессрочно."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO blacklist_manual (tg_id, reason, until, by_id) "
            "VALUES (?, ?, ?, ?)", (tg_id, reason, until, by_id))
        await db.execute("DELETE FROM blacklist_allow WHERE tg_id = ?", (tg_id,))
        await db.commit()


async def bl_log(tg_id: int, action: str, reason: str | None = None,
                 by_id: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO blacklist_log (tg_id, action, reason, by_id) VALUES (?, ?, ?, ?)",
            (tg_id, action, reason, by_id))
        await db.commit()


async def bl_history(tg_id: int, limit: int = 5) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT action, reason, by_id, datetime(created_at, 'localtime') "
            "FROM blacklist_log WHERE tg_id = ? ORDER BY id DESC LIMIT ?",
            (tg_id, int(limit)),
        ) as cur:
            return await cur.fetchall()


async def bl_times_listed(tg_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM blacklist_log WHERE tg_id = ? AND action IN ('added', 'readded')",
            (tg_id,),
        ) as cur:
            return (await cur.fetchone())[0]


async def bl_expired_now() -> list:
    """Кому срок в ЧС уже вышел."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tg_id, reason FROM blacklist_manual "
            "WHERE until IS NOT NULL AND until <= CURRENT_TIMESTAMP"
        ) as cur:
            return await cur.fetchall()


async def bl_remove(tg_id: int):
    """Снимает с ЧС: ручную запись удаляет, для общего списка ставит исключение."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM blacklist_manual WHERE tg_id = ?", (tg_id,))
        await db.execute(
            "INSERT OR IGNORE INTO blacklist_allow (tg_id) "
            "SELECT tg_id FROM blacklist_remote WHERE tg_id = ?", (tg_id,))
        await db.commit()


async def bl_unallow(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM blacklist_allow WHERE tg_id = ?", (tg_id,))
        await db.commit()


# кто сейчас в ЧС: ручные записи плюс общий список без исключений
_BL_CTE = """
    WITH bl AS (
        SELECT tg_id FROM blacklist_manual
        UNION
        SELECT tg_id FROM blacklist_remote
        WHERE ? = 1 AND tg_id NOT IN (SELECT tg_id FROM blacklist_allow)
    )
"""


async def bl_effective_ids(use_remote: bool) -> set:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(_BL_CTE + "SELECT tg_id FROM bl", (1 if use_remote else 0,)) as cur:
            return {r[0] for r in await cur.fetchall()}


async def bl_counts(use_remote: bool) -> dict:
    flag = (1 if use_remote else 0,)
    async with aiosqlite.connect(DB_PATH) as db:
        async def one(q, params=()):
            async with db.execute(q, params) as cur:
                return (await cur.fetchone())[0]
        return {
            "remote": await one("SELECT COUNT(*) FROM blacklist_remote"),
            "manual": await one("SELECT COUNT(*) FROM blacklist_manual"),
            "allow": await one("SELECT COUNT(*) FROM blacklist_allow"),
            "ours": await one(_BL_CTE + "SELECT COUNT(*) FROM users u JOIN bl ON bl.tg_id = u.id", flag),
            "ours_active": await one(
                _BL_CTE + "SELECT COUNT(DISTINCT s.tg_id) FROM paid_subs s "
                "JOIN bl ON bl.tg_id = s.tg_id WHERE s.status IN ('active', 'renewal')", flag),
        }


async def bl_stats() -> dict:
    """Итоги по блокировкам: сколько, каких и что было за месяц."""
    async with aiosqlite.connect(DB_PATH) as db:
        async def one(q, args=()):
            async with db.execute(q, args) as cur:
                return (await cur.fetchone())[0]
        return {
            "temporary": await one(
                "SELECT COUNT(*) FROM blacklist_manual WHERE until IS NOT NULL"),
            "forever": await one(
                "SELECT COUNT(*) FROM blacklist_manual WHERE until IS NULL"),
            "banned": await one(
                "SELECT COUNT(*) FROM bans "
                "WHERE until IS NULL OR until > CURRENT_TIMESTAMP"),
            "banned_temp": await one(
                "SELECT COUNT(*) FROM bans WHERE until > CURRENT_TIMESTAMP"),
            "added_30d": await one(
                "SELECT COUNT(*) FROM blacklist_log WHERE action IN ('added', 'readded') "
                "AND created_at >= datetime('now', '-30 days')"),
            "removed_30d": await one(
                "SELECT COUNT(*) FROM blacklist_log WHERE action IN ('removed', 'expired') "
                "AND created_at >= datetime('now', '-30 days')"),
            "held": await one("SELECT COUNT(*) FROM blacklist_hold"),
            "held_seconds": await one(
                "SELECT COALESCE(SUM(remaining), 0) FROM blacklist_hold"),
        }


async def bl_list(scope: str, use_remote: bool, page: int = 1, per_page: int = 10):
    """Строки (tg_id, имя, username, причина, источник) и число страниц."""
    if scope == "manual":
        base = "FROM blacklist_manual m LEFT JOIN users u ON u.id = m.tg_id"
        cols = "m.tg_id, u.first_name, u.username, m.reason, 'manual'"
        order, params = "m.created_at DESC", []
    elif scope == "allow":
        base = ("FROM blacklist_allow a LEFT JOIN users u ON u.id = a.tg_id "
                "LEFT JOIN blacklist_remote r ON r.tg_id = a.tg_id")
        cols = "a.tg_id, u.first_name, u.username, r.reason, 'allow'"
        order, params = "a.created_at DESC", []
    else:
        base = ("FROM users u LEFT JOIN blacklist_manual m ON m.tg_id = u.id "
                "LEFT JOIN blacklist_remote r ON r.tg_id = u.id AND ? = 1 "
                "AND u.id NOT IN (SELECT tg_id FROM blacklist_allow) "
                "WHERE m.tg_id IS NOT NULL OR r.tg_id IS NOT NULL")
        cols = ("u.id, u.first_name, u.username, COALESCE(m.reason, r.reason), "
                "CASE WHEN m.tg_id IS NOT NULL THEN 'manual' ELSE 'remote' END")
        order, params = "(m.tg_id IS NULL), m.created_at DESC, u.id DESC", [1 if use_remote else 0]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT COUNT(*) {base}", params) as cur:
            total = (await cur.fetchone())[0]
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(max(1, page), pages)
        async with db.execute(f"SELECT {cols} {base} ORDER BY {order} LIMIT ? OFFSET ?",
                              params + [per_page, (page - 1) * per_page]) as cur:
            return await cur.fetchall(), pages


async def bl_hold_set(tg_id: int, kind: str, sub_id: int, remaining: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO blacklist_hold (tg_id, kind, sub_id, remaining) VALUES (?, ?, ?, ?)",
            (tg_id, kind, sub_id, int(remaining)))
        await db.commit()


async def bl_holds(tg_id: int | None = None) -> list:
    """Удержания: (tg_id, вид, id подписки, остаток в секундах)."""
    q = "SELECT tg_id, kind, sub_id, remaining FROM blacklist_hold"
    params = ()
    if tg_id is not None:
        q += " WHERE tg_id = ?"
        params = (tg_id,)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, params) as cur:
            return await cur.fetchall()


async def bl_hold_take(tg_id: int) -> list:
    """Забирает удержания человека: (вид, id подписки, остаток). Второй раз их не вернуть."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT kind, sub_id, remaining FROM blacklist_hold WHERE tg_id = ?", (tg_id,)
        ) as cur:
            rows = await cur.fetchall()
        await db.execute("DELETE FROM blacklist_hold WHERE tg_id = ?", (tg_id,))
        await db.commit()
    return rows


async def bl_remote_subs() -> list:
    """Подписки людей из общего списка без исключений: (tg_id, статус, продлений)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT s.tg_id, s.status, s.times_renewed FROM paid_subs s
            JOIN blacklist_remote r ON r.tg_id = s.tg_id
            WHERE s.tg_id NOT IN (SELECT tg_id FROM blacklist_allow)
            ORDER BY s.created_at DESC
        """) as cur:
            return await cur.fetchall()


async def digest_stats(day_offset: int = 1) -> dict:
    """Цифры за сутки в местном времени: 1 — вчера, 0 — сегодня."""
    day = f"date('now', 'localtime', '-{int(day_offset)} day')"

    def on(col: str) -> str:
        return f"date({col}, 'localtime') = {day}"

    async with aiosqlite.connect(DB_PATH) as db:
        async def one(q):
            async with db.execute(q) as cur:
                return await cur.fetchone()

        new_users = (await one(f"SELECT COUNT(*) FROM users WHERE {on('created_at')}"))[0]
        active, actions = await one(
            f"SELECT COUNT(DISTINCT tg_id), COUNT(*) FROM activity_log "
            f"WHERE is_admin = 0 AND {on('created_at')}")
        trials = (await one(
            f"SELECT COUNT(*) FROM paid_sub_history WHERE action = 'sub_created' "
            f"AND details LIKE '%пробный период%' AND {on('created_at')}"))[0]
        paid_cnt, paid_sum = await one(
            f"SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments "
            f"WHERE paid_at IS NOT NULL AND {on('paid_at')}")
        ref_cnt, ref_sum = await one(
            f"SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments "
            f"WHERE refunded_at IS NOT NULL AND {on('refunded_at')}")
        ended = (await one(
            f"SELECT COUNT(*) FROM activity_log WHERE action = 'ev:period_ended' AND {on('created_at')}"))[0]
        expired = (await one(
            f"SELECT COUNT(*) FROM activity_log WHERE action = 'ev:expired' AND {on('created_at')}"))[0]
        sup_msgs, sup_users = await one(
            f"SELECT COUNT(*), COUNT(DISTINCT user_id) FROM support_messages "
            f"WHERE from_admin = 0 AND {on('created_at')}")
        active_subs = (await one(
            "SELECT COUNT(*) FROM paid_subs WHERE status IN ('active','renewal')"))[0]
        label = (await one(f"SELECT strftime('%d.%m', {day})"))[0]

    return {"new_users": new_users, "active": active, "actions": actions,
            "trials": trials, "paid_cnt": paid_cnt, "paid_sum": paid_sum,
            "ref_cnt": ref_cnt, "ref_sum": ref_sum, "ended": ended, "expired": expired,
            "sup_msgs": sup_msgs, "sup_users": sup_users,
            "active_subs": active_subs, "label": label}


async def remind_stats(days: int = 30) -> dict:
    """Сколько напоминаний ушло и сколько людей после них заплатили."""
    window = f"-{int(days)} days"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM activity_log WHERE action = 'ev:reminded' "
            "AND created_at >= datetime('now', ?)", (window,),
        ) as cur:
            sent = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(DISTINCT tg_id) FROM activity_log WHERE action = 'ev:reminded' "
            "AND created_at >= datetime('now', ?)", (window,),
        ) as cur:
            people = (await cur.fetchone())[0]
        # заплатил после того, как получил напоминание
        async with db.execute("""
            SELECT COUNT(*) FROM (
                SELECT a.tg_id, MIN(a.created_at) AS first_rem
                FROM activity_log a
                WHERE a.action = 'ev:reminded' AND a.created_at >= datetime('now', ?)
                GROUP BY a.tg_id
            ) r
            WHERE EXISTS (
                SELECT 1 FROM payments p
                WHERE p.tg_id = r.tg_id AND p.status = 'paid'
                  AND p.paid_at IS NOT NULL AND p.paid_at >= r.first_rem
            )
        """, (window,)) as cur:
            paid = (await cur.fetchone())[0]
    return {"sent": sent, "people": people, "paid": paid,
            "percent": round(paid * 100 / people) if people else 0}


async def purge_activity(days: int = 90) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM activity_log WHERE created_at < datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        await db.commit()
        return cur.rowcount or 0


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
            SELECT file_id, file_type, from_admin, datetime(created_at, 'localtime')
            FROM support_messages
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


async def get_ticket_users(page: int = 1, status: str = "open"):
    """Переписки для админского списка.

    Открытые идут первыми и сортируются по времени ожидания: дольше всех
    ждущий человек оказывается наверху, а не теряется под свежими.
    """
    offset = (page - 1) * TICKETS_PER_PAGE
    where = ""
    params: list = []
    if status == "open":
        where = "WHERE COALESCE(t.status, 'open') = 'open'"
    elif status == "closed":
        where = "WHERE t.status = 'closed'"
    elif status == "answered":
        where = "WHERE t.status = 'answered'"

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT sm.user_id FROM support_messages sm
                LEFT JOIN tickets t ON t.user_id = sm.user_id
                {where}
                GROUP BY sm.user_id
                HAVING SUM(CASE WHEN sm.from_admin = 0 THEN 1 ELSE 0 END) > 0
            )
        """, params) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(f"""
            SELECT
                u.id, u.first_name, u.username,
                COUNT(sm.id) AS total,
                SUM(CASE WHEN sm.from_admin = 0 AND sm.is_read = 0 THEN 1 ELSE 0 END) AS unread,
                datetime(MAX(sm.created_at), 'localtime') AS last_time,
                (SELECT text FROM support_messages s2 WHERE s2.user_id = u.id ORDER BY s2.id DESC LIMIT 1) AS last_text,
                (SELECT from_admin FROM support_messages s3 WHERE s3.user_id = u.id ORDER BY s3.id DESC LIMIT 1) AS last_from_admin,
                COALESCE(t.status, 'open') AS status,
                COALESCE(t.topic, 'other') AS topic,
                CAST(strftime('%s', 'now') - strftime('%s', t.waiting_since) AS INTEGER) AS waiting
            FROM support_messages sm
            JOIN users u ON u.id = sm.user_id
            LEFT JOIN tickets t ON t.user_id = sm.user_id
            {where}
            GROUP BY sm.user_id
            HAVING SUM(CASE WHEN sm.from_admin = 0 THEN 1 ELSE 0 END) > 0
            ORDER BY CASE WHEN COALESCE(t.status, 'open') = 'open' THEN 0 ELSE 1 END,
                     waiting DESC, last_time DESC
            LIMIT ? OFFSET ?
        """, params + [TICKETS_PER_PAGE, offset]) as cur:
            rows = await cur.fetchall()
    total_pages = max(1, (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE)
    return rows, total_pages


async def ticket_opened(user_id: int, topic: str | None = None):
    """Человек написал: переписка открыта и ждёт ответа.

    Время ожидания ставим только если его ещё нет — иначе каждое новое
    сообщение сбрасывало бы счётчик, и давно ждущий уходил бы вниз списка.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO tickets (user_id, topic, status, waiting_since, updated_at)
            VALUES (?, COALESCE(?, 'other'), 'open', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                status = 'open',
                topic = COALESCE(?, tickets.topic),
                waiting_since = COALESCE(tickets.waiting_since, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP,
                closed_at = NULL
        """, (user_id, topic, topic))
        await db.commit()


async def ticket_answered(user_id: int):
    """Поддержка ответила — ожидание закончилось."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO tickets (user_id, status, waiting_since, updated_at)
            VALUES (?, 'answered', NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                status = 'answered', waiting_since = NULL, updated_at = CURRENT_TIMESTAMP
        """, (user_id,))
        await db.commit()


async def ticket_closed(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO tickets (user_id, status, waiting_since, updated_at, closed_at)
            VALUES (?, 'closed', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                status = 'closed', waiting_since = NULL,
                updated_at = CURRENT_TIMESTAMP, closed_at = CURRENT_TIMESTAMP
        """, (user_id,))
        await db.commit()


async def get_ticket(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT topic, status,
                   CAST(strftime('%s', 'now') - strftime('%s', waiting_since) AS INTEGER)
            FROM tickets WHERE user_id = ?
        """, (user_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return {"topic": "other", "status": "open", "waiting": 0}
    return {"topic": row[0] or "other", "status": row[1] or "open",
            "waiting": int(row[2] or 0)}


async def ticket_counts() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        out = {}
        for key, cond in (("open", "= 'open'"), ("answered", "= 'answered'"),
                          ("closed", "= 'closed'")):
            async with db.execute(f"""
                SELECT COUNT(*) FROM (
                    SELECT sm.user_id FROM support_messages sm
                    LEFT JOIN tickets t ON t.user_id = sm.user_id
                    WHERE COALESCE(t.status, 'open') {cond}
                    GROUP BY sm.user_id
                    HAVING SUM(CASE WHEN sm.from_admin = 0 THEN 1 ELSE 0 END) > 0
                )
            """) as cur:
                out[key] = (await cur.fetchone())[0]
        out["all"] = out["open"] + out["answered"] + out["closed"]
        return out


async def user_payment_total(tg_id: int) -> tuple:
    """Сколько человек заплатил всего и сколько было платежей."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM payments "
            "WHERE tg_id = ? AND status = 'paid'", (tg_id,)
        ) as cur:
            return await cur.fetchone()


async def get_user_info(user_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, first_name, username FROM users WHERE id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone()


# ── Баны ─────────────────────────────────────────────────────────────────────

async def ban_user(tg_id: int, reason: str | None = None,
                   until: str | None = None, by_id: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bans (tg_id, banned_at, reason, until, by_id) "
            "VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?)", (tg_id, reason, until, by_id))
        await db.commit()


async def ban_entry(tg_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT reason, datetime(until, 'localtime'), by_id, "
            "datetime(banned_at, 'localtime') FROM bans WHERE tg_id = ?", (tg_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {"reason": row[0], "until": row[1], "by_id": row[2], "since": row[3]}


async def bans_expired_now() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tg_id FROM bans WHERE until IS NOT NULL AND until <= CURRENT_TIMESTAMP"
        ) as cur:
            return [r[0] for r in await cur.fetchall()]


async def bans_list(page: int = 1, per_page: int = 10) -> tuple:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM bans") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT b.tg_id, u.first_name, u.username, b.reason, "
            "datetime(b.until, 'localtime') FROM bans b "
            "LEFT JOIN users u ON u.id = b.tg_id "
            "ORDER BY b.banned_at DESC LIMIT ? OFFSET ?",
            (per_page, (page - 1) * per_page),
        ) as cur:
            rows = await cur.fetchall()
    pages = max(1, (total + per_page - 1) // per_page)
    return rows, pages, total


async def unban_user(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bans WHERE tg_id = ?", (tg_id,))
        await db.commit()


async def is_banned(tg_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM bans WHERE tg_id = ? "
            "AND (until IS NULL OR until > CURRENT_TIMESTAMP)", (tg_id,),
        ) as cur:
            return (await cur.fetchone()) is not None


# ── Winback ──────────────────────────────────────────────────────────────────

async def winback_stage(tg_id: int) -> int:
    """Какая волна человеку уже уходила. 0 — ещё ни одной."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT stage FROM winback_sent WHERE tg_id = ?", (tg_id,)) as cur:
            row = await cur.fetchone()
    return int(row[0] or 1) if row else 0


async def winback_stats() -> dict:
    """Сколько писем ушло и сколько людей после них вернулись."""
    async with aiosqlite.connect(DB_PATH) as db:
        async def one(q, args=()):
            async with db.execute(q, args) as cur:
                return (await cur.fetchone())[0]
        people = await one("SELECT COUNT(*) FROM winback_sent")
        sent = await one("SELECT COALESCE(SUM(stage), 0) FROM winback_sent")
        used = await one("SELECT COUNT(*) FROM promo_uses WHERE code LIKE 'BACK%'")
        returned = await one("""
            SELECT COUNT(*) FROM (
                SELECT w.tg_id FROM winback_sent w
                WHERE EXISTS (
                    SELECT 1 FROM payments p
                    WHERE p.tg_id = w.tg_id AND p.status = 'paid'
                      AND p.paid_at IS NOT NULL AND p.paid_at >= w.sent_at
                ) GROUP BY w.tg_id
            )
        """)
    return {"people": people, "sent": sent, "used": used, "returned": returned,
            "percent": round(returned * 100 / people) if people else 0}


async def mark_winback_sent(tg_id: int, stage: int = 1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO winback_sent (tg_id, stage, sent_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)", (tg_id, int(stage)))
        await db.commit()


# ── Отпечатки подписок и находки антифрода ───────────────────────────────────

async def remember_fingerprints(email: str, tg_id: int, kind: str, values) -> list:
    """Запоминает отпечатки подписки. Возвращает те, что увидели впервые.

    Только новые и возвращаем: сверять заново каждый раз одно и то же —
    это лишние тревоги админу про давно известную пару.
    """
    values = [str(v) for v in (values or []) if v]
    if not values:
        return []
    fresh = []
    async with aiosqlite.connect(DB_PATH) as db:
        for value in values:
            cur = await db.execute(
                "UPDATE device_seen SET last_seen = CURRENT_TIMESTAMP, tg_id = ? "
                "WHERE email = ? AND kind = ? AND value = ?",
                (tg_id, email, kind, value),
            )
            if not cur.rowcount:
                await db.execute(
                    "INSERT OR IGNORE INTO device_seen (email, tg_id, kind, value) "
                    "VALUES (?, ?, ?, ?)", (email, tg_id, kind, value),
                )
                fresh.append(value)
        await db.commit()
    return fresh


async def fingerprint_owners(kind: str, value: str, exclude_tg: int) -> list:
    """Чьи ещё подписки засветились с этим отпечатком."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT DISTINCT tg_id, email FROM device_seen "
            "WHERE kind = ? AND value = ? AND tg_id IS NOT NULL AND tg_id != ?",
            (kind, value, exclude_tg),
        ) as cur:
            return await cur.fetchall()


async def note_fraud_pair(a: int, b: int, kind: str, value: str) -> bool:
    """Записывает находку. False — про эту пару уже говорили."""
    lo, hi = (a, b) if a <= b else (b, a)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO fraud_pairs (tg_a, tg_b, kind, value) VALUES (?, ?, ?, ?)",
            (lo, hi, kind, value),
        )
        await db.commit()
        return bool(cur.rowcount)


async def ignore_fraud_pair(a: int, b: int):
    lo, hi = (a, b) if a <= b else (b, a)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE fraud_pairs SET status = 'ignored' WHERE tg_a = ? AND tg_b = ?", (lo, hi)
        )
        await db.commit()


async def set_fraud_pair_status(a: int, b: int, status: str):
    lo, hi = (a, b) if a <= b else (b, a)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE fraud_pairs SET status = ? WHERE tg_a = ? AND tg_b = ?", (status, lo, hi)
        )
        await db.commit()


async def get_fraud_pair(a: int, b: int) -> tuple | None:
    lo, hi = (a, b) if a <= b else (b, a)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tg_a, tg_b, kind, value, status, created_at FROM fraud_pairs "
            "WHERE tg_a = ? AND tg_b = ?", (lo, hi),
        ) as cur:
            return await cur.fetchone()


async def list_fraud_pairs(status: str | None = None, limit: int = 15) -> list:
    """Находки для экрана. status=None — все, иначе new / ignored / blocked."""
    q = ("SELECT tg_a, tg_b, kind, value, status, created_at FROM fraud_pairs")
    args: list = []
    if status:
        q += " WHERE status = ?"
        args.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(int(limit))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, args) as cur:
            return await cur.fetchall()


async def fingerprint_cluster(kind: str, value: str) -> list:
    """Все аккаунты, засветившиеся с этим отпечатком, с датами."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tg_id, email, MIN(first_seen), MAX(last_seen) FROM device_seen "
            "WHERE kind = ? AND value = ? AND tg_id IS NOT NULL GROUP BY tg_id, email "
            "ORDER BY MIN(first_seen)",
            (kind, value),
        ) as cur:
            return await cur.fetchall()


async def user_fingerprint_stats(tg_id: int) -> dict:
    """Сколько устройств и адресов запомнено у человека."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT kind, COUNT(DISTINCT value) FROM device_seen "
            "WHERE tg_id = ? GROUP BY kind", (tg_id,),
        ) as cur:
            return {k: n for k, n in await cur.fetchall()}


async def fraud_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async def one(q):
            async with db.execute(q) as cur:
                return (await cur.fetchone())[0]
        return {
            "fingerprints": await one("SELECT COUNT(*) FROM device_seen"),
            "devices": await one("SELECT COUNT(DISTINCT value) FROM device_seen WHERE kind = 'hwid'"),
            "ips": await one("SELECT COUNT(DISTINCT value) FROM device_seen WHERE kind = 'ip'"),
            "pairs": await one("SELECT COUNT(*) FROM fraud_pairs"),
            "new": await one("SELECT COUNT(*) FROM fraud_pairs WHERE status = 'new'"),
            "ignored": await one("SELECT COUNT(*) FROM fraud_pairs WHERE status = 'ignored'"),
            "blocked": await one("SELECT COUNT(*) FROM fraud_pairs WHERE status = 'blocked'"),
            # отпечаток, который светится больше чем у двух аккаунтов, — уже не совпадение
            "clusters": await one(
                "SELECT COUNT(*) FROM (SELECT value FROM device_seen WHERE kind = 'hwid' "
                "AND tg_id IS NOT NULL GROUP BY value HAVING COUNT(DISTINCT tg_id) > 2)"),
        }
