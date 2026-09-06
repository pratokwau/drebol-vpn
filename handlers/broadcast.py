import re

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_users_by_segment
from keyboards import cancel_admin
from states import AWAITING_BROADCAST, AWAITING_BROADCAST_BUTTONS


SEGMENTS = {
    "all": "🌍 Все пользователи",
    "active": "🟢 Активные подписки",
    "expired": "🔴 Истёкшие подписки",
    "trial": "🆓 Только триал",
    "paying": "⭐️ Платящие",
    "no_sub": "🚫 Без подписки",
    "pending_pay": "⏳ Ожидают оплаты",
}

# Сущности, которые Telegram проставляет при форматировании в самом клиенте
_FMT_ENTITIES = {
    "bold", "italic", "underline", "strikethrough", "spoiler",
    "code", "pre", "text_link", "blockquote", "expandable_blockquote",
    "custom_emoji",
}

_HTML_TAG_RE = re.compile(
    r"</?(b|strong|i|em|u|ins|s|strike|del|a|code|pre|tg-spoiler|span|blockquote)\b",
    re.IGNORECASE,
)

# «Текст - https://...» / «Текст — tg://...»
_BUTTON_RE = re.compile(r"^(.*?)\s*[-–—]\s*((?:https?://|tg://)\S+)$")

FORMAT_HELP = (
    "Форматировать можно двумя способами:\n\n"
    "1️⃣ <b>Прямо в Telegram</b> — выделите текст и примените жирный, курсив, "
    "ссылку, моноширинный, зачёркнутый, скрытый. Всё сохранится.\n\n"
    "2️⃣ <b>HTML-тегами</b>:\n"
    "<code>&lt;b&gt;жирный&lt;/b&gt;</code>\n"
    "<code>&lt;i&gt;курсив&lt;/i&gt;</code>\n"
    "<code>&lt;u&gt;подчёркнутый&lt;/u&gt;</code>\n"
    "<code>&lt;s&gt;зачёркнутый&lt;/s&gt;</code>\n"
    "<code>&lt;code&gt;моноширинный&lt;/code&gt;</code>\n"
    "<code>&lt;tg-spoiler&gt;скрытый&lt;/tg-spoiler&gt;</code>\n"
    "<code>&lt;a href=\"https://...\"&gt;ссылка&lt;/a&gt;</code>\n"
    "<code>&lt;blockquote&gt;цитата&lt;/blockquote&gt;</code>"
)

BUTTONS_HELP = (
    "Формат — по одной кнопке в строке:\n"
    "<code>Текст кнопки - https://example.com</code>\n\n"
    "Несколько кнопок в один ряд — через <code>|</code>:\n"
    "<code>Канал - https://t.me/x | Чат - https://t.me/y</code>\n\n"
    "Пример:\n"
    "<code>💳 Продлить - https://example.com/pay\n"
    "📰 Наш канал - https://t.me/channel</code>"
)


def extract_html(message) -> str:
    """Текст сообщения с сохранением форматирования.

    Если админ форматировал средствами Telegram — переводим сущности в HTML.
    Если написал теги руками — оставляем строку как есть.
    Иначе экранируем, чтобы «<» в тексте не ломал разметку.
    """
    raw = message.text or message.caption or ""
    entities = list(message.entities or []) + list(message.caption_entities or [])
    if any(getattr(e, "type", None) in _FMT_ENTITIES for e in entities):
        return message.text_html if message.text else (message.caption_html or "")
    if _HTML_TAG_RE.search(raw):
        return raw
    return message.text_html if message.text else (message.caption_html or "")


def parse_buttons(text: str):
    """Разбирает кнопки. Строка = ряд, «|» делит ряд на колонки.

    Возвращает (spec, error): spec — список рядов из пар (label, url).
    """
    rows = []
    for i, line in enumerate(text.strip().split("\n"), 1):
        line = line.strip()
        if not line:
            continue
        row = []
        for part in line.split("|"):
            part = part.strip()
            if not part:
                continue
            m = _BUTTON_RE.match(part)
            if not m:
                return None, (
                    f"Строка {i}: не разобрал «{part}».\n"
                    "Нужен формат <code>Текст - https://ссылка</code>"
                )
            label, url = m.group(1).strip(), m.group(2).strip()
            if not label:
                return None, f"Строка {i}: пустой текст кнопки"
            if len(label) > 64:
                return None, f"Строка {i}: текст кнопки длиннее 64 символов"
            row.append((label, url))
        if row:
            if len(row) > 3:
                return None, f"Строка {i}: максимум 3 кнопки в один ряд"
            rows.append(row)
    if not rows:
        return None, "Не нашёл ни одной кнопки"
    if len(rows) > 10:
        return None, "Максимум 10 рядов кнопок"
    return rows, None


def build_markup(spec) -> InlineKeyboardMarkup | None:
    if not spec:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, url=url) for label, url in row]
        for row in spec
    ])


def _reset(context):
    for key in ("bcast_text", "bcast_buttons", "bcast_segment"):
        context.user_data.pop(key, None)
    context.user_data.pop("state", None)


# ── Шаг 1: выбор сегмента ────────────────────────────────────────────────────

