"""Сайт-визитка на втором сервере.

Бот подключается к серверу по SSH, ставит nginx, кладёт одну страницу и
включает её. Всё делается заново при каждом «Развернуть», поэтому обновить
сайт — это просто нажать кнопку ещё раз.

Пароль сервера хранится в конфиге бота (файл доступен только root) и
никогда не показывается в переписке: сообщение с ним бот удаляет сразу.
"""

import asyncio
import os
from datetime import datetime
from html import escape

from config import load_config, save_config

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_ROOT = "/var/www/drebol"
NGINX_CONF = "/etc/nginx/sites-available/drebol"
LOGO_NAME = "logo.png"


def _asset(name: str) -> bytes:
    """Файл из папки assets. Нет файла — пустые байты, не падаем."""
    try:
        with open(os.path.join(PROJECT_DIR, "assets", name), "rb") as f:
            return f.read()
    except OSError:
        return b""


def save_logo(data: bytes):
    os.makedirs(os.path.join(PROJECT_DIR, "assets"), exist_ok=True)
    with open(os.path.join(PROJECT_DIR, "assets", LOGO_NAME), "wb") as f:
        f.write(data)


def has_logo() -> bool:
    return bool(_asset(LOGO_NAME))


def process_logo(data: bytes) -> bytes:
    """Готовит присланную картинку к вставке на тёмную страницу.

    Обрезает пустые поля и, если логотип белый на тёмном фоне, делает фон
    прозрачным — иначе на сайте вокруг знака висел бы тёмный прямоугольник.
    Картинку с настоящей прозрачностью не трогаем, только подрезаем.
    """
    try:
        import io
        from PIL import Image
    except ImportError:
        return data
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return data

    has_alpha = im.mode in ("RGBA", "LA") and im.getchannel("A").getextrema()[0] < 255
    if not has_alpha:
        grey = im.convert("L")
        # тёмный фон — берём прозрачность из яркости, знак остаётся белым
        if sum(grey.getdata()) / max(1, grey.width * grey.height) < 110:
            # фон почти никогда не бывает чисто чёрным, поэтому тёмное уводим
            # в полную прозрачность, светлое — в полную непрозрачность,
            # а между ними оставляем мягкий край, чтобы буквы не рвало
            ramp = grey.point(lambda v: 0 if v < 95 else
                              (255 if v > 190 else int((v - 95) * 255 / 95)))
            im = Image.merge("RGBA", (
                Image.new("L", grey.size, 255), Image.new("L", grey.size, 255),
                Image.new("L", grey.size, 255), ramp))
        else:
            im = im.convert("RGBA")
    else:
        im = im.convert("RGBA")

    alpha = im.getchannel("A")
    # обрезаем по заметной части, а не по первому ненулевому пикселю
    box = alpha.point(lambda v: 255 if v > 60 else 0).getbbox()
    if box:
        im = im.crop(box)
    if im.width > 900:
        im = im.resize((900, max(1, round(im.height * 900 / im.width))), Image.LANCZOS)

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def creds() -> dict:
    cfg = load_config()
    return {
        "host": cfg.get("site_host", ""),
        "port": int(cfg.get("site_port", 22) or 22),
        "user": cfg.get("site_user", "root"),
        "password": cfg.get("site_pass", ""),
        "domain": cfg.get("site_domain", ""),
        "deployed_at": cfg.get("site_deployed_at", ""),
        "https": bool(cfg.get("site_https", False)),
    }


def save_creds(**kw):
    cfg = load_config()
    cfg.update(kw)
    save_config(cfg)


def configured() -> bool:
    c = creds()
    return bool(c["host"] and c["user"] and c["password"])


def site_url() -> str:
    c = creds()
    if c["domain"]:
        return f"{'https' if c['https'] else 'http'}://{c['domain']}"
    return f"http://{c['host']}" if c["host"] else ""


def _client():
    """SSH-подключение. paramiko импортируем здесь: без сайта он не нужен."""
    import paramiko
    c = creds()
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(hostname=c["host"], port=c["port"], username=c["user"],
                password=c["password"], timeout=20, banner_timeout=20,
                auth_timeout=20, look_for_keys=False, allow_agent=False)
    return cli


