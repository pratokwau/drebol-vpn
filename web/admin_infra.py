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
    return web.json_response({"servers": servers, "sites": sites})


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


async def node_users(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    node_id = request.match_info.get("node_id") or ""
    start = request.query.get("start") or ""
    end = request.query.get("end") or ""
    if not start or not end:
        d_start, d_end, _label = rw_mod.current_month_dates()
        start = start or d_start
        end = end or d_end
    res = await rw_mod.node_users_usage(node_id, start, end)
    return web.json_response({"node": node_id, "start": start, "end": end,
                              "usage": res})


# ── Синхронизация с панелью ──────────────────────────────────────────────────

async def panel_sync_run(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    res = await rw_mod.run_panel_sync()
    if res.get("ok"):
        from config import load_config, save_config
        cfg = load_config()
        cfg["panel_sync_last_run"] = datetime.now().isoformat(timespec="seconds")
        cfg["panel_sync_last_report"] = {
            "at": cfg["panel_sync_last_run"],
            "checked": res.get("checked", 0),
            "updated": res.get("updated_subs", 0),
            "orphans": len(res.get("orphans") or []),
            "missing": len(res.get("missing") or []),
        }
        save_config(cfg)
    await _audit(actor, "panel_sync",
                 f"ok={bool(res.get('ok'))} checked={res.get('checked', 0)} "
                 f"updated={res.get('updated_subs', 0)}")
    return web.json_response({
        "ok": bool(res.get("ok")), "result": res,
        "report": rw_mod.panel_sync_report_text(res),
    })


def _panel_sync_settings_snapshot() -> dict:
    from config import load_config
    cfg = load_config()
    return {
        "mode": cfg.get("panel_sync_mode") or "off",
        "interval_hours": int(cfg.get("panel_sync_interval_hours") or 24),
        "daily_time": cfg.get("panel_sync_daily_time") or "03:00",
        "last_run": cfg.get("panel_sync_last_run"),
        "last_report": cfg.get("panel_sync_last_report") or {},
        "schedule": rw_mod.panel_sync_schedule_text(cfg),
    }


async def panel_sync_settings_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response({"settings": _panel_sync_settings_snapshot()})


async def panel_sync_settings_patch(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    patch = body.get("settings") if isinstance(body, dict) else None
    if not isinstance(patch, dict):
        return _json_error("bad_request")
    mode = patch.get("mode", _panel_sync_settings_snapshot()["mode"])
    if mode not in ("off", "interval", "daily"):
        return _json_error("bad_mode")
    clean = {"panel_sync_mode": mode}
    if "interval_hours" in patch:
        try:
            hours = int(patch["interval_hours"])
        except (TypeError, ValueError):
            return _json_error("bad_interval")
        if hours < 1 or hours > 720:
            return _json_error("bad_interval")
        clean["panel_sync_interval_hours"] = hours
    if "daily_time" in patch:
        parsed = morning_mod.parse_time(str(patch["daily_time"] or ""))
        if parsed is None:
            return _json_error("bad_time")
        clean["panel_sync_daily_time"] = f"{parsed[0]:02d}:{parsed[1]:02d}"
    from config import atomic_update
    atomic_update(lambda cfg: cfg.update(clean))
    await _audit(actor, "panel_sync_settings",
                 "mode: " + str(clean.get("panel_sync_mode")))
    return web.json_response({"ok": True,
                              "settings": _panel_sync_settings_snapshot()})


# ── Логи ─────────────────────────────────────────────────────────────────────

def _activity_row(row) -> dict:
    return {"id": row[0], "tg_id": row[1], "action": row[2],
            "details": _scrub(str(row[3] or "")), "time": str(row[4] or ""),
            "first_name": row[5] or "", "username": row[6] or ""}


def _error_row(row) -> dict:
    return {"id": row[0], "source": row[1], "level": row[2],
            "message": _scrub(str(row[3] or "")),
            "details": _scrub(str(row[4] or "")), "time": str(row[5] or ""),
            "tg_id": row[6]}


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
        return web.json_response({"kind": "errors", "page": page,
                                  "pages": pages,
                                  "rows": [_error_row(r) for r in rows]})
    scope = request.query.get("scope") or "all"
    user_id = request.query.get("user_id")
    if scope == "all":
        # list_activity("all") отдаёт только не-админские строки, а
        # scope="admin" — только админские: «все» — это их слияние.
        rows_a, _ = await list_activity(
            "admin", 1, 5000, user_id=int(user_id) if user_id else None,
            kind=request.query.get("filter_kind") or None,
            date_from=request.query.get("date_from") or None,
            date_to=request.query.get("date_to") or None)
        rows_b, _ = await list_activity(
            "all", 1, 5000, user_id=int(user_id) if user_id else None,
            kind=request.query.get("filter_kind") or None,
            date_from=request.query.get("date_from") or None,
            date_to=request.query.get("date_to") or None)
        merged = sorted(rows_a + rows_b, key=lambda r: r[0], reverse=True)
        total = len(merged)
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        rows = merged[(page - 1) * per_page: page * per_page]
        return web.json_response({"kind": "activity", "page": page,
                                  "pages": pages,
                                  "rows": [_activity_row(r) for r in rows]})
    rows, pages = await list_activity(
        scope, page, per_page,
        user_id=int(user_id) if user_id else None,
        kind=request.query.get("filter_kind") or None,
        date_from=request.query.get("date_from") or None,
        date_to=request.query.get("date_to") or None)
    return web.json_response({"kind": "activity", "page": page,
                              "pages": pages,
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
    else:
        # Как в logs_get: «все» — слияние админских и обычных строк.
        rows_a, _ = await list_activity("admin", 1, EXPORT_MAX_ROWS)
        rows_b, _ = await list_activity("all", 1, EXPORT_MAX_ROWS)
        rows = sorted(rows_a + rows_b, key=lambda r: r[0], reverse=True)
        blob = _export_rows_to_csv(rows, "activity")
        fname = f"drebol-logs-activity-{today}.csv"
    text = _scrub(blob.decode("utf-8", "replace"))
    return web.Response(
        text=text, content_type="text/csv", charset="utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


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
    return web.json_response({
        "domains": [{"label": label, "domain": domain}
                    for label, domain in domains],
        "operators": [{"label": label, "asns": asns}
                      for label, asns in operators],
        "netcheck_days": net_cfg.get("netcheck_days"),
        "netcheck_last_run": net_cfg.get("netcheck_last_run"),
    })


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
        "user": creds.get("user") or "",
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
                              "restart": "scheduled"})


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
            return _json_error("bad_archive")
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
    out = []
    for uid in staff_mod.helper_ids():
        u = await get_user_info(uid)
        out.append({
            "tg_id": uid,
            "first_name": (u[1] if u else "") or "",
            "username": (u[2] if u else "") or "",
            "perms": sorted(staff_mod.helper_perms(uid)),
            "web_access": False,
        })
    return web.json_response({"helpers": out})


# ── Чёрный список ────────────────────────────────────────────────────────────

async def blacklist_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from core.database import bl_counts, bl_list, bl_stats
    scope = request.query.get("scope") or "manual"
    if scope not in ("manual", "allow", "people"):
        scope = "manual"
    page = max(1, _int_query(request, "page", 1))
    use_remote = bl_mod.remote_on()
    rows, pages = await bl_list(scope, use_remote, page, 10)
    return web.json_response({
        "scope": scope, "page": page, "pages": pages,
        "counts": await bl_counts(use_remote),
        "stats": await bl_stats(),
        "remote_enabled": use_remote,
        "entries": [{"tg_id": r[0], "first_name": r[1] or "",
                     "username": r[2] or "", "reason": r[3] or "",
                     "source": r[4]} for r in rows],
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


# ── Фрод ─────────────────────────────────────────────────────────────────────

async def fraud_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    from core.database import fraud_stats, list_fraud_pairs
    status = request.query.get("status") or None
    if status not in (None, "new", "ignored", "blocked"):
        status = None
    rows = await list_fraud_pairs(status, limit=15)
    return web.json_response({
        "stats": await fraud_stats(),
        "pairs": [{"tg_a": r[0], "tg_b": r[1], "kind": r[2],
                   "value": str(r[3])[:40], "status": r[4],
                   "created_at": str(r[5] or "")} for r in rows],
    })


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
    from core.database import get_open_support_topics, support_stats
    rows = await get_open_support_topics()
    return web.json_response({
        "stats": await support_stats(),
        "topics": [{"user_id": r[0], "topic_id": r[1], "group_id": r[2],
                    "topic_name": r[3] or ""} for r in rows],
    })


async def downtime_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    import time as _time
    from core.database import downtime_summary, get_downtime_events
    days = _int_query(request, "days", 30)
    days = min(90, max(1, days))
    now = int(_time.time())
    since = now - days * 86400
    events = await get_downtime_events(since)
    return web.json_response({
        "days": days, "since": since, "now": now,
        "summary": downtime_summary(events, since, now),
        "events": events,
    })


async def online_get(request):
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
    return web.json_response({"online": online, "last_online": last})


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
    if "webapi_enabled" in body:
        return _json_error(
            "webapi_enabled меняется только из ТГ: выключение убьёт и эту админку",
            403)
    if patch:
        def _apply(cfg):
            cfg.update(patch)
        atomic_update(_apply)
    await _audit(actor, "web_access_update",
                 "keys: " + ", ".join(sorted(patch)) + " (restart_required)")
    return web.json_response({"ok": True, "restart_required": True,
                              "webapi": patch})


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
    return web.json_response({"ok": True, "profile": res.get("data")})


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
    return web.json_response({"ok": True, "inbound": fresh_inbound})


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
    if not text:
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
    if group_id:
        try:
            await bot.send_message(chat_id=group_id,
                                   message_thread_id=topic_id, text=text)
            delivered_via = "topic"
        except Exception as ex:
            logging.error("админка: support reply to topic: %s", ex)
    if delivered_via is None:
        try:
            await bot.send_message(chat_id=user_id, text=text)
            delivered_via = "dm"
        except Exception as ex:
            logging.error("админка: support reply DM: %s", ex)
            return _json_error("delivery_failed", 502)
    await add_support_message(user_id, text, from_admin=True)
    await touch_support_topic(user_id)
    if close:
        await set_support_topic_status(user_id, "closed")
    await _audit(actor, "support_reply",
                 f"user_id={user_id} via={delivered_via}"
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


async def support_settings_get(request):
    try:
        await _require_actor(request)
    except Exception:
        return _json_error("no_session", 401)
    return web.json_response({"settings": _support_settings_snapshot()})


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


# ── Помощники: добавление, права, удаление (Mark-only) ───────────────────────

async def helpers_add(request):
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    mark_err = _mark_only(actor)
    if mark_err is not None:
        return mark_err
    body = await _json_body(request)
    try:
        tg_id = int(body.get("tg_id") or 0)
    except (TypeError, ValueError):
        tg_id = 0
    if not tg_id:
        return _json_error("bad_request")
    from config import ADMIN_ID
    if tg_id == ADMIN_ID:
        return _json_error("is_admin")
    from core.database import get_user_info
    u = await get_user_info(tg_id)
    if not u:
        return _json_error("user_not_found", 404)
    if tg_id in staff_mod.helper_ids():
        await _audit(actor, "helpers_add", f"tg_id={tg_id} already")
        return web.json_response({"ok": True, "already": True, "tg_id": tg_id,
                                  "perms": sorted(staff_mod.helper_perms(tg_id))})
    # Тот же путь, что features/staff.py handle_helper_input: в список
    # + права по умолчанию (карточки людей, сообщения людям).
    staff_mod._save_ids(staff_mod.helper_ids() + [tg_id])
    staff_mod.set_helper_perms(tg_id, staff_mod.DEFAULT_PERMS)
    await _audit(actor, "helpers_add", f"tg_id={tg_id}")
    return web.json_response({"ok": True, "tg_id": tg_id,
                              "perms": sorted(staff_mod.helper_perms(tg_id))})


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
    staff_mod._forget(tg_id)
    await _audit(actor, "helpers_delete", f"tg_id={tg_id}")
    return web.json_response({"ok": True})


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
                     "fields": [f for f, _ in items]}
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


# ── Яндекс Клауд (только чтение) ─────────────────────────────────────────────

# Тот же текст, что services/remnawave.py handle_rw_yandex_sub: зеркало
# подписки sub.drbl.tech через CDN Яндекса, основная ссылка — key.drbl.tech.
YANDEX_MIRROR_LINES = [
    "Страница подписки — зеркало через CDN",
    "",
    "sub.drbl.tech — только зеркало ссылки подписки (кнопка «🪞 Зеркало подписки»",
    "в «Моей подписке»), основная ссылка остаётся key.drbl.tech.",
    "Кэш полностью ВЫКЛЮЧЕН — иначе один юзер получит чужой конфиг.",
    "",
    "1. Сертификат (Certificate Manager)",
    "В Яндексе нужен только один сертификат — для sub.drbl.tech.",
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
    "Решающий тест: INCY на МТС без VPN обновляет подписку по зеркальной ссылке",
    "(кнопка «🪞 Зеркало подписки» в «Моей подписке»).",
    "",
    "Цена: 150 ₽/мес за ресурс (150 ГБ + 100 млн запросов), сверх — ~1,05 ₽/ГБ.",
    "Основная ссылка остаётся key.drbl.tech, sub.drbl.tech — только зеркало.",
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
}


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
    try:
        tick = getattr(importlib.import_module(mod_name), func_name)
        res = await tick(context)
    except Exception as ex:
        logging.error("админка: jobs run-now %s: %s", job, ex)
        await _audit(actor, "jobs_run_now_failed", f"job={job}")
        return _json_error("job_failed", 502)
    if res is None:
        result = None
    elif isinstance(res, str):
        result = _scrub(res)
    else:
        result = _scrub(str(res))
    await _audit(actor, "jobs_run_now", f"job={job}")
    return web.json_response({"ok": True, "job": job, "result": result})


# ── Регистрация ──────────────────────────────────────────────────────────────

def register(app) -> None:
    """Добавляет маршруты фазы 3 в админ-подприложение (пути — без
    префикса /api/admin: его даёт add_subapp в webapi.build_app)."""
    app.router.add_get("/nodes", nodes)
    app.router.add_get("/squads", squads)
    app.router.add_get("/panel", panel_view)
    app.router.add_get("/nodes/{node_id}/users", node_users)
    app.router.add_post("/panel-sync", panel_sync_run)
    app.router.add_get("/panel-sync/settings", panel_sync_settings_get)
    app.router.add_patch("/panel-sync/settings", panel_sync_settings_patch)
    app.router.add_get("/logs", logs_get)
    app.router.add_get("/logs/export", logs_export)
    app.router.add_post("/logs/purge", logs_purge)
    app.router.add_get("/morning", morning_get)
    app.router.add_patch("/morning", morning_patch)
    app.router.add_post("/morning/run-now", morning_run_now)
    app.router.add_get("/netcheck", netcheck_get)
    app.router.add_post("/netcheck/run", netcheck_run)
    app.router.add_get("/site", site_get)
    app.router.add_post("/site/deploy", site_deploy)
    app.router.add_post("/site/delete", site_delete)
    app.router.add_get("/site/texts", site_texts_get)
    app.router.add_patch("/site/texts", site_texts_patch)
    app.router.add_get("/yandex", yandex_get)
    app.router.add_post("/jobs/run-now", jobs_run_now)
    app.router.add_get("/panel/profiles/{uuid}", panel_profile_get)
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
    app.router.add_post("/git-update", git_update)
    app.router.add_get("/backup/export", backup_export)
    app.router.add_post("/backup/restore", backup_restore)
    app.router.add_get("/helpers", helpers_get)
    app.router.add_post("/helpers/add", helpers_add)
    app.router.add_post("/helpers/{tg_id}/perm", helpers_perm)
    app.router.add_post("/helpers/{tg_id}/delete", helpers_delete)
    app.router.add_get("/blacklist", blacklist_get)
    app.router.add_post("/blacklist/add", blacklist_add)
    app.router.add_post("/blacklist/{tg_id}/stop", blacklist_stop)
    app.router.add_post("/blacklist/{tg_id}/readd", blacklist_readd)
    app.router.add_get("/fraud", fraud_get)
    app.router.add_post("/fraud/scan", fraud_scan)
    app.router.add_post("/fraud/{tg_id}/stop", fraud_stop)
    app.router.add_get("/support/topics", support_topics)
    app.router.add_get("/support/topics/{user_id}", support_topic_get)
    app.router.add_post("/support/topics/{user_id}/reply", support_topic_reply)
    app.router.add_post("/support/topics/{user_id}/close", support_topic_close)
    app.router.add_get("/downtime", downtime_get)
    app.router.add_get("/online", online_get)
    app.router.add_get("/web-access", web_access_get)
    app.router.add_patch("/web-access", web_access_patch)
    app.router.add_get("/connect-help", connect_help_get)
    app.router.add_patch("/connect-help", connect_help_patch)
