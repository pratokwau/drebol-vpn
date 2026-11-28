"""Веб-админка Drebol VPN — фаза 3: узлы/панель, логи, синхронизации,
сайт, бэкап, помощники, ЧС, фрод, поддержка, падения, онлайн.

Только маршруты поверх уже существующих функций: панель (read-only),
логи, утренняя сводка, netcheck, деплой сайта, git-update, бэкап.
Никакого редактирования профилей/инбаундов Remnawave, никакого
изменения поведения кабинета и фазы 1 (auth/CSRF/CORS/bind/lockout).

register(app) добавляет маршруты в переданное админ-подприложение
(то, что монтируется в webapi.build_app() как /api/admin), поэтому
пути здесь ОТНОСИТЕЛЬНЫЕ — без префикса /api/admin.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import logging
import os
import re
import subprocess
from datetime import datetime
from types import SimpleNamespace

from aiohttp import web

from features import backup as backup_mod
from features import blacklist as bl_mod
from features import fraud as fraud_mod
from features import staff as staff_mod
from handlers import morning as morning_mod
from handlers import netcheck as netcheck_mod
from services import globalping as gp_mod
from services import panel as panel_mod
from services import panel_tags as tags_mod
from services import remnawave as rw_mod
from web import site_deploy as site_mod
from web.admin_api import (
    _audit, _require_actor, _require_mutation, _reschedule_morning,
    confirm_needed_response, get_bot, issue_confirm, require_mark,
    take_confirm, validate_settings_patch,
)
from web.admin_api import _application as _admin_application

SECRET_CONFIG_KEYS = (
    "rw_token", "platega_secret", "support_bot_token", "site_pass",
    "turnstile_secret_key",
)


def _real_schedule_restart() -> None:
    """Тот же рестарт, что features/backup.py _schedule_restart: выйти
    через 2 с, systemd поднимет бота заново."""
    async def _bye():
        await asyncio.sleep(2)
        os._exit(0)

    try:
        asyncio.get_running_loop().create_task(_bye())
    except RuntimeError:
        asyncio.get_event_loop().create_task(_bye())


# Хук планировщика рестарта: тесты подменяют его стабом, чтобы не убить
# тестовый процесс (см. set_restart_scheduler).
_schedule_restart_fn = _real_schedule_restart


def set_restart_scheduler(fn) -> None:
    """Подменить планировщик рестарта (тесты) или вернуть настоящий."""
    global _schedule_restart_fn
    _schedule_restart_fn = fn or _real_schedule_restart


def _scrub(text: str) -> str:
    """Вырезает значения секретов из текста (логи, экспорт, отчёты)."""
    if not text:
        return text
    try:
        from config import load_config
        cfg = load_config()
    except Exception:
        return text
    for key in SECRET_CONFIG_KEYS:
        value = cfg.get(key)
        if isinstance(value, str) and len(value) >= 4 and value in text:
            text = text.replace(value, "***")
    return text


def _json_error(error: str, status: int = 400):
    return web.json_response({"error": error}, status=status)


def _actor_id(actor: dict):
    return actor.get("tg_id") or actor.get("account_id")


def _mark_only(actor):
    if not require_mark(actor):
        return _json_error("mark_only", 403)
    return None


async def _json_body(request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _int_query(request, name: str, default: int) -> int:
    try:
        return int(request.query.get(name) or default)
    except (TypeError, ValueError):
        return default


# ── Узлы и панель (только чтение) ────────────────────────────────────────────

async def nodes(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    try:
        servers = await panel_mod.probe_servers()
    except Exception as ex:
        logging.error("админка: probe_servers: %s", ex)
        servers = {"ok": False, "error": "probe_failed"}
    try:
        sites = await panel_mod.probe_sites()
    except Exception as ex:
        logging.error("админка: probe_sites: %s", ex)
        sites = {}
    # Последний неприменённый срок — как блок «Срок не применился» в ТГ
    # handle_healthcheck: панель помнит его в services.panel.LAST_EXPIRE_FAIL.
    expire_fail = getattr(panel_mod, "LAST_EXPIRE_FAIL", None)
    return web.json_response({"servers": servers, "sites": sites,
                              "expire_fail": expire_fail})


async def squads(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    res = await rw_mod.list_squads()
    return web.json_response(res)


async def panel_view(request):
    """Живой вид панели: узлы, сквады, счётчик пользователей. Только чтение."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    nodes_res = await rw_mod.nodes()
    squads_res = await rw_mod.list_squads()
    profiles_res = await rw_mod.list_config_profiles()
    try:
        users = await panel_mod.count_panel_clients()
    except Exception as ex:
        logging.error("админка: count_panel_clients: %s", ex)
        users = {"success": False, "error": "panel_failed"}
    return web.json_response({
        "nodes": nodes_res.get("data") if nodes_res.get("ok") else [],
        "nodes_ok": bool(nodes_res.get("ok")),
        "nodes_error": None if nodes_res.get("ok") else "panel_failed",
        "squads": squads_res.get("squads") if squads_res.get("ok") else [],
        "squads_ok": bool(squads_res.get("ok")),
        "profiles": profiles_res.get("profiles") if profiles_res.get("ok") else [],
        "profiles_ok": bool(profiles_res.get("ok")),
        "users": users,
    })


# ── Трафик по узлам: паритет с экраном «Трафик» в ТГ ─────────────────────────
# (services/remnawave.py handle_rw_usage / handle_rw_usage_node /
# handle_rw_usage_all): те же периоды, та же сортировка по убыванию ГБ,
# те же подписи имён из базы, пагинация 20/стр. Периоды считает тот же
# rw_mod.resolve_usage_period, что в ТГ; подписи — структурированным
# JSON, а не HTML-строками _resolve_usage_labels.

_USAGE_PERIODS = ("month", "prev", "7d", "30d", "90d", "custom")
_USAGE_PAGE_SIZE = 20


def _usage_period(request):
    """Период из query -> (start, end, label, code) или (None, error).

    period=month/prev/7d/30d/90d — пресеты как в ТГ; period=custom или
    явные start/end без period — свой диапазон YYYY-MM-DD; пусто —
    текущий месяц (как раньше)."""
    code = (request.query.get("period") or "").strip()
    start = (request.query.get("start") or "").strip()
    end = (request.query.get("end") or "").strip()
    if code and code not in _USAGE_PERIODS:
        return None, _json_error("bad_period", 400)
    if code == "custom" or (not code and (start or end)):
        if not start or not end:
            return None, _json_error("bad_range", 400)
        try:
            d0 = datetime.strptime(start, "%Y-%m-%d").date()
            d1 = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            return None, _json_error("bad_date", 400)
        if d0 > d1:
            return None, _json_error("bad_range", 400)
        return (start, end, rw_mod._period_label(start, end),
                "custom"), None
    ctx = SimpleNamespace(user_data={"rw_usage_period": code or "month"})
    start, end, label, code = rw_mod.resolve_usage_period(ctx)
    return (start, end, label, code), None


def _panel_tg_id(panel_username: str):
    """TG ID, зашитый в имя панели — та же регулярка, что в ТГ
    (_panel_tg_id в services/remnawave.py)."""
    m = re.match(r"^(?:paid_)?(\d+)(?:_|$)", panel_username or "")
    return int(m.group(1)) if m else None


async def _usage_labels(panel_usernames: list) -> dict:
    """Имя панели -> {name, tg_username, tg_id, expire, in_db}.

    Та же трёхпутевая привязка к базе, что _resolve_usage_labels в ТГ:
    email подписки равен имени панели; TG ID из самого имени; имя панели
    как @username. Не нашёлся нигде — in_db False, чтобы такие клиенты
    были видны, а не молча терялись."""
    labels = {u: {"username": u, "name": None, "tg_username": None,
                  "tg_id": None, "expire": None, "in_db": False}
              for u in panel_usernames}
    if not panel_usernames:
        return labels
    try:
        import core.database as db
    except Exception:
        return labels
    try:
        by_email = await db.users_by_emails(list(panel_usernames))
    except Exception:
        by_email = {}
    resolved = {}
    parsed_ids = {}
    for un in panel_usernames:
        if un in by_email:
            tg_id, fn, db_un = by_email[un]
            resolved[un] = (tg_id, fn, db_un)
        else:
            tg_id = _panel_tg_id(un)
            if tg_id:
                parsed_ids[un] = tg_id
            else:
                try:
                    row = await db.find_user_by_username(un)
                except Exception:
                    row = None
                if row:
                    resolved[un] = (row[0], row[1], row[2])
    tg_ids = [tg for tg, _, _ in resolved.values() if tg]
    tg_ids += list(parsed_ids.values())
    try:
        by_id = await db.users_by_ids(tg_ids) if tg_ids else {}
    except Exception:
        by_id = {}
    try:
        subs = await db.subs_by_tg_ids(tg_ids) if tg_ids else {}
    except Exception:
        subs = {}
    for un in panel_usernames:
        if un in resolved:
            tg_id, fn, db_un = resolved[un]
        elif un in parsed_ids:
            tg_id = parsed_ids[un]
            fn, db_un = by_id.get(tg_id, (None, None))
        else:
            continue
        if tg_id is None:
            continue
        sub = subs.get(tg_id) or {}
        labels[un] = {"username": un, "name": fn, "tg_username": db_un,
                      "tg_id": tg_id, "expire": sub.get("expire"),
                      "in_db": True}
    return labels