def _run(cli, script: str) -> tuple:
    """Гоняет bash-скрипт на сервере. Не root — добавляем sudo с паролем."""
    c = creds()
    if c["user"] != "root":
        cmd = "sudo -S -p '' bash -s"
    else:
        cmd = "bash -s"
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=300)
    if c["user"] != "root":
        stdin.write(c["password"] + "\n")
    stdin.write(script)
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _check_sync() -> dict:
    try:
        cli = _client()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    try:
        code, out, err = _run(cli, "hostname; . /etc/os-release 2>/dev/null && echo $PRETTY_NAME\n")
        if code != 0:
            return {"ok": False, "error": (err or out or "команда не выполнилась")[:200]}
        lines = [l for l in out.splitlines() if l.strip()]
        return {"ok": True, "host": lines[0] if lines else "?",
                "os": lines[1] if len(lines) > 1 else "?"}
    finally:
        cli.close()


def _deploy_sync(page: str, og_bytes: bytes, logo_bytes: bytes = b"") -> dict:
    c = creds()
    try:
        cli = _client()
    except Exception as e:
        return {"ok": False, "error": f"не подключиться: {type(e).__name__}: {e}"}
    try:
        prepare = f"""set -e
export DEBIAN_FRONTEND=noninteractive
if ! command -v nginx >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq nginx
fi
mkdir -p {WEB_ROOT}
chmod 755 {WEB_ROOT}
"""
        code, out, err = _run(cli, prepare)
        if code != 0:
            return {"ok": False, "error": f"не удалось поставить nginx: {(err or out)[-300:]}"}

        # Файлы кладём во временную папку: у не-root пользователя нет прав
        # писать в /var/www напрямую, а sudo cp ниже отработает в любом случае
        sftp = cli.open_sftp()
        try:
            with sftp.open("/tmp/drebol_index.html", "w") as f:
                f.write(page)
            with sftp.open("/tmp/drebol_og.webp", "wb") as f:
                f.write(og_bytes)
            if logo_bytes:
                with sftp.open("/tmp/drebol_logo", "wb") as f:
                    f.write(logo_bytes)
        finally:
            sftp.close()

        server_name = c["domain"] or "_"
        cert_domain = c["domain"]
        install = f"""set -e
mv /tmp/drebol_index.html {WEB_ROOT}/index.html
mv /tmp/drebol_og.webp {WEB_ROOT}/og.webp
[ -f /tmp/drebol_logo ] && mv /tmp/drebol_logo {WEB_ROOT}/{LOGO_NAME} || true
chmod 644 {WEB_ROOT}/index.html {WEB_ROOT}/og.webp
[ -f {WEB_ROOT}/{LOGO_NAME} ] && chmod 644 {WEB_ROOT}/{LOGO_NAME} || true
cat > {NGINX_CONF} <<'NGINXCONF'
server {{
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name {server_name};
    root {WEB_ROOT};
    index index.html;
    charset utf-8;
    location / {{
        try_files $uri $uri/ =404;
    }}
    location ~* \\.(webp|svg|ico|css|js)$ {{
        expires 7d;
        add_header Cache-Control "public";
    }}
}}
NGINXCONF
mkdir -p /etc/nginx/sites-enabled
ln -sf {NGINX_CONF} /etc/nginx/sites-enabled/drebol
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx 2>/dev/null || systemctl restart nginx
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
fi
# Конфиг мы переписали с нуля, поэтому блок HTTPS, который добавлял certbot,
# пропал бы вместе с ним. Сертификат на месте — просто прописываем его заново
if [ -n "{cert_domain}" ] && [ -d "/etc/letsencrypt/live/{cert_domain}" ] \
   && command -v certbot >/dev/null 2>&1; then
  certbot --nginx -d {cert_domain} --agree-tos --register-unsafely-without-email \
          --non-interactive --redirect --reinstall >/dev/null 2>&1 || true
  systemctl reload nginx 2>/dev/null || true
fi
echo DEPLOY_OK
"""
        code, out, err = _run(cli, install)
        if code != 0 or "DEPLOY_OK" not in out:
            return {"ok": False, "error": (err or out)[-400:]}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        cli.close()


