"""Посты в Telegram-канал из админки бота («📣 Пост в ТГК»).

Отличие от «Рассылки»: рассылка уходит личным сообщением пользователям,
а это — публикация в канал (канал задан в «📢 Канал», channel_url).
Бот должен быть администратором канала, иначе Telegram не даст постить.

Состав поста:
- текст с форматированием (сущности Telegram или HTML-теги — как в рассылке);
- постоянная подпись из config (channel_signature) — дописывается в конец
  каждого поста, на предпросмотре её можно выключить для одного поста;
- картинки: одна — подписью к фото, несколько — альбомом (у альбома
  Telegram не разрешает инлайн-кнопки, об этом честно предупреждаем);
- инлайн-кнопки выбираются из кнопок главного меню /start: в посте они
  становятся ссылками — URL-кнопки как есть, остальные ведут в бота
  диплинком /start ch_<key>, а start.py открывает нужный экран.
"""

from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
)
from telegram.ext import ContextTypes

from config import atomic_update, load_config
from core.keyboards import back_admin, cancel_admin
from core.states import (
    AWAITING_CHPOST_PHOTO, AWAITING_CHPOST_SIGN, AWAITING_CHPOST_TEXT,
)
from handlers.broadcast import CAPTION_LIMIT, FORMAT_HELP, extract_html

# Кнопки главного меню пользователя: (ключ, подпись).
# Раскладка повторяет main_keyboard: подписка — во всю ширину, дальше парами.
MENU_BUTTONS = {
    "mysub": "🔐 Моя подписка",
    "renew": "💳 Продлить",
    "referral": "🎁 Пригласить друга",
    "support": "🛟 Поддержка",
    "info": "ℹ️ Инфо",
    "news": "📣 Новости",
}
MENU_LAYOUT = [["mysub"], ["renew", "referral"], ["support", "info"], ["news"]]

_DRAFT_KEYS = ("chpost_text", "chpost_photos", "chpost_sel", "chpost_use_sign")


# ── Настройки канала ─────────────────────────────────────────────────────────

def channel_target(cfg: dict | None = None):
    """Куда постить: числовой id из config (channel_id), иначе @username
    из channel_url. None — канал не настроен."""
    cfg = cfg if cfg is not None else load_config()
    cid = cfg.get("channel_id")
    if cid:
        try:
            return int(cid)
        except (TypeError, ValueError):
            pass
    from core.subscription import extract_channel_username
    username = extract_channel_username(cfg.get("channel_url") or "")
    return f"@{username}" if username else None


def get_signature() -> str:
    return str(load_config().get("channel_signature") or "")


def _plain(html_text: str) -> str:
    """Грубый текст без тегов — для короткого превью подписи в меню."""
    import re
    return re.sub(r"<[^>]+>", "", html_text or "").strip()


# ── Черновик поста ───────────────────────────────────────────────────────────

def _reset(context):
    for key in _DRAFT_KEYS:
        context.user_data.pop(key, None)
    context.user_data.pop("state", None)


def _final_text(context) -> str:
    text = context.user_data.get("chpost_text") or ""
    sign = get_signature()
    if sign and context.user_data.get("chpost_use_sign", True):
        text = f"{text}\n\n{sign}" if text else sign
    return text


def _button_url(key: str, bot_username: str, cfg: dict) -> str:
    if key == "news":
        return cfg.get("channel_url") or f"https://t.me/{bot_username}"
    if key == "support":
        from handlers.support import support_bot_url
        return support_bot_url() or f"https://t.me/{bot_username}?start=ch_support"
    return f"https://t.me/{bot_username}?start=ch_{key}"


def build_post_markup(context, bot_username: str) -> InlineKeyboardMarkup | None:
    sel = set(context.user_data.get("chpost_sel") or [])
    if not sel:
        return None
    cfg = load_config()
    rows = []
    for layout_row in MENU_LAYOUT:
        row = [InlineKeyboardButton(MENU_BUTTONS[k], url=_button_url(k, bot_username, cfg))
               for k in layout_row if k in sel]
        if row:
            rows.append(row)
    return InlineKeyboardMarkup(rows) if rows else None


