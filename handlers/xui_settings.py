from config import load_config
from keyboards import back_admin, xui_settings_keyboard
from states import AWAITING_XUI_URL, AWAITING_XUI_TOKEN, AWAITING_XUI_SUB_PORT, AWAITING_XUI_SUB_PATH


async def handle_xui_settings(query):
    cfg = load_config()
    url = cfg.get("xui_url") or "не задан"
    token_set = "✅ задан" if cfg.get("xui_token") else "❌ не задан"
    sub_port = cfg.get("xui_sub_port") or "не задан"
    sub_path = cfg.get("xui_sub_path") or "/sub/"

    await query.edit_message_text(
        "<b>⚙️ Параметры 3x-UI</b>\n\n"
        f"🌐 URL панели: <code>{url}</code>\n"
        f"🔑 API Токен: {token_set}\n"
        f"🔌 Порт подписки: <code>{sub_port}</code>\n"
        f"📂 Путь подписки: <code>{sub_path}</code>\n\n"
        "ℹ️ ID инбаунда определяется автоматически (первый VLESS).\n\n"
        "Токен: 3x-UI → Settings → API → Token",
        parse_mode="HTML",
        reply_markup=xui_settings_keyboard(),
    )


async def handle_test_xui(query):
    await query.edit_message_text("⏳ Проверяю соединение...")
    from xui_api import test_connection
    result = await test_connection()
    if result["success"]:
        count = result.get("inbounds", "?")
        await query.edit_message_text(
            f"✅ <b>Соединение с панелью успешно!</b>\n\nИнбаундов найдено: <b>{count}</b>",
            parse_mode="HTML",
            reply_markup=back_admin(),
        )
    else:
        await query.edit_message_text(
            f"❌ <b>Ошибка соединения</b>\n\n"
            f"URL: <code>{result.get('url', 'не задан')}</code>\n\n"
            f"Детали:\n<code>{result['error']}</code>",
            parse_mode="HTML",
            reply_markup=back_admin(),
        )


async def handle_set_xui_url(query, context):
    context.user_data["state"] = AWAITING_XUI_URL
    await query.edit_message_text(
        "🌐 <b>URL панели</b>\n\nВведи полный URL вместе с секретным путём:\n"
        "<code>https://example.com:14127/secretpath</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_set_xui_token(query, context):
    context.user_data["state"] = AWAITING_XUI_TOKEN
    await query.edit_message_text(
        "🔑 <b>API Токен</b>\n\n"
        "Найди токен в 3x-UI:\n"
        "<b>Settings → Security → Secret Token</b>\n\n"
        "Введи токен:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_set_xui_sub_port(query, context):
    context.user_data["state"] = AWAITING_XUI_SUB_PORT
    await query.edit_message_text(
        "🔌 <b>Порт подписки</b>\n\nВведи порт для ссылок подписки (например: <code>2096</code>):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_set_xui_sub_path(query, context):
    context.user_data["state"] = AWAITING_XUI_SUB_PATH
    await query.edit_message_text(
        "📂 <b>Путь подписки</b>\n\nВведи путь (по умолчанию <code>/sub/</code>):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )
