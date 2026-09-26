import re

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_users_by_segment
from keyboards import cancel_admin
from states import AWAITING_BROADCAST, AWAITING_BROADCAST_BUTTONS, AWAITING_BROADCAST_PHOTO

# В подпись к картинке Telegram пускает 1024 символа, в обычное сообщение — 4096
CAPTION_LIMIT = 1024


SEGMENTS = {
    "all": "🌍 Все пользователи",
    "active": "🟢 Активные подписки",
    "expired": "🔴 Истёкшие подписки",
    "trial": "🆓 Только триал",
    "paying": "⭐️ Платящие",
    "no_sub": "🚫 Без подписки",
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
    "💡 <b>Как оформить</b>\n"
    "<blockquote expandable>"
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
    "</blockquote>"
)

BUTTONS_HELP = (
    "<blockquote>"
    "Формат — по одной кнопке в строке:\n"
    "<code>Текст кнопки - https://example.com</code>\n\n"
    "Несколько кнопок в один ряд — через <code>|</code>:\n"
    "<code>Канал - https://t.me/x | Чат - https://t.me/y</code>\n\n"
    "Пример:\n"
    "<code>💳 Продлить - https://example.com/pay\n"
    "📰 Наш канал - https://t.me/channel</code>"
    "</blockquote>"
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
    for key in ("bcast_text", "bcast_buttons", "bcast_segment", "bcast_photo"):
        context.user_data.pop(key, None)
    context.user_data.pop("state", None)


# ── Шаг 1: выбор сегмента ────────────────────────────────────────────────────

async def handle_broadcast_start(query, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    # сегменты парами: «Все пользователи» первым и во всю ширину
    items = list(SEGMENTS.items())
    kb = [[InlineKeyboardButton(items[0][1], callback_data=f"bcast_seg:{items[0][0]}")]]
    for i in range(1, len(items), 2):
        kb.append([InlineKeyboardButton(label, callback_data=f"bcast_seg:{key}")
                   for key, label in items[i:i + 2]])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text(
        "📣 <b>Рассылка</b>  ·  <i>шаг 1 из 4</i>\n\n"
        "Кому отправить сообщение?",
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
        "📣 <b>Рассылка</b>  ·  <i>шаг 2 из 4</i>\n\n"
        f"<blockquote>🎯 {SEGMENTS[segment]}\n"
        f"👥 Получателей: <b>{count}</b></blockquote>\n\n"
        "✍️ <b>Пришлите текст сообщения</b>\n\n"
        f"{FORMAT_HELP}",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


# ── Шаг 3: картинка ──────────────────────────────────────────────────────────

async def ask_photo(message, context: ContextTypes.DEFAULT_TYPE):
    """Текст принят — предлагаем прикрепить картинку."""
    photo = context.user_data.get("bcast_photo")
    rows = [[InlineKeyboardButton("📷 Заменить картинку" if photo else "📷 Добавить картинку",
                                  callback_data="bcast_photo_add")]]
    if photo:
        rows.append([InlineKeyboardButton("🗑 Убрать картинку", callback_data="bcast_photo_del")])
    rows.append([InlineKeyboardButton("➡️ Дальше" if photo else "⏭ Без картинки",
                                      callback_data="bcast_photo_skip")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")])
    await message.reply_text(
        "📣 <b>Рассылка</b>  ·  <i>шаг 3 из 4</i>\n\n"
        "✅ Текст принят.\n\n"
        + ("🖼 Картинка прикреплена." if photo else "🖼 <b>Добавить картинку?</b>"),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_bcast_photo_add(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_BROADCAST_PHOTO
    await query.edit_message_text(
        "🖼 <b>Картинка для рассылки</b>\n\n"
        "<i>Пришлите фото одним сообщением. Подпись писать не нужно — "
        "текст рассылки уже принят.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ Без картинки", callback_data="bcast_photo_skip"),
             InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
        ]),
    )


async def handle_bcast_photo_skip(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("state", None)
    await ask_buttons(query.message, context)


async def handle_bcast_photo_del(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("bcast_photo", None)
    context.user_data.pop("state", None)
    await ask_photo(query.message, context)


async def accept_photo(message, context: ContextTypes.DEFAULT_TYPE):
    """Фото пришло на шаге картинки."""
    context.user_data["bcast_photo"] = message.photo[-1].file_id
    context.user_data.pop("state", None)
    await message.reply_text("🖼 <b>Картинка принята</b>", parse_mode="HTML")
    await ask_buttons(message, context)


async def accept_photo_with_text(message, context: ContextTypes.DEFAULT_TYPE):
    """Фото прислали вместо текста: подпись становится текстом рассылки."""
    context.user_data["bcast_photo"] = message.photo[-1].file_id
    caption = extract_html(message)
    if not caption.strip():
        await message.reply_text("🖼 <b>Картинка принята</b>\n\n"
                                 "<i>Теперь пришлите текст рассылки.</i>", parse_mode="HTML")
        return
    context.user_data["bcast_text"] = caption
    context.user_data.pop("state", None)
    await ask_buttons(message, context)


# ── Шаг 4: кнопки ────────────────────────────────────────────────────────────

async def ask_buttons(message, context: ContextTypes.DEFAULT_TYPE):
    """Текст принят — спрашиваем про инлайн-кнопки."""
    await message.reply_text(
        "📣 <b>Рассылка</b>  ·  <i>шаг 4 из 4</i>\n\n"
        "🔘 <b>Прикрепить кнопки-ссылки?</b>\n"
        "<i>Например, «Продлить» или «Наш канал».</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить кнопки", callback_data="bcast_buttons_add"),
             InlineKeyboardButton("⏭ Без кнопок", callback_data="bcast_buttons_skip")],
            [InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
        ]),
    )


async def handle_bcast_buttons_add(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_BROADCAST_BUTTONS
    await query.edit_message_text(
        f"🔘 <b>Кнопки для рассылки</b>\n\n{BUTTONS_HELP}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ Пропустить", callback_data="bcast_buttons_skip"),
             InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
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
    photo = context.user_data.get("bcast_photo")
    if not text:
        await message.reply_text("😕 <b>Текст рассылки потерялся</b>\n\n<i>Начните заново.</i>",
                                 parse_mode="HTML")
        return

    count = len(await get_users_by_segment(segment))

    await message.reply_text(
        "👀 <b>Так увидят получатели</b> 👇",
        parse_mode="HTML",
    )
    try:
        if photo and len(text) <= CAPTION_LIMIT:
            await message.reply_photo(photo, caption=text, parse_mode="HTML",
                                      reply_markup=build_markup(spec))
        else:
            if photo:
                await message.reply_photo(photo)
            await message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=build_markup(spec),
                disable_web_page_preview=False,
            )
    except Exception as e:
        await message.reply_text(
            f"❌ <b>Ошибка разметки</b>\n\n<blockquote><code>{e}</code></blockquote>\n\n"
            "<i>Исправьте текст и отправьте заново.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Изменить текст", callback_data="bcast_edit_text"),
                 InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
            ]),
        )
        return

    btn_line = f"\n🔘 Кнопок: <b>{sum(len(r) for r in spec)}</b>" if spec else ""
    photo_line = "\n🖼 Картинка: <b>есть</b>" if photo else ""
    photo_note = ("\n\n<i>Текст длиннее 1024 символов — картинка уйдёт "
                  "отдельным сообщением перед текстом.</i>"
                  if photo and len(text) > CAPTION_LIMIT else "")
    await message.reply_text(
        "📣 <b>Проверьте рассылку</b>\n\n"
        f"<blockquote>🎯 {SEGMENTS.get(segment, 'Все')}\n"
        f"👥 Получателей: <b>{count}</b>"
        f"{photo_line}{btn_line}</blockquote>"
        f"{photo_note}\n\n"
        "<b>Отправляем?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🚀 Отправить · {count}", callback_data="bcast_send")],
            [
                InlineKeyboardButton("✏️ Текст", callback_data="bcast_edit_text"),
                InlineKeyboardButton("🖼 Картинка", callback_data="bcast_photo_add"),
                InlineKeyboardButton("🔘 Кнопки", callback_data="bcast_buttons_add"),
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")],
        ]),
    )


