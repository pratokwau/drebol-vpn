"""Клиент платёжной системы Platega.

Основной API: https://app.platega.io, авторизация — заголовки
X-MerchantId / X-Secret (кабинет → Настройки → API-ключи).
Создание платежа: POST /v2/transaction/process (способ выбирает
плательщик на форме), проверка: GET /transaction/{id}.
Статусы: PENDING → CONFIRMED / CANCELED / CHARGEBACKED
(+ PARTIALLY_REFUNDED после частичного возврата).

Колбэки: Platega шлёт POST на Callback URL из кабинета (Настройки →
Callback URLs) с заголовками X-MerchantId / X-Secret; проверка —
сверка этих заголовков с настройками бота. Тело: id (uuid уведомления),
status, paymentMethod, payload. Отвечать 200. Выдавать подписку —
только после CONFIRMED. Опрос статусов — страховка, если колбэк
не дойдёт.

Возвраты ЕСТЬ (в отличие от anore): cancel-supported → cancel /
cancel-partial; итог — только через колбэк (refundStatus).

Выводы — отдельный Payout API: https://app.platega.io/api/v1,
авторизация HMAC (PG-HMAC), секрет — отдельный, из раздела Payout API
в кабинете; IP сервера должен быть в белом списке ключа.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid

import aiohttp

from config import load_config

BASE_URL = "https://app.platega.io"
PAYOUT_BASE_URL = "https://app.platega.io/api/v1"

# PaymentMethodInt из документации
PAYMENT_METHODS = {
    2: "СБП (QR-код)",
    3: "ЕРИП",
    11: "Карты",
    12: "Международная оплата",
    13: "Криптовалюта",
    14: "SberPay",
}

# Статусы платежа — нормализованные, как их видят опрос и вебхук.
# Сырой статус Platega лежит в get_status()["platega_status"].
STATUS_PENDING = "pending"
STATUS_PAID = "paid"
STATUS_CANCELED = "canceled"
STATUS_CHARGEBACKED = "chargebacked"
STATUS_PARTIALLY_REFUNDED = "partially_refunded"
# отдельного EXPIRED у Platega нет: неоплаченный счёт через 15 минут
# становится CANCELED — опрос помечает его так же
STATUS_EXPIRED = "expired"

_RAW_TO_NORM = {
    "PENDING": STATUS_PENDING,
    "CONFIRMED": STATUS_PAID,
    "CANCELED": STATUS_CANCELED,
    "CHARGEBACKED": STATUS_CHARGEBACKED,
    "PARTIALLY_REFUNDED": STATUS_PARTIALLY_REFUNDED,
    "DISPUTED": STATUS_CHARGEBACKED,
}

# Счёт Platega живёт 15 минут (expiresIn "00:15:00") — дольше этого
# срока оплату ждать нечего
INVOICE_TTL_MINUTES = 15


def is_configured() -> bool:
    cfg = load_config()
    return bool(cfg.get("platega_merchant_id") and cfg.get("platega_secret"))


def is_payout_configured() -> bool:
    """Настроены ли выводы: нужен отдельный секрет Payout API."""
    cfg = load_config()
    return bool(cfg.get("platega_merchant_id")
                and cfg.get("platega_payout_secret"))


def _merchant_id() -> str:
    cfg = load_config()
    return (cfg.get("platega_merchant_id") or "").strip()


def _headers() -> dict:
    cfg = load_config()
    return {
        "X-MerchantId": (cfg.get("platega_merchant_id") or "").strip(),
        "X-Secret": (cfg.get("platega_secret") or "").strip(),
        "Content-Type": "application/json",
    }


def _return_url() -> str:
    """Куда вернуть человека после оплаты — в самого бота."""
    cfg = load_config()
    uname = (cfg.get("bot_username") or "").lstrip("@")
    return f"https://t.me/{uname}" if uname else "https://t.me"


async def _request(method: str, path: str, payload: dict | None = None,
                   timeout: int = 30, headers: dict | None = None
                   ) -> tuple[int | None, dict | str | None, str]:
    """Возвращает (http_код, разобранное_тело, текст_ошибки)."""
    url = f"{BASE_URL}{path}"
    merged = _headers()
    if headers:
        merged.update(headers)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as s:
            async with s.request(method, url, json=payload, headers=merged) as r:
                text = await r.text()
                try:
                    body = await r.json(content_type=None)
                except Exception:
                    body = text
                return r.status, body, ""
    except asyncio.TimeoutError:
        await _log_api_error("таймаут запроса к Platega")
        return None, None, "таймаут запроса к Platega"
    except aiohttp.ClientError as e:
        await _log_api_error(f"сеть: {str(e)[:80]}")
        return None, None, f"сеть: {str(e)[:80]}"
    except Exception as e:
        await _log_api_error(str(e)[:80])
        return None, None, str(e)[:80]


async def _log_api_error(text: str):
    """Ошибка вызова Platega — в журнал ошибок. Не ломает запрос при сбое БД."""
    try:
        from core.database import log_error
        await log_error("platega", "error", text)
    except Exception:
        pass


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

    POST /v2/transaction/process без paymentMethod — способ (СБП,
    карта, крипта) человек выбирает сам на форме Platega.
    success_url — куда вернуть после успешной оплаты (return),
    fail_url — при неуспехе (failedUrl); back_url у Platega нет —
    кнопка «вернуться» на форме ведёт на return.
    user_email обязателен по документации — для Telegram берём
    {tg_id}@telegram.org.
    """
    if not is_configured():
        return {"ok": False, "error": "Platega не настроена (нет MerchantId или ключа)"}

    ret = success_url or _return_url()
    payload = {
        "paymentDetails": {"amount": int(amount), "currency": "RUB"},
        "description": description[:200],
        "return": ret,
        "failedUrl": fail_url or ret,
        # payload возвращается в колбэке — кладём наш id заказа
        "payload": order_id or f"tg{tg_id}-{uuid.uuid4().hex[:12]}",
        "metadata": {
            "userId": str(tg_id),
            "userName": f"@{username}" if username else f"id{tg_id}",
            "user_email": f"{tg_id}@telegram.org",
        },
    }

    status, body, err = await _request("POST", "/v2/transaction/process", payload)
    if err:
        return {"ok": False, "error": err}
    if status not in (200, 201) or not isinstance(body, dict):
        return {"ok": False, "error": _err_text(status, body)}

    tx_id = body.get("transactionId") or body.get("id")
    link = body.get("url") or body.get("redirect")
    if not tx_id or not link:
        return {"ok": False, "error": f"ответ без transactionId/url: {str(body)[:120]}"}

    return {
        "ok": True,
        "payment_id": str(tx_id),
        "url": link,
        "status": _RAW_TO_NORM.get((body.get("status") or "").upper(),
                                   STATUS_PENDING),
        "expires_in": body.get("expiresIn"),
    }


async def get_status(transaction_id: str) -> dict:
    """Текущий статус транзакции: paid / pending / canceled /
    chargebacked / partially_refunded."""
    if not is_configured():
        return {"ok": False, "error": "Platega не настроена"}

    status, body, err = await _request("GET", f"/transaction/{transaction_id}", timeout=20)
    if err:
        return {"ok": False, "error": err}
    if status == 404:
        return {"ok": False, "error": "транзакция не найдена", "not_found": True}
    if status != 200 or not isinstance(body, dict):
        return {"ok": False, "error": _err_text(status, body)}

    raw_status = (body.get("status") or "").upper()
    # amount — поле верхнего уровня; paymentDetails в ответе — строка
    amount = body.get("amount")
    return {
        "ok": True,
        "status": _RAW_TO_NORM.get(raw_status, STATUS_PENDING),
        "platega_status": raw_status,
        "paid": raw_status == "CONFIRMED",
        "amount": amount,
        "payload": body.get("payload"),
        "raw": body,
    }


async def get_balance() -> dict:
    """Балансы кассы: рубли и USDT, доступно и заморожено."""
    if not is_configured():
        return {"ok": False, "error": "Platega не настроена"}
    status, body, err = await _request("GET", "/balance/all", timeout=20)
    if err:
        return {"ok": False, "error": err}
    if status != 200 or not isinstance(body, list):
        return {"ok": False, "error": _err_text(status, body)}
    out = {"ok": True, "rub": None, "usdt": None,
           "frozen_rub": None, "frozen_usdt": None, "raw": body}
    for row in body:
        if not isinstance(row, dict):
            continue
        cur = (row.get("currency") or "").upper()
        if cur == "RUB":
            out["rub"] = row.get("amount")
            out["frozen_rub"] = row.get("frozenBalance")
        elif cur == "USDT":
            out["usdt"] = row.get("amount")
            out["frozen_usdt"] = row.get("frozenBalance")
    return out


