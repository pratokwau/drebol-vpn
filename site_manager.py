"""Управление сайтом-визиткой с сервера бота.

Разворачивает статику в /var/www/<домен>, генерирует конфиг nginx,
выпускает сертификат через certbot и включает/выключает сайт.

Все команды запускаются списком аргументов, без shell, а домен проходит
строгую проверку — значения из чата не должны попадать в командную строку
как есть.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from datetime import datetime

from config import INSTALL_DIR, load_config, save_config

SITE_SRC = os.path.join(INSTALL_DIR, "site")
WEBROOT_BASE = "/var/www"
NGINX_SITES_AVAILABLE = "/etc/nginx/sites-available"
NGINX_SITES_ENABLED = "/etc/nginx/sites-enabled"
NGINX_CONF_D = "/etc/nginx/conf.d"
LE_LIVE = "/etc/letsencrypt/live"

# Домен: метки из букв/цифр/дефисов, зона от 2 букв. Без схем, путей и пробелов.
DOMAIN_RE = re.compile(
    r"^(?=.{4,253}$)(?!-)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

NGINX_TEMPLATE = """# Создано ботом Drebol VPN. Правки будут перезаписаны при активации.
server {{
    listen 80;
    listen [::]:80;
    server_name {domain};

    root {webroot};
    index index.html;

    access_log /var/log/nginx/{domain}.access.log;
    error_log  /var/log/nginx/{domain}.error.log;

    location /.well-known/acme-challenge/ {{
        root {webroot};
        allow all;
    }}

    location = /config.js {{
        add_header Cache-Control "no-store";
    }}

    location ~* \\.(css|js|svg|png|jpg|jpeg|webp|ico|woff2?)$ {{
        expires 7d;
        add_header Cache-Control "public";
    }}

    location / {{
        try_files $uri $uri/ /index.html;
    }}

    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options SAMEORIGIN;
    add_header Referrer-Policy strict-origin-when-cross-origin;

    gzip on;
    gzip_types text/css application/javascript image/svg+xml;
    gzip_min_length 512;
}}
"""


def valid_domain(domain: str) -> bool:
    return bool(DOMAIN_RE.match((domain or "").strip().lower()))


def normalize_domain(raw: str) -> str:
    """Приводит ввод к голому домену: срезает схему, www, путь и порт."""
    d = (raw or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0]
    d = d.split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    return d.strip().strip(".")


async def run(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    """Запускает команду без shell. Возвращает (код, вывод)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return 127, f"команда не найдена: {cmd[0]}"
    except Exception as e:
        return 1, str(e)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return 124, f"превышено время ожидания ({timeout} с)"
    return proc.returncode, (out or b"").decode("utf-8", "replace").strip()


def _nginx_layout() -> tuple[str, str | None]:
    """Куда класть конфиг: (каталог_конфигов, каталог_симлинков или None)."""
    if os.path.isdir(NGINX_SITES_AVAILABLE) and os.path.isdir(NGINX_SITES_ENABLED):
        return NGINX_SITES_AVAILABLE, NGINX_SITES_ENABLED
    return NGINX_CONF_D, None


def _conf_paths(domain: str) -> tuple[str, str | None]:
    avail_dir, enabled_dir = _nginx_layout()
    conf = os.path.join(avail_dir, f"{domain}.conf")
    link = os.path.join(enabled_dir, f"{domain}.conf") if enabled_dir else None
    return conf, link


def webroot_for(domain: str) -> str:
    return os.path.join(WEBROOT_BASE, domain)


async def check_env() -> dict:
    """Что есть на сервере и чего не хватает."""
    is_root = (os.geteuid() == 0) if hasattr(os, "geteuid") else False
    nginx = shutil.which("nginx")
    certbot = shutil.which("certbot")
    rc, _ = await run(["systemctl", "is-active", "nginx"], timeout=15)
    return {
        "is_root": is_root,
        "nginx": bool(nginx),
        "certbot": bool(certbot),
        "nginx_running": rc == 0,
        "site_src": os.path.isdir(SITE_SRC),
    }


