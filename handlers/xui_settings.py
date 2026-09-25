from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import load_config, save_config
from keyboards import back_admin, xui_settings_keyboard
from states import (
    AWAITING_XUI_URL, AWAITING_XUI_TOKEN, AWAITING_XUI_SUB_PORT, AWAITING_XUI_SUB_PATH,
    AWAITING_NODE_HOST,
)


def _back_xui() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К серверам", callback_data="xui_settings")]])


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

    from html import escape
    lines = [
        "🖧 <b>Узлы</b>", "",
        "<i>Инбаунды одного сервера названы с общим префиксом. Укажи адрес "
        "сервера для префикса — и бот будет проверять его порты там, "
        "а не на панели.</i>", "",
    ]
    if panel_host:
        lines.append(f"🏠 Адрес панели: <code>{escape(panel_host)}</code> — "
                     "<i>по нему проверяются префиксы без адреса</i>")

    kb = []
    node_lines = []
    for p in sorted(prefixes):
        host = nodes.get(p)
        mark = "✅" if host else "🏠"
        shown = host or "по адресу панели"
        node_lines.append(f"{mark} <b>{escape(p)}</b> — {escape(shown)} · инбаундов: {len(prefixes[p])}")
        kb.append([InlineKeyboardButton(
            f"{mark} {p} — {shown}", callback_data=f"node_set:{p}"
        )])
    if node_lines:
        lines += ["", "<blockquote>" + "\n".join(node_lines) + "</blockquote>"]

    if not prefixes:
        lines += ["", "<blockquote>⚠️ Не удалось получить инбаунды из панели.</blockquote>"]

    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="xui_settings")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )


async def handle_node_set(query, context, prefix: str):
    context.user_data["state"] = AWAITING_NODE_HOST
    context.user_data["node_prefix"] = prefix
    cfg = load_config()
    cur = (cfg.get("node_hosts") or {}).get(prefix)
    cur_line = f"<blockquote>Сейчас: <code>{cur}</code></blockquote>\n\n" if cur else ""
    await query.edit_message_text(
        f"🖧 <b>Адрес узла «{prefix}»</b>\n\n{cur_line}"
        "Пришли IP или домен сервера, на котором работают инбаунды "
        f"с префиксом <b>{prefix}</b>.\n\n"
        "<i>Например <code>203.0.113.10</code> или <code>n3.example.com</code>. "
        "<code>-</code> — убрать привязку.</i>",
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
        await message.reply_text("😕 <b>Узел потерялся</b>\n\n<i>Начни заново.</i>",
                                 parse_mode="HTML", reply_markup=back_admin())
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
            f"✅ <b>Привязка для {prefix} убрана</b>\n\n<i>Проверка пойдёт по адресу панели.</i>",
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
            "❌ <b>Нужен IP или домен</b>\n\n"
            "<i>Например <code>203.0.113.10</code> или <code>n3.example.com</code></i>",
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
            from html import escape
            checked.append(f"{icon} {escape(str(tag))} — {escape(str(detail))}")

    body = f"✅ <b>Узел {prefix}</b>: <code>{value}</code>"
    if checked:
        body += "\n\n📡 <b>Проверка портов</b>\n<blockquote>" + "\n".join(checked) + "</blockquote>"
    await message.reply_text(body, parse_mode="HTML", reply_markup=kb)


async def handle_xui_settings(query):
    cfg = load_config()
    from html import escape
    url = cfg.get("xui_url") or "не задан"
    token_set = "✅ задан" if cfg.get("xui_token") else "❌ не задан"
    sub_port = cfg.get("xui_sub_port") or "не задан"
    sub_path = cfg.get("xui_sub_path") or "/sub/"

    from panel import on_remnawave
    # Подписки могут уже жить в Remnawave — тогда здесь просто старая панель,
    # и менять её параметры смысла нет: важно, чтобы это было видно сразу.
    note = ("⚠️ <i>Подписки обслуживает Remnawave — эти параметры ни на что "
            "не влияют. Панель оставлена на случай возврата.</i>"
            if on_remnawave() else
            "<i>ID инбаунда определяется сам (первый VLESS). "
            "Токен: 3x-UI → Settings → API → Token.</i>")

    await query.edit_message_text(
        "🖥 <b>Серверы и 3x-UI</b>\n\n"
        f"<blockquote>🌐 Панель: <code>{escape(str(url))}</code>\n"
        f"🔑 API-токен: {token_set}\n"
        f"🔌 Порт подписки: <code>{escape(str(sub_port))}</code>\n"
        f"📂 Путь подписки: <code>{escape(str(sub_path))}</code></blockquote>\n\n"
        + note,
        parse_mode="HTML",
        reply_markup=xui_settings_keyboard(),
    )


async def handle_test_xui(query):
    await query.edit_message_text("📡 Проверяю соединение…")
    from xui_api import test_connection
    result = await test_connection()
    if result["success"]:
        count = result.get("inbounds", "?")
        await query.edit_message_text(
            "✅ <b>Панель на связи</b>\n\n"
            f"<blockquote>📡 Инбаундов найдено: <b>{count}</b></blockquote>",
            parse_mode="HTML",
            reply_markup=_back_xui(),
        )
    else:
        # панель в ошибке может вернуть HTML-страницу — без экранирования
        # сообщение не отправится вовсе, и админ не увидит причину
        from html import escape
        await query.edit_message_text(
            "❌ <b>Панель не отвечает</b>\n\n"
            f"<blockquote>🌐 <code>{escape(str(result.get('url', 'не задан')))}</code>\n"
            f"<code>{escape(str(result['error']))}</code></blockquote>\n\n"
            "<i>Проверь адрес панели и токен.</i>",
            parse_mode="HTML",
            reply_markup=_back_xui(),
        )


async def handle_set_xui_url(query, context):
    context.user_data["state"] = AWAITING_XUI_URL
    await query.edit_message_text(
        "🌐 <b>Адрес панели</b>\n\n"
        "Пришли полный адрес вместе с секретным путём:\n"
        "<code>https://example.com:14127/secretpath</code>",
        parse_mode="HTML",
        reply_markup=_back_xui(),
    )


async def handle_set_xui_token(query, context):
    context.user_data["state"] = AWAITING_XUI_TOKEN
    await query.edit_message_text(
        "🔑 <b>API-токен</b>\n\n"
        "<blockquote>В 3x-UI: <b>Settings → Security → Secret Token</b></blockquote>\n\n"
        "<i>Пришли токен одним сообщением.</i>",
        parse_mode="HTML",
        reply_markup=_back_xui(),
    )


async def handle_set_xui_sub_port(query, context):
    context.user_data["state"] = AWAITING_XUI_SUB_PORT
    await query.edit_message_text(
        "🔌 <b>Порт подписки</b>\n\n<i>Пришли порт для ссылок подписки, например <code>2096</code>.</i>",
        parse_mode="HTML",
        reply_markup=_back_xui(),
    )


async def handle_set_xui_sub_path(query, context):
    context.user_data["state"] = AWAITING_XUI_SUB_PATH
    await query.edit_message_text(
        "📂 <b>Путь подписки</b>\n\n<i>Пришли путь. По умолчанию <code>/sub/</code>.</i>",
        parse_mode="HTML",
        reply_markup=_back_xui(),
    )