async def handle_bcast_edit_text(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_BROADCAST
    await query.edit_message_text(
        f"✍️ <b>Пришлите новый текст рассылки</b>\n\n{FORMAT_HELP}",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


async def handle_bcast_cancel(query, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    from keyboards import back_admin
    await query.edit_message_text(
        "❌ <b>Рассылка отменена</b>", parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Шаг 5: отправка ──────────────────────────────────────────────────────────

async def handle_bcast_send(query, context: ContextTypes.DEFAULT_TYPE):
    text = context.user_data.get("bcast_text")
    segment = context.user_data.get("bcast_segment", "all")
    spec = context.user_data.get("bcast_buttons")
    photo = context.user_data.get("bcast_photo")
    if not text:
        await query.edit_message_text("😕 <b>Текст рассылки потерялся</b>\n\n<i>Начните заново.</i>",
                                      parse_mode="HTML")
        return

    user_ids = await get_users_by_segment(segment)
    await query.edit_message_text(
        f"⏳ <b>Отправляю рассылку…</b>\n\n<i>Получателей: {len(user_ids)}. "
        "Не закрывайте — это займёт немного времени.</i>", parse_mode="HTML",
    )
    ok, fail = await do_broadcast(context.bot, text, segment, build_markup(spec), photo)

    from keyboards import back_admin
    from log_channel import send_log
    await send_log(context.bot,
        f"📣 Рассылка ({SEGMENTS.get(segment, segment)}): "
        f"доставлено {ok}, ошибок {fail}"
    )
    _reset(context)
    await query.edit_message_text(
        "✅ <b>Рассылка завершена</b>\n\n"
        f"<blockquote>🎯 {SEGMENTS.get(segment, 'Все')}\n"
        f"👥 Получателей: <b>{len(user_ids)}</b>\n"
        f"📨 Доставлено: <b>{ok}</b>\n"
        f"❌ Не дошло: <b>{fail}</b></blockquote>"
        + ("\n\n<i>Не дошло обычно тем, кто заблокировал бота.</i>" if fail else ""),
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def do_broadcast(bot: Bot, text: str, segment: str = "all",
                       reply_markup: InlineKeyboardMarkup | None = None,
                       photo: str | None = None) -> tuple[int, int]:
    user_ids = await get_users_by_segment(segment)
    ok = 0
    fail = 0
    # длинный текст в подпись не влезет — тогда картинка идёт отдельным сообщением
    split = bool(photo) and len(text) > CAPTION_LIMIT
    for uid in user_ids:
        try:
            if photo and not split:
                await bot.send_photo(
                    chat_id=uid, photo=photo, caption=text, parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            else:
                if photo:
                    await bot.send_photo(chat_id=uid, photo=photo)
                await bot.send_message(
                    chat_id=uid, text=text, parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            ok += 1
        except Exception:
            fail += 1
    return ok, fail
