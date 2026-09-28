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


# Срок хранится текстом «дд.мм.гггг чч:мм:сс» — для сравнений и сортировки
# собираем из него ключ «ггггммдд чч:мм:сс»: по нему строки сортируются как даты
_EXP_KEY = ("substr(expire_date, 7, 4) || substr(expire_date, 4, 2) || "
            "substr(expire_date, 1, 2) || substr(expire_date, 11)")

# Вкладки списка подписок. Выключенных в панели здесь нет: это состояние знает
# только панель, поэтому такую вкладку собирает уже сам экран.
PAID_SCOPES = {
    "all": "1 = 1",
    "active": "status = 'active'",
    "soon": f"status = 'active' AND {_EXP_KEY} <= ?soon",
    "expired": "status = 'expired'",
    "trial": "times_renewed = 0",
    "paying": "times_renewed > 0",
}

PAID_SORTS = {
    "new": "created_at DESC, id DESC",
    "expire": f"{_EXP_KEY} ASC",
    "name": "email ASC",
}

# Сколько дней считаем «скоро кончится»
SOON_DAYS = 3

_PAID_LIST_COLS = ("id, tg_id, email, expire_date, total_gb, created_at, "
                   "status, times_renewed")


def _soon_key() -> str:
    from datetime import datetime, timedelta
    return (datetime.now() + timedelta(days=SOON_DAYS)).strftime("%Y%m%d %H:%M:%S")


def _scope_where(scope: str) -> tuple:
    raw = PAID_SCOPES.get(scope, PAID_SCOPES["all"])
    if "?soon" in raw:
        return raw.replace("?soon", "?"), [_soon_key()]
    return raw, []


async def list_paid_subs(page: int = 1, scope: str = "all", sort: str = "new",
                         per_page: int = SUBS_PER_PAGE) -> tuple[list, int]:
    """Страница списка: строки (id, tg_id, email, срок, ГБ, создана, статус, продлений)."""
    where, params = _scope_where(scope)
    order = PAID_SORTS.get(sort, PAID_SORTS["new"])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT COUNT(*) FROM paid_subs WHERE {where}", params) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            f"SELECT {_PAID_LIST_COLS} FROM paid_subs WHERE {where} "
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        ) as cur:
            rows = await cur.fetchall()
    return rows, max(1, (total + per_page - 1) // per_page)


async def all_paid_subs(scope: str = "all", sort: str = "new") -> list:
    """Все строки вкладки без пагинации — нужно, когда фильтр знает только панель."""
    where, params = _scope_where(scope)
    order = PAID_SORTS.get(sort, PAID_SORTS["new"])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT {_PAID_LIST_COLS} FROM paid_subs WHERE {where} ORDER BY {order}", params
        ) as cur:
            return await cur.fetchall()


async def paid_emails() -> set:
    """Имена клиентов всех подписок — для сверки с состояниями панели."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT email FROM paid_subs WHERE email IS NOT NULL") as cur:
            return {r[0] for r in await cur.fetchall()}


async def paid_counts() -> dict:
    """Сколько подписок в каждой вкладке — для цифр на кнопках."""
    async with aiosqlite.connect(DB_PATH) as db:
        out = {}
        for scope in PAID_SCOPES:
            where, params = _scope_where(scope)
            async with db.execute(f"SELECT COUNT(*) FROM paid_subs WHERE {where}", params) as cur:
                out[scope] = (await cur.fetchone())[0]
        return out


# ВНИМАНИЕ: у двух выборок подписки поля совпадают только до 11-го индекса.
# Дальше они расходятся, и ряд нельзя передавать «куда попало»:
#   get_paid_sub:          12 payment_pending … 18 period_end
#   get_paid_sub_by_tg_id: 12 times_renewed   … 18 extra_devices
# Общее у них — ind_*-поля с 13 по 17, на них и опирается sub_settings().

async def get_paid_sub(sub_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at,
                   status, payment_pending, ind_trial_period, ind_pay_period, ind_renew_time, ind_price, ind_pay_url,
                   period_end
            FROM paid_subs WHERE id = ?
        """, (sub_id,)) as cur:
            return await cur.fetchone()


