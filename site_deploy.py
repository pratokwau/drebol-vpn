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


def _deploy_sync(page: str, og_bytes: bytes) -> dict:
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
        finally:
            sftp.close()

        server_name = c["domain"] or "_"
        install = f"""set -e
mv /tmp/drebol_index.html {WEB_ROOT}/index.html
mv /tmp/drebol_og.webp {WEB_ROOT}/og.webp
chmod 644 {WEB_ROOT}/index.html {WEB_ROOT}/og.webp
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


async def deploy(bot_username: str) -> dict:
    """Собирает страницу и раскатывает её на сервер."""
    from site_page import build_page
    cfg = load_config()
    page = build_page(
        bot_username=bot_username,
        privacy_url=cfg.get("privacy_url", "") or "",
        terms_url=cfg.get("terms_url", "") or "",
        channel_url=cfg.get("channel_url", "") or "",
    )
    og_path = os.path.join(PROJECT_DIR, "assets", "og.webp")
    try:
        with open(og_path, "rb") as f:
            og_bytes = f.read()
    except OSError:
        og_bytes = b""
    res = await asyncio.to_thread(_deploy_sync, page, og_bytes)
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
            "🌐 <b>Сайт-визитка</b>\n\n"
            "Нужна библиотека для SSH. На сервере бота выполни:\n"
            "<code>pip install paramiko</code>\n"
            "и перезапусти бота.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
            ]),
        )
        return

    server = (f"<code>{escape(c['host'])}</code> · {escape(c['user'])}"
              if c["host"] else "не задан")
    domain = f"<code>{escape(c['domain'])}</code>" if c["domain"] else "не задан"
    state = f"развёрнут {c['deployed_at']}" if c["deployed_at"] else "ещё не разворачивали"
    url = site_url()

    lines = ["🌐 <b>Сайт-визитка</b>", "",
             f"🖥 Сервер: {server}",
             f"🌍 Домен: {domain}",
             f"🚀 Статус: {state}"]
    if url and c["deployed_at"]:
        lines.append(f"🔗 {escape(url)}")
    lines += ["", "<i>Страница с логотипом, анимацией и кнопкой в Telegram. "
              "Разворачивается на втором сервере, бота не трогает.</i>"]

    kb = [[InlineKeyboardButton("🖥 Данные сервера", callback_data="site_server"),
           InlineKeyboardButton("🌍 Домен", callback_data="site_domain")]]
    if configured():
        kb.append([InlineKeyboardButton(
            "🔄 Обновить сайт" if c["deployed_at"] else "🚀 Развернуть сайт",
            callback_data="site_deploy")])
        if c["domain"] and c["deployed_at"] and not c["https"]:
            kb.append([InlineKeyboardButton("🔒 Включить HTTPS", callback_data="site_cert")])
        if c["deployed_at"] and url:
            kb.append([InlineKeyboardButton("🔗 Открыть сайт", url=url)])
            kb.append([InlineKeyboardButton("🗑 Удалить сайт", callback_data="site_delete")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])

    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_site_server(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_SITE_HOST
    context.user_data["state"] = AWAITING_SITE_HOST
    await query.edit_message_text(
        "🖥 <b>Сервер для сайта</b> · шаг 1 из 3\n\n"
        "Пришли IP второго сервера.\n"
        "Если SSH на другом порту — <code>1.2.3.4:2222</code>",
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
        f"Сейчас: <b>{escape(cur) if cur else 'не задан'}</b>\n\n"
        "Пришли домен без http, например <code>drbl.tech</code>.\n"
        "A-запись домена должна смотреть на IP этого сервера.\n"
        "<code>-</code> — убрать домен.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="site_menu")],
        ]),
    )


async def handle_site_deploy(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if not configured():
        await query.answer("Сначала данные сервера", show_alert=True)
        return
    await query.edit_message_text("🚀 Разворачиваю сайт… это займёт до минуты.")
    me = await context.bot.get_me()
    res = await deploy(me.username)
    if not res.get("ok"):
        await query.edit_message_text(
            "❌ <b>Не получилось</b>\n\n"
            f"<code>{escape(str(res.get('error'))[:500])}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="site_deploy")],
                [InlineKeyboardButton("◀️ Назад", callback_data="site_menu")],
            ]),
        )
        return
    url = site_url()
    from log_channel import send_log
    await send_log(context.bot, f"🌐 Сайт развёрнут: {escape(url)}")
    await query.edit_message_text(
        f"✅ <b>Сайт развёрнут</b>\n\n🔗 {escape(url)}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Открыть", url=url)],
            [InlineKeyboardButton("◀️ К сайту", callback_data="site_menu")],
        ]),
        disable_web_page_preview=True,
    )


async def handle_site_cert(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text("🔒 Выпускаю сертификат… до минуты.")
    res = await issue_cert()
    if not res.get("ok"):
        await query.edit_message_text(
            "❌ <b>Сертификат не выпустился</b>\n\n"
            f"<code>{escape(str(res.get('error'))[:500])}</code>\n\n"
            "Обычно причина одна: домен ещё не смотрит на этот сервер.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="site_cert")],
                [InlineKeyboardButton("◀️ Назад", callback_data="site_menu")],
            ]),
        )
        return
    await query.answer("HTTPS включён")
    await handle_site_menu(query)


async def handle_site_delete(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text("🗑 Удаляю сайт…")
    res = await remove_site()
    if not res.get("ok"):
        await query.edit_message_text(
            f"❌ <b>Не получилось</b>\n\n<code>{escape(str(res.get('error'))[:400])}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="site_menu")],
            ]),
        )
        return
    await query.answer("Сайт удалён")
    await handle_site_menu(query)
