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


# Страница-переходник: Telegram пускает в кнопки только http(s), а приложения
# ловят свои схемы (happ://, incy://). Открывается по ссылке из бота и сразу
# уводит в приложение; если оно не установлено, остаётся ссылка и инструкция.
ADD_PAGE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Добавляем подписку</title>
<style>
 :root { color-scheme: dark; }
 body { margin:0; min-height:100vh; display:flex; align-items:center;
        justify-content:center; background:#0e1117; color:#e7e9ee;
        font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
 .card { max-width:420px; padding:28px 22px; text-align:center; }
 h1 { font-size:20px; margin:0 0 10px; }
 p { color:#9aa4b2; margin:0 0 18px; }
 a.btn { display:block; padding:14px 18px; margin:10px 0; border-radius:12px;
         background:#2f81f7; color:#fff; text-decoration:none; font-weight:600; }
 a.ghost { background:#1c2128; color:#e7e9ee; }
 code { display:block; word-break:break-all; background:#1c2128; color:#9aa4b2;
        padding:12px; border-radius:10px; font-size:13px; margin-top:16px; }
</style></head>
<body><div class="card">
 <h1 id="head">Открываем приложение…</h1>
 <p id="hint">Если ничего не произошло — нажмите кнопку ниже.</p>
 <a class="btn" id="go" href="#">Добавить подписку</a>
 <a class="ghost btn" id="store" href="#" style="display:none">Установить приложение</a>
 <code id="raw"></code>
</div>
<script>
 var q = new URLSearchParams(location.search);
 var app = (q.get("app") || "happ").toLowerCase();
 var sub = q.get("u") || "";
 var apps = {
   happ: {name: "Happ", scheme: "happ://add/",
          store: "https://apps.apple.com/us/app/happ-proxy-utility/id6504287215"},
   incy: {name: "INCY", scheme: "incy://add/",
          store: "https://apps.apple.com/ru/app/incy/id6756943388"}
 };
 var cfg = apps[app] || apps.happ;
 var link = sub ? cfg.scheme + sub : "";
 document.getElementById("head").textContent = "Добавляем подписку в " + cfg.name;
 var go = document.getElementById("go");
 go.textContent = "Открыть " + cfg.name;
 go.href = link || "#";
 var store = document.getElementById("store");
 store.href = cfg.store;
 store.textContent = "Установить " + cfg.name;
 document.getElementById("raw").textContent = sub;
 if (link) {
   setTimeout(function () { location.href = link; }, 100);
   setTimeout(function () { store.style.display = "block"; }, 2500);
 } else {
   document.getElementById("head").textContent = "Ссылка не передана";
   document.getElementById("hint").textContent = "Вернитесь в бот и нажмите кнопку ещё раз.";
 }
</script></body></html>
"""


# Кабинет: статическая страница, которая ходит в API бота. Вход двумя путями —
# кнопка Telegram на сайте и initData, если страницу открыли как мини-приложение.
# Страница кабинета оформлена как главная: тот же фон-«шёлк», Manrope,
# белые кнопки-пилюли и стеклянные карточки. Сырая строка — чтобы
# обратные слеши в JS доходили до браузера как есть.
CABINET_PAGE = r"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<meta name="theme-color" content="#05070c">
<title>Личный кабинет · Drebol VPN</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cg fill='none' stroke='white' stroke-width='7'%3E%3Ccircle cx='50' cy='50' r='40'/%3E%3Cellipse cx='50' cy='50' rx='40' ry='13'/%3E%3C/g%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
 /* Цвета, шрифт и «шёлк» — как на главной странице сайта */
 :root {
   color-scheme: dark;
   --bg: #05070c; --ink: #ffffff;
   --muted: rgba(255,255,255,.64); --soft: rgba(255,255,255,.52);
   --line: rgba(255,255,255,.10); --card: rgba(255,255,255,.035);
   --accent: #4f8cff; --accent-soft: rgba(79,140,255,.14);
   --ok: #4ade80; --warn: #fbbf24; --bad: #f87171;
 }
 * { box-sizing: border-box; }
 body { margin:0; min-height:100vh; background:var(--bg); color:var(--ink); overflow-x:hidden;
        font:16px/1.55 Manrope,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
        -webkit-font-smoothing:antialiased; }
 a { color:inherit; text-decoration:none; }
 h1, h2, p { margin:0; }

 .bg { position:fixed; inset:0; z-index:0; pointer-events:none; overflow:hidden; }
 .silk { position:absolute; inset:-20%; filter:blur(60px); opacity:.85; }
 .silk span { position:absolute; border-radius:50%;
   background:radial-gradient(circle at 30% 30%, rgba(79,140,255,.5), transparent 60%);
   animation:drift 26s ease-in-out infinite; }
 .silk span:nth-child(1) { width:60vmax; height:60vmax; top:-15%; left:-10%; }
 .silk span:nth-child(2) { width:50vmax; height:50vmax; bottom:-20%; right:-15%;
   background:radial-gradient(circle at 60% 40%, rgba(120,140,190,.38), transparent 62%);
   animation-duration:32s; animation-delay:-8s; }
 @keyframes drift {
   0%,100% { transform:translate3d(0,0,0) scale(1); }
   33% { transform:translate3d(5vw,-4vh,0) scale(1.1); }
   66% { transform:translate3d(-4vw,5vh,0) scale(.95); } }
 .vignette { position:absolute; inset:0;
   background:radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,.7) 100%); }

 .wrap { position:relative; z-index:1; max-width:560px; margin:0 auto;
         padding:18px 16px 48px; padding-top:max(18px, env(safe-area-inset-top)); }

 /* шапка */
 .top { display:flex; align-items:center; justify-content:space-between; gap:12px;
        min-height:48px; margin-bottom:22px; }
 .brand { display:flex; align-items:center; min-height:44px; }
 .brand img { height:26px; width:auto; display:block; }
 .logo { display:none; align-items:center; gap:10px; font-weight:800; font-size:22px; letter-spacing:-.02em; }
 .logo svg { width:28px; height:28px; }
 .logo svg * { fill:none; stroke:#fff; stroke-width:7; }

 /* кнопки */
 .btn { display:flex; align-items:center; justify-content:center; gap:10px; width:100%;
        min-height:54px; padding:0 22px; border-radius:999px; border:1px solid transparent;
        font:inherit; font-size:16px; font-weight:800; cursor:pointer; text-align:center;
        transition:transform .2s ease, box-shadow .2s ease, background .2s, border-color .2s; }
 .btn svg { width:19px; height:19px; flex:none; }
 .btn-main { background:#fff; color:var(--bg); box-shadow:0 10px 36px rgba(255,255,255,.16); }
 .btn-main:hover { transform:translateY(-1px); box-shadow:0 14px 44px rgba(255,255,255,.26); }
 .btn-ghost { background:transparent; color:#fff; border-color:rgba(255,255,255,.2); font-weight:700; }
 .btn-ghost:hover { background:rgba(255,255,255,.07); border-color:rgba(255,255,255,.32); }
 .btn-sm { width:auto; min-height:44px; padding:0 18px; font-size:14px; }
 .stack { display:flex; flex-direction:column; gap:10px; }
 .pair { display:grid; grid-template-columns:1fr 1fr; gap:10px; }

 /* карточки */
 .card { background:var(--card); border:1px solid var(--line); border-radius:24px;
         padding:22px; margin:14px 0; backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px); }
 .card.hero { border-color:rgba(79,140,255,.35);
              background:linear-gradient(180deg, rgba(79,140,255,.14), rgba(79,140,255,.02)); }
 .card-title { display:flex; align-items:center; gap:10px; font-size:17px; font-weight:800; margin-bottom:4px; }
 .card-title .ico { width:34px; height:34px; border-radius:11px; display:flex; align-items:center;
                    justify-content:center; background:var(--accent-soft); color:var(--accent); }
 .card-title .ico svg { width:18px; height:18px; }
 .card-sub { color:var(--muted); font-size:14px; margin-bottom:16px; }

 .eyebrow { font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--accent); }
 .hello { font-size:clamp(28px, 7vw, 36px); line-height:1.1; font-weight:800; letter-spacing:-.03em; margin:6px 0 4px; }
 .muted { color:var(--muted); font-size:14px; }

 .hero-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
 .plan { font-weight:700; color:rgba(255,255,255,.9); }
 .big { font-size:clamp(30px, 8vw, 40px); line-height:1.1; font-weight:800; letter-spacing:-.03em; margin:14px 0 2px; }
 .big-sub { color:var(--muted); font-size:14px; }
 .stats { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:8px; margin-top:18px; }
 .stat { background:rgba(5,7,12,.35); border:1px solid var(--line); border-radius:16px; padding:12px; min-width:0; }
 .stat b { display:block; font-size:15px; font-weight:800; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
 .stat span { display:block; font-size:12px; color:var(--soft); margin-top:2px; }

 .pill { display:inline-flex; align-items:center; gap:7px; padding:6px 12px; border-radius:999px;
         font-size:13px; font-weight:700; white-space:nowrap; }
 .pill::before { content:""; width:7px; height:7px; border-radius:50%; background:currentColor; }
 .ok { background:rgba(74,222,128,.12); color:var(--ok); }
 .warn { background:rgba(251,191,36,.12); color:var(--warn); }
 .bad { background:rgba(248,113,113,.12); color:var(--bad); }

 .link { display:flex; align-items:center; gap:10px; margin-top:12px; padding:10px 10px 10px 14px;
         background:rgba(5,7,12,.55); border:1px solid var(--line); border-radius:16px; }
 .link code { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
              color:var(--muted); font-size:13px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
 .copy { flex:none; min-height:40px; padding:0 14px; border-radius:999px; border:1px solid rgba(255,255,255,.2);
         background:transparent; color:#fff; font:inherit; font-size:13px; font-weight:700; cursor:pointer; }
 .copy:hover { background:rgba(255,255,255,.07); }

 .row { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:11px 0;
        border-top:1px solid var(--line); font-size:15px; }
 .row:first-of-type { border-top:0; }
 .row span:first-child { color:rgba(255,255,255,.88); min-width:0; overflow-wrap:anywhere; }
 .row span:last-child { color:var(--soft); text-align:right; }

 /* вход */
 #login { text-align:center; padding:6vh 0 0; }
 #login .card { padding:30px 22px; }
 #login h1 { font-size:clamp(28px, 7vw, 36px); line-height:1.1; font-weight:800; letter-spacing:-.03em; margin:10px 0 10px; }
 #widget { display:flex; justify-content:center; min-height:48px; margin:22px 0 6px; }
 #loginerr { margin-top:10px; }
 #loginerr code { display:block; margin:8px 0; word-break:break-all; color:var(--soft); font-size:12px; }
 .perks { display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin-top:18px; }
 .perks span { padding:7px 12px; border-radius:999px; border:1px solid var(--line); font-size:13px; color:var(--muted); }

 .foot { text-align:center; margin-top:28px; font-size:13px; color:var(--soft); }
 .hide { display:none !important; }

 @media (max-width: 480px) {
   .stats { grid-template-columns:1fr 1fr; }
   .stat:first-child { grid-column:1 / -1; }
   .pair { grid-template-columns:1fr; }
   .card { padding:20px 18px; }
 }
 @media (prefers-reduced-motion: reduce) { .silk span { animation:none; } .btn { transition:none; } }
</style></head>
<body>
<div class="bg" aria-hidden="true"><div class="silk"><span></span><span></span></div><div class="vignette"></div></div>

<div class="wrap">
 <header class="top">
   <a class="brand" href="/" aria-label="Drebol VPN — на сайт">
     <img src="logo.png" alt="drebol" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
     <span class="logo"><svg viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="40"/><ellipse cx="50" cy="50" rx="40" ry="13"/></svg>drebol</span>
   </a>
   <button class="btn btn-ghost btn-sm hide" id="out" type="button">Выйти</button>
 </header>

 <div id="login">
   <div class="card">
     <span class="eyebrow">Личный кабинет</span>
     <h1>Войдите через Telegram</h1>
     <p class="muted">Увидите срок подписки, ссылку для подключения<br>и свои устройства.</p>
     <div id="widget"></div>
     <p class="muted" id="loginerr"></p>
     <div class="perks"><span>Без паролей</span><span>Данные только ваши</span><span>Вход за секунду</span></div>
   </div>
   <p class="foot">Нет подписки? <a id="botlink" href="#" style="color:#fff;font-weight:700">Откройте бота</a></p>
 </div>

 <div id="app" class="hide">
   <span class="eyebrow">Личный кабинет</span>
   <h1 class="hello" id="hello">Личный кабинет</h1>
   <div class="muted" id="whoami"></div>
   <div id="body"></div>
 </div>

 <p class="foot">© Drebol VPN</p>
</div>

<script>
 var API = "__API__";
 var BOT = "__BOT__";
 var KEY = "drebol_token";
 var tg = window.Telegram && window.Telegram.WebApp;
 function esc(s) { return String(s == null ? "" : s).replace(/[<>&"]/g, function (c) {
   return {"<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;"}[c]; }); }
 var memToken = "";
 function token() {
   if (memToken) { return memToken; }
   try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; }
 }
 function setToken(t) {
   memToken = t || "";
   try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY); } catch (e) {}
 }
 function say(msg) { document.getElementById("loginerr").innerHTML = msg || ""; }
 function botUrl() { return "https://t.me/" + BOT; }
 document.getElementById("botlink").href = botUrl();

 // Иконки обводкой — те же, что на главной
 var ICON = {
   tg: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M21.9 4.3 18.7 19c-.2 1-.9 1.3-1.8.8l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5l.4-5 9.1-8.2c.4-.4-.1-.6-.6-.2L6.2 12.9l-4.8-1.5c-1-.3-1-1 .2-1.5l18.9-7.3c.9-.3 1.6.2 1.4 1.7z"/></svg>',
   key: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 8.7-8.7M16 7l3 3M14 9l2 2"/></svg>',
   dev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="4" width="14" height="10" rx="1.5"/><path d="M6 18h6M9 14v4"/><rect x="17" y="8" width="5" height="12" rx="1.2"/></svg>',
   card: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M2.5 10h19M6.5 15h4"/></svg>',
   lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>'
 };
 function title(icon, text) {
   return '<div class="card-title"><span class="ico">' + ICON[icon] + "</span>" + esc(text) + "</div>";
 }

 function api(path, opts) {
   opts = opts || {};
   opts.headers = Object.assign({"Content-Type": "application/json"},
                                opts.headers || {},
                                token() ? {"Authorization": "Bearer " + token()} : {});
   return fetch(API + path, opts).then(function (r) {
     return r.text().then(function (body) {
       var data = {};
       try { data = JSON.parse(body); } catch (e) { data = {raw: body}; }
       return {status: r.status, data: data};
     });
   });
 }

 // Причину видно сразу: иначе вход «проходит», а страница молча остаётся формой
 function fail(where, err) {
   var addr = API || location.origin;
   say("Не получилось " + where + ".<code>" + esc(addr) + "</code>" +
       esc(err && err.message ? err.message : err || "нет ответа"));
 }

 function login(payload) {
   say("Входим…");
   return api("/api/auth", {method: "POST", body: JSON.stringify(payload)})
     .then(function (r) {
       if (r.status === 200 && r.data.token) { setToken(r.data.token); return load(); }
       if (r.status === 401) { say("Телеграм не подтвердил вход. Попробуйте ещё раз."); return; }
       fail("войти", "ответ " + r.status);
     })
     .catch(function (e) { fail("связаться с кабинетом", e); });
 }

 window.onTelegramAuth = function (user) { login({user: user}); };

 function pill(text, kind) { return '<span class="pill ' + kind + '">' + esc(text) + "</span>"; }
 function row(a, b) { return '<div class="row"><span>' + a + "</span><span>" + b + "</span></div>"; }
 function stat(value, label) { return '<div class="stat"><b>' + value + "</b><span>" + esc(label) + "</span></div>"; }

 function render(p) {
   document.getElementById("login").className = "hide";
   document.getElementById("app").className = "";
   document.getElementById("out").classList.remove("hide");
   document.getElementById("hello").textContent = "Привет, " + (p.user.name || "друг") + "!";
   document.getElementById("whoami").textContent = p.user.username ? "@" + p.user.username : "";
   var out = [];

   if (p.blocked) {
     out.push('<div class="card">' + title("lock", "Доступ закрыт") +
              '<p class="card-sub">Если это ошибка — напишите в поддержку в боте.</p>' +
              row("Статус", pill("закрыт", "bad")) +
              row("Причина", esc(p.blocked.reason)) +
              '<div class="stack" style="margin-top:14px"><a class="btn btn-ghost" href="' + botUrl() + '">' +
              ICON.tg + "Написать в поддержку</a></div></div>");
     document.getElementById("body").innerHTML = out.join("");
     return;
   }
   if (!p.subscription) {
     out.push('<div class="card hero">' + title("key", "Подписки пока нет") +
              '<p class="card-sub">Оформите её в боте — пробный период выдаётся сразу.</p>' +
              '<a class="btn btn-main" href="' + botUrl() + '">' + ICON.tg + "Оформить в боте</a></div>");
     document.getElementById("body").innerHTML = out.join("");
     return;
   }

   var s = p.subscription;
   var mark = s.status === "expired" ? pill("закончилась", "bad")
            : !s.enabled ? pill("на паузе", "warn") : pill("активна", "ok");
   var plan = s.plan === "paid" ? "⭐️ Премиум" : "🆓 Пробный период";
   var big = s.status === "expired" ? "Подписка закончилась"
           : (s.left_text ? esc(s.left_text) : "до " + esc(s.until));
   var bigSub = s.status === "expired" ? "Продлите в боте — доступ вернётся сразу."
              : (s.left_text ? "осталось · до " + esc(s.until) : "действует");
   var traffic = esc(s.traffic_used_text) + (s.traffic_limit_gb ? " / " + esc(s.traffic_limit_gb) + " ГБ" : "");

   // Главная карточка: статус и сколько осталось
   out.push('<div class="card hero">' +
            '<div class="hero-head"><span class="plan">' + plan + "</span>" + mark + "</div>" +
            '<div class="big">' + big + "</div>" +
            '<div class="big-sub">' + bigSub + "</div>" +
            '<div class="stats">' +
              stat(esc(s.until), "действует до") +
              stat(s.devices_limit ? "до " + esc(s.devices_limit) : "∞", "устройств") +
              stat(traffic || "—", s.traffic_limit_gb ? "трафик" : "трафик · безлимит") +
            "</div>" +
            '<div class="stack" style="margin-top:16px"><a class="btn btn-main" href="' + botUrl() + '">' +
            ICON.card + (s.status === "expired" ? "Продлить в боте" : "Продлить подписку") + "</a></div>" +
            "</div>");

   // Подключение: приложение в одно нажатие и ссылка с копированием
   out.push('<div class="card">' + title("key", "Подключение") +
            '<p class="card-sub">Добавьте подписку в приложение одним нажатием.</p>' +
            '<div class="pair">' +
              '<a class="btn btn-main" href="happ://add/' + encodeURI(s.url) + '">Добавить в Happ</a>' +
              '<a class="btn btn-ghost" href="incy://add/' + encodeURI(s.url) + '">Добавить в INCY</a>' +
            "</div>" +
            '<div class="link"><code id="suburl">' + esc(s.url) + "</code>" +
            '<button class="copy" type="button" data-copy="' + esc(s.url) + '">Скопировать</button></div>' +
            "</div>");

   if (p.devices && p.devices.length) {
     var d = p.devices.map(function (x) { return row(esc(x.model), esc(x.seen)); }).join("");
     out.push('<div class="card">' + title("dev", "Мои устройства") +
              '<p class="card-sub">Подключено: ' + p.devices.length +
              (s.devices_limit ? " из " + esc(s.devices_limit) : "") + "</p>" + d + "</div>");
   }
   out.push('<div class="stack" style="margin-top:6px"><a class="btn btn-ghost" href="' + botUrl() + '">' +
            ICON.tg + "Открыть бота</a></div>");
   document.getElementById("body").innerHTML = out.join("");
 }

 // Копирование ссылки. Где буфер недоступен — просто выделяем её
 document.addEventListener("click", function (e) {
   var btn = e.target.closest && e.target.closest("[data-copy]");
   if (!btn) { return; }
   var text = btn.getAttribute("data-copy");
   function done() {
     btn.textContent = "Скопировано ✓";
     setTimeout(function () { btn.textContent = "Скопировать"; }, 1600);
   }
   function select() {
     var el = document.getElementById("suburl");
     var r = document.createRange(); r.selectNodeContents(el);
     var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
   }
   if (navigator.clipboard && navigator.clipboard.writeText) {
     navigator.clipboard.writeText(text).then(done, select);
   } else { select(); }
 });

 function load() {
   return api("/api/me").then(function (r) {
     if (r.status === 200) { say(""); return render(r.data); }
     setToken("");
     showLogin();
     if (r.status !== 401) { fail("получить данные", "ответ " + r.status); }
   }).catch(function (e) { showLogin(); fail("связаться с кабинетом", e); });
 }

 var widgetShown = false;
 function showLogin() {
   document.getElementById("app").className = "hide";
   document.getElementById("login").className = "";
   document.getElementById("out").classList.add("hide");
   if (!API) {
     say("Кабинет ещё не настроен: не задан адрес API.");
     return;
   }
   if (widgetShown) { return; }
   widgetShown = true;
   var w = document.createElement("script");
   w.async = true;
   w.src = "https://telegram.org/js/telegram-widget.js?22";
   w.setAttribute("data-telegram-login", BOT);
   w.setAttribute("data-size", "large");
   w.setAttribute("data-radius", "999");
   w.setAttribute("data-onauth", "onTelegramAuth(user)");
   w.setAttribute("data-request-access", "write");
   document.getElementById("widget").appendChild(w);
 }

 document.getElementById("out").onclick = function () {
   api("/api/logout", {method: "POST"});
   setToken("");
   location.reload();
 };

 if (tg && tg.initData) {
   tg.ready(); tg.expand();
   // внутри Telegram красим шапку в цвет страницы
   try { tg.setHeaderColor("#05070c"); tg.setBackgroundColor("#05070c"); } catch (e) {}
   login({initData: tg.initData});
 } else if (token()) {
   load();
 } else {
   showLogin();
 }
</script></body></html>
"""


def cabinet_page(bot_username: str) -> str:
    """Готовая страница кабинета: подставлены адрес API и имя бота."""
    from config import load_config
    api = (load_config().get("webapi_public") or "").rstrip("/")
    return (CABINET_PAGE.replace("__API__", api or "")
            .replace("__BOT__", bot_username or ""))


def add_ready() -> bool:
    """Страница-переходник уже лежит на сайте — можно давать кнопки в боте."""
    c = creds()
    return bool(c["domain"] and load_config().get("site_add_page"))


def add_url(app: str, sub_url: str) -> str:
    """Ссылка, которая уведёт человека прямо в приложение."""
    from urllib.parse import quote
    if not add_ready() or not sub_url:
        return ""
    return f"{site_url()}/add.html?app={quote(app)}&u={quote(sub_url, safe='')}"


def deeplink(app: str, sub_url: str) -> str:
    """Схема приложения — её можно скопировать и вставить в импорт."""
    scheme = {"happ": "happ://add/", "incy": "incy://add/"}.get(app, "happ://add/")
    return f"{scheme}{sub_url}" if sub_url else ""


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


def _probe_targets_sync(targets: list) -> dict:
    """Проверяет с сервера сайта, достучится ли он до бота по этим адресам."""
    out = {}
    try:
        cli = _client()
    except Exception as e:
        return {"error": f"не подключиться к серверу сайта: {type(e).__name__}: {e}"}
    try:
        for target in targets:
            script = (f"curl -s -o /dev/null -m 6 -w '%{{http_code}}' "
                      f"http://{target}/api/health 2>/dev/null || echo 000")
            code, res, err = _run(cli, script)
            out[target] = (res or "").strip()[-3:] or "000"
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        cli.close()
    return out


async def probe_targets(targets: list) -> dict:
    return await asyncio.to_thread(_probe_targets_sync, targets)


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


def _deploy_sync(page: str, og_bytes: bytes, logo_bytes: bytes = b"",
                 cabinet: str = "") -> dict:
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
            with sftp.open("/tmp/drebol_add.html", "w") as f:
                f.write(ADD_PAGE)
            with sftp.open("/tmp/drebol_cabinet.html", "w") as f:
                f.write(cabinet or "")
            if logo_bytes:
                with sftp.open("/tmp/drebol_logo", "wb") as f:
                    f.write(logo_bytes)
        finally:
            sftp.close()

        server_name = c["domain"] or "_"
        cert_domain = c["domain"]
        # Личный кабинет ходит в бота: если адрес задан, сайт проксирует /api/ к нему
        upstream = str(load_config().get("webapi_upstream") or "").strip()
        api_block = ""
        if upstream:
            api_block = f"""    location /api/ {{
        proxy_pass http://{upstream}/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }}"""
        install = f"""set -e
mv /tmp/drebol_index.html {WEB_ROOT}/index.html
mv /tmp/drebol_og.webp {WEB_ROOT}/og.webp
mv /tmp/drebol_add.html {WEB_ROOT}/add.html
mv /tmp/drebol_cabinet.html {WEB_ROOT}/cabinet.html
chmod 644 {WEB_ROOT}/add.html {WEB_ROOT}/cabinet.html
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
{api_block}
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
        return tariffs
    except Exception:
        return []


async def build_current(bot_username: str) -> tuple:
    """Страница по текущим данным бота и файлы, которые едут вместе с ней.

    Одна сборка на всех: и кнопка «Обновить», и автообновление смотрят
    ровно на то, что окажется на сервере.
    """
    from site_page import build_page
    cfg = load_config()
    og_bytes = _asset("og.webp")
    logo_bytes = _asset(LOGO_NAME)
    # кабинет лежит рядом со страницей — ссылка относительная
    cabinet = "cabinet.html" if cfg.get("webapi_public") else ""
    page = build_page(
        bot_username=bot_username,
        cabinet_url=cabinet,
        privacy_url=cfg.get("privacy_url", "") or "",
        terms_url=cfg.get("terms_url", "") or "",
        channel_url=cfg.get("channel_url", "") or "",
        logo_file=LOGO_NAME if logo_bytes else "",
        tariffs=await site_tariffs(cfg),
        poster_file="og.webp" if og_bytes else "",
    )
    return page, og_bytes, logo_bytes


def cabinet_ready() -> bool:
    """Кабинет опубликован: есть домен, адрес API и страница уже уехала."""
    c = creds()
    cfg = load_config()
    return bool(c["domain"] and cfg.get("webapi_public") and cfg.get("site_cabinet"))


def cabinet_link() -> str:
    return f"{site_url()}/cabinet.html" if cabinet_ready() else ""


def page_hash(page: str, og_bytes: bytes, logo_bytes: bytes) -> str:
    """Отпечаток того, что должно лежать на сервере.

    По нему автообновление понимает, поменялось ли хоть что-нибудь: цена
    тарифа, ссылка на канал, документы, логотип. Не поменялось — не трогаем.
    """
    import hashlib
    h = hashlib.sha256()
    h.update(page.encode("utf-8"))
    h.update(og_bytes)
    h.update(logo_bytes)
    # адрес API кабинета тоже часть сайта: сменили — страницу надо перезалить
    h.update(str(load_config().get("webapi_public") or "").encode("utf-8"))
    return h.hexdigest()


async def deploy(bot_username: str) -> dict:
    """Собирает страницу и раскатывает её на сервер."""
    page, og_bytes, logo_bytes = await build_current(bot_username)
    cabinet = cabinet_page(bot_username)
    res = await asyncio.to_thread(_deploy_sync, page, og_bytes, logo_bytes, cabinet)
    if res.get("ok"):
        # вместе со страницей уехал и переходник — можно показывать кнопки приложений
        save_creds(site_deployed_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                   site_page_hash=page_hash(page, og_bytes, logo_bytes),
                   site_add_page=True, site_cabinet=bool(load_config().get("webapi_public")))
    return res


async def site_sync_tick(context):
    """Сам обновляет сайт, когда в боте что-то поменялось.

    Поменял цену тарифа, ссылку на канал или логотип — через пару минут это
    же окажется на сайте, нажимать «Обновить» не нужно.
    """
    cfg = load_config()
    if not cfg.get("site_auto", True) or not configured():
        return
    # сайт ещё ни разу не разворачивали — сами этого не делаем
    if not cfg.get("site_deployed_at"):
        return
    try:
        me = await context.bot.get_me()
        page, og_bytes, logo_bytes = await build_current(me.username)
    except Exception:
        return
    fresh = page_hash(page, og_bytes, logo_bytes)
    if fresh == cfg.get("site_page_hash"):
        return

    res = await asyncio.to_thread(_deploy_sync, page, og_bytes, logo_bytes)
    from log_channel import send_log
    if res.get("ok"):
        save_creds(site_deployed_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                   site_page_hash=fresh)
        await send_log(context.bot, "🌐 Сайт обновлён автоматически: данные изменились")
    else:
        # молчать нельзя: на сайте остались старые цены
        await send_log(context.bot,
            "⚠️ Сайт не обновился автоматически\n"
            f"<code>{escape(str(res.get('error'))[:300])}</code>")


async def issue_cert() -> dict:
    res = await asyncio.to_thread(_cert_sync)
    if res.get("ok"):
        save_creds(site_https=True)
    return res


async def remove_site() -> dict:
    res = await asyncio.to_thread(_remove_sync)
    if res.get("ok"):
        save_creds(site_deployed_at="", site_https=False, site_add_page=False)
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
            f"🖼 Логотип: {'свой' if has_logo() else 'нарисованный'}",
            "⚡ Автообновление: "
            + ("вкл" if load_config().get("site_auto", True) else "выкл")]
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
            extra.append(InlineKeyboardButton(
                "⚡ Авто: вкл" if load_config().get("site_auto", True) else "💤 Авто: выкл",
                callback_data="site_auto"))
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


async def handle_site_auto(query, context):
    cfg = load_config()
    cfg["site_auto"] = not cfg.get("site_auto", True)
    save_config(cfg)
    await query.answer("Сайт будет обновляться сам" if cfg["site_auto"]
                       else "Теперь только вручную")
    await handle_site_menu(query)


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
