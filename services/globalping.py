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

# (подпись, [ASN]) — операторы, с которых проверяют наши клиенты.
# У оператора может быть несколько ASN: проб Globalping на домашних
# сетях 0–2 на ASN, и они то появляются, то пропадают, поэтому второй
# ASN заметно повышает шанс поймать живую пробу. ASN проверены через
# RIPEstat whois (AS16345 = BEE-AS, AS15378 = TELE2-RU-AS).
OPERATORS: list[tuple[str, list[str]]] = [
    ("МТС", ["AS8359"]),
    ("МегаФон", ["AS31133"]),
    ("Билайн", ["AS3216", "AS16345"]),
    ("T2", ["AS12958", "AS15378"]),
    ("Ростелеком", ["AS12389"]),
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
                            target: str,
                            operators: list[tuple[str, list[str]]]) -> str | None:
    """Создаёт HTTP-измерение; возвращает его id или None при ошибке."""
    payload = {
        "type": "http",
        "target": target,
        "locations": [{"magic": asn} for _, asns in operators
                      for asn in asns],
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


def _probe_state(res: dict) -> tuple[str, dict]:
    """Один результат пробы -> (state, поля)."""
    status = res.get("status")
    code = res.get("statusCode")
    timings = res.get("timings") or {}
    if status == "finished" and code is not None:
        if code >= 500:
            # сервер отвечает, но сломан upstream (502 и т.п.) —
            # это не блок оператора, а проблема на нашей стороне
            return "error", {"code": code, "ms": timings.get("total")}
        return "ok", {"code": code, "ms": timings.get("total")}
    if status == "failed":
        return "blocked", {"error": _short_error(res)}
    return "blocked", {"error": "нет ответа"}


def _parse_result(measurement: dict | None,
                  operators: list[tuple[str, list[str]]]) -> dict[str, dict]:
    """Сырое измерение -> {оператор: {state, code, ms, city}}.

    У оператора может быть несколько ASN: берём лучший исход по
    приоритету ok > error > blocked > no_probe, а город/время — из
    пробы, которая этот исход дала.
    """
    out: dict[str, dict] = {}
    results = (measurement or {}).get("results") or []
    by_asn: dict[int, dict] = {}
    for r in results:
        probe = r.get("probe") or {}
        by_asn[probe.get("asn")] = r
    order = {"ok": 0, "error": 1, "blocked": 2, "no_probe": 3}
    for label, asns in operators:
        best: dict | None = None
        for asn in asns:
            r = by_asn.get(int(asn[2:]))
            if r is None:
                continue
            res = r.get("result") or {}
            probe = r.get("probe") or {}
            state, fields = _probe_state(res)
            fields["city"] = probe.get("city")
            if (best is None
                    or order[state] < order[best["state"]]):
                best = {"state": state, **fields}
        out[label] = best if best is not None else {"state": "no_probe"}
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
                     label: str, domain: str,
                     operators: list[tuple[str, list[str]]]) -> dict:
    """Один домен: создать измерение, дождаться, распарсить."""
    mid = await _post_measurement(session, domain, operators)
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
            "operators": _parse_result(measurement, operators)}


_RETRY_ATTEMPTS = 3
_RETRY_PAUSE = 10.0


async def check_all(domains: list[tuple[str, str]] | None = None,
                  operators: list[tuple[str, list[str]]] | None = None) -> list[dict]:
    """Проверяет выбранные домены с выбранных операторов. По умолчанию —
    все домены (TARGETS) со всех операторов (OPERATORS). Возвращает список
    {label, domain, operators: {оператор: {...}} | error}.

    Проб Globalping на домашних сетях 0–2 на оператора, и они то
    появляются, то пропадают, поэтому если после первой попытки у
    оператора не нашлось пробы, проверка повторяется только для него
    (до 2 повторов с паузой) — шанс поймать живую пробу заметно выше.
    """
    domains = domains or TARGETS
    operators = operators or OPERATORS
    timeout = aiohttp.ClientTimeout(total=90)
    # trust_env: учитывать прокси из окружения (в песочнице без этого
    # TLS-рукопожатие падает; на сервере переменных прокси нет).
    async with aiohttp.ClientSession(timeout=timeout,
                                     trust_env=True) as session:
        results = await asyncio.gather(
            *[_check_one(session, label, domain, operators)
              for label, domain in domains]
        )
        for _ in range(_RETRY_ATTEMPTS - 1):
            missing = _missing_operators(results, operators)
            if not missing:
                break
            await asyncio.sleep(_RETRY_PAUSE)
            retry = await asyncio.gather(
                *[_check_one(session, label, domain, missing)
                  for label, domain in domains]
            )
            _merge_results(results, retry)
        return results


def _missing_operators(results: list[dict],
                       operators: list[tuple[str, list[str]]]
                       ) -> list[tuple[str, list[str]]]:
    """Операторы, у которых хотя бы по одному домену нет пробы."""
    wanted = {label for label, _ in operators}
    missing = set()
    for r in results:
        for label, op in (r.get("operators") or {}).items():
            if op.get("state") == "no_probe":
                missing.add(label)
    return [(label, asns) for label, asns in operators
            if label in missing and label in wanted]


def _merge_results(results: list[dict], retry: list[dict]) -> None:
    """Вписывает исходы повторной попытки в пропуски первой."""
    for base, extra in zip(results, retry):
        ops = base.get("operators") or {}
        for label, op in (extra.get("operators") or {}).items():
            if ops.get(label, {}).get("state") == "no_probe":
                ops[label] = op


def summarize_operators(results: list[dict]) -> dict[str, str]:
    """Итог по операторам: {оператор: mark}, где mark — один из:
    ✅ — все проверенные домены доступны;
    ❌ — хотя бы один домен недоступен (блок);
    ⚠️ — есть ошибка сервера (5xx), блоков нет;
    — — ни по одному домену нет онлайн-пробы."""
    marks: dict[str, str] = {}
    for r in results:
        for label, op in (r.get("operators") or {}).items():
            state = op.get("state")
            cur = marks.get(label)
            if state == "blocked":
                marks[label] = "❌"
            elif state == "error":
                if cur != "❌":
                    marks[label] = "⚠️"
            elif state == "ok":
                if cur not in ("❌", "⚠️"):
                    marks[label] = "✅"
            else:  # no_probe
                if cur is None:
                    marks[label] = "—"
    return marks


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
