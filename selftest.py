"""Самопроверка бота на живом тестовом клиенте.

Заводит подписку настоящему тестовому пользователю в настоящей панели, проходит
за него все клиентские экраны и за админа — всю админскую работу с этой
подпиской, после каждого действия сверяет, что получилось, с тем, что должно
было получиться, и присылает разбор админу в бот.

Запуск на сервере:

    cd /root/drebol-vpn && venv/bin/python selftest.py

Что важно знать:

— Подписка создаётся настоящая: в базе бота и в панели. В конце прогон её
  удаляет вместе со всеми следами (история, промокод, тикет, платежи).
— Сообщения «клиенту» никуда не уходят: бот в прогоне поддельный, он их только
  записывает. Наружу уходит один настоящий отчёт — тебе в личку.
— Счёт в Platega не выставляется: создание платежа подменено заглушкой,
  чтобы прогон не плодил счета в кабинете.
— Опасное прогон не трогает: массовые действия над всеми подписками, рассылки,
  техработы, восстановление из бэкапа, удаление сайта, обновление с GitHub.
  Это перечислено в отчёте, чтобы не было иллюзии, что проверено всё.
"""

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import ADMIN_ID, BOT_TOKEN, load_config   # noqa: E402

TEST_TG_ID = int(os.environ.get("SELFTEST_TG_ID") or 900000001)
TEST_NAME = "Тест Прогонов"
TEST_USERNAME = "selftest_user"
DATE_FMT = "%d.%m.%Y %H:%M:%S"

SKIPPED = [
    "массовые действия над всеми подписками (сдвиг срока, лимиты всем)",
    "рассылки клиентам и рассылка ссылок подписок",
    "техработы (включили бы их всем)",
    "восстановление базы из бэкапа",
    "удаление сайта и обновление с GitHub",
    "реальное выставление счёта в Platega (подменено заглушкой)",
]


# ── Журнал ────────────────────────────────────────────────────────────────────

class Log:
    def __init__(self):
        self.rows = []      # (уровень, действие, ожидали, получили)
        self.section = ""

    def part(self, title):
        self.section = title
        self.rows.append(("part", title, "", ""))
        print(f"\n── {title}")

    def check(self, action, ok, expected="", got=""):
        self.rows.append(("ok" if ok else "bad", action, expected, str(got)[:400]))
        mark = "✅" if ok else "❌"
        print(f"{mark} {action}")
        if not ok:
            print(f"    ждали: {expected}")
            print(f"    вышло: {str(got)[:400]}")
        return ok

    def note(self, text):
        self.rows.append(("note", text, "", ""))
        print(f"ℹ️  {text}")

    def crash(self, action, err):
        self.rows.append(("crash", action, "должно было выполниться без ошибок",
                          f"{type(err).__name__}: {err}"))
        print(f"💥 {action}: {type(err).__name__}: {err}")

    @property
    def bad(self):
        return [r for r in self.rows if r[0] in ("bad", "crash")]

    def text(self) -> str:
        total = sum(1 for r in self.rows if r[0] in ("ok", "bad", "crash"))
        lines = [
            "ОТЧЁТ САМОПРОВЕРКИ DREBOL VPN",
            f"Когда: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            f"Тестовый клиент: tg {TEST_TG_ID}",
            f"Проверок: {total}, проблем: {len(self.bad)}",
            "",
        ]
        for kind, action, expected, got in self.rows:
            if kind == "part":
                lines += ["", f"── {action} " + "─" * max(0, 60 - len(action))]
            elif kind == "note":
                lines.append(f"    · {action}")
            elif kind == "ok":
                lines.append(f"[ОК]   {action}")
            else:
                lines.append(f"[ПЛОХО] {action}")
                lines.append(f"        ждали: {expected}")
                lines.append(f"        вышло: {got}")
        lines += ["", "НЕ ПРОВЕРЯЛОСЬ (опасно для живых клиентов):"]
        lines += [f"    · {s}" for s in SKIPPED]
        return "\n".join(lines)


log = Log()


# ── Поддельные телеграм-объекты ───────────────────────────────────────────────

class FakeBot:
    """Записывает всё, что бот попытался отправить, и никуда это не отправляет."""

    def __init__(self):
        self.sent = []          # (chat_id, text)

    async def send_message(self, chat_id=None, text=None, **kw):
        self.sent.append((chat_id, text or ""))
        return types.SimpleNamespace(message_id=1, chat_id=chat_id)

    async def send_photo(self, chat_id=None, photo=None, caption=None, **kw):
        self.sent.append((chat_id, f"[фото] {caption or ''}"))
        return types.SimpleNamespace(message_id=1)

    async def send_document(self, chat_id=None, document=None, caption=None, **kw):
        self.sent.append((chat_id, f"[файл] {caption or ''}"))
        return types.SimpleNamespace(message_id=1)

    async def get_me(self):
        return types.SimpleNamespace(username="drebolvpn_bot", id=1, first_name="Drebol")

    async def get_chat_member(self, chat_id=None, user_id=None, **kw):
        return types.SimpleNamespace(status="member")

    def __getattr__(self, name):
        async def _noop(*a, **kw):
            return None
        return _noop

    def to(self, chat_id) -> list:
        return [t for c, t in self.sent if c == chat_id]

    def last(self) -> str:
        return self.sent[-1][1] if self.sent else ""