async def count_paid_subs() -> int:
    """Сколько записей затронет массовый сдвиг срока — он идёт по всем."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM paid_subs") as cur:
            return (await cur.fetchone())[0]


async def get_paid_sub_by_tg_id(tg_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, limit_ip, limit_hwid, total_gb, created_at, status, times_renewed,
                   ind_trial_period, ind_pay_period, ind_renew_time, ind_price, ind_pay_url,
                   extra_devices
            FROM paid_subs WHERE tg_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (tg_id,)) as cur:
            return await cur.fetchone()


def sub_settings(row) -> dict:
    """Условия конкретной подписки.

    Пробный период фиксируется при создании, поэтому правка общих настроек
    не меняет условия уже выданных подписок. Срок и цену платного периода
    задают тарифы — в подписке они остались только у старых записей.

    Работает и с get_paid_sub, и с get_paid_sub_by_tg_id: в обеих выборках
    ind_*-поля идут с 13-го индекса.
    """
    from config import load_config
    cfg = load_config()

    def own(idx: int) -> int:
        """Значение самой подписки: общий конфиг тут не запасной вариант."""
        val = row[idx] if row is not None and len(row) > idx else None
        return int(val or 0)

    trial = row[13] if row is not None and len(row) > 13 else None
    return {
        "trial_period": int(trial or cfg.get("paid_trial_period", 86400) or 0),
        "pay_period": own(14),
        "price": own(16),
    }


def base_hwid(limit_hwid, extra_devices) -> int:
    """Лимит устройств без докупленных слотов.

    В базе limit_hwid — итог: свой лимит подписки плюс оплаченные слоты.
    Админ и пресеты оперируют именно своим лимитом, поэтому слоты при
    любой правке прибавляются сверху, а не съедаются ею.
    """
    return max(0, int(limit_hwid or 0) - int(extra_devices or 0))


def parse_sub_date(raw: str):
    from datetime import datetime
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return None


async def set_expire_date(sub_id: int, new_expire: str):
    """Ставит дату окончания. Конец периода совпадает с ней: окна оплаты нет."""
    await update_paid_sub_field(sub_id, "expire_date", new_expire)
    if parse_sub_date(new_expire):
        await update_paid_sub_field(sub_id, "period_end", new_expire)
    await update_paid_sub_field(sub_id, "remind_stage", 0)


async def snapshot_sub_settings(sub_id: int):
    """Фиксирует действующие общие настройки в подписке при её создании."""
    from config import load_config
    cfg = load_config()
    async with aiosqlite.connect(DB_PATH) as db:
        for col, key in (
            ("ind_trial_period", "paid_trial_period"),
        ):
            val = cfg.get(key)
            if val:
                await db.execute(
                    f"UPDATE paid_subs SET {col} = ? WHERE id = ?", (val, sub_id)
                )
        await db.commit()


async def delete_paid_sub(sub_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM paid_subs WHERE id = ?", (sub_id,))
        await db.commit()


async def live_paid_subs() -> list:
    """Живые подписки со всем, что нужно, чтобы написать человеку про его ключ."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, expire_date, limit_ip, limit_hwid, total_gb,
                   status, times_renewed, extra_devices, sub_url
            FROM paid_subs
            WHERE tg_id IS NOT NULL AND status IN ('active', 'renewal')
            ORDER BY id
        """) as cur:
            return await cur.fetchall()


async def update_paid_sub_field(sub_id: int, field: str, value):
    allowed = {"expire_date", "limit_ip", "limit_hwid", "total_gb", "status", "payment_pending",
                "ind_trial_period", "ind_pay_period", "ind_renew_time", "ind_price", "ind_pay_url",
                "times_renewed", "pending_promo", "uuid", "period_end", "extra_devices",
                "sub_id", "sub_url", "remind_stage"}
    if field not in allowed:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE paid_subs SET {field} = ? WHERE id = ?", (value, sub_id))
        await db.commit()


async def get_expired_paid_subs() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date, status, times_renewed, ind_renew_time, period_end
            FROM paid_subs
        """) as cur:
            return await cur.fetchall()


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


# ── История действий ─────────────────────────────────────────────────────────

HISTORY_PER_PAGE = 8


async def add_history(tg_id: int, action: str, details: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO paid_sub_history (tg_id, action, details) VALUES (?, ?, ?)",
            (tg_id, action, details),
        )
        await db.commit()
    # то же событие — в общий журнал, чтобы лента видела жизненный цикл подписки
    if tg_id:
        from database import log_activity
        first_line = details.splitlines()[0] if details else None
        await log_activity(tg_id, f"ev:{action}", first_line)