def _cert_sync() -> dict:
    c = creds()
    if not c["domain"]:
        return {"ok": False, "error": "домен не задан"}
    try:
        cli = _client()
    except Exception as e:
        return {"ok": False, "error": f"не подключиться: {type(e).__name__}: {e}"}
    try:
        script = f"""set -e
export DEBIAN_FRONTEND=noninteractive
if ! command -v certbot >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq certbot python3-certbot-nginx
fi
certbot --nginx -d {c['domain']} --agree-tos --register-unsafely-without-email \
        --non-interactive --redirect
echo CERT_OK
"""
        code, out, err = _run(cli, script)
        if code != 0 or "CERT_OK" not in out:
            return {"ok": False, "error": (err or out)[-400:]}
        return {"ok": True}
    finally:
        cli.close()


DIAG_SCRIPT = """
D="__DOMAIN__"
echo "domain=$D"
echo "ip=$(curl -s -m 5 https://api.ipify.org 2>/dev/null || echo '?')"
if [ -n "$D" ]; then
  if command -v dig >/dev/null 2>&1; then
    echo "dns=$(dig +short A "$D" | tr '\n' ' ')"
  elif command -v getent >/dev/null 2>&1; then
    echo "dns=$(getent ahostsv4 "$D" | awk '{print $1}' | sort -u | tr '\n' ' ')"
  else
    echo "dns=?"
  fi
  [ -d "/etc/letsencrypt/live/$D" ] && echo "cert=yes" || echo "cert=no"
  echo "https=$(curl -s -o /dev/null -w '%{http_code}' -m 8 "https://$D/" 2>/dev/null || echo '-')"
fi
echo "nginx443=$(grep -c 'listen 443' /etc/nginx/sites-available/drebol 2>/dev/null || echo 0)"
echo "listen443=$( (ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null) | grep -c ':443 ' )"
echo "http=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1/ 2>/dev/null || echo '-')"
echo "certbot=$(command -v certbot >/dev/null 2>&1 && echo yes || echo no)"
echo DIAG_OK
"""


def _diagnose_sync() -> dict:
    """Собирает с сервера всё, что объясняет, почему сайт не на HTTPS."""
    c = creds()
    try:
        cli = _client()
    except Exception as e:
        return {"ok": False, "error": f"не подключиться: {type(e).__name__}: {e}"}
    try:
        code, out, err = _run(cli, DIAG_SCRIPT.replace("__DOMAIN__", c["domain"]))
        if "DIAG_OK" not in out:
            return {"ok": False, "error": (err or out)[-300:]}
        data = {}
        for line in out.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                data[k.strip()] = v.strip()
        return {"ok": True, "data": data}
    finally:
        cli.close()


async def diagnose() -> dict:
    res = await asyncio.to_thread(_diagnose_sync)
    # Галочку HTTPS поправляем, только когда проверка дала ясный ответ:
    # молчание сервера бывает от случайной сети, и снимать из-за него
    # уже работающий HTTPS неправильно
    if res.get("ok"):
        data = res["data"]
        code = data.get("https", "")
        if code in ("200", "301", "302"):
            if not creds()["https"]:
                save_creds(site_https=True)
        elif code not in ("", "-") and creds()["https"]:
            # «000» и прочие коды — сервер ответил внятным отказом,
            # а пустое значение или «-» значит, что проверить не вышло
            save_creds(site_https=False)
    return res


def _remove_sync() -> dict:
    try:
        cli = _client()
    except Exception as e:
        return {"ok": False, "error": f"не подключиться: {type(e).__name__}: {e}"}
    try:
        script = f"""set -e
rm -f /etc/nginx/sites-enabled/drebol {NGINX_CONF}
rm -rf {WEB_ROOT}
if [ -f /etc/nginx/sites-available/default ]; then
  ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
fi
nginx -t && (systemctl reload nginx 2>/dev/null || true)
echo REMOVE_OK
"""
        code, out, err = _run(cli, script)
        if code != 0 or "REMOVE_OK" not in out:
            return {"ok": False, "error": (err or out)[-300:]}
        return {"ok": True}
    finally:
        cli.close()


async def check_connection() -> dict:
    return await asyncio.to_thread(_check_sync)


async def site_tariffs(cfg: dict) -> list:
    """Тарифы для раздела «Тарифы» на сайте — те же, что видит клиент в боте.

    Активные тарифы из базы; если их нет — одна цена из общих настроек.
    Ничего не нашлось или база недоступна — пустой список, и раздел
    на сайте просто не показывается.
    """
    try:
        from database import list_tariffs
        from paidsub.time_parser import fmt_duration
        rows = await list_tariffs()
        tariffs = [{"name": name, "price": price, "period": fmt_duration(period)}
                   for _, name, period, price, is_active, _ in rows if is_active]
        if not tariffs:
            price = cfg.get("paid_price", 0)
            period = cfg.get("paid_pay_period")
            if price and period:
                tariffs = [{"name": fmt_duration(period), "price": price}]
        return tariffs
    except Exception:
        return []


async def deploy(bot_username: str) -> dict:
    """Собирает страницу и раскатывает её на сервер."""
    from site_page import build_page
    cfg = load_config()
    og_bytes = _asset("og.webp")
    logo_bytes = _asset(LOGO_NAME)
    page = build_page(
        bot_username=bot_username,
        privacy_url=cfg.get("privacy_url", "") or "",
        terms_url=cfg.get("terms_url", "") or "",
        channel_url=cfg.get("channel_url", "") or "",
        logo_file=LOGO_NAME if logo_bytes else "",
        tariffs=await site_tariffs(cfg),
        poster_file="og.webp" if og_bytes else "",
    )
    res = await asyncio.to_thread(_deploy_sync, page, og_bytes, logo_bytes)
    if res.get("ok"):
        save_creds(site_deployed_at=datetime.now().strftime("%d.%m.%Y %H:%M"))
    return res


async def issue_cert() -> dict:
    res = await asyncio.to_thread(_cert_sync)
    if res.get("ok"):
        save_creds(site_https=True)
    return res


async def remove_site() -> dict:
    res = await asyncio.to_thread(_remove_sync)
    if res.get("ok"):
        save_creds(site_deployed_at="", site_https=False)
    return res


def pip_path() -> str:
    """pip того же окружения, в котором крутится бот.

    Бот запускается из venv, а привычный «pip install» ставит пакет в
    системный Python — библиотека появляется, но бот её не видит.
    """
    import sys
    from pathlib import Path
    exe = Path(sys.executable)
    for name in ("pip", "pip3"):
        candidate = exe.with_name(name)
        if candidate.exists():
            return str(candidate)
    return f"{exe} -m pip"


def paramiko_ready() -> bool:
    try:
        import paramiko  # noqa: F401
        return True
    except ImportError:
        return False


# ── Экраны админки ────────────────────────────────────────────────────────────

