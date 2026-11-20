"""Чистые действия над подписками: база бота + панель Remnawave.

Каждый helper здесь — это последовательность «база + панель» одного действия
админа или оплаты, без объектов Telegram: хендлеры спрашивают и показывают
текст, а работу делают эти функции. Здесь нет ни отправки, ни правки
сообщений в чате админа — только вызовы базы, панели и, где положено,
уведомления пользователю через переданный bot.

Соглашения:
- kind="paid" — таблица paid_subs, kind="admin" — admin_subs. Где действия
  различаются (история пишется только для платных, админские правки молчат),
  это ветвление живёт здесь, а не в хендлерах.
- bot — объект с async send_message(chat_id, text, parse_mode): бот целиком
  или заглушка из тестов. None — не уведомлять никого (и не писать в лог-канал).
- panel — модуль services.panel или его заглушка. None — берётся настоящий
  services.panel при каждом вызове (по атрибутам модуля, чтобы подмена
  services.panel.create_client и т.п. в тестах работала).
- Возврат — всегда plain dict: {"ok": bool, ...} или {"ok": False,
  "error": str}. Панель и база обновляются вместе: сначала база, потом
  панель; если панель не приняла, это видно в panel_ok/panel_error,
  а база уже изменена — так было и в хендлерах до выноса.
"""

from datetime import datetime, timedelta

from config import ADMIN_ID, load_config


# ── Внутреннее ────────────────────────────────────────────────────────────────

def _panel(panel=None):
    if panel is not None:
        return panel
    import services.panel as panel_mod
    return panel_mod


async def _notify(bot, tg_id, text: str):
    if not bot or not tg_id:
        return
    try:
        await bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML")
    except Exception:
        pass


async def _send_log(bot, text: str):
    if not bot:
        return
    try:
        from core.log_channel import send_log
        await send_log(bot, text)
    except Exception:
        pass


def _esc(value, fallback="") -> str:
    from html import escape
    return escape(str(value if value not in (None, "") else fallback))


def _parse_expire(raw):
    from paidsub.storage import parse_sub_date
    return parse_sub_date(raw)


def _fmt_seconds(seconds: int) -> str:
    from paidsub.time_parser import fmt_duration
    return fmt_duration(int(seconds or 0))


async def _load(kind: str, sub_id: int):
    """Строка подписки. Возвращает (row, by_tg_row|None)."""
    if kind == "admin":
        from adminsub.storage import get_sub
        return await get_sub(sub_id), None
    from paidsub.storage import get_paid_sub, get_paid_sub_by_tg_id
    row = await get_paid_sub(sub_id)
    by_tg = await get_paid_sub_by_tg_id(row[1]) if row and row[1] else None
    return row, by_tg


def _norm(kind: str, row, by_tg=None) -> dict:
    """Нормализованный вид строки подписки (индексы у таблиц разные)."""
    d = {
        "id": row[0], "tg_id": row[1], "email": row[2], "uuid": row[3],
        "sub_id": row[4], "sub_url": row[5], "expire_date": row[6],
        "limit_ip": row[7], "limit_hwid": row[8], "total_gb": row[9],
        "created_at": row[10],
        "status": row[11] if kind == "paid" else None,
        "times_renewed": 0, "extra_devices": 0, "lte_gb": None,
        "period_end": None, "ind_trial_period": None,
    }
    if kind == "paid":
        d["status"] = row[11] if len(row) > 11 else "active"
        d["period_end"] = row[18] if len(row) > 18 else None
        d["lte_gb"] = row[19] if len(row) > 19 else None
        d["ind_trial_period"] = row[13] if len(row) > 13 else None
        if by_tg is not None:
            d["times_renewed"] = by_tg[12] if len(by_tg) > 12 else 0
            d["extra_devices"] = int(by_tg[18] or 0) if len(by_tg) > 18 else 0
            d["lte_gb"] = by_tg[19] if len(by_tg) > 19 else d["lte_gb"]
    else:
        d["lte_gb"] = row[11] if len(row) > 11 else None
    return d


async def _write(kind: str, sub_id: int, field: str, value):
    if kind == "admin":
        from adminsub.storage import update_sub_field
        await update_sub_field(sub_id, field, value)
    else:
        from paidsub.storage import update_paid_sub_field
        await update_paid_sub_field(sub_id, field, value)


async def _set_expire_db(kind: str, sub_id: int, new_expire: str):
    """Дата окончания в базе. У платных заодно period_end и сброс напоминаний."""
    if kind == "admin":
        await _write(kind, sub_id, "expire_date", new_expire)
    else:
        from paidsub.storage import set_expire_date
        await set_expire_date(sub_id, new_expire)


async def _history(kind: str, tg_id, action: str, details: str | None = None):
    """История пишется обоим видам подписок: она одна на человека (по tg_id),
    а у админских событий в деталях помечаем, что речь об админской подписке."""
    if not tg_id:
        return
    from paidsub.storage import add_history
    if kind == "admin":
        details = ("[админская] " + details) if details else "[админская подписка]"
    await add_history(tg_id, action, details)


async def _retag(tg_id):
    """Тег человека в панели по новому статусу подписки (services/panel_tags).

    Best-effort: статус в базе уже сменился, а панель может лежать —
    тег тогда подтянет ручное «Применить ко всем» в админке.
    """
    if not tg_id:
        return
    try:
        from services.panel_tags import refresh_user_tag
        await refresh_user_tag(tg_id)
    except Exception:
        pass


async def _re_enable_if_needed(panel_mod, email: str):
    """Вернуть доступ, если клиент был выключен в панели."""
    info = await panel_mod.get_client_info(email)
    if info.get("success") and not info.get("enabled", True):
        await panel_mod.toggle_client(email, True)


# ── Карточка подписки ─────────────────────────────────────────────────────────

async def get_sub_card(sub_id: int, *, kind: str = "paid", panel=None) -> dict:
    """Данные для экрана подписки: строка базы + состояние в панели.

    Возвращает {"ok": True, "kind", "sub": {...}, "row": tuple,
    "panel": {"enabled": bool|None, "traffic_ok": bool, "up": int, "down": int},
    "times_renewed": int, "user": {"first_name","username"}|None,
    "referrer": {"tg_id","first_name"}|None} или {"ok": False, "error": ...}.
    LTE-потребление сюда не входит: его считает _lte_view_line в хендлере.
    """
    row, by_tg = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row, by_tg)
    panel_mod = _panel(panel)

    t = await panel_mod.get_client_traffic(sub["email"])
    traffic_ok = bool(t.get("success"))
    up, down = int(t.get("up") or 0), int(t.get("down") or 0)
    info = await panel_mod.get_client_info(sub["email"])
    enabled = info.get("enabled", True) if info.get("success") else True

    user = None
    if sub["tg_id"]:
        from core.database import get_user_info
        u = await get_user_info(sub["tg_id"])
        if u:
            user = {"first_name": u[1], "username": u[2]}

    referrer = None
    if kind == "paid" and sub["tg_id"]:
        from paidsub.storage import get_referrer
        from core.database import get_user_info
        ref_id = await get_referrer(sub["tg_id"])
        if ref_id:
            ref_info = await get_user_info(ref_id)
            referrer = {"tg_id": ref_id,
                        "first_name": ref_info[1] if ref_info else str(ref_id)}

    return {"ok": True, "kind": kind, "sub": sub, "row": row,
            "panel": {"enabled": enabled, "traffic_ok": traffic_ok,
                      "up": up, "down": down},
            "times_renewed": sub["times_renewed"],
            "user": user, "referrer": referrer}