async def list_history(page: int = 1, per_page: int = HISTORY_PER_PAGE) -> tuple[list, int]:
    offset = (page - 1) * per_page
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM paid_sub_history") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT h.id, h.tg_id, h.action, h.details,
                   datetime(h.created_at, 'localtime'), u.first_name, u.username
            FROM paid_sub_history h LEFT JOIN users u ON u.id = h.tg_id
            ORDER BY h.id DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)) as cur:
            rows = await cur.fetchall()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return rows, total_pages


async def get_user_history(tg_id: int, page: int = 1, per_page: int = 8) -> tuple[list, int]:
    offset = (page - 1) * per_page
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM paid_sub_history WHERE tg_id = ?", (tg_id,)
        ) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT id, tg_id, action, details, created_at
            FROM paid_sub_history WHERE tg_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (tg_id, per_page, offset)) as cur:
            rows = await cur.fetchall()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return rows, total_pages


async def get_history_entry(entry_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, tg_id, action, details, created_at FROM paid_sub_history WHERE id = ?",
            (entry_id,),
        ) as cur:
            return await cur.fetchone()


# ── Рефералы ────────────────────────────────────────────────────────────────

async def save_referral(tg_id: int, referred_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM referrals WHERE tg_id = ?", (tg_id,)
        )
        if await cur.fetchone():
            return
        await db.execute(
            "INSERT INTO referrals (tg_id, referred_by) VALUES (?, ?)",
            (tg_id, referred_by),
        )
        await db.commit()


async def get_referrer(tg_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT referred_by FROM referrals WHERE tg_id = ?", (tg_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def mark_referral_rewarded(tg_id: int, bonus_seconds: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE referrals SET rewarded = 1, bonus_seconds = ? WHERE tg_id = ? AND rewarded = 0",
            (bonus_seconds, tg_id),
        )
        await db.commit()


async def get_referral_stats(referrer_tg_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referred_by = ?", (referrer_tg_id,)
        ) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referred_by = ? AND rewarded = 1", (referrer_tg_id,)
        ) as cur:
            rewarded = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COALESCE(SUM(bonus_seconds), 0) FROM referrals WHERE referred_by = ? AND rewarded = 1",
            (referrer_tg_id,),
        ) as cur:
            total_bonus = (await cur.fetchone())[0]
    return {"total": total, "rewarded": rewarded, "total_bonus": total_bonus}


async def get_referral_list(referrer_tg_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT r.tg_id, r.rewarded, r.bonus_seconds, r.created_at
            FROM referrals r
            WHERE r.referred_by = ?
            ORDER BY r.created_at DESC
        """, (referrer_tg_id,)) as cur:
            return await cur.fetchall()


async def get_subs_for_reminder() -> list:
    """Активные подписки с известным концом периода — кандидаты на напоминание."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, tg_id, period_end, times_renewed, remind_stage
            FROM paid_subs
            WHERE tg_id IS NOT NULL AND status = 'active' AND period_end IS NOT NULL
        """) as cur:
            return await cur.fetchall()


async def get_all_referral_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM referrals") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE rewarded = 1") as cur:
            rewarded = (await cur.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(bonus_seconds), 0) FROM referrals WHERE rewarded = 1") as cur:
            total_bonus = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT referred_by, COUNT(*) as cnt
            FROM referrals GROUP BY referred_by ORDER BY cnt DESC LIMIT 10
        """) as cur:
            top_referrers = await cur.fetchall()
    return {"total": total, "rewarded": rewarded, "total_bonus": total_bonus, "top_referrers": top_referrers}


# ── Промокоды ────────────────────────────────────────────────────────────────

# Новые поля идут в конце выборок: старый код читает промокод по индексам
_PROMO_COLS = ("id, code, percent, expires_at, active, created_at, "
               "owner_tg_id, max_uses, kind, days, note, source, first_only")


async def create_promo(code: str, percent: int, expires_at: str | None,
                       owner_tg_id: int | None = None, max_uses: int = 0,
                       kind: str = "percent", days: int = 0,
                       note: str | None = None, source: str = "manual",
                       first_only: int = 0) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO promo_codes (code, percent, expires_at, owner_tg_id, "
                "max_uses, kind, days, note, source, first_only) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code.upper(), percent, expires_at, owner_tg_id, max_uses, kind, days,
                 note, source, int(first_only or 0)),
            )
            await db.commit()
        return True
    except Exception:
        return False