async def handle_site_menu(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    c = creds()
    ready = paramiko_ready()

    if not ready:
        await query.edit_message_text(
            "🌐 <b>Сайт</b>\n\n"
            "Нужна библиотека для SSH. Ставить её надо в тот же Python, "
            "из которого работает бот:\n\n"
            f"<blockquote><code>{escape(pip_path())} install paramiko</code>\n"
            "<code>systemctl restart drebol-vpn</code></blockquote>\n\n"
            "<i>Обычный «pip install» ставит в системный Python, "
            "а бот живёт в своём venv — поэтому и не видит библиотеку.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Проверить снова", callback_data="site_menu"),
                 InlineKeyboardButton("◀️ В админку", callback_data="admin_panel")],
            ]),
        )
        return

    server = (f"<code>{escape(c['host'])}</code> · {escape(c['user'])}"
              if c["host"] else "не задан")
    domain = f"<code>{escape(c['domain'])}</code>" if c["domain"] else "не задан"
    state = (f"🟢 развёрнут {c['deployed_at']}" if c["deployed_at"]
             else "⚪️ ещё не разворачивали")
    url = site_url()

    card = [f"🚀 Статус: <b>{state}</b>",
            f"🖥 Сервер: {server}",
            f"🌍 Домен: {domain}" + ("  ·  🔒 HTTPS" if c.get("https") else ""),
            f"🖼 Логотип: {'свой' if has_logo() else 'нарисованный'}"]
    if url and c["deployed_at"]:
        card.append(f"🔗 {escape(url)}")
    lines = ["🌐 <b>Сайт</b>", "", "<blockquote>" + "\n".join(card) + "</blockquote>",
             "", "<i>Лендинг Drebol VPN: разделы, тарифы из бота, кнопка в Telegram. "
             "Живёт на втором сервере и бота не трогает. Цены и ссылки подставляются "
             "при каждом обновлении.</i>"]

    kb = []
    if configured():
        # главное действие — первым и во всю ширину
        kb.append([InlineKeyboardButton(
            "🔄 Обновить сайт" if c["deployed_at"] else "🚀 Развернуть сайт",
            callback_data="site_deploy")])
    kb.append([InlineKeyboardButton("🖥 Сервер", callback_data="site_server"),
               InlineKeyboardButton("🌍 Домен", callback_data="site_domain"),
               InlineKeyboardButton("🖼 Логотип", callback_data="site_logo")])
    if configured():
        extra = []
        if c["domain"] and c["deployed_at"] and not c["https"]:
            extra.append(InlineKeyboardButton("🔒 Включить HTTPS", callback_data="site_cert"))
        if c["deployed_at"]:
            extra.append(InlineKeyboardButton("🩺 Проверить", callback_data="site_check"))
        if extra:
            kb.append(extra)
        if c["deployed_at"] and url:
            kb.append([InlineKeyboardButton("🔗 Открыть сайт", url=url),
                       InlineKeyboardButton("🗑 Удалить", callback_data="site_delete")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])

    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_site_server(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_SITE_HOST
    context.user_data["state"] = AWAITING_SITE_HOST
    await query.edit_message_text(
        "🖥 <b>Сервер для сайта</b>  ·  <i>шаг 1 из 3</i>\n\n"
        "Пришли IP второго сервера.\n\n"
        "<i>Если SSH на другом порту — <code>1.2.3.4:2222</code></i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Отмена", callback_data="site_menu")],
        ]),
    )


async def handle_site_domain(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_SITE_DOMAIN
    context.user_data["state"] = AWAITING_SITE_DOMAIN
    cur = creds()["domain"]
    await query.edit_message_text(
        "🌍 <b>Домен сайта</b>\n\n"
        f"<blockquote>Сейчас: <b>{escape(cur) if cur else 'не задан'}</b></blockquote>\n\n"
        "Пришли домен без http, например <code>drbl.tech</code>.\n\n"
        "<i>A-запись домена должна смотреть на IP этого сервера. "
        "<code>-</code> — убрать домен.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="site_menu")],
        ]),
    )


async def handle_site_logo(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_SITE_LOGO
    context.user_data["state"] = AWAITING_SITE_LOGO
    cur = "стоит твой файл" if has_logo() else "нарисованный знак"
    await query.edit_message_text(
        "🖼 <b>Логотип сайта</b>\n\n"
        f"<blockquote>Сейчас: <b>{cur}</b></blockquote>\n\n"
        "Пришли картинку — лучше PNG с прозрачным фоном. "
        "Тёмную подложку уберу сам, если её видно.\n\n"
        "<i>После замены нажми «Обновить сайт».</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
        ]),
    )


async def handle_site_deploy(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if not configured():
        await query.answer("Сначала данные сервера", show_alert=True)
        return
    await query.edit_message_text("🚀 <b>Разворачиваю сайт…</b>\n\n<i>Это займёт до минуты.</i>",
                                  parse_mode="HTML")
    me = await context.bot.get_me()
    res = await deploy(me.username)
    if not res.get("ok"):
        await query.edit_message_text(
            "❌ <b>Не получилось развернуть</b>\n\n"
            f"<blockquote><code>{escape(str(res.get('error'))[:500])}</code></blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="site_deploy"),
                 InlineKeyboardButton("◀️ Назад", callback_data="site_menu")],
            ]),
        )
        return
    url = site_url()
    from log_channel import send_log
    await send_log(context.bot, f"🌐 Сайт развёрнут: {escape(url)}")
    await query.edit_message_text(
        f"✅ <b>Сайт развёрнут</b>\n\n<blockquote>🔗 {escape(url)}</blockquote>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Открыть", url=url),
             InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
        ]),
        disable_web_page_preview=True,
    )


