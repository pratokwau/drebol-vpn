"""Веб-консоль серверов Drebol VPN и токен-вход Muse.

Часть 1 — онлайн-консоль (раздел «🖥 Консоль» веб-админки).
Терминал в браузере: WebSocket ↔ PTY на главном сервере. Для главного
сервера — локальный bash, для остальных — ssh с главного сервера по
отдельному ключу консоли (config `console_key_path`, по умолчанию
/root/drebol-vpn/.console_key; пара генерируется при первом обращении
и никогда не перезаписывается). Транспорт — только stdlib: pty +
asyncio subprocess, без новых зависимостей.

Доступ — роли mark и muse (muse — по прямому заказу Mark: консоль
нужна и ассистенту). Остальных сюда не пускает сама сессия: _actor()
отдаёт только эти две роли. Ограничения: одна активная сессия на
аккаунт (новая вытесняет старую), простой 10 минут, предел сессии
60 минут, kill-switch `console_enabled` (false в конфиге — все
эндпоинты недоступны). Подключения и отключения пишутся в тот же
журнал действий, что и всё в админке (_audit → log_activity).

Часть 2 — вход Muse по секретной ссылке: GET /admin/muse-login?t=…
Токен — config `muse_access_token` (значение задаёт Mark в config.json
на сервере; пустой/отсутствующий ключ — эндпоинт всегда 404). При
совпадении (constant-time) заводится обычная веб-сессия аккаунта muse
и редирект на /admin/. Токен нигде не логируется. Тот же обработчик
доступен и как /api/admin/muse-login — этот путь проксируется nginx'ом
сайта, а чистый /admin/ на сайте статический.
"""

from __future__ import annotations

import asyncio
import fcntl
import hmac
import json
import logging
import os
import pty
import struct
import termios
import time

from aiohttp import web

from web.admin_api import (
    _actor,
    _audit,
    _check_origin,
    _client_ip,
    _set_session_cookies,
    require_mark,
)

IDLE_SECONDS = 600          # простой: 10 минут без ввода
MAX_SECONDS = 3600          # предел одной сессии: 60 минут
DEFAULT_KEY_PATH = "/root/drebol-vpn/.console_key"

# Дефолтный парк серверов; config `console_servers` (список словарей
# {id, name, host, user, port, local}) заменяет его целиком.
# Финляндии нет и не будет: сервер умирает 2026-11-24.
DEFAULT_SERVERS = [
    {"id": "main", "name": "🇩🇪 Главная", "local": True},
    {"id": "latvia", "name": "🇱🇻 Латвия (мост)",
     "host": "31.59.168.90", "user": "root", "port": 22},
    {"id": "sweden", "name": "🇸🇪 Швеция",
     "host": "81.90.21.84", "user": "root", "port": 22},
    {"id": "oblako", "name": "☁️ Oblako (мост)",
     "host": "187.54.0.243", "user": "root", "port": 22},
]

# Одна активная консоль на аккаунт: ключ — "mark:<tg_id>"/"muse:<id>",
# значение — dict с полями ws/proc/started (для вытеснения старой).
_ACTIVE: dict = {}


def _load_cfg() -> dict:
    from config import load_config
    return load_config() or {}


def _console_enabled(cfg: dict) -> bool:
    """Kill-switch: выключено только явным false в конфиге."""
    return cfg.get("console_enabled") is not False


def _key_path(cfg: dict) -> str:
    return str(cfg.get("console_key_path") or DEFAULT_KEY_PATH)


def _servers(cfg: dict) -> list:
    """Список серверов из конфига или дефолт. Битые записи пропускаем,
    чтобы один кривой словарь не уронил весь раздел."""
    raw = cfg.get("console_servers")
    if not isinstance(raw, list):
        raw = DEFAULT_SERVERS
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        sid = str(item.get("id") or f"s{i}").strip() or f"s{i}"
        if item.get("local"):
            out.append({"id": sid, "name": name, "local": True})
            continue
        host = str(item.get("host") or "").strip()
        if not host:
            continue
        try:
            port = int(item.get("port") or 22)
        except (TypeError, ValueError):
            port = 22
        out.append({"id": sid, "name": name, "local": False,
                    "host": host,
                    "user": str(item.get("user") or "root").strip() or "root",
                    "port": port})
    return out


def _server_target(srv: dict) -> str:
    if srv["local"]:
        return "локальная оболочка главного сервера"
    return f"{srv['user']}@{srv['host']}:{srv['port']}"


# ── Ключ консоли ─────────────────────────────────────────────────────────────

