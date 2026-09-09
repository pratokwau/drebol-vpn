from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import load_config, save_config
from keyboards import back_admin, xui_settings_keyboard
from states import (
    AWAITING_XUI_URL, AWAITING_XUI_TOKEN, AWAITING_XUI_SUB_PORT, AWAITING_XUI_SUB_PATH,
    AWAITING_NODE_HOST,
)


# ── Узлы: адреса серверов, на которых живут инбаунды ─────────────────────────

async def handle_nodes_menu(query, context=None):
    """Список префиксов инбаундов и привязанные к ним адреса."""
    if context:
        context.user_data.pop("state", None)
    from xui_api import get_inbounds, node_prefix

    cfg = load_config()
    nodes = cfg.get("node_hosts") or {}
    panel_host = (cfg.get("xui_url") or "").split("//")[-1].split("/")[0].split(":")[0]

    result = await get_inbounds()
    prefixes = {}
    if result.get("success"):
        for inb in result["inbounds"]:
            tag = inb.get("tag") or inb.get("remark") or ""
            p = node_prefix(tag)
            if p:
                prefixes.setdefault(p, []).append(tag)

    lines = [
        "🖧 <b>Узлы</b>\n",
        "Инбаунды одного сервера названы с общим префиксом. Укажи адрес "
        "сервера для префикса — и бот будет проверять его порты там, "
        "а не на панели.\n",
    ]
    if panel_host:
        lines.append(f"🏠 Адрес панели: <code>{panel_host}</code>")
        lines.append("<i>Префиксы без адреса проверяются по нему.</i>\n")

    kb = []
    for p in sorted(prefixes):
        host = nodes.get(p)
        mark = "✅" if host else "🏠"
        shown = host or "по адресу панели"
        lines.append(f"{mark} <b>{p}</b> — {shown} · инбаундов: {len(prefixes[p])}")
        kb.append([InlineKeyboardButton(
            f"{mark} {p} — {shown}", callback_data=f"node_set:{p}"
        )])

    if not prefixes:
        lines.append("⚠️ Не удалось получить инбаунды из панели.")

    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="xui_settings")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )


async def handle_node_set(query, context, prefix: str):
    context.user_data["state"] = AWAITING_NODE_HOST
    context.user_data["node_prefix"] = prefix
    cfg = load_config()
    cur = (cfg.get("node_hosts") or {}).get(prefix)
    cur_line = f"Сейчас: <code>{cur}</code>\n\n" if cur else ""
    await query.edit_message_text(
        f"🖧 <b>Адрес узла «{prefix}»</b>\n\n{cur_line}"
        "Пришли IP или домен сервера, на котором работают инбаунды "
        f"с префиксом <b>{prefix}</b>.\n\n"
        "Например: <code>203.0.113.10</code> или <code>n3.example.com</code>\n\n"
        "Отправь <code>-</code>, чтобы убрать привязку.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К узлам", callback_data="nodes_menu")],
        ]),
    )


async def apply_node_host(message, context, raw: str):
    """Сохраняет адрес узла и сразу проверяет его доступность."""
    import re
    from xui_api import check_tcp, get_inbounds, node_prefix

    prefix = context.user_data.pop("node_prefix", None)
    context.user_data.pop("state", None)
    if not prefix:
        await message.reply_text("❌ Узел потерян, начни заново.", reply_markup=back_admin())
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ К узлам", callback_data="nodes_menu")],
    ])
    cfg = load_config()
    nodes = dict(cfg.get("node_hosts") or {})
    value = (raw or "").strip().lower()

    if value == "-":
        nodes.pop(prefix, None)
        cfg["node_hosts"] = nodes
        save_config(cfg)
        await message.reply_text(
            f"✅ Привязка для <b>{prefix}</b> убрана — проверка пойдёт по адресу панели.",
            parse_mode="HTML", reply_markup=kb,
        )
        return

    # адрес уходит в сетевые вызовы, поэтому принимаем только IP или домен
    value = re.sub(r"^https?://", "", value).split("/")[0].split(":")[0]
    ok_ip = re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", value) and all(
        0 <= int(o) <= 255 for o in value.split(".")
    )
    ok_domain = re.fullmatch(
        r"(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", value
    )
    if not (ok_ip or ok_domain):
        await message.reply_text(
            "❌ Нужен IP или домен: <code>203.0.113.10</code> или <code>n3.example.com</code>",
            parse_mode="HTML", reply_markup=kb,
        )
        return

    nodes[prefix] = value
    cfg["node_hosts"] = nodes
    save_config(cfg)

    # сразу показываем, ожил ли узел
    result = await get_inbounds()
    checked = []
    if result.get("success"):
        for inb in result["inbounds"]:
            tag = inb.get("tag") or inb.get("remark") or ""
            if node_prefix(tag) != prefix or not inb.get("enable", True):
                continue
            chk = await check_tcp(value, inb.get("port"))
            icon = "🟢" if chk["ok"] else "🔴"
            detail = f"{chk['ms']} мс" if chk["ok"] else chk["error"]
            checked.append(f"{icon} {tag} — {detail}")

    body = f"✅ Узел <b>{prefix}</b>: <code>{value}</code>"
    if checked:
        body += "\n\n<b>Проверка портов:</b>\n" + "\n".join(checked)
    await message.reply_text(body, parse_mode="HTML", reply_markup=kb)


async def handle_xui_settings(query):
    cfg = load_config()
    url = cfg.get("xui_url") or "не задан"
    token_set = "✅ задан" if cfg.get("xui_token") else "❌ не задан"
    sub_port = cfg.get("xui_sub_port") or "не задан"
    sub_path = cfg.get("xui_sub_path") or "/sub/"

    await query.edit_message_text(
        "<b>🖥 Серверы и 3x-UI</b>\n\n"
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
