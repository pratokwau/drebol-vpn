"""Проверка доступности из российских сетей — GhostMesh.

Главный слой проверки операторов (handlers/netcheck.py): живые
пробы сервиса GhostMesh (srs-ghostmesh.com) из российских сетей
(Москва, СПб, Новосибирск, Владивосток и др.; Timeweb, Selectel,
МТС AS8359, Ростелеком AS12389, ER-Telecom и др.) пытаются
подключиться к цели. Ловит именно ТСПУ-блокировки по IP, которых
нет в публичных списках РКН (кейс Швеции 2026-11-28: Cheburcheck
говорил «не в списках», а 22 из 23 проб GhostMesh не смогли
подключиться).

API: POST https://srs-ghostmesh.com/api/connection-check/availability/
тело {"target": <домен|IPv4>, "scope": "wide"|"default",
"wide": bool}. Публичный эндпоинт: авторизация и токены не нужны,
так же его дёргает сам сайт GhostMesh (credentials: omit). Ответ:
{"target", "measuredAt", "cities": [{"city", "status",
"probe": {"network", "asn"}, "resolvedIp"}]}. Результаты у
сервиса кешируются на несколько минут; попадания в кеш лимит
не расходуют.

Статусы проб:
- available — цель полностью доступна;
- tlsError — TCP-подключение проходит, рушится только TLS. Для
  голого IP это норма (проба идёт без нужного SNI): хост достижим;
- failed — соединение не устанавливается вообще: подпись блока.

Итог по цели:
- ok — ни одной failed-пробы: доступен;
- partial — failed меньше половины проб: недоступен из части сетей;
- blocked — failed половина и больше: блок ТСПУ;
- error — ответ не получен (сеть, 5xx после повторов или лимит).

ЛИМИТ СЕРВИСА — ЖЁСТКИЙ (проверено 2026-11-28): пачка параллельных
запросов мгновенно ловит 429, а Retry-After доходит до ~1600 с
(окно порядка получаса; кеш-попадания, похоже, не считаются).
Поэтому: запросы СТРОГО по одному, сначала IP прямых хостов
(главный сигнал), потом домены; пауза между целями; на 429 с
Retry-After ≤ 90 с — подождать и повторить; на длинный
Retry-After — не ждать, а честно помечать эту и остальные цели
«лимит сервиса» и завершать слой с тем, что успело провериться.
Объём проб: широкий (23 города) — IP хостов, обычный (3 города:
Москва, СПб, Новосибирск) — доменам. Незакешированная проверка
цели занимает до ~50 с (сервис реально гоняет пробы).
"""

from __future__ import annotations

import asyncio

import aiohttp

from services.cheburcheck import DIRECT_HOSTS, _resolve_ipv4

API_URL = "https://srs-ghostmesh.com/api/connection-check/availability/"

_TIMEOUT = aiohttp.ClientTimeout(total=60)
_PAUSE_BETWEEN = 3.0
_MAX_RATE_WAITS = 2        # сколько раз ждать короткий Retry-After
_MAX_RATE_WAIT = 90.0      # длиннее — не ждём, слой завершается
_BACKOFF_5XX = [5, 15]     # повторы при 5xx/сетевых сбоях


class _RateLimited(Exception):
    """Сервис просит подождать дольше разумного — слой стоп."""

    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after:.0f}s")
        self.retry_after = retry_after


