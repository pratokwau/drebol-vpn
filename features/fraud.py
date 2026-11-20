"""Ловля повторных триалов.

Человек берёт пробный период, потом заводит новый аккаунт и берёт ещё один —
с тем же телефоном и той же квартирой. Панель про это знает: у подписки видны
устройства (HWID) и адреса, с которых она подключалась. Бот их постепенно
запоминает и сверяет аккаунты друг с другом по всем параметрам, какие у него
есть: устройства (сильные HWID и слабый композит модели), адреса, ники и
имена, почта кабинета (с вариантами написания), реферальные связи, личные
промокоды и даты регистраций.

Каждое совпадение — улика с весом. Вердикт строится по сумме улик: одно
устройство — уже почти наверняка один человек; один адрес — почти ни о чём
не говорит; а вот адрес + та же модель телефона + регистрация в один час +
реферальная связь между аккаунтами — это уже реальный абуз, а не совпадение.
Находку бот приносит админу — решение всегда за человеком, сам бот никого
не банит.
"""

from config import ADMIN_ID, load_config, save_config


# Ключи, под которыми панель отдаёт настоящий идентификатор устройства.
# Их написание меняется от версии к версии, поэтому перебираем.
_STRONG_KEYS = ("hwid", "hwId", "deviceId", "device_id", "fingerprint", "uuid")
# Слабый запасной вариант: «iOS · iPhone» совпадает у тысяч людей,
# поэтому такие отпечатки просто запоминаем, но никогда не считаем уликой.
_WEAK_KEYS = ("deviceOs", "deviceModel", "appVersion")


def is_public_ip(value: str) -> bool:
    """Адрес, по которому вообще можно кого-то узнать.

    За обратным прокси или CDN панель пишет внутренний адрес — он одинаковый
    у всех клиентов, и уликой быть не может.
    """
    import ipaddress
    try:
        ip = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast)


def device_key(item: dict):
    """Отпечаток устройства и признак того, что он надёжный."""
    for k in _STRONG_KEYS:
        val = item.get(k)
        if val:
            return str(val), True
    parts = [str(item.get(k)) for k in _WEAK_KEYS if item.get(k)]
    return ("|".join(parts), False) if parts else (None, False)


# ── Полная сверка пары: каждый параметр — улика с весом ──────────────────────

WEIGHTS = {
    "hwid": 50,           # один и тот же телефон/компьютер — почти приговор
    "promo_personal": 35,  # чужой личный промокод не вводят случайно
    "email_variant": 30,  # та же почта кабинета, записанная с точками/плюсом
    "ip": 20,             # общий публичный адрес (но бывает и общий Wi-Fi)
    "referral_direct": 15,  # один пригласил другого — аккаунты знакомы лично
    "username": 15,       # тот же ник или ник, отличающийся цифрами/точками
    "referral_common": 10,  # оба пришли от одного пригласившего
    "hwid_weak": 10,      # та же связка ОС + модель + версия приложения
    "name": 5,            # то же имя — слабенько, но в сумме помогает
    "promo_shared": 5,    # оба ввели один общий код почти одновременно
    "timing": 5,          # регистрации в один час
}

_KIND_LABEL = {
    "hwid": "📱 Одно устройство",
    "ip": "🌐 Один IP-адрес",
    "hwid_weak": "📲 Та же модель и ОС",
    "username": "🪪 Совпадение ника",
    "name": "🪪 Одно имя",
    "email_variant": "✉️ Та же почта кабинета",
    "referral_direct": "🔗 Реферальная связь между аккаунтами",
    "referral_common": "🔗 Общий пригласивший",
    "promo_personal": "🎟 Чужой личный промокод",
    "promo_shared": "🎟 Один промокод в одно время",
    "timing": "🕐 Регистрации почти одновременно",
}


def verdict(score: int) -> str:
    """Человеческий вердикт по сумме улик."""
    if score >= 50:
        return "🔴 Похоже на реальный абуз"
    if score >= 30:
        return "🟠 Вероятно, один человек"
    if score >= 15:
        return "🟡 Подозрительно"
    return "⚪ Слабое совпадение"


def _norm_name(s: str) -> str:
    import re
    return re.sub(r"[^a-zа-яё0-9]", "", (s or "").lower())


