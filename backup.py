"""Бэкап бота: выгрузить всё одним файлом и залить обратно на новом сервере.

В архив идёт база (подписки, платежи, промокоды, тикеты, история), config.json
со всеми настройками и папка assets с логотипом. Токен бота не кладём: он
живёт в .env и задаётся при установке — случайно переслать архив с токеном
опаснее, чем один раз вписать его руками.

База копируется средствами самой SQLite, а не «cp файла»: бот в этот момент
работает, и простая копия могла бы застать базу на середине записи.
"""

import io
import json
import os
import sqlite3
import zipfile
from datetime import datetime

from config import INSTALL_DIR, CONFIG_FILE

DB_NAME = "bot.db"
ASSETS_DIR = os.path.join(INSTALL_DIR, "assets")
STAGED = os.path.join(INSTALL_DIR, "restore_staged.zip")
# таблицы, без которых архив точно не наш
REQUIRED_TABLES = {"users", "paid_subs", "payments"}


def _db_path() -> str:
    from database import DB_PATH
    return DB_PATH


def snapshot_db() -> bytes:
    """Консистентная копия базы, снятая на работающем боте."""
    tmp = os.path.join(INSTALL_DIR, f".snapshot_{os.getpid()}.db")
    src = sqlite3.connect(_db_path())
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        src.close()
        if os.path.exists(tmp):
            os.remove(tmp)


def db_counts(path: str = "") -> dict:
    """Сколько чего в базе — чтобы видеть, что именно уезжает и приезжает."""
    out = {}
    try:
        con = sqlite3.connect(path or _db_path())
        try:
            for label, table in (("Пользователи", "users"), ("Подписки", "paid_subs"),
                                 ("Платежи", "payments"), ("Промокоды", "promo_codes"),
                                 ("Сообщения", "support_messages")):
                try:
                    out[label] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    continue
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return out