class FakeQuery:
    """Экран, каким его увидел бы человек: текст и кнопки."""

    def __init__(self, uid, first_name="Тест", username=None):
        self.from_user = types.SimpleNamespace(id=uid, first_name=first_name,
                                               username=username, is_bot=False)
        self.out, self.toasts = [], []
        self.data = ""
        self.message = types.SimpleNamespace(
            message_id=1, chat_id=uid, text="",
            reply_text=self._reply, delete=self._noop, chat=types.SimpleNamespace(id=uid),
        )

    async def _reply(self, text=None, **kw):
        self.out.append((text or "", kw.get("reply_markup")))
        return types.SimpleNamespace(message_id=1)

    async def _noop(self, *a, **kw):
        return None

    async def edit_message_text(self, text=None, **kw):
        self.out.append((text or "", kw.get("reply_markup")))
        return True

    async def edit_message_caption(self, caption=None, **kw):
        self.out.append((caption or "", kw.get("reply_markup")))
        return True

    async def answer(self, text=None, **kw):
        self.toasts.append(text or "")
        return True

    async def delete_message(self, *a, **kw):
        return True

    @property
    def text(self) -> str:
        return self.out[-1][0] if self.out else ""

    @property
    def buttons(self) -> list:
        """Все callback_data с последнего экрана."""
        mk = self.out[-1][1] if self.out else None
        rows = getattr(mk, "inline_keyboard", None) or []
        return [b.callback_data for r in rows for b in r if b.callback_data]

    @property
    def labels(self) -> list:
        mk = self.out[-1][1] if self.out else None
        rows = getattr(mk, "inline_keyboard", None) or []
        return [b.text for r in rows for b in r]

    @property
    def urls(self) -> list:
        """Адреса кнопок-ссылок — например, ссылки на оплату."""
        mk = self.out[-1][1] if self.out else None
        rows = getattr(mk, "inline_keyboard", None) or []
        return [b.url for r in rows for b in r if getattr(b, "url", None)]


class FakeUpdate:
    """Сообщение в чат — так проверяем экраны, которые ждут ввод текстом."""

    def __init__(self, uid, text):
        self.effective_user = types.SimpleNamespace(id=uid, first_name="Админ",
                                                    username="admin", is_bot=False)
        self.out = []
        self.message = types.SimpleNamespace(
            message_id=2, chat_id=uid, text=text,
            reply_text=self._reply, delete=self._noop,
            chat=types.SimpleNamespace(id=uid), from_user=self.effective_user,
            photo=None, document=None, caption=None,
        )

    async def _reply(self, text=None, **kw):
        self.out.append(text or "")
        return types.SimpleNamespace(message_id=3)

    async def _noop(self, *a, **kw):
        return None

    @property
    def text(self) -> str:
        return self.out[-1] if self.out else ""


def ctx(bot):
    return types.SimpleNamespace(bot=bot, user_data={}, chat_data={}, args=[],
                                 application=types.SimpleNamespace(bot_data={}))


# ── Помощники ─────────────────────────────────────────────────────────────────

async def panel_user(email: str) -> dict:
    """Что о клиенте думает панель прямо сейчас."""
    import remnawave as rw
    from panel import _name
    r = await rw.user_by_name(_name(email))
    return (r.get("data") or {}) if r.get("ok") else {}


def days_between(a: str, b: str) -> float:
    from paidsub.storage import parse_sub_date
    da, db_ = parse_sub_date(a), parse_sub_date(b)
    if not da or not db_:
        return -999
    return round((db_ - da).total_seconds() / 86400, 3)


def iso_day(raw) -> str:
    return str(raw or "")[:10]


def ru_day(raw: str) -> str:
    from paidsub.storage import parse_sub_date
    d = parse_sub_date(raw)
    return d.strftime("%Y-%m-%d") if d else ""


async def run_state(bot, state: str, text: str, sub_id=None, uid=None):
    """Прогоняет ввод текстом так, как это делает живой чат."""
    from handlers.messages import handle_text
    c = ctx(bot)
    c.user_data["state"] = state
    if sub_id is not None:
        c.user_data["edit_sub_id"] = sub_id
    upd = FakeUpdate(uid or ADMIN_ID, text)
    await handle_text(upd, c)
    return upd


# ── Подготовка ────────────────────────────────────────────────────────────────

