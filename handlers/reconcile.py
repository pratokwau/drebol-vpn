"""Сверка с Platega: каждый счёт из базы против платёжной системы.

Зачем: возврат, сделанный в кабинете Platega, мог не попасть в базу
(вебхук раньше игнорировал колбэки по оплаченным счетам), а частичный
возврат не вычитался из доходов. Сверка сверяет последние счета
(60 дней, до 40 штук) живыми запросами GET /transaction/{id} и
показывает расхождения построчно, с суммой, на которую завышена прибыль.

Исправление правит ТОЛЬКО денежные записи (статус, partial_refunded):
сроки подписок не отзываются и уведомления не отправляются — их админ
решает сам через карточку платежа.
"""

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.database import (
    claim_refund, list_reconcile_payments, set_partial_refunded,
)
import services.platega_api as pg

DAYS = 60
LIMIT = 40
_CONCURRENCY = 5

def compare_payment(row: tuple, res: dict) -> dict | None:
    """Одно расхождение или None, если счёт в порядке.

    row — (id, tg_id, external_id, amount, status, partial_refunded,
    paid_at) из list_reconcile_payments; res — ответ pg.get_status.
    """
    pid, _tg, _ext, amount, status, partial, _paid = row
    if not res.get("ok"):
        if res.get("not_found"):
            return {"kind": "not_found",
                    "text": "в Platega не найден",
                    "fix": None, "impact": 0}
        return {"kind": "unchecked",
                "text": f"не проверено: {res.get('error') or 'ошибка API'}",
                "fix": None, "impact": 0}
    pg_status = res.get("status")
    pg_amount = res.get("amount")
    raw = res.get("raw") or {}
    try:
        pg_refunded = int(float(raw.get("refundedAmount") or 0))
    except (TypeError, ValueError):
        pg_refunded = 0

    def issue(kind: str, text: str, fix=None, impact: int = 0) -> dict:
        return {"kind": kind, "text": text, "fix": fix, "impact": impact}

    if pg_status == pg.STATUS_PAID:
        if status == "paid":
            if pg_amount is not None and int(pg_amount) != int(amount):
                return issue("amount",
                             f"сумма не сходится: в базе {amount} ₽,"
                             f" в Platega {pg_amount} ₽")
            return None
        if status == "pending":
            return issue("missed_confirm",
                         "оплачен в Platega, в базе ждёт оплаты")
        if status in ("refunded", "chargebacked"):
            return issue("refund_mismatch",
                         "в базе возврат, в Platega оплачен")
        return issue("state",
                     f"в базе {status}, в Platega оплачен")
    if pg_status == pg.STATUS_CANCELED:
        if status == "paid":
            return issue("paid_canceled",
                         "в базе оплачен, в Platega отменён",
                         impact=int(amount))
        return None  # pending/canceled/expired — опрос сам доведёт
    if pg_status == pg.STATUS_CHARGEBACKED:
        if status in ("refunded", "chargebacked"):
            return None
        if status == "paid":
            return issue("full_refund_missed",
                         "полный возврат не учтён",
                         fix={"kind": "full"}, impact=int(amount))
        return issue("state",
                     f"в базе {status}, в Platega возврат")
    if pg_status == pg.STATUS_PARTIALLY_REFUNDED:
        if status in ("refunded", "chargebacked"):
            return issue("refund_mismatch",
                         "в базе полный возврат, в Platega частичный")
        if status == "paid":
            if pg_refunded == int(partial or 0):
                return None
            if pg_refunded <= 0:
                return issue("partial_unknown",
                             "частичный возврат без суммы — проверь в Platega")
            return issue("partial_mismatch",
                         f"частичный возврат: в Platega {pg_refunded} ₽,"
                         f" в базе {int(partial or 0)} ₽",
                         fix={"kind": "partial", "amount": pg_refunded},
                         impact=pg_refunded - int(partial or 0))
        return issue("state",
                     f"в базе {status}, в Platega частичный возврат")
    if pg_status == pg.STATUS_PENDING:
        if status == "pending":
            return None
        return issue("state",
                     f"в базе {status}, в Platega ждёт оплаты")
    return issue("unchecked", f"неизвестный статус Platega: {pg_status}")


def _back_rows() -> list:
    return [[InlineKeyboardButton("◀️ К финансам",
                                  callback_data="pay_provider_menu")]]


async def handle_reconcile_menu(query, context: ContextTypes.DEFAULT_TYPE):
    """Экран сверки: что проверяется и зачем."""
    if not pg.is_configured():
        await query.edit_message_text(
            "🔍 <b>Сверка с Platega</b>\n\n"
            "⚠️ Platega не настроена — задай Merchant ID и API ключ "
            "(💰 Финансы → 💳 Платёжная система), потом возвращайся.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(_back_rows()),
        )
        return
    await query.edit_message_text(
        "🔍 <b>Сверка с Platega</b>\n\n"
        "Сверяет каждый счёт из базы с платёжной системой живыми "
        f"запросами (последние {DAYS} дней, до {LIMIT} счетов) и находит:\n"
        "• полный возврат, который не попал в базу\n"
        "• частичный возврат с неверной суммой\n"
        "• оплату, которая прошла, но не засчитана\n"
        "• суммы, которые не сходятся\n\n"
        "Исправление правит только денежные записи. Сроки подписок "
        "не отзываются — их решаешь сам через карточку платежа.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Проверить",
                                  callback_data="reconcile_run")],
            *_back_rows(),
        ]),
    )