async def _deliver(bot: Bot, chat_id, context, *, with_markup: bool = True):
    """Отправляет пост ровно в том виде, в каком он уйдёт в канал.
    Используется и для предпросмотра админу, и для публикации."""
    text = _final_text(context)
    photos = context.user_data.get("chpost_photos") or []
    markup = build_post_markup(context, bot.username) if with_markup else None
    if len(photos) > 1:
        # Альбом: кнопки Telegram не разрешает, подпись — только к первому фото
        media = []
        for i, fid in enumerate(photos):
            caption = text if i == 0 and len(text) <= CAPTION_LIMIT else None
            media.append(InputMediaPhoto(
                media=fid, caption=caption,
                parse_mode="HTML" if caption else None))
        await bot.send_media_group(chat_id=chat_id, media=media)
        if len(text) > CAPTION_LIMIT:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        return
    if photos:
        if len(text) <= CAPTION_LIMIT:
            await bot.send_photo(chat_id=chat_id, photo=photos[0], caption=text,
                                 parse_mode="HTML", reply_markup=markup)
        else:
            await bot.send_photo(chat_id=chat_id, photo=photos[0])
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML",
                                   reply_markup=markup)
        return
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML",
                           reply_markup=markup,
                           disable_web_page_preview=False)


# ── Меню раздела ─────────────────────────────────────────────────────────────

def _menu_text() -> str:
    cfg = load_config()
    target = channel_target(cfg)
    sign = get_signature()
    if target:
        head = f"<blockquote>📢 Канал: <b>{target}</b></blockquote>"
    else:
        head = ("<blockquote>⚠️ Канал не настроен. Сначала задайте его "
                "в разделе «📢 Канал» админки.</blockquote>")
    sign_line = (f"✒️ Подпись: <i>{_plain(sign)[:80]}</i>" if sign
                 else "✒️ Подпись: <i>не задана</i>")
    return (f"📣 <b>Пост в ТГК</b>\n\n{head}\n\n{sign_line}\n\n"
            "<i>Подпись автоматически дописывается в конец каждого поста. "
            "Бот должен быть администратором канала.</i>")


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Новый пост", callback_data="chpost_new")],
        [InlineKeyboardButton("✒️ Подпись", callback_data="chpost_sign_view")],
        [InlineKeyboardButton("◀️ Канал", callback_data="channel_menu")],
    ])


async def handle_chpost_menu(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("state", None)
    await query.edit_message_text(_menu_text(), parse_mode="HTML",
                                  reply_markup=_menu_kb())


# ── Подпись ──────────────────────────────────────────────────────────────────

async def handle_chpost_sign_view(query, context: ContextTypes.DEFAULT_TYPE):
    sign = get_signature()
    rows = [[InlineKeyboardButton("✏️ Задать подпись" if not sign else "✏️ Изменить подпись",
                                  callback_data="chpost_sign_edit")]]
    if sign:
        rows.append([InlineKeyboardButton("🗑 Убрать подпись",
                                          callback_data="chpost_sign_del")])
    rows.append([InlineKeyboardButton("◀️ Посты в ТГК", callback_data="chpost_menu")])
    await query.edit_message_text(
        "✒️ <b>Подпись к постам</b>\n\n"
        + (f"<blockquote>{sign}</blockquote>" if sign
           else "<i>Подпись пока не задана.</i>")
        + "\n\n<i>Она добавляется в самый конец каждого поста в канал. "
          "Форматирование поддерживается — как в тексте поста.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_chpost_sign_edit(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_CHPOST_SIGN
    await query.edit_message_text(
        f"✒️ <b>Пришлите текст подписи</b>\n\n{FORMAT_HELP}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Подпись", callback_data="chpost_sign_view")],
        ]),
    )


async def handle_chpost_sign_del(query, context: ContextTypes.DEFAULT_TYPE):
    def _drop(cfg):
        cfg.pop("channel_signature", None)
    atomic_update(_drop)
    await handle_chpost_sign_view(query, context)


async def accept_signature(message, context: ContextTypes.DEFAULT_TYPE):
    """Текст подписи пришёл сообщением (состояние AWAITING_CHPOST_SIGN)."""
    html = extract_html(message)
    if not html.strip():
        await message.reply_text("❌ Подпись пустая — пришлите текст.")
        return
    atomic_update(lambda cfg: cfg.__setitem__("channel_signature", html))
    context.user_data.pop("state", None)
    await message.reply_text(
        "✅ <b>Подпись сохранена</b>\n\n"
        "<i>Теперь она будет дописываться в конец каждого поста.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📣 Посты в ТГК", callback_data="chpost_menu")],
            [InlineKeyboardButton("◀️ В админку", callback_data="admin_panel")],
        ]),
    )