async def prepare(bot):
    log.part("Подготовка")
    from database import init_db, upsert_user, get_user_info
    import remnawave as rw

    await init_db()
    log.check("база на месте", True)

    cfg = load_config()
    log.check("панель настроена", rw.is_configured(),
              "адрес и токен Remnawave заданы", "нет адреса или токена")
    check = await rw.test_connection()
    log.check("панель отвечает", bool(check.get("ok")),
              "панель на связи", check.get("error"))

    ready = all(cfg.get(k) is not None for k in
                ("paid_trial_period", "paid_pay_period", "paid_preset_hwid",
                 "paid_preset_traffic"))
    log.check("настройки платных подписок заданы", ready,
              "заполнены триал, период оплаты, лимит устройств, трафик",
              "не хватает части настроек")

    await upsert_user(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
    row = await get_user_info(TEST_TG_ID)
    log.check("тестовый пользователь в базе", bool(row), "запись в users", row)
    return ready and bool(check.get("ok"))


async def issue_sub(bot):
    log.part("Выдача подписки")
    from paidsub.handlers import do_create_paid_sub
    from paidsub.storage import get_paid_sub_by_tg_id

    replies = []

    async def reply(text=None, **kw):
        replies.append(text or "")

    await do_create_paid_sub(None, TEST_TG_ID, ctx(bot), reply, trial=False)
    row = await get_paid_sub_by_tg_id(TEST_TG_ID)
    log.check("подписка создана в базе", bool(row), "строка в paid_subs", row)
    if not row:
        return None

    sub_id, email, sub_url = row[0], row[2], row[5]
    log.check("ссылка подписки выдана", bool(sub_url) and "://" in sub_url,
              "ссылка вида https://…/sub/…", sub_url)

    pu = await panel_user(email)
    log.check("клиент появился в панели", bool(pu.get("username")),
              f"клиент {email} в панели", pu or "панель его не знает")
    log.check("срок в панели совпадает с базой",
              iso_day(pu.get("expireAt")) == ru_day(row[6]),
              f"expireAt = {ru_day(row[6])}", iso_day(pu.get("expireAt")))
    log.check("лимит устройств доехал",
              int(pu.get("hwidDeviceLimit") or 0) == int(row[8] or 0),
              f"{row[8]} устройств", pu.get("hwidDeviceLimit"))
    log.check("в панели видно, кто это",
              str(pu.get("telegramId") or "") == str(TEST_TG_ID),
              f"telegramId = {TEST_TG_ID}", pu.get("telegramId"))
    log.check("ссылка из панели, а не придумана ботом",
              sub_url == pu.get("subscriptionUrl"),
              "ссылка совпадает с subscriptionUrl панели", pu.get("subscriptionUrl"))
    return sub_id


# ── Клиентские действия ───────────────────────────────────────────────────────

async def client_flow(bot, sub_id):
    log.part("Что может сделать сам клиент")
    import handlers.user as hu
    from paidsub.storage import get_paid_sub_by_tg_id

    user = types.SimpleNamespace(id=TEST_TG_ID, first_name=TEST_NAME,
                                 username=TEST_USERNAME, is_bot=False)
    c = ctx(bot)

    text, _mk = await hu.start_screen(user)
    log.check("/start показывает подписку",
              "подписка" in text.lower() and "🔗" in text or "Ссылка" in text,
              "на старте видно состояние подписки и ссылку", text[:200])

    q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
    await hu.handle_my_paid_sub(q)
    log.check("экран «действия с подпиской» открывается",
              bool(q.buttons), "экран с кнопками", q.text[:160])
    log.check("на экране есть устройства и перевыпуск ключа",
              "my_devices" in q.buttons and "reissue_key" in q.buttons,
              "кнопки «Мои устройства» и «Перевыпустить ключ»", q.buttons)

    q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
    await hu.handle_renew_sub(q)
    renew_ok = bool(q.buttons)
    log.check("экран продления открывается", renew_ok, "тарифы или счёт", q.text[:200])
    tariff_btn = [b for b in q.buttons if b.startswith("tariff_pick:")]
    log.note(f"тарифов на экране: {len(tariff_btn)}")

    if tariff_btn:
        q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
        tid = int(tariff_btn[0].split(":")[1])
        await hu.handle_tariff_pick(q, c, tid)
        log.check("карточка тарифа открывается",
                  "₽" in q.text, "цена и срок тарифа", q.text[:200])
        log.check("с карточки можно оплатить",
                  any(b.startswith("pay_invoice") for b in q.buttons),
                  "кнопка оплаты", q.buttons)

        q2 = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
        await hu.handle_pay_invoice(q2, c, tid)
        log.check("счёт выставляется и ссылка на оплату приходит",
                  any("http" in u for u in q2.urls),
                  "кнопка со ссылкой на оплату",
                  q2.urls or q2.text[:200])

    q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
    await hu.handle_my_devices(q, c)
    log.check("«мои устройства» открывается", bool(q.text),
              "список устройств или сообщение, что их нет", q.text[:200])
    dev_btn = [b for b in q.buttons if b.startswith("dev_del:")]
    log.note(f"устройств у тестового клиента: {len(dev_btn)} "
             "(ноль — нормально, он не подключался)")
    if dev_btn:
        await hu.handle_dev_del(q, c, dev_btn[0].split(":", 1)[1])
        log.check("клиент может отключить своё устройство",
                  any("отключ" in (t or "").lower() for t in q.toasts), "подтверждение",
                  q.toasts)

    for name, fn in (("как подключиться", hu.handle_how_to), ("цены", hu.handle_prices),
                     ("о сервисе", hu.handle_about), ("инфо", hu.handle_info)):
        q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
        try:
            await fn(q)
            log.check(f"экран «{name}» открывается", bool(q.text), "текст на экране",
                      q.text[:120])
        except Exception as e:
            log.crash(f"экран «{name}»", e)

    q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
    await hu.handle_referral(q, c)
    log.check("реферальная ссылка выдаётся", "t.me" in q.text or "start=" in q.text,
              "ссылка-приглашение", q.text[:200])

    q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
    await hu.handle_qr_code(q, c)
    qr_sent = any("[фото]" in t for t in bot.to(TEST_TG_ID))
    no_lib = any("QR-генератор" in (t or "") for t in q.toasts)
    log.check("QR-код подписки отдаётся", qr_sent,
              "боту прислали картинку с QR",
              "на сервере нет модуля qrcode — кнопка QR у клиентов не работает, "
              "лечится: venv/bin/pip install qrcode pillow" if no_lib
              else (bot.to(TEST_TG_ID)[-1:] or q.toasts))

    # ── промокод: создаём свой, применяем, снимаем
    from paidsub.storage import create_promo, get_promo
    code = f"SELFTEST{datetime.now().strftime('%H%M%S')}"
    await create_promo(code, 50, None, note="самопроверка")
    promo = await get_promo(code)
    log.check("промокод создался", bool(promo), "запись в promo_codes", promo)
    if promo:
        from paidsub.storage import get_pending_promo
        upd = await run_state(bot, "awaiting_promo_code", code, uid=TEST_TG_ID)
        pending = await get_pending_promo(TEST_TG_ID)
        log.check("промокод применился к подписке",
                  (pending or "").upper() == code.upper(),
                  f"pending_promo = {code}", pending or upd.text[:160])
        q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
        await hu.handle_renew_sub(q)
        log.check("скидка видна на экране продления",
                  "−50%" in q.text or "-50%" in q.text or "50%" in q.text,
                  "в тексте есть скидка 50%", q.text[:200])
        q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
        await hu.handle_remove_promo(q, c)
        left = await get_pending_promo(TEST_TG_ID)
        log.check("промокод снимается", not left, "pending_promo пуст", left)

    # ── перевыпуск ключа
    before = (await get_paid_sub_by_tg_id(TEST_TG_ID))[5]
    q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
    await hu.handle_reissue_key(q, c)
    log.check("перевыпуск спрашивает подтверждение",
              any("reissue" in b for b in q.buttons),
              "кнопка подтверждения", q.buttons)
    q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
    await hu.handle_reissue_do(q, c)
    row = await get_paid_sub_by_tg_id(TEST_TG_ID)
    pu = await panel_user(row[2])
    log.check("ключ перевыпущен и ссылка сменилась", row[5] != before,
              "новая ссылка в базе", f"было {before}, стало {row[5]}")
    log.check("новая ссылка совпадает с панелью", row[5] == pu.get("subscriptionUrl"),
              "ссылка из панели", pu.get("subscriptionUrl"))
    new_url = row[5]
    log.check("клиент увидел новую ссылку",
              new_url and (new_url in q.text
                           or any(new_url in t for t in bot.to(TEST_TG_ID))),
              f"на экране или в сообщении есть {new_url}", q.text[:200])

    # ── поддержка
    from handlers.support import open_support
    q = FakeQuery(TEST_TG_ID, TEST_NAME, TEST_USERNAME)
    await open_support(q, TEST_TG_ID)
    log.check("поддержка открывается", bool(q.text), "экран поддержки", q.text[:160])
    upd = await run_state(bot, "awaiting_support_msg", "проверка связи, это самопроверка",
                          uid=TEST_TG_ID)
    from database import get_support_messages
    msgs, _pages = await get_support_messages(TEST_TG_ID)
    log.check("сообщение в поддержку сохранилось", bool(msgs),
              "запись в support_messages", upd.text[:160])
    log.check("клиенту ответили, что приняли", "отправлено" in upd.text.lower(),
              "подтверждение отправки", upd.text[:160])


# ── Админские действия ────────────────────────────────────────────────────────

async def admin_flow(bot, sub_id):
    log.part("Что делает админ с этой подпиской")
    import paidsub.handlers as ph
    from paidsub.storage import get_paid_sub
    c = ctx(bot)

    q = FakeQuery(ADMIN_ID, "Админ", "admin")
    await ph.handle_paid_subs_menu(q, 1)
    log.check("список платных подписок открывается", bool(q.buttons),
              "список с кнопками", q.text[:160])

    q = FakeQuery(ADMIN_ID, "Админ", "admin")
    await ph.handle_paid_sub_view(q, sub_id)
    log.check("карточка подписки открывается", str(sub_id) in q.text,
              f"карточка #{sub_id}", q.text[:200])
    log.check("в карточке есть устройства, IP и настройки",
              {f"paid_devices:{sub_id}", f"paid_ips:{sub_id}",
               f"paid_sub_settings:{sub_id}"} <= set(q.buttons),
              "кнопки устройств, адресов и настроек", q.buttons)

    q = FakeQuery(ADMIN_ID, "Админ", "admin")
    await ph.handle_paid_sub_settings(q, sub_id)
    log.check("настройки подписки открываются", "Настройки подписки" in q.text,
              "экран настроек", q.text[:160])
    log.check("мёртвого лимита IP на экране нет", "Лимит IP" not in q.text,
              "в Remnawave лимита по IP нет — его не показываем", q.text[:200])

    # ── срок: добавить
    row = await get_paid_sub(sub_id)
    before = row[6]
    await run_state(bot, "awaiting_paid_sub_extend", "7 дней", sub_id=sub_id)
    row = await get_paid_sub(sub_id)
    added = days_between(before, row[6])
    log.check("«добавить срок 7 дней» сдвигает дату ровно на 7", added == 7,
              "ровно +7 дней", f"{added} дней ({before} → {row[6]})")
    pu = await panel_user(row[2])
    log.check("новый срок доехал до панели",
              iso_day(pu.get("expireAt")) == ru_day(row[6]),
              f"expireAt = {ru_day(row[6])}", iso_day(pu.get("expireAt")))

    # ── срок: убавить
    before = row[6]
    await run_state(bot, "awaiting_paid_sub_reduce", "3 дня", sub_id=sub_id)
    row = await get_paid_sub(sub_id)
    cut = days_between(row[6], before)
    log.check("«убавить срок 3 дня» убирает ровно 3", cut == 3,
              "ровно −3 дня", f"{cut} дней ({before} → {row[6]})")
    pu = await panel_user(row[2])
    log.check("убавленный срок тоже доехал до панели",
              iso_day(pu.get("expireAt")) == ru_day(row[6]),
              f"expireAt = {ru_day(row[6])}", iso_day(pu.get("expireAt")))

    # ── лимит устройств
    await run_state(bot, "awaiting_paid_sub_edit_hwid", "4", sub_id=sub_id)
    row = await get_paid_sub(sub_id)
    pu = await panel_user(row[2])
    log.check("лимит устройств меняется в базе", int(row[8] or 0) == 4,
              "limit_hwid = 4", row[8])
    log.check("лимит устройств меняется в панели",
              int(pu.get("hwidDeviceLimit") or 0) == 4,
              "hwidDeviceLimit = 4", pu.get("hwidDeviceLimit"))

    # ── трафик
    await run_state(bot, "awaiting_paid_sub_edit_traffic", "70", sub_id=sub_id)
    row = await get_paid_sub(sub_id)
    pu = await panel_user(row[2])
    log.check("лимит трафика меняется в базе", int(row[9] or 0) == 70,
              "total_gb = 70", row[9])
    log.check("лимит трафика меняется в панели",
              int(pu.get("trafficLimitBytes") or 0) == 70 * 1024 ** 3,
              "trafficLimitBytes = 70 ГБ", pu.get("trafficLimitBytes"))

    # ── дата вручную
    manual = (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y %H:%M:%S")
    await run_state(bot, "awaiting_paid_sub_edit_expire", manual, sub_id=sub_id)
    row = await get_paid_sub(sub_id)
    pu = await panel_user(row[2])
    log.check("дата, введённая руками, встала в базу", row[6] == manual,
              manual, row[6])
    log.check("и доехала до панели", iso_day(pu.get("expireAt")) == ru_day(manual),
              ru_day(manual), iso_day(pu.get("expireAt")))

    # ── устройства и адреса в админке
    q = FakeQuery(ADMIN_ID, "Админ", "admin")
    await ph.handle_paid_devices(q, sub_id)
    log.check("экран устройств в админке открывается", "Устройства подписки" in q.text,
              "список устройств", q.text[:160])
    q = FakeQuery(ADMIN_ID, "Админ", "admin")
    await ph.handle_paid_ips(q, sub_id)
    log.check("экран адресов открывается", "IP-адреса подписки" in q.text,
              "список адресов", q.text[:160])
    log.check("кнопки сброса адресов нет — она бы не сработала",
              not any("ips_clear" in b for b in q.buttons),
              "в Remnawave адреса живут с устройствами", q.buttons)

    # ── вкл/выкл
    q = FakeQuery(ADMIN_ID, "Админ", "admin")
    await ph.handle_paid_sub_toggle(q, sub_id, c)
    pu = await panel_user((await get_paid_sub(sub_id))[2])
    log.check("«отключить» гасит клиента в панели",
              pu.get("status") != "ACTIVE", "статус не ACTIVE", pu.get("status"))
    log.check("клиента предупредили об отключении",
              any("приостановлена" in t or "отключ" in t.lower()
                  for t in bot.to(TEST_TG_ID)),
              "сообщение клиенту", bot.to(TEST_TG_ID)[-1:])
    q = FakeQuery(ADMIN_ID, "Админ", "admin")
    await ph.handle_paid_sub_toggle(q, sub_id, c)
    pu = await panel_user((await get_paid_sub(sub_id))[2])
    log.check("«включить» возвращает доступ", pu.get("status") == "ACTIVE",
              "статус ACTIVE", pu.get("status"))

    # ── заморозка
    q = FakeQuery(ADMIN_ID, "Админ", "admin")
    await ph.handle_paid_sub_freeze(q, sub_id, c)
    row = await get_paid_sub(sub_id)
    pu = await panel_user(row[2])
    log.check("заморозка отключает клиента в панели", pu.get("status") != "ACTIVE",
              "статус не ACTIVE", pu.get("status"))
    log.note(f"после заморозки статус подписки в базе: {row[11]}")
    import handlers.user as hu
    text, _mk = await hu.start_screen(types.SimpleNamespace(
        id=TEST_TG_ID, first_name=TEST_NAME, username=TEST_USERNAME, is_bot=False))
    log.check("клиент видит, что подписка заморожена, а не «всё хорошо»",
              "заморож" in text.lower() or "приостановлен" in text.lower()
              or "не работает" in text.lower(),
              "на /start честно написано про заморозку", text[:220])
    q = FakeQuery(ADMIN_ID, "Админ", "admin")
    await ph.handle_paid_sub_toggle(q, sub_id, c)
    pu = await panel_user((await get_paid_sub(sub_id))[2])
    log.check("после разморозки доступ снова открыт", pu.get("status") == "ACTIVE",
              "статус ACTIVE", pu.get("status"))

    # ── общие экраны админки
    import handlers.admin as ha
    import handlers.control as hc
    import remnawave as rw
    for name, call in (
        ("статистика", lambda: ha.handle_dashboard(FakeQuery(ADMIN_ID))),
        ("здоровье панели и узлов", lambda: ha.handle_healthcheck(FakeQuery(ADMIN_ID))),
        ("карточка пользователя", lambda: ha.handle_user_profile(FakeQuery(ADMIN_ID), TEST_TG_ID)),
        ("контроль", lambda: hc.handle_control_menu(FakeQuery(ADMIN_ID), ctx(bot))),
        ("кто онлайн", lambda: hc.handle_online(FakeQuery(ADMIN_ID))),
        ("трафик", lambda: hc.handle_traffic(FakeQuery(ADMIN_ID))),
        ("запросы", lambda: ph.handle_paid_requests(FakeQuery(ADMIN_ID))),
        ("история действий", lambda: ph.handle_paid_history(FakeQuery(ADMIN_ID), 1)),
        ("меню панели", lambda: rw.handle_rw_menu(FakeQuery(ADMIN_ID), ctx(bot))),
        ("настройки подписок", lambda: ph.handle_paid_presets_menu(FakeQuery(ADMIN_ID))),
    ):
        try:
            await call()
            log.check(f"экран «{name}» открывается", True)
        except Exception as e:
            log.crash(f"экран «{name}»", e)

    # ── бэкап: только собираем архив, восстановление не трогаем
    try:
        import backup
        data, name, inside = backup.make_archive()
        log.check("архив базы собирается",
                  bool(data) and len(data) > 1000 and str(name).endswith(".zip"),
                  "zip с базой и настройками", f"{name}, {len(data or b'')} байт")
        log.note(f"внутри архива: {inside}")
    except Exception as e:
        log.crash("сборка архива базы", e)


# ── Оплата, окончание срока, чёрный список ────────────────────────────────────

async def money_and_expiry(bot, sub_id):
    log.part("Оплата, окончание срока, чёрный список")
    import paidsub.handlers as ph
    from paidsub.storage import get_paid_sub, set_expire_date, update_paid_sub_field
    c = ctx(bot)

    from paidsub.storage import get_paid_sub_by_tg_id
    row = await get_paid_sub(sub_id)
    by_tg = await get_paid_sub_by_tg_id(TEST_TG_ID)
    before_expire = row[6]
    before_renewed = by_tg[12] if by_tg and len(by_tg) > 12 else 0
    res = await ph.apply_paid_payment(TEST_TG_ID, 100, c, source="Самопроверка")
    row = await get_paid_sub(sub_id)
    by_tg = await get_paid_sub_by_tg_id(TEST_TG_ID)
    pu = await panel_user(row[2])
    now_renewed = by_tg[12] if by_tg and len(by_tg) > 12 else 0
    log.check("оплата засчитывается", res.get("ok"), "срок продлён", res)
    log.check("срок после оплаты вырос", days_between(before_expire, row[6]) > 0,
              "дата окончания сдвинулась вперёд", f"{before_expire} → {row[6]}")
    log.check("счётчик продлений вырос", now_renewed == before_renewed + 1,
              f"times_renewed = {before_renewed + 1}", now_renewed)
    log.check("срок после оплаты доехал до панели",
              iso_day(pu.get("expireAt")) == ru_day(row[6]),
              ru_day(row[6]), iso_day(pu.get("expireAt")))
    log.check("клиенту сообщили об оплате",
              any("продлен" in t.lower() or "оплат" in t.lower()
                  for t in bot.to(TEST_TG_ID)),
              "сообщение об оплате", bot.to(TEST_TG_ID)[-1:])

    # ── возврат платежа: срок обязан уехать назад и в базе, и в панели
    from database import record_paid_payment
    pay_id = await record_paid_payment(
        tg_id=TEST_TG_ID, provider="platega", amount=100,
        period_seconds=30 * 86400,
        external_id=f"selftest-refund-{TEST_TG_ID}")
    row = await get_paid_sub(sub_id)
    before_refund = row[6]
    from handlers.payments import finalize_refund
    bot.sent.clear()
    await finalize_refund(c, pay_id, revoke=True)
    row = await get_paid_sub(sub_id)
    pu = await panel_user(row[2])
    cut = days_between(row[6], before_refund)
    log.check("возврат уменьшает срок в базе", cut == 30,
              "−30 дней (оплаченный период)", f"{cut} дней ({before_refund} → {row[6]})")
    log.check("возврат уменьшает срок и в панели",
              iso_day(pu.get("expireAt")) == ru_day(row[6]),
              f"expireAt = {ru_day(row[6])}", iso_day(pu.get("expireAt")))
    admin_said = [t for _c, t in bot.sent if "Возврат по платежу" in (t or "")]
    log.check("админу пришёл отчёт о возврате", bool(admin_said),
              "сообщение админу", bot.sent[-2:])
    if admin_said:
        log.check("в отчёте нет обещаний, которых панель не подтвердила",
                  "не подтвердила" not in admin_said[0],
                  "или дата применилась, или честное предупреждение",
                  admin_said[0][:200])
    log.note(f"после возврата панель показывает статус: {pu.get('status')}")

    # ── окончание срока: ставим дату в прошлое и зовём проверку
    past = (datetime.now() - timedelta(minutes=5)).strftime(DATE_FMT)
    await set_expire_date(sub_id, past)
    await update_paid_sub_field(sub_id, "period_end", past)
    await update_paid_sub_field(sub_id, "status", "active")
    from panel import update_client_expire
    await update_client_expire(row[2], past)
    bot.sent.clear()
    await ph.check_expired_subs(c)
    row = await get_paid_sub(sub_id)
    pu = await panel_user(row[2])
    log.check("подписка перешла в «истекла»", row[11] == "expired",
              "status = expired", row[11])
    log.check("клиента предупредили об окончании",
              any("законч" in t.lower() or "отключ" in t.lower()
                  for t in bot.to(TEST_TG_ID)),
              "сообщение клиенту", bot.to(TEST_TG_ID)[-1:])
    log.check("бот не отключал клиента руками — это дело панели",
              pu.get("status") in ("ACTIVE", "EXPIRED", "LIMITED"),
              "статус ставит панель по сроку, а не бот", pu.get("status"))
    log.note(f"панель показывает статус: {pu.get('status')} "
             f"при сроке {iso_day(pu.get('expireAt'))}")

    text, _mk = await __import__("handlers.user", fromlist=["x"]).start_screen(
        types.SimpleNamespace(id=TEST_TG_ID, first_name=TEST_NAME,
                              username=TEST_USERNAME, is_bot=False))
    log.check("на /start видно, что подписка кончилась",
              "законч" in text.lower() or "истек" in text.lower()
              or "продл" in text.lower(),
              "на старте написано про окончание", text[:200])

    # ── чёрный список: остановка и возврат остатка
    future = (datetime.now() + timedelta(days=10)).strftime(DATE_FMT)
    await set_expire_date(sub_id, future)
    await update_paid_sub_field(sub_id, "status", "active")
    await update_client_expire(row[2], future)

    import blacklist as bl
    stopped = await bl.stop_subs(TEST_TG_ID, "самопроверка")
    row = await get_paid_sub(sub_id)
    pu = await panel_user(row[2])
    log.check("чёрный список останавливает подписку", row[11] == "expired",
              "status = expired", row[11])
    log.check("и закрывает доступ в панели сразу", pu.get("status") != "ACTIVE",
              "статус не ACTIVE", pu.get("status"))
    log.check("остаток срока сохранён", bool(stopped.get("paid")),
              "в bl_hold лежит остаток", stopped)
    restored = await bl.restore_subs(TEST_TG_ID)
    row = await get_paid_sub(sub_id)
    pu = await panel_user(row[2])
    log.check("снятие с ЧС возвращает остаток", bool(restored.get("paid_until")),
              "дата окончания вернулась", restored)
    log.check("и доступ в панели снова открыт", pu.get("status") == "ACTIVE",
              "статус ACTIVE", pu.get("status"))


# ── Уборка ────────────────────────────────────────────────────────────────────

async def cleanup(bot, sub_id):
    log.part("Уборка")
    import aiosqlite
    from database import DB_PATH
    from panel import delete_client
    from paidsub.storage import get_paid_sub

    email = None
    if sub_id:
        row = await get_paid_sub(sub_id)
        email = row[2] if row else None

    if email:
        r = await delete_client(email)
        log.check("тестовый клиент удалён из панели", r.get("success"),
                  "клиента в панели нет", r)
        left = await panel_user(email)
        log.check("панель его больше не знает", not left.get("username"),
                  "пусто", left.get("username"))

    async with aiosqlite.connect(DB_PATH) as db:
        for sql, args in (
            ("DELETE FROM paid_subs WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM paid_sub_history WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM paid_sub_requests WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM support_messages WHERE user_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM tickets WHERE user_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM payments WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM activity_log WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM device_seen WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM blacklist_manual WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM blacklist_hold WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM winback_sent WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM promo_uses WHERE tg_id = ?", (TEST_TG_ID,)),
            ("DELETE FROM promo_codes WHERE code LIKE 'SELFTEST%'", ()),
            ("DELETE FROM users WHERE id = ?", (TEST_TG_ID,)),
        ):
            try:
                await db.execute(sql, args)
            except Exception as e:
                log.crash(f"уборка: {sql[:40]}", e)
        await db.commit()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM paid_subs WHERE tg_id = ?",
                              (TEST_TG_ID,)) as cur:
            left = (await cur.fetchone())[0]
    log.check("следов в базе не осталось", left == 0, "0 записей", left)


# ── Отчёт ─────────────────────────────────────────────────────────────────────

async def send_report(report: str):
    """Отчёт уходит настоящим ботом настоящему админу."""
    from telegram import Bot
    bot = Bot(BOT_TOKEN)
    bad = log.bad
    head = ("🧪 <b>Самопроверка бота</b>\n\n"
            f"<blockquote>Проверок: <b>{sum(1 for r in log.rows if r[0] in ('ok', 'bad', 'crash'))}</b>\n"
            f"Проблем: <b>{len(bad)}</b></blockquote>\n\n")
    if bad:
        from html import escape
        head += "<b>Что сломано:</b>\n" + "\n".join(
            f"• {escape(a)}" for _k, a, _e, _g in bad[:10])
        if len(bad) > 10:
            head += f"\n<i>…и ещё {len(bad) - 10}</i>"
    else:
        head += "✅ <i>Всё сработало как задумано.</i>"

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        f"selftest_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=head, parse_mode="HTML")
        with open(path, "rb") as f:
            await bot.send_document(chat_id=ADMIN_ID, document=f,
                                    filename=os.path.basename(path),
                                    caption="Полный лог самопроверки")
        print(f"\nОтчёт отправлен админу и сохранён: {path}")
    except Exception as e:
        print(f"\nНе смог отправить отчёт в телеграм: {type(e).__name__}: {e}")
        print(f"Лог лежит здесь: {path}")


async def main():
    bot = FakeBot()

    # счёт в Platega не создаём: иначе прогон плодил бы счета в кабинете
    import platega_api as pg
    real_create = pg.create_payment

    async def fake_create(amount, description, tg_id, username=None,
                          order_id=None, method=None):
        # формат тот же, что у настоящей Platega, только без запроса к ней
        return {"ok": True, "transaction_id": f"selftest-{tg_id}-{amount}",
                "url": "https://example.invalid/selftest-invoice",
                "amount": amount, "method": method}

    pg.create_payment = fake_create

    sub_id = None
    try:
        if not await prepare(bot):
            log.note("часть проверок пропущена: окружение не готово")
        sub_id = await issue_sub(bot)
        if sub_id:
            await client_flow(bot, sub_id)
            await admin_flow(bot, sub_id)
            await money_and_expiry(bot, sub_id)
        else:
            log.note("подписку создать не удалось — дальше проверять нечего")
    except Exception as e:
        import traceback
        log.crash("прогон упал на полпути", e)
        log.note(traceback.format_exc()[-600:])
    finally:
        pg.create_payment = real_create
        try:
            await cleanup(bot, sub_id)
        except Exception as e:
            log.crash("уборка", e)

    report = log.text()
    print("\n" + "=" * 70)
    print(f"Проблем: {len(log.bad)}")
    await send_report(report)


if __name__ == "__main__":
    asyncio.run(main())