def make_archive() -> tuple:
    """Готовит архив. Возвращает (байты, имя файла, что внутри)."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    counts = db_counts()
    meta = {"created_at": datetime.now().isoformat(timespec="seconds"),
            "counts": counts, "source": os.uname().nodename if hasattr(os, "uname") else ""}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(DB_NAME, snapshot_db())
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "rb") as f:
                z.writestr("config.json", f.read())
        if os.path.isdir(ASSETS_DIR):
            for name in sorted(os.listdir(ASSETS_DIR)):
                path = os.path.join(ASSETS_DIR, name)
                if os.path.isfile(path):
                    with open(path, "rb") as f:
                        z.writestr(f"assets/{name}", f.read())
        z.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
    return buf.getvalue(), f"drebol-backup_{stamp}.zip", counts


def inspect_archive(blob: bytes) -> dict:
    """Проверяет присланный архив, не трогая рабочие файлы."""
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "это не zip-архив"}
    names = set(z.namelist())
    if DB_NAME not in names:
        return {"ok": False, "error": "в архиве нет базы bot.db"}

    tmp = os.path.join(INSTALL_DIR, f".check_{os.getpid()}.db")
    try:
        with open(tmp, "wb") as f:
            f.write(z.read(DB_NAME))
        con = sqlite3.connect(tmp)
        try:
            state = con.execute("PRAGMA integrity_check").fetchone()[0]
            if state != "ok":
                return {"ok": False, "error": f"база повреждена: {state[:120]}"}
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
        missing = REQUIRED_TABLES - tables
        if missing:
            return {"ok": False, "error": f"это база не от нашего бота "
                                          f"(нет таблиц: {', '.join(sorted(missing))})"}
        counts = db_counts(tmp)
    except sqlite3.Error as e:
        return {"ok": False, "error": f"базу не открыть: {e}"}
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    meta = {}
    if "meta.json" in names:
        try:
            meta = json.loads(z.read("meta.json").decode("utf-8"))
        except Exception:
            meta = {}
    return {"ok": True, "counts": counts, "meta": meta,
            "has_config": "config.json" in names,
            "assets": sorted(n.split("/", 1)[1] for n in names
                             if n.startswith("assets/") and not n.endswith("/"))}


def stage_archive(blob: bytes):
    """Кладёт присланный архив рядом с ботом до подтверждения."""
    with open(STAGED, "wb") as f:
        f.write(blob)


def staged_archive() -> bytes:
    with open(STAGED, "rb") as f:
        return f.read()


def drop_staged():
    if os.path.exists(STAGED):
        os.remove(STAGED)


def apply_archive(blob: bytes) -> dict:
    """Заменяет данные бота данными из архива.

    Перед заменой складывает текущее состояние в отдельный файл: если в
    архиве окажется не то, будет чем вернуться.
    """
    try:
        safety, name, _ = make_archive()
        safety_path = os.path.join(INSTALL_DIR, f"before-restore_{name}")
        with open(safety_path, "wb") as f:
            f.write(safety)
    except Exception as e:
        return {"ok": False, "error": f"не сделать страховочную копию: {e}"}

    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        with open(_db_path(), "wb") as f:
            f.write(z.read(DB_NAME))
        if "config.json" in z.namelist():
            with open(CONFIG_FILE, "wb") as f:
                f.write(z.read("config.json"))
        os.makedirs(ASSETS_DIR, exist_ok=True)
        for entry in z.namelist():
            if entry.startswith("assets/") and not entry.endswith("/"):
                with open(os.path.join(ASSETS_DIR, os.path.basename(entry)), "wb") as f:
                    f.write(z.read(entry))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "safety": safety_path, "counts": db_counts()}


def human_size(num: int) -> str:
    if num < 1024:
        return f"{num} Б"
    if num < 1024 ** 2:
        return f"{num / 1024:.0f} КБ"
    return f"{num / 1024 ** 2:.1f} МБ"


def _counts_block(counts: dict) -> str:
    return "\n".join(f"{k}: <b>{v}</b>" for k, v in counts.items()) or "пусто"


# ── Экраны админки ────────────────────────────────────────────────────────────

async def handle_backup_menu(query, context=None):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context:
        context.user_data.pop("state", None)
    drop_staged()
    counts = db_counts()
    size = os.path.getsize(_db_path()) if os.path.exists(_db_path()) else 0

    await query.edit_message_text(
        "💾 <b>Бэкап и перенос</b>\n\n"
        f"<blockquote>{_counts_block(counts)}\n"
        f"База: <b>{human_size(size)}</b></blockquote>\n\n"
        "В архив идут база, настройки и логотип. Токен бота не кладём — "
        "он в <code>.env</code> и задаётся при установке.\n\n"
        "<i>В настройках лежат ключи платёжки и пароль сервера сайта: "
        "архив никому не пересылай.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Выгрузить", callback_data="backup_export"),
             InlineKeyboardButton("📥 Загрузить", callback_data="backup_import")],
            [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
        ]),
    )


async def handle_backup_export(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from html import escape
    await query.edit_message_text("📦 Собираю архив…")
    try:
        blob, name, counts = make_archive()
    except Exception as e:
        await query.edit_message_text(
            f"❌ <b>Не собрать архив</b>\n\n<code>{escape(str(e)[:300])}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="backup_menu")]]),
        )
        return

    await context.bot.send_document(
        chat_id=query.from_user.id,
        document=io.BytesIO(blob), filename=name,
        caption=(f"💾 <b>Бэкап Drebol VPN</b>\n\n"
                 f"<blockquote>{_counts_block(counts)}\n"
                 f"Размер: <b>{human_size(len(blob))}</b></blockquote>\n\n"
                 "На новом сервере: поставь бота, задай токен в <code>.env</code> "
                 "и пришли этот файл в «💾 Бэкап» → «📥 Загрузить»."),
        parse_mode="HTML",
    )
    await query.edit_message_text(
        "✅ <b>Архив отправлен</b>\n\n"
        "<i>Сохрани его у себя и удали сообщение из чата — внутри ключи.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="backup_menu")]]),
    )


async def handle_backup_import(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_BACKUP_FILE
    context.user_data["state"] = AWAITING_BACKUP_FILE
    await query.edit_message_text(
        "📥 <b>Загрузка бэкапа</b>\n\n"
        "Пришли файл <code>.zip</code>, который бот выгружал раньше.\n\n"
        "Сначала покажу, что внутри, и только после подтверждения заменю данные. "
        "Текущее состояние сохраню отдельным файлом на сервере.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Отмена", callback_data="backup_menu")]]),
    )


async def offer_restore(message, context, blob: bytes):
    """Показывает содержимое присланного архива и спрашивает подтверждение."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from html import escape
    info = inspect_archive(blob)
    if not info["ok"]:
        await message.reply_text(
            f"❌ <b>Архив не подходит</b>\n\n<code>{escape(str(info['error']))}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К бэкапу", callback_data="backup_menu")]]),
        )
        return

    stage_archive(blob)
    when = (info["meta"].get("created_at") or "").replace("T", " ")[:16]
    extras = []
    if info["has_config"]:
        extras.append("настройки")
    if info["assets"]:
        extras.append("логотип")
    await message.reply_text(
        "📥 <b>Проверил архив</b>\n\n"
        f"<blockquote>{_counts_block(info['counts'])}</blockquote>\n"
        + (f"📅 Создан: <b>{when}</b>\n" if when else "")
        + (f"📦 Ещё внутри: {', '.join(extras)}\n" if extras else "")
        + "\n⚠️ <b>Текущие данные бота будут заменены.</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("♻️ Заменить данные", callback_data="backup_apply")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="backup_menu")],
        ]),
    )


async def handle_backup_apply(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from html import escape
    if not os.path.exists(STAGED):
        await query.answer("Архив не найден — пришли файл заново", show_alert=True)
        await handle_backup_menu(query, context)
        return

    await query.edit_message_text("♻️ Заменяю данные…")
    res = apply_archive(staged_archive())
    drop_staged()
    if not res["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получилось</b>\n\n<code>{escape(str(res['error'])[:300])}</code>\n\n"
            "Данные остались прежними.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К бэкапу", callback_data="backup_menu")]]),
        )
        return

    from log_channel import send_log
    await send_log(context.bot, "💾 Данные бота восстановлены из бэкапа")
    await query.edit_message_text(
        "✅ <b>Данные восстановлены</b>\n\n"
        f"<blockquote>{_counts_block(res['counts'])}</blockquote>\n"
        "Перезапускаюсь, чтобы подхватить базу.\n\n"
        "<i>Если не отвечу через минуту — запусти службу руками:</i>\n"
        "<code>systemctl restart drebol-vpn</code>",
        parse_mode="HTML",
    )
    _schedule_restart(context)


def _schedule_restart(context):
    """Выходим — systemd поднимет бота заново с новой базой."""
    import asyncio

    async def _bye():
        await asyncio.sleep(2)
        os._exit(0)

    try:
        context.application.create_task(_bye())
    except Exception:
        asyncio.get_event_loop().create_task(_bye())