# ── Шаг 1: текст поста ───────────────────────────────────────────────────────

async def handle_chpost_new(query, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    if not channel_target():
        await query.edit_message_text(
            "⚠️ <b>Канал не настроен</b>\n\n"
            "<i>Задайте канал в разделе «📢 Канал» — оттуда берётся адрес "
            "для постов.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Канал", callback_data="channel_menu")],
                [InlineKeyboardButton("◀️ Посты в ТГК", callback_data="chpost_menu")],
            ]),
        )
        return
    context.user_data["state"] = AWAITING_CHPOST_TEXT
    await query.edit_message_text(
        "📣 <b>Пост в ТГК</b>  ·  <i>шаг 1 из 3</i>\n\n"
        "✍️ <b>Пришлите текст поста</b>\n"
        "<i>Можно сразу с картинкой — её подпись станет текстом.</i>\n\n"
        f"{FORMAT_HELP}",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


async def accept_text(message, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["chpost_text"] = extract_html(message)
    context.user_data.pop("state", None)
    if context.user_data.get("chpost_photos"):
        await ask_buttons(message, context)
    else:
        await ask_photo(message, context)


async def accept_photo_with_text(message, context: ContextTypes.DEFAULT_TYPE):
    """Фото прислали вместо текста: подпись становится текстом поста."""
    photos = context.user_data.setdefault("chpost_photos", [])
    photos.append(message.photo[-1].file_id)
    caption = extract_html(message)
    if not caption.strip():
        await message.reply_text(
            "🖼 <b>Картинка принята</b>\n\n<i>Теперь пришлите текст поста.</i>",
            parse_mode="HTML")
        return
    context.user_data["chpost_text"] = caption
    context.user_data.pop("state", None)
    await ask_buttons(message, context)


# ── Шаг 2: картинки ──────────────────────────────────────────────────────────

async def ask_photo(message, context: ContextTypes.DEFAULT_TYPE):
    photos = context.user_data.get("chpost_photos") or []
    rows = [[InlineKeyboardButton("📷 Добавить ещё" if photos else "📷 Добавить картинку",
                                  callback_data="chpost_photo_add")]]
    if photos:
        rows.append([InlineKeyboardButton("🗑 Убрать картинки",
                                          callback_data="chpost_photo_del")])
    rows.append([InlineKeyboardButton("➡️ Дальше", callback_data="chpost_photo_next")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="chpost_cancel")])
    note = ""
    if len(photos) > 1:
        note = ("\n\n<i>Несколько картинок уйдут альбомом — к альбому "
                "Telegram не прикрепляет инлайн-кнопки.</i>")
    await message.reply_text(
        "📣 <b>Пост в ТГК</b>  ·  <i>шаг 2 из 3</i>\n\n"
        "✅ Текст принят.\n\n"
        + (f"🖼 Картинок: <b>{len(photos)}</b>" if photos
           else "🖼 <b>Добавить картинку?</b>")
        + note,
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_chpost_photo_add(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_CHPOST_PHOTO
    await query.edit_message_text(
        "🖼 <b>Картинка для поста</b>\n\n"
        "<i>Пришлите фото одним сообщением. Можно несколько по очереди.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ Дальше", callback_data="chpost_photo_next"),
             InlineKeyboardButton("❌ Отмена", callback_data="chpost_cancel")],
        ]),
    )


async def accept_photo(message, context: ContextTypes.DEFAULT_TYPE):
    """Фото пришло на шаге картинок — добавляем к посту."""
    photos = context.user_data.setdefault("chpost_photos", [])
    photos.append(message.photo[-1].file_id)
    context.user_data.pop("state", None)
    await message.reply_text(f"🖼 <b>Картинка принята</b> · всего: {len(photos)}",
                             parse_mode="HTML")
    await ask_photo(message, context)