def verify_callback(headers) -> bool:
    """Проверяет заголовки колбэка Platega.

    Platega шлёт X-MerchantId и X-Secret — те же, что в настройках
    бота. Совпали оба — колбэк настоящий.
    """
    cfg = load_config()
    merchant = (cfg.get("platega_merchant_id") or "").strip()
    secret = (cfg.get("platega_secret") or "").strip()
    if not merchant or not secret:
        return False
    got_merchant = (headers.get("X-MerchantId") or "").strip()
    got_secret = (headers.get("X-Secret") or "").strip()
    return (hmac.compare_digest(got_merchant, merchant)
            and hmac.compare_digest(got_secret, secret))


# ── Возвраты ─────────────────────────────────────────────────────────────────

async def refund_supported(transaction_id: str, amount: int | None = None) -> dict:
    """Можно ли вернуть платёж и во что это обойдётся.

    Возврат оплачивается с баланса мерчанта: если на нём не хватает
    средств, Platega отвечает supported=false.
    """
    if not is_configured():
        return {"ok": False, "error": "Platega не настроена"}
    path = f"/transaction/{transaction_id}/cancel-supported"
    if amount:
        path += f"?amount={int(amount)}"
    status, body, err = await _request("GET", path, timeout=20)
    if err:
        return {"ok": False, "error": err}
    if status != 200 or not isinstance(body, dict):
        return {"ok": False, "error": _err_text(status, body)}
    return {
        "ok": True,
        "supported": bool(body.get("supported")),
        "partial_supported": body.get("partialSupported"),
        "refundable_amount": body.get("refundableAmount"),
        "refunded_amount": body.get("refundedAmount"),
        "deduct_usdt": body.get("totalDeductUsdt"),
        "penalty_usdt": body.get("penaltyUsdt"),
        "block_reason": body.get("blockReason"),
    }


async def refund(transaction_id: str) -> dict:
    """Запускает полный возврат.

    Возврат может пройти не сразу: пока Platega его обрабатывает, она
    отвечает accepted=false и manualControlRequired=true. Окончательный
    итог виден по статусу транзакции — CHARGEBACKED — и приходит
    колбэком (refundStatus).
    """
    if not is_configured():
        return {"ok": False, "error": "Platega не настроена"}
    status, body, err = await _request(
        "POST", f"/transaction/{transaction_id}/cancel", timeout=30
    )
    if err:
        return {"ok": False, "error": err}
    if status != 200 or not isinstance(body, dict):
        return {"ok": False, "error": _err_text(status, body)}
    return {
        "ok": True,
        "accepted": bool(body.get("accepted")),
        "manual": bool(body.get("manualControlRequired")),
        "message": body.get("message") or "",
    }


async def refund_partial(transaction_id: str, amount: int) -> dict:
    """Частичный возврат: POST /transaction/{id}/cancel-partial.

    amount — целое число в валюте исходной транзакции (для бота — рубли);
    отдельного поля валюты у эндпоинта нет. Сумма не может превысить
    доступный остаток — иначе Platega вернёт AMOUNT_EXCEEDS_REFUNDABLE.
    Частичных возвратов по одному платежу может быть несколько, пока
    их сумма не превысит исходную. Idempotency-Key обязателен по
    документации — генерируем уникальный на операцию.
    Ответ повторяет форму полного возврата + refundOperationId.
    """
    if not is_configured():
        return {"ok": False, "error": "Platega не настроена"}
    status, body, err = await _request(
        "POST", f"/transaction/{transaction_id}/cancel-partial",
        {"amount": int(amount)}, timeout=30,
        headers={"Idempotency-Key": f"partial-refund-{uuid.uuid4().hex}"},
    )
    if err:
        return {"ok": False, "error": err}
    if status != 200 or not isinstance(body, dict):
        return {"ok": False, "error": _err_text(status, body)}
    return {
        "ok": True,
        "accepted": bool(body.get("accepted")),
        "manual": bool(body.get("manualControlRequired")),
        "message": body.get("message") or "",
        "refund_operation_id": body.get("refundOperationId"),
    }