async def run_reconciliation() -> dict:
    """Живая сверка счетов с Platega (без экрана).

    Возвращает {checked, issues: [(row, issue)], impact, fixable}.
    Исправления НЕ применяет — их делает handle_reconcile_fix.
    Переиспользуется утренней синхронизацией.
    """
    rows = await list_reconcile_payments(DAYS, LIMIT)
    if not rows:
        return {"checked": 0, "issues": [], "impact": 0, "fixable": []}
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _one(row):
        async with sem:
            return await pg.get_status(row[2])

    results = await asyncio.gather(
        *[_one(r) for r in rows], return_exceptions=True)
    issues: list[tuple[tuple, dict]] = []
    for row, res in zip(rows, results):
        if isinstance(res, Exception):
            issues.append((row, {"kind": "unchecked",
                                 "text": f"не проверено: {res}",
                                 "fix": None, "impact": 0}))
            continue
        found = compare_payment(row, res)
        if found:
            issues.append((row, found))
    fixable = [(row, iss) for row, iss in issues if iss.get("fix")]
    impact = sum(max(0, iss.get("impact") or 0) for _, iss in issues)
    return {"checked": len(rows), "issues": issues,
            "impact": impact, "fixable": fixable}


async def handle_reconcile_run(query, context: ContextTypes.DEFAULT_TYPE):
    """Живая проверка счетов + список расхождений."""
    await query.edit_message_text("🔍 Проверяю счета в Platega…")
    if not pg.is_configured():
        await query.edit_message_text(
            "🔍 <b>Сверка с Platega</b>\n\n⚠️ Platega не настроена.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(_back_rows()),
        )
        return
    res = await run_reconciliation()
    checked = res["checked"]
    issues = res["issues"]
    fixable = res["fixable"]
    impact = res["impact"]
    if checked == 0:
        await query.edit_message_text(
            "🔍 <b>Сверка с Platega</b>\n\n"
            "Счетов Platega за последние "
            f"{DAYS} дней нет — сверять нечего.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(_back_rows()),
        )
        return
    context.user_data["reconcile_fix"] = [
        {"payment_id": row[0], **iss["fix"]} for row, iss in fixable
    ]
    lines = ["🔍 <b>Сверка с Platega</b>",
             f"<i>Проверено счетов: {checked} · за {DAYS} дней</i>", "",
             f"✅ Совпало: <b>{checked - len(issues)}</b>",
             f"⚠️ Расхождений: <b>{len(issues)}</b>"]
    if impact > 0:
        lines.append(f"💸 Прибыль завышена на: <b>{impact} ₽</b>")
    if issues:
        lines.append("")
        lines.append("<b>Расхождения:</b>")
        for row, iss in issues[:10]:
            lines.append(f"• #{row[0]} · {row[3]} ₽ · {iss['text']}")
        if len(issues) > 10:
            lines.append(f"• …и ещё {len(issues) - 10}")
    else:
        lines.append("")
        lines.append("Всё сходится — база и Platega совпадают.")
    rows_kb: list = []
    if fixable:
        rows_kb.append([InlineKeyboardButton(
            f"✅ Исправить расхождения ({len(fixable)})",
            callback_data="reconcile_fix")])
    rows_kb.append([InlineKeyboardButton("🔄 Проверить снова",
                                         callback_data="reconcile_run")])
    rows_kb += _back_rows()
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows_kb),
        disable_web_page_preview=True,
    )


async def handle_reconcile_fix(query, context: ContextTypes.DEFAULT_TYPE):
    """Применяет исправления из сверки к денежным записям."""
    fixes = context.user_data.pop("reconcile_fix", None) or []
    if not fixes:
        await query.edit_message_text(
            "✅ Исправлять нечего — запусти проверку заново.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Проверить снова",
                                      callback_data="reconcile_run")],
                *_back_rows(),
            ]),
        )
        return
    done: list[str] = []
    total = 0
    for fix in fixes:
        pid = fix["payment_id"]
        if fix["kind"] == "full":
            if await claim_refund(pid):
                done.append(f"• #{pid} → полный возврат учтён")
                total += 1
        elif fix["kind"] == "partial":
            await set_partial_refunded(pid, int(fix["amount"]))
            done.append(f"• #{pid} → частичный возврат {fix['amount']} ₽")
            total += 1
    lines = ["✅ <b>Сверка: исправлено</b>", ""] + done
    lines.append("")
    lines.append("Доходы теперь считаются нетто — прибыль уменьшена "
                 "на сумму возвратов.")
    lines.append("Сроки подписок не отзывались: если нужно, отзови срок "
                 "через карточку платежа.")
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Проверить снова",
                                  callback_data="reconcile_run")],
            *_back_rows(),
        ]),
    )
