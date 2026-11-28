"""Проверка наших доменов и IP по спискам блокировок — Cheburcheck.

Единственный слой проверки операторов (handlers/netcheck.py):
статус доменов и IP прямых хостов по спискам блокировок РКН/ТСПУ —
цель в списках, заблокированные подсети, дневные счётчики жалоб.

API: GET https://cheburcheck.ru/api/v1/check?target=<домен|IPv4>.
Авторизация для /check НЕ требуется (публичный эндпоинт, см.
https://cheburcheck.ru/kb/api). Сетевые сканеры (/probe, вердикты
tspu_block/sni_block) требуют API-токен и сюда сознательно не входят.

ВАЖНО про лимиты: у /check жёсткий рейт-лимит — пачка параллельных
запросов ловит HTTP 429, и цель остаётся «не проверенной» (так
2026-11-28 Швеция с реальным блоком IP показала «не проверено»).
Поэтому запросы идут СТРОГО по одному, с паузой между целями, а на
429/5xx/сетевой сбой — повторы с растущей паузой (или Retry-After),
пока сервис не даст окончательный ответ (200 или 404). Проверка
8 целей занимает обычно ~30 секунд, при лимитах — до нескольких
минут, но результат всегда окончательный, а не «не проверено».

Цели: домены TARGETS (выбор — в настройках проверки, config.json
ключ "netcheck") плюс IP прямых хостов. Адреса хостов не
захардкожены, а получаются резолвом публичных имён в момент
проверки (de/se/lv/app.balticway.space), чтобы не протухали.

Исходы по цели:
- ok — не найдено в списках блокировок;
- blocked — домен/IP в списках или попадает в заблокированную подсеть;
- unknown — Cheburcheck вернул 404: цели нет в его базе (для доменов
  это обычное дело — базы списков ведутся по жалобам и выгрузкам);
- error — окончательный ответ не получен даже после всех повторов.
"""

from __future__ import annotations

import asyncio
import socket

import aiohttp

API_BASE = "https://cheburcheck.ru/api/v1"

# (подпись, домен) — домены проверки; выбор хранится в config.json.
TARGETS: list[tuple[str, str]] = [
    ("Сайт", "vpn.drbl.tech"),
    ("Подписка", "key.drbl.tech"),
    ("Финляндия", "helsinki.tembadr.tech"),
    ("Германия", "berlin.tembadr.tech"),
]

# Прямые хосты выдачи: (подпись, публичное имя). IP не храним —
# резолвим на каждой проверке.
DIRECT_HOSTS: list[tuple[str, str]] = [
    ("Германия — прямой", "de.balticway.space"),
    ("Швеция — прямой", "se.balticway.space"),
    ("Латвия — прямой", "lv.balticway.space"),
    ("Германия-2 — прямой", "app.balticway.space"),
]

_TIMEOUT = aiohttp.ClientTimeout(total=30)
_PAUSE_BETWEEN = 2.5          # пауза между целями, секунды
_BACKOFF = [4, 8, 16, 32, 60]  # паузы между повторами одной цели
_MAX_ATTEMPTS = 1 + len(_BACKOFF)


async def _resolve_ipv4(host: str) -> str | None:
    """Первый IPv4-адрес публичного имени или None."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, family=socket.AF_INET,
                                       type=socket.SOCK_STREAM)
    except OSError:
        return None
    for info in infos or []:
        sockaddr = info[4]
        if sockaddr and ":" not in sockaddr[0]:
            return sockaddr[0]
    return None


def _retry_pause(resp: aiohttp.ClientResponse, attempt: int) -> float:
    """Пауза перед повтором: Retry-After сервиса, иначе наш бэкофф."""
    raw = (resp.headers.get("Retry-After") or "").strip()
    if raw.isdigit():
        return min(float(raw), 90.0)
    return _BACKOFF[min(attempt, len(_BACKOFF) - 1)]


async def _check_one(session: aiohttp.ClientSession,
                     label: str, target: str, shown: str) -> dict:
    """Одна цель: GET /check с повторами до окончательного ответа."""
    out = {"label": label, "target": target, "shown": shown}
    last_error = "нет ответа"
    for attempt in range(_MAX_ATTEMPTS):
        pause = None
        try:
            async with session.get(f"{API_BASE}/check",
                                   params={"target": target},
                                   timeout=_TIMEOUT) as resp:
                if resp.status == 200:
                    body = await resp.json(content_type=None)
                    if isinstance(body, dict):
                        return _parse(out, body)
                    last_error = "странный ответ"
                elif resp.status == 404:
                    return {**out, "state": "unknown"}
                elif resp.status == 429 or resp.status >= 500:
                    last_error = f"HTTP {resp.status}"
                    pause = _retry_pause(resp, attempt)
                else:
                    return {**out, "state": "error",
                            "error": f"HTTP {resp.status}"}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            last_error = "нет ответа"
            pause = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
        if attempt < _MAX_ATTEMPTS - 1:
            await asyncio.sleep(
                pause if pause is not None
                else _BACKOFF[min(attempt, len(_BACKOFF) - 1)])
    return {**out, "state": "error", "error": last_error}


def _parse(out: dict, body: dict) -> dict:
    blocked = bool(body.get("blocked"))
    subnets = body.get("blocked_subnets") or []
    complaints = body.get("complaints") or []
    complaints_total = sum(int(c.get("count") or 0) for c in complaints
                           if isinstance(c, dict))
    geo = body.get("geo") or {}
    return {
        **out,
        "state": "blocked" if (blocked or subnets) else "ok",
        "subnets": subnets,
        "complaints": complaints_total,
        "location": geo.get("location"),
        "asn": geo.get("asn"),
    }


async def check_all(domains: list[tuple[str, str]] | None = None) -> list[dict]:
    """Проверяет выбранные домены и IP прямых хостов.

    Запросы — строго последовательно, с паузами и повторами при
    лимитах (см. шапку модуля): каждая цель доводится до
    окончательного ответа. Возвращает список словарей из _check_one.
    """
    jobs: list[tuple[str, str, str]] = []  # (label, target, shown)
    for label, domain in (domains or TARGETS):
        jobs.append((label, domain, domain))
    async with aiohttp.ClientSession(trust_env=True) as session:
        for label, host in DIRECT_HOSTS:
            ip = await _resolve_ipv4(host)
            if ip:
                jobs.append((label, ip, f"{host} · {ip}"))
            else:
                jobs.append((label, host, f"{host} · IP не разрешился"))
        results = []
        for i, (label, target, shown) in enumerate(jobs):
            if i:
                await asyncio.sleep(_PAUSE_BETWEEN)
            results.append(await _check_one(session, label, target, shown))
        return results


def summarize(results: list[dict]) -> tuple[int, int, int, int]:
    """(ok, blocked, unknown, error) по всем целям."""
    ok = blocked = unknown = error = 0
    for r in results:
        state = r.get("state")
        if state == "ok":
            ok += 1
        elif state == "blocked":
            blocked += 1
        elif state == "unknown":
            unknown += 1
        else:
            error += 1
    return ok, blocked, unknown, error
