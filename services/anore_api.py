"""Клиент платёжной системы anore (anore.cc).

Авторизация — Bearer-ключ аккаунта (an_live_ / an_test_), для ключей
аккаунта обязателен shopId магазина.
Создание платежа: POST /payments, проверка: GET /payments/{id}.

Вебхуки anore (payment.succeeded / payment.canceled) приходят на
/api/webhooks/anore и проверяются HMAC-SHA256 по сырому телу запроса
(заголовок Anore-Signature). Опрос статусов остаётся страховкой,
если вебхук не дойдёт.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid

import aiohttp

from config import load_config

BASE_URL = "https://api.anore.cc/v1"

# Статусы платежа из документации anore
STATUS_NEW = "new"
STATUS_PAID = "paid"
STATUS_EXPIRED = "expired"


def _creds() -> tuple[str, str]:
    cfg = load_config()
    key = (cfg.get("anore_api_key") or "").strip()
    shop = str(cfg.get("anore_shop_id") or "").strip()
    return key, shop


def is_configured() -> bool:
    key, shop = _creds()
    return bool(key and shop)


def _shop_id() -> int | None:
    """ID магазина как int — для shopId в запросах к API."""
    _key, shop = _creds()
    try:
        return int(shop)
    except (TypeError, ValueError):
        return None


def _headers() -> dict:
    key, _shop = _creds()
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _request(method: str, path: str, payload: dict | None = None,
                   timeout: int = 30, params: dict | None = None
                   ) -> tuple[int | None, dict | str | None, str]:
    """Возвращает (http_код, разобранное_тело, текст_ошибки)."""
    url = f"{BASE_URL}{path}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as s:
            async with s.request(method, url, json=payload, params=params,
                                 headers=_headers()) as r:
                text = await r.text()
                try:
                    body = await r.json(content_type=None)
                except Exception:
                    body = text
                return r.status, body, ""
    except asyncio.TimeoutError:
        return None, None, "таймаут запроса к anore"
    except aiohttp.ClientError as e:
        return None, None, f"сеть: {str(e)[:80]}"
    except Exception as e:
        return None, None, str(e)[:80]


def _err_text(status: int, body) -> str:
    if isinstance(body, dict):
        for key in ("message", "error", "detail", "title"):
            if body.get(key):
                return f"{status}: {body[key]}"
    if isinstance(body, str) and body.strip():
        return f"{status}: {body.strip()[:120]}"
    return f"HTTP {status}"


async def create_payment(amount: int, description: str, tg_id: int,
                         username: str | None = None,
                         order_id: str | None = None,
                         success_url: str | None = None,
                         fail_url: str | None = None,
                         back_url: str | None = None) -> dict:
    """Создаёт платёж и возвращает ссылку на оплату.

    Способ оплаты (СБП или крипта) человек выбирает сам на форме anore —
    в настройках магазина включены оба. Редиректы после оплаты по
    умолчанию берутся из настроек магазина, но их можно переопределить
    для одного счёта: success_url — после успешной оплаты, fail_url —
    при неуспехе или истечении, back_url — кнопка «вернуться» на форме.
    """
    if not is_configured():
        return {"ok": False, "error": "anore не настроена (нет ключа или id магазина)"}

    _key, shop = _creds()
    try:
        shop_id = int(shop)
    except (TypeError, ValueError):
        return {"ok": False, "error": "id магазина anore — не число"}

    payload = {
        "amount": int(amount),
        "description": description[:200],
        "shopId": shop_id,
        # orderId виден в кабинете anore и возвращается в вебхуке —
        # по нему видно, чей счёт, даже без сверки с базой бота
        "orderId": order_id or f"tg{tg_id}-{uuid.uuid4().hex[:12]}",
    }
    if success_url:
        payload["successurl"] = success_url
    if fail_url:
        payload["failurl"] = fail_url
    if back_url:
        payload["getbackurl"] = back_url
    status, body, err = await _request("POST", "/payments", payload)
    if err:
        return {"ok": False, "error": err}
    if status not in (200, 201) or not isinstance(body, dict):
        return {"ok": False, "error": _err_text(status, body)}

    pay_id = body.get("id")
    link = body.get("paymentUrl")
    if not pay_id or not link:
        return {"ok": False, "error": f"ответ без id/paymentUrl: {str(body)[:120]}"}

    return {
        "ok": True,
        "payment_id": str(pay_id),
        "url": link,
        "status": body.get("status", STATUS_NEW),
        "expires_in": body.get("expiresIn"),
    }


async def get_status(payment_id: str) -> dict:
    """Текущий статус платежа: new | paid | expired."""
    if not is_configured():
        return {"ok": False, "error": "anore не настроена"}

    status, body, err = await _request("GET", f"/payments/{payment_id}", timeout=20)
    if err:
        return {"ok": False, "error": err}
    if status == 404:
        return {"ok": False, "error": "платёж не найден", "not_found": True}
    if status != 200 or not isinstance(body, dict):
        return {"ok": False, "error": _err_text(status, body)}

    return {
        "ok": True,
        "status": (body.get("status") or "").lower(),
        "paid": bool(body.get("paid")),
        "amount": body.get("amount"),
        "raw": body,
    }


async def list_payments(status_filter: str | None = None, limit: int = 50,
                        offset: int = 0) -> dict:
    """Список платежей кассы в anore, свежие сверху.

    Удобен для сверки: видно способ оплаты (sbp/crypto) и платежи,
    которых нет в базе бота. Фильтр status — paid/pending/failed/
    written_off (шкала списка отличается от статуса одного платежа).
    """
    params: dict[str, str | int] = {"limit": max(1, min(limit, 200)),
                                    "offset": max(0, offset)}
    shop_id = _shop_id()
    if shop_id is not None:
        params["shopId"] = shop_id
    if status_filter:
        params["status"] = status_filter
    status, body, err = await _request("GET", "/payments", params=params)
    if status not in (200, 201) or not isinstance(body, dict):
        return {"ok": False, "error": err or f"HTTP {status}"}
    return {"ok": True, "total": body.get("total"),
            "payments": body.get("payments", []), "raw": body}


# ---------------------------------------------------------------------------
# Баланс и выплаты (Payout API). Для кассы он должен быть включён в
# кабинете anore, иначе API отвечает 403 — см. _payout_api_error.
# ---------------------------------------------------------------------------

def _payout_api_error(status: int | None, err: str) -> dict:
    if status == 403:
        return {"ok": False, "payout_api_disabled": True,
                "error": "Payout API не включён для этой кассы — "
                         "включи его в кабинете anore"}
    return {"ok": False, "error": err or f"HTTP {status}"}


async def get_balance() -> dict:
    """Баланс кассы: доступно, в холде, созрело, выведено, комиссии."""
    params = {}
    shop_id = _shop_id()
    if shop_id is not None:
        params["shopId"] = shop_id
    status, body, err = await _request("GET", "/balance", params=params)
    if status not in (200, 201) or not isinstance(body, dict):
        return _payout_api_error(status, err)
    return {"ok": True, "available": body.get("available"),
            "hold": body.get("hold"), "matured": body.get("matured"),
            "withdrawn": body.get("withdrawn"),
            "paid_amount": body.get("paidAmount"),
            "fee": body.get("fee"), "min_amount": body.get("minAmount"),
            "max_amount": body.get("maxAmount"), "raw": body}


async def get_payout_fees() -> dict:
    """Актуальные комиссии на вывод для мерчанта."""
    params = {}
    shop_id = _shop_id()
    if shop_id is not None:
        params["shopId"] = shop_id
    status, body, err = await _request("GET", "/payouts/fees", params=params)
    if status not in (200, 201) or not isinstance(body, dict):
        return _payout_api_error(status, err)
    return {"ok": True, "raw": body}


async def get_payout_rates() -> dict:
    """Предварительные курсы выплат (итоговый — в ответе создания)."""
    params = {}
    shop_id = _shop_id()
    if shop_id is not None:
        params["shopId"] = shop_id
    status, body, err = await _request("GET", "/payouts/rates", params=params)
    if status not in (200, 201) or not isinstance(body, dict):
        return _payout_api_error(status, err)
    return {"ok": True, "raw": body}


# Способы вывода: карта РФ и USDT в четырёх сетях. Выплаты по телефону
# и СБП у anore временно приостановлены — их здесь нет.
PAYOUT_METHODS = {
    "card": "💳 Карта РФ",
    "usdt_ton": "💎 USDT · TON",
    "usdt_bep20": "💎 USDT · BNB Chain",
    "usdt_erc20": "💎 USDT · Ethereum",
    "usdt_trc20": "💎 USDT · TRON",
}


def payout_limits(method: str) -> tuple[int, int]:
    """(минимум, максимум) суммы вывода в рублях для способа."""
    if method == "card":
        return 3000, 500000
    return 500, 1500000


async def create_payout(amount: int, method: str, address: str,
                        external_id: str | None = None) -> dict:
    """Создаёт заявку на вывод. Сумма — целые рубли.

    address — полный номер карты (для card) или адрес кошелька в сети
    метода (для usdt_*). Никакие CVV/PIN/секреты сюда не передаются.
    В ответе — комиссия и сумма к получению, реквизиты — только в маске.
    """
    if method not in PAYOUT_METHODS:
        return {"ok": False, "error": f"Неизвестный способ вывода: {method}"}
    low, high = payout_limits(method)
    if not low <= int(amount) <= high:
        return {"ok": False,
                "error": f"Сумма для {PAYOUT_METHODS[method]} — "
                         f"от {low} до {high} ₽"}
    payload = {"amount": int(amount), "method": method, "address": address}
    shop_id = _shop_id()
    if shop_id is not None:
        payload["shopId"] = shop_id
    if external_id:
        payload["externalId"] = external_id
    status, body, err = await _request("POST", "/payouts", payload)
    if status not in (200, 201) or not isinstance(body, dict):
        return _payout_api_error(status, err)
    return {"ok": True, "id": body.get("id"), "status": body.get("status"),
            "amount": body.get("amount"), "fee": body.get("fee"),
            "net": body.get("netRub"),
            "settlement": body.get("settlementRub"),
            "address_masked": body.get("address"),
            "tx_hash": body.get("txHash"), "raw": body}


async def list_payouts(limit: int = 50, cursor: str | None = None) -> dict:
    """Список выплат кассы, от новых к старым (курсорная пагинация)."""
    params: dict[str, str | int] = {"limit": max(1, min(limit, 100))}
    shop_id = _shop_id()
    if shop_id is not None:
        params["shopId"] = shop_id
    if cursor:
        params["cursor"] = cursor
    status, body, err = await _request("GET", "/payouts", params=params)
    if status not in (200, 201) or not isinstance(body, dict):
        return _payout_api_error(status, err)
    return {"ok": True, "items": body.get("items", []),
            "has_more": body.get("hasMore"),
            "next_cursor": body.get("nextCursor"), "raw": body}


async def get_payout(payout_id: str) -> dict:
    """Статус одной выплаты: pending/approved/paid/rejected."""
    status, body, err = await _request("GET", f"/payouts/{payout_id}")
    if status == 404:
        return {"ok": False, "not_found": True,
                "error": "Выплата не найдена в anore"}
    if status not in (200, 201) or not isinstance(body, dict):
        return _payout_api_error(status, err)
    return {"ok": True, "id": body.get("id"), "status": body.get("status"),
            "amount": body.get("amount"), "fee": body.get("fee"),
            "net": body.get("netRub"), "method": body.get("methodCode"),
            "address_masked": body.get("address"),
            "tx_hash": body.get("txHash"), "raw": body}


def verify_webhook(raw_body: bytes, signature: str | None) -> bool:
    """Проверяет подпись вебхука: HMAC-SHA256 по сырому телу.

    Секрет появляется в настройках anore после сохранения url вебхука;
    хранится в config.json как anore_webhook_secret.
    """
    cfg = load_config()
    secret = (cfg.get("anore_webhook_secret") or "").strip()
    if not raw_body or not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature).strip().lower())


async def test_connection() -> dict:
    """Проверяет учётные данные.

    Отдельного метода для этого нет, поэтому запрашиваем несуществующий
    платёж: 401/403 — ключ неверный, 404 — ключ принят.
    """
    if not is_configured():
        return {"ok": False, "error": "не заданы ключ или id магазина"}

    probe = str(uuid.uuid4())
    status, body, err = await _request("GET", f"/payments/{probe}", timeout=20)
    if err:
        return {"ok": False, "error": err}
    if status in (401, 403):
        return {"ok": False, "error": "ключ отклонён (401/403) — проверь ключ и id магазина"}
    if status in (200, 404):
        return {"ok": True, "message": "ключи приняты"}
    return {"ok": False, "error": _err_text(status, body)}