def _norm_username(s: str) -> str:
    import re
    return re.sub(r"[0-9._]+$", "", (s or "").lower().lstrip("@"))


def _norm_email(s: str) -> str:
    """Почта без точечных и плюсовых вариантов: ivan.petrov+x@gmail = ivanpetrov@gmail."""
    s = (s or "").strip().lower()
    if "@" not in s:
        return ""
    local, domain = s.split("@", 1)
    local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}" if local and domain else ""


def _close_in_time(a, b, seconds: int = 3600) -> bool:
    """Две даты из базы (строки) — рядом по времени или нет."""
    from datetime import datetime
    if not a or not b:
        return False
    try:
        da = datetime.fromisoformat(str(a))
        db = datetime.fromisoformat(str(b))
    except ValueError:
        return False
    return abs((da - db).total_seconds()) <= seconds


async def evaluate_pair(tg_a: int, tg_b: int) -> dict:
    """Сверяет два аккаунта по всем параметрам. Возвращает улики и сумму.

    Улика — (kind, value, weight). Это полная проверка пары «здесь и сейчас»
    по всем данным базы: отпечатки, ники, почта, рефералы, промо, даты.
    """
    from core.database import shared_fingerprints, fraud_account_facts
    ev: list = []
    seen_kinds: set = set()

    def add(kind, value):
        if kind in seen_kinds and kind not in ("ip",):
            return
        seen_kinds.add(kind)
        ev.append((kind, str(value)[:120], WEIGHTS[kind]))

    shared = await shared_fingerprints(tg_a, tg_b)
    ip_count = 0
    for kind, value in shared:
        if kind == "hwid":
            add("hwid", value)
        elif kind == "ip":
            if is_public_ip(value):
                ip_count += 1
                if ip_count <= 2:  # два общих адреса — потолок веса IP
                    ev.append(("ip", value, WEIGHTS["ip"]))
        elif kind == "hwid_weak":
            add("hwid_weak", value)

    fa = await fraud_account_facts(tg_a)
    fb = await fraud_account_facts(tg_b)

    ua, ub = (fa["username"] or "").lower(), (fb["username"] or "").lower()
    if ua and ub:
        if ua == ub or _norm_username(ua) == _norm_username(ub):
            add("username", fa["username"])
    na, nb = _norm_name(fa["first_name"]), _norm_name(fb["first_name"])
    if na and na == nb and len(na) >= 3:
        add("name", fa["first_name"])

    ea, eb = _norm_email(fa["login_email"]), _norm_email(fb["login_email"])
    if ea and ea == eb:
        add("email_variant", fa["login_email"])

    if fa["referred_by"] == tg_b or fb["referred_by"] == tg_a:
        add("referral_direct", "один пригласил другого")
    elif fa["referred_by"] and fa["referred_by"] == fb["referred_by"]:
        add("referral_common", f"пригласил {fa['referred_by']}")

    owners_a = {code: owner for code, owner, _u in fa["promo_uses"]}
    owners_b = {code: owner for code, owner, _u in fb["promo_uses"]}
    for code, owner in owners_a.items():
        if owner == tg_b:
            add("promo_personal", code)
    for code, owner in owners_b.items():
        if owner == tg_a:
            add("promo_personal", code)
    shared_codes = set(owners_a) & set(owners_b)
    if shared_codes and "promo_personal" not in seen_kinds:
        uses_a = {c: u for c, _o, u in fa["promo_uses"]}
        uses_b = {c: u for c, _o, u in fb["promo_uses"]}
        for code in shared_codes:
            if _close_in_time(uses_a.get(code), uses_b.get(code), 48 * 3600):
                add("promo_shared", code)
                break

    if _close_in_time(fa["user_created"], fb["user_created"]):
        add("timing", "аккаунты в один час")
    elif _close_in_time(fa["sub_created"], fb["sub_created"]):
        add("timing", "подписки в один час")

    return {"score": sum(w for _k, _v, w in ev), "evidence": ev}