async def _run_quiet(argv: list) -> tuple:
    """(returncode, stdout) подпроцесса; (-1, '') при любой ошибке."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        return proc.returncode or 0, out.decode("utf-8", "replace").strip()
    except Exception as ex:
        logging.error("консоль: %s: %s", argv[0], ex)
        return -1, ""


async def _ensure_keypair(cfg: dict):
    """Гарантирует ed25519-пару консоли. Возвращает (priv_path, pubkey)
    или (priv_path, None), если создать/прочитать ключ не удалось.
    Существующий ключ никогда не перезаписывается."""
    priv = _key_path(cfg)
    pub_path = priv + ".pub"
    if os.path.exists(pub_path):
        try:
            with open(pub_path, encoding="utf-8") as fh:
                pub = fh.read().strip()
            if pub:
                return priv, pub
        except OSError:
            pass
    if not os.path.exists(priv):
        parent = os.path.dirname(priv)
        try:
            if parent:
                os.makedirs(parent, exist_ok=True)
        except OSError as ex:
            logging.error("консоль: каталог ключа: %s", ex)
            return priv, None
        code, _ = await _run_quiet(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", priv,
             "-C", "drebol-console"])
        if code != 0 or not os.path.exists(priv):
            return priv, None
    # Приватный есть, публичный потерян — выводим его из приватного.
    code, pub = await _run_quiet(["ssh-keygen", "-y", "-f", priv])
    if code == 0 and pub:
        try:
            with open(pub_path, "w", encoding="utf-8") as fh:
                fh.write(pub + " drebol-console\n")
        except OSError:
            pass
        return priv, pub + " drebol-console"
    return priv, None


# ── HTTP-эндпоинты ───────────────────────────────────────────────────────────

async def console_servers(request):
    """Список серверов для UI + флаг kill-switch'а."""
    try:
        actor = await _actor(request)
    except Exception:
        actor = None
    if not actor:
        return web.json_response({"error": "no_session"}, status=401)
    cfg = _load_cfg()
    enabled = _console_enabled(cfg)
    servers = []
    if enabled:
        servers = [{"id": s["id"], "name": s["name"], "local": s["local"],
                    "target": _server_target(s)} for s in _servers(cfg)]
    return web.json_response({"enabled": enabled, "servers": servers})


async def console_pubkey(request):
    """Публичный ключ консоли — только Mark: он добавляет его в
    authorized_keys на серверах руками."""
    try:
        actor = await _actor(request)
    except Exception:
        actor = None
    if not actor:
        return web.json_response({"error": "no_session"}, status=401)
    if not require_mark(actor):
        return web.json_response({"error": "mark_only"}, status=403)
    cfg = _load_cfg()
    if not _console_enabled(cfg):
        raise web.HTTPNotFound()
    priv, pub = await _ensure_keypair(cfg)
    if not pub:
        return web.json_response({"error": "keygen_failed"}, status=500)
    return web.json_response({"pubkey": pub, "key_path": priv})


# ── WebSocket-терминал ───────────────────────────────────────────────────────

def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ,
                    struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0))
    except OSError:
        pass