# ── Вкл/выкл, заморозка, удаление ─────────────────────────────────────────────

async def toggle_sub(sub_id: int, *, kind: str = "paid", bot=None, panel=None) -> dict:
    """Включает/выключает подписку в панели (состояние читается из панели).

    Возвращает {"ok": True, "enabled": bool, "email", "tg_id"} или
    {"ok": False, "error": "not_found" | "panel_client_not_found" | <текст панели>}.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    panel_mod = _panel(panel)
    info = await panel_mod.get_client_info(sub["email"])
    if not info.get("success"):
        return {"ok": False, "error": "panel_client_not_found",
                "email": sub["email"], "tg_id": sub["tg_id"]}
    new_state = not info.get("enabled", True)
    result = await panel_mod.toggle_client(sub["email"], new_state)
    if not result.get("success"):
        return {"ok": False, "error": str(result.get("error") or "?"),
                "email": sub["email"], "tg_id": sub["tg_id"]}
    if kind == "paid":
        if new_state:
            await _notify(bot, sub["tg_id"],
                          "✅ <b>Подписка снова включена</b>\n\n"
                          "<i>VPN работает — можно подключаться.</i>")
        else:
            await _notify(bot, sub["tg_id"],
                          "⏸ <b>Подписка приостановлена</b>\n\n"
                          "<i>Вопросы — в поддержку, ответим в боте.</i>")
        await _history(kind, sub["tg_id"],
                       "sub_enabled" if new_state else "sub_disabled",
                       f"Подписка #{sub_id} ({sub['email']})")
    else:
        status_text = "✅ включена" if new_state else "⏸ приостановлена"
        await _notify(bot, sub["tg_id"],
                      f"ℹ️ Ваша админская подписка <b>{status_text}</b>.")
    return {"ok": True, "enabled": new_state,
            "email": sub["email"], "tg_id": sub["tg_id"]}


async def freeze_sub(sub_id: int, *, kind: str = "paid", bot=None, panel=None) -> dict:
    """Замораживает подписку: выключает в панели, срок не трогает.

    Возвращает {"ok": True, "enabled": False, ...} или
    {"ok": False, "error": "not_found" | "already_frozen" | <текст панели>}.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    panel_mod = _panel(panel)
    info = await panel_mod.get_client_info(sub["email"])
    enabled = info.get("enabled", True) if info.get("success") else True
    if not enabled:
        return {"ok": False, "error": "already_frozen",
                "email": sub["email"], "tg_id": sub["tg_id"]}
    result = await panel_mod.toggle_client(sub["email"], False)
    if not result.get("success"):
        return {"ok": False, "error": str(result.get("error") or "?"),
                "email": sub["email"], "tg_id": sub["tg_id"]}
    if kind == "paid":
        await _notify(bot, sub["tg_id"],
                      "❄️ <b>Подписка заморожена</b>\n\n"
                      "<blockquote>Срок на паузе — оставшиеся дни никуда не денутся.</blockquote>")
        await _history(kind, sub["tg_id"], "sub_frozen",
                       f"Подписка #{sub_id} ({sub['email']})")
    else:
        await _notify(bot, sub["tg_id"],
                      "ℹ️ Ваша админская подписка <b>⏸ приостановлена</b>.")
    return {"ok": True, "enabled": False,
            "email": sub["email"], "tg_id": sub["tg_id"]}


async def delete_sub(sub_id: int, *, kind: str = "paid", bot=None, panel=None) -> dict:
    """Удаляет подписку: сначала из панели, потом из базы.

    Панель может не принять удаление — база всё равно чистится, как было
    в хендлерах: panel_ok=False и panel_status с причиной.
    Возвращает {"ok": True, "found": bool, "panel_ok": bool,
    "panel_status": str, "email", "tg_id"}.
    """
    row, _ = await _load(kind, sub_id)
    tg_id = row[1] if row else None
    email = row[2] if row else None
    panel_ok = False
    if email:
        panel_mod = _panel(panel)
        panel_result = await panel_mod.delete_client(email)
        panel_ok = bool(panel_result.get("success"))
        panel_status = ("✅ удалена из панели" if panel_ok
                        else f"⚠️ панель: {panel_result.get('error', '?')}")
    else:
        panel_status = "⚠️ email не найден, из панели не удалено"

    if kind == "admin":
        from adminsub.storage import delete_sub as _delete_admin_sub
        await _delete_admin_sub(sub_id)
    else:
        from paidsub.storage import delete_paid_sub
        await delete_paid_sub(sub_id)

    if row:
        await _history(kind, tg_id, "sub_deleted",
                       f"Подписка #{sub_id} ({email}) · {panel_status}")
        if kind == "paid":
            await _notify(bot, tg_id,
                          "🗑 <b>Подписка удалена</b>\n\n"
                          "<i>Чтобы оформить новую, откройте /start.</i>")
        else:
            await _notify(bot, tg_id,
                          "🗑 Ваша админская подписка была <b>удалена</b>.")
    return {"ok": True, "found": row is not None, "panel_ok": panel_ok,
            "panel_status": panel_status, "email": email, "tg_id": tg_id}


# ── Срок: сдвиг и установка даты ──────────────────────────────────────────────

def _shifted_expire(expire_str, seconds: int, direction: int) -> str:
    """Новая дата окончания. Плюс — от остатка, а если срок вышел, от сегодня."""
    expire_dt = _parse_expire(expire_str)
    if expire_dt is None:
        expire_dt = datetime.now()
    if direction > 0:
        base = expire_dt if expire_dt > datetime.now() else datetime.now()
        new_expire = base + timedelta(seconds=seconds)
    else:
        new_expire = expire_dt - timedelta(seconds=seconds)
    return new_expire.strftime("%d.%m.%Y %H:%M:%S")


