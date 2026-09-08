"""Раздел «Сайт» в админке: домен, активация, включение/выключение."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config
from keyboards import back_admin
from states import AWAITING_SITE_DOMAIN

try:
    import site_manager as sm
except ImportError:
    # При частичном обновлении файла может не быть. Раздел сайта тогда
    # недоступен, но бот должен запускаться — иначе падает всё остальное.
    sm = None


_NO_MODULE_TEXT = (
    "❌ <b>Модуль сайта не найден</b>\n\n"
    "На сервере отсутствует <code>site_manager.py</code> в корне проекта "
    "(<code>/root/drebol-vpn/</code>).\n\n"
    "Обнови код полностью — файл лежит рядом с <code>bot.py</code>, "
    "а не в папке <code>handlers/</code>."
)


def _back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ])


async def _no_module(query) -> bool:
    """True — модуль недоступен, обработчику дальше делать нечего."""
    if sm is not None:
        return False
    await query.edit_message_text(
        _NO_MODULE_TEXT, parse_mode="HTML", reply_markup=_back_kb()
    )
    return True


def _menu_kb(st: dict) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🌍 Задать домен", callback_data="site_set_domain")]]

    if st["domain"]:
        if not st["activated"] or not st["conf_exists"]:
            rows.append([InlineKeyboardButton("🚀 Активировать сайт", callback_data="site_activate")])
        else:
            if st["served"]:
                rows.append([InlineKeyboardButton("⏸ Выключить сайт", callback_data="site_disable")])
            else:
                rows.append([InlineKeyboardButton("▶️ Включить сайт", callback_data="site_enable")])
            rows.append([
                InlineKeyboardButton("🔄 Обновить файлы", callback_data="site_sync"),
                InlineKeyboardButton("🔐 Сертификат", callback_data="site_cert"),
            ])
            rows.append([InlineKeyboardButton("♻️ Переактивировать", callback_data="site_activate")])

    rows.append([InlineKeyboardButton("🩺 Проверить сервер", callback_data="site_check")])
    rows.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def _status_text(st: dict) -> str:
    if not st["domain"]:
        state = "⚪️ домен не задан"
    elif not st["conf_exists"]:
        state = "🟡 домен задан, сайт не активирован"
    elif st["served"]:
        state = "🟢 работает"
    else:
        state = "⏸ выключен"

    lines = [
        "🌐 <b>Сайт-визитка</b>\n",
        f"📌 Статус: <b>{state}</b>",
    ]

    if st["domain"]:
        scheme = "https" if st["cert_until"] else "http"
        lines.append(f"🌍 Домен: <code>{st['domain']}</code>")
        lines.append(f"🔗 {scheme}://{st['domain']}")

    if st["cert_until"]:
        lines.append(f"🔐 Сертификат до: <b>{st['cert_until']}</b>")
    elif st["conf_exists"]:
        lines.append("🔓 Сертификат: <b>нет</b> — сайт по http")

    if st["activated_at"]:
        lines.append(f"🕐 Активирован: {st['activated_at']}")

    problems = []
    if not st["is_root"]:
        problems.append("бот запущен не от root — nginx и certbot будут недоступны")
    if not st["nginx"]:
        problems.append("nginx не установлен")
    if not st["certbot"]:
        problems.append("certbot не установлен — сертификат не выпустить")
    if not st["site_src"]:
        problems.append(f"нет каталога {sm.SITE_SRC}")
    if st["nginx"] and not st["nginx_running"]:
        problems.append("nginx установлен, но не запущен")

    if problems:
        lines.append("\n⚠️ <b>Требует внимания:</b>")
        lines += [f"• {p}" for p in problems]

    cfg = load_config()
    if not cfg.get("bot_username"):
        lines.append(
            "\n💡 Кнопка на сайте ведёт в бота по <code>bot_username</code>.\n"
            "Он подставится сам при активации."
        )

    return "\n".join(lines)


async def handle_site_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    if await _no_module(query):
        return
    if context:
        context.user_data.pop("state", None)
    st = await sm.status()
    await query.edit_message_text(
        _status_text(st), parse_mode="HTML",
        reply_markup=_menu_kb(st), disable_web_page_preview=True,
    )


async def handle_site_set_domain(query, context: ContextTypes.DEFAULT_TYPE):
    if await _no_module(query):
        return
    context.user_data["state"] = AWAITING_SITE_DOMAIN
    cfg = load_config()
    cur = cfg.get("site_domain")
    cur_line = f"Сейчас: <code>{cur}</code>\n\n" if cur else ""
    await query.edit_message_text(
        f"🌍 <b>Домен сайта</b>\n\n{cur_line}"
        "Пришли домен, например <code>drbl.tech</code> или <code>vpn.drbl.tech</code>.\n\n"
        "⚠️ A-запись домена должна уже указывать на IP этого сервера —\n"
        "иначе не получится выпустить сертификат.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
        ]),
    )


async def apply_domain(message, context: ContextTypes.DEFAULT_TYPE, raw: str):
    """Вызывается из обработчика текста."""
    if sm is None:
        await message.reply_text(_NO_MODULE_TEXT, parse_mode="HTML", reply_markup=_back_kb())
        return
    domain = sm.normalize_domain(raw)
    if not sm.valid_domain(domain):
        await message.reply_text(
            "❌ Не похоже на домен.\n\n"
            "Нужен вид <code>drbl.tech</code> или <code>vpn.drbl.tech</code> — "
            "без <code>http://</code>, путей и пробелов.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
            ]),
        )
        return

    cfg = load_config()
    prev = cfg.get("site_domain")
    cfg["site_domain"] = domain
    if prev and prev != domain:
        # другой домен — прежняя активация к нему не относится
        cfg["site_activated"] = False
    save_config(cfg)

    await message.reply_text(
        f"✅ Домен сохранён: <code>{domain}</code>\n\n"
        "Теперь нажми «🚀 Активировать сайт» — я разложу файлы,\n"
        "настрою nginx и выпущу сертификат.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Активировать сайт", callback_data="site_activate")],
            [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
        ]),
    )


async def handle_site_activate(query, context: ContextTypes.DEFAULT_TYPE):
    if await _no_module(query):
        return
    cfg = load_config()
    domain = cfg.get("site_domain")
    if not domain:
        await query.answer("Сначала задай домен", show_alert=True)
        return

    # имя бота нужно для кнопки на сайте — берём у самого бота
    if not cfg.get("bot_username"):
        try:
            me = await context.bot.get_me()
            cfg["bot_username"] = me.username or ""
            save_config(cfg)
        except Exception:
            pass

    await query.edit_message_text(
        f"🚀 <b>Активирую сайт</b>\n\n🌍 {domain}\n\n⏳ Начинаю...",
        parse_mode="HTML",
    )

    async def progress(text: str):
        try:
            await query.edit_message_text(
                f"🚀 <b>Активирую сайт</b>\n\n🌍 {domain}\n\n{text}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    result = await sm.activate(domain, progress=progress)

    if not result["ok"]:
        hint = f"\n\n💡 Попробуй: <code>{result['hint']}</code>" if result.get("hint") else ""
        await query.edit_message_text(
            f"❌ <b>Не удалось активировать</b>\n\n"
            f"<code>{result['error']}</code>{hint}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="site_activate")],
                [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
            ]),
        )
        return

    from log_channel import send_log
    await send_log(context.bot, f"🌐 Сайт активирован: {result['url']}")

    if result["https"]:
        cert_line = "🔐 Сертификат выпущен, работает https"
    else:
        cert_line = (
            f"🔓 Сертификат не выпущен: <code>{result['cert_msg']}</code>\n"
            f"Сайт пока отдаётся по http."
        )

    await query.edit_message_text(
        f"✅ <b>Сайт активирован</b>\n\n"
        f"🔗 {result['url']}\n"
        f"{cert_line}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть сайт", url=result["url"])],
            [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
        ]),
        disable_web_page_preview=True,
    )


async def handle_site_toggle(query, context: ContextTypes.DEFAULT_TYPE, enable: bool):
    if await _no_module(query):
        return
    await query.edit_message_text("⏳ Применяю...")
    res = await sm.set_enabled(enable)
    if not res["ok"]:
        await query.edit_message_text(
            f"❌ <code>{res['error']}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
            ]),
        )
        return
    from log_channel import send_log
    await send_log(context.bot, "🌐 Сайт включён" if enable else "🌐 Сайт выключен")
    await handle_site_menu(query, context)


async def handle_site_sync(query, context: ContextTypes.DEFAULT_TYPE):
    if await _no_module(query):
        return
    cfg = load_config()
    domain = cfg.get("site_domain")
    if not domain:
        await query.answer("Домен не задан", show_alert=True)
        return
    await query.edit_message_text("🔄 Обновляю файлы сайта...")
    ok, res = await sm.sync_files(domain)
    if not ok:
        await query.edit_message_text(
            f"❌ <code>{res}</code>", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
            ]),
        )
        return
    await query.answer("Файлы обновлены")
    await handle_site_menu(query, context)


async def handle_site_cert(query, context: ContextTypes.DEFAULT_TYPE):
    if await _no_module(query):
        return
    cfg = load_config()
    domain = cfg.get("site_domain")
    if not domain:
        await query.answer("Домен не задан", show_alert=True)
        return
    await query.edit_message_text(
        f"🔐 Выпускаю сертификат для <code>{domain}</code>...\n\nЭто может занять до минуты.",
        parse_mode="HTML",
    )
    ok, msg = await sm.issue_cert(domain)
    if ok:
        await sm.nginx_test_reload()
        text = f"✅ Сертификат выпущен.\n\n🔗 https://{domain}"
    else:
        text = (
            f"❌ Не удалось выпустить сертификат:\n\n<code>{msg}</code>\n\n"
            "Частые причины: A-запись домена не указывает на этот сервер, "
            "или порт 80 закрыт файрволом."
        )
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
        ]),
        disable_web_page_preview=True,
    )


async def handle_site_check(query, context: ContextTypes.DEFAULT_TYPE):
    if await _no_module(query):
        return
    await query.edit_message_text("🩺 Проверяю сервер...")
    env = await sm.check_env()

    def mark(v):
        return "✅" if v else "❌"

    lines = [
        "🩺 <b>Проверка сервера</b>\n",
        f"{mark(env['is_root'])} Права root",
        f"{mark(env['nginx'])} nginx установлен",
        f"{mark(env['nginx_running'])} nginx запущен",
        f"{mark(env['certbot'])} certbot установлен",
        f"{mark(env['site_src'])} Файлы сайта ({sm.SITE_SRC})",
    ]

    missing = []
    if not env["nginx"]:
        missing.append("apt install -y nginx")
    if not env["certbot"]:
        missing.append("apt install -y certbot python3-certbot-nginx")
    if missing:
        lines.append("\n💡 <b>Установить недостающее:</b>")
        lines.append("<code>" + " && ".join(missing) + "</code>")
    if not env["site_src"]:
        lines.append(
            f"\n⚠️ Каталога <code>{sm.SITE_SRC}</code> нет.\n"
            "Обнови код с GitHub — файлы сайта лежат в папке <code>site/</code>."
        )

    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Проверить снова", callback_data="site_check")],
            [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
        ]),
    )