async def apply_evaluation(context, tg_a: int, tg_b: int) -> int:
    """Оценивает пару, записывает улики и балл, присылает алерт, если пара
    новая и убедительная — или если улики дотянули её до «абуза»."""
    from core.database import (note_fraud_pair, record_fraud_evidence,
                               get_fraud_pair, set_fraud_pair_score)
    res = await evaluate_pair(tg_a, tg_b)
    score, ev = res["score"], res["evidence"]
    if not ev:
        return 0
    for kind, value, weight in ev:
        await record_fraud_evidence(tg_a, tg_b, kind, value, weight)

    strongest = max(ev, key=lambda e: e[2])
    pair = await get_fraud_pair(tg_a, tg_b)
    was_new = pair is None
    prev_score = (pair[6] if pair and len(pair) > 6 else 0) or 0
    if was_new:
        if score < 15 and strongest[0] != "hwid":
            return score  # слишком слабо — пару даже не заводим
        await note_fraud_pair(tg_a, tg_b, strongest[0], strongest[1])
    await set_fraud_pair_score(tg_a, tg_b, score)

    pair = await get_fraud_pair(tg_a, tg_b)
    status = pair[4] if pair else "new"
    if status != "new":
        return score
    if was_new and score >= 15:
        await send_fraud_alert(context, tg_a, tg_b, score, ev)
    elif not was_new and prev_score < 50 <= score:
        await send_fraud_alert(context, tg_a, tg_b, score, ev, boosted=True)
    return score