async def get_promo(code: str) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT {_PROMO_COLS} FROM promo_codes WHERE code = ?", (code.upper(),)
        ) as cur:
            return await cur.fetchone()


async def get_promo_by_id(promo_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT {_PROMO_COLS} FROM promo_codes WHERE id = ?", (promo_id,)
        ) as cur:
            return await cur.fetchone()


async def list_promos(owner_tg_id: int | None = None, limit: int = 60) -> list:
    """Промокоды: id, код, %, до, активен, кому выдан, лимит, тип, дни, сколько раз применён."""
    q = ("SELECT p.id, p.code, p.percent, p.expires_at, p.active, p.owner_tg_id, "
         "p.max_uses, p.kind, p.days, "
         "(SELECT COUNT(*) FROM promo_uses u WHERE u.code = p.code) "
         "FROM promo_codes p")
    params: list = []
    if owner_tg_id is not None:
        q += " WHERE p.owner_tg_id = ?"
        params.append(owner_tg_id)
    q += " ORDER BY p.created_at DESC LIMIT ?"
    params.append(limit)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, params) as cur:
            return await cur.fetchall()


# Вкладки списка: что считаем «мёртвым» — выключенные и просроченные коды
_PROMO_DEAD = ("(p.active = 0 OR (p.expires_at IS NOT NULL "
               "AND date(substr(p.expires_at, 7, 4) || '-' || substr(p.expires_at, 4, 2) "
               "|| '-' || substr(p.expires_at, 1, 2)) < date('now', 'localtime')))")

_PROMO_TABS = {
    "all": "1 = 1",
    "common": "p.owner_tg_id IS NULL AND NOT " + _PROMO_DEAD,
    "personal": "p.owner_tg_id IS NOT NULL AND NOT " + _PROMO_DEAD,
    "dead": _PROMO_DEAD,
}


async def list_promos_page(tab: str = "all", page: int = 1, per_page: int = 10) -> tuple:
    """Страница списка промокодов: строки, всего страниц, всего кодов во вкладке."""
    where = _PROMO_TABS.get(tab, _PROMO_TABS["all"])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT COUNT(*) FROM promo_codes p WHERE {where}") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(f"""
            SELECT p.id, p.code, p.percent, p.expires_at, p.active, p.owner_tg_id,
                   p.max_uses, p.kind, p.days, p.first_only,
                   (SELECT COUNT(*) FROM promo_uses u WHERE u.code = p.code)
            FROM promo_codes p WHERE {where}
            ORDER BY p.id DESC LIMIT ? OFFSET ?
        """, (per_page, (page - 1) * per_page)) as cur:
            rows = await cur.fetchall()
    return rows, max(1, (total + per_page - 1) // per_page), total


async def promo_tab_counts() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        out = {}
        for tab, where in _PROMO_TABS.items():
            async with db.execute(f"SELECT COUNT(*) FROM promo_codes p WHERE {where}") as cur:
                out[tab] = (await cur.fetchone())[0]
        return out


async def promo_stats() -> dict:
    """Итоги раздела: сколько кодов, применений и денег они принесли."""
    async with aiosqlite.connect(DB_PATH) as db:
        async def one(q, args=()):
            async with db.execute(q, args) as cur:
                return (await cur.fetchone())[0]
        return {
            "total": await one("SELECT COUNT(*) FROM promo_codes"),
            "active": await one("SELECT COUNT(*) FROM promo_codes WHERE active = 1"),
            "personal": await one("SELECT COUNT(*) FROM promo_codes WHERE owner_tg_id IS NOT NULL"),
            "uses": await one("SELECT COUNT(*) FROM promo_uses"),
            "uses_30d": await one("SELECT COUNT(*) FROM promo_uses "
                                  "WHERE used_at >= datetime('now', '-30 days')"),
            "pays": await one("SELECT COUNT(*) FROM payments "
                              "WHERE status = 'paid' AND promo_code IS NOT NULL"),
            "revenue": await one("SELECT COALESCE(SUM(amount), 0) FROM payments "
                                 "WHERE status = 'paid' AND promo_code IS NOT NULL"),
        }


async def promo_users(code: str, limit: int = 20) -> list:
    """Кто применял код: человек, когда и сколько заплатил с этим кодом."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT u.tg_id, us.first_name, us.username,
                   datetime(u.used_at, 'localtime'),
                   (SELECT COALESCE(SUM(p.amount), 0) FROM payments p
                    WHERE p.tg_id = u.tg_id AND p.promo_code = u.code AND p.status = 'paid')
            FROM promo_uses u LEFT JOIN users us ON us.id = u.tg_id
            WHERE u.code = ? ORDER BY u.id DESC LIMIT ?
        """, (code.upper(), int(limit))) as cur:
            return await cur.fetchall()


async def promo_set(promo_id: int, field: str, value):
    if field not in ("expires_at", "max_uses", "first_only", "note"):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE promo_codes SET {field} = ? WHERE id = ?", (value, promo_id))
        await db.commit()


async def promo_dead_ids() -> list:
    """Мёртвые коды без применений — их не жалко убрать."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"""
            SELECT p.id FROM promo_codes p
            WHERE {_PROMO_DEAD}
              AND NOT EXISTS (SELECT 1 FROM promo_uses u WHERE u.code = p.code)
        """) as cur:
            return [r[0] for r in await cur.fetchall()]


async def promo_clean_dead() -> int:
    ids = await promo_dead_ids()
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"DELETE FROM promo_codes WHERE id IN ({marks})", ids)
        await db.commit()
    return len(ids)


async def find_promos(needle: str, limit: int = 20) -> list:
    like = f"%{(needle or '').strip().upper()}%"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT p.id, p.code, p.percent, p.expires_at, p.active, p.owner_tg_id,
                   p.max_uses, p.kind, p.days, p.first_only,
                   (SELECT COUNT(*) FROM promo_uses u WHERE u.code = p.code)
            FROM promo_codes p WHERE p.code LIKE ? ORDER BY p.id DESC LIMIT ?
        """, (like, int(limit))) as cur:
            return await cur.fetchall()