async def extend_sub(sub_id: int, seconds: int, *, kind: str = "paid",
                     bot=None, panel=None) -> dict:
    """Сдвигает срок подписки: seconds > 0 — добавить, < 0 — убавить.

    База + панель, при добавлении срока доступ возвращается (статус active
    у платных, включение в панели). Разница видов на ошибке панели —
    как было в хендлерах: у платных панельная ошибка не останавливает
    ни включение, ни уведомление (panel_ok=False в ответе), у админских
    действие прерывается: {"ok": False, "error", "until"}.
    Возвращает {"ok": True, "until": str, "seconds": int, "direction": int,
    "panel_ok": bool, "panel_error": str} (panel_error — "" при успехе).
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    seconds = int(seconds)
    direction = 1 if seconds >= 0 else -1
    new_str = _shifted_expire(sub["expire_date"], abs(seconds), direction)
    panel_mod = _panel(panel)

    await _set_expire_db(kind, sub_id, new_str)
    if kind == "paid" and direction > 0:
        await _write(kind, sub_id, "status", "active")
    pushed = await panel_mod.update_client_expire(sub["email"], new_str)
    panel_ok = bool(pushed.get("success"))
    panel_error = "" if panel_ok else str(pushed.get("error") or "?")
    if kind == "admin" and not panel_ok:
        return {"ok": False, "error": panel_error, "until": new_str,
                "panel_ok": False, "panel_error": panel_error,
                "seconds": seconds, "direction": direction}

    if direction > 0:
        await _re_enable_if_needed(panel_mod, sub["email"])

    action = "sub_extended" if direction > 0 else "sub_reduced"
    await _history(kind, sub["tg_id"], action,
                   f"Подписка #{sub_id} ({sub['email']})\n"
                   f"{'Добавлено' if direction > 0 else 'Убавлено'}: "
                   f"{_fmt_seconds(abs(seconds))}\nНовая дата: {new_str}")
    if kind == "paid":
        if direction > 0:
            await _notify(bot, sub["tg_id"],
                          f"🎉 <b>Ваша подписка продлена!</b>\n\n"
                          f"➕ Добавлено: <b>{_fmt_seconds(abs(seconds))}</b>\n"
                          f"📅 Действует до: <b>{new_str}</b>")
        else:
            await _notify(bot, sub["tg_id"],
                          f"ℹ️ <b>Срок вашей подписки изменён.</b>\n\n"
                          f"➖ Убавлено: <b>{_fmt_seconds(abs(seconds))}</b>\n"
                          f"📅 Действует до: <b>{new_str}</b>")
    else:
        if direction > 0:
            await _notify(bot, sub["tg_id"],
                          "🎉 <b>Подписка продлена!</b>\n\n"
                          f"<blockquote>➕ Добавлено: <b>{_fmt_seconds(abs(seconds))}</b>\n"
                          f"📅 Действует до: <b>{new_str[:16]}</b></blockquote>")
        else:
            await _notify(bot, sub["tg_id"],
                          "ℹ️ <b>Срок подписки изменён</b>\n\n"
                          f"<blockquote>➖ Убавлено: <b>{_fmt_seconds(abs(seconds))}</b>\n"
                          f"📅 Действует до: <b>{new_str[:16]}</b></blockquote>")
    await _retag(sub["tg_id"])
    return {"ok": True, "until": new_str, "seconds": seconds,
            "direction": direction, "panel_ok": panel_ok,
            "panel_error": panel_error}


async def set_expire(sub_id: int, new_expire: str, *, kind: str = "paid",
                     mark_active: bool = False, bot=None, panel=None) -> dict:
    """Ставит дату окончания как есть (строка «дд.мм.гггг[ чч:мм[:сс]]»).

    mark_active — платные правки заодно возвращают статус active.
    Панельная ошибка не отменяет запись в базе (так было в хендлерах),
    она возвращается в panel_ok/panel_error.
    Возвращает {"ok": True, "expire": str, "panel_ok": bool, "panel_error": str}.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    await _set_expire_db(kind, sub_id, new_expire)
    if mark_active:
        await _write(kind, sub_id, "status", "active")
    panel_mod = _panel(panel)
    res = await panel_mod.update_client_expire(sub["email"], new_expire)
    panel_ok = bool(res.get("success"))
    panel_error = "" if panel_ok else str(res.get("error") or "?")
    await _history(kind, sub["tg_id"], "settings_changed",
                   f"Подписка #{sub_id}: дата окончания → {new_expire}")
    await _retag(sub["tg_id"])
    return {"ok": True, "expire": new_expire,
            "panel_ok": panel_ok, "panel_error": panel_error}


# ── Лимиты ────────────────────────────────────────────────────────────────────

async def set_hwid_limit(sub_id: int, limit: int, *, kind: str = "paid",
                         bot=None, panel=None) -> dict:
    """Лимит устройств. У платных оплаченные слоты идут сверх: target =
    limit + extra_devices (0 — без ограничения, слоты не прибавляются).

    Возвращает {"ok": True, "limit": int, "target": int, "extra": int,
    "panel_ok": bool, "panel_error": str}.
    """
    row, by_tg = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row, by_tg)
    limit = int(limit)
    extra = sub["extra_devices"] if kind == "paid" else 0
    target = limit + extra if limit else 0
    await _write(kind, sub_id, "limit_hwid", target)
    panel_mod = _panel(panel)
    res = await panel_mod.update_client_limits(sub["email"], limit_hwid=target)
    panel_ok = bool(res.get("success"))
    panel_error = "" if panel_ok else str(res.get("error") or "?")
    await _history(kind, sub["tg_id"], "settings_changed",
                   f"Подписка #{sub_id}: лимит HWID → {target}")
    return {"ok": True, "limit": limit, "target": target, "extra": extra,
            "panel_ok": panel_ok, "panel_error": panel_error}


async def set_traffic_limit(sub_id: int, total_gb: int, *, kind: str = "paid",
                            bot=None, panel=None) -> dict:
    """Лимит трафика в ГБ (0 — безлимит). База + панель.

    Возвращает {"ok": True, "total_gb": int, "label": str,
    "panel_ok": bool, "panel_error": str}.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    total_gb = int(total_gb)
    label = "безлимит" if total_gb == 0 else f"{total_gb} ГБ"
    await _write(kind, sub_id, "total_gb", total_gb)
    panel_mod = _panel(panel)
    res = await panel_mod.update_client_traffic(sub["email"], total_gb)
    panel_ok = bool(res.get("success"))
    panel_error = "" if panel_ok else str(res.get("error") or "?")
    await _history(kind, sub["tg_id"], "settings_changed",
                   f"Подписка #{sub_id}: трафик → {label}")
    return {"ok": True, "total_gb": total_gb, "label": label,
            "panel_ok": panel_ok, "panel_error": panel_error}


async def set_lte_limit(sub_id: int, lte_gb, *, kind: str = "paid",
                        bot=None, panel=None) -> dict:
    """LTE-лимит в ГБ в месяц (None — по умолчанию). Только база бота:
    панель о LTE-лимите не знает.

    Возвращает {"ok": True, "lte_gb": int|None, "label": str}.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    label = "по умолчанию" if lte_gb is None else f"{int(lte_gb)} ГБ"
    await _write(kind, sub_id, "lte_gb", lte_gb)
    await _history(kind, sub["tg_id"], "settings_changed",
                   f"Подписка #{sub_id}: LTE-трафик → {label}")
    return {"ok": True, "lte_gb": lte_gb, "label": label}