def _usage_page(items, page):
    """Пагинация как в ТГ (_PAGE_SIZE=20): (страница, всего страниц)."""
    total_pages = max(1, (len(items) + _USAGE_PAGE_SIZE - 1)
                      // _USAGE_PAGE_SIZE)
    page = min(max(1, page), total_pages)
    start = (page - 1) * _USAGE_PAGE_SIZE
    return items[start:start + _USAGE_PAGE_SIZE], page, total_pages


async def _usage_response(node, period, items, page):
    """Общий ответ трафика: итог + страница с подписями."""
    start, end, label, code = period
    total_bytes = sum(total for _, total in items)
    page_items, page, total_pages = _usage_page(items, page)
    labels = await _usage_labels([u for u, _ in page_items])
    return {
        "ok": True, "node": node, "start": start, "end": end,
        "period": label, "code": code,
        "total_bytes": total_bytes, "users": len(items),
        "page": page, "total_pages": total_pages,
        "items": [{"username": u, "bytes": b, "label": labels[u]}
                  for u, b in page_items],
    }


def _usage_panel_failed(node, period, error):
    """Панель не ответила: ok False, а не 500 — как panel_view."""
    start, end, label, code = period
    return web.json_response({
        "ok": False, "node": node, "start": start, "end": end,
        "period": label, "code": code, "error": "panel_failed",
        "detail": str(error)[:300] if error else "",
    })


async def node_users(request):
    """Трафик одной ноды за период — как экран «Трафик» в ТГ."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    node_id = request.match_info.get("node_id") or ""
    period, err = _usage_period(request)
    if err is not None:
        return err
    start, end, _label, _code = period
    try:
        res = await rw_mod.node_users_usage(node_id, start, end)
    except Exception as ex:
        logging.error("админка: node_users_usage: %s", ex)
        res = {"ok": False, "error": "panel_failed"}
    if not res.get("ok"):
        return _usage_panel_failed(node_id, period, res.get("error"))
    items = rw_mod._usage_items(res.get("data"))
    return web.json_response(await _usage_response(
        node_id, period, items, _int_query(request, "page", 1)))


async def nodes_usage(request):
    """Трафик суммарно по всем узлам за период — «Все ноды» в ТГ."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    period, err = _usage_period(request)
    if err is not None:
        return err
    start, end, _label, _code = period
    try:
        nodes_res = await rw_mod.nodes()
    except Exception as ex:
        logging.error("админка: nodes_usage nodes: %s", ex)
        nodes_res = {"ok": False, "error": "panel_failed"}
    if not nodes_res.get("ok"):
        return _usage_panel_failed("all", period, nodes_res.get("error"))
    parsed = rw_mod._parse_nodes(nodes_res.get("data"))
    if not parsed:
        return web.json_response(await _usage_response(
            "all", period, [], _int_query(request, "page", 1)))
    try:
        res = await rw_mod.nodes_users_usage(
            [n["uuid"] for n in parsed], start, end)
    except Exception as ex:
        logging.error("админка: nodes_users_usage: %s", ex)
        res = {"ok": False, "error": "panel_failed"}
    if not res.get("ok"):
        return _usage_panel_failed("all", period, res.get("error"))
    items = rw_mod._usage_items(res.get("data"))
    return web.json_response(await _usage_response(
        "all", period, items, _int_query(request, "page", 1)))


async def usage_snapshot(request):
    """Сводка за всё время: счётчики панели с последнего сброса + топ-10 —
    тот же блок, что в начале экрана «Трафик» в ТГ."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    try:
        snap = await panel_mod.get_traffic_snapshot()
    except Exception as ex:
        logging.error("админка: traffic_snapshot: %s", ex)
        snap = {}
    clients = (snap or {}).get("clients") or {}
    total = sum(up + down for up, down in clients.values())
    top = sorted(clients.items(),
                 key=lambda kv: kv[1][0] + kv[1][1], reverse=True)[:10]
    labels = await _usage_labels([e for e, _ in top])
    return web.json_response({
        "ok": True,
        "snapshot_ok": bool((snap or {}).get("ok")) and bool(clients),
        "total_bytes": total, "users": len(clients),
        "items": [{"username": e, "bytes": up + down, "label": labels[e]}
                  for e, (up, down) in top],
    })


# ── Синхронизация с панелью ──────────────────────────────────────────────────

# Тексты статусов сайта — те же, что в services/remnawave.py
# full_sync_report_text (секция «Сайт и кабинет»).
_SYNC_SITE_TEXT = {
    "unchanged": "Актуален, изменений нет — деплой не понадобился.",
    "deployed": "Обновлён: залита свежая версия.",
    "not_deployed": "Ещё ни разу не развёрнут — пропускаю (деплой делается вручную).",
    "not_configured": "Не настроен — пропускаю.",
    "no_bot": "Пропущено: нет доступа к боту.",
}


def _full_sync_steps(res: dict) -> list:
    """Структурированный отчёт полной синхронизации: те же 8 секций,
    что services/remnawave.full_sync_report_text, но машиночитаемо —
    фронт рисует по шагам вместо сырого JSON-дампа. Каждый шаг:
    {key, title, status: ok|fail|skip, summary, lines[]}.
    Значения и тексты — те же, что в тексте отчёта ТГ."""
    steps = []

    # 1) панель → бот: подписки (поля панели в базу)
    p = res.get("panel") or {}
    if p.get("ok"):
        lines = [
            f"Пользователей в панели: {p.get('panel_total', 0)}",
            f"Сверено подписок: {p.get('checked', 0)}",
            f"Обновлено подписок: {p.get('updated_subs', 0)} "
            f"(полей: {p.get('updated_fields', 0)})",
        ]
        if p.get("disabled"):
            lines.append(f"В панели отключено подписок: {p['disabled']} "
                         "(статусы в базе не трогаем)")
        for label, key in (("Что поменялось", "examples"),
                           ("В панели есть, а в базе нет", "orphans"),
                           ("В базе есть, а в панели нет", "missing")):
            items = p.get(key) or []
            if items:
                lines.append(f"{label}: {len(items)}")
                lines.extend(str(e)[:120] for e in items[:5])
                if len(items) > 5:
                    lines.append(f"…и ещё {len(items) - 5}")
        steps.append({"key": "panel", "title": "🔄 Подписки (панель → бот)",
                      "status": "ok",
                      "summary": f"Сверено {p.get('checked', 0)}, "
                                 f"обновлено {p.get('updated_subs', 0)}",
                      "lines": lines})
    else:
        steps.append({"key": "panel", "title": "🔄 Подписки (панель → бот)",
                      "status": "fail",
                      "summary": "Панель недоступна",
                      "lines": [str(p.get("error") or "ошибка")[:300],
                                "База не менялась: при ошибке панели "
                                "ничего не трогаем."]})

    # 2) бот → панель: ники и юзернеймы в описания клиентов
    names = res.get("names")
    if names is None:
        steps.append({"key": "names", "title": "👤 Ники и юзернеймы",
                      "status": "skip",
                      "summary": "Пропущено: панель недоступна",
                      "lines": []})
    elif names.get("ok"):
        errs = names.get("errors") or []
        lines = [f"Проверено подписок: {names.get('checked', 0)}",
                 f"Обновлено описаний: {names.get('updated', 0)}",
                 f"С ошибкой: {len(errs)}"]
        lines.extend(str(e)[:120] for e in errs[:5])
        if len(errs) > 5:
            lines.append(f"…и ещё {len(errs) - 5}")
        steps.append({"key": "names", "title": "👤 Ники и юзернеймы",
                      "status": "ok",
                      "summary": f"Обновлено описаний: {names.get('updated', 0)}",
                      "lines": lines})
    else:
        steps.append({"key": "names", "title": "👤 Ники и юзернеймы",
                      "status": "fail",
                      "summary": "Не удалось обновить ники",
                      "lines": [str(names.get("error") or "ошибка")[:300]]})

    # 3) ресурсы: панель, выдача подписок и все узлы — живы ли
    probe = res.get("probe") or {}
    if probe.get("error"):
        steps.append({"key": "probe", "title": "🖥 Ресурсы и узлы",
                      "status": "fail",
                      "summary": "Проверка не удалась",
                      "lines": [str(probe["error"])[:300]]})
    else:
        panel_p = probe.get("panel") or {}
        sub = probe.get("sub") or {}
        nodes = probe.get("nodes") or []
        lines = [
            f"Панель: {'отвечает' if panel_p.get('ok') else 'недоступна'}"
            f" · {panel_p.get('ms', '—')} мс",
            f"Выдача подписок: {'отвечает' if sub.get('ok') else 'недоступна'}"
            f" · {sub.get('ms', '—')} мс",
        ]
        if nodes:
            for n in nodes:
                if not n.get("enabled"):
                    state = "выключен"
                elif n.get("reachable"):
                    state = "онлайн"
                else:
                    state = str(n.get("error") or "недоступен")
                lines.append(f"{n.get('tag')}: {state} · {n.get('host') or ''}"
                             f" · онлайн-клиентов: {n.get('clients', 0)}")
        else:
            lines.append("Узлов панель не отдала.")
        steps.append({"key": "probe", "title": "🖥 Ресурсы и узлы",
                      "status": "ok",
                      "summary": f"Панель {'отвечает' if panel_p.get('ok') else 'недоступна'}, "
                                 f"узлов: {len(nodes)}",
                      "lines": lines})

    # 4) хосты панели: состав, отключённые, скрытые
    hosts = res.get("hosts") or {}
    if hosts.get("ok"):
        hs = hosts.get("hosts") or []
        off = [h for h in hs if h.get("isDisabled")]
        hidden = [h for h in hs if h.get("isHidden")]
        lines = [f"Всего: {len(hs)} · отключено: {len(off)}"
                 f" · скрыто: {len(hidden)}"]
        if off:
            lines.append("Отключены: " + ", ".join(
                str(h.get("remark") or h.get("address") or "?")
                for h in off[:10]))
        steps.append({"key": "hosts", "title": "🌐 Хосты в панели",
                      "status": "ok",
                      "summary": f"Всего {len(hs)}, отключено {len(off)}, "
                                 f"скрыто {len(hidden)}",
                      "lines": lines})
    else:
        steps.append({"key": "hosts", "title": "🌐 Хосты в панели",
                      "status": "fail",
                      "summary": "Не получить",
                      "lines": [str(hosts.get("error") or "ошибка")[:300]]})

    # 5) сквады: выбранные в боте против живых в панели
    squads = res.get("squads") or {}
    if squads.get("ok"):
        missing = squads.get("missing") or []
        lines = [f"В панели: {len(squads.get('squads') or [])} · "
                 f"выбрано для выдачи: {squads.get('chosen', 0)}"]
        if missing:
            lines.append(f"⚠️ Выбранных в панели больше нет: {len(missing)}"
                         " — проверь сквады в Remnawave.")
        steps.append({"key": "squads", "title": "👥 Сквады",
                      "status": "ok",
                      "summary": f"В панели {len(squads.get('squads') or [])}, "
                                 f"выбрано {squads.get('chosen', 0)}",
                      "lines": lines})
    else:
        steps.append({"key": "squads", "title": "👥 Сквады",
                      "status": "fail",
                      "summary": "Не получить",
                      "lines": [str(squads.get("error") or "ошибка")[:300]]})

    # 6) сайт: пересборка и деплой, если что-то поменялось
    site = res.get("site") or {}
    st = site.get("status")
    if st in ("unchanged", "deployed"):
        site_status, site_summary = "ok", _SYNC_SITE_TEXT[st]
    elif st in ("not_configured", "not_deployed", "no_bot"):
        site_status, site_summary = "skip", _SYNC_SITE_TEXT[st]
    else:
        site_status = "fail"
        site_summary = ("Не удалось: "
                        + str(site.get("error") or st or "ошибка")[:300])
    steps.append({"key": "site", "title": "🌍 Сайт и кабинет",
                  "status": site_status, "summary": site_summary,
                  "lines": []})

    # 7) общий чёрный список: скачать и применить (если включён)
    bl = res.get("blacklist") or {}
    if bl.get("status") == "off":
        steps.append({"key": "blacklist", "title": "🚫 Чёрный список",
                      "status": "skip",
                      "summary": "Общий список выключен — пропускаю",
                      "lines": []})
    elif bl.get("status") == "no_bot":
        steps.append({"key": "blacklist", "title": "🚫 Чёрный список",
                      "status": "skip",
                      "summary": "Пропущено: нет доступа к боту",
                      "lines": []})
    elif bl.get("ok"):
        stopped = (len(bl.get("trials_stopped") or [])
                   + len(bl.get("paid_stopped") or [])
                   + len(bl.get("admin_stopped") or []))
        steps.append({"key": "blacklist", "title": "🚫 Чёрный список",
                      "status": "ok",
                      "summary": f"Записей в списке: {bl.get('total', 0)}, "
                                 f"добавлено {bl.get('added', 0)}, "
                                 f"снято {bl.get('removed', 0)}",
                      "lines": [f"Записей в списке: {bl.get('total', 0)}",
                                f"Добавлено: {bl.get('added', 0)}",
                                f"Снято: {bl.get('removed', 0)}",
                                f"Остановлено подписок: {stopped}",
                                f"Восстановлено: "
                                f"{len(bl.get('restored') or [])}"]})
    else:
        steps.append({"key": "blacklist", "title": "🚫 Чёрный список",
                      "status": "fail",
                      "summary": "Не удалось",
                      "lines": [str(bl.get("error") or "ошибка")[:300]]})

    # 8) сверка Platega: только отчёт, исправления — отдельной кнопкой
    rec = res.get("reconcile") or {}
    if rec.get("error"):
        steps.append({"key": "reconcile", "title": "🔍 Сверка с Platega",
                      "status": "fail",
                      "summary": "Не удалось",
                      "lines": [str(rec["error"])[:300]]})
    else:
        issues = rec.get("issues") or []
        lines = [f"Проверено счетов: {rec.get('checked', 0)}",
                 f"Расхождений: {len(issues)}"]
        if issues:
            lines.append("Исправления отсюда не применяются — они в "
                         "разделе сверки, по кнопке.")
        steps.append({"key": "reconcile", "title": "🔍 Сверка с Platega",
                      "status": "ok",
                      "summary": f"Проверено счетов: {rec.get('checked', 0)}, "
                                 f"расхождений: {len(issues)}",
                      "lines": lines})

    return steps


async def panel_sync_run(request):
    """Полная синхронизация одной кнопкой: подписки, ники, узлы, хосты,
    сквады, сайт, чёрный список, сверка Platega (та же, что в ТГ-боте)."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    res = await rw_mod.run_full_sync(get_bot())
    panel = res.get("panel") or {}
    await _audit(actor, "panel_sync",
                 f"ok={bool(panel.get('ok'))} checked={panel.get('checked', 0)} "
                 f"updated={panel.get('updated_subs', 0)} "
                 f"names={(res.get('names') or {}).get('updated', 0)}")
    return web.json_response({
        "ok": bool(panel.get("ok")),
        "report": rw_mod.full_sync_report_text(res),
        "steps": _full_sync_steps(res),
    })


async def _names_sync_run(tables):
    """Актуализация ников и юзернеймов в панели — тот же
    refresh_panel_descriptions, что в ТГ handle_panel_names_sync:
    живая проверка каждого человека в Telegram (getChat по TG ID),
    свежие юзернейм и ник пишутся в описание клиента панели.
    Возвращает (status, payload): 409 panel_not_configured без
    адреса/токена панели (как в ТГ — «Сначала задай адрес панели
    и токен»), 503 no_bot без бота (живая проверка обязательна),
    502 panel_failed при исключении сервиса."""
    if not rw_mod.is_configured():
        return 409, {"error": "panel_not_configured"}
    bot = get_bot()
    if bot is None:
        return 503, {"error": "no_bot"}
    try:
        resolver = await panel_mod.tg_chat_resolver(bot)
        res = await panel_mod.refresh_panel_descriptions(
            tables, resolve_chat=resolver)
    except Exception:
        logging.exception("panel names-sync failed")
        return 502, {"error": "panel_failed"}
    return 200, {"ok": True, "checked": res["checked"],
                 "updated": res["updated"],
                 "errors": res.get("errors") or [],
                 "by_table": res.get("by_table") or {}}


async def panel_names_sync(request):
    """«👤 Только ники и юзернеймы» — паритет с ТГ
    (handle_panel_names_sync): платные + админские подписки,
    без запуска полной синхронизации."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    status, payload = await _names_sync_run(("paid_subs", "admin_subs"))
    if status != 200:
        return web.json_response(payload, status=status)
    await _audit(actor, "panel_names_sync",
                 f"checked={payload['checked']} "
                 f"updated={payload['updated']} "
                 f"errors={len(payload['errors'])}")
    return web.json_response(payload)


def _panel_sync_settings_snapshot() -> dict:
    """Только последний запуск и отчёт: расписания у синхронизации нет,
    она запускается вручную (решение владельца 2026-11-19)."""
    from config import load_config
    cfg = load_config()
    return {
        "last_run": cfg.get("panel_sync_last_run"),
        "last_report": cfg.get("panel_sync_last_report") or {},
    }


async def panel_sync_settings_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response({"settings": _panel_sync_settings_snapshot()})


# ── Теги подписчиков в панели ────────────────────────────────────────────────

async def panel_tags_get(request):
    """Счётчики тегов подписчиков — по данным бота, без запросов в панель.
    Только чтение. Паритет с «🏷 Теги подписчиков» в ТГ-меню Remnawave."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    try:
        counts = await tags_mod.tag_counters()
    except Exception as ex:
        logging.error("админка: panel_tags_get: %s", ex)
        return _json_error("tags_failed", 502)
    return web.json_response({"counts": counts, "labels": tags_mod.TAG_LABELS})


async def panel_tags_apply(request):
    """Применить теги всем подписчикам (как «🏷 Применить ко всем» в ТГ).
    Только Mark, с подтверждением: массовая правка клиентов панели."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        return confirm_needed_response(
            issue_confirm(actor, "panel_tags_apply", {},
                          "Применить теги всем подписчикам в панели?"),
            "Применить теги всем подписчикам в панели?")
    payload = take_confirm(actor, token, "panel_tags_apply")
    if payload is None:
        return _json_error("bad_confirm", 403)
    try:
        res = await tags_mod.apply_all_tags()
    except Exception as ex:
        logging.error("админка: panel_tags_apply: %s", ex)
        return _json_error("tags_failed", 502)
    report = dict(res)
    report["error_samples"] = [_scrub(str(s))
                               for s in (res.get("error_samples") or [])]
    await _audit(actor, "panel_tags_apply",
                 f"people={res.get('people', 0)} "
                 f"updated={res.get('updated', 0)} "
                 f"errors={res.get('errors', 0)}")
    return web.json_response({"ok": True, "report": report})


# ── Логи ─────────────────────────────────────────────────────────────────────

# Человеческие подписи действий веб-админки (в журнале они admin:<имя>)
_ADMIN_LABELS = {
    "login": "🔐 Вход в веб-админку", "logout": "🚪 Выход из веб-админки",
    "admin_sub_create": "🆕 Создал админскую подписку",
    "paid_sub_create": "➕ Создал платную подписку",
    "backup_export": "📤 Выгрузка бэкапа", "backup_restore": "♻️ Восстановление из бэкапа",
    "backup_inspect": "🔍 Проверил архив бэкапа",
    "backup_restore_failed": "⚠️ Восстановление из бэкапа не удалось",
    "blacklist_add": "⛔ Внёс в чёрный список", "blacklist_readd": "⛔ Вернул в чёрный список",
    "blacklist_remove": "✅ Убрал из чёрного списка", "blacklist_sync": "🔄 Обновил общий чёрный список",
    "blacklist_remote_toggle": "🌐 Общий чёрный список вкл/выкл",
    "blacklist_stop": "⛔ ЧС: стоп триала",
    "broadcast_photo_upload": "🖼 Загрузил фото рассылки",
    "broadcast_send": "📣 Отправил рассылку",
    "channel_photo_upload": "🖼 Загрузил фото для поста в канал",
    "channel_post_send": "📣 Опубликовал пост в канале",
    "channel_signature": "✒️ Подпись к постам в канал",
    "connect_help_update": "❓ Обновил помощь при подключении",
    "fraud_scan": "🕵 Ручная проверка антифрода", "fraud_stop": "🚫 Закрыл триал за повтор",
    "fraud_toggle": "🕵 Слежка за повторными триалами вкл/выкл",
    "fraud_ip_toggle": "🕵 Адрес как улика антифрода вкл/выкл",
    "fraud_ignore": "🙈 Находка антифрода — не фрод",
    "fraud_recheck": "🕵 Перепроверил пару антифрода",
    "git_update": "⬆️ Обновление с GitHub", "git_update_failed": "⚠️ Обновление с GitHub не удалось",
    "helpers_add": "👥 Добавил помощника", "helpers_delete": "👥 Удалил помощника",
    "helper_invite": "📩 Приглашение в группу поддержки",
    "helpers_perm": "👥 Сменил права помощника",
    "jobs_run_now": "▶️ Запустил фоновую задачу", "jobs_run_now_failed": "⚠️ Фоновая задача упала",
    "logs_purge": "🧹 Очистил старые логи", "logs_retention": "🗄 Срок хранения журналов", "lte_check_now": "📶 Ручная проверка LTE",
    "subs_squads_issued": "🗂 Выдаваемые сквады: переключил", "subs_squads_lte": "📡 Сквад LTE: переключил",
    "subs_squads_fallback": "🔀 Сквад после конца LTE: выбрал",
    "morning_run_now": "🌅 Запустил утреннюю сводку", "morning_update": "🌅 Настройки утренней сводки",
    "maintenance_feature": "🛠 Функция вкл/выкл", "maintenance_text": "🛠 Текст техработ",
    "maintenance_toggle": "🛠 Техработы вкл/выкл",
    "muse_account_create": "👤 Создал Muse-аккаунт", "muse_account_direct": "👤 Muse-аккаунт напрямую",
    "netcheck_run": "📡 Запустил проверку операторов",
    "panel_host_create": "➕ Создал хост в панели", "panel_host_delete": "🗑 Удалил хост в панели",
    "panel_host_edit": "✏️ Изменил хост в панели",
    "panel_profile_inbound_edit": "✏️ Изменил инбаунд профиля",
    "panel_settings": "⚙️ Настройки панели", "panel_settings_test": "🔌 Проверка панели",
    "links_update": "🔗 Основные ссылки",
    "panel_sync": "🔄 Синхронизация с панелью", "panel_sync_settings": "🔄 Настройки синхронизации",
    "panel_names_sync": "👤 Ники и юзернеймы в панели", "admin_subs_names_sync": "👤 Ники админских в панели",
    "panel_tags_apply": "🏷 Применил теги всем",
    "payment_refund": "💸 Оформил возврат", "platega_update": "💳 Настройки Platega",
    "promo_batch": "🎁 Пакетная раздача промокодов", "promo_create": "🎁 Создал промокод",
    "promo_delete": "🗑 Удалил промокод", "promo_toggle": "🎁 Вкл/выкл промокода",
    "promo_update": "🎁 Изменил промокод",
    "promo_give": "🎁 Выдал промокод", "promo_seg": "📤 Раздал промокоды сегменту",
    "promo_clean": "🧹 Убрал мёртвые промокоды",
    "reconcile_fix": "🧾 Исправил расхождения сверки", "reconcile_run": "🧾 Запустил сверку",
    "remind_test": "📨 Пример напоминания", "retention_update": "🔔 Настройки напоминаний и возврата",
    "server_create": "➕ Добавил сервер в расходы", "server_delete": "🗑 Удалил сервер из расходов",
    "server_mark": "✅ Отметил оплату сервера", "server_update": "✏️ Изменил сервер в расходах",
    "settings_update": "⚙️ Изменил настройки",
    "site_delete": "🗑 Удалил сайт", "site_delete_failed": "⚠️ Удаление сайта не удалось",
    "site_deploy": "🚀 Развернул сайт", "site_deploy_failed": "⚠️ Деплой сайта не удался",
    "site_texts": "📝 Тексты сайта",
    "site_texts_reset": "🔄 Сбросил все тексты сайта",
    "subs_presets_update": "⚙️ Пресеты подписок",
    "admin_subs_presets_update": "⚙️ Пресеты админских подписок",
    "support_close": "💬 Закрыл обращение", "support_reply": "💬 Ответил в поддержке",
    "support_settings": "💬 Настройки поддержки",
    "support_token": "🤖 Токен бота поддержки",
    "tariff_create": "🏷 Создал тариф", "tariff_delete": "🗑 Удалил тариф",
    "tariff_update": "🏷 Изменил тариф",
    "user_dm": "✉️ Написал пользователю", "user_gift": "🎁 Подарил подписку",
    "web_access_update": "🌐 Настройки веб-доступа",
    "sub_extend": "⏩ Продлил подписку", "sub_reduce": "➖ Убавил срок подписки",
    "sub_expire": "📅 Установил дату подписки",
    "sub_delete": "🗑 Удалил подписку", "sub_reissue": "🔁 Перевыпустил ключ",
    "sub_freeze": "❄️ Заморозил/разморозил подписку",
    "sub_toggle": "🔀 Вкл/выкл подписки",
    "sub_hwid": "📱 Изменил устройства подписки",
    "sub_traffic": "📊 Изменил трафик подписки", "sub_lte": "📶 Изменил LTE подписки",
    "sub_trial": "🎁 Изменил триал подписки",
    "sub_topic": "💬 Открыл тему поддержки",
    "subs_bulk_extend": "📦 Массовый сдвиг сроков", "subs_bulk_limits": "📦 Массовые лимиты",
    "subs_bulk_lte": "📦 Массовый LTE",
    "winback_test": "🎯 Пример письма возврата",
}


def _action_label_text(action: str, details: str) -> str:
    """Подпись действия для веб-журнала: admin:* — по словарю выше,
    остальные (cb:/cmd:/msg:/ev:) — тем же action_label, что и ТГ-журнал,
    только без HTML-разметки."""
    if (action or "").startswith("admin:"):
        name = action[len("admin:"):]
        return _ADMIN_LABELS.get(name, "⚙️ Админ: " + name.replace("_", " "))
    try:
        import html as _html
        import re as _re
        from handlers.control import action_label
        text = action_label(action, details)
        return _html.unescape(_re.sub(r"<[^>]+>", "", text)).strip() or action
    except Exception:
        return action or ""


def _activity_row(row) -> dict:
    details = _scrub(str(row[3] or ""))
    return {"id": row[0], "tg_id": row[1], "action": row[2],
            "label": _action_label_text(row[2], details),
            "details": details, "time": str(row[4] or ""),
            "first_name": row[5] or "", "username": row[6] or ""}


def _error_row(row) -> dict:
    return {"id": row[0], "source": row[1], "level": row[2],
            "message": _scrub(str(row[3] or "")),
            "details": _scrub(str(row[4] or "")), "time": str(row[5] or ""),
            "tg_id": row[6]}


# Области ленты — те же 6 вкладок, что FEED_TITLES в handlers/control.py
# («Ошибки» — отдельный kind, а не scope). Виды действий — LOG_KIND_LABELS там же.
LOG_SCOPES = ("all", "important", "admin", "helpers", "subs")
LOG_KINDS = ("cb", "cmd", "msg", "ev")


def _is_date(value: str) -> bool:
    try:
        from datetime import date as _date
        _date.fromisoformat(value)
        return len(value) == 10
    except ValueError:
        return False


def _logs_filters(request):
    """Валидация фильтров ленты. Возвращает (params, error_response):
    params — scope/filter_kind/user_id/date_from/date_to."""
    scope = request.query.get("scope") or "all"
    if scope not in LOG_SCOPES:
        return None, _json_error("bad_scope", 400)
    filter_kind = request.query.get("filter_kind") or None
    if filter_kind is not None and filter_kind not in LOG_KINDS:
        return None, _json_error("bad_kind", 400)
    user_raw = request.query.get("user_id") or None
    user_id = None
    if user_raw is not None:
        try:
            user_id = int(user_raw)
        except (TypeError, ValueError):
            return None, _json_error("bad_user", 400)
    date_from = request.query.get("date_from") or None
    date_to = request.query.get("date_to") or None
    for d in (date_from, date_to):
        if d is not None and not _is_date(d):
            return None, _json_error("bad_date", 400)
    return {"scope": scope, "filter_kind": filter_kind, "user_id": user_id,
            "date_from": date_from, "date_to": date_to}, None


def _history_row(row) -> dict:
    """Строка истории подписок: та же форма, что _activity_row, подпись —
    HIST_LABELS, как в ТГ-ленте _subs_feed."""
    details = _scrub(str(row[3] or ""))
    try:
        from handlers.control import HIST_LABELS
        label = HIST_LABELS.get(row[2]) or ("• " + str(row[2] or ""))
    except Exception:
        label = str(row[2] or "")
    return {"id": row[0], "tg_id": row[1], "action": row[2],
            "label": label, "details": details, "time": str(row[4] or ""),
            "first_name": row[5] or "", "username": row[6] or ""}


async def logs_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from core.database import list_activity, list_errors
    kind = request.query.get("kind") or "activity"
    page = max(1, _int_query(request, "page", 1))
    per_page = min(100, max(1, _int_query(request, "per_page", 15)))
    if kind == "errors":
        rows, pages = await list_errors(page, per_page)
        return web.json_response({"kind": "errors", "scope": "errors",
                                  "page": page, "pages": pages,
                                  "rows": [_error_row(r) for r in rows]})
    if kind != "activity":
        return _json_error("bad_kind", 400)
    params, err = _logs_filters(request)
    if err is not None:
        return err
    scope = params["scope"]
    if scope == "subs":
        # Как в ТГ-ленте: на вкладке подписок фильтры человека/вида/дат
        # не действуют — история подписок живёт отдельно от activity_log.
        from paidsub.storage import list_history
        rows, pages = await list_history(page, per_page)
        return web.json_response({"kind": "activity", "scope": "subs",
                                  "page": page, "pages": pages,
                                  "rows": [_history_row(r) for r in rows]})
    if scope == "all":
        # list_activity("all") отдаёт только не-админские строки, а
        # scope="admin" — только админские: «все» — это их слияние.
        rows_a, _ = await list_activity(
            "admin", 1, 5000, user_id=params["user_id"],
            kind=params["filter_kind"],
            date_from=params["date_from"], date_to=params["date_to"])
        rows_b, _ = await list_activity(
            "all", 1, 5000, user_id=params["user_id"],
            kind=params["filter_kind"],
            date_from=params["date_from"], date_to=params["date_to"])
        merged = sorted(rows_a + rows_b, key=lambda r: r[0], reverse=True)
        total = len(merged)
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        rows = merged[(page - 1) * per_page: page * per_page]
        return web.json_response({"kind": "activity", "scope": "all",
                                  "page": page, "pages": pages,
                                  "rows": [_activity_row(r) for r in rows]})
    rows, pages = await list_activity(
        scope, page, per_page, user_id=params["user_id"],
        kind=params["filter_kind"],
        date_from=params["date_from"], date_to=params["date_to"])
    return web.json_response({"kind": "activity", "scope": scope,
                              "page": page, "pages": pages,
                              "rows": [_activity_row(r) for r in rows]})


async def logs_export(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from datetime import date
    from core.database import list_activity, list_errors
    from handlers.control import EXPORT_MAX_ROWS, _export_rows_to_csv
    kind = request.query.get("kind") or "activity"
    today = date.today().isoformat()
    if kind == "errors":
        rows, _pages = await list_errors(1, EXPORT_MAX_ROWS)
        blob = _export_rows_to_csv(rows, "errors")
        fname = f"drebol-logs-errors-{today}.csv"
    elif kind != "activity":
        return _json_error("bad_kind", 400)
    else:
        params, err = _logs_filters(request)
        if err is not None:
            return err
        scope = params["scope"]
        if scope == "subs":
            from paidsub.storage import list_history
            rows, _pages = await list_history(1, EXPORT_MAX_ROWS)
            blob = _export_rows_to_csv(rows, "activity")
            fname = f"drebol-logs-subs-{today}.csv"
        elif scope == "all":
            # Как в logs_get: «все» — слияние админских и обычных строк.
            rows_a, _ = await list_activity(
                "admin", 1, EXPORT_MAX_ROWS, user_id=params["user_id"],
                kind=params["filter_kind"],
                date_from=params["date_from"], date_to=params["date_to"])
            rows_b, _ = await list_activity(
                "all", 1, EXPORT_MAX_ROWS, user_id=params["user_id"],
                kind=params["filter_kind"],
                date_from=params["date_from"], date_to=params["date_to"])
            rows = sorted(rows_a + rows_b, key=lambda r: r[0], reverse=True)
            blob = _export_rows_to_csv(rows, "activity")
            fname = f"drebol-logs-activity-{today}.csv"
        else:
            rows, _pages = await list_activity(
                scope, 1, EXPORT_MAX_ROWS, user_id=params["user_id"],
                kind=params["filter_kind"],
                date_from=params["date_from"], date_to=params["date_to"])
            blob = _export_rows_to_csv(rows, "activity")
            fname = f"drebol-logs-{scope}-{today}.csv"
    text = _scrub(blob.decode("utf-8", "replace"))
    return web.Response(
        text=text, content_type="text/csv", charset="utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


async def _logs_entry_id(request):
    """id записи из пути. Возвращает (id, error_response)."""
    try:
        return int(request.match_info.get("entry_id") or ""), None
    except (TypeError, ValueError):
        return None, _json_error("bad_id", 400)


async def logs_activity_entry(request):
    """Подробности записи журнала действий — как /a123 в ТГ-ленте."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    entry_id, err = await _logs_entry_id(request)
    if err is not None:
        return err
    from core.database import get_activity_entry
    row = await get_activity_entry(entry_id)
    if row is None:
        return _json_error("not_found", 404)
    return web.json_response({"kind": "activity", "entry": _activity_row(row)})


async def logs_error_entry(request):
    """Подробности записи журнала ошибок — как /e123 в ТГ-ленте."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    entry_id, err = await _logs_entry_id(request)
    if err is not None:
        return err
    from core.database import get_error_entry
    row = await get_error_entry(entry_id)
    if row is None:
        return _json_error("not_found", 404)
    return web.json_response({"kind": "errors", "entry": _error_row(row)})


async def logs_history_entry(request):
    """Подробности записи истории подписок — как /h123 в ТГ-ленте."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    entry_id, err = await _logs_entry_id(request)
    if err is not None:
        return err
    from paidsub.storage import get_history_entry
    row = await get_history_entry(entry_id)
    if row is None:
        return _json_error("not_found", 404)
    from core.database import get_user_info
    u = await get_user_info(row[1]) if row[1] else None
    full = (row[0], row[1], row[2], row[3], row[4],
            u[1] if u else None, u[2] if u else None)
    return web.json_response({"kind": "activity", "entry": _history_row(full)})


async def logs_purge(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        from config import load_config
        days = int(load_config().get("activity_retention_days", 90) or 90)
        payload = {"days": days}
        return confirm_needed_response(
            issue_confirm(actor, "logs_purge", payload,
                          f"Удалить записи журналов старше {days} дн.?"),
            f"Удалить записи журналов старше {days} дн.?")
    payload = take_confirm(actor, token, "logs_purge")
    if payload is None:
        return _json_error("bad_confirm", 403)
    from core.database import purge_activity, purge_errors
    days = int(payload.get("days") or 90)
    removed_act = await purge_activity(days)
    removed_err = await purge_errors(days)
    await _audit(actor, "logs_purge",
                 f"days={days} activity={removed_act} errors={removed_err}")
    return web.json_response({"ok": True, "removed_activity": removed_act,
                              "removed_errors": removed_err, "days": days})


# ── Хранение журналов ─────────────────────────────────────────────────────────
# Паритет с ТГ: handlers/control.py handle_storage_menu / handle_retention_set.
# Те же сроки хранения (30/90/180/365) и та же статистика из
# core.database.activity_stats; размер базы — тем же human_size, что в бэкапе.
LOG_RETENTION_DAYS = (30, 90, 180, 365)


async def _logs_storage_payload() -> dict:
    from config import load_config
    from core.database import activity_stats
    try:
        days = int(load_config().get("activity_retention_days", 90) or 90)
    except (TypeError, ValueError):
        days = 90
    st = await activity_stats()
    return {
        "days": days,
        "retention_days": list(LOG_RETENTION_DAYS),
        "activity_rows": st["activity_rows"],
        "error_rows": st["error_rows"],
        "oldest_activity": st["oldest_activity"],
        "oldest_error": st["oldest_error"],
        "db_bytes": st["db_bytes"],
        "db_size_human": backup_mod.human_size(st["db_bytes"]),
    }


async def logs_storage(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response(await _logs_storage_payload())


async def logs_retention(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    days = body.get("days")
    if (isinstance(days, bool) or not isinstance(days, int)
            or days not in LOG_RETENTION_DAYS):
        return _json_error("bad_days", 400)
    from config import atomic_update

    def _apply(cfg):
        cfg["activity_retention_days"] = days

    atomic_update(_apply)
    await _audit(actor, "logs_retention", f"days={days}")
    payload = await _logs_storage_payload()
    payload["ok"] = True
    return web.json_response(payload)


# ── Утренняя синхронизация ────────────────────────────────────────────────────

async def morning_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response({"morning_sync": morning_mod.get_morning_cfg()})


async def morning_patch(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    patch = body.get("morning_sync") if isinstance(body, dict) else None
    if not isinstance(patch, dict):
        return _json_error("bad_request")
    clean, rejected, errors = validate_settings_patch({"morning_sync": patch})
    if rejected:
        return web.json_response(
            {"error": "forbidden_keys", "keys": sorted(set(rejected))},
            status=403)
    if errors:
        return web.json_response({"error": "bad_value", "details": errors},
                                 status=400)
    sub = clean.get("morning_sync") or {}
    before = morning_mod.get_morning_cfg()
    cfg = morning_mod.save_morning_cfg(sub)
    rescheduled = None
    if (sub.get("time") is not None and sub.get("time") != before.get("time")) \
            or (sub.get("enabled") is not None
                and sub.get("enabled") != before.get("enabled")):
        rescheduled = _reschedule_morning()
    await _audit(actor, "morning_update",
                 "keys: " + ", ".join(sorted(sub.keys())))
    return web.json_response({"ok": True, "morning_sync": cfg,
                              "morning_rescheduled": rescheduled})


async def morning_run_now(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    context = SimpleNamespace(bot=bot, application=_admin_application)
    await morning_mod.morning_sync_job(context)
    await _audit(actor, "morning_run_now", "")
    return web.json_response({"ok": True})


# ── Проверка операторов ──────────────────────────────────────────────────────

async def netcheck_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    domains, operators = netcheck_mod.get_netcheck_selection()
    from config import load_config
    cfg = load_config()
    net_cfg = cfg.get("netcheck") or {}
    import services.globalping as gp
    return web.json_response({
        "domains": [{"label": label, "domain": domain}
                    for label, domain in domains],
        "operators": [{"label": label, "asns": asns}
                      for label, asns in operators],
        "all_domains": [{"label": label, "domain": domain}
                        for label, domain in gp.TARGETS],
        "all_operators": [{"label": label, "asns": asns}
                          for label, asns in gp.OPERATORS],
        "selected_domains": list(net_cfg.get("domains") or []),
        "selected_operators": list(net_cfg.get("operators") or []),
        "netcheck_days": net_cfg.get("netcheck_days"),
        "netcheck_last_run": net_cfg.get("netcheck_last_run"),
    })


async def links_get(request):
    """«Основные ссылки»: авто-значения из конфига + ручные правки.

    Авто: адрес панели — rw_url, сайт — webapi_public, домены подписки —
    константы config (key — origin, sub — CDN). Ручные правки лежат в
    config.main_links и перекрывают авто при показе; пустая строка правки
    означает «использовать авто».
    """
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from config import (SUB_DISPLAY_DOMAIN, SUB_STORED_DOMAIN, load_config)
    cfg = load_config()
    return web.json_response({
        "auto": {
            "panel_url": (cfg.get("rw_url") or "").rstrip("/"),
            "site_url": (cfg.get("webapi_public") or "").rstrip("/"),
            "key_domain": SUB_STORED_DOMAIN,
            "sub_domain": SUB_DISPLAY_DOMAIN,
        },
        "overrides": cfg.get("main_links") or {},
    })


_LINKS_URL_KEYS = ("panel_url", "site_url")
_LINKS_DOMAIN_KEYS = ("key_domain", "sub_domain")


async def links_patch(request):
    """Сохранить ручные правки основных ссылок (config.main_links)."""
    from config import atomic_update
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    clean = {}
    for key in _LINKS_URL_KEYS + _LINKS_DOMAIN_KEYS:
        if key not in body:
            continue
        value = body[key]
        if not isinstance(value, str):
            return _json_error("bad_value")
        value = value.strip().rstrip("/")
        if key in _LINKS_URL_KEYS:
            if value and not value.startswith("https://"):
                return _json_error("bad_url")
        else:
            value = value.replace("https://", "").replace("http://", "")
            if value and ("." not in value or " " in value or "/" in value):
                return _json_error("bad_domain")
        clean[key] = value

    def _apply(cfg):
        cur = dict(cfg.get("main_links") or {})
        cur.update(clean)
        cfg["main_links"] = cur
    atomic_update(_apply)
    await _audit(actor, "links_update", ", ".join(sorted(clean)) or "-")
    return web.json_response({"ok": True, "overrides": clean})


async def netcheck_run(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    domains, operators = netcheck_mod.get_netcheck_selection()
    try:
        results = await gp_mod.check_all(domains, operators)
    except Exception as ex:
        logging.error("админка: netcheck: %s", ex)
        return _json_error("netcheck_failed", 502)
    summary = gp_mod.summarize(results)
    await _audit(actor, "netcheck_run",
                 f"domains={len(results)} ok={summary[0]} blocked={summary[1]}")
    return web.json_response({"ok": True, "results": results,
                              "summary": {"ok": summary[0],
                                          "blocked": summary[1],
                                          "no_probe": summary[2],
                                          "errors": summary[3],
                                          "total": sum(summary)},
                              "by_operator": gp_mod.summarize_operators(results)})


# ── Сайт ─────────────────────────────────────────────────────────────────────

def _site_snapshot() -> dict:
    from config import load_config
    cfg = load_config()
    creds = site_mod.creds()
    return {
        "domain": creds.get("domain") or "",
        "https": bool(creds.get("https")),
        "deployed_at": creds.get("deployed_at") or "",
        "auto": bool(cfg.get("site_auto", True)),
        "texts": cfg.get("site_texts") or {},
        "url": site_mod.site_url(),
        "configured": site_mod.configured(),
        "host": creds.get("host") or "",
        "port": creds.get("port") or 22,
        "user": creds.get("user") or "",
        "password_set": bool(creds.get("password")),
        "update_pending": bool(cfg.get("site_update_pending")),
    }


async def site_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response({"site": _site_snapshot()})


async def site_deploy(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        return confirm_needed_response(
            issue_confirm(actor, "site_deploy", {},
                          "Развернуть сайт на сервере?"),
            "Развернуть сайт на сервере?")
    if take_confirm(actor, token, "site_deploy") is None:
        return _json_error("bad_confirm", 403)
    bot = get_bot()
    username = ""
    try:
        username = getattr(bot, "username", "") or ""
    except Exception:
        username = ""
    try:
        res = await site_mod.deploy(username)
    except Exception as ex:
        logging.error("админка: site deploy: %s", ex)
        return _json_error("deploy_failed", 502)
    if not res.get("ok"):
        # Ошибку деплоя не отдаём как есть: в ней могут быть SSH-детали.
        await _audit(actor, "site_deploy_failed", "")
        return _json_error("deploy_failed", 502)
    await _audit(actor, "site_deploy", "")
    return web.json_response({"ok": True, "site": _site_snapshot()})


async def site_settings_patch(request):
    """Настройки сайта, которые раньше жили только в ТГ: домен, авто-обновление
    и доступ к серверу сайта. Пароль сервера — только владелец (mark):
    это пароль от целого сервера, а не настройка."""
    import re
    from config import atomic_update
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    creds_patch = {}
    if "domain" in body:
        domain = str(body.get("domain") or "").strip().lower()
        if domain and not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", domain):
            return _json_error("bad_domain", 400)
        creds_patch["site_domain"] = domain
    if "host" in body:
        host = str(body.get("host") or "").strip()
        if " " in host or "/" in host:
            return _json_error("bad_host", 400)
        creds_patch["site_host"] = host
    if "port" in body:
        port = body.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return _json_error("bad_port", 400)
        creds_patch["site_port"] = port
    if "user" in body:
        user = str(body.get("user") or "").strip()
        if " " in user:
            return _json_error("bad_user", 400)
        creds_patch["site_user"] = user
    if body.get("password"):
        creds_patch["site_pass"] = str(body["password"])
    if any(k in creds_patch for k in ("site_host", "site_user", "site_pass")):
        mark_err = _mark_only(actor)
        if mark_err is not None:
            return mark_err
    changed = []
    if creds_patch:
        site_mod.save_creds(**creds_patch)
        # пароль в аудит не пишем никогда — только факт смены
        changed += [k for k in creds_patch if k != "site_pass"]
        if "site_pass" in creds_patch:
            changed.append("site_pass(скрыт)")
    if "auto" in body:
        if not isinstance(body["auto"], bool):
            return _json_error("bad_value", 400)

        def _apply_auto(cfg):
            cfg["site_auto"] = body["auto"]
        atomic_update(_apply_auto)
        changed.append("site_auto")
    await _audit(actor, "site_settings_update", "keys: " + ", ".join(changed))
    return web.json_response({"ok": True, "site": _site_snapshot()})


async def site_cert(request):
    """Выпуск HTTPS-сертификата — как в ТГ, с двухшаговым подтверждением."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    token = body.get("confirm_token")
    if not token:
        return confirm_needed_response(
            issue_confirm(actor, "site_cert", {},
                          "Выпустить HTTPS-сертификат для сайта?"),
            "Выпустить HTTPS-сертификат для сайта?")
    if take_confirm(actor, token, "site_cert") is None:
        return _json_error("bad_confirm", 403)
    try:
        res = await site_mod.issue_cert()
    except Exception as ex:
        logging.error("админка: site cert: %s", ex)
        return _json_error("cert_failed", 502)
    if not res.get("ok"):
        await _audit(actor, "site_cert_failed", "")
        return _json_error("cert_failed", 502)
    await _audit(actor, "site_cert", "")
    return web.json_response({"ok": True, "site": _site_snapshot()})


async def site_check(request):
    """Диагностика сайта — та же, что кнопка «Проверить» в ТГ."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    try:
        res = await site_mod.diagnose()
    except Exception as ex:
        logging.error("админка: site diagnose: %s", ex)
        return _json_error("check_failed", 502)
    return web.json_response({"ok": bool(res.get("ok")),
                              "data": res.get("data") or {},
                              "site": _site_snapshot()})


# ── Git update (Mark и Muse) ───────────────────────────────────────────────
# Mark разрешил Muse жать кнопку обновления самому после пуша
# (2026-11-15): _mark_only здесь НЕТ — двухшаговое подтверждение и
# аудит остаются, остальные _mark_only не тронуты.

def run_git_update() -> dict:
    """Тот же путь, что handlers/admin.py handle_git_update: git pull,
    флаг site_update_pending при правках web/assets, рестарт
    support-bot, затем основного бота. stderr git'а наружу не отдаём
    никогда — только общий признак ошибки."""
    from config import INSTALL_DIR, load_config, save_config
    try:
        old_head = subprocess.run(
            ["git", "-C", INSTALL_DIR, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        result = subprocess.run(
            ["git", "-C", INSTALL_DIR, "pull"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"ok": False, "error": "git_failed"}
        site_changed = False
        new_head = subprocess.run(
            ["git", "-C", INSTALL_DIR, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        # Ничего нового не приехало — рестарт не нужен (как в TG-пути).
        up_to_date = bool(
            (old_head and new_head and old_head == new_head)
            or "Already up to date" in (result.stdout or "")
        )
        if up_to_date:
            return {"ok": True, "up_to_date": True, "site_changed": False}
        if old_head and new_head and old_head != new_head:
            diff = subprocess.run(
                ["git", "-C", INSTALL_DIR, "diff", "--name-only",
                 old_head, new_head],
                capture_output=True, text=True, timeout=10,
            )
            site_changed = any(
                p.startswith(("web/", "assets/"))
                for p in diff.stdout.splitlines())
        if site_changed:
            cfg = load_config()
            cfg["site_update_pending"] = True
            save_config(cfg)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git_timeout"}
    except Exception:
        return {"ok": False, "error": "git_failed"}
    subprocess.Popen(
        ["systemctl", "restart", "drebol-support-bot"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.Popen(
        ["systemctl", "restart", "drebol-vpn"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "site_changed": site_changed}


async def git_update(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        return confirm_needed_response(
            issue_confirm(actor, "git_update", {},
                          "Обновить бота с GitHub и перезапустить?"),
            "Обновить бота с GitHub и перезапустить?")
    if take_confirm(actor, token, "git_update") is None:
        return _json_error("bad_confirm", 403)
    res = run_git_update()
    if not res.get("ok"):
        await _audit(actor, "git_update_failed", res.get("error") or "")
        return _json_error(res.get("error") or "git_failed", 502)
    await _audit(actor, "git_update",
                 f"site_changed={bool(res.get('site_changed'))}")
    return web.json_response({"ok": True,
                              "site_changed": bool(res.get("site_changed")),
                              "up_to_date": bool(res.get("up_to_date")),
                              "restart": ("skipped" if res.get("up_to_date")
                                          else "scheduled")})


# ── Бэкап ────────────────────────────────────────────────────────────────────

async def backup_export(request):
    try:
        actor = await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    blob, fname, counts = backup_mod.make_archive()
    await _audit(actor, "backup_export",
                 f"file={fname} users={counts.get('Пользователи', '?')}")
    return web.Response(
        body=blob, content_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


async def backup_info(request):
    """Текущее состояние — как handle_backup_menu в ТГ: счётчики базы
    и размер файла БД, чтобы видеть, что именно уйдёт в архив."""
    try:
        actor = await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    counts = backup_mod.db_counts()
    size = None
    try:
        db_path = backup_mod._db_path()
        if os.path.exists(db_path):
            size = os.path.getsize(db_path)
    except Exception:
        size = None
    return web.json_response({
        "ok": True, "counts": counts,
        "db_size": size,
        "db_size_human": backup_mod.human_size(size) if size is not None else None,
    })


def _inspect_summary(info: dict) -> dict:
    """Содержимое архива — те же поля, что offer_restore в ТГ
    (features/backup.py): счётчики, дата создания, состав, контрольные
    суммы. Секретов здесь нет — только метаданные."""
    meta = info.get("meta") or {}
    return {
        "ok": True,
        "counts": info.get("counts") or {},
        "created_at": meta.get("created_at") or "",
        "has_config": bool(info.get("has_config")),
        "has_env": bool(info.get("has_env")),
        "assets_count": len(info.get("assets") or []),
        "checksum": info.get("checksum") or "none",
    }


async def backup_inspect(request):
    """Предпросмотр архива перед восстановлением — как offer_restore в ТГ.
    Только Mark: это шаг восстановления. Ничего не меняет, архив не
    сохраняется; при битом архиве возвращается та же причина, что даёт
    inspect_archive."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    archive_b64 = str(body.get("archive") or "")
    if not archive_b64:
        return _json_error("no_archive")
    try:
        blob = base64.b64decode(archive_b64, validate=True)
    except Exception:
        return _json_error("bad_archive")
    info = backup_mod.inspect_archive(blob)
    if not info.get("ok"):
        return web.json_response(
            {"error": "bad_archive", "details": str(info.get("error") or "")},
            status=400)
    await _audit(actor, "backup_inspect",
                 f"users={info.get('counts', {}).get('Пользователи', '?')} "
                 f"checksum={info.get('checksum') or 'none'}")
    return web.json_response(_inspect_summary(info))


async def backup_restore(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        if body.get("fresh_backup") is not True:
            return web.json_response(
                {"error": "fresh_backup_required",
                 "hint": "Сначала сделайте свежий бэкап и подтвердите "
                         "fresh_backup=true"},
                status=400)
        archive_b64 = str(body.get("archive") or "")
        if not archive_b64:
            return _json_error("no_archive")
        try:
            blob = base64.b64decode(archive_b64, validate=True)
        except Exception:
            return _json_error("bad_archive")
        info = backup_mod.inspect_archive(blob)
        if not info.get("ok"):
            return web.json_response(
                {"error": "bad_archive",
                 "details": str(info.get("error") or "")}, status=400)
        payload = {"archive_b64": archive_b64}
        return confirm_needed_response(
            issue_confirm(actor, "backup_restore", payload,
                          "Заменить данные бота данными из архива? "
                          "Текущие данные будут заменены."),
            "Заменить данные бота данными из архива?")
    payload = take_confirm(actor, token, "backup_restore")
    if payload is None:
        return _json_error("bad_confirm", 403)
    try:
        blob = base64.b64decode(payload["archive_b64"], validate=True)
    except Exception:
        return _json_error("bad_archive")
    res = backup_mod.apply_archive(blob)
    if not res.get("ok"):
        await _audit(actor, "backup_restore_failed", "")
        return _json_error("restore_failed", 502)
    await _audit(actor, "backup_restore",
                 f"counts={res.get('counts') or {}}")
    # Как в ТГ (features/backup.py _schedule_restart): выходим через 2 с,
    # systemd поднимает бота заново уже с новой базой. Планировщик —
    # через хук _schedule_restart_fn, чтобы тесты могли его подменить.
    try:
        _schedule_restart_fn()
    except Exception as ex:
        logging.error("админка: schedule restart: %s", ex)
        return web.json_response({"ok": True, "restart": "failed",
                                  "counts": res.get("counts") or {}})
    return web.json_response({"ok": True, "restart": "scheduled",
                              "counts": res.get("counts") or {}})


# ── Помощники (только чтение; веб-доступа у них нет) ─────────────────────────

async def helpers_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from core.database import get_user_info
    bot = get_bot()
    out = []
    for uid in staff_mod.helper_ids():
        u = await get_user_info(uid)
        st = (await staff_mod.support_member_status(bot, uid)
              if bot is not None else "unknown")
        out.append({
            "tg_id": uid,
            "first_name": (u[1] if u else "") or "",
            "username": (u[2] if u else "") or "",
            "perms": sorted(staff_mod.helper_perms(uid)),
            "web_access": False,
            "in_group": st,
        })
    return web.json_response({
        "helpers": out,
        "support_group_set": bool(staff_mod.support_group_id()),
    })


async def helpers_invite(request):
    """Приглашение помощника в группу поддержки: одноразовая ссылка от
    бота (он админ группы) + сообщение помощнику в личку."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    try:
        tg_id = int(request.match_info.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    if not tg_id or tg_id not in staff_mod.helper_ids():
        return _json_error("bad_request")
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    invite = await staff_mod.make_support_invite(bot, tg_id)
    if not invite:
        return _json_error("invite_failed", 502)
    sent = False
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        await bot.send_message(
            chat_id=tg_id,
            text=("🛟 <b>Приглашение в группу поддержки Drebol VPN</b>\n\n"
                  "<i>В группе лежат обращения людей. Вступи — и сможешь отвечать "
                  "им прямо в темах: бот поддержки доставит ответ человеку. "
                  "Ссылка одноразовая, только для тебя.</i>"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Вступить в группу поддержки", url=invite)],
            ]))
        sent = True
    except Exception:
        sent = False
    await _audit(actor, "helper_invite", f"tg_id={tg_id} sent={sent}")
    return web.json_response({
        "ok": True, "sent": sent,
        # ссылку показываем админу только если бот не достучался сам
        "invite_link": None if sent else invite,
    })


# ── Чёрный список ────────────────────────────────────────────────────────────

async def blacklist_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from config import load_config
    from core.database import bl_counts, bl_list, bl_stats
    scope = request.query.get("scope") or "manual"
    if scope not in ("manual", "allow", "people"):
        scope = "manual"
    page = max(1, _int_query(request, "page", 1))
    use_remote = bl_mod.remote_on()
    rows, pages = await bl_list(scope, use_remote, page, 10)
    page = min(max(1, page), pages)
    cfg = load_config()
    return web.json_response({
        "scope": scope, "page": page, "pages": pages,
        "counts": await bl_counts(use_remote),
        "stats": await bl_stats(),
        "remote_enabled": use_remote,
        # те же поля, что handle_bl_menu: когда обновлялся общий и доп.
        # списки и чем кончилось последнее обновление
        "synced_at": cfg.get("blacklist_synced_at") or None,
        "extra_synced_at": cfg.get("blacklist_extra_synced_at") or None,
        "last_error": cfg.get("blacklist_last_error") or None,
        "extra_last_error": cfg.get("blacklist_extra_last_error") or None,
        "entries": [{"tg_id": r[0], "first_name": r[1] or "",
                     "username": r[2] or "", "reason": r[3] or "",
                     "source": r[4]} for r in rows],
    })


async def blacklist_entry(request):
    """Карточка записи ЧС — как handle_bl_view в ТГ."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    try:
        tg_id = int(request.match_info.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    if not tg_id:
        return _json_error("bad_id", 400)
    from core.database import (
        bl_history, bl_holds, bl_lookup, bl_times_listed, get_user_info,
    )
    from paidsub.storage import get_paid_sub_by_tg_id
    e = await bl_mod.entry(tg_id)
    info = await bl_lookup(tg_id)
    u = await get_user_info(tg_id)
    holds = {h[1]: h[3] for h in await bl_holds(tg_id)}
    sub = await get_paid_sub_by_tg_id(tg_id)
    sub_live = bool(sub) and sub[11] in ("active", "renewal")
    if e:
        status = "manual" if e["source"] == "manual" else "remote"
        reason = e["reason"] or ""
        source = e["source"]
        remote_src = e.get("remote_src") or None
        until = e.get("until")
        by_id = e.get("by_id")
        since = e.get("since")
    elif info["allowed"]:
        status, reason, source = "allowed", info["remote"] or "", "remote"
        remote_src, until, by_id, since = info.get("remote_src"), None, None, None
    elif info["remote_listed"] and not bl_mod.remote_on():
        status, reason, source = "remote_off", info["remote"] or "", "remote"
        remote_src, until, by_id, since = info.get("remote_src"), None, None, None
    else:
        status, reason, source = "none", "", None
        remote_src, until, by_id, since = None, None, None, None
    by_name = None
    if by_id:
        bu = await get_user_info(by_id)
        by_name = bu[1] if bu and len(bu) > 1 else None
    hist = await bl_history(tg_id, 5)
    return web.json_response({
        "tg_id": tg_id,
        "first_name": u[1] if u else None,
        "username": u[2] if u else None,
        "status": status, "reason": reason,
        "public_reason": bl_mod.public_reason(reason) if reason else None,
        "source": source, "remote_src": remote_src,
        "until": str(until or "")[:16] or None,
        "until_text": bl_mod.fmt_until(until) if status == "manual" else None,
        "by_id": by_id, "by_name": by_name,
        "since": str(since or "")[:16] or None,
        "sub": {"live": sub_live,
                "until": str(sub[6])[:16] if sub else None,
                "held_seconds": holds.get("paid")},
        "history": [{"when": str(h[3] or "")[:16],
                     "word": bl_mod.HIST_WORDS.get(h[0], h[0]),
                     "reason": bl_mod.public_reason(h[1]) if h[1] else None}
                    for h in hist],
        "times": await bl_times_listed(tg_id),
    })


async def blacklist_add(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    try:
        tg_id = int(body.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    reason = str(body.get("reason") or "").strip()
    if not tg_id or not reason:
        return _json_error("bad_request")
    until = None
    term = str(body.get("term") or "")
    # старые страницы админки шлют day/week/month — маппим их тоже,
    # иначе срок молча сбрасывался бы в «навсегда»
    term = {"day": "1d", "week": "7d", "month": "30d"}.get(term, term)
    if term and term in bl_mod.TERM_SECONDS:
        until = bl_mod.until_utc(bl_mod.TERM_SECONDS[term])
    elif body.get("until"):
        until = str(body.get("until"))
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    by_id = _actor_id(actor) if actor["kind"] == "mark" else None
    res = await bl_mod.blacklist_add(bot, tg_id, reason, until, by_id=by_id)
    await _audit(actor, "blacklist_add", f"tg_id={tg_id}")
    return web.json_response({"ok": True, "result": res or {}})


async def blacklist_stop(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        tg_id = int(request.match_info.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    if not tg_id:
        return _json_error("bad_request")
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        return confirm_needed_response(
            issue_confirm(actor, "blacklist_stop", {"tg_id": tg_id},
                          f"Остановить подписку {tg_id} (чёрный список)?"),
            f"Остановить подписку {tg_id} (чёрный список)?")
    payload = take_confirm(actor, token, "blacklist_stop")
    if payload is None or int(payload.get("tg_id") or 0) != tg_id:
        return _json_error("bad_confirm", 403)
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    res = await bl_mod.blacklist_stop(bot, tg_id)
    if res is None:
        return _json_error("not_blacklisted", 404)
    await _audit(actor, "blacklist_stop", f"tg_id={tg_id}")
    return web.json_response({"ok": True, "result": res})


async def blacklist_readd(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        tg_id = int(request.match_info.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    if not tg_id:
        return _json_error("bad_request")
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    by_id = _actor_id(actor) if actor["kind"] == "mark" else None
    res = await bl_mod.blacklist_readd(bot, tg_id, by_id=by_id)
    if res is None:
        return _json_error("not_found", 404)
    await _audit(actor, "blacklist_readd", f"tg_id={tg_id}")
    return web.json_response({"ok": True, "result": res})


async def blacklist_remove(request):
    """Убрать из ЧС — как handle_bl_del в ТГ (двухшаговое подтверждение)."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        tg_id = int(request.match_info.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    if not tg_id:
        return _json_error("bad_request")
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        return confirm_needed_response(
            issue_confirm(actor, "blacklist_remove", {"tg_id": tg_id},
                          f"Убрать {tg_id} из чёрного списка?"),
            f"Убрать {tg_id} из чёрного списка?")
    payload = take_confirm(actor, token, "blacklist_remove")
    if payload is None or int(payload.get("tg_id") or 0) != tg_id:
        return _json_error("bad_confirm", 403)
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    by_id = _actor_id(actor) if actor["kind"] == "mark" else None
    res = await bl_mod.blacklist_remove(bot, tg_id, by_id=by_id)
    await _audit(actor, "blacklist_remove", f"tg_id={tg_id}")
    return web.json_response({"ok": True, "result": res or {}})


async def blacklist_sync(request):
    """Ручное обновление общего списка — как handle_bl_sync_now в ТГ."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    r = await bl_mod.sync_remote(bot, force_extra=True)
    if r.get("ok"):
        try:
            await bl_mod.send_report(bot, r)
        except Exception:
            pass
        await _audit(actor, "blacklist_sync",
                     f"total={r.get('total')} +{r.get('added')} -{r.get('removed')}")
        return web.json_response({"ok": True, "total": r.get("total", 0),
                                  "added": r.get("added", 0),
                                  "removed": r.get("removed", 0),
                                  "extra_total": r.get("extra_total", 0),
                                  "extra_fetched": bool(r.get("extra_fetched")),
                                  "extra_error": r.get("extra_error")})
    return web.json_response({"ok": False,
                              "error": str(r.get("error") or "sync_failed")})


async def blacklist_remote_toggle(request):
    """Тумблер общего списка — как handle_bl_remote_toggle в ТГ."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    turn_on = not bl_mod.remote_on()
    if not token:
        summary = ("Включить общий чёрный список и обновить его?"
                   if turn_on else
                   "Выключить общий чёрный список? "
                   "Остановленные из-за него подписки вернутся.")
        return confirm_needed_response(
            issue_confirm(actor, "blacklist_remote_toggle",
                          {"on": turn_on}, summary),
            summary)
    payload = take_confirm(actor, token, "blacklist_remote_toggle")
    if payload is None or bool(payload.get("on")) != turn_on:
        return _json_error("bad_confirm", 403)
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    from config import atomic_update

    def _apply(cfg):
        cfg["blacklist_remote_enabled"] = turn_on
    atomic_update(_apply)
    out = {"ok": True, "enabled": turn_on}
    if turn_on:
        r = await bl_mod.sync_remote(bot, full_scan=True, force_extra=True)
        try:
            await bl_mod.send_report(bot, r)
        except Exception:
            pass
        out.update(sync_ok=bool(r.get("ok")), total=r.get("total", 0),
                   added=r.get("added", 0), removed=r.get("removed", 0),
                   sync_error=str(r.get("error") or "") or None)
    else:
        restored = await bl_mod.restore_unlisted(bot)
        out["restored"] = len(restored)
    await _audit(actor, "blacklist_remote_toggle",
                 "on" if turn_on else "off")
    return web.json_response(out)


# ── Фрод ─────────────────────────────────────────────────────────────────────

async def fraud_get(request):
    try:
        actor = await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from config import load_config
    from core.database import fraud_stats, list_fraud_pairs
    status = request.query.get("status") or None
    if status not in (None, "new", "ignored", "blocked", "all"):
        return _json_error("bad_status", 400)
    if status == "all":
        status = None
    rows = await list_fraud_pairs(status, limit=15)
    cfg = load_config()
    return web.json_response({
        "enabled": bool(cfg.get("fraud_enabled", True)),
        "use_ip": bool(cfg.get("fraud_use_ip", True)),
        "is_mark": bool(require_mark(actor)),
        "stats": await fraud_stats(),
        "pairs": [{"tg_a": r[0], "tg_b": r[1], "kind": r[2],
                   "value": str(r[3])[:40], "status": r[4],
                   "created_at": str(r[5] or ""), "score": r[6] or 0}
                  for r in rows],
    })


async def _fraud_toggle_core(request, key: str, action: str, label: str):
    """Тумблер из handle_fraud_menu в ТГ (fraud_toggle / fraud_ip_toggle):
    только Mark, с подтверждением, тот же ключ config.json."""
    from config import atomic_update, load_config
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    enabled = bool(load_config().get(key, True))
    body = await _json_body(request)
    token = body.get("token") or body.get("confirm_token")
    if not token:
        summary = (f"Выключить: {label}?" if enabled else
                   f"Включить: {label}?")
        return confirm_needed_response(
            issue_confirm(actor, action, {}, summary),
            summary)
    payload = take_confirm(actor, token, action)
    if payload is None:
        return _json_error("bad_confirm", 403)

    def _apply(cfg):
        cfg[key] = not bool(cfg.get(key, True))
    atomic_update(_apply)
    now_on = bool(load_config().get(key, True))
    bot = get_bot()
    if bot is not None:
        try:
            from core.log_channel import send_log
            await send_log(bot, f"🕵 {label}: "
                           f"{'включено' if now_on else 'выключено'}")
        except Exception as ex:
            logging.error("админка: %s send_log: %s", action, ex)
    await _audit(actor, action, "on" if now_on else "off")
    return web.json_response({"ok": True, "enabled": now_on})


async def fraud_toggle(request):
    """Слежка за повторными триалами вкл/выкл — как fraud_toggle в ТГ."""
    return await _fraud_toggle_core(
        request, "fraud_enabled", "fraud_toggle",
        "слежка за повторными триалами")


async def fraud_ip_toggle(request):
    """Адрес как улика вкл/выкл — как fraud_ip_toggle в ТГ."""
    return await _fraud_toggle_core(
        request, "fraud_use_ip", "fraud_ip_toggle",
        "адрес как улика антифрода")


def _fraud_who(tg_id: int, info, sub_row, marks: dict) -> dict:
    """Справка о человеке — те же поля, что who_line в features/fraud.py,
    только структурой, а не HTML-строкой."""
    name, username = None, None
    if info:
        name = info[1] if len(info) > 1 else None
        username = info[2] if len(info) > 2 else None
    sub = None
    can_stop = False
    if sub_row:
        status = sub_row[11] if len(sub_row) > 11 else "active"
        renewed = sub_row[12] if len(sub_row) > 12 else 0
        sub = {"kind": "платная" if renewed else "пробная",
               "status": status,
               "until": str(sub_row[6])[:16] if len(sub_row) > 6 else None}
        # закрыть триал предлагаем только тому, кто ещё ни разу не платил
        # и чей триал не истёк — то же условие, что handle_fraud_pair
        can_stop = bool(not renewed and status != "expired")
    return {"tg_id": tg_id, "name": name, "username": username, "sub": sub,
            "hwid": int(marks.get("hwid") or 0),
            "ip": int(marks.get("ip") or 0), "can_stop": can_stop}


async def fraud_pair(request):
    """Карточка находки — как handle_fraud_pair в ТГ: кто эти двое,
    что совпало (улики с весами), кластер отпечатка, вердикт."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    try:
        a = int(request.query.get("a") or 0)
        b = int(request.query.get("b") or 0)
    except (TypeError, ValueError):
        a = b = 0
    if not a or not b or a == b:
        return _json_error("bad_request", 400)
    from core.database import (
        fingerprint_cluster, get_fraud_evidence, get_fraud_pair,
        get_user_info, user_fingerprint_stats,
    )
    from paidsub.storage import get_paid_sub_by_tg_id
    pair = await get_fraud_pair(a, b)
    if not pair:
        return _json_error("pair_not_found", 404)
    tg_a, tg_b, kind, value, status, created = pair[:6]
    score = pair[6] if len(pair) > 6 else 0
    evidence = await get_fraud_evidence(tg_a, tg_b)
    ev_rows = [{"kind": ek,
                "label": fraud_mod._KIND_LABEL.get(ek, f"🔎 {ek}"),
                "value": str(ev)[:40], "weight": int(ew or 0)}
               for ek, ev, ew, _ec in evidence]
    if not ev_rows:
        ev_rows = [{"kind": kind,
                    "label": fraud_mod._KIND_LABEL.get(kind, f"🔎 {kind}"),
                    "value": str(value)[:40], "weight": 0}]
    cluster = await fingerprint_cluster(kind, value)
    others = [c for c in cluster if c[0] not in (tg_a, tg_b)]
    first_seen = min((c[2] for c in cluster if c[2]), default=None)
    last_seen = max((c[3] for c in cluster if c[3]), default=None)
    other_rows = []
    for tg_id, _email, _f, _l in others[:4]:
        u = await get_user_info(tg_id)
        other_rows.append({"tg_id": tg_id,
                           "name": u[1] if u and len(u) > 1 else None,
                           "username": u[2] if u and len(u) > 2 else None})
    who = []
    for tg_id in (tg_a, tg_b):
        who.append(_fraud_who(
            tg_id, await get_user_info(tg_id),
            await get_paid_sub_by_tg_id(tg_id),
            await user_fingerprint_stats(tg_id)))
    has_ip = any(e["kind"] == "ip" for e in ev_rows)
    has_hwid = any(e["kind"] == "hwid" for e in ev_rows)
    return web.json_response({
        "pair": {"tg_a": tg_a, "tg_b": tg_b, "kind": kind,
                 "value": str(value)[:40], "status": status,
                 "created_at": str(created or "")[:16],
                 "score": score or 0,
                 "verdict": fraud_mod.verdict(score or 0)},
        "evidence": ev_rows,
        "cluster": {"first_seen": str(first_seen)[:16] if first_seen else None,
                    "last_seen": str(last_seen)[:16] if last_seen else None,
                    "others": other_rows, "others_count": len(others)},
        "who": who,
        # сильной улики (устройства) нет: адрес и прочее по отдельности
        # слабы — то же предупреждение, что handle_fraud_pair
        "weak_only": bool(has_ip and not has_hwid),
    })


async def fraud_ignore(request):
    """«Не фрод — больше не спрашивать» — как handle_fraud_ok в ТГ."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        a = int(request.match_info.get("a") or 0)
        b = int(request.match_info.get("b") or 0)
    except (TypeError, ValueError):
        a = b = 0
    if not a or not b or a == b:
        return _json_error("bad_request", 400)
    from core.database import get_fraud_pair, ignore_fraud_pair
    if not await get_fraud_pair(a, b):
        return _json_error("pair_not_found", 404)
    await ignore_fraud_pair(a, b)
    await _audit(actor, "fraud_ignore", f"{a}<->{b}")
    return web.json_response({"ok": True})


async def fraud_recheck(request):
    """Полная пересверка пары — как handle_fraud_recheck в ТГ:
    тот же apply_evaluation (улики, балл, алерт админу при росте)."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        a = int(request.match_info.get("a") or 0)
        b = int(request.match_info.get("b") or 0)
    except (TypeError, ValueError):
        a = b = 0
    if not a or not b or a == b:
        return _json_error("bad_request", 400)
    from core.database import get_fraud_pair
    if not await get_fraud_pair(a, b):
        return _json_error("pair_not_found", 404)
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    context = SimpleNamespace(bot=bot, application=_admin_application)
    score = await fraud_mod.apply_evaluation(context, a, b)
    await _audit(actor, "fraud_recheck", f"{a}<->{b} score={score}")
    return web.json_response({"ok": True, "score": score,
                              "verdict": fraud_mod.verdict(score)})


async def fraud_scan(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    from config import load_config
    context = SimpleNamespace(bot=bot, application=_admin_application)
    batch = await fraud_mod._subs_slice(
        int(load_config().get("fraud_batch", 8) or 8))
    alerts = 0
    for _sub_id, tg_id, email, times_renewed in batch:
        alerts += len(await fraud_mod.scan_sub(
            context, tg_id, email, bool(times_renewed)))
    await _audit(actor, "fraud_scan",
                 f"checked={len(batch)} alerts={alerts}")
    return web.json_response({"ok": True, "checked": len(batch),
                              "alerts": alerts})


async def _fraud_stop_core(tg_id: int, other_tg: int) -> dict:
    """Ядро handlers/fraud.py handle_fraud_stop без query: закрывает
    пробную подписку, выключает клиента в панели, помечает пару."""
    from core.database import set_fraud_pair_status
    from paidsub.storage import (
        add_history, get_paid_sub_by_tg_id, set_expire_date,
        update_paid_sub_field,
    )
    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return {"ok": False, "error": "no_sub"}
    sub_id, email = row[0], row[2]
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    await set_expire_date(sub_id, now)
    await update_paid_sub_field(sub_id, "status", "expired")
    pushed = await panel_mod.update_client_expire(email, now)
    off = await panel_mod.toggle_client(email, False)
    await add_history(tg_id, "trial_stopped",
                      "Триал закрыт: повторная регистрация")
    await set_fraud_pair_status(tg_id, other_tg, "blocked")
    trouble = ""
    if not pushed.get("success"):
        trouble += f" · срок: {pushed.get('error')}"
    if not off.get("success"):
        trouble += f" · отключение: {off.get('error')}"
    return {"ok": True, "trouble": trouble.strip(" ·")}


async def fraud_stop(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        tg_id = int(request.match_info.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    if not tg_id:
        return _json_error("bad_request")
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        try:
            other_tg = int(body.get("other_tg") or 0)
        except (TypeError, ValueError):
            other_tg = 0
        if not other_tg:
            return _json_error("bad_request")
        return confirm_needed_response(
            issue_confirm(actor, "fraud_stop",
                          {"tg_id": tg_id, "other_tg": other_tg},
                          f"Закрыть триал {tg_id} (повторная регистрация)?"),
            f"Закрыть триал {tg_id} (повторная регистрация)?")
    payload = take_confirm(actor, token, "fraud_stop")
    if payload is None or int(payload.get("tg_id") or 0) != tg_id:
        return _json_error("bad_confirm", 403)
    res = await _fraud_stop_core(tg_id, int(payload.get("other_tg") or 0))
    if not res.get("ok"):
        return _json_error(res.get("error") or "fraud_stop_failed", 404)
    await _audit(actor, "fraud_stop", f"tg_id={tg_id}")
    return web.json_response({"ok": True, "trouble": res.get("trouble") or ""})


# ── Поддержка, падения, онлайн ───────────────────────────────────────────────

async def support_topics(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from core.database import get_open_support_topics, get_user_info, support_stats
    rows = await get_open_support_topics()
    topics = []
    for r in rows:
        info = await get_user_info(r[0])
        topics.append({"user_id": r[0], "topic_id": r[1], "group_id": r[2],
                       "topic_name": r[3] or "",
                       "first_name": (info[1] if info else "") or "",
                       "username": (info[2] if info else "") or ""})
    return web.json_response({
        "stats": await support_stats(),
        "topics": topics,
    })


# Подписи целей и порядок — как handlers/downtime.py target_label/_ordered_targets.
_DOWNTIME_KIND_ORDER = {"service": 0, "site": 1, "node": 2}


def _downtime_label(target: str) -> str:
    if target == "panel":
        return "Панель"
    if target == "sub":
        return "Ссылки подписок"
    if target.startswith("site:"):
        return ("Сайт" if target == "site:vpn.drbl.tech"
                else "Страница подписки")
    if target.startswith("node:"):
        return f"Узел {target[5:]}"
    return target


def _downtime_ordered_targets(summary, current):
    targets = list(dict.fromkeys(list(summary) + list(current)))

    def _kind(t):
        k = (summary.get(t) or {}).get("kind")
        if k:
            return k
        if t.startswith("node:"):
            return "node"
        if t.startswith("site:"):
            return "site"
        return "service"

    return sorted(targets,
                  key=lambda t: (_DOWNTIME_KIND_ORDER.get(_kind(t), 9), t))


async def downtime_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    import time as _time
    from config import load_config
    from core.database import downtime_summary, get_downtime_events
    days = _int_query(request, "days", 30)
    days = min(90, max(1, days))
    now = int(_time.time())
    cfg = load_config()
    observation_since = int(cfg.get("downtime_since") or now)
    window_start = max(observation_since, now - days * 86400)
    window_sec = max(1, now - window_start)
    events = await get_downtime_events(window_start)
    from datetime import datetime, timedelta, timezone
    msk = timezone(timedelta(hours=3))

    def _fmt(ts):
        if not ts:
            return None
        return datetime.fromtimestamp(int(ts), msk).strftime("%d.%m.%Y %H:%M:%S")

    for ev in events:
        ev["started_str"] = _fmt(ev.get("started_at"))
        ev["ended_str"] = _fmt(ev.get("ended_at"))
        end = int(ev["ended_at"]) if ev.get("ended_at") else now
        ev["duration_sec"] = max(0, end - int(ev["started_at"]))
        ev["label"] = _downtime_label(ev.get("target") or "")
    summary = downtime_summary(events, window_start, now)
    # Текущее состояние — живой пробой, как в ТГ handle_downtime_menu.
    # Падение пробоя — пустой current, а не 500: сводка всё равно отдаётся.
    current: dict[str, bool] = {}
    try:
        r = await panel_mod.probe_servers()
        current["panel"] = bool(r["panel"]["ok"])
        if r["panel"]["ok"]:
            current["sub"] = bool(r["sub"]["ok"])
            for n in r["nodes"]:
                if n["enabled"]:
                    current[f"node:{n['tag']}"] = bool(n["reachable"])
    except Exception:
        pass
    try:
        for target, st in (await panel_mod.probe_sites()).items():
            current[target] = bool(st["ok"])
    except Exception:
        pass
    ordered_summary: dict[str, dict] = {}
    for t in _downtime_ordered_targets(summary, current):
        st = dict(summary.get(t) or {
            "kind": "", "incidents": 0, "downtime_sec": 0,
            "open_since": None, "last_start": None, "last_end": None,
        })
        st["label"] = _downtime_label(t)
        # Та же формула и тот же формат, что _uptime_pct в handlers/downtime.py.
        st["uptime"] = f"{100.0 * (1 - st['downtime_sec'] / window_sec):.1f}%"
        ordered_summary[t] = st
    return web.json_response({
        "days": days, "since": window_start, "now": now,
        "observation_since": observation_since,
        "current": current,
        "summary": ordered_summary,
        "events": events,
    })


async def online_get(request):
    """Кто онлайн + последняя активность — с именами людей, как в ТГ.

    handle_online в ТГ (handlers/control.py): get_online_emails ->
    users_by_emails -> люди с именем/@username/TG ID. Раньше веб
    отдавал только сырые email, а фронт показывал их пилюлями без имён.
    Новые поля people/last — та же привязка; старые online/last_online
    не меняются (совместимость). Резолв — best-effort: его падение не
    роняет ответ, email тогда остаются сырыми.
    """
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    try:
        online = await panel_mod.get_online_emails()
    except Exception as ex:
        logging.error("админка: online: %s", ex)
        online = {"ok": False, "emails": []}
    try:
        last = await panel_mod.get_last_online()
    except Exception as ex:
        logging.error("админка: last_online: %s", ex)
        last = {"ok": False, "last": {}}
    if not isinstance(online, dict):
        online = {"ok": False, "emails": []}
    if not isinstance(last, dict):
        last = {"ok": False, "last": {}}
    emails = list(dict.fromkeys(
        (online.get("emails") or []) + list((last.get("last") or {}).keys())))
    by_email = {}
    if emails:
        try:
            import core.database as db
            by_email = await db.users_by_emails(emails) or {}
        except Exception as ex:
            logging.error("админка: online: users_by_emails: %s", ex)
            by_email = {}

    def _person(email):
        tg_id, fn, un = by_email.get(email, (None, None, None))
        return {"email": email, "tg_id": tg_id, "name": fn, "username": un}

    people = [_person(e) for e in (online.get("emails") or [])]
    last_map = last.get("last") or {}
    last_rows = []
    for email, ms in sorted(last_map.items(),
                            key=lambda kv: kv[1] or 0, reverse=True)[:50]:
        row = _person(email)
        row["ms"] = ms or 0
        last_rows.append(row)
    return web.json_response({"online": online, "last_online": last,
                              "people": people, "last": last_rows})


# ── Веб-доступ и помощь при подключении ──────────────────────────────────────

async def web_access_get(request):
    """Страница «Веб-доступ»: настройки API кабинета и статистика сессий.

    Только чтение плюс смена порта/bind — они вступают в силу только
    после рестарта бота (DESIGN §3.3). Включать/выключать сам API из
    веба нельзя: выключение убило бы и эту админку — это делает ТГ."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from config import load_config
    from core.database import web_sessions_stats
    from web.webapi import settings as webapi_settings
    cfg = load_config()
    stats = await web_sessions_stats()
    return web.json_response({
        "webapi": webapi_settings(),
        "public": cfg.get("webapi_public") or "",
        "upstream": cfg.get("webapi_upstream") or "",
        "turnstile_site_key_set": bool(cfg.get("turnstile_site_key")),
        "turnstile_secret_set": bool(cfg.get("turnstile_secret_key")),
        "sessions": stats,
    })


async def web_access_patch(request):
    from config import atomic_update
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return _json_error("bad_request", 400)
    patch = {}
    if "webapi_port" in body:
        port = body.get("webapi_port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return _json_error("bad_value", 400)
        patch["webapi_port"] = port
    if "webapi_bind" in body:
        bind = str(body.get("webapi_bind") or "").strip()
        if bind not in ("127.0.0.1", "0.0.0.0"):
            return _json_error("bad_value", 400)
        patch["webapi_bind"] = bind
    # Публичный адрес и upstream раньше правились только из ТГ — теперь и здесь.
    for key in ("webapi_public", "webapi_upstream"):
        if key in body:
            val = str(body.get(key) or "").strip().rstrip("/")
            if val and not val.startswith(("http://", "https://")):
                return _json_error("bad_value", 400)
            patch[key] = val
    # Ключи Turnstile — только запись: наружу отдаём лишь факт, что заданы.
    if body.get("turnstile_site_key"):
        patch["turnstile_site_key"] = str(body["turnstile_site_key"]).strip()
    if body.get("turnstile_secret_key"):
        patch["turnstile_secret_key"] = str(body["turnstile_secret_key"]).strip()
    if "webapi_enabled" in body:
        return _json_error(
            "webapi_enabled меняется только из ТГ: выключение убьёт и эту админку",
            403)
    if patch:
        def _apply(cfg):
            cfg.update(patch)
        atomic_update(_apply)
    shown = [k for k in sorted(patch) if "turnstile" not in k]
    if any("turnstile" in k for k in patch):
        shown.append("turnstile(скрыт)")
    await _audit(actor, "web_access_update",
                 "keys: " + ", ".join(shown) + " (restart_required)")
    return web.json_response({"ok": True, "restart_required": True,
                              "webapi": {k: v for k, v in patch.items()
                                         if "turnstile" not in k}})


async def web_access_check(request):
    """Проверка кабинета — та же, что кнопка «Проверить» в ТГ (webapi.probe)."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    from web.webapi import probe
    try:
        res = await probe()
    except Exception as ex:
        logging.error("админка: web-access probe: %s", ex)
        return _json_error("check_failed", 502)
    return web.json_response({"check": res})


async def web_access_find_upstream(request):
    """«Найти адрес бота» — та же, что кнопка в ТГ (webapi.find_upstream).

    Перебирает кандидатов (тот же сервер, внешний IP бота, хост сервера
    сайта), проверку делает сам сервер сайта; первый ответивший 200
    сохраняется в webapi_upstream, а при заданном домене сайта — и
    webapi_public, как в handle_cabinet_find. Неудача — не ошибка HTTP:
    возвращается список перебранных адресов и подсказка про файрвол.
    """
    from config import atomic_update
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    from web.webapi import find_upstream, settings as webapi_settings
    try:
        res = await find_upstream()
    except Exception as ex:
        logging.error("админка: web-access find-upstream: %s", ex)
        return _json_error("check_failed", 502)
    if not res.get("ok"):
        port = webapi_settings()["port"]
        return web.json_response({
            "ok": False,
            "tried": res.get("tried") or {},
            "error": str(res.get("error") or "ни один адрес не ответил"),
            "hint": (
                "Чаще всего мешает файрвол: открой порт "
                f"{port} на сервере бота для адреса сервера сайта. "
                f"Например: ufw allow from АДРЕС_САЙТА to any port {port}"
            ),
            "port": port,
        })
    import web.site_deploy as site
    target = res["target"]
    public = site.site_url() if site.creds()["domain"] else ""

    def _apply(cfg):
        cfg["webapi_upstream"] = target
        if public:
            cfg["webapi_public"] = public
    atomic_update(_apply)
    await _audit(actor, "web_access_update",
                 f"найден upstream {target}"
                 + ("; public обновлён" if public else ""))
    return web.json_response({
        "ok": True,
        "target": target,
        "tried": res.get("tried") or {},
        "ip": res.get("ip") or "",
        "public": public,
        "public_updated": bool(public),
    })


async def connect_help_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from config import load_config
    from core.database import connect_help_stats
    cfg = load_config()
    return web.json_response({
        "enabled": bool(cfg.get("connect_help_enabled", True)),
        "hours": int(cfg.get("connect_help_hours", 3) or 3),
        "stats": await connect_help_stats(),
    })


async def connect_help_patch(request):
    from config import atomic_update
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return _json_error("bad_request", 400)
    patch = {}
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            return _json_error("bad_value", 400)
        patch["connect_help_enabled"] = body["enabled"]
    if "hours" in body:
        hours = body["hours"]
        if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1:
            return _json_error("bad_value", 400)
        patch["connect_help_hours"] = hours
    if patch:
        def _apply(cfg):
            cfg.update(patch)
        atomic_update(_apply)
    await _audit(actor, "connect_help_update",
                 "keys: " + ", ".join(sorted(patch)))
    return web.json_response({"ok": True})


# ── Панель: профили/инбаунды/хосты (Mark-only) ───────────────────────────────

def _panel_error(res: dict):
    """Ошибка панели наружу — только её текст, без внутренностей."""
    return _json_error(_scrub(str(res.get("error") or "panel_failed")), 502)


def _profile_config(profile: dict) -> dict | None:
    """Xray-JSON профиля: поле config, либо сам профиль, если он и есть
    конфиг. None — если конфига нет вообще."""
    cfg = profile.get("config")
    if isinstance(cfg, dict):
        return cfg
    return profile if isinstance(profile, dict) else None


def _find_inbound(config: dict, tag: str) -> dict | None:
    for ib in config.get("inbounds") or []:
        if isinstance(ib, dict) and ib.get("tag") == tag:
            return ib
    return None


def _inbound_public(ib: dict) -> dict:
    """Публичный вид инбаунда для веба: только редактируемые поля.

    Полный инбаунд из конфига профиля несёт settings.clients,
    realitySettings.privateKey и shortIds — в браузер это не отдаём
    вообще: ни в дамп профиля, ни в ответ после правки."""
    if not isinstance(ib, dict):
        return {"tag": "", "protocol": "", "port": None,
                "serverNames": [], "dest": "", "fingerprint": ""}
    rs = {}
    ss = ib.get("streamSettings")
    if isinstance(ss, dict):
        rs = ss.get("realitySettings") or {}
        if not isinstance(rs, dict):
            rs = {}
    names = rs.get("serverNames") or []
    if isinstance(names, str):
        names = [names]
    names = [str(n) for n in names if isinstance(n, (str, int))]
    return {
        "tag": str(ib.get("tag") or ""),
        "protocol": str(ib.get("protocol") or ib.get("type") or ""),
        "port": ib.get("port"),
        "serverNames": names,
        "dest": str(rs.get("dest") or ""),
        "fingerprint": str(rs.get("fingerprint") or ""),
    }


async def panel_hosts_list(request):
    """Все хосты панели — для кликабельного списка в админке.
    Только чтение."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    res = await rw_mod.list_hosts()
    return web.json_response(res)


async def panel_profile_get(request):
    try:
        actor = await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    uuid = request.match_info.get("uuid") or ""
    res = await rw_mod.get_config_profile(uuid)
    if not res.get("ok"):
        return _panel_error(res)
    config = _profile_config(res.get("data") or {})
    if config is None:
        return _json_error("panel_failed", 502)
    data = res.get("data") or {}
    return web.json_response({
        "ok": True,
        "uuid": uuid,
        "name": data.get("name") or "",
        # Полный конфиг (privateKey, clients, shortIds) наружу не
        # отдаём — только публичные поля инбаундов.
        "inbounds": [_inbound_public(ib)
                      for ib in (config.get("inbounds") or [])
                      if isinstance(ib, dict)],
    })


_INBOUND_EDIT_FIELDS = ("port", "serverNames", "dest", "target", "fingerprint")


def _clean_inbound_patch(body: dict):
    """Проверяет PATCH тела инбаунда. Возвращает (fields, error)."""
    fields = {}
    for key in body:
        if key not in _INBOUND_EDIT_FIELDS:
            return None, "bad_field"
    if "port" in body:
        port = body["port"]
        if isinstance(port, bool) or not isinstance(port, int) \
                or not 1 <= port <= 65535:
            return None, "bad_port"
        fields["port"] = port
    if "serverNames" in body:
        names = body["serverNames"]
        if not isinstance(names, list) \
                or any(not isinstance(n, str) for n in names):
            return None, "bad_server_names"
        fields["serverNames"] = list(names)
    for key in ("dest", "target"):
        if key in body:
            val = body[key]
            if not isinstance(val, str) or not val.strip():
                return None, "bad_dest"
            fields["dest"] = val.strip()
    if "fingerprint" in body:
        fp = body["fingerprint"]
        if not isinstance(fp, str) or not fp.strip():
            return None, "bad_fingerprint"
        fields["fingerprint"] = fp.strip()
    if not fields:
        return None, "bad_request"
    return fields, None


async def panel_profile_inbound_patch(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    uuid = request.match_info.get("uuid") or ""
    tag = request.match_info.get("tag") or ""
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        fields, bad = _clean_inbound_patch(body)
        if bad:
            return _json_error(bad)
        return confirm_needed_response(
            issue_confirm(actor, "panel_profile_inbound_patch",
                          {"uuid": uuid, "tag": tag, "fields": fields},
                          f"Изменить инбаунд {tag} в профиле?"),
            f"Изменить инбаунд {tag} в профиле?")
    payload = take_confirm(actor, token, "panel_profile_inbound_patch")
    if payload is None or payload.get("uuid") != uuid \
            or payload.get("tag") != tag:
        return _json_error("bad_confirm", 403)
    fields = payload.get("fields") or {}
    # 1. GET профиля, правим копию конфига — только whitelisted-поля.
    res = await rw_mod.get_config_profile(uuid)
    if not res.get("ok"):
        return _panel_error(res)
    config = _profile_config(res.get("data") or {})
    if config is None:
        return _json_error("panel_failed", 502)
    config = copy.deepcopy(config)
    inbound = _find_inbound(config, tag)
    if inbound is None:
        return _json_error("inbound_not_found", 404)
    reality_fields = {"serverNames", "dest", "fingerprint"} & set(fields)
    if reality_fields:
        ss = inbound.get("streamSettings")
        if not isinstance(ss, dict):
            return _json_error("not_reality_inbound", 400)
        rs = ss.get("realitySettings")
        if rs is None:
            if ss.get("security") != "reality":
                return _json_error("not_reality_inbound", 400)
            rs = {}
            ss["realitySettings"] = rs
        if not isinstance(rs, dict):
            return _json_error("not_reality_inbound", 400)
        if "serverNames" in fields:
            rs["serverNames"] = fields["serverNames"]
        if "dest" in fields:
            rs["dest"] = fields["dest"]
        if "fingerprint" in fields:
            rs["fingerprint"] = fields["fingerprint"]
    if "port" in fields:
        inbound["port"] = fields["port"]
    # settings.clients / privateKey / shortIds не трогаем вообще: мы не
    # пишем в settings, только в port и streamSettings.realitySettings.
    # 2. PATCH {uuid, config} обратно в панель.
    res = await rw_mod.update_config_profile(uuid, config)
    if not res.get("ok"):
        return _panel_error(res)
    # 3. Валидация: computed-config, затем свежий профиль.
    comp = await rw_mod.get_computed_config(uuid)
    if not comp.get("ok"):
        return _panel_error(comp)
    fresh = await rw_mod.get_config_profile(uuid)
    if not fresh.get("ok"):
        return _panel_error(fresh)
    fresh_config = _profile_config(fresh.get("data") or {})
    fresh_inbound = _find_inbound(fresh_config, tag) \
        if fresh_config is not None else None
    if fresh_inbound is None:
        return _json_error("inbound_not_found", 404)
    await _audit(actor, "panel_profile_inbound_edit",
                 f"profile={uuid} tag={tag} "
                 f"fields={','.join(sorted(fields))}")
    return web.json_response({"ok": True,
                              "inbound": _inbound_public(fresh_inbound)})


_HOST_EDIT_FIELDS = ("remark", "address", "port", "sni", "isDisabled")


def _clean_host_patch(body: dict):
    """Проверяет PATCH тела хоста. Возвращает (fields, error)."""
    fields = {}
    for key in body:
        if key not in _HOST_EDIT_FIELDS:
            return None, "bad_field"
    for key in ("remark", "address", "sni"):
        if key in body:
            val = body[key]
            if not isinstance(val, str):
                return None, "bad_value"
            fields[key] = val
    if "port" in body:
        port = body["port"]
        if isinstance(port, bool) or not isinstance(port, int) \
                or not 1 <= port <= 65535:
            return None, "bad_port"
        fields["port"] = port
    if "isDisabled" in body:
        if not isinstance(body["isDisabled"], bool):
            return None, "bad_value"
        fields["isDisabled"] = body["isDisabled"]
    if not fields:
        return None, "bad_request"
    return fields, None


async def _read_back_host(uuid: str):
    """Хост из панели после правки (валидация read-back)."""
    res = await rw_mod.list_hosts()
    if not res.get("ok"):
        return None
    for h in res.get("hosts") or []:
        if h.get("uuid") == uuid:
            return h
    return None


async def panel_host_patch(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    uuid = request.match_info.get("uuid") or ""
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        fields, bad = _clean_host_patch(body)
        if bad:
            return _json_error(bad)
        return confirm_needed_response(
            issue_confirm(actor, "panel_host_patch",
                          {"uuid": uuid, "fields": fields},
                          "Изменить хост в панели?"),
            "Изменить хост в панели?")
    payload = take_confirm(actor, token, "panel_host_patch")
    if payload is None or payload.get("uuid") != uuid:
        return _json_error("bad_confirm", 403)
    fields = payload.get("fields") or {}
    # Хосты — тот же collection-паттерн, что /api/users и
    # /api/config-profiles: PATCH {uuid, ...fields}, валидация read-back.
    res = await rw_mod.patch_host(uuid, fields)
    if not res.get("ok"):
        return _panel_error(res)
    host = await _read_back_host(uuid)
    await _audit(actor, "panel_host_edit",
                 f"host={uuid} fields={','.join(sorted(fields))}")
    return web.json_response({"ok": True, "host": host or fields})


async def panel_host_create(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        inbound_uuid = str(body.get("inboundUuid") or "")
        address = str(body.get("address") or "")
        port = body.get("port")
        if not inbound_uuid or not address \
                or isinstance(port, bool) or not isinstance(port, int) \
                or not 1 <= port <= 65535:
            return _json_error("bad_request")
        fields = {
            "inboundUuid": inbound_uuid,
            "remark": str(body.get("remark") or ""),
            "address": address,
            "port": port,
            "sni": str(body.get("sni") or ""),
            # Как в UI панели: новый хост по умолчанию выключен.
            "isDisabled": True,
        }
        return confirm_needed_response(
            issue_confirm(actor, "panel_host_create", {"fields": fields},
                          "Создать хост в панели?"),
            "Создать хост в панели?")
    payload = take_confirm(actor, token, "panel_host_create")
    if payload is None:
        return _json_error("bad_confirm", 403)
    fields = payload.get("fields") or {}
    res = await rw_mod.create_host(fields)
    if not res.get("ok"):
        return _panel_error(res)
    data = res.get("data") or {}
    host = None
    if isinstance(data, dict) and data.get("uuid"):
        host = await _read_back_host(str(data["uuid"]))
    await _audit(actor, "panel_host_create",
                 f"inbound={fields.get('inboundUuid')} "
                 f"address={fields.get('address')}")
    return web.json_response({"ok": True, "host": host or data or fields})


async def panel_host_delete(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    uuid = request.match_info.get("uuid") or ""
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        return confirm_needed_response(
            issue_confirm(actor, "panel_host_delete", {"uuid": uuid},
                          "Удалить хост из панели?"),
            "Удалить хост из панели?")
    payload = take_confirm(actor, token, "panel_host_delete")
    if payload is None or payload.get("uuid") != uuid:
        return _json_error("bad_confirm", 403)
    res = await rw_mod.delete_host(uuid)
    if not res.get("ok"):
        return _panel_error(res)
    await _audit(actor, "panel_host_delete", f"host={uuid}")
    return web.json_response({"ok": True})


# ── Настройки панели ─────────────────────────────────────────────────────────

async def panel_settings_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from config import load_config
    cfg = load_config()
    # rw_token — секрет, только из ТГ; здесь его нет и не будет.
    return web.json_response({"rw_url": cfg.get("rw_url") or ""})


async def panel_settings_patch(request):
    from config import atomic_update
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    if "rw_url" not in body:
        return _json_error("bad_request")
    url = body["rw_url"]
    if not isinstance(url, str) or not url.startswith("https://"):
        return _json_error("bad_url")
    url = url.strip().rstrip("/")
    if len(url) <= len("https://"):
        return _json_error("bad_url")

    def _apply(cfg):
        cfg["rw_url"] = url
    atomic_update(_apply)
    await _audit(actor, "panel_settings", "rw_url updated")
    return web.json_response({"ok": True, "rw_url": url})


async def panel_settings_test(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    res = await rw_mod.test_connection()
    await _audit(actor, "panel_settings_test",
                 f"ok={bool(res.get('ok'))}")
    if not res.get("ok"):
        return _panel_error(res)
    return web.json_response({"ok": True, "squads": res.get("squads", 0)})


# ── Поддержка: тема, ответ, закрытие ─────────────────────────────────────────

async def _send_media(bot, *, chat_id, file_id, file_type, caption=None,
                      thread_id=None, parse_mode=None):
    """Фото/документ по file_id (file_id — из POST /media/upload).
    Близнец такого же хелпера в admin_users.py (DM) — держим оба,
    чтобы не тянуть кросс-импорт между модулями админки в тестах."""
    kw = {}
    if thread_id is not None:
        kw["message_thread_id"] = thread_id
    if caption:
        kw["caption"] = caption
    if parse_mode:
        kw["parse_mode"] = parse_mode
    if file_type == "photo":
        return await bot.send_photo(chat_id=chat_id, photo=file_id, **kw)
    return await bot.send_document(chat_id=chat_id, document=file_id, **kw)


async def media_get(request):
    """GET /media/{file_id} — файл из Telegram для истории темы:
    бот скачивает его по file_id и отдаёт браузеру. Только сессия
    админа; file_id — непрозрачный идентификатор Telegram, сам по себе
    файл не открывает (скачать его можно только токеном бота)."""
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    file_id = (request.match_info.get("file_id") or "").strip()
    if not file_id:
        return _json_error("bad_request")
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    try:
        tg_file = await bot.get_file(file_id)
        import io
        buf = io.BytesIO()
        await tg_file.download_to_memory(buf)
        data = buf.getvalue()
    except Exception as ex:
        logging.error("админка: media %s: %s", file_id[:8], ex)
        return _json_error("media_error", 502)
    import mimetypes
    import os
    path = getattr(tg_file, "file_path", "") or ""
    ctype, _ = mimetypes.guess_type(path)
    name = os.path.basename(path) or "file"
    return web.Response(body=data,
                        content_type=ctype or "application/octet-stream",
                        headers={"Content-Disposition":
                                 f'inline; filename="{name}"'})


async def support_topic_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    try:
        user_id = int(request.match_info.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if not user_id:
        return _json_error("bad_request")
    from core.database import (
        get_support_messages, get_support_topic,
        mark_ticket_read as mark_support_read,
    )
    topic = await get_support_topic(user_id)
    if not topic:
        return _json_error("no_topic", 404)
    msgs, pages = await get_support_messages(user_id)
    # mark_support_read — в core/database.py функция называется
    # mark_ticket_read: помечает сообщения юзера прочитанными.
    await mark_support_read(user_id)
    return web.json_response({
        "topic": {"user_id": user_id, "topic_id": topic[0],
                  "group_id": topic[1], "status": topic[2]},
        "messages": [{"text": m[0] or "", "from_admin": bool(m[1]),
                      "created_at": str(m[2] or ""),
                      "file_id": m[3], "file_type": m[4]} for m in msgs],
        "pages": pages,
    })


async def support_topic_reply(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        user_id = int(request.match_info.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if not user_id:
        return _json_error("bad_request")
    body = await _json_body(request)
    text = str(body.get("text") or "").strip()
    file_id = body.get("file_id")
    file_type = body.get("file_type")
    is_media = file_id is not None
    if is_media:
        if not isinstance(file_id, str) or not file_id.strip():
            return _json_error("bad_file_id")
        file_id = file_id.strip()
        if file_type not in ("photo", "document"):
            return _json_error("bad_file_type")
    elif not text:
        return _json_error("bad_request")
    close = bool(body.get("close"))
    from core.database import (
        add_support_message, get_support_topic, set_support_topic_status,
        touch_support_topic,
    )
    topic = await get_support_topic(user_id)
    if not topic:
        return _json_error("no_topic", 404)
    topic_id, group_id = int(topic[0]), int(topic[1])
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    delivered_via = None
    # Тот же путь, что support_bot.py on_group_message: ответ — в тему
    # юзера в группе поддержки, а бот поддержки копирует его юзеру.
    # Если основного бота нет в группе (отправка в тему падает) — шлём
    # ответ юзеру напрямую в личку основного бота.
    # Медиа — тем же путём: send_photo/send_document вместо send_message.
    if group_id:
        try:
            if is_media:
                await _send_media(bot, chat_id=group_id, file_id=file_id,
                                  file_type=file_type, caption=text or None,
                                  thread_id=topic_id)
            else:
                await bot.send_message(chat_id=group_id,
                                       message_thread_id=topic_id, text=text)
            delivered_via = "topic"
        except Exception as ex:
            logging.error("админка: support reply to topic: %s", ex)
    if delivered_via is None:
        try:
            if is_media:
                await _send_media(bot, chat_id=user_id, file_id=file_id,
                                  file_type=file_type, caption=text or None)
            else:
                await bot.send_message(chat_id=user_id, text=text)
            delivered_via = "dm"
        except Exception as ex:
            logging.error("админка: support reply DM: %s", ex)
            return _json_error("delivery_failed", 502)
    await add_support_message(user_id, text, from_admin=True,
                              file_id=file_id if is_media else None,
                              file_type=file_type if is_media else None)
    await touch_support_topic(user_id)
    if close:
        await set_support_topic_status(user_id, "closed")
    await _audit(actor, "support_reply",
                 f"user_id={user_id} via={delivered_via}"
                 + (f" {file_type}" if is_media else "")
                 + (" closed" if close else ""))
    return web.json_response({"ok": True, "delivered_via": delivered_via})


async def support_topic_close(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        user_id = int(request.match_info.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if not user_id:
        return _json_error("bad_request")
    from core.database import get_support_topic, set_support_topic_status
    topic = await get_support_topic(user_id)
    if not topic:
        return _json_error("no_topic", 404)
    await set_support_topic_status(user_id, "closed")
    bot = get_bot()
    if bot is not None:
        # Тот же текст, что support_bot.py cmd_close.
        try:
            await bot.send_message(
                chat_id=user_id,
                text="✅ <b>Обращение закрыто.</b>\n\n"
                     "<i>Если появится новый вопрос — просто напишите сюда.</i>",
                parse_mode="HTML")
        except Exception:
            pass
    await _audit(actor, "support_close", f"user_id={user_id}")
    return web.json_response({"ok": True})


# ── Настройки поддержки ──────────────────────────────────────────────────────

def _support_settings_snapshot() -> dict:
    from config import load_config
    cfg = load_config()
    return {
        "support_group_id": int(cfg.get("support_group_id") or 0),
        "log_channel_id": int(cfg.get("log_channel_id") or 0),
    }


async def _support_settings_full(actor) -> dict:
    """Снапшот экрана поддержки — как handle_support_group_settings
    в ТГ: группа, лог-канал, токен (только факт + юзернейм, сам
    токен никогда не возвращается) и статистика support_stats."""
    from config import load_config
    from core.database import support_stats
    cfg = load_config()
    try:
        stats = await support_stats()
    except Exception:
        stats = {"open_topics": 0, "new_yesterday": 0, "closed_total": 0}
    snap = _support_settings_snapshot()
    snap["token_set"] = bool(cfg.get("support_bot_token"))
    snap["support_bot_username"] = cfg.get("support_bot_username") or None
    snap["stats"] = stats
    snap["is_mark"] = bool(require_mark(actor))
    return snap


async def support_settings_get(request):
    try:
        actor = await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response({"settings": await _support_settings_full(actor)})


async def support_settings_patch(request):
    from config import atomic_update
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    clean = {}
    for key in ("support_group_id", "log_channel_id"):
        if key in body:
            val = body[key]
            if isinstance(val, bool) or not isinstance(val, int):
                return _json_error("bad_value")
            clean[key] = val
    if not clean:
        return _json_error("bad_request")

    def _apply(cfg):
        # 0 — очистить, как в ТГ (cfg.pop); иначе — записать.
        for key, val in clean.items():
            if val == 0:
                cfg.pop(key, None)
            else:
                cfg[key] = val
    atomic_update(_apply)
    await _audit(actor, "support_settings",
                 "keys: " + ", ".join(sorted(clean)))
    return web.json_response({"ok": True,
                              "settings": _support_settings_snapshot()})


# ── Токен бота поддержки ─────────────────────────────────────────────────────

_SUPPORT_TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")


async def _support_bot_username(token: str):
    """Юзернейм бота по токену — как в handlers/messages.py
    (AWAITING_SUPPORT_TOKEN): getMe, None если Telegram не ответил."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as _s:
            async with _s.get(
                    f"https://api.telegram.org/bot{token}/getMe",
                    timeout=aiohttp.ClientTimeout(total=15)) as _r:
                _d = await _r.json()
                if _d.get("ok"):
                    return _d["result"].get("username")
    except Exception:
        return None
    return None


async def support_token_set(request):
    """Сохранить токен бота поддержки (как ввод токена в ТГ-админке).
    Только Mark: смена токена переводит поддержку на другого бота
    и перезапускает сервис drebol-support-bot.
    Подтверждение: первый POST валидирует токен и узнаёт юзернейм
    через getMe, второй (с confirm_token) сохраняет и запускает
    сервис. Токен в confirm-payload не хранится — второй запрос
    присылает его заново в теле и валидируется повторно; в ответ,
    логи и аудит попадает только юзернейм, никогда сам токен."""
    from config import atomic_update
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    raw = body.get("token")
    if not isinstance(raw, str) or not _SUPPORT_TOKEN_RE.fullmatch(raw.strip()):
        return _json_error("bad_token")
    token = raw.strip()
    confirm_token = body.get("confirm_token") or ""
    if not confirm_token:
        username = await _support_bot_username(token)
        if username:
            summary = (f"Сохранить токен бота поддержки @{username}? "
                       "Сервис drebol-support-bot перезапустится.")
        else:
            summary = ("Токен похож на настоящий, но Telegram не подтвердил "
                       "юзернейм (не ответил). Сохранить всё равно? Сервис "
                       "drebol-support-bot перезапустится.")
        return confirm_needed_response(
            issue_confirm(actor, "support_token", {}, summary), summary)
    if take_confirm(actor, confirm_token, "support_token") is None:
        return _json_error("bad_confirm", 403)
    username = await _support_bot_username(token)

    def _apply(cfg):
        cfg["support_bot_token"] = token
        if username:
            cfg["support_bot_username"] = username
    atomic_update(_apply)
    # Сначала сохранить, потом запускать: сервис читает токен из
    # config.json при старте — как в handlers/messages.py.
    ok, detail = True, "active"
    try:
        from services.support_service import ensure_support_bot_running
        ok, detail = await ensure_support_bot_running()
    except Exception as ex:
        ok, detail = False, f"{type(ex).__name__}: {ex}"
    bot = get_bot()
    if bot is not None:
        try:
            from core.log_channel import send_log
            await send_log(bot, "🤖 Бот поддержки: токен сохранён"
                           + (f" (@{username})" if username else "")
                           + (" — сервис запущен" if ok
                              else " — сервис НЕ запустился"))
        except Exception as ex:
            logging.error("админка: support_token send_log: %s", ex)
    await _audit(actor, "support_token",
                 f"username=@{username}" if username else "username=?")
    snap = await _support_settings_full(actor)
    return web.json_response({
        "ok": True, "service_ok": bool(ok),
        "service_detail": "" if ok else str(detail),
        "settings": snap})


# ── Техработы и функции ──────────────────────────────────────────────────────

_MAINTENANCE_TEXT_MAX = 3500


def _maintenance_snapshot(actor) -> dict:
    """Состояние экрана «Техработы и функции» — как mnt_menu в ТГ
    (core/maintenance.py): переключатель техработ, текст для
    пользователей и тумблеры функций из features_off."""
    from config import load_config
    from core import maintenance as mnt_mod
    cfg = load_config()
    off = set(cfg.get("features_off") or [])
    return {
        "maintenance_enabled": bool(cfg.get("maintenance_enabled", False)),
        "maintenance_text": mnt_mod.maintenance_text(),
        "text_custom": bool(cfg.get("maintenance_text")),
        "features": [
            {"key": key, "emoji": emoji, "name": name,
             "enabled": key not in off}
            for key, (emoji, name, _cbs) in mnt_mod.FEATURES.items()
        ],
        "is_mark": bool(require_mark(actor)),
    }


async def maintenance_get(request):
    try:
        actor = await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response(_maintenance_snapshot(actor))


async def maintenance_toggle(request):
    """Включить/выключить техработы (как mnt_toggle в ТГ).
    Только Mark, с подтверждением: закрывает бота для пользователей."""
    from config import atomic_update, load_config
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    enabled = bool(load_config().get("maintenance_enabled", False))
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        summary = ("Выключить техработы? Бот снова откроется для "
                   "пользователей." if enabled else
                   "Включить техработы? Бот закроется для пользователей.")
        return confirm_needed_response(
            issue_confirm(actor, "maintenance_toggle", {}, summary),
            summary)
    payload = take_confirm(actor, token, "maintenance_toggle")
    if payload is None:
        return _json_error("bad_confirm", 403)

    def _apply(cfg):
        cfg["maintenance_enabled"] = not bool(
            cfg.get("maintenance_enabled", False))
    atomic_update(_apply)
    now_on = bool(load_config().get("maintenance_enabled", False))
    bot = get_bot()
    if bot is not None:
        try:
            from core.log_channel import send_log
            await send_log(bot, "🛠 Техработы включены" if now_on
                           else "✅ Техработы выключены")
        except Exception as ex:
            logging.error("админка: maintenance_toggle send_log: %s", ex)
    await _audit(actor, "maintenance_toggle",
                 "on" if now_on else "off")
    return web.json_response({"ok": True,
                              **_maintenance_snapshot(actor)})


async def maintenance_feature(request):
    """Выключить/включить одну функцию (как mnt_feature:key в ТГ).
    Только Mark, без подтверждения — как promo_toggle."""
    from config import atomic_update, load_config
    from core import maintenance as mnt_mod
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    key = str(body.get("key") or "")
    if key not in mnt_mod.FEATURES:
        return _json_error("bad_feature")
    # Тот же путь, что handle_feature_toggle в core/maintenance.py:
    # features_off — отсортированный список выключенных ключей.
    off = set(load_config().get("features_off") or [])
    now_off = key not in off
    if now_off:
        off.add(key)
    else:
        off.discard(key)

    def _apply(cfg):
        cfg["features_off"] = sorted(off)
    atomic_update(_apply)
    name = mnt_mod.FEATURES[key][1]
    bot = get_bot()
    if bot is not None:
        try:
            from core.log_channel import send_log
            await send_log(bot, f"⏸ Выключена функция «{name}»" if now_off
                           else f"▶️ Включена функция «{name}»")
        except Exception as ex:
            logging.error("админка: maintenance_feature send_log: %s", ex)
    await _audit(actor, "maintenance_feature",
                 f"{key}={'off' if now_off else 'on'}")
    return web.json_response({"ok": True,
                              **_maintenance_snapshot(actor)})


async def maintenance_text(request):
    """Текст техработ (как apply_maintenance_text в ТГ): «-» или пусто —
    вернуть стандартный; иначе разметка проверяется предпросмотром
    Марку в Telegram — битая разметка не сохраняется. Только Mark."""
    from config import atomic_update
    from core import maintenance as mnt_mod
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    raw = body.get("text")
    if raw is None or not isinstance(raw, str):
        return _json_error("bad_text")
    raw = raw.strip()
    if raw == "" or raw == "-":
        new = None
    else:
        if len(raw) > _MAINTENANCE_TEXT_MAX:
            return _json_error("bad_text")
        new = raw
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    tg_id = actor.get("tg_id")
    if not tg_id:
        return _json_error("mark_only", 403)
    # Предпросмотр — та же проверка, что в ТГ: Telegram должен принять
    # разметку, иначе текст не сохраняется.
    try:
        await bot.send_message(
            chat_id=tg_id,
            text=(f"✅ <b>{'Вернул стандартный текст' if new is None else 'Текст сохранён'}</b>\n"
                  f"<i>Так его увидят пользователи:</i>\n\n"
                  f"{new or mnt_mod.DEFAULT_TEXT}"),
            parse_mode="HTML")
    except Exception as ex:
        return web.json_response(
            {"error": "bad_html", "details": str(ex)[:200]}, status=400)

    def _apply(cfg):
        if new is None:
            cfg.pop("maintenance_text", None)
        else:
            cfg["maintenance_text"] = new
    atomic_update(_apply)
    await _audit(actor, "maintenance_text",
                 "reset" if new is None else f"len={len(new)}")
    return web.json_response({"ok": True,
                              **_maintenance_snapshot(actor)})


# ── Помощники: добавление, права, удаление (Mark-only) ───────────────────────

async def _helper_welcome(bot, tg_id):
    """Приветствие нового помощника — как handle_helper_input в ТГ:
    одноразовое приглашение в группу поддержки + DM с кнопками.
    Возвращает (invite_created, dm_sent); ошибки бота не роняют вызов."""
    if bot is None:
        return False, False
    invite = await staff_mod.make_support_invite(bot, tg_id)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    if invite:
        rows.append([InlineKeyboardButton("📩 Вступить в группу поддержки", url=invite)])
    rows.append([InlineKeyboardButton("🛡 Панель поддержки", callback_data="admin_panel")])
    try:
        await bot.send_message(
            chat_id=tg_id,
            text=("🛡 <b>Вам выдан доступ помощника Drebol VPN</b>\n\n"
                  "<blockquote>Поддержка живёт в отдельной группе: там лежат обращения "
                  "людей по темам. Вступи в группу по кнопке ниже — и сможешь отвечать "
                  "людям прямо в темах, бот поддержки доставит ответ человеку.</blockquote>\n\n"
                  "<i>Панель помощника — в главном меню бота, раздел «🛟 Поддержка» "
                  "покажет твой статус в группе.</i>"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows))
        return bool(invite), True
    except Exception:
        return bool(invite), False


async def helpers_add(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    # Цель — TG ID или @username, как handle_helper_input в ТГ;
    # tg_id int — legacy-поле фронта до этого прохода.
    target = body.get("target")
    if target is None:
        target = body.get("tg_id")
    raw = str(target or "").strip()
    if not raw:
        return _json_error("bad_request")
    from core.database import get_user_info, find_user_by_username
    u = await get_user_info(int(raw)) if raw.isdigit() else await find_user_by_username(raw)
    if not u:
        return _json_error("user_not_found", 404)
    tg_id = int(u[0])
    from config import ADMIN_ID
    if tg_id == ADMIN_ID:
        return _json_error("is_admin")
    if tg_id in staff_mod.helper_ids():
        await _audit(actor, "helpers_add", f"tg_id={tg_id} already")
        return web.json_response({"ok": True, "already": True, "tg_id": tg_id,
                                  "perms": sorted(staff_mod.helper_perms(tg_id))})
    # Тот же путь, что features/staff.py handle_helper_input: в список
    # + права по умолчанию (карточки людей, сообщения людям, поддержка).
    staff_mod._save_ids(staff_mod.helper_ids() + [tg_id])
    staff_mod.set_helper_perms(tg_id, staff_mod.DEFAULT_PERMS)
    bot = get_bot()
    invite_created, dm_sent = await _helper_welcome(bot, tg_id)
    if bot is not None:
        try:
            from core.log_channel import send_log
            await send_log(bot, f"👥 Новый помощник: {staff_mod._name(u, tg_id)} · <code>{tg_id}</code>")
        except Exception as ex:
            logging.error("админка: helpers_add send_log: %s", ex)
    await _audit(actor, "helpers_add", f"tg_id={tg_id}")
    return web.json_response({"ok": True, "tg_id": tg_id,
                              "perms": sorted(staff_mod.helper_perms(tg_id)),
                              "invite_sent": bool(invite_created and dm_sent),
                              "dm_sent": dm_sent})


async def helpers_perm(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    try:
        tg_id = int(request.match_info.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    if not tg_id:
        return _json_error("bad_request")
    body = await _json_body(request)
    perm = str(body.get("perm") or "")
    if perm not in staff_mod.PERMS:
        return _json_error("bad_perm")
    if tg_id not in staff_mod.helper_ids():
        return _json_error("not_helper", 404)
    perms = staff_mod.toggle_helper_perm(tg_id, perm)
    await _audit(actor, "helpers_perm",
                 f"tg_id={tg_id} perm={perm} on={perm in perms}")
    return web.json_response({"ok": True, "tg_id": tg_id, "perm": perm,
                              "perms": sorted(perms),
                              "enabled": perm in perms})


async def helpers_delete(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    try:
        tg_id = int(request.match_info.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    if not tg_id:
        return _json_error("bad_request")
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        if tg_id not in staff_mod.helper_ids():
            return _json_error("not_helper", 404)
        return confirm_needed_response(
            issue_confirm(actor, "helpers_delete", {"tg_id": tg_id},
                          f"Убрать помощника {tg_id}?"),
            f"Убрать помощника {tg_id}?")
    payload = take_confirm(actor, token, "helpers_delete")
    if payload is None or int(payload.get("tg_id") or 0) != tg_id:
        return _json_error("bad_confirm", 403)
    # Тот же путь, что features/staff.py handle_helper_del: из списка
    # и права вместе с ним.
    from core.database import get_user_info
    u = await get_user_info(tg_id)
    staff_mod._forget(tg_id)
    # и из группы поддержки — иначе продолжит отвечать людям в темах
    bot = get_bot()
    kicked = (await staff_mod.kick_from_support_group(bot, tg_id)
              if bot is not None else False)
    dm_sent = False
    if bot is not None:
        try:
            await bot.send_message(
                chat_id=tg_id,
                text="🛡 <b>Доступ помощника снят</b>"
                     + ("\n\n<i>Вы также выведены из группы поддержки.</i>" if kicked else ""),
                parse_mode="HTML")
            dm_sent = True
        except Exception:
            dm_sent = False
        try:
            from core.log_channel import send_log
            await send_log(bot, f"👥 Помощник убран: {staff_mod._name(u, tg_id)} · <code>{tg_id}</code>"
                           + (" · выведен из группы поддержки" if kicked else ""))
        except Exception as ex:
            logging.error("админка: helpers_delete send_log: %s", ex)
    await _audit(actor, "helpers_delete",
                 f"tg_id={tg_id}" + (" kicked_from_group" if kicked else ""))
    return web.json_response({"ok": True, "kicked_from_group": kicked,
                              "dm_sent": dm_sent})


# ── Сайт: удаление и тексты ──────────────────────────────────────────────────

async def site_delete(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        return confirm_needed_response(
            issue_confirm(actor, "site_delete", {},
                          "Удалить сайт с сервера?"),
            "Удалить сайт с сервера?")
    if take_confirm(actor, token, "site_delete") is None:
        return _json_error("bad_confirm", 403)
    try:
        res = await site_mod.remove_site()
    except Exception as ex:
        logging.error("админка: site delete: %s", ex)
        return _json_error("delete_failed", 502)
    if not res.get("ok"):
        await _audit(actor, "site_delete_failed", "")
        return _json_error("delete_failed", 502)
    await _audit(actor, "site_delete", "")
    return web.json_response({"ok": True, "site": _site_snapshot()})


def _site_texts_snapshot() -> dict:
    from config import load_config
    cfg = load_config()
    return {
        "texts": cfg.get("site_texts") or {},
        "sections": {
            sec_id: {"title": title,
                     "fields": [{"field": f, "label": name}
                                for f, name in items]}
            for sec_id, (title, items) in site_mod.SITE_SECTIONS.items()
        },
    }


async def site_texts_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response(_site_texts_snapshot())


async def site_texts_patch(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    field = str(body.get("field") or "")
    text = body.get("text")
    allowed = {f for _, items in site_mod.SITE_SECTIONS.values()
               for f, _ in items}
    if field not in allowed or not isinstance(text, str):
        return _json_error("bad_field")
    site_mod.save_site_text(field, text)
    await _audit(actor, "site_texts", f"field={field}")
    snap = _site_texts_snapshot()
    snap["note"] = ("Тексты применятся при следующем деплое сайта — "
                    "деплой делается отдельно.")
    return web.json_response({"ok": True, **snap})


async def site_texts_reset(request):
    """Сбросить все тексты сайта к стандартным — паритет с ТГ
    (handle_site_text_reset_do: cfg['site_texts'] = {}).
    С подтверждением, как сброс в ТГ (handle_site_text_reset_ask)."""
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        return confirm_needed_response(
            issue_confirm(
                actor, "site_texts_reset", {},
                "Сбросить абсолютно все тексты сайта к исходным "
                "стандартным значениям?"),
            "Сбросить абсолютно все тексты сайта к исходным "
            "стандартным значениям?")
    payload = take_confirm(actor, token, "site_texts_reset")
    if payload is None:
        return _json_error("bad_confirm", 403)
    from config import atomic_update

    def _clear(cfg):
        cfg["site_texts"] = {}

    atomic_update(_clear)
    await _audit(actor, "site_texts_reset", "")
    snap = _site_texts_snapshot()
    snap["note"] = ("Все тексты сброшены к стандартным — применится "
                    "при следующем деплое сайта.")
    return web.json_response({"ok": True, **snap})


# ── Яндекс Клауд (только чтение) ─────────────────────────────────────────────

# Тот же текст, что services/remnawave.py handle_rw_yandex_sub: ссылка
# подписки sub.drbl.tech через CDN Яндекса — основная, key.drbl.tech — запасной адрес.
# Актуализировано под 2026-11-26: кнопка «🪞 Зеркало подписки» в боте
# убрана 2026-11-18 (пользователям выдаётся только sub.drbl.tech);
# зеркало живёт в старом аккаунте cloud-pratokwau, перенос ресурса
# sub на новый аккаунт cloud-frost-287 — в работе.
YANDEX_MIRROR_LINES = [
    "Страница подписки — зеркало через CDN",
    "",
    "sub.drbl.tech — основная ссылка подписки, которую бот даёт пользователям.",
    "key.drbl.tech — запасной адрес (origin подписки, НЕ трогать).",
    "Кнопка «🪞 Зеркало подписки» из бота убрана 2026-11-18 —",
    "пользователям выдаётся только sub.drbl.tech.",
    "Кэш полностью ВЫКЛЮЧЕН — иначе один юзер получит чужой конфиг.",
    "",
    "Сейчас зеркало живёт в СТАРОМ аккаунте (cloud-pratokwau).",
    "Перенос на новый аккаунт (cloud-frost-287) — в работе:",
    "сертификат для sub.drbl.tech выпущен, группа источников",
    "«sub-key» создана. Осталось: удалить старый ресурс и создать",
    "новый в cloud-frost-287, переключить DNS и проверить.",
    "Пока перенос не завершён — старый ресурс НЕ трогать.",
    "",
    "1. Сертификат (Certificate Manager)",
    "Для зеркала нужен свой сертификат — для sub.drbl.tech.",
    "Остальные домены проекта (key, vpn, panel) — на Let's Encrypt на сервере, их не трогаем.",
    "Certificate Manager → «Создать сертификат»:",
    "Имя: sub-drbl-tech",
    "Домены: sub.drbl.tech",
    "Тип проверки: DNS.",
    "Нажми «Создать» — Яндекс покажет TXT-запись.",
    "В DNS добавь TXT _acme-challenge.sub.drbl.tech со значением от Яндекса.",
    "Дождись статуса Issued.",
    "",
    "2. Ресурс CDN — шаг 1 «Основные параметры»",
    "Cloud CDN → «Создать ресурс»:",
    "Источник: key.drbl.tech",
    "Протокол для источника: HTTPS.",
    "Заголовок Host: «Свое значение» = key.drbl.tech.",
    "(«Основное доменное имя» — это домен самого ресурса, не источника.)",
    "SNI вручную: выкл.",
    "Доменное имя: sub.drbl.tech",
    "Тип сертификата: «Из Certificate Manager» → sub-drbl-tech.",
    "Нажми «Далее».",
    "",
    "3. Ресурс CDN — шаг 2 «Кэширование»",
    "Кэширование в CDN: ВЫКЛЮЧИТЬ (тумблер).",
    "Кэш браузера: выкл.",
    "(В ссылке токен юзера — кэш даст чужой конфиг.)",
    "Нажми «Далее».",
    "",
    "4. Ресурс CDN — шаг 3 «Заголовки»",
    "Заголовки: ничего не добавлять (x-hwid проходит сам).",
    "Скрытие заголовков: «Не скрывать».",
    "CORS: «Не добавлять».",
    "Методы: GET, HEAD.",
    "Кастомный HTTP-ответ: выкл.",
    "Нажми «Далее», проверь сводку и «Создать ресурс».",
    "",
    "5. DNS",
    "На вкладке «Обзор» ресурса → «Настройки DNS»: скопируй домен вида",
    "xxx.topology.gslb.yccdn.ru.",
    "В DNS: CNAME sub.drbl.tech → этот домен.",
    "Подожди пару минут, пока edge подхватит сертификат",
    "(сразу может дать ERR_CONNECTION_CLOSED — это нормально).",
    "",
    "6. Проверка",
    "curl https://sub.drbl.tech/<uuid> → 200.",
    "Решающий тест: INCY на МТС без VPN обновляет подписку",
    "по ссылке sub.drbl.tech.",
    "",
    "Цена: 150 ₽/мес за ресурс (150 ГБ + 100 млн запросов), сверх — ~1,05 ₽/ГБ.",
    "Основная ссылка — sub.drbl.tech, key.drbl.tech — запасной адрес.",
]


# Тот же текст, что services/remnawave.py handle_rw_yandex_whitelist:
# белые списки Yandex Cloud CDN — в ресурсе и на origin. Plain-text,
# без HTML-тегов ТГ (<b>/<code> сняты — фронт экранирует сам).
# Актуализировано под нынешнюю инфраструктуру (в ТГ текст
# устарел, код бота не трогается): ресурсы нового аккаунта
# cloud-frost-287 — sub/static/assets/media.drbl.tech
# (de1cdn/se1cdn/fin1cdn/ro1cdn — старый аккаунт); дубликаты [CDN] —
# Германия, Швеция и Латвия (Румыния и Финляндия убраны).
YANDEX_WHITELIST_LINES = [
    "Белые списки",
    "",
    "В Yandex Cloud CDN белые списки — в двух местах: поле в самом ресурсе",
    "и список IP edge-серверов для origin.",
    "",
    "1. В ресурсе CDN — ВЫКЛЮЧЕНО",
    "Шаг 1 «Основные параметры», поля «Доступ по IP-адресам»,",
    "«Доступ по странам», «Доступ по защищённому токену» — выкл.",
    "для ВСЕХ наших ресурсов: sub.drbl.tech, static.drbl.tech, assets.drbl.tech, media.drbl.tech.",
    "Клиенты заходят с любого IP по всей России — включишь и впишешь",
    "свой IP, отрежешь всех остальных.",
    "",
    "2. Белый список на origin — IP Яндекса",
    "Origin (нода) должен отвечать ТОЛЬКО edge-серверам Яндекса,",
    "а не кому попало напрямую. Официальный список:",
    "https://tech.cdn.yandex.net/prefixes/yc.json",
    "(дока Яндекса «Диапазоны публичных IP-адресов» → Cloud CDN).",
    "Список меняется — скачивать свежий при каждом применении.",
    "",
    "3. Применить на ноде (дубликат [CDN], порт 8880)",
    "На сервере ноды (Германия, Швеция, Латвия — дубликат [CDN]):",
    "ufw status",
    "Если выключен — сначала ufw allow 22/tcp, потом",
    "ufw enable, иначе потеряешь SSH.",
    "Затем разрешить Яндекс на 8880:",
    "curl -s https://tech.cdn.yandex.net/prefixes/yc.json | python3 -c \"import json,sys; print('\\n'.join(p for p in json.load(sys.stdin)['prefixes'] if ':' not in p))\" | while read ip; do ufw allow from $ip to any port 8880 proto tcp; done",
    "Правило для 12222 (только IP панели) и порт 22 — НЕ трогать.",
    "Порты основной ноды (VTR, HY2) — тоже не трогать: они прямые, не через CDN.",
    "",
    "4. body-brown (подписка) — НЕ ставится",
    "На 443 висят ещё панель и сайт — белый список на файрволе",
    "отрежет и их. Для зеркала sub.drbl.tech он не нужен:",
    "клиенты идут на sub.drbl.tech, а key.drbl.tech напрямую и так режет DPI.",
    "",
    "5. Проверка",
    "Напрямую на origin-порт с обычного IP — таймаут (закрыто).",
    "Через CDN-домен (assets.drbl.tech:443) — подключается.",
    "Это hardening, без него всё работает — делать после того,",
    "как нода [CDN] уже зелёная в панели.",
]



# Тот же текст, что handlers/yandex_cloud.py handle_yc_resources:
# ресурсы CDN нового аккаунта cloud-frost-287, их origins и цепочка
# «CDN → nginx → VXC» на ноде. Plain-text, без HTML-тегов ТГ.
# Отличие от ТГ: media уже построен 2026-11-26 (ID ресурса
# bc8rx4x747fl7l27hpop), поэтому «строится» убрано.
YANDEX_RESOURCES_LINES = [
    "Ресурсы и ноды",
    "",
    "Папка в Yandex Cloud: cloud-frost-287 (новый аккаунт,",
    "миграция 2026-11-26). Все ресурсы Active,",
    "сертификаты выпущены. Общий CNAME для всех ресурсов:",
    "bc6681bc57f8bf03.topology.gslb.yccdn.ru",
    "",
    "Ресурсы и их origins",
    "• static (bc8rhsx4snr37xstoxao) → 144.31.223.252",
    "  по HTTP, Host static.drbl.tech (Германия, хост «- 2»);",
    "• assets (bc8rjuvq5ztilk7zwrp2) → 81.90.21.84",
    "  по HTTP, Host — как у клиента (Швеция, хост «- 2»);",
    "• sub → key.drbl.tech по HTTPS",
    "  (страница подписки, перенос на новый аккаунт);",
    "• media (bc8rx4x747fl7l27hpop) → 109.248.161.146",
    "  по HTTP, Host media.drbl.tech (Латвия, хост «- 2»).",
    "",
    "Цепочка на ноде",
    "CDN приходит на nginx ноды: порт 80, server_name —",
    "домен ресурса страны (static/assets/media). Дальше location /drbl7f3a",
    "→ proxy_pass 127.0.0.1:8880 — это XHTTP-инбаунд",
    "VXC-<Country>-1 в панели Remnawave (packet-up, GET-uplink).",
    "",
    "«Welcome to nginx» на голом *cdn-домене — НОРМА: рабочий",
    "путь — секретный /drbl7f3a, корень домена — заглушка.",
    "",
    "В панели VXC-инбаунд должен быть выбран на CDN-ноде страны",
    "(1 из 5 инбаундов) — иначе цепочка мертва при живом CDN.",
]


# Тот же текст, что handlers/yandex_cloud.py handle_yc_dns: DNS зоны
# drbl.tech и типовые поломки. Отличие от ТГ: media уже построен и
# резолвится, поэтому он есть в CNAME-строке; sub пока CNAME на
# старый аккаунт — переезд в работе.
YANDEX_DNS_LINES = [
    "DNS и ремонт",
    "",
    "Зона drbl.tech ведётся в SpaceWeb. Записи CDN-части:",
    "• static, assets, media — CNAME на",
    "  bc6681bc57f8bf03.topology.gslb.yccdn.ru;",
    "• sub — пока CNAME на старый аккаунт (cloud-pratokwau),",
    "  переезд на новый — в работе;",
    "• denode1 — A 144.31.223.252;",
    "• senode1 — A 81.90.21.84;",
    "• key — A 144.31.223.252.",
    "key.drbl.tech — origin подписки, НЕ трогать.",
    "",
    "Типовые поломки (реальный ремонт 2026-11-22)",
    "",
    "1. Нет CNAME у *cdn-домена — страна умирает на резолве,",
    "в приложении n/a. Так было с de1cdn: записи просто не",
    "существовало. Лечение: добавить CNAME на gslb (выше)",
    "и подождать распространения DNS.",
    "",
    "2. На ноде нет nginx-location /drbl7f3a — CDN отвечает",
    "(«Welcome to nginx»), но трафик не идёт. Так было с FI и SE.",
    "Конфиг — как на немецкой ноде: listen 80, server_name —",
    "cdn-домен страны, location /drbl7f3a → proxy_pass",
    "127.0.0.1:8880, proxy_http_version 1.1, таймауты 86400s,",
    "proxy_buffering off, location / → 404. После правки:",
    "nginx -t && systemctl reload nginx.",
    "",
    "3. VXC не выбран на CDN-ноде — в карточке CDN-ноды страны",
    "в панели должен быть отмечен инбаунд VXC-<Country>-1 (1/5).",
]


# Тот же текст, что handlers/yandex_cloud.py handle_yc_billing: биллинг
# Yandex CDN и связь с LTE-лимитами подписок в боте. Дословно.
YANDEX_BILLING_LINES = [
    "Биллинг Yandex CDN",
    "",
    "Пакеты",
    "150 ₽/мес за ресурс. Сейчас в новом аккаунте 2 ресурса",
    "(static, assets) = 300 ₽/мес; с sub и media будет",
    "4 ресурса = 600 ₽/мес.",
    "В пакет каждого ресурса включено: 150 ГБ исходящего",
    "трафика + 100 млн запросов. Пакеты между ресурсами",
    "НЕ переносятся — неиспользованное сгорает.",
    "",
    "Сверх пакета — оплата за ГБ, но ставка в консоли",
    "не отображается: смотреть детализацию биллинга.",
    "",
    "Сейчас",
    "Новый аккаунт (cloud-frost-287): стартовый грант",
    "4 000 ₽ до 25.01.2027 покрывает пакеты и трафик.",
    "Старый аккаунт после переноса sub выводится из работы.",
    "",
    "Связь с ботом",
    "У подписок есть месячный LTE-лимит: пресеты paid_preset_lte",
    "и preset_lte (настройки подписок), изначально — 30 ГБ/мес.",
    "При превышении лимита бот перекидывает подписку",
    "в fallback-сквад. Лимит можно полностью отключить",
    "тумблером «Лимит LTE» (Платные подписки → «Сквад после",
    "конца LTE») — тогда CDN-варианты доступны всем без учёта.",
]


# Структурированные страницы Yandex Cloud для веба (рендер вместо <pre>):
# блок: {"t": "p"|"h"|"note"|"warn"|"rows"|"table"|"steps", ...}
#   p     — абзац {"text"}
#   h     — подзаголовок {"text"}
#   note  — примечание {"text"}
#   warn  — предупреждение {"text"}
#   rows  — таблица «ключ — значение» {"rows": [{"k", "v", "copy"}]},
#           copy=True — у значения кнопка «Копировать»
#   table — таблица {"cols": [...], "rows": [[...]], "mono": [индексы
#           колонок моноширинным шрифтом]}
#   steps — нумерованные шаги {"steps": [{"title", "body": [...]}]},
#           элемент body — строка, {"code": "..."} или
#           {"link": {"text": "...", "href": "..."}}
# Факты и порядок — те же, что в YANDEX_*_LINES выше; текст
# переразложен по блокам, ничего не добавлено и не выброшено.
YANDEX_RESOURCES_BLOCKS = [
    {"t": "p", "text": "Папка в Yandex Cloud: cloud-frost-287 (новый аккаунт, миграция 2026-11-26). Все ресурсы Active, сертификаты выпущены."},
    {"t": "rows", "rows": [
        {"k": "Общий CNAME для всех ресурсов", "v": "bc6681bc57f8bf03.topology.gslb.yccdn.ru", "copy": True},
    ]},
    {"t": "h", "text": "Ресурсы и их origins"},
    {"t": "table", "cols": ["Ресурс", "ID", "Origin", "Хост «- 2»"], "mono": [1], "rows": [
        ["static", "bc8rhsx4snr37xstoxao", "144.31.223.252 по HTTP, Host static.drbl.tech", "Германия"],
        ["assets", "bc8rjuvq5ztilk7zwrp2", "81.90.21.84 по HTTP, Host — как у клиента", "Швеция"],
        ["sub", "—", "key.drbl.tech по HTTPS", "Страница подписки, перенос на новый аккаунт"],
        ["media", "bc8rx4x747fl7l27hpop", "109.248.161.146 по HTTP, Host media.drbl.tech", "Латвия"],
    ]},
    {"t": "h", "text": "Цепочка на ноде"},
    {"t": "p", "text": "CDN приходит на nginx ноды: порт 80, server_name — домен ресурса страны (static/assets/media). Дальше location /drbl7f3a → proxy_pass 127.0.0.1:8880 — это XHTTP-инбаунд VXC-<Country>-1 в панели Remnawave (packet-up, GET-uplink)."},
    {"t": "note", "text": "«Welcome to nginx» на голом *cdn-домене — НОРМА: рабочий путь — секретный /drbl7f3a, корень домена — заглушка."},
    {"t": "warn", "text": "В панели VXC-инбаунд должен быть выбран на CDN-ноде страны (1 из 5 инбаундов) — иначе цепочка мертва при живом CDN."},
]

YANDEX_DNS_BLOCKS = [
    {"t": "p", "text": "Зона drbl.tech ведётся в SpaceWeb. Записи CDN-части:"},
    {"t": "rows", "rows": [
        {"k": "static, assets, media — CNAME", "v": "bc6681bc57f8bf03.topology.gslb.yccdn.ru", "copy": True},
        {"k": "sub", "v": "пока CNAME на старый аккаунт (cloud-pratokwau), переезд на новый — в работе"},
        {"k": "denode1", "v": "A 144.31.223.252", "copy": True},
        {"k": "senode1", "v": "A 81.90.21.84", "copy": True},
        {"k": "key", "v": "A 144.31.223.252", "copy": True},
    ]},
    {"t": "warn", "text": "key.drbl.tech — origin подписки, НЕ трогать."},
    {"t": "h", "text": "Типовые поломки (реальный ремонт 2026-11-22)"},
    {"t": "steps", "steps": [
        {"title": "Нет CNAME у *cdn-домена", "body": [
            "Страна умирает на резолве, в приложении n/a. Так было с de1cdn: записи просто не существовало.",
            "Лечение: добавить CNAME на gslb (выше) и подождать распространения DNS.",
        ]},
        {"title": "На ноде нет nginx-location /drbl7f3a", "body": [
            "CDN отвечает («Welcome to nginx»), но трафик не идёт. Так было с FI и SE.",
            "Конфиг — как на немецкой ноде: listen 80, server_name — cdn-домен страны, location /drbl7f3a → proxy_pass 127.0.0.1:8880, proxy_http_version 1.1, таймауты 86400s, proxy_buffering off, location / → 404.",
            "После правки:",
            {"code": "nginx -t && systemctl reload nginx"},
        ]},
        {"title": "VXC не выбран на CDN-ноде", "body": [
            "В карточке CDN-ноды страны в панели должен быть отмечен инбаунд VXC-<Country>-1 (1/5).",
        ]},
    ]},
]

YANDEX_BILLING_BLOCKS = [
    {"t": "h", "text": "Пакеты"},
    {"t": "p", "text": "150 ₽/мес за ресурс. Сейчас в новом аккаунте 2 ресурса (static, assets) = 300 ₽/мес; с sub и media будет 4 ресурса = 600 ₽/мес."},
    {"t": "p", "text": "В пакет каждого ресурса включено: 150 ГБ исходящего трафика + 100 млн запросов. Пакеты между ресурсами НЕ переносятся — неиспользованное сгорает."},
    {"t": "p", "text": "Сверх пакета — оплата за ГБ, но ставка в консоли не отображается: смотреть детализацию биллинга."},
    {"t": "h", "text": "Сейчас"},
    {"t": "p", "text": "Новый аккаунт (cloud-frost-287): стартовый грант 4 000 ₽ до 25.01.2027 покрывает пакеты и трафик. Старый аккаунт после переноса sub выводится из работы."},
    {"t": "h", "text": "Связь с ботом"},
    {"t": "p", "text": "У подписок есть месячный LTE-лимит: пресеты paid_preset_lte и preset_lte (настройки подписок), изначально — 30 ГБ/мес. При превышении лимита бот перекидывает подписку в fallback-сквад. Лимит можно полностью отключить тумблером «Лимит LTE» (Платные подписки → «Сквад после конца LTE») — тогда CDN-варианты доступны всем без учёта."},
]

YANDEX_MIRROR_BLOCKS = [
    {"t": "p", "text": "sub.drbl.tech — основная ссылка подписки, которую бот даёт пользователям. key.drbl.tech — запасной адрес (origin подписки, НЕ трогать). Кнопка «🪞 Зеркало подписки» из бота убрана 2026-11-18 — пользователям выдаётся только sub.drbl.tech."},
    {"t": "note", "text": "Кэш полностью ВЫКЛЮЧЕН — иначе один юзер получит чужой конфиг."},
    {"t": "warn", "text": "Сейчас зеркало живёт в СТАРОМ аккаунте (cloud-pratokwau). Перенос на новый аккаунт (cloud-frost-287) — в работе: сертификат для sub.drbl.tech выпущен, группа источников «sub-key» создана. Осталось: удалить старый ресурс и создать новый в cloud-frost-287, переключить DNS и проверить. Пока перенос не завершён — старый ресурс НЕ трогать."},
    {"t": "steps", "steps": [
        {"title": "Сертификат (Certificate Manager)", "body": [
            "Для зеркала нужен свой сертификат — для sub.drbl.tech. Остальные домены проекта (key, vpn, panel) — на Let's Encrypt на сервере, их не трогаем.",
            "Certificate Manager → «Создать сертификат»: Имя: sub-drbl-tech, Домены: sub.drbl.tech, Тип проверки: DNS.",
            "Нажми «Создать» — Яндекс покажет TXT-запись. В DNS добавь TXT _acme-challenge.sub.drbl.tech со значением от Яндекса. Дождись статуса Issued.",
        ]},
        {"title": "Ресурс CDN — шаг 1 «Основные параметры»", "body": [
            "Cloud CDN → «Создать ресурс»: Источник: key.drbl.tech, Протокол для источника: HTTPS. Заголовок Host: «Свое значение» = key.drbl.tech. («Основное доменное имя» — это домен самого ресурса, не источника.) SNI вручную: выкл. Доменное имя: sub.drbl.tech. Тип сертификата: «Из Certificate Manager» → sub-drbl-tech. Нажми «Далее».",
        ]},
        {"title": "Ресурс CDN — шаг 2 «Кэширование»", "body": [
            "Кэширование в CDN: ВЫКЛЮЧИТЬ (тумблер). Кэш браузера: выкл. (В ссылке токен юзера — кэш даст чужой конфиг.) Нажми «Далее».",
        ]},
        {"title": "Ресурс CDN — шаг 3 «Заголовки»", "body": [
            "Заголовки: ничего не добавлять (x-hwid проходит сам). Скрытие заголовков: «Не скрывать». CORS: «Не добавлять». Методы: GET, HEAD. Кастомный HTTP-ответ: выкл. Нажми «Далее», проверь сводку и «Создать ресурс».",
        ]},
        {"title": "DNS", "body": [
            "На вкладке «Обзор» ресурса → «Настройки DNS»: скопируй домен вида xxx.topology.gslb.yccdn.ru. В DNS: CNAME sub.drbl.tech → этот домен. Подожди пару минут, пока edge подхватит сертификат (сразу может дать ERR_CONNECTION_CLOSED — это нормально).",
        ]},
        {"title": "Проверка", "body": [
            {"code": "curl https://sub.drbl.tech/<uuid> → 200"},
            "Решающий тест: INCY на МТС без VPN обновляет подписку по ссылке sub.drbl.tech.",
        ]},
    ]},
    {"t": "p", "text": "Цена: 150 ₽/мес за ресурс (150 ГБ + 100 млн запросов), сверх — ~1,05 ₽/ГБ. Основная ссылка — sub.drbl.tech, key.drbl.tech — запасной адрес."},
]

YANDEX_WHITELIST_BLOCKS = [
    {"t": "p", "text": "В Yandex Cloud CDN белые списки — в двух местах: поле в самом ресурсе и список IP edge-серверов для origin."},
    {"t": "steps", "steps": [
        {"title": "В ресурсе CDN — ВЫКЛЮЧЕНО", "body": [
            "Шаг 1 «Основные параметры», поля «Доступ по IP-адресам», «Доступ по странам», «Доступ по защищённому токену» — выкл. для ВСЕХ наших ресурсов: sub.drbl.tech, static.drbl.tech, assets.drbl.tech, media.drbl.tech.",
            "Клиенты заходят с любого IP по всей России — включишь и впишешь свой IP, отрежешь всех остальных.",
        ]},
        {"title": "Белый список на origin — IP Яндекса", "body": [
            "Origin (нода) должен отвечать ТОЛЬКО edge-серверам Яндекса, а не кому попало напрямую. Официальный список:",
            {"link": {"text": "https://tech.cdn.yandex.net/prefixes/yc.json", "href": "https://tech.cdn.yandex.net/prefixes/yc.json"}},
            "(дока Яндекса «Диапазоны публичных IP-адресов» → Cloud CDN).",
            "Список меняется — скачивать свежий при каждом применении.",
        ]},
        {"title": "Применить на ноде (дубликат [CDN], порт 8880)", "body": [
            "На сервере ноды (Германия, Швеция, Латвия — дубликат [CDN]):",
            {"code": "ufw status"},
            "Если выключен — сначала ufw allow 22/tcp, потом ufw enable, иначе потеряешь SSH.",
            "Затем разрешить Яндекс на 8880:",
            {"code": "curl -s https://tech.cdn.yandex.net/prefixes/yc.json | python3 -c \"import json,sys; print('\\n'.join(p for p in json.load(sys.stdin)['prefixes'] if ':' not in p))\" | while read ip; do ufw allow from $ip to any port 8880 proto tcp; done"},
            "Правило для 12222 (только IP панели) и порт 22 — НЕ трогать. Порты основной ноды (VTR, HY2) — тоже не трогать: они прямые, не через CDN.",
        ]},
        {"title": "body-brown (подписка) — НЕ ставится", "body": [
            "На 443 висят ещё панель и сайт — белый список на файрволе отрежет и их. Для зеркала sub.drbl.tech он не нужен: клиенты идут на sub.drbl.tech, а key.drbl.tech напрямую и так режет DPI.",
        ]},
        {"title": "Проверка", "body": [
            "Напрямую на origin-порт с обычного IP — таймаут (закрыто).",
            "Через CDN-домен (assets.drbl.tech:443) — подключается.",
            "Это hardening, без него всё работает — делать после того, как нода [CDN] уже зелёная в панели.",
        ]},
    ]},
]

async def yandex_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response({
        "mirror": "sub.drbl.tech",
        "main": "key.drbl.tech",
        "cache": "disabled",
        "text": "\n".join(YANDEX_MIRROR_LINES),
        "whitelist_text": "\n".join(YANDEX_WHITELIST_LINES),
        "resources_text": "\n".join(YANDEX_RESOURCES_LINES),
        "dns_text": "\n".join(YANDEX_DNS_LINES),
        "billing_text": "\n".join(YANDEX_BILLING_LINES),
        # Структурированные страницы для веба (рендер вместо <pre>);
        # тексты *_text оставлены для совместимости.
        "pages": {
            "res": {"title": "Ресурсы и ноды", "blocks": YANDEX_RESOURCES_BLOCKS},
            "dns": {"title": "DNS и ремонт", "blocks": YANDEX_DNS_BLOCKS},
            "bill": {"title": "Биллинг Yandex CDN", "blocks": YANDEX_BILLING_BLOCKS},
            "wl": {"title": "Белые списки", "blocks": YANDEX_WHITELIST_BLOCKS},
            "mirror": {"title": "Страница подписки — зеркало через CDN", "blocks": YANDEX_MIRROR_BLOCKS},
        },
    })


# ── Jobs run-now ─────────────────────────────────────────────────────────────

_JOB_TICKS = {
    # job: (модуль, функция). morning/panel-sync/netcheck/fraud-scan
    # здесь нет — у них свои эндпоинты, не дублируем.
    "expiry_reminder": ("paidsub.handlers", "expiry_reminder_tick"),
    "lte_fallback": ("paidsub.handlers", "lte_fallback_tick"),
    "check_expired": ("paidsub.handlers", "check_expired_subs"),
    "winback": ("features.winback", "winback_tick"),
    "fraud": ("features.fraud", "fraud_tick"),
    "blacklist_sync": ("features.blacklist", "blacklist_sync_tick"),
    "blacklist_expire": ("features.blacklist", "blacklist_expire_tick"),
    "connect_help": ("handlers.control", "connect_help_tick"),
    "purge": ("handlers.control", "purge_tick"),
    "site_sync": ("web.site_deploy", "site_sync_tick"),
    # Ручной запуск тумблер не проверяет (прецедент site_sync):
    # тумблер device_watch правит только расписанием, а кнопка —
    # явное действие админа через postConfirm.
    "device_watch": ("services.device_watch", "device_watch_tick"),
    "sessions": ("web.webapi", "sessions_tick"),
}


def _scrub_value(value):
    """Рекурсивно вырезает секреты из значений результата тика."""
    if isinstance(value, str):
        return _scrub(value)
    if isinstance(value, dict):
        return {str(k): _scrub_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_value(v) for v in value]
    return value


def _remind_stages(cfg):
    """Сроки напоминаний в секундах — те же ключи, что expiry_reminder_tick."""
    return [int(cfg.get("remind_first", 3 * 86400) or 0),
            int(cfg.get("remind_second", 86400) or 0),
            int(cfg.get("remind_third", 0) or 0)]


def _remind_blocked_note(cfg):
    """Почему тик напоминаний ничего не отправит (None — не заблокирован)."""
    if not cfg.get("remind_enabled", True):
        return "Напоминания выключены"
    if not any(_remind_stages(cfg)):
        return "Сроки напоминаний не заданы"
    from paidsub.handlers import in_quiet_hours
    if in_quiet_hours(datetime.now(), cfg):
        return "Тихие часы — отправка отложена"
    return None


async def _remind_due_count(cfg):
    """Сколько напоминаний тик попытается отправить — те же фильтры,
    что expiry_reminder_tick (paidsub/handlers.py)."""
    if _remind_blocked_note(cfg) is not None:
        return 0
    from paidsub.storage import get_subs_for_reminder, parse_sub_date
    from features.blacklist import blacklisted_ids
    stages = _remind_stages(cfg)
    skip = await blacklisted_ids()
    remind_trials = cfg.get("remind_trials", True)
    now = datetime.now()
    due = 0
    for _sub_id, tg_id, period_end, times_renewed, stage in await get_subs_for_reminder():
        if not tg_id or tg_id in skip:
            continue
        if not times_renewed and not remind_trials:
            continue
        end = parse_sub_date(period_end)
        if not end:
            continue
        left = int((end - now).total_seconds())
        if left <= 0:
            continue
        target = 0
        for idx, window in enumerate(stages, start=1):
            if window and left <= window:
                target = idx
        if not target or target <= int(stage or 0):
            continue
        due += 1
    return due


async def _expired_candidates():
    """Сколько подписок тик пометит истёкшими / восстановит активными —
    те же условия, что check_expired_subs (paidsub/handlers.py)."""
    from paidsub.storage import get_expired_paid_subs, parse_sub_date
    now = datetime.now()
    expired = reactivated = 0
    for row in await get_expired_paid_subs():
        (_sid, _tg, _email, _uuid, _sub, _url, expire_str, status,
         _renewed, _ind, _period_end, frozen_at) = row
        if frozen_at:
            continue
        expire_dt = parse_sub_date(expire_str)
        if not expire_dt:
            continue
        if now < expire_dt:
            if status != "active":
                reactivated += 1
        elif status != "expired":
            expired += 1
    return {"expired": expired, "reactivated": reactivated}


async def _winback_candidates():
    """Сколько писем возврата тик попытается отправить — те же условия,
    что winback_tick (features/winback.py)."""
    from features.winback import settings as winback_settings
    from core.database import winback_stage
    from features.blacklist import is_blacklisted
    from paidsub.storage import get_expired_paid_subs, parse_sub_date
    s = winback_settings()
    if not s["enabled"]:
        return {"due": 0, "note": "Возврат ушедших выключен"}
    now = datetime.now()
    due = 0
    for row in await get_expired_paid_subs():
        tg_id, expire_str, status = row[1], row[6], row[7]
        times_renewed = row[8] if len(row) > 8 else 0
        if status != "expired" or not tg_id:
            continue
        if s["paid_only"] and not times_renewed:
            continue
        end = parse_sub_date(expire_str)
        if not end:
            continue
        gone = (now - end).days
        target = 0
        if gone >= s["days"]:
            target = 1
        if s["days2"] and gone >= s["days2"]:
            target = 2
        if not target or target <= await winback_stage(tg_id):
            continue
        if await is_blacklisted(tg_id):
            continue
        due += 1
    return {"due": due, "note": None}


async def _sessions_expired_counts() -> dict:
    """Сколько просроченных записей в 4 таблицах сессий/кодов — те же
    WHERE, что purge-функции core/database.py (sessions_tick)."""
    from core.database import DB_PATH
    import aiosqlite
    queries = {
        "web": "SELECT COUNT(*) FROM web_sessions "
               "WHERE expires_at <= CURRENT_TIMESTAMP",
        "resets": "SELECT COUNT(*) FROM password_resets "
                  "WHERE used = 1 OR expires_at <= CURRENT_TIMESTAMP",
        "admin": "SELECT COUNT(*) FROM admin_sessions "
                 "WHERE expires_at <= CURRENT_TIMESTAMP",
        "setup": "SELECT COUNT(*) FROM admin_setup_tokens "
                 "WHERE used = 1 OR expires_at <= CURRENT_TIMESTAMP",
    }
    out = {}
    async with aiosqlite.connect(DB_PATH) as db:
        for key, q in queries.items():
            async with db.execute(q) as cur:
                out[key] = (await cur.fetchone())[0]
    return out


async def _job_probe(job):
    """Состояние до запуска тика — для честного итога.

    Возвращает opaque-словарь; падение любого чтения — None, запуск
    тика это не останавливает.
    """
    try:
        from config import load_config
        cfg = load_config()
        if job == "expiry_reminder":
            return {"due": await _remind_due_count(cfg),
                    "note": _remind_blocked_note(cfg)}
        if job == "check_expired":
            return await _expired_candidates()
        if job == "winback":
            return await _winback_candidates()
        if job == "fraud":
            from core.database import list_fraud_pairs
            rows = await list_fraud_pairs(None, limit=100000)
            return {"pairs": {(r[0], r[1]) for r in rows}}
        if job == "blacklist_expire":
            from core.database import bl_expired_now
            return {"expired": len(await bl_expired_now())}
        if job == "connect_help":
            from core.database import connect_help_stats
            from core import maintenance as mnt_mod
            note = None
            if not cfg.get("connect_help_enabled", True):
                note = "Помощь при подключении выключена"
            elif mnt_mod.is_maintenance():
                note = "Техработы — подсказки не отправляются"
            return {"sent": (await connect_help_stats()).get("total", 0),
                    "note": note}
        if job == "purge":
            from core.database import activity_stats
            st = await activity_stats()
            return {"act": st.get("activity_rows", 0),
                    "err": st.get("error_rows", 0)}
        if job == "sessions":
            return await _sessions_expired_counts()
    except Exception:
        return None
    return None


async def _job_summarize(job, before, result):
    """Итог запуска: список {label, value} и примечание (или None).

    Подсчёт — best-effort: любая ошибка здесь не должна ронять ответ,
    поэтому jobs_run_now оборачивает вызов в try/except.
    """
    if job == "expiry_reminder":
        b = before or {}
        return [{"label": "Напоминаний", "value": str(b.get("due", 0))}], b.get("note")
    if job == "check_expired":
        b = before or {}
        rows = [{"label": "Помечено истёкшими", "value": str(b.get("expired", 0))}]
        if b.get("reactivated"):
            rows.append({"label": "Восстановлено активных",
                         "value": str(b["reactivated"])})
        return rows, None
    if job == "winback":
        b = before or {}
        return [{"label": "Писем возврата", "value": str(b.get("due", 0))}], b.get("note")
    if job == "fraud":
        from core.database import list_fraud_pairs
        after = {(r[0], r[1]) for r in await list_fraud_pairs(None, limit=100000)}
        new = len(after - (before or {}).get("pairs", set()))
        return [{"label": "Новых находок", "value": str(new)}], None
    if job == "blacklist_expire":
        from core.database import bl_expired_now
        left = len(await bl_expired_now())
        removed = (before or {}).get("expired", 0) - left
        return [{"label": "Снято блокировок", "value": str(max(removed, 0))}], None
    if job == "connect_help":
        from core.database import connect_help_stats
        sent = (await connect_help_stats()).get("total", 0) - (before or {}).get("sent", 0)
        return [{"label": "Подсказок отправлено", "value": str(max(sent, 0))}], (before or {}).get("note")
    if job == "purge":
        from core.database import activity_stats
        st = await activity_stats()
        b = before or {}
        return [{"label": "Действий",
                 "value": f"{b.get('act', 0)} → {st.get('activity_rows', 0)}"},
                {"label": "Ошибок",
                 "value": f"{b.get('err', 0)} → {st.get('error_rows', 0)}"}], None
    if job == "device_watch":
        # Тик сам возвращает счётчики (services/device_watch.py).
        r = result if isinstance(result, dict) else {}
        if r.get("skipped") == "already_running":
            return [], "Вотчер уже работает — повторный запуск пропущен"
        rows = [{"label": "Проверено подписок",
                 "value": str(r.get("checked", 0))},
                {"label": "Новых устройств",
                 "value": str(r.get("new", 0))},
                {"label": "Уведомлений отправлено",
                 "value": str(r.get("notified", 0))}]
        if r.get("panel_fail"):
            rows.append({"label": "Ошибок панели",
                         "value": str(r["panel_fail"])})
        if r.get("skipped"):
            rows.append({"label": "Пропущено подписок",
                         "value": str(r["skipped"])})
        note = None
        if r.get("ok") is False:
            note = r.get("error") or "Панель не ответила"
        return rows, note
    if job == "sessions":
        after = await _sessions_expired_counts()
        b = before or {}
        labels = {"web": "Сессий кабинета", "resets": "Кодов сброса",
                  "admin": "Сессий админки", "setup": "Токенов установки"}
        rows = [{"label": labels[k],
                 "value": f"{b.get(k, 0)} → {after.get(k, 0)}"}
                for k in ("web", "resets", "admin", "setup")]
        return rows, None
    return None, None


async def jobs_run_now(request):
    import importlib
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    job = str(body.get("job") or "")
    if job not in _JOB_TICKS:
        return _json_error("unknown_job", 400)
    bot = get_bot()
    if bot is None:
        return _json_error("no_bot", 503)
    mod_name, func_name = _JOB_TICKS[job]
    context = SimpleNamespace(bot=bot, application=_admin_application)
    before = None
    try:
        before = await _job_probe(job)
    except Exception:
        before = None
    try:
        tick = getattr(importlib.import_module(mod_name), func_name)
        res = await tick(context)
    except Exception as ex:
        logging.error("админка: jobs run-now %s: %s", job, ex)
        await _audit(actor, "jobs_run_now_failed", f"job={job}")
        return _json_error("job_failed", 502)
    if res is None:
        result = None
    elif isinstance(res, dict):
        result = _scrub_value(res)
    elif isinstance(res, str):
        result = _scrub(res)
    else:
        result = _scrub(str(res))
    summary = note = None
    try:
        summary, note = await _job_summarize(job, before, result)
    except Exception:
        summary = note = None
    await _audit(actor, "jobs_run_now", f"job={job}")
    return web.json_response({"ok": True, "job": job, "result": result,
                             "summary": summary, "note": note})


# ── Регистрация ──────────────────────────────────────────────────────────────

def register(app) -> None:
    """Добавляет маршруты фазы 3 в админ-подприложение (пути — без
    префикса /api/admin: его даёт add_subapp в webapi.build_app)."""
    app.router.add_get("/nodes", nodes)
    app.router.add_get("/squads", squads)
    app.router.add_get("/panel", panel_view)
    app.router.add_get("/nodes/usage", nodes_usage)
    app.router.add_get("/nodes/usage/snapshot", usage_snapshot)
    app.router.add_get("/nodes/{node_id}/users", node_users)
    app.router.add_post("/panel-sync", panel_sync_run)
    app.router.add_post("/panel/names-sync", panel_names_sync)
    app.router.add_get("/panel-sync/settings", panel_sync_settings_get)
    app.router.add_get("/panel/tags", panel_tags_get)
    app.router.add_post("/panel/tags/apply", panel_tags_apply)
    app.router.add_get("/logs", logs_get)
    app.router.add_get("/logs/export", logs_export)
    app.router.add_get("/logs/activity/{entry_id}", logs_activity_entry)
    app.router.add_get("/logs/errors/{entry_id}", logs_error_entry)
    app.router.add_get("/logs/history/{entry_id}", logs_history_entry)
    app.router.add_post("/logs/purge", logs_purge)
    app.router.add_get("/logs/storage", logs_storage)
    app.router.add_patch("/logs/retention", logs_retention)
    app.router.add_get("/morning", morning_get)
    app.router.add_patch("/morning", morning_patch)
    app.router.add_post("/morning/run-now", morning_run_now)
    app.router.add_get("/maintenance", maintenance_get)
    app.router.add_post("/maintenance/toggle", maintenance_toggle)
    app.router.add_post("/maintenance/feature", maintenance_feature)
    app.router.add_post("/maintenance/text", maintenance_text)
    app.router.add_get("/netcheck", netcheck_get)
    app.router.add_post("/netcheck/run", netcheck_run)
    app.router.add_get("/links", links_get)
    app.router.add_patch("/links", links_patch)
    app.router.add_get("/site", site_get)
    app.router.add_patch("/site/settings", site_settings_patch)
    app.router.add_post("/site/cert", site_cert)
    app.router.add_get("/site/check", site_check)
    app.router.add_post("/site/deploy", site_deploy)
    app.router.add_post("/site/delete", site_delete)
    app.router.add_get("/site/texts", site_texts_get)
    app.router.add_patch("/site/texts", site_texts_patch)
    app.router.add_post("/site/texts/reset", site_texts_reset)
    app.router.add_get("/yandex", yandex_get)
    app.router.add_post("/jobs/run-now", jobs_run_now)
    app.router.add_get("/panel/profiles/{uuid}", panel_profile_get)
    app.router.add_get("/panel/hosts", panel_hosts_list)
    app.router.add_patch("/panel/profiles/{uuid}/inbounds/{tag}",
                         panel_profile_inbound_patch)
    app.router.add_patch("/panel/hosts/{uuid}", panel_host_patch)
    app.router.add_post("/panel/hosts", panel_host_create)
    app.router.add_delete("/panel/hosts/{uuid}", panel_host_delete)
    app.router.add_get("/panel/settings", panel_settings_get)
    app.router.add_patch("/panel/settings", panel_settings_patch)
    app.router.add_post("/panel/settings/test", panel_settings_test)
    app.router.add_get("/support/settings", support_settings_get)
    app.router.add_patch("/support/settings", support_settings_patch)
    app.router.add_post("/support/token", support_token_set)
    app.router.add_post("/git-update", git_update)
    app.router.add_get("/backup/export", backup_export)
    app.router.add_get("/backup/info", backup_info)
    app.router.add_post("/backup/inspect", backup_inspect)
    app.router.add_post("/backup/restore", backup_restore)
    app.router.add_get("/helpers", helpers_get)
    app.router.add_post("/helpers/add", helpers_add)
    app.router.add_post("/helpers/{tg_id}/perm", helpers_perm)
    app.router.add_post("/helpers/{tg_id}/invite", helpers_invite)
    app.router.add_post("/helpers/{tg_id}/delete", helpers_delete)
    app.router.add_get("/blacklist", blacklist_get)
    app.router.add_get("/blacklist/{tg_id}", blacklist_entry)
    app.router.add_post("/blacklist/add", blacklist_add)
    app.router.add_post("/blacklist/sync", blacklist_sync)
    app.router.add_post("/blacklist/remote-toggle", blacklist_remote_toggle)
    app.router.add_post("/blacklist/{tg_id}/stop", blacklist_stop)
    app.router.add_post("/blacklist/{tg_id}/readd", blacklist_readd)
    app.router.add_post("/blacklist/{tg_id}/remove", blacklist_remove)
    app.router.add_get("/fraud", fraud_get)
    app.router.add_get("/fraud/pair", fraud_pair)
    app.router.add_post("/fraud/toggle", fraud_toggle)
    app.router.add_post("/fraud/ip-toggle", fraud_ip_toggle)
    app.router.add_post("/fraud/{a}/{b}/ignore", fraud_ignore)
    app.router.add_post("/fraud/{a}/{b}/recheck", fraud_recheck)
    app.router.add_post("/fraud/scan", fraud_scan)
    app.router.add_post("/fraud/{tg_id}/stop", fraud_stop)
    app.router.add_get("/support/topics", support_topics)
    app.router.add_get("/support/topics/{user_id}", support_topic_get)
    app.router.add_post("/support/topics/{user_id}/reply", support_topic_reply)
    app.router.add_get("/media/{file_id}", media_get)
    app.router.add_post("/support/topics/{user_id}/close", support_topic_close)
    app.router.add_get("/downtime", downtime_get)
    app.router.add_get("/online", online_get)
    app.router.add_get("/web-access", web_access_get)
    app.router.add_patch("/web-access", web_access_patch)
    app.router.add_post("/web-access/check", web_access_check)
    app.router.add_post("/web-access/find-upstream", web_access_find_upstream)
    app.router.add_get("/connect-help", connect_help_get)
    app.router.add_patch("/connect-help", connect_help_patch)