def build_config_js() -> str:
    """config.js для витрины — из настроек бота."""
    cfg = load_config()
    bot_username = (cfg.get("bot_username") or "").lstrip("@")
    data = {
        "siteName": cfg.get("site_name") or "Drebol VPN",
        "botUrl": f"https://t.me/{bot_username}" if bot_username else "",
        "privacyUrl": cfg.get("privacy_url") or "",
        "termsUrl": cfg.get("terms_url") or "",
    }
    return (
        "/* Сгенерировано ботом Drebol VPN. Правки будут затёрты. */\n"
        "window.SITE_CONFIG = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
    )


async def sync_files(domain: str) -> tuple[bool, str]:
    """Копирует статику в веб-корень и обновляет config.js."""
    if not os.path.isdir(SITE_SRC):
        return False, f"нет каталога сайта: {SITE_SRC}"
    webroot = webroot_for(domain)
    try:
        os.makedirs(webroot, exist_ok=True)
        for name in os.listdir(SITE_SRC):
            src = os.path.join(SITE_SRC, name)
            if not os.path.isfile(src):
                continue
            shutil.copy2(src, os.path.join(webroot, name))
        with open(os.path.join(webroot, "config.js"), "w", encoding="utf-8") as f:
            f.write(build_config_js())
        # nginx читает файлы от www-data
        await run(["chmod", "-R", "a+rX", webroot], timeout=30)
    except PermissionError:
        return False, "нет прав на запись в /var/www (бот должен работать от root)"
    except Exception as e:
        return False, str(e)
    return True, webroot


async def write_nginx_conf(domain: str) -> tuple[bool, str]:
    conf_path, link_path = _conf_paths(domain)
    body = NGINX_TEMPLATE.format(domain=domain, webroot=webroot_for(domain))
    try:
        os.makedirs(os.path.dirname(conf_path), exist_ok=True)
        with open(conf_path, "w", encoding="utf-8") as f:
            f.write(body)
        if link_path and not os.path.islink(link_path):
            if os.path.exists(link_path):
                os.remove(link_path)
            os.symlink(conf_path, link_path)
    except PermissionError:
        return False, "нет прав на запись в /etc/nginx (бот должен работать от root)"
    except Exception as e:
        return False, str(e)
    return True, conf_path


async def nginx_test_reload() -> tuple[bool, str]:
    rc, out = await run(["nginx", "-t"], timeout=30)
    if rc != 0:
        return False, out
    rc, out = await run(["systemctl", "reload", "nginx"], timeout=30)
    if rc != 0:
        rc2, out2 = await run(["systemctl", "restart", "nginx"], timeout=45)
        if rc2 != 0:
            return False, out2 or out
    return True, "ok"


async def issue_cert(domain: str) -> tuple[bool, str]:
    """Выпускает сертификат Let's Encrypt через плагин nginx."""
    if not shutil.which("certbot"):
        return False, "certbot не установлен"
    cfg = load_config()
    email = (cfg.get("site_email") or "").strip()
    cmd = [
        "certbot", "--nginx",
        "-d", domain,
        "--non-interactive", "--agree-tos",
        "--redirect", "--keep-until-expiring",
    ]
    cmd += ["-m", email] if email else ["--register-unsafely-without-email"]
    rc, out = await run(cmd, timeout=300)
    if rc != 0:
        tail = "\n".join(out.splitlines()[-6:]) if out else "неизвестная ошибка"
        return False, tail
    return True, "ok"


def cert_expiry(domain: str) -> str | None:
    path = os.path.join(LE_LIVE, domain, "cert.pem")
    if not os.path.isfile(path):
        return None
    try:
        import ssl
        raw = ssl._ssl._test_decode_cert(path)  # type: ignore[attr-defined]
        return raw.get("notAfter")
    except Exception:
        return None


