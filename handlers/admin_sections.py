"""Разделы новой админки: хабы Деньги / Серверы / Люди / Маркетинг / Система.

Навигация перестроена полностью: вместо плоского списка из 14 рядов —
дашборд (handlers.admin.handle_admin_panel) и пять хабов. Сами экраны
функций (листья) не менялись: их callback_data и хендлеры прежние,
поэтому глубокие переходы и старые кнопки продолжают работать.
"""

import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config
import core.maintenance as mnt


def _back() -> list:
    return [InlineKeyboardButton("◀️ Админка", callback_data="admin_panel")]


def _render(query, text: str, rows: list) -> object:
    rows = [r for r in rows if r]
    rows.append(_back())
    return query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
        disable_web_page_preview=True,
    )


async def handle_admin_money(query, context: ContextTypes.DEFAULT_TYPE):
    """💰 Деньги: статистика, финансы, подписки."""
    from core.database import finance_summary
    from handlers.finance import current_period, fmt_price, month_title
    try:
        period = current_period()
        s = await finance_summary(period)
        money = (
            "<blockquote>"
            f"📅 {month_title(period)}\n"
            f"💵 Доходы: <b>{fmt_price(s['income'])}</b>\n"
            f"🖥 Расходы: <b>{fmt_price(s['expenses'])}</b>\n"
            f"💹 Прибыль: <b>{fmt_price(s['profit'])}</b>"
            "</blockquote>"
        )
    except Exception:
        money = ""
    text = "💰 <b>Деньги</b>\n\n" + money
    await _render(query, text, [
        [InlineKeyboardButton("📊 Статистика", callback_data="dashboard")],
        [InlineKeyboardButton("💰 Финансы", callback_data="pay_provider_menu")],
        [InlineKeyboardButton("💳 Платные подписки", callback_data="paid_subs"),
         InlineKeyboardButton("📋 Админские", callback_data="admin_subs")],
    ])


async def handle_admin_servers(query, context: ContextTypes.DEFAULT_TYPE):
    """🛰 Серверы: панель, сайт, проверки, бэкап."""
    cfg = load_config()
    dead = cfg.get("dead_nodes") or []
    if not cfg.get("panel_healthy", True):
        line = "🔴 Панель недоступна"
    elif dead:
        line = f"🟡 Недоступны узлы: {', '.join(dead)}"
    elif not cfg.get("sub_healthy", True):
        line = "🟡 Ссылки подписок не отдаются"
    else:
        line = "🟢 Всё работает"
    from core.database import get_downtime_events
    now = int(time.time())
    try:
        falls = len(await get_downtime_events(now - 30 * 86400))
        falls_line = f"\n📉 Падений за 30 дней: <b>{falls}</b>"
    except Exception:
        falls_line = ""
    text = (
        "🛰 <b>Серверы</b>\n\n"
        "<blockquote>"
        f"{line}{falls_line}"
        "</blockquote>"
    )
    await _render(query, text, [
        [InlineKeyboardButton("🖥 Панель и узлы", callback_data="rw_menu")],
        [InlineKeyboardButton("🌐 Веб-доступ", callback_data="web_menu")],
        [InlineKeyboardButton("🌐 Проверка операторов",
                              callback_data="netcheck_menu")],
        [InlineKeyboardButton("💾 Бэкап и перенос", callback_data="backup_menu")],
    ])


async def handle_admin_people(query, context: ContextTypes.DEFAULT_TYPE):
    """👥 Люди: тикеты, юзеры, помощники, чёрный список."""
    from core.database import get_unread_tickets_count
    unread = await get_unread_tickets_count()
    tickets = (f"🎫 Тикеты · 🔴 {unread}" if unread else "🎫 Тикеты")
    text = (
        "👥 <b>Люди</b>\n\n"
        "<blockquote>"
        f"🎫 Открытых тикетов: <b>{unread}</b>"
        "</blockquote>"
    )
    await _render(query, text, [
        [InlineKeyboardButton(tickets, callback_data="ticket_list:1")],
        [InlineKeyboardButton("🔍 Найти юзера", callback_data="find_user")],
        [InlineKeyboardButton("👥 Помощники", callback_data="helpers_menu")],
        [InlineKeyboardButton("⛔ Чёрный список", callback_data="bl_menu"),
         InlineKeyboardButton("🕵 Повторные триалы", callback_data="fraud_menu")],
        [InlineKeyboardButton("🎯 Возврат ушедших",
                              callback_data="winback_settings"),
         InlineKeyboardButton("⏰ Напоминания",
                              callback_data="remind_settings")],
    ])


async def handle_admin_marketing(query, context: ContextTypes.DEFAULT_TYPE):
    """📣 Маркетинг: рассылка, канал, документы."""
    await _render(query, "📣 <b>Маркетинг</b>", [
        [InlineKeyboardButton("📣 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton("📢 Канал", callback_data="channel_menu")],
        [InlineKeyboardButton("📄 Документы", callback_data="documents_menu")],
    ])


async def handle_admin_system(query, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ Система: логи, поддержка, техработы, обновление."""
    mnt_label = ("🔴 Техработы ВКЛЮЧЕНЫ" if mnt.is_maintenance()
                 else "🛠 Техработы и функции")
    text = "⚙️ <b>Система</b>"
    if mnt.is_maintenance():
        text += ("\n\n🔴 <b>Техработы включены</b> — пользователи видят "
                 "заглушку")
    await _render(query, text, [
        [InlineKeyboardButton("📜 Логи", callback_data="ctl_menu")],
        [InlineKeyboardButton("🛟 Поддержка", callback_data="support_settings"),
         InlineKeyboardButton("🧾 Лог-канал",
                              callback_data="log_channel_settings")],
        [InlineKeyboardButton(mnt_label, callback_data="mnt_menu")],
        [InlineKeyboardButton("🔄 Обновиться с GitHub",
                              callback_data="git_update")],
    ])