async def send_fraud_alert(context, tg_a: int, tg_b: int, score: int,
                           ev: list, boosted: bool = False):
    """Алерт админу: пара, вердикт и главные улики."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    top = sorted(ev, key=lambda e: -e[2])[:4]
    lines = "\n".join(f"· {_KIND_LABEL.get(k, k)} (+{w})" for k, _v, w in top)
    head = ("🕵 <b>Улики усилились до абуза</b>" if boosted
            else "🕵 <b>Похожие аккаунты</b>")
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(f"{head}\n\n"
              f"{await who_line(tg_a)}\n\n"
              f"{await who_line(tg_b)}\n\n"
              f"<blockquote>{verdict(score)} · <b>{score}</b> баллов\n{lines}</blockquote>"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Разобрать",
                                  callback_data=f"fraud_pair:{tg_a}:{tg_b}")],
            [InlineKeyboardButton("⛔ В ЧС первого", callback_data=f"bl_add_for:{tg_a}"),
             InlineKeyboardButton("🙈 Не фрод", callback_data=f"fraud_ok:{tg_a}:{tg_b}")],
        ]),
    )
    from core.log_channel import send_log
    await send_log(context.bot,
                   f"🕵 Антифрод: <code>{tg_a}</code> ↔ <code>{tg_b}</code> — "
                   f"{score} баллов ({verdict(score)})")


async def pre_trial_check(tg_id: int) -> list:
    """Быстрые предупреждения перед выдачей триала новому аккаунту.

    Отпечатков у новичка ещё нет, поэтому сверяем то, что уже известно:
    ник и имя против уже пойманных на абузе, варианты почты кабинета и
    пригласившего. Возвращает список строк-предупреждений (пустой — чисто).
    """
    from core.database import fraud_account_facts
    import aiosqlite
    from core.database import DB_PATH
    facts = await fraud_account_facts(tg_id)
    out = []
    blocked: set = set()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tg_a, tg_b FROM fraud_pairs WHERE status = 'blocked'"
        ) as cur:
            for a, b in await cur.fetchall():
                blocked.add(a)
                blocked.add(b)
        if facts["referred_by"] and facts["referred_by"] in blocked:
            out.append("пригласивший уже блокировался за повторные триалы")
        email = _norm_email(facts["login_email"])
        if email:
            async with db.execute(
                "SELECT id, login_email FROM users WHERE login_email IS NOT NULL "
                "AND id != ?", (tg_id,),
            ) as cur:
                for other_id, other_email in await cur.fetchall():
                    if _norm_email(other_email) == email:
                        out.append(f"почта кабинета совпадает с аккаунтом {other_id} "
                                   "(вариант написания)")
                        break
        uname = _norm_username(facts["username"])
        if uname:
            async with db.execute(
                "SELECT id, username FROM users WHERE id != ?", (tg_id,),
            ) as cur:
                for other_id, other_name in await cur.fetchall():
                    if other_id in blocked and _norm_username(other_name or "") == uname:
                        out.append(f"ник совпадает с заблокированным за абуз {other_id}")
                        break
    return out


async def _subs_slice(limit: int) -> list:
    """Очередная порция подписок для опроса панели.

    Ходим по кругу: за раз трогаем несколько подписок, чтобы не устраивать
    панели шквал запросов, но со временем обойти всех.
    """
    import aiosqlite
    from core.database import DB_PATH
    cfg = load_config()
    cursor = int(cfg.get("fraud_cursor", 0) or 0)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, tg_id, email, times_renewed FROM paid_subs "
            "WHERE tg_id IS NOT NULL "
            "UNION ALL "
            "SELECT id, tg_id, email, 1 FROM admin_subs WHERE tg_id IS NOT NULL "
            "ORDER BY 3"
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        return []
    start = cursor % len(rows)
    batch = rows[start:start + limit]
    if len(batch) < limit:
        batch += rows[:limit - len(batch)]
    cfg["fraud_cursor"] = (start + len(batch)) % len(rows)
    save_config(cfg)
    return batch


async def fraud_tick(context):
    """Обходит подписки по кругу и запоминает их устройства и адреса."""
    cfg = load_config()
    if not cfg.get("fraud_enabled", True):
        return
    from services.panel import is_configured
    if not is_configured():
        return
    batch = await _subs_slice(int(cfg.get("fraud_batch", 8) or 8))
    for _sub_id, tg_id, email, times_renewed in batch:
        await scan_sub(context, tg_id, email, bool(times_renewed))


async def scan_sub(context, tg_id: int, email: str, paid: bool) -> list:
    """Запоминает отпечатки одной подписки и полностью сверяет совпавшие пары.

    Раньше пара рождалась из одного совпадения. Теперь каждое свежее
    совпадение запускает полную сверку пары по всем параметрам
    (evaluate_pair), а вердикт и алерт зависят от суммы улик.
    """
    from core.database import (remember_fingerprints, fingerprint_owners,
                               fingerprint_cluster)
    from services.panel import get_client_hwids, get_client_ips

    found = []
    hw = await get_client_hwids(email)
    if hw.get("ok"):
        strong, weak = [], []
        for item in hw["items"]:
            value, is_strong = device_key(item)
            if not value:
                continue
            (strong if is_strong else weak).append(value)
        fresh_weak = await remember_fingerprints(email, tg_id, "hwid_weak", weak)
        fresh = await remember_fingerprints(email, tg_id, "hwid", strong)
        found += [("hwid", v) for v in fresh]
        # слабый композит (модель+ОС) сам по себе — не улика, но как повод
        # для полной сверки годится, если такой телефон не у половины города
        for v in fresh_weak:
            cluster = await fingerprint_cluster("hwid_weak", v)
            if len(cluster) <= 6:
                found.append(("hwid_weak", v))

    cfg = load_config()
    if cfg.get("fraud_use_ip", True):
        ips = await get_client_ips(email)
        if ips.get("ok"):
            values = [i["ip"] for i in ips["items"]
                      if i.get("ip") and is_public_ip(i["ip"])]
            fresh = await remember_fingerprints(email, tg_id, "ip", values)
            found += [("ip", v) for v in fresh]

    alerts = []
    checked_pairs = set()
    for kind, value in found:
        for other_tg, _other_email in await fingerprint_owners(kind, value, tg_id):
            pair_key = (min(tg_id, other_tg), max(tg_id, other_tg))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)
            score = await apply_evaluation(context, tg_id, other_tg)
            if score >= 15:
                alerts.append((other_tg, kind))
    return alerts


# ── Кто эти двое ──────────────────────────────────────────────────────────────

async def who_line(tg_id: int) -> str:
    """Короткая справка о человеке: кто, когда пришёл, что с подпиской."""
    from core.database import get_user_info, user_fingerprint_stats
    from paidsub.storage import get_paid_sub_by_tg_id
    from paidsub.handlers import _esc_name

    u = await get_user_info(tg_id)
    from core.database import format_client
    who = format_client(u[1] if u else None, u[2] if u else None, tg_id)
    since = f" · с {str(u[3])[:10]}" if u and len(u) > 3 and u[3] else ""

    row = await get_paid_sub_by_tg_id(tg_id)
    if row:
        status = row[11] if len(row) > 11 else "active"
        renewed = row[12] if len(row) > 12 else 0
        kind = "платная" if renewed else "пробная"
        labels = {"active": "активна", "expired": "истекла"}
        sub = f"{kind}, {labels.get(status, status)}, до {str(row[6])[:16]}"
    else:
        sub = "подписки нет"

    marks = await user_fingerprint_stats(tg_id)
    seen = " · ".join(x for x in (
        f"устройств: {marks.get('hwid', 0)}" if marks.get("hwid") else "",
        f"адресов: {marks.get('ip', 0)}" if marks.get("ip") else "") if x)
    return (f"👤 {who}{since}\n"
            f"💳 {sub}" + (f"\n🔎 {seen}" if seen else ""))


def _match_line(kind: str, value: str) -> str:
    label = _KIND_LABEL.get(kind, f"🔎 {kind}")
    return f"{label} · <code>{value[:40]}</code>"


# ── Экран в админке ───────────────────────────────────────────────────────────

async def handle_fraud_menu(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.database import fraud_stats
    cfg = load_config()
    enabled = cfg.get("fraud_enabled", True)
    use_ip = cfg.get("fraud_use_ip", True)
    st = await fraud_stats()
    status = "🟢 включена" if enabled else "🔴 выключена"

    lines = ["🕵 <b>Повторные триалы</b>", "",
             "<blockquote>"
             f"Слежка: <b>{status}</b>\n"
             f"📱 Устройств запомнено: <b>{st['devices']}</b>\n"
             f"🌐 Адресов запомнено: <b>{st['ips']}</b></blockquote>", "",
             "<blockquote>"
             f"🔎 Находок всего: <b>{st['pairs']}</b>\n"
             f"🆕 Не разобрано: <b>{st['new']}</b>\n"
             f"🔴 Из них похожи на абуз (50+ баллов): <b>{st.get('abuse', 0)}</b>\n"
             f"⛔ Закончились блокировкой: <b>{st['blocked']}</b>\n"
             f"🙈 Отмечено «не фрод»: <b>{st['ignored']}</b>"
             + (f"\n👨‍👩‍👧 Устройств на трёх и более аккаунтах: <b>{st['clusters']}</b>"
                if st["clusters"] else "")
             + "</blockquote>", "",
             "<i>Бот по кругу опрашивает панель и сверяет аккаунты по всем "
             "параметрам: устройства, адреса, ники, почта кабинета, реферальные "
             "связи, промокоды и даты. Каждое совпадение — улика с весом, "
             "вердикт — по сумме. Сам никого не банит: решение за тобой.</i>"]

    kb = [[InlineKeyboardButton("🔴 Выключить" if enabled else "🟢 Включить",
                                callback_data="fraud_toggle"),
           InlineKeyboardButton("🔍 Проверить сейчас", callback_data="fraud_scan")]]
    if st["pairs"]:
        kb.append([InlineKeyboardButton(
            f"📋 Находки{' · 🆕 ' + str(st['new']) if st['new'] else ''}",
            callback_data="fraud_list:new" if st["new"] else "fraud_list:all")])
    kb.append([InlineKeyboardButton(
        f"🌐 Адрес как улика: {'да' if use_ip else 'нет'}", callback_data="fraud_ip_toggle")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_fraud_ip_toggle(query):
    """Адрес — слабая улика: у мобильных операторов и общего Wi-Fi он совпадает
    у чужих людей. Этой кнопкой его можно вовсе перестать учитывать."""
    cfg = load_config()
    cfg["fraud_use_ip"] = not cfg.get("fraud_use_ip", True)
    save_config(cfg)
    await handle_fraud_menu(query)


_KIND_ICON = {"hwid": "📱", "ip": "🌐"}
_STATUS_LABEL = {"new": "🆕", "ignored": "🙈", "blocked": "⛔"}


async def handle_fraud_list(query, which: str = "new"):
    """Список находок с фильтром."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.database import list_fraud_pairs, get_user_info
    from paidsub.handlers import _esc_name

    status = None if which == "all" else which
    rows = await list_fraud_pairs(status, limit=12)
    titles = {"new": "не разобранные", "ignored": "«не фрод»",
              "blocked": "с блокировкой", "all": "все"}
    lines = [f"📋 <b>Находки — {titles.get(which, which)}</b>", ""]
    kb = []
    if not rows:
        lines.append("<blockquote>Пусто.</blockquote>")
    for tg_a, tg_b, kind, _value, st, created, score in rows:
        a = await get_user_info(tg_a)
        b = await get_user_info(tg_b)
        a_name = _esc_name(a[1] if a else None, tg_a)
        b_name = _esc_name(b[1] if b else None, tg_b)
        when = str(created)[5:16] if created else ""
        lines.append(f"{_STATUS_LABEL.get(st, '·')} {_KIND_ICON.get(kind, '🔎')} "
                     f"{a_name} ↔ {b_name} · <b>{score or 0}</b> баллов · {when}")
        kb.append([InlineKeyboardButton(
            f"{score or 0}б · {a_name[:14]} ↔ {b_name[:14]}",
            callback_data=f"fraud_pair:{tg_a}:{tg_b}")])

    tabs = [("🆕 Новые", "new"), ("⛔ Блок", "blocked"),
            ("🙈 Не фрод", "ignored"), ("📚 Все", "all")]
    kb.append([InlineKeyboardButton(("• " if key == which else "") + label,
                                    callback_data=f"fraud_list:{key}")
               for label, key in tabs])
    kb.append([InlineKeyboardButton("◀️ К повторным триалам", callback_data="fraud_menu")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_fraud_pair(query, a: int, b: int):
    """Карточка находки: кто эти двое, что совпало и что можно сделать."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.database import get_fraud_pair, fingerprint_cluster, get_user_info
    from paidsub.handlers import _esc_name
    from paidsub.storage import get_paid_sub_by_tg_id

    pair = await get_fraud_pair(a, b)
    if not pair:
        await query.answer("Находка не найдена", show_alert=True)
        await handle_fraud_list(query, "all")
        return
    tg_a, tg_b, kind, value, status, created = pair[:6]
    score = pair[6] if len(pair) > 6 else 0

    cluster = await fingerprint_cluster(kind, value)
    others = [c for c in cluster if c[0] not in (tg_a, tg_b)]
    first_seen = min((c[2] for c in cluster if c[2]), default=None)
    last_seen = max((c[3] for c in cluster if c[3]), default=None)

    from core.database import get_fraud_evidence
    evidence = await get_fraud_evidence(tg_a, tg_b)
    facts = [f"{verdict(score or 0)} · <b>{score or 0}</b> баллов"]
    if evidence:
        facts.append("<b>Улики:</b>")
        for ek, ev_value, ew, _ec in evidence:
            facts.append(f"· {_match_line(ek, ev_value)} (+{ew})")
    else:
        facts.append(_match_line(kind, value))
    if first_seen:
        facts.append(f"📆 Впервые: {str(first_seen)[:16]} · последний раз: "
                     f"{str(last_seen)[:16]}")
    if others:
        names = []
        for tg_id, _email, _f, _l in others[:4]:
            u = await get_user_info(tg_id)
            names.append(_esc_name(u[1] if u else None, tg_id))
        facts.append(f"👥 Тот же отпечаток ещё у <b>{len(others)}</b>: " + ", ".join(names))
    if any(ek == "ip" for ek, *_ in evidence) and not any(
            ek == "hwid" for ek, *_ in evidence):
        facts.append("<i>Сильной улики (устройства) нет: адрес и прочее по "
                     "отдельности слабы, смотри на сумму.</i>")

    state_line = {"new": "🆕 не разобрано", "ignored": "🙈 отмечено «не фрод»",
                  "blocked": "⛔ закончилось блокировкой"}.get(status, status)

    text = ("🕵 <b>Находка</b>\n"
            f"<i>{state_line} · {str(created)[:16]}</i>\n\n"
            f"{await who_line(tg_a)}\n\n"
            f"{await who_line(tg_b)}\n\n"
            "<blockquote>" + "\n".join(facts) + "</blockquote>")

    kb = [[InlineKeyboardButton("👤 Первый", callback_data=f"user_profile:{tg_a}"),
           InlineKeyboardButton("👤 Второй", callback_data=f"user_profile:{tg_b}")],
          [InlineKeyboardButton("🔄 Перепроверить пару",
                                callback_data=f"fraud_recheck:{tg_a}:{tg_b}")],
          [InlineKeyboardButton("⛔ В ЧС первого", callback_data=f"bl_add_for:{tg_a}"),
           InlineKeyboardButton("⛔ В ЧС второго", callback_data=f"bl_add_for:{tg_b}")]]

    # закрыть триал предлагаем только тому, кто ещё ни разу не платил
    for tg_id, label in ((tg_a, "первому"), (tg_b, "второму")):
        row = await get_paid_sub_by_tg_id(tg_id)
        renewed = (row[12] if row and len(row) > 12 else 0)
        status_now = (row[11] if row and len(row) > 11 else "")
        if row and not renewed and status_now != "expired":
            kb.append([InlineKeyboardButton(
                f"🚫 Закрыть триал {label}", callback_data=f"fraud_stop:{tg_id}:{tg_a}:{tg_b}")])

    if status != "ignored":
        kb.append([InlineKeyboardButton("🙈 Не фрод — больше не спрашивать",
                                        callback_data=f"fraud_ok:{tg_a}:{tg_b}")])
    kb.append([InlineKeyboardButton("◀️ К находкам", callback_data="fraud_list:new")])
    await query.edit_message_text(text, parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_fraud_stop(query, context, tg_id: int, a: int, b: int):
    """Закрывает пробную подписку: срок в прошлое, доступ выключен."""
    from datetime import datetime
    from paidsub.storage import (get_paid_sub_by_tg_id, set_expire_date,
                                 update_paid_sub_field, add_history)
    from services.panel import update_client_expire, toggle_client
    from core.database import set_fraud_pair_status
    from core.log_channel import send_log

    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        await query.answer("Подписки нет", show_alert=True)
        return
    sub_id, email = row[0], row[2]
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    await set_expire_date(sub_id, now)
    await update_paid_sub_field(sub_id, "status", "expired")
    pushed = await update_client_expire(email, now)
    off = await toggle_client(email, False)
    await add_history(tg_id, "trial_stopped", "Триал закрыт: повторная регистрация")
    await set_fraud_pair_status(a, b, "blocked")

    trouble = ""
    if not pushed.get("success"):
        trouble += f" · срок: {pushed.get('error')}"
    if not off.get("success"):
        trouble += f" · отключение: {off.get('error')}"
    await send_log(context.bot,
                   f"🚫 Триал закрыт у <code>{tg_id}</code> (повторная регистрация){trouble}")
    await query.answer("Триал закрыт" + (" · панель ответила с ошибкой" if trouble else ""),
                       show_alert=bool(trouble))
    await handle_fraud_pair(query, a, b)


async def handle_fraud_toggle(query):
    cfg = load_config()
    cfg["fraud_enabled"] = not cfg.get("fraud_enabled", True)
    save_config(cfg)
    await handle_fraud_menu(query)


async def handle_fraud_scan(query, context):
    """Ручной прогон: полезно сразу после включения."""
    await query.edit_message_text("🔍 Опрашиваю панель…")
    cfg = load_config()
    batch = await _subs_slice(int(cfg.get("fraud_batch", 8) or 8))
    alerts = 0
    for _sub_id, tg_id, email, times_renewed in batch:
        alerts += len(await scan_sub(context, tg_id, email, bool(times_renewed)))
    await query.answer(
        f"Проверено подписок: {len(batch)} · находок: {alerts}", show_alert=True)
    await handle_fraud_menu(query)


async def handle_fraud_ok(query, a: int, b: int):
    from core.database import ignore_fraud_pair, get_fraud_pair
    await ignore_fraud_pair(a, b)
    await query.answer("Больше про эту пару не напомню")
    if await get_fraud_pair(a, b):
        await handle_fraud_pair(query, a, b)
    else:
        await handle_fraud_menu(query)


async def handle_fraud_recheck(query, context, a: int, b: int):
    """Полная пересверка пары по всем параметрам прямо из карточки."""
    score = await apply_evaluation(context, a, b)
    await query.answer(f"Перепроверил: {score} баллов — {verdict(score)}",
                       show_alert=True)
    await handle_fraud_pair(query, a, b)