async def console_ws(request):
    actor = await _actor(request)
    if not actor:
        return web.json_response({"error": "no_session"}, status=401)
    if not _check_origin(request):
        return web.json_response({"error": "bad_origin"}, status=403)
    cfg = _load_cfg()
    if not _console_enabled(cfg):
        raise web.HTTPNotFound()
    srv = None
    wanted = request.query.get("server") or ""
    for cand in _servers(cfg):
        if cand["id"] == wanted:
            srv = cand
            break
    if srv is None:
        raise web.HTTPNotFound()

    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    if srv["local"]:
        argv = ["/bin/bash", "-l"]
    else:
        priv, pub = await _ensure_keypair(cfg)
        if not pub:
            return web.json_response({"error": "keygen_failed"}, status=500)
        argv = ["ssh", "-tt", "-i", priv,
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ServerAliveInterval=30",
                "-o", "ConnectTimeout=15",
                "-p", str(srv["port"]), f"{srv['user']}@{srv['host']}"]

    actor_key = f"{actor['kind']}:" \
        f"{actor.get('tg_id') or actor.get('account_id')}"
    old = _ACTIVE.pop(actor_key, None)
    if old is not None:
        try:
            await old["ws"].close(code=4001, message=b"replaced")
        except Exception:
            pass

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    home = os.path.expanduser("~") or "/"
    master = slave = None
    proc = None
    try:
        master, slave = pty.openpty()
        _set_winsize(master, 24, 80)
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=slave, stdout=slave, stderr=slave, env=env,
            cwd=home if os.path.isdir(home) else "/",
            start_new_session=True)
    except Exception as ex:
        logging.error("консоль: spawn %s: %s", argv[0], ex)
        await ws.send_str("\r\n[не удалось запустить оболочку]\r\n")
        await ws.close()
        return ws
    finally:
        if slave is not None:
            try:
                os.close(slave)
            except OSError:
                pass

    session = {"ws": ws, "proc": proc, "started": time.time()}
    _ACTIVE[actor_key] = session
    started = session["started"]
    last_input = [time.time()]
    try:
        await _audit(actor, "console_open", f"server={srv['name']}")
    except Exception:
        pass

    loop = asyncio.get_running_loop()
    out_queue: asyncio.Queue = asyncio.Queue()
    os.set_blocking(master, False)

    def _on_readable():
        try:
            data = os.read(master, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if data:
            out_queue.put_nowait(data)
        else:
            try:
                loop.remove_reader(master)
            except Exception:
                pass
            out_queue.put_nowait(None)

    loop.add_reader(master, _on_readable)

    async def _sender():
        try:
            while True:
                data = await out_queue.get()
                if data is None:
                    return
                await ws.send_bytes(data)
        finally:
            # Оболочка вышла — закрываем WS, чтобы основной цикл
            # (async for по ws) завершился и сессия убралась.
            try:
                await ws.close()
            except Exception:
                pass

    async def _watchdog():
        while True:
            await asyncio.sleep(10)
            now = time.time()
            note = None
            if now - last_input[0] > IDLE_SECONDS:
                note = "\r\n[сессия закрыта: 10 минут без ввода]\r\n"
            elif now - started > MAX_SECONDS:
                note = "\r\n[сессия закрыта: предел 60 минут]\r\n"
            if note is not None:
                try:
                    await ws.send_str(note)
                except Exception:
                    pass
                try:
                    await ws.close()
                except Exception:
                    pass
                return

    sender_task = asyncio.ensure_future(_sender())
    watchdog_task = asyncio.ensure_future(_watchdog())
    try:
        async for msg in ws:
            last_input[0] = time.time()
            if msg.type == web.WSMsgType.BINARY:
                try:
                    os.write(master, msg.data)
                except (BlockingIOError, OSError):
                    pass
            elif msg.type == web.WSMsgType.TEXT:
                try:
                    ctl = json.loads(msg.data)
                except (ValueError, TypeError):
                    ctl = None
                if isinstance(ctl, dict) and ctl.get("type") == "resize":
                    try:
                        _set_winsize(master, int(ctl.get("rows") or 24),
                                     int(ctl.get("cols") or 80))
                    except (TypeError, ValueError):
                        pass
                # {"type": "ping"} и прочий текст — просто активность.
            elif msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED,
                              web.WSMsgType.ERROR):
                break
    finally:
        for task in (sender_task, watchdog_task):
            task.cancel()
        try:
            loop.remove_reader(master)
        except Exception:
            pass
        if _ACTIVE.get(actor_key) is session:
            _ACTIVE.pop(actor_key, None)
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        try:
            os.close(master)
        except OSError:
            pass
        try:
            await ws.close()
        except Exception:
            pass
        try:
            await _audit(actor, "console_close",
                         f"server={srv['name']}; "
                         f"duration={int(time.time() - started)}s")
        except Exception:
            pass
    return ws


# ── Токен-вход Muse ──────────────────────────────────────────────────────────

async def muse_login(request):
    """Вход аккаунта muse по секретной ссылке: ?t=<muse_access_token>.

    Совпадение — constant-time; успех — обычная веб-сессия и редирект
    на /admin/. Всё остальное — 404, токен нигде не логируется. Если
    ключ в конфиге не задан — эндпоинт всегда 404."""
    cfg = _load_cfg()
    expected = str(cfg.get("muse_access_token") or "")
    provided = str(request.query.get("t") or "")
    if (not expected or not provided
            or not hmac.compare_digest(provided.encode("utf-8"),
                                       expected.encode("utf-8"))):
        raise web.HTTPNotFound()
    from core.database import (
        admin_account_list,
        admin_account_touch_login,
        admin_session_new,
    )
    target = None
    for row in await admin_account_list():
        # (id, email, role, created_by, created_at, last_login, disabled)
        if not row[6]:
            target = row
            break
    if target is None:
        raise web.HTTPNotFound()
    account_id = int(target[0])
    await admin_account_touch_login(account_id)
    token = await admin_session_new(
        account_id, None, _client_ip(request),
        request.headers.get("User-Agent", ""))
    actor = {"kind": "muse", "account_id": account_id, "email": target[1]}
    try:
        await _audit(actor, "login", "token link")
    except Exception:
        pass
    resp = web.HTTPFound("/admin/")
    _set_session_cookies(resp, request, token)
    return resp


# ── Регистрация ──────────────────────────────────────────────────────────────

def register(app) -> None:
    """Маршруты в админ-подприложение (пути без /api/admin)."""
    app.router.add_get("/console/servers", console_servers)
    app.router.add_get("/console/pubkey", console_pubkey)
    app.router.add_get("/console/ws", console_ws)
    # Тот же вход, что и /admin/muse-login, но этот путь проксирует
    # nginx сайта (/api/admin/), чистый /admin/ на сайте — статика.
    app.router.add_get("/muse-login", muse_login)


def register_top(app) -> None:
    """Маршруты в главное приложение webapi: чистый /admin/muse-login
    (регистрировать ДО /admin/{tail:.*})."""
    app.router.add_get("/admin/muse-login", muse_login)
