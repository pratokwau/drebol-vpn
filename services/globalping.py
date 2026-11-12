"""Проверка доступности наших доменов у российских операторов.

Через Globalping (globalping.io): бесплатный сервис, пробы стоят на
реальных домашних сетях (eyeball), а не в дата-центрах. Измерение —
HTTP HEAD с проб, выбранных по ASN оператора. Ключ API не нужен
(анонимный режим), лимиты — см. доку Globalping.

Проверяем 4 публичных домена с 5 операторов: МТС, МегаФон, Билайн,
T2, Ростелеком. Один запрос на домен: 5 локаций (по одной пробе
на оператора) — всего 4 измерения на проверку.

Исход на оператора:
- ok — проба получила HTTP-ответ (любой код: сервер отвечает);
- blocked — проба не дождалась ответа (таймаут/сброс/DNS) — признак
  блокировки на уровне оператора;
- no_probe — у Globalping сейчас нет онлайн-пробы в этой сети —
  это НЕ блок, просто повторить позже.
"""

from __future__ import annotations

import asyncio

import aiohttp

API_BASE = "https://api.globalping.io/v1"

# (подпись, ASN) — операторы, с которых проверяют наши клиенты
OPERATORS: list[tuple[str, str]] = [
    ("МТС", "AS8359"),
    ("МегаФон", "AS31133"),
    ("Билайн", "AS3216"),
    ("T2", "AS12958"),
    ("Ростелеком", "AS12389"),
]

# (подпись, домен) — что проверяем
TARGETS: list[tuple[str, str]] = [
    ("Сайт", "vpn.drbl.tech"),
    ("Подписка", "key.drbl.tech"),
    ("Финляндия", "helsinki.tembadr.tech"),
    ("Германия", "berlin.tembadr.tech"),
]

_POLL_INTERVAL = 2.0
_POLL_TIMEOUT = 60.0


async def _post_measurement(session: aiohttp.ClientSession,
                            target: str) -> str | None:
    """Создаёт HTTP-измерение; возвращает его id или None при ошибке."""
    payload = {
        "type": "http",
        "target": target,
        "locations": [{"magic": asn} for _, asn in OPERATORS],
        "limit": 1,
        "measurementOptions": {
            "protocol": "HTTPS",
            "request": {"method": "HEAD"},
        },
    }
    try:
        async with session.post(f"{API_BASE}/measurements",
                                json=payload, timeout=20) as resp:
            body = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None
    if resp.status != 202 and resp.status != 200:
        return None
    return (body or {}).get("id")


async def _fetch_measurement(session: aiohttp.ClientSession,
                             measurement_id: str) -> dict | None:
    try:
        async with session.get(f"{API_BASE}/measurements/{measurement_id}",
                               timeout=20) as resp:
            return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


def _parse_result(measurement: dict | None) -> dict[str, dict]:
    """Сырое измерение -> {оператор: {state, code, ms, city}}."""
    out: dict[str, dict] = {}
    results = (measurement or {}).get("results") or []
    by_asn = {}
    for r in results:
        probe = r.get("probe") or {}
        by_asn[probe.get("asn")] = r
    for label, asn in OPERATORS:
        r = by_asn.get(int(asn[2:]))
        if r is None:
            out[label] = {"state": "no_probe"}
            continue
        res = r.get("result") or {}
        probe = r.get("probe") or {}
        status = res.get("status")
        code = res.get("statusCode")
        timings = res.get("timings") or {}
        if status == "finished" and code is not None:
            if code >= 500:
                # сервер отвечает, но сломан upstream (502 и т.п.) —
                # это не блок оператора, а проблема на нашей стороне
                out[label] = {"state": "error", "code": code,
                              "ms": timings.get("total"),
                              "city": probe.get("city")}
            else:
                out[label] = {"state": "ok", "code": code,
                              "ms": timings.get("total"),
                              "city": probe.get("city")}
        elif status == "failed":
            out[label] = {"state": "blocked",
                          "error": _short_error(res)}
        else:
            out[label] = {"state": "blocked",
                          "error": "нет ответа"}
    return out


def _short_error(res: dict) -> str:
    """Короткая причина неуспеха для экрана (без технических деталей)."""
    err = (res.get("error") or "").strip()
    if err:
        return err[:60]
    raw = (res.get("rawOutput") or "").strip()
    if raw:
        return raw.splitlines()[0][:60]
    return "нет ответа"


async def _check_one(session: aiohttp.ClientSession,
                     label: str, domain: str) -> dict:
    """Один домен: создать измерение, дождаться, распарсить."""
    mid = await _post_measurement(session, domain)
    if not mid:
        return {"label": label, "domain": domain, "error": "Globalping не ответил"}
    deadline = asyncio.get_event_loop().time() + _POLL_TIMEOUT
    measurement = None
    while asyncio.get_event_loop().time() < deadline:
        measurement = await _fetch_measurement(session, mid)
        if measurement and measurement.get("status") == "finished":
            break
        await asyncio.sleep(_POLL_INTERVAL)
    if not measurement or measurement.get("status") != "finished":
        return {"label": label, "domain": domain,
                "error": "проверка не завершилась вовремя"}
    return {"label": label, "domain": domain,
            "operators": _parse_result(measurement)}


async def check_all() -> list[dict]:
    """Проверяет все домены со всех операторов. Возвращает список
    {label, domain, operators: {оператор: {...}} | error}."""
    timeout = aiohttp.ClientTimeout(total=90)
    # trust_env: учитывать прокси из окружения (в песочнице без этого
    # TLS-рукопожатие падает; на сервере переменных прокси нет).
    async with aiohttp.ClientSession(timeout=timeout,
                                     trust_env=True) as session:
        return await asyncio.gather(
            *[_check_one(session, label, domain)
              for label, domain in TARGETS]
        )


def summarize(results: list[dict]) -> tuple[int, int, int, int]:
    """(ok, blocked, no_probe, error) по всем парам домен×оператор."""
    ok = blocked = no_probe = error = 0
    for r in results:
        for op in (r.get("operators") or {}).values():
            state = op.get("state")
            if state == "ok":
                ok += 1
            elif state == "blocked":
                blocked += 1
            elif state == "error":
                error += 1
            else:
                no_probe += 1
    return ok, blocked, no_probe, error
