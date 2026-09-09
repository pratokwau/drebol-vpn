"""Клиент платёжной системы Platega.

Авторизация — заголовки X-MerchantId / X-Secret.
Создание платежа: POST /transaction/process, проверка: GET /transaction/{id}.

Колбэки Platega требуют публичный HTTPS с валидным сертификатом, поэтому
статус оплаты бот выясняет опросом — так интеграция не зависит от того,
занят ли на сервере 443-й порт.
"""

from __future__ import annotations

import asyncio
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
DEFAULT_METHOD = 2

# PaymentStatus из документации
STATUS_PENDING = "PENDING"
STATUS_CONFIRMED = "CONFIRMED"
STATUS_CANCELED = "CANCELED"
STATUS_CHARGEBACKED = "CHARGEBACKED"
FINAL_STATUSES = {STATUS_CONFIRMED, STATUS_CANCELED, STATUS_CHARGEBACKED}


def is_configured() -> bool:
    cfg = load_config()
    return bool(cfg.get("platega_merchant_id") and cfg.get("platega_secret"))


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
                   timeout: int = 30) -> tuple[int | None, dict | str | None, str]:
    """Возвращает (http_код, разобранное_тело, текст_ошибки)."""
    url = f"{BASE_URL}{path}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as s:
            async with s.request(method, url, json=payload, headers=_headers()) as r:
                text = await r.text()
                try:
                    body = await r.json(content_type=None)
                except Exception:
                    body = text
                return r.status, body, ""
    except asyncio.TimeoutError:
        return None, None, "таймаут запроса к Platega"
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
                         method: int | None = None) -> dict:
    """Создаёт платёж и возвращает ссылку на оплату."""
    if not is_configured():
        return {"ok": False, "error": "Platega не настроена (нет MerchantId или ключа)"}

    cfg = load_config()
    if method is None:
        method = int(cfg.get("platega_method", DEFAULT_METHOD) or DEFAULT_METHOD)

    ret = _return_url()
    payload = {
        "paymentMethod": method,
        "paymentDetails": {"amount": amount, "currency": "RUB"},
        "description": description[:200],
        "return": ret,
        "failedUrl": ret,
        # payload возвращается в колбэке — кладём, кому засчитать оплату
        "payload": str(tg_id),
        "metadata": {
            "userId": str(tg_id),
            "userName": f"@{username}" if username else f"id{tg_id}",
        },
    }
    if order_id:
        payload["orderId"] = str(order_id)

    status, body, err = await _request("POST", "/transaction/process", payload)
    if err:
        return {"ok": False, "error": err}
    if status not in (200, 201) or not isinstance(body, dict):
        return {"ok": False, "error": _err_text(status, body)}

    tx_id = body.get("transactionId") or body.get("id")
    link = body.get("redirect")
    if not tx_id or not link:
        return {"ok": False, "error": f"ответ без transactionId/redirect: {str(body)[:120]}"}

    return {
        "ok": True,
        "transaction_id": str(tx_id),
        "url": link,
        "status": body.get("status", STATUS_PENDING),
        "expires_in": body.get("expiresIn"),
    }


async def get_status(transaction_id: str) -> dict:
    """Текущий статус транзакции."""
    if not is_configured():
        return {"ok": False, "error": "Platega не настроена"}

    status, body, err = await _request("GET", f"/transaction/{transaction_id}", timeout=20)
    if err:
        return {"ok": False, "error": err}
    if status == 404:
        return {"ok": False, "error": "транзакция не найдена", "not_found": True}
    if status != 200 or not isinstance(body, dict):
        return {"ok": False, "error": _err_text(status, body)}

    details = body.get("paymentDetails") or {}
    amount = details.get("amount") if isinstance(details, dict) else None
    return {
        "ok": True,
        "status": (body.get("status") or "").upper(),
        "amount": amount,
        "payload": body.get("payload"),
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