async def _check_one(session: aiohttp.ClientSession,
                     label: str, target: str, shown: str,
                     wide: bool = False) -> dict:
    """Одна цель: POST availability; повторы при 5xx и коротких 429."""
    out = {"label": label, "target": target, "shown": shown}
    payload = {"target": target,
               "scope": "wide" if wide else "default",
               "wide": wide}
    rate_waits = 0
    tries_5xx = 0
    while True:
        try:
            async with session.post(API_URL, json=payload,
                                    timeout=_TIMEOUT) as resp:
                if resp.status == 200:
                    body = await resp.json(content_type=None)
                    if isinstance(body, dict) and body.get("cities"):
                        return _parse(out, body)
                    last_error = "пустой ответ"
                elif resp.status == 429:
                    raw = (resp.headers.get("Retry-After") or "").strip()
                    retry_after = float(raw) if raw.isdigit() else 60.0
                    if retry_after > _MAX_RATE_WAIT:
                        raise _RateLimited(retry_after)
                    if rate_waits >= _MAX_RATE_WAITS:
                        return {**out, "state": "error",
                                "error": "лимит сервиса (429)"}
                    rate_waits += 1
                    await asyncio.sleep(retry_after)
                    continue
                elif resp.status >= 500:
                    last_error = f"HTTP {resp.status}"
                else:
                    return {**out, "state": "error",
                            "error": f"HTTP {resp.status}"}
        except _RateLimited:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            last_error = "нет ответа"
        if tries_5xx >= len(_BACKOFF_5XX):
            return {**out, "state": "error", "error": last_error}
        await asyncio.sleep(_BACKOFF_5XX[tries_5xx])
        tries_5xx += 1


def _parse(out: dict, body: dict) -> dict:
    cities = body.get("cities") or []
    total = len(cities)
    failed = [c for c in cities if c.get("status") == "failed"]
    n_failed = len(failed)
    if n_failed == 0:
        state = "ok"
    elif n_failed * 2 >= total:
        state = "blocked"
    else:
        state = "partial"
    networks: list[str] = []
    for c in failed:
        name = ((c.get("probe") or {}).get("network") or "").strip()
        if name and name not in networks:
            networks.append(name)
    return {
        **out,
        "state": state,
        "total": total,
        "failed": n_failed,
        "available": sum(1 for c in cities
                         if c.get("status") == "available"),
        "tls": sum(1 for c in cities if c.get("status") == "tlsError"),
        "failed_networks": networks,
        "resolved_ip": next((c.get("resolvedIp") for c in cities
                             if c.get("resolvedIp")), None),
    }


async def check_all(domains: list[tuple[str, str]]) -> list[dict]:
    """Проверяет IP прямых хостов (широко) и выбранные домены.

    Порядок — сначала IP хостов: если сервис упрётся в длинный
    лимит, главный ТСПУ-сигнал уже будет на руках, а оставшиеся
    цели честно получат state="error" про лимит.
    """
    jobs: list[tuple[str, str, str, bool]] = []  # (label, target, shown, wide)
    async with aiohttp.ClientSession(trust_env=True) as session:
        for label, host in DIRECT_HOSTS:
            ip = await _resolve_ipv4(host)
            if ip:
                jobs.append((label, ip, f"{host} · {ip}", True))
            else:
                jobs.append((label, host, f"{host} · IP не разрешился", True))
        for label, domain in domains:
            jobs.append((label, domain, domain, False))
        results: list[dict] = []
        limited: float | None = None
        for i, (label, target, shown, wide) in enumerate(jobs):
            if limited is not None:
                results.append({
                    "label": label, "target": target, "shown": shown,
                    "state": "error",
                    "error": f"лимит GhostMesh (~{limited / 60:.0f} мин)"})
                continue
            if i:
                await asyncio.sleep(_PAUSE_BETWEEN)
            try:
                results.append(
                    await _check_one(session, label, target, shown, wide))
            except _RateLimited as exc:
                limited = exc.retry_after
                results.append({
                    "label": label, "target": target, "shown": shown,
                    "state": "error",
                    "error": f"лимит GhostMesh (~{limited / 60:.0f} мин)"})
        return results


def summarize(results: list[dict]) -> tuple[int, int, int, int]:
    """(ok, partial, blocked, error) по всем целям."""
    ok = partial = blocked = error = 0
    for r in results:
        state = r.get("state")
        if state == "ok":
            ok += 1
        elif state == "partial":
            partial += 1
        elif state == "blocked":
            blocked += 1
        else:
            error += 1
    return ok, partial, blocked, error