async def set_trial(sub_id: int, seconds: int, *, kind: str = "paid",
                    bot=None, panel=None) -> dict:
    """Свой пробный период подписки (секунды). Только платные, только база.

    Возвращает {"ok": True, "trial_seconds": int}.
    """
    if kind != "paid":
        return {"ok": False, "error": "trial_not_supported_for_admin"}
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    await _write(kind, sub_id, "ind_trial_period", int(seconds))
    return {"ok": True, "trial_seconds": int(seconds)}


# ── Устройства и адреса ───────────────────────────────────────────────────────

async def list_devices(sub_id: int, *, kind: str = "paid", panel=None) -> dict:
    """Устройства (HWID) из панели.

    Возвращает {"ok": True, "items": [...], "limit_hwid": int, "email": str}
    или {"ok": False, "error": ...}. Формат items — как у panel.get_client_hwids.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    panel_mod = _panel(panel)
    r = await panel_mod.get_client_hwids(sub["email"])
    if not r.get("ok"):
        return {"ok": False, "error": str(r.get("error") or "?"),
                "items": [], "limit_hwid": sub["limit_hwid"],
                "email": sub["email"]}
    return {"ok": True, "items": r.get("items") or [],
            "limit_hwid": sub["limit_hwid"], "email": sub["email"]}


async def list_ips(sub_id: int, *, kind: str = "paid", panel=None) -> dict:
    """IP-адреса из панели (берутся из записей устройств).

    Возвращает {"ok": True, "items": [...], "email": str}
    или {"ok": False, "error": ...}.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    panel_mod = _panel(panel)
    r = await panel_mod.get_client_ips(sub["email"])
    if not r.get("ok"):
        return {"ok": False, "error": str(r.get("error") or "?"),
                "items": [], "email": sub["email"]}
    return {"ok": True, "items": r.get("items") or [], "email": sub["email"]}


async def delete_device(sub_id: int, ref: str, *, kind: str = "paid",
                        bot=None, panel=None, history: bool = True) -> dict:
    """Убирает одно устройство. ref — метка из кнопки (начало hwid).

    history=False — не писать в историю (самообслуживание клиента:
    отключение своего устройства — не действие админа).

    Возвращает {"ok": True, "hwid_id": str} или
    {"ok": False, "error": "not_found" | "gone" | <текст панели>}.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    panel_mod = _panel(panel)
    hwid_id = await panel_mod.resolve_hwid(sub["email"], ref)
    if hwid_id is None:
        return {"ok": False, "error": "gone", "email": sub["email"]}
    res = await panel_mod.delete_client_hwid(sub["email"], hwid_id)
    if not res.get("success"):
        return {"ok": False, "error": str(res.get("error") or "?"),
                "hwid_id": hwid_id}
    if history:
        await _history(kind, sub["tg_id"], "settings_changed",
                       f"Убрано устройство #{hwid_id}")
    return {"ok": True, "hwid_id": hwid_id, "email": sub["email"]}


async def clear_hwid(sub_id: int, *, kind: str = "paid", bot=None, panel=None) -> dict:
    """Забывает все устройства подписки в панели.

    Возвращает {"ok": True} или {"ok": False, "error": ...}.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    panel_mod = _panel(panel)
    res = await panel_mod.clear_client_hwids(sub["email"])
    if not res.get("success"):
        return {"ok": False, "error": str(res.get("error") or "?"),
                "email": sub["email"]}
    await _history(kind, sub["tg_id"], "settings_changed",
                   "Очищены все устройства (HWID)")
    if kind == "paid":
        await _notify(bot, sub["tg_id"],
                      "📱 <b>Список устройств сброшен</b>\n\n"
                      "<i>Просто включите VPN на тех устройствах, которыми пользуетесь, — "
                      "они добавятся заново.</i>")
    else:
        await _notify(bot, sub["tg_id"],
                      "📱 <b>Список устройств очищен</b>\n\n"
                      "<blockquote>Включите VPN на нужных устройствах — "
                      "они добавятся заново.</blockquote>")
    return {"ok": True, "email": sub["email"]}


# ── Перевыпуск ключа ──────────────────────────────────────────────────────────

