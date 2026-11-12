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
"""

from __future__ import annotations

import asyncio
import hmac
import uuid

import aiohttp

from config import load_config

BASE_URL = "https://app.platega.io"

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