async def handle_chpost_photo_del(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["chpost_photos"] = []
    context.user_data.pop("state", None)
    await ask_photo(query.message, context)


async def handle_chpost_photo_next(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("state", None)
    await ask_buttons(query.message, context)


# ── Шаг 3: выбор инлайн-кнопок из меню /start ────────────────────────────────

async def ask_buttons(message, context: ContextTypes.DEFAULT_TYPE):
    photos = context.user_data.get("chpost_photos") or []
    album_note = ("\n\n<i>⚠️ Картинок несколько — пост уйдёт альбомом, "
                  "а к альбому кнопки не прикрепляются.</i>"
                  if len(photos) > 1 else "")
    await message.reply_text(
        "📣 <b>Пост в ТГК</b>  ·  <i>шаг 3 из 3</i>\n\n"
        "🔘 <b>Добавить инлайн-кнопки к посту?</b>\n"
        "<i>Кнопки — как в главном меню бота: подписка, продлить, "
        "пригласить друга и другие.</i>"
        f"{album_note}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Выбрать кнопки", callback_data="chpost_pick"),
             InlineKeyboardButton("⏭ Без кнопок", callback_data="chpost_buttons_skip")],
            [InlineKeyboardButton("❌ Отмена", callback_data="chpost_cancel")],
        ]),
    )


def _picker_kb(context) -> InlineKeyboardMarkup:
    sel = set(context.user_data.get("chpost_sel") or [])
    rows = []
    for layout_row in MENU_LAYOUT:
        rows.append([
            InlineKeyboardButton(
                f"{'✅' if k in sel else '❌'} {MENU_BUTTONS[k]}",
                callback_data=f"chpost_tgl:{k}")
            for k in layout_row
        ])
    rows.append([InlineKeyboardButton("➡️ Далее", callback_data="chpost_pick_done")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="chpost_cancel")])
    return InlineKeyboardMarkup(rows)


_PICKER_TEXT = (
    "🔘 <b>Кнопки поста</b>\n\n"
    "<i>Это меню /start обычного пользователя. Отметьте галочкой ✅ кнопки, "
    "которые попадут в пост, крестик ❌ — кнопка не нужна. "
    "В канале кнопки станут ссылками в бота на нужный экран.</i>"
)


