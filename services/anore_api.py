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


def _headers() -> dict:
    key, _shop = _creds()
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _request(method: str, path: str, payload: dict | None = None,
                   timeout: int = 30) -> tuple[int | None, dict | str | None, str]:
    """Возвращает (http_код, разобранное_тело, текст_ошибки)."""
    url = f"{BASE_URL}{path}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as s:
            async with s.request(method, url, json=payload,
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
                         order_id: str | None = None) -> dict:
    """Создаёт платёж и возвращает ссылку на оплату.

    Способ оплаты (СБП или крипта) человек выбирает сам на форме anore —
    в настройках магазина включены оба. Редиректы после оплаты тоже
    задаются в настройках магазина, а не в каждом счёте.
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
