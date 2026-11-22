"""Раздел «☁️ Yandex Cloud»: как устроена CDN-часть сервиса.

Только справка, ничего не меняется и не нажимается: ресурсы Yandex CDN,
их связь с панелью Remnawave и нодами, DNS зоны drbl.tech, биллинг
и типовые поломки LTE-линейки с рецептами ремонта (по итогам разбора
и починки 2026-11-22). Настройка зеркала страницы подписки и белые
списки живут отдельно — в «Панель и узлы» → «Яндекс Клауд» (rw_yandex).
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

GSLB = "8d4319fdecfff922.topology.gslb.yccdn.ru"


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
        "Yandex CDN — край для LTE-линейки и страницы подписки.",
        "Схема: пользователь → Yandex CDN → основная нода страны.",
        "Кеширование на всех ресурсах <b>ВЫКЛЮЧЕНО</b> — CDN только",
        "проксирует трафик к нодам.",
        "",
        "<b>Что внутри</b>",
        "• «Ресурсы и ноды» — ресурсы CDN, origins, цепочка на ноде;",
        "• «DNS и ремонт» — записи зоны и типовые поломки;",
        "• «Биллинг» — пакеты, грант и связь с лимитами LTE в боте.",
        "",
        "⚠️ <b>Финляндия умирает 2026-11-24 01:09</b> вместе с сервером FI:",
        "после этого ресурс fin1cdn и хост «Финляндия [LTE]»",
        "подлежат удалению.",
    ]
    kb = _kb([
        [InlineKeyboardButton("📦 Ресурсы и ноды", callback_data="yc_resources")],
        [InlineKeyboardButton("🌐 DNS и ремонт", callback_data="yc_dns")],
        [InlineKeyboardButton("💰 Биллинг", callback_data="yc_billing")],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ])
    await _show(query, context, lines, kb)


async def handle_yc_resources(query, context=None):
    """Ресурсы CDN, их origins и цепочка «CDN → nginx → VXC» на ноде."""
    lines = [
        "📦 <b>Ресурсы и ноды</b>",
        "",
        "Папка в Yandex Cloud: <b>cloud-pratokwau</b>. Все ресурсы Active,",
        "сертификаты выпущены. Общий CNAME для всех ресурсов:",
        f"<code>{GSLB}</code>",
        "",
        "<b>Ресурсы и их origins</b>",
        "• <b>fin1cdn</b> (<code>bc8r6dlc6663p5pte2m7</code>) → 95.85.251.169",
        "  по HTTP, Host — как у клиента;",
        "• <b>de1cdn</b> (<code>bc8rpgse7cdpe44yji5v</code>) → 144.31.223.252",
        "  по HTTP, Host de1cdn.drbl.tech;",
        "• <b>se1cdn</b> (<code>bc8rnvikmt7jicqodcjk</code>) → 81.90.21.84 по HTTP;",
        "• <b>sub</b> (<code>bc8rx2kwik6ohfqdylu3</code>) → key.drbl.tech по HTTPS",
        "  (страница подписки).",
        "",
        "<b>Цепочка на ноде</b>",
        "CDN приходит на nginx ноды: порт 80, server_name —",
        "<code>&lt;страна&gt;1cdn.drbl.tech</code>. Дальше <code>location /drbl7f3a</code>",
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
        "• fin1cdn, de1cdn, se1cdn, sub — CNAME на",
        f"  <code>{GSLB}</code>;",
        "• finnode1 — A 95.85.251.169;",
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
        "150 ₽/мес за ресурс × 4 ресурса = <b>600 ₽/мес</b>.",
        "В пакет каждого ресурса включено: 150 ГБ исходящего",
        "трафика + 100 млн запросов. Пакеты между ресурсами",
        "<b>НЕ переносятся</b> — неиспользованное сгорает.",
        "",
        "Сверх пакета — оплата за ГБ, но ставка в консоли",
        "не отображается: смотреть детализацию биллинга.",
        "",
        "<b>Сейчас</b>",
        "На 2026-11-22 потребление (~44,5 ГБ за 30 дней) полностью",
        "покрыто грантом 2 650 ₽ — к оплате 0 ₽. Когда грант",
        "кончится, счёт станет ~600 ₽/мес плюс сверхпакетный трафик.",
        "",
        "<b>Связь с ботом</b>",
        "У подписок есть месячный LTE-лимит: пресеты paid_preset_lte",
        "и preset_lte (настройки подписок), изначально — 30 ГБ/мес.",
        "При превышении лимита бот перекидывает подписку",
        "в fallback-сквад, поэтому для основной линейки пресет",
        "должен быть заметно выше фактического расхода.",
    ]
    await _show(query, context, lines, _back_to_menu())