async def test_connection() -> dict:
    """Проверяет учётные данные.

    Отдельного метода для этого нет, поэтому запрашиваем несуществующую
    транзакцию: 401/403 — ключи неверные, 404 — ключи приняты.
    """
    if not is_configured():
        return {"ok": False, "error": "не заданы MerchantId или ключ"}

    probe = str(uuid.uuid4())
    status, body, err = await _request("GET", f"/transaction/{probe}", timeout=20)
    if err:
        return {"ok": False, "error": err}
    if status in (401, 403):
        return {"ok": False, "error": "ключи отклонены (401/403) — проверь MerchantId и Secret"}
    if status in (200, 404):
        return {"ok": True, "message": "ключи приняты"}
    return {"ok": False, "error": _err_text(status, body)}


# ── Выводы (Payout API) ──────────────────────────────────────────────────────
# Отдельный API на HMAC-подписи (PG-HMAC): строка подписи —
# METHOD\nPATH\ntimestamp\nidempotency-key\nsha256_hex(body),
# заголовок Authorization: PG-HMAC kid={MERCHANT_ID}, ts={ts}, sig={sig}.
# Секрет — отдельный, из раздела Payout API в кабинете; IP сервера
# должен быть в белом списке ключа. У Payout API нет списка выплат —
# историю созданных ботом выплат ведём в своей базе (таблица payouts).

PAYOUT_METHODS = {
    "card": "💳 Карта РФ",
    "sbp": "📱 СБП по телефону",
    "usdt_trc20": "💎 USDT · TRON",
    "usdt_ton": "💎 USDT · TON",
    "usdt_bep20": "💎 USDT · BNB Chain",
    "usdt_erc20": "💎 USDT · Ethereum",
}

_USDT_NETWORKS = {
    "usdt_trc20": "TRX-TRC20",
    "usdt_ton": "TON",
    "usdt_bep20": "BSC-BEP20",
    "usdt_erc20": "ETH-ERC20",
}


def payout_limits(method: str) -> tuple[int, int]:
    """(минимум, максимум) суммы вывода.

    Для рублей лимиты из документации (1000–100000 ₽); для USDT
    документация лимитов не даёт — широкие (1–100000), отсекает
    только мусор.
    """
    if method in ("card", "sbp"):
        return 1000, 100000
    return 1, 100000


def _payout_headers(method: str, path: str, body: bytes) -> dict:
    """Заголовки PG-HMAC для запроса к Payout API."""
    cfg = load_config()
    secret = (cfg.get("platega_payout_secret") or "").strip()
    merchant = _merchant_id()
    ts = str(int(time.time()))
    idem = uuid.uuid4().hex
    body_hash = hashlib.sha256(body).hexdigest()
    sign_string = f"{method}\n{path}\n{ts}\n{idem}\n{body_hash}"
    sig = base64.b64encode(
        hmac.new(secret.encode("utf-8"), sign_string.encode("utf-8"),
                 hashlib.sha256).digest()
    ).decode("ascii")
    return {
        "Authorization": f"PG-HMAC kid={merchant}, ts={ts}, sig={sig}",
        "X-Idempotency-Key": idem,
        "Content-Type": "application/json",
    }


async def _payout_request(method: str, path: str,
                          payload: dict | None = None,
                          timeout: int = 30
                          ) -> tuple[int | None, dict | str | None, str]:
    """Запрос к Payout API. Возвращает (http_код, тело, текст_ошибки)."""
    url = f"{PAYOUT_BASE_URL}{path}"
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else b""
    if method == "GET":
        body = b""
    headers = _payout_headers(method, path, body)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as s:
            async with s.request(method, url, data=body or None,
                                 headers=headers) as r:
                text = await r.text()
                try:
                    parsed = await r.json(content_type=None)
                except Exception:
                    parsed = text
                return r.status, parsed, ""
    except asyncio.TimeoutError:
        await _log_api_error("таймаут запроса к Payout API Platega")
        return None, None, "таймаут запроса к Payout API"
    except aiohttp.ClientError as e:
        await _log_api_error(f"сеть: {str(e)[:80]}")
        return None, None, f"сеть: {str(e)[:80]}"
    except Exception as e:
        await _log_api_error(str(e)[:80])
        return None, None, str(e)[:80]