async def handle_site_check(query, context):
    """Почему сайт не на HTTPS — по фактам с самого сервера."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text("🩺 Проверяю сервер…")
    res = await diagnose()
    if not res.get("ok"):
        await query.edit_message_text(
            f"❌ <b>Не получилось проверить</b>\n\n"
            f"<blockquote><code>{escape(str(res.get('error'))[:300])}</code></blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")]]),
        )
        return

    d = res["data"]
    domain = d.get("domain", "")
    ip = d.get("ip", "?")
    dns = d.get("dns", "")
    cert = d.get("cert") == "yes"
    conf443 = d.get("nginx443", "0") != "0"
    listen443 = d.get("listen443", "0") != "0"
    https_code = d.get("https", "-")
    http_code = d.get("http", "-")
    dns_ok = bool(dns) and ip != "?" and ip in dns.split()

    def mark(ok):
        return "✅" if ok else "❌"

    lines = ["🩺 <b>Проверка сайта</b>", ""]
    if not domain:
        lines += ["❌ <b>Домен не задан</b>", "",
                  "По IP сертификат не выпустить — HTTPS бывает только с доменом.",
                  "Задай домен, направь его A-запись на "
                  f"<code>{escape(ip)}</code> и включи HTTPS."]
    else:
        lines += [f"🌍 <code>{escape(domain)}</code>  ·  🖥 <code>{escape(ip)}</code>", "",
                  "<blockquote>"
                  f"{mark(dns_ok)} A-запись: <code>{escape(dns or 'не найдена')}</code>\n"
                  f"{mark(cert)} Сертификат на сервере\n"
                  f"{mark(conf443)} 443 в конфиге nginx\n"
                  f"{mark(listen443)} nginx слушает 443\n"
                  f"🌐 Ответ: http <b>{escape(http_code)}</b> · https <b>{escape(https_code)}</b>"
                  "</blockquote>", ""]
        # первая же невыполненная причина и объясняет всё остальное
        if not dns_ok:
            lines += ["<b>Причина: домен не смотрит на этот сервер.</b>",
                      "Поправь A-запись у регистратора на IP выше и подожди "
                      "до часа — потом включи HTTPS."]
        elif not cert:
            lines += ["<b>Причина: сертификата нет.</b>",
                      "Нажми «🔒 Включить HTTPS» — теперь домен смотрит куда надо."]
        elif not conf443 or not listen443:
            lines += ["<b>Причина: сертификат есть, но nginx его не подхватил.</b>",
                      "Нажми «🔒 Включить HTTPS» — конфиг пропишется заново."]
        elif https_code in ("200", "301", "302"):
            lines += ["<b>HTTPS работает.</b>",
                      "Если открывается по http — проверь, что заходишь "
                      f"на <code>https://{escape(domain)}</code>, а не по IP."]
        else:
            lines += ["<b>Сертификат и конфиг на месте, но сайт по https молчит.</b>",
                      "Обычно мешает закрытый 443 порт у хостера или фаервол."]

    kb = [[InlineKeyboardButton("🔒 Включить HTTPS", callback_data="site_cert")]] if domain else []
    kb.append([InlineKeyboardButton("🔄 Проверить снова", callback_data="site_check"),
               InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_site_cert(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text("🔒 <b>Выпускаю сертификат…</b>\n\n<i>Это займёт до минуты.</i>",
                                  parse_mode="HTML")
    res = await issue_cert()
    if not res.get("ok"):
        await query.edit_message_text(
            "❌ <b>Сертификат не выпустился</b>\n\n"
            f"<blockquote><code>{escape(str(res.get('error'))[:500])}</code></blockquote>\n\n"
            "<i>Обычно причина одна: домен ещё не смотрит на этот сервер.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="site_cert"),
                 InlineKeyboardButton("◀️ Назад", callback_data="site_menu")],
            ]),
        )
        return
    await query.answer("HTTPS включён")
    await handle_site_check(query, context)


async def handle_site_delete(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text("🗑 Удаляю сайт…")
    res = await remove_site()
    if not res.get("ok"):
        await query.edit_message_text(
            f"❌ <b>Не получилось удалить</b>\n\n"
            f"<blockquote><code>{escape(str(res.get('error'))[:400])}</code></blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="site_menu")],
            ]),
        )
        return
    await query.answer("Сайт удалён")
    await handle_site_menu(query)