async def handle_broadcast_start(query, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    kb = [[InlineKeyboardButton(label, callback_data=f"bcast_seg:{key}")]
          for key, label in SEGMENTS.items()]
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text(
        "📣 <b>Рассылка</b>\n\nВыберите, кому отправить сообщение:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


# ── Шаг 2: текст ─────────────────────────────────────────────────────────────

async def handle_broadcast_segment(query, context: ContextTypes.DEFAULT_TYPE, segment: str):
    if segment not in SEGMENTS:
        segment = "all"
    context.user_data["state"] = AWAITING_BROADCAST
    context.user_data["bcast_segment"] = segment
    count = len(await get_users_by_segment(segment))
    await query.edit_message_text(
        f"📣 <b>Рассылка · {SEGMENTS[segment]}</b>\n\n"
        f"👥 Получателей: <b>{count}</b>\n\n"
        f"✍️ Отправьте текст сообщения.\n\n{FORMAT_HELP}",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


# ── Шаг 3: кнопки ────────────────────────────────────────────────────────────

async def ask_buttons(message, context: ContextTypes.DEFAULT_TYPE):
    """Текст принят — спрашиваем про инлайн-кнопки."""
    await message.reply_text(
        "✅ Текст принят.\n\n"
        "🔘 Прикрепить к рассылке инлайн-кнопки?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить кнопки", callback_data="bcast_buttons_add")],
            [InlineKeyboardButton("⏭ Без кнопок", callback_data="bcast_buttons_skip")],
            [InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
        ]),
    )


async def handle_bcast_buttons_add(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_BROADCAST_BUTTONS
    await query.edit_message_text(
        f"🔘 <b>Кнопки для рассылки</b>\n\n{BUTTONS_HELP}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ Пропустить", callback_data="bcast_buttons_skip")],
            [InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
        ]),
    )


async def handle_bcast_buttons_skip(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("state", None)
    context.user_data["bcast_buttons"] = None
    await show_preview(query.message, context)


# ── Шаг 4: предпросмотр ──────────────────────────────────────────────────────

async def show_preview(message, context: ContextTypes.DEFAULT_TYPE):
    text = context.user_data.get("bcast_text")
    segment = context.user_data.get("bcast_segment", "all")
    spec = context.user_data.get("bcast_buttons")
    if not text:
        await message.reply_text("❌ Текст рассылки потерян, начните заново.")
        return

    count = len(await get_users_by_segment(segment))

    await message.reply_text(
        "👀 <b>Так увидят получатели:</b>",
        parse_mode="HTML",
    )
    try:
        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=build_markup(spec),
            disable_web_page_preview=False,
        )
    except Exception as e:
        await message.reply_text(
            f"❌ <b>Ошибка разметки</b>\n\n<code>{e}</code>\n\n"
            "Исправьте текст и отправьте заново.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Изменить текст", callback_data="bcast_edit_text")],
                [InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
            ]),
        )
        return

    btn_line = f"🔘 Кнопок: <b>{sum(len(r) for r in spec)}</b>\n" if spec else ""
    await message.reply_text(
        f"📣 <b>Проверьте рассылку</b>\n\n"
        f"🎯 Сегмент: <b>{SEGMENTS.get(segment, 'Все')}</b>\n"
        f"👥 Получателей: <b>{count}</b>\n"
        f"{btn_line}\n"
        "Отправляем?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Отправить", callback_data="bcast_send")],
            [
                InlineKeyboardButton("✏️ Текст", callback_data="bcast_edit_text"),
                InlineKeyboardButton("🔘 Кнопки", callback_data="bcast_buttons_add"),
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
        ]),
    )


async def handle_bcast_edit_text(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_BROADCAST
    await query.edit_message_text(
        f"✍️ Отправьте новый текст рассылки.\n\n{FORMAT_HELP}",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


async def handle_bcast_cancel(query, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    from keyboards import back_admin
    await query.edit_message_text(
        "❌ Рассылка отменена.",
        reply_markup=back_admin(),
    )


# ── Шаг 5: отправка ──────────────────────────────────────────────────────────

async def handle_bcast_send(query, context: ContextTypes.DEFAULT_TYPE):
    text = context.user_data.get("bcast_text")
    segment = context.user_data.get("bcast_segment", "all")
    spec = context.user_data.get("bcast_buttons")
    if not text:
        await query.edit_message_text("❌ Текст рассылки потерян, начните заново.")
        return

    user_ids = await get_users_by_segment(segment)
    await query.edit_message_text(
        f"⏳ Отправляю рассылку — {len(user_ids)} получателям...",
    )
    ok, fail = await do_broadcast(context.bot, text, segment, build_markup(spec))

    from keyboards import back_admin
    from log_channel import send_log
    await send_log(context.bot,
        f"📣 Рассылка ({SEGMENTS.get(segment, segment)}): "
        f"доставлено {ok}, ошибок {fail}"
    )
    _reset(context)
    await query.edit_message_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"🎯 Сегмент: {SEGMENTS.get(segment, 'Все')}\n"
        f"👥 Получателей: {len(user_ids)}\n"
        f"📨 Доставлено: <b>{ok}</b>\n"
        f"❌ Ошибок: <b>{fail}</b>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def do_broadcast(bot: Bot, text: str, segment: str = "all",
                       reply_markup: InlineKeyboardMarkup | None = None) -> tuple[int, int]:
    user_ids = await get_users_by_segment(segment)
    ok = 0
    fail = 0
    for uid in user_ids:
        try:
            await bot.send_message(
                chat_id=uid, text=text, parse_mode="HTML",
                reply_markup=reply_markup,
            )
            ok += 1
        except Exception:
            fail += 1
    return ok, fail
