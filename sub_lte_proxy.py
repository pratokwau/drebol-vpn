#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перехватчик остатка LTE для подписок Drebol VPN.

Стоит между nginx (key.drbl.tech) и remnawave-subscription-page
(127.0.0.1:3010). Прозрачно проксирует всё, и единственное, что меняет, —
заголовок profile-description: дописывает последней строкой остаток
LTE-трафика подписчика, посчитанный тем же кодом, что и в боте
(services.remnawave.user_cdn_usage + lte_limit_gb, как в
handlers/user.py::_sub_facts).

FAIL-OPEN: любая ошибка на любом этапе — ответ панели уходит клиенту
без изменений. Бюджет на подсчёт LTE — 2 секунды (дальше ответ уходит
без строки, а подсчёт докручивается в фоне и ложится в кэш на 120 с).
subscription-userinfo и тело ответа не трогаем никогда.
"""

import asyncio
import base64
import binascii
import logging
import os
import sqlite3
import sys
import time

from aiohttp import ClientSession, ClientTimeout, TCPConnector, web

APP_DIR = "/root/drebol-vpn"
DB_PATH = os.path.join(APP_DIR, "bot.db")
UPSTREAM = "http://127.0.0.1:3010"
LISTEN_HOST, LISTEN_PORT = "127.0.0.1", 3011
CACHE_TTL = 120.0
LTE_BUDGET = 2.0
SUBMAP_REFRESH = 60.0

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-connection", "te", "trailer",
    "transfer-encoding", "upgrade", "proxy-authenticate",
    "proxy-authorization",
}

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sub_lte_proxy")

os.chdir(APP_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# token -> ("paid", email, lte_gb) | ("admin",)
SUBMAP = {}
# token -> (monotonic_ts, line | None)
LTE_CACHE = {}


def _load_submap():
    m = {}
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=3)
    try:
        for sub_url, email, lte_gb in con.execute(
                "SELECT sub_url, email, lte_gb FROM paid_subs "
                "WHERE sub_url IS NOT NULL AND sub_url != ''"):
            tok = (sub_url or "").rstrip("/").rsplit("/", 1)[-1]
            if tok:
                m[tok] = ("paid", email, lte_gb)
        for (sub_url,) in con.execute(
                "SELECT sub_url FROM admin_subs "
                "WHERE sub_url IS NOT NULL AND sub_url != ''"):
            tok = (sub_url or "").rstrip("/").rsplit("/", 1)[-1]
            if tok:
                m.setdefault(tok, ("admin",))
    finally:
        con.close()
    return m


async def _submap_refresher():
    global SUBMAP
    while True:
        await asyncio.sleep(SUBMAP_REFRESH)
        try:
            SUBMAP = await asyncio.to_thread(_load_submap)
        except Exception as e:  # noqa: BLE001 — fail-open: старая карта живёт
            log.warning("submap refresh failed: %r", e)


async def _compute_lte_line(email, lte_gb_val):
    """Строка про LTE — тем же кодом, что в handlers/user.py (_sub_facts).

    None — строки нет (панель молчит, нет LTE-узлов и т.п.).
    """
    from config import load_config
    from services.remnawave import (is_configured, lte_limit_gb,
                                    lte_limit_off,
                                    make_username, user_cdn_usage)
    if lte_limit_off():
        # Учёт CDN выключен тумблером в админке — строки в подписке нет.
        return None
    limit = lte_limit_gb(lte_gb_val, load_config().get("paid_preset_lte"))
    if limit == 0:
        return "📡 LTE-серверы: закрыты"
    if not is_configured():
        return None
    r = await user_cdn_usage(make_username(email or "", 0))
    if r.get("ok") and r.get("cdn_nodes"):
        left = max(0.0, limit - r["used_bytes"] / 1024 ** 3)
        return f"📡 Остаток LTE-серверов: {left:.2f} ГБ из {limit} ГБ"
    return None


async def _compute_and_cache(token, ent):
    line = None
    try:
        line = await _compute_lte_line(ent[1], ent[2])
    except Exception as e:  # noqa: BLE001 — fail-open
        log.warning("lte compute failed for ...%s: %r", token[-4:], e)
        line = None
    LTE_CACHE[token] = (time.monotonic(), line)
    return line


def _rewrite_description(value, line):
    """Новое значение profile-description или None, если менять не надо."""
    prefix = None
    for pfx in ("rwEncodeBase64:", "base64:"):
        if value.startswith(pfx):
            prefix = pfx
            break
    if prefix is None:
        return None
    payload = value[len(prefix):].strip()
    try:
        text = base64.b64decode(payload).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    for existing in text.splitlines():
        if existing.startswith("📡 Остаток LTE") or \
                existing.startswith("📡 LTE-серверы"):
            return None  # уже дописано — не дублируем
    new_text = (text.rstrip("\n") + "\n" + line) if text.strip() else line
    return prefix + base64.b64encode(new_text.encode("utf-8")).decode("ascii")


async def handle(request):
    started = time.monotonic()
    token = request.path.lstrip("/").split("/", 1)[0]
    ent = SUBMAP.get(token)
    line = None
    line_task = None
    if ent and ent[0] == "paid":
        cached = LTE_CACHE.get(token)
        if cached and started - cached[0] < CACHE_TTL:
            line = cached[1]
        else:
            line_task = asyncio.ensure_future(_compute_and_cache(token, ent))

    fwd_headers = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk == "host":
            continue
        fwd_headers[k] = v
    fwd_headers["Host"] = request.host

    session = request.app["session"]
    try:
        upstream = await session.request(
            request.method, UPSTREAM + request.path_qs,
            headers=fwd_headers, data=request.content,
            auto_decompress=False, allow_redirects=False)
    except Exception as e:  # noqa: BLE001 — панель недоступна, не наши проблемы
        log.warning("upstream error %s %s: %r",
                    request.method, request.path, e)
        return web.Response(status=502, text="Bad Gateway")

    async with upstream:
        if line_task is not None:
            remain = LTE_BUDGET - (time.monotonic() - started)
            if remain > 0:
                try:
                    line = await asyncio.wait_for(
                        asyncio.shield(line_task), timeout=remain)
                except Exception:  # noqa: BLE001 — таймаут/ошибка: без строки
                    line = None

        resp_headers = {}
        for k, v in upstream.headers.items():
            if k.lower() in HOP_BY_HOP:
                continue
            resp_headers[k] = v
        if line:
            desc = upstream.headers.get("profile-description")
            if desc:
                try:
                    new_desc = _rewrite_description(desc, line)
                except Exception as e:  # noqa: BLE001 — fail-open
                    log.warning("desc rewrite failed: %r", e)
                    new_desc = None
                if new_desc:
                    resp_headers["profile-description"] = new_desc
                    log.info("lte line added for ...%s", token[-4:])

        resp = web.StreamResponse(status=upstream.status,
                                  reason=upstream.reason,
                                  headers=resp_headers)
        await resp.prepare(request)
        try:
            async for chunk in upstream.content.iter_any():
                await resp.write(chunk)
            await resp.write_eof()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return resp


async def _on_startup(app):
    app["session"] = ClientSession(
        connector=TCPConnector(limit=0, ttl_dns_cache=300),
        timeout=ClientTimeout(total=180, connect=5, sock_read=120),
    )
    app["refresher"] = asyncio.ensure_future(_submap_refresher())


async def _on_cleanup(app):
    app["refresher"].cancel()
    await app["session"].close()


def main():
    global SUBMAP
    try:
        SUBMAP = _load_submap()
        log.info("submap loaded: %d tokens", len(SUBMAP))
    except Exception as e:  # noqa: BLE001 — прокси обязан жить и без карты
        log.warning("initial submap load failed: %r", e)
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)


if __name__ == "__main__":
    main()
