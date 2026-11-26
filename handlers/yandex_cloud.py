"""Раздел «☁️ Yandex Cloud»: как устроена CDN-часть сервиса.

Только справка, ничего не меняется и не нажимается: ресурсы Yandex CDN,
их связь с панелью Remnawave и нодами, DNS зоны drbl.tech, биллинг
и типовые поломки CDN-линейки с рецептами ремонта (по итогам разбора
и починки 2026-11-22). Здесь же — настройка зеркала страницы подписки
и белые списки (экраны rw_yandex_sub / rw_yandex_whitelist из
services/remnawave.py, кнопки ведут сюда же).
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

GSLB = "bc6681bc57f8bf03.topology.gslb.yccdn.ru"


def _kb(rows):
    return InlineKeyboardMarkup(rows)


def _back_to_menu():
    return _kb([[InlineKeyboardButton("◀️ К Yandex Cloud", callback_data="yc_menu")]])


async def _show(query, context, lines, kb):
    if context:
        context.user_data.pop("state", None)
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=kb, disable_web_page_preview=True)


async def handle_yc_menu(query, context=None):
    """Обзор: роль Yandex CDN и оглавление раздела."""
    lines = [
        "☁️ <b>Yandex Cloud</b>",
        "",
        "<i>Как устроена CDN-часть сервиса. Только справка —",
        "здесь ничего не меняется и не нажимается.</i>",
        "",
        "<b>Роль</b>",
        "Yandex CDN — край для CDN-вариантов стран (хосты «- 2»)",
        "и страницы подписки.",
        "Схема: пользователь → Yandex CDN → основная нода страны.",
        "Кеширование на всех ресурсах <b>ВЫКЛЮЧЕНО</b> — CDN только",
        "проксирует трафик к нодам.",
        "",
        "<b>Что внутри</b>",
        "• «Ресурсы и ноды» — ресурсы CDN, origins, цепочка на ноде;",
        "• «DNS и ремонт» — записи зоны и типовые поломки;",
        "• «Биллинг» — пакеты, грант и связь с лимитами LTE в боте.",
        "• «Страница подписки» и «Белые списки» — настройка зеркала",
        "  sub.drbl.tech и списки IP Яндекса для файрвола нод.",
    ]
    kb = _kb([
        [InlineKeyboardButton("📦 Ресурсы и ноды", callback_data="yc_resources")],
        [InlineKeyboardButton("🌐 DNS и ремонт", callback_data="yc_dns")],
        [InlineKeyboardButton("💰 Биллинг", callback_data="yc_billing")],
        [InlineKeyboardButton("📄 Страница подписки", callback_data="rw_yandex_sub")],
        [InlineKeyboardButton("📋 Белые списки", callback_data="rw_yandex_whitelist")],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ])
    await _show(query, context, lines, kb)


async def handle_yc_resources(query, context=None):
    """Ресурсы CDN, их origins и цепочка «CDN → nginx → VXC» на ноде."""
    lines = [
        "📦 <b>Ресурсы и ноды</b>",
        "",
        "Папка в Yandex Cloud: <b>cloud-frost-287</b> (новый аккаунт,",
        "миграция 2026-11-26). Все ресурсы Active,",
        "сертификаты выпущены. Общий CNAME для всех ресурсов:",
        f"<code>{GSLB}</code>",
        "",
        "<b>Ресурсы и их origins</b>",
        "• <b>static</b> (<code>bc8rhsx4snr37xstoxao</code>) → 144.31.223.252",
        "  по HTTP, Host static.drbl.tech (Германия, хост «- 2»);",
        "• <b>assets</b> (<code>bc8rjuvq5ztilk7zwrp2</code>) → 81.90.21.84",
        "  по HTTP, Host — как у клиента (Швеция, хост «- 2»);",
        "• <b>sub</b> → key.drbl.tech по HTTPS",
        "  (страница подписки, перенос на новый аккаунт);",
        "• <b>media</b> → 109.248.161.146 по HTTP (Латвия, хост «- 2»,",
        "  строится).",
        "",
        "<b>Цепочка на ноде</b>",
        "CDN приходит на nginx ноды: порт 80, server_name —",
        "домен ресурса страны (<code>static</code>/<code>assets</code>/<code>media</code>). Дальше <code>location /drbl7f3a</code>",
        "→ <code>proxy_pass 127.0.0.1:8880</code> — это XHTTP-инбаунд",
        "VXC-&lt;Country&gt;-1 в панели Remnawave (packet-up, GET-uplink).",
        "",
        "«Welcome to nginx» на голом *cdn-домене — <b>НОРМА</b>: рабочий",
        "путь — секретный /drbl7f3a, корень домена — заглушка.",
        "",
        "В панели VXC-инбаунд должен быть <b>выбран на CDN-ноде страны</b>",
        "(1 из 5 инбаундов) — иначе цепочка мертва при живом CDN.",
    ]
    await _show(query, context, lines, _back_to_menu())


async def handle_yc_dns(query, context=None):
    """DNS зоны drbl.tech и типовые поломки LTE-линейки."""
    lines = [
        "🌐 <b>DNS и ремонт</b>",
        "",
        "Зона <b>drbl.tech</b> ведётся в SpaceWeb. Записи CDN-части:",
        "• static, assets, sub — CNAME на",
        f"  <code>{GSLB}</code>;",
        "• denode1 — A 144.31.223.252;",
        "• senode1 — A 81.90.21.84;",
        "• key — A 144.31.223.252.",
        "<b>key.drbl.tech — origin подписки, НЕ трогать.</b>",
        "",
        "<b>Типовые поломки</b> (реальный ремонт 2026-11-22)",
        "",
        "<b>1. Нет CNAME у *cdn-домена</b> — страна умирает на резолве,",
        "в приложении n/a. Так было с de1cdn: записи просто не",
        "существовало. Лечение: добавить CNAME на gslb (выше)",
        "и подождать распространения DNS.",
        "",
        "<b>2. На ноде нет nginx-location /drbl7f3a</b> — CDN отвечает",
        "(«Welcome to nginx»), но трафик не идёт. Так было с FI и SE.",
        "Конфиг — как на немецкой ноде: listen 80, server_name —",
        "cdn-домен страны, location /drbl7f3a → proxy_pass",
        "127.0.0.1:8880, proxy_http_version 1.1, таймауты 86400s,",
        "proxy_buffering off, location / → 404. После правки:",
        "<code>nginx -t &amp;&amp; systemctl reload nginx</code>.",
        "",
        "<b>3. VXC не выбран на CDN-ноде</b> — в карточке CDN-ноды страны",
        "в панели должен быть отмечен инбаунд VXC-&lt;Country&gt;-1 (1/5).",
    ]
    await _show(query, context, lines, _back_to_menu())


async def handle_yc_billing(query, context=None):
    """Биллинг Yandex CDN и связь с LTE-лимитами подписок в боте."""
    lines = [
        "💰 <b>Биллинг Yandex CDN</b>",
        "",
        "<b>Пакеты</b>",
        "150 ₽/мес за ресурс. Сейчас в новом аккаунте 2 ресурса",
        "(static, assets) = <b>300 ₽/мес</b>; с sub и media будет",
        "4 ресурса = <b>600 ₽/мес</b>.",
        "В пакет каждого ресурса включено: 150 ГБ исходящего",
        "трафика + 100 млн запросов. Пакеты между ресурсами",
        "<b>НЕ переносятся</b> — неиспользованное сгорает.",
        "",
        "Сверх пакета — оплата за ГБ, но ставка в консоли",
        "не отображается: смотреть детализацию биллинга.",
        "",
        "<b>Сейчас</b>",
        "Новый аккаунт (cloud-frost-287): стартовый грант",
        "<b>4 000 ₽ до 25.01.2027</b> покрывает пакеты и трафик.",
        "Старый аккаунт после переноса sub выводится из работы.",
        "",
        "<b>Связь с ботом</b>",
        "У подписок есть месячный LTE-лимит: пресеты paid_preset_lte",
        "и preset_lte (настройки подписок), изначально — 30 ГБ/мес.",
        "При превышении лимита бот перекидывает подписку",
        "в fallback-сквад. Лимит можно полностью <b>отключить</b>",
        "тумблером «Лимит LTE» (Платные подписки → «Сквад после",
        "конца LTE») — тогда CDN-варианты доступны всем без учёта.",
    ]
    await _show(query, context, lines, _back_to_menu())