async def handle_chpost_pick(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault("chpost_sel", [])
    await query.edit_message_text(_PICKER_TEXT, parse_mode="HTML",
                                  reply_markup=_picker_kb(context))


async def handle_chpost_toggle(query, context: ContextTypes.DEFAULT_TYPE, key: str):
    if key not in MENU_BUTTONS:
        return
    sel = list(context.user_data.get("chpost_sel") or [])
    if key in sel:
        sel.remove(key)
    else:
        sel.append(key)
    context.user_data["chpost_sel"] = sel
    try:
        await query.edit_message_reply_markup(reply_markup=_picker_kb(context))
    except Exception:
        pass


async def handle_chpost_pick_done(query, context: ContextTypes.DEFAULT_TYPE):
    await show_preview(query.message, context)


async def handle_chpost_buttons_skip(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["chpost_sel"] = []
    await show_preview(query.message, context)


# ── Предпросмотр ─────────────────────────────────────────────────────────────

async def show_preview(message, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("chpost_text"):
        await message.reply_text(
            "😕 <b>Текст поста потерялся</b>\n\n<i>Начните заново.</i>",
            parse_mode="HTML")
        return
    photos = context.user_data.get("chpost_photos") or []
    sel = context.user_data.get("chpost_sel") or []
    sign_on = bool(get_signature()) and context.user_data.get("chpost_use_sign", True)

    await message.reply_text("👀 <b>Так пост будет выглядеть в канале</b> 👇",
                             parse_mode="HTML")
    try:
        await _deliver(context.bot, message.chat_id, context)
    except Exception as e:
        await message.reply_text(
            f"❌ <b>Ошибка разметки</b>\n\n<blockquote><code>{e}</code></blockquote>\n\n"
            "<i>Исправьте текст и отправьте заново.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Изменить текст", callback_data="chpost_edit_text"),
                 InlineKeyboardButton("❌ Отмена", callback_data="chpost_cancel")],
            ]),
        )
        return

    warn = ""
    if len(photos) > 1 and sel:
        warn = ("\n\n<i>⚠️ Альбом из нескольких картинок публикуется без "
                "кнопок — Telegram так не умеет. Кнопки ниже не попадут "
                "в канал.</i>")
    sign_btn = ("✒️ Подпись: вкл" if sign_on else "✒️ Подпись: выкл") \
        if get_signature() else "✒️ Подпись не задана"
    rows = [[InlineKeyboardButton("🚀 Отправить в канал", callback_data="chpost_send")],
            [InlineKeyboardButton("✏️ Текст", callback_data="chpost_edit_text"),
             InlineKeyboardButton("🖼 Картинки", callback_data="chpost_photo_add"),
             InlineKeyboardButton("🔘 Кнопки", callback_data="chpost_pick")]]
    if get_signature():
        rows.append([InlineKeyboardButton(sign_btn, callback_data="chpost_toggle_sign")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="chpost_cancel")])
    await message.reply_text(
        "📣 <b>Проверьте пост</b>\n\n"
        f"<blockquote>📢 Канал: <b>{channel_target()}</b>\n"
        f"🖼 Картинок: <b>{len(photos)}</b>\n"
        f"🔘 Кнопок: <b>{len(sel)}</b>\n"
        f"✒️ Подпись: <b>{'да' if sign_on else 'нет'}</b></blockquote>"
        f"{warn}\n\n<b>Публикуем?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_chpost_edit_text(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_CHPOST_TEXT
    await query.edit_message_text(
        f"✍️ <b>Пришлите новый текст поста</b>\n\n{FORMAT_HELP}",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


async def handle_chpost_toggle_sign(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["chpost_use_sign"] = \
        not context.user_data.get("chpost_use_sign", True)
    await show_preview(query.message, context)


async def handle_chpost_cancel(query, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    await query.edit_message_text(
        "❌ <b>Пост отменён</b>", parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Публикация ───────────────────────────────────────────────────────────────

async def handle_chpost_send(query, context: ContextTypes.DEFAULT_TYPE):
    target = channel_target()
    if not target:
        await query.edit_message_text(
            "⚠️ <b>Канал не настроен</b>\n\n<i>Задайте его в «📢 Канал».</i>",
            parse_mode="HTML", reply_markup=back_admin())
        return
    if not context.user_data.get("chpost_text"):
        await query.edit_message_text(
            "😕 <b>Текст поста потерялся</b>\n\n<i>Начните заново.</i>",
            parse_mode="HTML", reply_markup=back_admin())
        return
    try:
        await _deliver(context.bot, target, context)
    except Exception as e:
        await query.edit_message_text(
            "❌ <b>Не удалось опубликовать</b>\n\n"
            f"<blockquote><code>{e}</code></blockquote>\n\n"
            "<i>Чаще всего бот не администратор канала. Добавьте бота "
            "в админы канала с правом публикации и попробуйте снова — "
            "черновик не потерян.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Попробовать снова", callback_data="chpost_send")],
                [InlineKeyboardButton("❌ Отмена", callback_data="chpost_cancel")],
            ]),
        )
        return

    from core.log_channel import send_log
    await send_log(context.bot, f"📣 Опубликован пост в канал {target}")
    _reset(context)
    await query.edit_message_text(
        "✅ <b>Пост опубликован в канале</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Ещё пост", callback_data="chpost_new")],
            [InlineKeyboardButton("◀️ В админку", callback_data="admin_panel")],
        ]),
    )


# ── Диплинки из постов: /start ch_<key> ─────────────────────────────────────

class _DeepLinkQuery:
    """Обёртка над сообщением /start под интерфейс query у экранов
    пользователя: экраны зовут edit_message_text — отвечаем новым
    сообщением в личку."""

    def __init__(self, message, user):
        self.message = message
        self.from_user = user

    async def edit_message_text(self, text, **kwargs):
        kwargs.pop("chat_id", None)
        kwargs.pop("message_id", None)
        return await self.message.reply_text(text, **kwargs)


async def open_deep_link(update, context: ContextTypes.DEFAULT_TYPE, key: str) -> bool:
    """Открывает экран, на который ведёт кнопка поста канала.
    True — экран показан; False — ключ неизвестен, обычный /start."""
    query = _DeepLinkQuery(update.message, update.effective_user)
    try:
        if key == "mysub":
            from handlers.user import handle_my_paid_sub
            await handle_my_paid_sub(query)
        elif key == "renew":
            from handlers.user import handle_renew_sub
            await handle_renew_sub(query)
        elif key == "referral":
            from handlers.user import handle_referral
            await handle_referral(query, context)
        elif key == "info":
            from handlers.user import handle_info
            await handle_info(query)
        elif key == "support":
            from handlers.support import open_support
            await open_support(query)
        else:
            return False
    except Exception:
        return False
    return True