async def promo_income(code: str) -> tuple:
    """Сколько оплат прошло с этим кодом и на какую сумму (возвраты не в счёт)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments "
            "WHERE promo_code = ? AND status = 'paid'", (code.upper(),)
        ) as cur:
            return await cur.fetchone()


async def promo_income_all() -> list:
    """По каждому коду: применений и заработанная сумма — сверху самые денежные."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT p.code, p.kind, p.percent, p.days,
                   (SELECT COUNT(*) FROM promo_uses u WHERE u.code = p.code),
                   (SELECT COUNT(*) FROM payments pay WHERE pay.promo_code = p.code AND pay.status = 'paid'),
                   (SELECT COALESCE(SUM(amount), 0) FROM payments pay
                    WHERE pay.promo_code = p.code AND pay.status = 'paid')
            FROM promo_codes p
            ORDER BY 7 DESC, 5 DESC LIMIT 30
        """) as cur:
            return await cur.fetchall()


async def unique_promo_code(prefix: str) -> str:
    """Короткий код без похожих друг на друга букв и цифр."""
    import random
    alphabet = "ACDEFGHJKLMNPQRTUVWXY34679"
    for _ in range(50):
        code = f"{prefix}{''.join(random.choices(alphabet, k=5))}"
        if not await get_promo(code):
            return code
    return f"{prefix}{random.randint(100000, 999999)}"


async def toggle_promo(promo_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE promo_codes SET active = 1 - active WHERE id = ?", (promo_id,)
        )
        await db.commit()


async def delete_promo(promo_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM promo_codes WHERE id = ?", (promo_id,))
        await db.commit()


async def promo_used_by(code: str, tg_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM promo_uses WHERE code = ? AND tg_id = ?",
            (code.upper(), tg_id),
        ) as cur:
            return (await cur.fetchone()) is not None


async def record_promo_use(code: str, tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO promo_uses (code, tg_id) VALUES (?, ?)",
            (code.upper(), tg_id),
        )
        await db.commit()


async def promo_use_count(code: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM promo_uses WHERE code = ?", (code.upper(),)
        ) as cur:
            return (await cur.fetchone())[0]


async def get_pending_promo(tg_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT pending_promo FROM paid_subs WHERE tg_id = ? ORDER BY created_at DESC LIMIT 1",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row and row[0] else None