async def reissue_sub(sub_id: int, *, kind: str = "paid", bot=None, panel=None) -> dict:
    """Меняет ссылку подписки в панели и пишет новые uuid/sub_id/sub_url в базу.

    Старая ссылка перестаёт работать. Уведомление владельцу — только
    для админских (у платных перевыпуск делает сам владелец в своём чате,
    ссылку показывает хендлер). Лог-канал пишет хендлер: тексты там разные.
    Возвращает {"ok": True, "new_url": str, "new_uuid": str, "sub_id": str}
    или {"ok": False, "error": ...}.
    """
    row, _ = await _load(kind, sub_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sub = _norm(kind, row)
    panel_mod = _panel(panel)
    result = await panel_mod.reissue_subscription(sub["email"])
    if not result.get("success"):
        return {"ok": False, "error": str(result.get("error") or "?"),
                "email": sub["email"], "tg_id": sub["tg_id"]}
    new_url = result.get("sub_url") or ""
    await _write(kind, sub_id, "uuid", result.get("new_uuid", ""))
    await _write(kind, sub_id, "sub_id", result.get("sub_id", ""))
    await _write(kind, sub_id, "sub_url", new_url)
    await _history(kind, sub["tg_id"], "key_reissued", f"Новая ссылка: {new_url}")
    if kind == "admin":
        # владельцу показываем только sub.drbl.tech, в базе хранится key
        from handlers.user import primary_sub_url
        await _notify(bot, sub["tg_id"],
                      "🔁 <b>Ключ подписки перевыпущен</b>\n\n"
                      f"<blockquote><code>{_esc(primary_sub_url(new_url))}</code></blockquote>\n\n"
                      "Удалите старую подписку в приложении и вставьте эту ссылку — "
                      "старая больше не работает.")
    return {"ok": True, "new_url": new_url,
            "new_uuid": result.get("new_uuid", ""),
            "sub_id": result.get("sub_id", ""),
            "email": sub["email"], "tg_id": sub["tg_id"]}


# ── Массовые действия (только платные) ────────────────────────────────────────

async def bulk_extend(seconds: int, direction: int, *, bot=None, panel=None,
                      only_ids=None) -> dict:
    """Сдвигает срок у платных подписок. direction: +1 добавить, -1 убавить.

    only_ids — ограничить выборкой (вкладка списка); None — все подписки.
    Подписки из ЧС не трогаются. Ошибка панели по одной подписке не
    останавливает остальные (как было в хендлере: результат панели
    здесь не проверяется, срок в базе уже сдвинут).
    Возвращает {"updated": int, "errors": int, "total": int, "skipped": int}.
    """
    from paidsub.storage import get_paid_sub
    from features.blacklist import blacklisted_ids
    from core.database import DB_PATH
    import aiosqlite
    panel_mod = _panel(panel)
    if only_ids is not None:
        all_ids = [int(i) for i in only_ids]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id FROM paid_subs") as cur:
                all_ids = [r[0] for r in await cur.fetchall()]

    updated = errors = skipped = 0
    skip_ids = await blacklisted_ids()
    for sid in all_ids:
        row = await get_paid_sub(sid)
        if not row:
            continue
        sub = _norm("paid", row)
        if sub["tg_id"] in skip_ids:
            skipped += 1
            continue
        new_str = _shifted_expire(sub["expire_date"], int(seconds), int(direction))
        try:
            await _set_expire_db("paid", sid, new_str)
            await panel_mod.update_client_expire(sub["email"], new_str)
            if direction > 0:
                await _write("paid", sid, "status", "active")
                await _re_enable_if_needed(panel_mod, sub["email"])
            updated += 1
            if sub["tg_id"]:
                if direction > 0:
                    await _notify(bot, sub["tg_id"],
                                  f"🎉 <b>Подписка продлена!</b>\n\n"
                                  f"<blockquote>➕ Добавлено: <b>{_fmt_seconds(seconds)}</b>\n"
                                  f"📅 Действует до: <b>{new_str[:16]}</b></blockquote>")
                else:
                    await _notify(bot, sub["tg_id"],
                                  f"ℹ️ <b>Срок подписки изменён</b>\n\n"
                                  f"<blockquote>➖ Убавлено: <b>{_fmt_seconds(seconds)}</b>\n"
                                  f"📅 Действует до: <b>{new_str[:16]}</b></blockquote>")
                await _history("paid", sub["tg_id"],
                               "bulk_extended" if direction > 0 else "bulk_reduced",
                               f"Подписка #{sid} ({sub['email']})\n"
                               f"{'Добавлено' if direction > 0 else 'Убавлено'}: "
                               f"{_fmt_seconds(seconds)}\nНовая дата: {new_str}")
        except Exception:
            errors += 1
    return {"updated": updated, "errors": errors,
            "total": len(all_ids), "skipped": skipped}


async def bulk_set_limits(kind_limit: str, value, *, bot=None, panel=None,
                          only_ids=None) -> dict:
    """Ставит лимит платным подпискам. kind_limit: "hwid" или "lte".

    only_ids — ограничить выборкой (вкладка списка); None — все подписки.
    Устройства — в базе и в панели, LTE — только в базе (панель о нём
    не знает). Оплаченные слоты устройств идут сверх общего лимита.
    Тем, кому стало строже, приходит уведомление.
    Возвращает {"updated": int, "panel_fail": int, "skipped": int,
    "tightened": int}.
    """
    from paidsub.storage import update_paid_sub_field
    from features.blacklist import blacklisted_ids
    from core.database import DB_PATH
    import aiosqlite
    limits = {"hwid": ("🖥", "устройств", "limit_hwid"),
              "lte": ("📡", "LTE-трафика", "lte_gb")}
    _emoji, label, field = limits[kind_limit]
    async with aiosqlite.connect(DB_PATH) as db:
        if only_ids is not None:
            ids = [int(i) for i in only_ids] or [-1]
            marks = ",".join("?" for _ in ids)
            async with db.execute(
                f"SELECT id, tg_id, email, {field}, extra_devices FROM paid_subs "
                f"WHERE id IN ({marks})", ids
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                f"SELECT id, tg_id, email, {field}, extra_devices FROM paid_subs"
            ) as cur:
                rows = await cur.fetchall()

    skip_ids = await blacklisted_ids()
    panel_mod = _panel(panel)
    updated = panel_fail = skipped = 0
    tightened = []
    if kind_limit == "lte":
        from services.remnawave import lte_limit_gb
        preset = load_config().get("paid_preset_lte")
        new_eff = lte_limit_gb(None, preset) if value is None else value
    for sub_id, tg_id, email, old, extra in rows:
        if tg_id in skip_ids:
            skipped += 1
            continue
        target = value + int(extra or 0) if (kind_limit == "hwid" and value) else value
        await update_paid_sub_field(sub_id, field, target)
        if kind_limit == "hwid":
            res = await panel_mod.update_client_limits(email, limit_hwid=target)
            if not res.get("success"):
                panel_fail += 1
        updated += 1
        if tg_id:
            if kind_limit == "lte":
                hist_label = "по умолчанию" if target is None else f"{target} ГБ"
            else:
                hist_label = target or "без ограничения"
            await _history("paid", tg_id, "settings_changed",
                           f"Массово: лимит {label} → {hist_label}"
                           + (f" (в т.ч. докуплено {extra})" if target != value else ""))
            if kind_limit == "lte":
                if new_eff < lte_limit_gb(old, preset):
                    tightened.append((tg_id, new_eff))
            elif target and (not old or target < old):
                tightened.append((tg_id, target))

    for tg_id, target in tightened:
        if kind_limit == "lte":
            await _notify(bot, tg_id,
                          "🌐 <b>Изменён лимит LTE-трафика</b>\n\n"
                          f"<blockquote>Теперь в месяц: <b>{target} ГБ</b></blockquote>\n\n"
                          "<i>Остаток смотри в «Моя подписка».</i>")
        else:
            await _notify(bot, tg_id,
                          "📱 <b>Изменён лимит устройств</b>\n\n"
                          f"<blockquote>Теперь можно подключить: <b>{target}</b></blockquote>\n\n"
                          "<i>Лишние устройства перестанут подключаться.</i>")
    return {"updated": updated, "panel_fail": panel_fail,
            "skipped": skipped, "tightened": len(tightened)}


# ── Создание подписки (для подарка и ручной выдачи) ───────────────────────────

async def create_paid_sub(tg_id: int, *, trial: bool = False,
                          period_seconds: int | None = None,
                          bot=None, panel=None) -> dict:
    """Создаёт платную подписку: панель + база + фиксация условий.

    Срок: пробная — paid_trial_period, платная — period_seconds, а без
    него тоже paid_trial_period (так было в do_create_paid_sub).
    Без уведомлений: тексты показывает вызывающий (хендлер или gift_sub).
    Возвращает {"ok": True, "sub_id": int, "email": str, "uuid": str,
    "sub_url": str, "expire": str, "period_label": str, "traffic_str": str}
    или {"ok": False, "error": str}.
    """
    cfg = load_config()
    from core.database import get_user_info
    from services.panel import build_email
    user_row = await get_user_info(tg_id)
    username = user_row[2] if user_row else None
    email = build_email(tg_id, username, prefix="paid_")

    if trial:
        seconds = int(cfg.get("paid_trial_period", 86400))
    else:
        seconds = int(period_seconds or cfg.get("paid_trial_period", 86400))
    expire_dt = datetime.now() + timedelta(seconds=seconds)
    expire_date = expire_dt.strftime("%d.%m.%Y %H:%M:%S")

    panel_mod = _panel(panel)
    result = await panel_mod.create_client(
        expire_date=expire_date, limit_ip=0,
        limit_hwid=int(cfg.get("paid_preset_hwid", 0)),
        total_gb=int(cfg.get("paid_preset_traffic", 0)),
        email=email, tg_id=tg_id, note=f"@{username}" if username else "")
    if not result.get("success"):
        return {"ok": False, "error": str(result.get("error") or "?")}

    from paidsub.storage import (add_paid_sub, snapshot_sub_settings,
                                 update_paid_sub_field)
    new_sub_id = await add_paid_sub(
        tg_id=tg_id, email=result["email"], uuid_val=result["uuid"],
        sub_id=result["sub_id"], sub_url=result["sub_url"],
        expire_date=result["expire"], limit_ip=0,
        limit_hwid=int(cfg.get("paid_preset_hwid", 0)),
        total_gb=int(cfg.get("paid_preset_traffic", 0)))
    await snapshot_sub_settings(new_sub_id)
    await update_paid_sub_field(new_sub_id, "period_end", expire_date)
    if not trial:
        await update_paid_sub_field(new_sub_id, "times_renewed", 1)

    period_label = "пробный период" if trial else "оплаченный период"
    traffic = int(cfg.get("paid_preset_traffic", 0) or 0)
    traffic_str = f"{traffic} ГБ" if traffic > 0 else "безлимит"
    await _history("paid", tg_id, "sub_created",
                   f"Подписка #{new_sub_id} ({period_label})\n"
                   f"Email: {result['email']}\nДо: {result['expire']}")
    await _retag(tg_id)
    return {"ok": True, "sub_id": new_sub_id, "email": result["email"],
            "uuid": result["uuid"], "sub_url": result["sub_url"],
            "expire": result["expire"], "period_label": period_label,
            "traffic_str": traffic_str}


async def create_admin_sub(tg_id: int, *, bot=None, panel=None) -> dict:
    """Создаёт админскую подписку: панель + база + уведомление.

    Чистое ядро do_create_sub() из adminsub/handlers.py: пресеты
    (preset_expire/preset_hwid/preset_traffic) — условия выдачи,
    email — build_email(tg_id) без префикса. Панель — первая:
    uuid/sub_id/sub_url приходят от неё, и при её ошибке в базе
    ничего не появляется. Без импортов Telegram.
    Возвращает {"ok": True, "sub_id": int, "email": str, "uuid": str,
    "sub_url": str, "expire": str, "traffic_str": str}
    или {"ok": False, "error": "presets_not_ready" | "user_not_found" |
    <текст панели>}.
    """
    cfg = load_config()
    if not all(cfg.get(k) is not None
               for k in ("preset_expire", "preset_hwid", "preset_traffic")):
        return {"ok": False, "error": "presets_not_ready"}
    from core.database import get_user_info
    user_row = await get_user_info(tg_id)
    if not user_row:
        return {"ok": False, "error": "user_not_found"}
    username = user_row[2]
    from services.panel import build_email
    email = build_email(tg_id, username)
    panel_mod = _panel(panel)
    result = await panel_mod.create_client(
        expire_date=cfg["preset_expire"], limit_ip=0,
        limit_hwid=int(cfg["preset_hwid"]),
        total_gb=int(cfg["preset_traffic"]),
        email=email, tg_id=tg_id, note=f"@{username}" if username else "")
    if not result.get("success"):
        return {"ok": False, "error": str(result.get("error") or "?")}
    from adminsub.storage import add_sub
    new_sub_id = await add_sub(
        email=result["email"], uuid_val=result["uuid"],
        sub_id=result["sub_id"], sub_url=result["sub_url"],
        expire_date=result["expire"], limit_ip=0,
        limit_hwid=int(cfg["preset_hwid"]),
        total_gb=int(cfg["preset_traffic"]), tg_id=tg_id)
    traffic = int(cfg["preset_traffic"])
    traffic_str = f"{traffic} ГБ" if traffic > 0 else "безлимит"
    await _notify(bot, tg_id,
                  "🎉 <b>Вам выдана админская подписка!</b>\n\n"
                  f"📅 Действует до: <b>{result['expire']}</b>\n"
                  f"📶 Трафик: <b>{traffic_str}</b>\n\n"
                  f"🔗 Ссылка подписки:\n<code>{result['sub_url']}</code>\n\n"
                  "Скопируй ссылку и вставь в приложение (INCY, Happ и др.)")
    await _retag(tg_id)
    return {"ok": True, "sub_id": new_sub_id, "email": result["email"],
            "uuid": result["uuid"], "sub_url": result["sub_url"],
            "expire": result["expire"], "traffic_str": traffic_str}


# ── Оплата, устройства, подарок, возврат ──────────────────────────────────────

async def apply_devices_payment(tg_id: int, count: int, *, amount: int = 0,
                                mode: str = "add", bot=None, panel=None) -> dict:
    """Начисляет оплаченные слоты устройств: база + панель + уведомление.

    mode="add" — слоты прибавляются к уже оплаченным; mode="set" — слотов
    становится ровно count (0 — возврат к своему лимиту подписки).
    Возвращает {"ok": True, "limit": int, "changed": bool, "panel": bool}
    или {"ok": False, "error": str}.
    """
    from paidsub.storage import (get_paid_sub_by_tg_id, base_hwid,
                                 update_paid_sub_field)
    panel_mod = _panel(panel)
    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return {"ok": False, "error": "подписка не найдена"}
    sub_id, email = row[0], row[2]
    extra_was = int(row[18] if len(row) > 18 and row[18] else 0)
    base = base_hwid(row[8], extra_was)
    count = int(count or 0)

    if mode == "set":
        extra_now = max(0, count)
        if extra_now == extra_was:
            return {"ok": True, "limit": int(row[8] or 0), "changed": False}
    else:
        if base <= 0:
            return {"ok": False, "error": "у подписки нет лимита устройств"}
        extra_now = extra_was + max(1, count)

    if base <= 0:
        await update_paid_sub_field(sub_id, "extra_devices", extra_now)
        return {"ok": True, "limit": 0, "changed": False}

    new_limit = base + extra_now
    await update_paid_sub_field(sub_id, "limit_hwid", new_limit)
    await update_paid_sub_field(sub_id, "extra_devices", extra_now)
    res = await panel_mod.update_client_limits(email, limit_hwid=new_limit)
    note = "" if res.get("success") else f" (панель: {res.get('error', '?')})"

    added = extra_now - extra_was
    if added > 0:
        action = f"Оплачено устройств: +{added} → лимит {new_limit}"
    else:
        action = f"Отказ от устройств: {extra_was} → {extra_now}, лимит {new_limit}"
    await _history("paid", tg_id, "devices_bought",
                   action + (f"\nСумма: {amount} ₽" if amount else "") + note)
    if added > 0:
        await _notify(bot, tg_id,
                      "✅ <b>Устройства добавлены</b>\n\n"
                      f"<blockquote>📱 Теперь можно подключить: <b>{new_limit}</b></blockquote>")
    elif added < 0:
        await _notify(bot, tg_id,
                      "📱 <b>Дополнительные устройства отключены</b>\n\n"
                      f"<blockquote>Теперь можно подключить: <b>{new_limit}</b></blockquote>")
    return {"ok": True, "limit": new_limit, "changed": True,
            "panel": bool(res.get("success", False))}


def _renew_base(full_row) -> tuple:
    """С какой точки отсчитывать оплаченный срок: остаток не сгорает."""
    now = datetime.now()
    raw = full_row[18] if full_row is not None and len(full_row) > 18 else None
    if not raw:
        raw = full_row[6] if full_row is not None and len(full_row) > 6 else None
    end = _parse_expire(raw) if raw else None
    if end and end > now:
        return end, int((end - now).total_seconds())
    return now, 0


async def apply_paid_payment(tg_id: int, amount: int, *, promo_code: str | None = None,
                             source: str = "Platega",
                             period_seconds: int | None = None,
                             gift_from: int | None = None,
                             bot=None, panel=None) -> dict:
    """Засчитывает оплату: продлевает период, включает клиента, списывает промокод.

    Возвращает {"ok": True, "expire": str} или {"ok": False, "error": str}.
    """
    from features.blacklist import is_blacklisted
    if await is_blacklisted(tg_id):
        return {"ok": False, "error": "пользователь в чёрном списке — срок не начислен: "
                                      "верни деньги или убери из ЧС"}
    from paidsub.storage import (get_paid_sub_by_tg_id, get_paid_sub,
                                 sub_settings, update_paid_sub_field,
                                 get_pending_promo, get_promo, promo_used_by,
                                 record_promo_use)
    from core.database import get_user_info, list_tariffs
    panel_mod = _panel(panel)

    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return {"ok": False, "error": "подписка не найдена"}
    sub_id, email = row[0], row[2]
    full_row = await get_paid_sub(sub_id)
    settings = sub_settings(full_row)
    pay_seconds = int(period_seconds or settings["pay_period"] or 0)
    guessed = ""
    if not pay_seconds:
        tariffs = await list_tariffs(only_active=True)
        pay_seconds = int(tariffs[0][2]) if tariffs else 30 * 86400
        guessed = (f"⚠️ У платежа не было срока — начислил "
                   f"{_fmt_seconds(pay_seconds)} "
                   + ("по первому тарифу" if tariffs else "по умолчанию (30 дней)"))
    base, _carried = _renew_base(full_row)
    new_expire = base + timedelta(seconds=pay_seconds)
    new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")

    await update_paid_sub_field(sub_id, "expire_date", new_expire_str)
    await update_paid_sub_field(sub_id, "period_end", new_expire_str)
    await update_paid_sub_field(sub_id, "status", "active")
    await update_paid_sub_field(sub_id, "payment_pending", 0)
    await update_paid_sub_field(sub_id, "remind_stage", 0)
    cur_renewed = row[12] if len(row) > 12 else 0
    await update_paid_sub_field(sub_id, "times_renewed", cur_renewed + 1)

    info = await panel_mod.get_client_info(email)
    if info.get("success") and not info.get("enabled", True):
        await panel_mod.toggle_client(email, True)
    paid_panel = await panel_mod.update_client_expire(email, new_expire_str)
    if not paid_panel.get("success"):
        await _send_log(bot,
                        f"🛑 Оплата зачтена, но панель не приняла новый срок: "
                        f"<code>{email}</code> — {paid_panel.get('error', '?')}\n"
                        f"Проставь срок <b>{new_expire_str}</b> в панели руками.")

    promo_line = ""
    pending_promo = promo_code or await get_pending_promo(tg_id)
    if pending_promo:
        promo = await get_promo(pending_promo)
        promo_who = gift_from or tg_id
        if promo and not await promo_used_by(pending_promo, promo_who):
            await record_promo_use(pending_promo, promo_who)
            await _history("paid", promo_who, "promo_used",
                           f"Промокод {pending_promo} (−{promo[2]}%)")
            promo_line = f"🎟 Промокод: <b>{pending_promo}</b> (−{promo[2]}%)\n"
        await update_paid_sub_field(sub_id, "pending_promo", None)

    giver_name = None
    if gift_from:
        _gr = await get_user_info(gift_from)
        giver_name = _esc(_gr[1] if _gr else None, gift_from)

    promo_note = f" (промокод {pending_promo})" if promo_line else ""
    if gift_from:
        await _history("paid", tg_id, "gift_received",
                       f"Подарок от {giver_name}: {amount} ₽{promo_note}\n"
                       f"Через: {source}\nДо: {new_expire_str}")
    else:
        await _history("paid", tg_id, "payment_confirmed",
                       f"Сумма: {amount} ₽{promo_note}\nЧерез: {source}\nДо: {new_expire_str}")

    u = await get_user_info(tg_id)
    u_name = _esc(u[1] if u else None, tg_id)
    if gift_from:
        await _send_log(bot,
                        f"🎁 Подарок через {source}: {giver_name} (<code>{gift_from}</code>) → "
                        f"{u_name} (<code>{tg_id}</code>) — {amount} ₽\n"
                        f"{promo_line}📅 До: {new_expire_str}"
                        + (f"\n{guessed}" if guessed else ""))
    else:
        await _send_log(bot,
                        f"💰 Оплата через {source}: {u_name} (<code>{tg_id}</code>) — {amount} ₽\n"
                        f"{promo_line}📅 До: {new_expire_str}"
                        + (f"\n{guessed}" if guessed else ""))

    if gift_from:
        await _notify(bot, tg_id,
                      "🎁 <b>Вам подарили подписку Drebol VPN!</b>\n\n"
                      f"<blockquote>➕ Добавлено: <b>{_fmt_seconds(pay_seconds)}</b>\n"
                      f"📅 Подписка до: <b>{new_expire_str[:16]}</b></blockquote>\n\n"
                      f"<i>Подарил: {giver_name}</i>")
    else:
        await _notify(bot, tg_id,
                      "✅ <b>Оплата прошла — спасибо!</b>\n\n"
                      f"<blockquote>➕ Добавлено: <b>{_fmt_seconds(pay_seconds)}</b>\n"
                      f"📅 Подписка до: <b>{new_expire_str[:16]}</b></blockquote>")

    try:
        if gift_from:
            admin_text = (
                f"🎁 <b>Подарок через {source}</b>\n\n"
                f"🎁 От: {giver_name} (<code>{gift_from}</code>)\n"
                f"👤 Кому: {u_name} (<code>{tg_id}</code>)\n"
                f"💵 {amount} ₽\n{promo_line}"
                f"📅 До: <b>{new_expire_str}</b>")
        else:
            admin_text = (
                f"💰 <b>Оплата через {source}</b>\n\n"
                f"👤 {u_name} (<code>{tg_id}</code>)\n"
                f"💵 {amount} ₽\n{promo_line}"
                f"📅 До: <b>{new_expire_str}</b>")
        if bot:
            await bot.send_message(chat_id=ADMIN_ID, text=admin_text,
                                   parse_mode="HTML")
    except Exception:
        pass
    await _retag(tg_id)
    return {"ok": True, "expire": new_expire_str}


async def gift_sub(gift_tg: int, giver_tg: int, amount: int, *,
                   promo_code: str | None = None, source: str = "Platega",
                   period_seconds: int | None = None,
                   bot=None, panel=None) -> dict:
    """Засчитывает оплаченный подарок: подписка открывается у получателя.

    Подписка есть — продлеваем как обычную оплату. Нет — создаём
    с оплаченным сроком (без триала). Возвращает {"ok": True, "expire": str}
    или {"ok": False, "error": str}.
    """
    from features.blacklist import is_blacklisted
    if await is_blacklisted(gift_tg):
        return {"ok": False, "error": "получатель в чёрном списке — срок не начислен: "
                                      "верни деньги или убери из ЧС"}
    from paidsub.storage import (get_paid_sub_by_tg_id, get_promo,
                                 promo_used_by, record_promo_use,
                                 update_paid_sub_field)
    from core.database import get_user_info

    row = await get_paid_sub_by_tg_id(gift_tg)
    if row:
        res = await apply_paid_payment(
            gift_tg, amount, promo_code=promo_code, source=source,
            period_seconds=period_seconds, gift_from=giver_tg,
            bot=bot, panel=panel)
        if not res.get("ok"):
            return res
    else:
        await _notify(bot, giver_tg, "⏳ Создаю подписку…")
        created = await create_paid_sub(
            gift_tg, trial=False, period_seconds=period_seconds,
            bot=bot, panel=panel)
        if not created.get("ok"):
            return {"ok": False, "error": created.get("error") or "?"}
        await _notify(bot, giver_tg,
                      f"✅ <b>Подписка создана (оплаченный период)!</b>\n\n"
                      f"👤 TG ID: <code>{gift_tg}</code>\n"
                      f"📧 Email: <code>{created['email']}</code>\n"
                      f"📅 До: <b>{created['expire']}</b>\n"
                      f"📶 Трафик: <b>{created['traffic_str']}</b>\n\n"
                      f"🔗 Ссылка:\n<code>{created['sub_url']}</code>")
        row2 = await get_paid_sub_by_tg_id(gift_tg)
        if not row2:
            return {"ok": False, "error": "не удалось создать подписку получателя"}
        if promo_code:
            promo = await get_promo(promo_code)
            if promo and not await promo_used_by(promo_code, giver_tg):
                await record_promo_use(promo_code, giver_tg)
                await _history("paid", giver_tg, "promo_used",
                               f"Промокод {promo_code} (−{promo[2]}%)")
        giver_row = await get_user_info(giver_tg)
        giver_name = _esc(giver_row[1] if giver_row else None, giver_tg)
        new_expire = str(row2[6])[:16]
        sub_url = row2[5]
        await _notify(bot, gift_tg,
                      "🎁 <b>Вам подарили подписку Drebol VPN!</b>\n\n"
                      f"<blockquote>📅 Подписка до: <b>{new_expire}</b></blockquote>\n\n"
                      "🔑 <b>Ссылка для подключения</b>\n"
                      f"<code>{sub_url}</code>\n\n"
                      f"<i>Подарил: {giver_name}</i>")
        await _history("paid", gift_tg, "gift_received",
                       f"Подарок от {giver_name}: {amount} ₽\nДо: {new_expire}")
        u = await get_user_info(gift_tg)
        u_name = _esc(u[1] if u else None, gift_tg)
        await _send_log(bot,
                        f"🎁 Подарок через {source}: {giver_name} (<code>{giver_tg}</code>) → "
                        f"{u_name} (<code>{gift_tg}</code>) — {amount} ₽\n"
                        f"📅 До: {new_expire}")
        res = {"ok": True, "expire": str(row2[6])}

    giver_row = await get_paid_sub_by_tg_id(giver_tg)
    if giver_row:
        await update_paid_sub_field(giver_row[0], "pending_promo", None)

    u = await get_user_info(gift_tg)
    if u and u[1]:
        recipient_name = _esc(u[1], gift_tg)
    else:
        try:
            chat = await bot.get_chat(gift_tg)
            recipient_name = _esc(
                f"@{chat.username}" if getattr(chat, "username", None)
                else (chat.first_name or f"id{gift_tg}"), gift_tg)
        except Exception:
            recipient_name = f"id{gift_tg}"
    pay_seconds = int(period_seconds or 0)
    expire = str(res.get("expire", ""))[:16]
    lines = ["🎁 <b>Подарок оплачен и выдан!</b>", "",
             "<blockquote>"
             f"👤 {recipient_name}"]
    if pay_seconds:
        lines.append(f"➕ Срок: <b>{_fmt_seconds(pay_seconds)}</b>")
    if expire:
        lines.append(f"📅 Подписка до: <b>{expire}</b>")
    lines.append("</blockquote>")
    await _notify(bot, giver_tg, "\n".join(lines))
    await _history("paid", giver_tg, "gift_sent",
                   f"Подарок {recipient_name}: {amount} ₽\nДо: {expire}")
    return res


async def revoke_period(tg_id: int, period_seconds: int | None, *,
                        reason: str = "Возврат платежа",
                        bot=None, panel=None) -> dict:
    """Отзывает оплаченный срок (возврат платежа): дата назад, при уходе
    срока в прошлое доступ закрывается сразу.

    Возвращает {"ok": True, "expire": str, "panel_error": str}
    или {"ok": False, "error": str}.
    """
    if not period_seconds:
        return {"ok": False, "error": "у платежа нет сохранённого периода"}
    from paidsub.storage import get_paid_sub_by_tg_id, set_expire_date
    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return {"ok": False, "error": "подписка не найдена"}
    sub_id, email, expire_str = row[0], row[2], row[6]
    expire_dt = _parse_expire(expire_str)
    if not expire_dt:
        return {"ok": False, "error": f"не разобрал дату окончания: {expire_str}"}
    new_expire = expire_dt - timedelta(seconds=int(period_seconds))
    new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")
    await set_expire_date(sub_id, new_expire_str)
    panel_mod = _panel(panel)
    panel_error = ""
    r = await panel_mod.update_client_expire(email, new_expire_str)
    if not r.get("success"):
        panel_error = str(r.get("error") or "панель не приняла новый срок")
    if new_expire <= datetime.now():
        off = await panel_mod.toggle_client(email, False)
        if not off.get("success"):
            panel_error = ((panel_error + "; ") if panel_error else "") + \
                str(off.get("error") or "не удалось отключить клиента")
        await _write("paid", sub_id, "status", "expired")
    await _history("paid", tg_id, "payment_refunded",
                   f"{reason}\nОтозвано: {_fmt_seconds(int(period_seconds))}\n"
                   f"Новая дата: {new_expire_str}"
                   + (f"\n⚠️ Панель: {panel_error}" if panel_error else ""))
    await _retag(tg_id)
    return {"ok": True, "expire": new_expire_str, "panel_error": panel_error}