def _payout_api_error(status: int | None, err: str) -> dict:
    if status in (401, 403):
        return {"ok": False, "payout_api_disabled": True,
                "error": "Payout API не включён для этой кассы — "
                         "включи его в кабинете Platega (раздел Payout API), "
                         "внеси IP сервера в белый список и задай секрет в боте"}
    return {"ok": False, "error": err or f"HTTP {status}"}


async def create_payout(amount, method: str, address: str,
                        bank_id: str | None = None) -> dict:
    """Создаёт заявку на вывод.

    amount — рубли для card/sbp, USDT для usdt_*.
    address — номер карты (card), телефон 11 цифр с 7/8 (sbp) или
    адрес кошелька (usdt_*). Для sbp нужен bank_id из справочника
    банков (/sbp-banks). Никакие CVV/PIN/секреты сюда не передаются.
    В ответе — id записи вывода и списанная сумма в USDT.
    """
    if method not in PAYOUT_METHODS:
        return {"ok": False, "error": f"Неизвестный способ вывода: {method}"}
    low, high = payout_limits(method)
    try:
        amount_num = float(amount)
    except (TypeError, ValueError):
        return {"ok": False, "error": "сумма — число"}
    if not low <= amount_num <= high:
        unit = "₽" if method in ("card", "sbp") else "USDT"
        return {"ok": False,
                "error": f"Сумма для {PAYOUT_METHODS[method]} — "
                         f"от {low} до {high} {unit}"}
    if method == "card":
        path = "/payouts/card-rub"
        payload = {"cardNumber": str(address).replace(" ", ""),
                   "amountRub": int(amount_num),
                   "payoutMethod": "CARD", "currencyRequested": "RUB"}
    elif method == "sbp":
        if not bank_id:
            return {"ok": False, "error": "не выбран банк получателя"}
        phone = "".join(ch for ch in str(address) if ch.isdigit())
        if len(phone) != 11 or phone[0] not in "78":
            return {"ok": False,
                    "error": "телефон — 11 цифр, начинается с 7 или 8"}
        path = "/payouts/sbp-rub"
        payload = {"phone": phone, "bankId": str(bank_id),
                   "amountRub": int(amount_num),
                   "payoutMethod": "SBP", "currencyRequested": "RUB"}
    else:
        path = "/payouts/crypto"
        payload = {"walletAddress": str(address).strip(),
                   "currency": "USDT",
                   "network": _USDT_NETWORKS[method],
                   "amount": amount_num,
                   "payoutMethod": "CRYPTO", "currencyRequested": "USDT"}
    status, body, err = await _payout_request("POST", path, payload)
    if status not in (200, 201) or not isinstance(body, dict):
        return _payout_api_error(status, err)
    return {"ok": True,
            "id": body.get("withdrawalRecordId") or body.get("id"),
            "status": body.get("status"),
            "amount": body.get("amountUsdtDebited") or body.get("amount"),
            "raw": body}


async def get_cards() -> dict:
    """Сохранённые карты мерчанта (для выбора реквизитов)."""
    status, body, err = await _payout_request("GET", "/cards")
    if status not in (200, 201) or not isinstance(body, (list, dict)):
        return _payout_api_error(status, err)
    items = body if isinstance(body, list) else body.get("items", [])
    return {"ok": True, "items": items, "raw": body}


async def get_wallets() -> dict:
    """Сохранённые криптокошельки мерчанта."""
    status, body, err = await _payout_request("GET", "/wallets")
    if status not in (200, 201) or not isinstance(body, (list, dict)):
        return _payout_api_error(status, err)
    items = body if isinstance(body, list) else body.get("items", [])
    return {"ok": True, "items": items, "raw": body}


async def get_sbp_recipients() -> dict:
    """Сохранённые получатели СБП (телефон + банк)."""
    status, body, err = await _payout_request("GET", "/sbp-recipients")
    if status not in (200, 201) or not isinstance(body, (list, dict)):
        return _payout_api_error(status, err)
    items = body if isinstance(body, list) else body.get("items", [])
    return {"ok": True, "items": items, "raw": body}


async def get_sbp_banks() -> dict:
    """Справочник банков для выплат по СБП (кэшировать на стороне бота)."""
    status, body, err = await _payout_request("GET", "/sbp-banks")
    if status not in (200, 201) or not isinstance(body, (list, dict)):
        return _payout_api_error(status, err)
    items = body if isinstance(body, list) else body.get("items", [])
    return {"ok": True, "items": items, "raw": body}
