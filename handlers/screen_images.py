"""Админка: картинки к экранам меню.

«🖼 Картинки меню» → список экранов (есть картинка или нет) →
экран → «Задать / заменить» → админ присылает картинку фото или
файлом. Картинка хранится у Telegram как file_id, в базе — только
ссылка на неё.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core.screen_images import SCREENS, get_image, show_screen
from core.states import AWAITING_SCREEN_IMAGE


async def _show_menu_text(query, text: str, reply_markup) -> None:
    """Текст меню: если текущее сообщение — фото (деталь с превью),
    редактирование поменяло бы только подпись, поэтому удаляем его
    и шлём текст заново. На текстовом — просто редактируем."""
    msg = query.message
    if getattr(msg, "photo", None):
        try:
            await msg.delete()
        except Exception:
            pass
        await msg.chat.send_message(text, parse_mode="HTML",
                                    reply_markup=reply_markup)
        return
    await query.edit_message_text(text, parse_mode="HTML",
                                  reply_markup=reply_markup)


async def handle_screen_images_menu(query, context):
    """Список экранов с отметкой, где картинка уже есть."""
    from core.database import list_screen_images
    context.user_data.pop("state", None)
    context.user_data.pop("screen_image_key", None)
    have = await list_screen_images()
    rows = [
        [InlineKeyboardButton(
            f"{'🖼' if key in have else '➖'} {label}",
            callback_data=f"screen_img:{key}")]
        for key, label in SCREENS.items()
    ]
    rows.append([InlineKeyboardButton("◀️ Назад в админку",
                                      callback_data="admin_panel")])
    await _show_menu_text(
        query,
        "🖼 <b>Картинки меню</b>\n\n"
        "Выберите экран и пришлите картинку — фото или файлом.\n"
        "Экран будет показываться картинкой с текстом в одном сообщении.\n"
        "Где картинки нет — экран как раньше, просто текст.\n\n"
        "Если текст экрана длиннее 1024 символов, картинка не покажется —\n"
        "у фото подпись короче, чем текст сообщения.",
        InlineKeyboardMarkup(rows),
    )


async def handle_screen_image_detail(query, key: str):
    """Экран: есть ли картинка, задать/заменить, убрать."""
    label = SCREENS.get(key)
    if not label:
        await query.answer("Нет такого экрана", show_alert=True)
        return
    img = await get_image(key)
    text = (f"🖼 <b>{label}</b>\n\n"
            + ("✅ Картинка задана — экран показывается с ней."
               if img else "➖ Картинки нет — экран показывается просто текстом."))
    rows = [[InlineKeyboardButton("📷 Задать / заменить",
                                  callback_data=f"screen_img_set:{key}")]]
    if img:
        rows.append([InlineKeyboardButton("🗑 Убрать картинку",
                                          callback_data=f"screen_img_del:{key}")])
    rows.append([InlineKeyboardButton("◀️ К списку",
                                      callback_data="screen_images_menu")])
    # Сам экран-картинка — превью: деталь показываем через show_screen,
    # чтобы админ сразу видел, как экран выглядит с картинкой
    await show_screen(query, key, text, InlineKeyboardMarkup(rows))


async def handle_screen_image_ask(query, context, key: str):
    """Просим прислать картинку для экрана."""
    label = SCREENS.get(key)
    if not label:
        await query.answer("Нет такого экрана", show_alert=True)
        return
    context.user_data["state"] = AWAITING_SCREEN_IMAGE
    context.user_data["screen_image_key"] = key
    await _show_menu_text(
        query,
        f"📷 <b>{label}</b>\n\n"
        "Пришлите картинку — фото или файлом (jpg, png…).\n"
        "Она будет показываться на этом экране вместе с текстом.",
        InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="screen_images_menu"),
        ]]),
    )


async def handle_screen_image_delete(query, key: str):
    """Убрать картинку с экрана."""
    label = SCREENS.get(key)
    if not label:
        await query.answer("Нет такого экрана", show_alert=True)
        return
    from core.database import delete_screen_image
    await delete_screen_image(key)
    await query.answer("Картинка убрана")
    await handle_screen_image_detail(query, key)


async def accept_screen_image(msg, context):
    """Админ прислал фото или файл-картинку в состоянии ожидания."""
    key = context.user_data.get("screen_image_key")
    label = SCREENS.get(key) if key else None
    if not label:
        context.user_data.pop("state", None)
        context.user_data.pop("screen_image_key", None)
        await msg.reply_text("⚠️ Экран не выбран — откройте «🖼 Картинки меню» заново.")
        return
    if msg.photo:
        file_id, kind = msg.photo[-1].file_id, "photo"
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file_id, kind = msg.document.file_id, "document"
    else:
        await msg.reply_text(
            "⚠️ Это не картинка. Пришлите фото или файл-картинку (jpg, png…).")
        return
    from core.database import set_screen_image
    await set_screen_image(key, file_id, kind)
    context.user_data.pop("state", None)
    context.user_data.pop("screen_image_key", None)
    await msg.reply_text(
        f"✅ Картинка сохранена для экрана «{label}».\n"
        "Откройте этот экран в боте — он покажется с картинкой.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🖼 Картинки меню",
                                 callback_data="screen_images_menu"),
        ]]),
    )