async def activate(domain: str, progress=None) -> dict:
    """Полная активация: файлы → nginx → сертификат."""
    async def say(text):
        if progress:
            await progress(text)

    if not valid_domain(domain):
        return {"ok": False, "error": "Некорректный домен."}

    env = await check_env()
    if not env["nginx"]:
        return {"ok": False, "error": "nginx не установлен", "hint": "apt install -y nginx"}
    if not env["site_src"]:
        return {"ok": False, "error": f"нет каталога {SITE_SRC}"}

    await say("📁 Копирую файлы сайта...")
    ok, res = await sync_files(domain)
    if not ok:
        return {"ok": False, "error": res}

    await say("⚙️ Настраиваю nginx...")
    ok, res = await write_nginx_conf(domain)
    if not ok:
        return {"ok": False, "error": res}

    ok, res = await nginx_test_reload()
    if not ok:
        return {"ok": False, "error": f"nginx не принял конфиг:\n{res[:500]}"}

    cert_ok, cert_msg = False, "пропущен"
    if env["certbot"]:
        await say("🔐 Выпускаю сертификат (до минуты)...")
        cert_ok, cert_msg = await issue_cert(domain)
        if cert_ok:
            await nginx_test_reload()
    else:
        cert_msg = "certbot не установлен"

    cfg = load_config()
    cfg["site_domain"] = domain
    cfg["site_activated"] = True
    cfg["site_enabled"] = True
    cfg["site_activated_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    save_config(cfg)

    return {
        "ok": True,
        "domain": domain,
        "https": cert_ok,
        "cert_msg": cert_msg,
        "url": f"{'https' if cert_ok else 'http'}://{domain}",
    }


async def set_enabled(enabled: bool) -> dict:
    """Включает или выключает отдачу сайта, не удаляя конфиг."""
    cfg = load_config()
    domain = cfg.get("site_domain")
    if not domain or not valid_domain(domain):
        return {"ok": False, "error": "домен не задан"}

    conf_path, link_path = _conf_paths(domain)
    if not os.path.exists(conf_path) and not os.path.exists(conf_path + ".disabled"):
        return {"ok": False, "error": "конфиг nginx не найден, сначала активируй сайт"}

    try:
        if link_path:
            # раскладка sites-available / sites-enabled — управляем симлинком
            if enabled:
                if not os.path.islink(link_path):
                    os.symlink(conf_path, link_path)
            elif os.path.islink(link_path):
                os.remove(link_path)
        else:
            # раскладка conf.d — управляем расширением файла
            disabled = conf_path + ".disabled"
            if enabled and os.path.exists(disabled):
                os.replace(disabled, conf_path)
            elif not enabled and os.path.exists(conf_path):
                os.replace(conf_path, disabled)
    except PermissionError:
        return {"ok": False, "error": "нет прав на /etc/nginx (нужен root)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    ok, res = await nginx_test_reload()
    if not ok:
        return {"ok": False, "error": f"nginx не принял конфиг:\n{res[:400]}"}

    cfg["site_enabled"] = enabled
    save_config(cfg)
    return {"ok": True, "enabled": enabled}


async def status() -> dict:
    cfg = load_config()
    domain = cfg.get("site_domain") or ""
    env = await check_env()

    conf_exists = served = False
    if domain and valid_domain(domain):
        conf_path, link_path = _conf_paths(domain)
        conf_exists = os.path.exists(conf_path) or os.path.exists(conf_path + ".disabled")
        served = os.path.islink(link_path) if link_path else os.path.exists(conf_path)

    return {
        "domain": domain,
        "activated": bool(cfg.get("site_activated")),
        "enabled": bool(cfg.get("site_enabled")),
        "conf_exists": conf_exists,
        "served": served,
        "cert_until": cert_expiry(domain) if domain else None,
        "activated_at": cfg.get("site_activated_at"),
        "webroot": webroot_for(domain) if domain else "",
        **env,
    }
