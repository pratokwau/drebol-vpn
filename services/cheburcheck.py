"""Проверка наших доменов и IP по спискам блокировок — Cheburcheck.

Второй слой проверки операторов (handlers/netcheck.py): Globalping
показывает живую доступность с сетей операторов, а Cheburcheck —
формальный статус по спискам РКН/ТСПУ: домен или IP в списках
блокировок, заблокированные подсети, дневные счётчики жалоб.

API: GET https://cheburcheck.ru/api/v1/check?target=<домен|IPv4>.
Авторизация для /check НЕ требуется (публичный эндпоинт, см.
https://cheburcheck.ru/kb/api). Сетевые сканеры (/probe, вердикты
tspu_block/sni_block) требуют API-токен и сюда сознательно не входят.

Цели: домены из services.globalping.TARGETS (тот же выбор, что у
Globalping) плюс IP прямых хостов — их адреса не захардкожены, а
получаются резолвом публичных имён хостов в момент проверки
(de/se/lv/app.balticway.space), чтобы не протухали при смене IP.

Исходы по цели:
- ok — не найдено в списках блокировок;
- blocked — домен/IP в списках или попадает в заблокированную подсеть;
- unknown — Cheburcheck вернул 404: цели нет в его базе (для доменов
  это обычное дело — базы списков ведутся по жалобам и выгрузкам);
- error — сеть/сервис недоступны, ответ не JSON и т.п.
"""

from __future__ import annotations

import asyncio
import socket

import aiohttp

import services.globalping as gp

API_BASE = "https://cheburcheck.ru/api/v1"

# Прямые хосты выдачи: (подпись, публичное имя). IP не храним —
# резолвим на каждой проверке.
DIRECT_HOSTS: list[tuple[str, str]] = [
    ("Германия — прямой", "de.balticway.space"),
    ("Швеция — прямой", "se.balticway.space"),
    ("Латвия — прямой", "lv.balticway.space"),
    ("Германия-2 — прямой", "app.balticway.space"),
]

_TIMEOUT = aiohttp.ClientTimeout(total=25)


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


async def _check_one(session: aiohttp.ClientSession,
                     label: str, target: str, shown: str) -> dict:
    """Одна цель: GET /check -> {label, target, shown, state, ...}."""
    out = {"label": label, "target": target, "shown": shown}
    try:
        async with session.get(f"{API_BASE}/check",
                               params={"target": target},
                               timeout=_TIMEOUT) as resp:
            if resp.status == 404:
                return {**out, "state": "unknown"}
            if resp.status != 200:
                return {**out, "state": "error",
                        "error": f"HTTP {resp.status}"}
            body = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return {**out, "state": "error", "error": "нет ответа"}
    if not isinstance(body, dict):
        return {**out, "state": "error", "error": "странный ответ"}
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


async def check_all() -> list[dict]:
    """Проверяет домены netcheck-выбора и IP прямых хостов.

    Возвращает список словарей из _check_one. Сетевые ошибки по
    отдельным целям не роняют всю проверку — цель получает
    state="error".
    """
    jobs: list[tuple[str, str, str]] = []  # (label, target, shown)
    for label, domain in gp.TARGETS:
        jobs.append((label, domain, domain))
    async with aiohttp.ClientSession(trust_env=True) as session:
        resolved = await asyncio.gather(
            *[_resolve_ipv4(host) for _, host in DIRECT_HOSTS])
        for (label, host), ip in zip(DIRECT_HOSTS, resolved):
            if ip:
                jobs.append((label, ip, f"{host} · {ip}"))
            else:
                jobs.append((label, host, f"{host} · IP не разрешился"))
        return await asyncio.gather(
            *[_check_one(session, label, target, shown)
              for label, target, shown in jobs])


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
