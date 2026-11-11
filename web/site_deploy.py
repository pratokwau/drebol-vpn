"""Сайт-визитка на втором сервере.

Бот подключается к серверу по SSH, ставит nginx, кладёт одну страницу и
включает её. Всё делается заново при каждом «Развернуть», поэтому обновить
сайт — это просто нажать кнопку ещё раз.

Пароль сервера хранится в конфиге бота (файл доступен только root) и
никогда не показывается в переписке: сообщение с ним бот удаляет сразу.
"""

import asyncio
import base64
import os
from datetime import datetime
from html import escape

from config import load_config, save_config

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # корень репозитория: web/ на уровень ниже
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
<meta name="theme-color" content="#020202">
<title>Личный кабинет · Drebol VPN</title>
<link rel="icon" href="__FAVICON__">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Unbounded:wght@500;600;700;800&display=swap" rel="stylesheet">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
 :root {
   color-scheme: dark;
   --bg: #020202; --ink: #f4f3ec;
   --muted: rgba(255,255,255,.72); --soft: rgba(255,255,255,.48);
   --line: rgba(255,255,255,.08); --line-strong: rgba(255,255,255,.16);
   --card: rgba(11,11,13,.78); --card-hover: rgba(16,16,19,.9);
   --accent: #2ea8ff; --accent-soft: rgba(46,168,255,.14);
   --ok: #38ef7d; --warn: #fbbf24; --bad: #f87171;
 }
 * { box-sizing: border-box; }
 body { margin:0; min-height:100vh; background:var(--bg); color:var(--ink); overflow-x:hidden;
        font:15px/1.55 "Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
        -webkit-font-smoothing:antialiased; }
 body { min-height:var(--tg-viewport-height, 100vh); }
 a { color:inherit; text-decoration:none; }
 h1, h2, p { margin:0; }

 .bg { position:fixed; inset:0; z-index:0; pointer-events:none; overflow:hidden; }
 .orbit { position:absolute; left:50%; top:-38vmax; border-radius:50%;
   border:1px solid rgba(46,168,255,.13); animation:spin 90s linear infinite; will-change:transform; }
 .orbit i { position:absolute; left:50%; top:-5px; width:10px; height:10px; margin-left:-5px;
   border-radius:50%; background:#2ea8ff;
   box-shadow:0 0 18px 4px rgba(46,168,255,.45), 0 0 46px 12px rgba(46,168,255,.25); }
 .orbit-a { width:110vmax; height:110vmax; margin-left:-55vmax; }
 .orbit-b { width:78vmax; height:78vmax; margin-left:-39vmax; top:-26vmax;
   border-color:rgba(46,168,255,.09); animation-duration:64s; animation-direction:reverse; }
 .orbit-b i { width:7px; height:7px; margin-left:-3.5px; top:-3.5px; }
 @keyframes spin { to { transform:rotate(360deg); } }
 .aurora { position:absolute; inset:-30%; filter:blur(80px); opacity:.85; }
 .aurora span { position:absolute; border-radius:50%; animation:floatOrb 24s ease-in-out infinite; mix-blend-mode:screen; }
 .aurora span:nth-child(1) { width:60vmax; height:60vmax; top:-15%; left:-10%;
   background:radial-gradient(circle at center, rgba(30,111,255,.32), transparent 70%); }
 .aurora span:nth-child(2) { width:50vmax; height:50vmax; bottom:-20%; right:-15%;
   background:radial-gradient(circle at center, rgba(46,168,255,.16), transparent 75%);
   animation-duration:30s; animation-delay:-6s; }
 .aurora span:nth-child(3) { width:45vmax; height:45vmax; top:25%; left:30%;
   background:radial-gradient(circle at center, rgba(30,111,255,.1), transparent 70%);
   animation-duration:34s; animation-delay:-12s; }
 @keyframes floatOrb {
   0%,100% { transform:translate3d(0,0,0) scale(1); }
   33% { transform:translate3d(5vw,-4vh,0) scale(1.1); }
   66% { transform:translate3d(-4vw,5vh,0) scale(.95); } }
 .vignette { position:absolute; inset:0;
   background:radial-gradient(ellipse at center, transparent 40%, rgba(2,2,2,.85) 100%); }

 .wrap { position:relative; z-index:1; max-width:520px; margin:0 auto;
         padding:12px 12px 36px;
         padding-top:max(12px, env(safe-area-inset-top, 0px),
                          var(--tg-content-safe-area-inset-top, 0px)); }

 .top { display:flex; align-items:center; justify-content:space-between; gap:10px;
        min-height:46px; margin-bottom:12px; background:rgba(7,7,8,.85);
        border:1px solid var(--line); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px);
        padding:7px 12px; border-radius:14px; }
 body.tg-fullscreen .wrap { padding-top:116px; }
 body.tg-fullscreen .tabs { top:96px; }
 .brand { display:flex; align-items:center; min-height:36px; text-decoration:none; }
 .brand img { height:40px; max-height:40px; width:auto; max-width:200px; object-fit:contain; display:block; filter:drop-shadow(0 0 12px rgba(46,168,255,.3)); }
 .logo { display:flex; align-items:center; gap:10px; }
 .logo .mark { width:28px; height:28px; }
 .logo .mark circle, .logo .mark ellipse { fill:none; stroke:#2ea8ff; stroke-width:7; }
 .logo .word { font-size:22px; font-weight:800; letter-spacing:-.02em; font-family:"Unbounded",sans-serif; color:#fff; }

 .btn { display:flex; align-items:center; justify-content:center; gap:10px; width:100%; position:relative; overflow:hidden;
        min-height:52px; padding:0 22px; border-radius:999px; border:1px solid transparent;
        font:inherit; font-size:15px; font-weight:800; cursor:pointer; text-align:center;
        transition:transform .2s ease, box-shadow .2s ease, background .2s, border-color .2s; }
 .btn svg { width:19px; height:19px; flex:none; }
 .btn-main { background:linear-gradient(135deg, #ffffff 0%, #e2e8f5 100%); color:#020202;
             box-shadow:0 0 0 1px rgba(255,255,255,.4), 0 8px 30px rgba(255,255,255,.16); }
 .btn-main:hover { transform:translateY(-2px); box-shadow:0 0 0 1px #fff, 0 12px 40px rgba(46,168,255,.4); }
 .btn-ghost { background:rgba(255,255,255,.05); color:#fff; border-color:var(--line-strong); font-weight:700; }
 .btn-ghost:hover { background:rgba(255,255,255,.1); border-color:rgba(255,255,255,.35); transform:translateY(-2px); }
 .btn-sm { width:auto; min-height:40px; padding:0 16px; font-size:13px; }
 .btn::after { content:""; position:absolute; top:0; left:-80%; width:50%; height:100%;
   background:linear-gradient(100deg, transparent, rgba(255,255,255,.32), transparent);
   transform:skewX(-20deg); transition:left .6s ease; pointer-events:none; }
 .btn:hover::after { left:130%; }
 .btn-main::after { background:linear-gradient(100deg, transparent, rgba(46,168,255,.28), transparent); }
 .stack { display:flex; flex-direction:column; gap:10px; }
 .pair { display:grid; grid-template-columns:1fr 1fr; gap:10px; }

 .card { background:var(--card); border:1px solid var(--line); border-radius:18px;
         padding:14px; margin:8px 0; backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px);
         box-shadow:0 6px 20px rgba(0,0,0,.35); position:relative; }
 .card::before { content:""; position:absolute; top:0; left:24px; right:24px; height:1px;
   background:linear-gradient(90deg, transparent, rgba(46,168,255,.55), transparent); pointer-events:none; }
 .card.hero { border-color:rgba(46,168,255,.45);
              background:linear-gradient(180deg, rgba(46,168,255,.14), rgba(11,11,13,.92));
              box-shadow:0 14px 36px rgba(0,0,0,.5), 0 0 24px rgba(46,168,255,.15);
              animation:heroIn .5s ease both; }
 .card.hero::after { content:""; position:absolute; inset:0; border-radius:inherit;
   background:radial-gradient(ellipse 70% 55% at 50% 0%, rgba(46,168,255,.22), transparent 70%);
   pointer-events:none; }
 .card.hero > * { position:relative; z-index:1; }
 @keyframes heroIn { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:none; } }
 .card-title { display:flex; align-items:center; gap:9px; font-size:15px; font-weight:800; margin-bottom:2px; }
 .card-title .ico { width:30px; height:30px; border-radius:9px; display:flex; align-items:center;
                    justify-content:center; background:var(--accent-soft); color:var(--accent);
                    box-shadow:0 0 14px rgba(46,168,255,.3); }
 .card-title .ico svg { width:15px; height:15px; }
 .card-sub { color:var(--muted); font-size:13px; margin-bottom:10px; }

 .eyebrow { font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; color:var(--accent); }
 .hello { font-size:clamp(26px, 7vw, 34px); line-height:1.1; font-weight:800; letter-spacing:-.03em; margin:6px 0 4px; font-family:"Unbounded","Inter",sans-serif; text-shadow:0 0 32px rgba(46,168,255,.28); }
 .muted { color:var(--muted); font-size:14px; }

 .hero-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
 .plan { font-weight:700; color:rgba(255,255,255,.9); }
 .big { font-size:clamp(28px, 8vw, 38px); line-height:1.1; font-weight:800; letter-spacing:-.03em; margin:14px 0 2px; font-family:"Unbounded",sans-serif; }
 .big-sub { color:var(--muted); font-size:14px; }
 .stats { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:8px; margin-top:18px; }
 .stat { background:linear-gradient(180deg, rgba(46,168,255,.08), rgba(2,2,2,.45)); border:1px solid var(--line); border-radius:16px; padding:12px; min-width:0; }
 .stat b { display:block; font-size:15px; font-weight:800; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-family:"Unbounded",sans-serif; }
 .stat span { display:block; font-size:12px; color:var(--soft); margin-top:2px; }
 .stat span::before { content:""; display:inline-block; width:5px; height:5px; border-radius:50%;
   background:var(--accent); margin-right:6px; vertical-align:1px; box-shadow:0 0 8px rgba(46,168,255,.8); }

 .pill { display:inline-flex; align-items:center; gap:7px; padding:6px 12px; border-radius:999px;
         font-size:12px; font-weight:700; white-space:nowrap; }
 .pill::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; }
 .ok { background:rgba(56,239,125,.14); color:var(--ok); }
 .warn { background:rgba(251,191,36,.14); color:var(--warn); }
 .bad { background:rgba(248,113,113,.14); color:var(--bad); }

 .link { display:flex; align-items:center; gap:10px; margin-top:12px; padding:10px 10px 10px 14px;
         background:rgba(2,2,2,.65); border:1px solid var(--line); border-radius:16px; }
 .link code { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
              color:var(--muted); font-size:13px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
 .copy { flex:none; min-height:40px; padding:0 14px; border-radius:999px; border:1px solid var(--line-strong);
         background:rgba(255,255,255,.05); color:#fff; font:inherit; font-size:13px; font-weight:700; cursor:pointer; }
 .copy:hover { background:rgba(255,255,255,.1); }

 .row { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:11px 0;
        border-top:1px solid var(--line); font-size:14px; }
 .row:first-of-type { border-top:0; }
 .row span:first-child { color:rgba(255,255,255,.88); min-width:0; overflow-wrap:anywhere; }
 .row span:last-child { color:var(--soft); text-align:right; }

 .bar { height:12px; border-radius:999px; background:rgba(255,255,255,.08); overflow:hidden; margin-top:14px; }
 .bar-fill { height:100%; border-radius:999px; background:linear-gradient(90deg, var(--accent), #7cc4ff);
   box-shadow:0 0 14px rgba(46,168,255,.55); }
 .bar-fill.full { background:linear-gradient(90deg, #fbbf24, #f87171); }
 .bar-note { display:flex; justify-content:space-between; gap:12px; margin-top:8px; font-size:13px; color:var(--soft); }

 .dev { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:11px 8px;
        border-top:1px solid var(--line); border-radius:12px; transition:background .2s ease; }
 .dev:hover { background:rgba(255,255,255,.04); }
 .dev:first-of-type { border-top:0; }
 .dev b { display:block; font-size:15px; overflow-wrap:anywhere; }
 .dev small { color:var(--soft); font-size:13px; }
 .btn-mini { flex:none; min-height:36px; padding:0 14px; border-radius:999px;
             border:1px solid rgba(248,113,113,.4); background:transparent; color:#fca5a5;
             font:inherit; font-size:13px; font-weight:700; cursor:pointer; }
 .btn-mini:hover { background:rgba(248,113,113,.12); }
 .btn-mini:disabled { opacity:.5; }
 .btn-danger { border-color:rgba(248,113,113,.45); color:#fca5a5; }
 .btn-danger:hover { background:rgba(248,113,113,.10); border-color:rgba(248,113,113,.6); }

 .tabs { position:sticky; top:var(--tg-content-safe-area-inset-top, 0px); z-index:5; display:flex; gap:6px; overflow-x:auto;
         margin:0 -12px; padding:7px 12px;
         background:rgba(2,2,2,.92); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px);
         scrollbar-width:none; }
 .tabs::-webkit-scrollbar { display:none; }
 .tab { flex:none; min-height:36px; padding:0 15px; border-radius:999px; position:relative;
        border:1px solid var(--line-strong); background:transparent; color:rgba(255,255,255,.75);
        font:inherit; font-size:13px; font-weight:700; cursor:pointer; white-space:nowrap;
        transition:all .22s ease; }
 .tab:active { transform:scale(.96); }
 .tab.active { background:#fff; color:#020202; border-color:#fff;
   box-shadow:0 3px 12px rgba(255,255,255,.2), 0 0 18px rgba(46,168,255,.3); }
 .tab .dot { position:absolute; top:5px; right:5px; width:8px; height:8px; border-radius:50%;
             background:#ff4d4d; box-shadow:0 0 0 0 rgba(255,77,77,.55);
             animation:dotPulse 1.6s ease-out infinite; pointer-events:none; }
 @keyframes dotPulse { 0% { box-shadow:0 0 0 0 rgba(255,77,77,.55); }
   70% { box-shadow:0 0 0 7px rgba(255,77,77,0); } 100% { box-shadow:0 0 0 0 rgba(255,77,77,0); } }
 .breadcrumb { font-size:11px; color:var(--soft); margin:4px 0 6px; display:flex; align-items:center; gap:4px; letter-spacing:.01em; }
 .breadcrumb span { color:var(--muted); font-weight:600; }
 .breadcrumb span:last-child { color:#fff; }

 .pay { padding:14px 0; border-top:1px solid var(--line); }
 .pay:first-of-type { border-top:0; }
 .pay-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
 .pay-amount { font-size:18px; font-weight:800; letter-spacing:-.01em; font-family:"Unbounded",sans-serif; }
 .pay-date { font-size:13px; color:var(--soft); margin-top:2px; }
 .pay-meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
 .chip { padding:4px 10px; border-radius:999px; border:1px solid var(--line);
         font-size:12px; font-weight:600; color:var(--muted); }

 @keyframes secIn { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:none; } }
 @keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
 #app:not(.hide) { animation:fadeIn .35s ease both; }
 [data-sec].sec-show { animation:secIn .35s ease both; }
 @media (prefers-reduced-motion: reduce) {
   #app:not(.hide), [data-sec].sec-show { animation:none; } }

 #login { text-align:center; padding:6vh 0 0; }
 #login .card { padding:30px 22px; border-color:rgba(46,168,255,.28);
   box-shadow:0 20px 60px rgba(0,0,0,.5), 0 0 44px rgba(46,168,255,.1); }
 #login h1 { font-size:clamp(28px, 7vw, 36px); line-height:1.1; font-weight:800; letter-spacing:-.03em; margin:10px 0 10px; }
 #widget { display:flex; justify-content:center; min-height:48px; margin:22px 0 6px; }
 #loginerr { margin-top:10px; }
 #loginerr code { display:block; margin:8px 0; word-break:break-all; color:var(--soft); font-size:12px; }
 .perks { display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin-top:18px; }
 .perks span { padding:7px 12px; border-radius:999px; border:1px solid var(--line); font-size:13px; color:var(--muted); }

 .foot { text-align:center; margin-top:28px; font-size:13px; color:var(--soft); }
 .hide { display:none !important; }

 .login-logo { display:flex; justify-content:center; margin:10px 0 22px; }
 .login-logo img { width:240px; max-width:70vw; height:auto;
   animation:logoGlow 6s ease-in-out infinite; }
 @keyframes logoGlow {
   0%,100% { filter:drop-shadow(0 0 16px rgba(46,168,255,.35)); }
   50% { filter:drop-shadow(0 0 32px rgba(46,168,255,.55)); } }
 .renew-tariff { justify-content:center; gap:8px; }
 .renew-tariff .rt-price { color:var(--accent); font-family:"Unbounded",sans-serif; font-size:16px; }

 @media (max-width: 480px) {
   .stats { grid-template-columns:1fr 1fr; }
   .stat:first-child { grid-column:1 / -1; }
   .pair { grid-template-columns:1fr; }
   .card { padding:12px 12px; }
 }

 @media (min-width: 900px) {
   .wrap { max-width:960px; }
   /* сетка — на #body: каждая карточка лежит в своём [data-sec],
      поэтому грид на самих карточках давал одну занятую колонку
      и пустую правую половину. Класс tab-sub ставит showTab. */
   #body.tab-sub { display:grid; grid-template-columns:1fr 1fr; gap:0 20px; align-items:start; }
   #body.tab-sub > #tabs, #body.tab-sub > .breadcrumb,
   #body.tab-sub > .stack, #body.tab-sub > .sub-hero { grid-column:1 / -1; }
   [data-sec="sub"] > .card { margin:14px 0; }
 }
 @media (prefers-reduced-motion: reduce) { .aurora span, .orbit { animation:none; } .btn { transition:none; } .tab .dot { animation:none; } .card.hero, .login-logo img { animation:none; } }

 .field { display:block; text-align:left; margin:12px 0 0; font-size:13px; font-weight:700; color:var(--muted); }
 .field input { display:block; width:100%; margin-top:6px; padding:12px 14px; border-radius:14px;
   border:1px solid var(--line-strong); background:rgba(255,255,255,.05); color:#fff;
   font:inherit; font-size:15px; outline:none; }
 .field input:focus { border-color:#2ea8ff; box-shadow:0 0 0 3px rgba(46,168,255,.25); }
 .or { display:flex; align-items:center; gap:12px; margin:22px 0 4px; color:var(--soft); font-size:13px; }
 .or::before, .or::after { content:""; flex:1; height:1px; background:var(--line); }
 #pwform .btn, #forgotform .btn, #prof-email-form .btn, #prof-pass-form .btn { width:100%; margin-top:14px; }
 #turnstile-box, #turnstile-box2 { display:flex; justify-content:center; margin-top:14px; }
 #turnstile-box:empty, #turnstile-box2:empty { display:none; }
 .form-note { font-size:13px; color:var(--soft); margin-top:10px; }
 .linklike { background:none; border:0; color:#7cc4ff; font:inherit; font-size:14px; cursor:pointer; padding:0; margin-top:12px; }
</style></head>
<body>
<div class="bg" aria-hidden="true">
  <div class="orbit orbit-a"><i></i></div>
  <div class="orbit orbit-b"><i></i></div>
  <div class="aurora"><span></span><span></span><span></span></div>
  <div class="vignette"></div>
</div>

<div class="wrap">
 <header class="top">
   <a class="brand" href="/" aria-label="Drebol VPN — на сайт">
     __LOGO__
   </a>
   <button class="btn btn-ghost btn-sm hide" id="out" type="button">Выйти</button>
 </header>

 <div id="login">
   <div class="login-logo">__LOGO__</div>
   <div class="card">
     <span class="eyebrow">Личный кабинет</span>
     <h1>Вход в кабинет</h1>
     <p class="muted">Увидите срок и трафик подписки, остаток LTE,<br>свои устройства, платежи и рефералку.</p>
     <div id="widget"></div>
     <div id="pwblock" class="hide">
       <div class="or"><span>или по почте</span></div>
       <form id="pwform" autocomplete="on">
         <label class="field">Почта<input type="email" id="pw-email" autocomplete="email" required></label>
         <label class="field">Пароль<input type="password" id="pw-pass" autocomplete="current-password" required></label>
         <div id="turnstile-box"></div>
         <button class="btn btn-main" type="submit">Войти</button>
       </form>
       <button class="linklike" type="button" id="forgot-open">Забыли пароль?</button>
       <form id="forgotform" class="hide" autocomplete="on">
         <label class="field">Почта<input type="email" id="fg-email" autocomplete="email" required></label>
         <div id="turnstile-box2"></div>
         <button class="btn btn-main" type="submit">Получить код в Telegram</button>
         <div id="fg-code-wrap" class="hide">
           <label class="field">Код из Telegram<input type="text" id="fg-code" inputmode="numeric" autocomplete="one-time-code"></label>
           <label class="field">Новый пароль<input type="password" id="fg-pass" autocomplete="new-password"></label>
           <button class="btn btn-main" type="button" id="fg-reset">Сменить пароль</button>
         </div>
         <button class="linklike" type="button" id="forgot-back">← Назад ко входу</button>
       </form>
       <p class="form-note" id="pw-note"></p>
     </div>
     <p class="muted" id="loginerr"></p>
     <div class="perks"><span>Два способа входа</span><span>Данные только ваши</span><span>Вход за секунду</span></div>
   </div>
   <p class="foot">Нет подписки? <a id="botlink" href="#" style="color:#fff;font-weight:700">Откройте бота</a></p>
 </div>

 <div id="app" class="hide">
   <span class="eyebrow">Личный кабинет</span>
   <h1 class="hello" id="hello">Личный кабинет</h1>
   <div class="muted" id="whoami"></div>
   <div id="body"></div>
 </div>

 <p class="foot">Drebol VPN</p>
</div>

<script>
 var API = "__API__";
 var BOT = "__BOT__";
 var TS_KEY = "__TURNSTILE__";
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
   lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
   user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5"/></svg>'
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

 // Капча Cloudflare Turnstile: грузится только если задан ключ сайта.
 // Без ключа блок входа по почте скрыт, вход через Telegram работает.
 var tsLoaded = false, tsWidgets = {};
 function tsLoad() {
   if (!TS_KEY || tsLoaded) { return; }
   tsLoaded = true;
   var s = document.createElement("script");
   s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
   s.async = true; s.defer = true;
   s.onload = function () {
     try {
       tsWidgets.pw = turnstile.render("#turnstile-box", {sitekey: TS_KEY});
       tsWidgets.fg = turnstile.render("#turnstile-box2", {sitekey: TS_KEY});
     } catch (e) {}
   };
   document.head.appendChild(s);
 }
 function tsToken(which) {
   try {
     return (window.turnstile && tsWidgets[which] !== undefined)
       ? turnstile.getResponse(tsWidgets[which]) : "";
   } catch (e) { return ""; }
 }
 function tsReset(which) {
   try {
     if (window.turnstile && tsWidgets[which] !== undefined) { turnstile.reset(tsWidgets[which]); }
   } catch (e) {}
 }

 function pill(text, kind) { return '<span class="pill ' + kind + '">' + esc(text) + "</span>"; }
 function row(a, b) { return '<div class="row"><span>' + a + "</span><span>" + b + "</span></div>"; }
 function stat(value, label) { return '<div class="stat"><b>' + value + "</b><span>" + esc(label) + "</span></div>"; }

 // Статусы платежей — человеческим языком, а не кодами из базы
 var PAY_STATUS = {
   paid: {text: "Оплачено", kind: "ok"},
   pending: {text: "Ожидает оплаты", kind: "warn"},
   failed: {text: "Не прошла", kind: "bad"},
   cancelled: {text: "Отменена", kind: "bad"},
   refunded: {text: "Возврат", kind: "warn"},
   refund_pending: {text: "Возврат в обработке", kind: "warn"}
 };
 function payProvider(raw) {
   var map = {anore: "Платёжная система", platega: "Platega", yookassa: "ЮKassa", telegram: "Telegram", stars: "Stars", crypto: "Крипта"};
   return map[String(raw).toLowerCase()] || String(raw);
 }
 // "2026-10-20 10:00" -> "20.10.2026 · 10:00"
 function fmtDate(raw) {
   var m = String(raw || "").match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/);
   return m ? m[3] + "." + m[2] + "." + m[1] + " · " + m[4] : String(raw || "");
 }

 // Профиль: почта и пароль для входа из браузера. Пока что-то не задано,
 // вкладка светится красной точкой (см. buildTabs).
 function profileCard(p) {
   var lg = p.login || {};
   var rows = [
     row("Почта", lg.email ? esc(lg.email) : pill("не задана", "warn")),
     row("Пароль", lg.has_password ? pill("задан", "ok") : pill("не задан", "warn"))
   ];
   return '<div data-sec="profile"><div class="card">' + title("user", "Профиль") +
     '<p class="card-sub">Почта и пароль — для входа в кабинет из браузера, без Telegram.</p>' +
     rows.join("") +
     '<form id="prof-email-form" style="margin-top:14px">' +
       '<label class="field">Почта<input type="email" id="prof-email" value="' + esc(lg.email || "") +
       '" placeholder="you@example.com" autocomplete="email"></label>' +
       '<button class="btn btn-ghost" type="submit">Сохранить почту</button></form>' +
     '<form id="prof-pass-form" style="margin-top:14px">' +
       (lg.has_password
         ? '<label class="field">Текущий пароль<input type="password" id="prof-cur" autocomplete="current-password"></label>'
         : "") +
       '<label class="field">Новый пароль (от 8 символов)<input type="password" id="prof-new" autocomplete="new-password" minlength="8"></label>' +
       '<button class="btn btn-ghost" type="submit">' +
       (lg.has_password ? "Сменить пароль" : "Задать пароль") + "</button></form>" +
     '<p class="form-note" id="prof-note"></p>' +
     "</div></div>";
 }

 function render(p) {
   document.getElementById("login").className = "hide";
   document.getElementById("app").className = "";
   document.getElementById("out").classList.remove("hide");
   document.getElementById("hello").textContent = "Привет, " + (p.user.name || "друг") + "!";
   document.getElementById("whoami").textContent = p.user.username ? "@" + p.user.username : "";
   window.LOGIN = p.login || {};
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
     var ref0 = referralCard(p);
     if (ref0) { out.push('<div data-sec="friends">' + ref0 + "</div>"); }
     out.push(profileCard(p));
     document.getElementById("body").innerHTML = out.join("");
     buildTabs();
     bindActions();
     return;
   }

   var s = p.subscription;
   var mark = s.status === "expired" ? pill("закончилась", "bad")
            : !s.enabled ? pill("на паузе", "warn") : pill("активна", "ok");
   var plan = s.plan === "paid" ? "💎 Премиум" : "🆓 Пробный период";
   var big = s.status === "expired" ? "Подписка закончилась"
           : (s.left_text ? esc(s.left_text) : "до " + esc(s.until));
   var bigSub = s.status === "expired" ? "Продлите здесь — доступ вернётся сразу."
              : (s.left_text ? "осталось · до " + esc(s.until) : "действует");
   var traffic = esc(s.traffic_used_text) + (s.traffic_limit_gb ? " / " + esc(s.traffic_limit_gb) + " ГБ" : "");
   var trafficBar = "";
   if (s.traffic_limit_gb) {
     var pct = Math.min(100, Math.round(s.traffic_used / (s.traffic_limit_gb * 1024 * 1024 * 1024) * 100));
     trafficBar = '<div class="bar"><div class="bar-fill' + (pct >= 100 ? " full" : "") +
                  '" style="width:' + pct + '%"></div></div>' +
                  '<div class="bar-note"><span>Использовано ' + pct + "%</span><span>" + traffic + "</span></div>";
   }

   // Главная карточка: статус и сколько осталось
   out.push('<div data-sec="sub" class="sub-hero"><div class="card hero">' +
            '<div class="hero-head"><span class="plan">' + plan + "</span>" + mark + "</div>" +
            '<div class="big">' + big + "</div>" +
            '<div class="big-sub">' + bigSub + "</div>" +
            '<div class="stats">' +
              stat(esc(s.until), "действует до") +
              stat(s.devices_limit ? "до " + esc(s.devices_limit) : "∞", "устройств") +
              stat(traffic || "—", s.traffic_limit_gb ? "трафик" : "трафик · безлимит") +
            "</div>" + trafficBar +
            '<div class="stack" style="margin-top:16px"><button class="btn btn-main" type="button" id="renew-open">' +
            ICON.card + "Продлить подписку</button></div>" +
            "</div></div>");

   // Продление: тарифы и оплата прямо здесь, без ухода в бот
   out.push('<div data-sec="sub"><div class="card" id="renew-card">' + title("card", "Продление") +
            '<div id="renew-body"><p class="card-sub">Загружаем тарифы…</p></div></div></div>');

   // Детали подписки: что не влезло в главную карточку
   var details = [row("Продлений", esc(s.renewed))];
   if (s.created_at) { details.push(row("Подписка с", esc(s.created_at))); }
   if (s.devices_extra) { details.push(row("Докуплено мест", "+" + esc(s.devices_extra))); }
   out.push('<div data-sec="sub"><div class="card">' + title("key", "О подписке") +
            '<p class="card-sub">Цифры на сейчас — кнопка «Обновить» внизу пересчитает их.</p>' +
            details.join("") + "</div></div>");

   // LTE: остаток за текущий месяц, как в боте на экране «LTE-интернет»
   if (p.lte && p.lte.available) {
     var lteBody;
     if (p.lte.closed) {
       lteBody = '<p class="card-sub">LTE-серверы для этой подписки закрыты.</p>';
     } else {
       var lpct = Math.min(100, Math.round(p.lte.used / (p.lte.limit_gb * 1024 * 1024 * 1024) * 100));
       lteBody = '<p class="card-sub">Использовано ' + esc(p.lte.used_text) + " из " +
                 esc(p.lte.limit_gb) + " ГБ · осталось <b style=\"color:#fff\">" +
                 esc(p.lte.left_gb) + " ГБ</b></p>" +
                 '<div class="bar"><div class="bar-fill' + (lpct >= 100 ? " full" : "") +
                 '" style="width:' + lpct + '%"></div></div>' +
                 '<div class="bar-note"><span>Лимит обновляется каждый месяц</span><span>' + lpct + "%</span></div>" +
                 (p.lte.fallback_active
                   ? '<p class="card-sub" style="margin-top:12px">⚠️ LTE на этот месяц закончился — ' +
                     "сейчас работают обычные серверы, в новом месяце LTE вернётся.</p>"
                   : "");
     }
     out.push('<div data-sec="lte"><div class="card">' + title("lock", "LTE-интернет") + lteBody + "</div></div>");
   }

   // Подключение: приложение в одно нажатие и ссылка с копированием
   out.push('<div data-sec="sub"><div class="card">' + title("key", "Подключение") +
            '<p class="card-sub">Добавьте подписку в приложение одним нажатием.</p>' +
            '<div class="pair">' +
              '<a class="btn btn-main" target="_blank" rel="noopener" href="' + esc(location.origin + "/add.html?app=happ&u=" + encodeURIComponent(s.url)) + '" onclick="return openAppLink(this)">Добавить в Happ</a>' +
              '<a class="btn btn-ghost" target="_blank" rel="noopener" href="' + esc(location.origin + "/add.html?app=incy&u=" + encodeURIComponent(s.url)) + '" onclick="return openAppLink(this)">Добавить в INCY</a>' +
            "</div>" +
            '<div class="link"><code id="suburl">' + esc(s.url) + "</code>" +
            '<button class="copy" type="button" data-copy="' + esc(s.url) + '">Скопировать</button></div>' +
            "</div></div>");

   // Устройства: каждое можно отключить прямо здесь
   var devList = (p.devices || []).map(function (x) {
     return '<div class="dev"><div><b>' + esc(x.model) + "</b><small>" +
            esc(x.seen || "был недавно") + "</small></div>" +
            '<button class="btn-mini" type="button" data-del="' + esc(x.id) +
            '" data-name="' + esc(x.model) + '">Отключить</button></div>';
   }).join("");
   out.push('<div data-sec="devices"><div class="card">' + title("dev", "Мои устройства") +
            '<p class="card-sub">Подключено: ' + (p.devices ? p.devices.length : 0) +
            (s.devices_limit ? " из " + esc(s.devices_limit) : "") +
            (s.devices_limit && p.devices && p.devices.length >= s.devices_limit
              ? " · все места заняты" : "") + "</p>" +
            (devList || '<p class="card-sub">Пока ни одного — подключитесь в приложении.</p>') + "</div></div>");

   // Действия: перевыпуск ключа — как кнопка «Новый ключ» в боте
   if ((s.status === "active" || s.status === "renewal") && s.enabled) {
     out.push('<div data-sec="sub"><div class="card">' + title("key", "Действия") +
              '<p class="card-sub">Старая ссылка перестанет работать на всех устройствах — ' +
              "пригодится, если она попала в чужие руки.</p>" +
              '<button class="btn btn-ghost btn-danger" type="button" id="reissue">🔁 Новый ключ</button></div></div>');
   }


   var ref = referralCard(p);
   if (ref) { out.push('<div data-sec="friends">' + ref + "</div>"); }
   out.push(profileCard(p));

   out.push('<div class="stack" style="margin-top:6px">' +
            '<button class="btn btn-ghost" type="button" onclick="load()">🔄 Обновить данные</button>' +
            '<a class="btn btn-ghost" href="' + botUrl() + '">' +
            ICON.tg + "Открыть бота</a></div>");
   document.getElementById("body").innerHTML = '<div class="tabs" id="tabs"></div><div class="breadcrumb" id="breadcrumb"></div>' + out.join("");
   buildTabs();
   bindActions();
 }

 // Разделы: лента вкладок собирается из того, что реально есть на странице.
 // Один раздел — ленту не показываем, запоминаем выбор между заходами.
 // Разделы открываются и прямыми ссылками: /cabinet/lte, /cabinet/devices
 // и т.д. — адрес из ссылки важнее запомненного. Переключение вкладок
 // тихое: раздел меняется на месте, без перезагрузки, а адрес просто
 // подстраивается под текущий раздел, чтобы ссылку можно было взять.
 var SEC_LABELS = {sub: "Подписка", lte: "LTE", devices: "Устройства",
                   payments: "Платежи", friends: "Друзья", profile: "Профиль"};
 function cabinetBase() {
   var p = location.pathname.replace(/\/+$/, "");
   if (p.slice(-13) === "/cabinet.html") { return p.slice(0, -13) + "/cabinet"; }
   var i = p.lastIndexOf("/cabinet");
   return i !== -1 ? p.slice(0, i + 8) : "/cabinet";
 }
 function sectionFromPath() {
   var parts = location.pathname.replace(/\/+$/, "").split("/");
   var last = parts[parts.length - 1];
   return (last && last !== "cabinet" && last !== "cabinet.html") ? last : "";
 }
 function buildTabs() {
   var tabs = document.getElementById("tabs");
   if (!tabs) { return; }
   var seen = [];
   document.querySelectorAll("#body [data-sec]").forEach(function (el) {
     var name = el.getAttribute("data-sec");
     if (seen.indexOf(name) === -1) { seen.push(name); }
   });
   if (seen.length <= 1) { tabs.style.display = "none"; return; }
   tabs.style.display = "";
   var saved = "";
   try { saved = localStorage.getItem("drebol_tab") || ""; } catch (e) {}
   var pathSec = sectionFromPath();
   var active = seen.indexOf(pathSec) !== -1 ? pathSec
     : seen.indexOf(saved) !== -1 ? saved : seen[0];
   tabs.innerHTML = "";
   seen.forEach(function (name) {
     var b = document.createElement("button");
     b.className = "tab" + (name === active ? " active" : "");
     b.type = "button";
     b.textContent = SEC_LABELS[name] || name;
     if (name === "profile" && window.LOGIN && (!window.LOGIN.email || !window.LOGIN.has_password)) {
       var d = document.createElement("span");
       d.className = "dot";
       d.title = "Задайте почту и пароль";
       b.appendChild(d);
     }
     b.onclick = function () { showTab(name); };
     tabs.appendChild(b);
   });
   showTab(active, true);
   if (seen.indexOf(pathSec) !== -1) {
     try { localStorage.setItem("drebol_tab", pathSec); } catch (e) {}
   }
 }
 function showTab(name, silent) {
   var bodyEl = document.getElementById("body");
   if (bodyEl) { bodyEl.classList.toggle("tab-sub", name === "sub"); }
   document.querySelectorAll("#body [data-sec]").forEach(function (el) {
     var show = el.getAttribute("data-sec") === name;
     el.style.display = show ? "" : "none";
     if (show) {
       // перезапускаем анимацию появления при каждом переключении
       el.classList.remove("sec-show");
       void el.offsetWidth;
       el.classList.add("sec-show");
     }
   });
   document.querySelectorAll("#tabs .tab").forEach(function (b) {
     b.classList.toggle("active", b.textContent === (SEC_LABELS[name] || name));
   });
   var bc = document.getElementById("breadcrumb");
   if (bc) { bc.innerHTML = '<span>Кабинет</span> <span style="opacity:.4">/</span> <span>' + (SEC_LABELS[name] || name) + '</span>'; }
   if (!silent) {
     try { localStorage.setItem("drebol_tab", name); } catch (e) {}
     try { history.replaceState(null, "", cabinetBase() + "/" + name); } catch (e) {}
   }
 }

 // Рефералка: статистика и ссылка — имя бота страница уже знает (BOT)
 function referralCard(p) {
   if (!p.referral) { return ""; }
   var r = p.referral;
   var link = "https://t.me/" + BOT + "?start=ref_" + p.user.id;
   var share = "https://t.me/share/url?url=" + encodeURIComponent(link) +
               "&text=" + encodeURIComponent("Попробуй Drebol VPN — быстрый и безопасный VPN!");
   return '<div class="card">' + title("tg", "Приглашайте друзей") +
     '<p class="card-sub">Приглашено: <b style="color:#fff">' + esc(r.invited) + "</b>" +
     " · бонус получили: <b style=\"color:#fff\">" + esc(r.rewarded) + "</b>" +
     (r.bonus_text ? " · вам начислено: <b style=\"color:#fff\">+" + esc(r.bonus_text) + "</b>" : "") + "</p>" +
     '<div class="link"><code id="reflink">' + esc(link) + "</code>" +
     '<button class="copy" type="button" data-copy="' + esc(link) + '">Скопировать</button></div>' +
     '<div class="stack" style="margin-top:12px"><a class="btn btn-ghost" href="' + share +
     '">📤 Поделиться ссылкой</a></div></div>';
 }

 // Кнопки действий после отрисовки: отключение устройства и перевыпуск
 function bindActions() {
   document.querySelectorAll("[data-del]").forEach(function (btn) {
     btn.onclick = function () {
       var name = btn.getAttribute("data-name") || "это устройство";
       if (!confirm("Отключить " + name + "? Оно потеряет доступ, слот освободится.")) { return; }
       btn.disabled = true; btn.textContent = "Отключаем…";
       api("/api/device/delete", {method: "POST",
           body: JSON.stringify({hwid: btn.getAttribute("data-del")})})
         .then(function (r) {
           if (r.status === 200) { return load(); }
           alert(r.data && r.data.error === "already_gone"
             ? "Это устройство уже отключено." : "Не получилось — попробуйте позже.");
           load();
         })
         .catch(function () { alert("Не получилось — попробуйте позже."); load(); });
     };
   });
   var re = document.getElementById("reissue");
   if (re) {
     re.onclick = function () {
       if (!confirm("Перевыпустить ключ? Старая ссылка перестанет работать на всех устройствах, " +
                    "новую нужно будет заново вставить в приложение.")) { return; }
       re.disabled = true; re.textContent = "Перевыпускаем…";
       api("/api/reissue", {method: "POST", body: "{}"})
         .then(function (r) {
           if (r.status === 200) { alert("Готово — новая ссылка уже в карточке «Подключение»."); }
           else { alert("Не получилось — попробуйте позже."); }
           load();
         })
         .catch(function () { alert("Не получилось — попробуйте позже."); load(); });
     };
   }
   var ro = document.getElementById("renew-open");
   if (ro) {
     ro.onclick = function () {
       var c = document.getElementById("renew-card");
       if (c) { c.scrollIntoView({behavior: "smooth", block: "start"}); }
       loadRenew();
     };
   }
   if (document.getElementById("renew-card")) { loadRenew(); }

   // Профиль: смена почты и пароля — формы перерисовываются при каждой
   // загрузке, поэтому привязка здесь же, после каждой отрисовки.
   var pef = document.getElementById("prof-email-form");
   if (pef) {
     pef.addEventListener("submit", function (e) {
       e.preventDefault();
       var v = document.getElementById("prof-email").value.trim();
       var note = document.getElementById("prof-note");
       note.textContent = "Сохраняем…";
       api("/api/profile/email", {method: "POST", body: JSON.stringify({email: v})})
         .then(function (r) {
           if (r.status === 200) { note.textContent = "Почта сохранена."; load(); return; }
           if (r.data && r.data.error === "email_taken") {
             note.textContent = "Эта почта уже привязана к другому человеку."; return;
           }
           if (r.data && r.data.error === "bad_email") {
             note.textContent = "Проверьте почту — похоже, опечатка."; return;
           }
           note.textContent = "Не получилось — попробуйте позже.";
         })
         .catch(function () { note.textContent = "Не получилось — попробуйте позже."; });
     });
   }
   var ppf = document.getElementById("prof-pass-form");
   if (ppf) {
     ppf.addEventListener("submit", function (e) {
       e.preventDefault();
       var cur = document.getElementById("prof-cur");
       var nw = document.getElementById("prof-new").value;
       var note = document.getElementById("prof-note");
       if (nw.length < 8) { note.textContent = "Пароль — от 8 символов."; return; }
       note.textContent = "Сохраняем…";
       api("/api/profile/password", {method: "POST",
           body: JSON.stringify({current: cur ? cur.value : "", password: nw})})
         .then(function (r) {
           if (r.status === 200) { note.textContent = "Пароль сохранён."; load(); return; }
           if (r.data && r.data.error === "bad_current") {
             note.textContent = "Неверный текущий пароль."; return;
           }
           if (r.data && r.data.error === "bad_password") {
             note.textContent = "Пароль — от 8 символов."; return;
           }
           note.textContent = "Не получилось — попробуйте позже.";
         })
         .catch(function () { note.textContent = "Не получилось — попробуйте позже."; });
     });
   }
 }

 // Продление: тарифы, счёт, ожидание подтверждения. Подтверждение
 // приходит вебхуком anore, а опрос — страховка: страница опрашивает
 // статус счёта каждые 10 секунд, пока ждёт.
 var renewTimer = null;
 var renewPayUrl = "";
 var pendingPayUrl = "";
 function stopRenewPoll() { if (renewTimer) { clearTimeout(renewTimer); renewTimer = null; } }
 function openPay(url) {
   if (tg && tg.openLink) { tg.openLink(url); }
   else { window.open(url, "_blank"); }
 }
 // Кнопки «Добавить в Happ/INCY» в мини-приложении не работали: WebView
 // Telegram проглатывает ссылки happ:// и incy:// — тап никуда не вёл.
 // Поэтому ведём через страницу-переходник /add.html — ту же, что в кнопках
 // бота: она откроется в браузере и сама уведёт в приложение, а если его
 // нет — покажет кнопку App Store.
 function openAppLink(el) {
   if (tg && tg.openLink) { tg.openLink(el.href); return false; }
   return true;
 }
 function loadRenew() {
   stopRenewPoll();
   var body = document.getElementById("renew-body");
   if (!body) { return; }
   api("/api/renew-options").then(function (r) {
     if (r.status !== 200 || !r.data.tariffs) {
       body.innerHTML = '<p class="card-sub">Продление сейчас недоступно. ' +
                        "Попробуйте позже или продлите в боте.</p>";
       return;
     }
     var d = r.data;
     var html = "";
     if (d.promo) {
       html += '<p class="card-sub">🎟 Промокод ' + esc(d.promo.code) + " (−" +
               esc(d.promo.percent) + "%) уже учтён в цене.</p>";
     }
     if (d.devices && d.devices.count && d.devices.price) {
       html += '<p class="card-sub">В цену включены ваши места: ' + esc(d.devices.count) +
               " × " + esc(d.devices.price) + " ₽.</p>";
     }
     if (d.pending) {
       pendingPayUrl = d.pending.url;
       html += '<p class="card-sub">⏳ У вас есть неоплаченный счёт на <b style="color:#fff">' +
               esc(d.pending.amount) + " ₽</b>.</p>" +
               '<div class="stack"><button class="btn btn-main" type="button" ' +
               'onclick="openPay(pendingPayUrl)">Продолжить оплату</button>' +
               '<button class="btn btn-ghost" type="button" onclick="pollPayment(' +
               d.pending.id + ', 90)">Проверить оплату</button></div>';
     }
     html += '<p class="card-sub">Выберите тариф — счёт создастся здесь же, оплата через платёжную систему.</p>';
     d.tariffs.forEach(function (t) {
       html += '<button class="btn btn-ghost renew-tariff" type="button" style="margin-top:8px" onclick="renewPay(' +
               t.id + ')">' + esc(t.period) + ' — <b class="rt-price">' +
               esc(t.price) + " ₽</b></button>";
     });
     body.innerHTML = html;
   }).catch(function () {
     body.innerHTML = '<p class="card-sub">Не получилось загрузить тарифы. Попробуйте позже.</p>';
   });
 }
 function renewPay(tariffId) {
   var body = document.getElementById("renew-body");
   if (!body) { return; }
   body.innerHTML = '<p class="card-sub">Создаём счёт…</p>';
   api("/api/renew", {method: "POST", body: JSON.stringify({tariff_id: tariffId})})
     .then(function (r) {
       if (r.status !== 200 || !r.data.url) {
         var msg = "Не получилось создать счёт. Попробуйте позже.";
         if (r.data.error === "bad_tariff") { msg = "Тариф больше недоступен."; }
         else if (r.data.error === "pay_unavailable") { msg = "Оплата временно недоступна."; }
         body.innerHTML = '<p class="card-sub">' + msg + '</p>' +
           '<button class="btn btn-ghost" type="button" onclick="loadRenew()">Попробовать ещё раз</button>';
         return;
       }
       renewPayUrl = r.data.url;
       body.innerHTML = '<div id="renew-wait"><p class="card-sub">Счёт на <b style="color:#fff">' +
         esc(r.data.amount) + " ₽</b> готов. Оплатите его — подтверждение придёт само, " +
         "обычно в течение минуты.</p>" +
         '<button class="btn btn-main" type="button" onclick="openPay(renewPayUrl)">Оплатить</button></div>';
       openPay(r.data.url);
       pollPayment(r.data.payment_id, 90);
     })
     .catch(function () {
       body.innerHTML = '<p class="card-sub">Не получилось создать счёт. Попробуйте позже.</p>' +
         '<button class="btn btn-ghost" type="button" onclick="loadRenew()">Попробовать ещё раз</button>';
     });
 }
 function pollPayment(id, tries) {
   stopRenewPoll();
   api("/api/payment?id=" + id).then(function (r) {
     var box = document.getElementById("renew-wait");
     if (r.status !== 200) {
       if (box) { box.innerHTML = '<p class="card-sub">Не удалось проверить статус. Попробуйте позже.</p>'; }
       return;
     }
     var st = r.data.status;
     if (st === "paid" || st === "refund_pending") {
       if (box) { box.innerHTML = '<p class="card-sub">✅ Оплата прошла! Обновляем данные…</p>'; }
       load();
       return;
     }
     if (st === "canceled" || st === "expired" || st === "error" ||
         st === "refunded" || st === "chargebacked") {
       if (box) { box.innerHTML = '<p class="card-sub">Счёт не оплачен. Создайте новый счёт.</p>' +
         '<button class="btn btn-ghost" type="button" onclick="loadRenew()">К тарифам</button>'; }
       return;
     }
     if (tries <= 0) {
       if (box) { box.innerHTML = '<p class="card-sub">Пока не оплачено. Если вы уже оплатили, ' +
         'подождите немного и нажмите «Проверить».</p>' +
         '<button class="btn btn-ghost" type="button" onclick="pollPayment(' + id + ', 90)">Проверить</button>'; }
       return;
     }
     renewTimer = setTimeout(function () { pollPayment(id, tries - 1); }, 10000);
   }).catch(function () {
     renewTimer = setTimeout(function () { pollPayment(id, tries - 1); }, 10000);
   });
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
   stopRenewPoll();
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
   if (TS_KEY) {
     document.getElementById("pwblock").classList.remove("hide");
     tsLoad();
   }
 }

 document.getElementById("out").onclick = function () {
   api("/api/logout", {method: "POST"});
   setToken("");
   location.reload();
 };

 // Вход по почте и паролю и сброс пароля — формы на экране входа,
 // привязка один раз при загрузке страницы.
 (function bindLoginForms() {
   var pwf = document.getElementById("pwform");
   if (pwf) {
     pwf.addEventListener("submit", function (e) {
       e.preventDefault();
       var email = document.getElementById("pw-email").value.trim();
       var pass = document.getElementById("pw-pass").value;
       var cap = tsToken("pw");
       if (!cap) { say("Подтвердите, что вы не робот — нажмите на капчу."); return; }
       say("Входим…");
       api("/api/auth/password", {method: "POST",
           body: JSON.stringify({email: email, password: pass, captcha: cap})})
         .then(function (r) {
           tsReset("pw");
           if (r.status === 200 && r.data.token) { setToken(r.data.token); return load(); }
           if (r.status === 401) { say("Неверная почта или пароль."); return; }
           if (r.status === 429) { say("Слишком много попыток. Подождите 15 минут."); return; }
           if (r.status === 403) { say("Капча не пройдена. Попробуйте ещё раз."); return; }
           if (r.status === 503) { say("Вход по почте пока не настроен."); return; }
           fail("войти", "ответ " + r.status);
         })
         .catch(function (e) { tsReset("pw"); fail("связаться с кабинетом", e); });
     });
   }
   var fo = document.getElementById("forgot-open");
   if (fo) {
     fo.onclick = function () {
       document.getElementById("pwform").classList.add("hide");
       fo.classList.add("hide");
       document.getElementById("forgotform").classList.remove("hide");
       say("");
     };
   }
   var fb = document.getElementById("forgot-back");
   if (fb) {
     fb.onclick = function () {
       document.getElementById("forgotform").classList.add("hide");
       document.getElementById("fg-code-wrap").classList.add("hide");
       document.getElementById("pwform").classList.remove("hide");
       document.getElementById("forgot-open").classList.remove("hide");
       document.getElementById("pw-note").textContent = "";
       say("");
     };
   }
   var fgf = document.getElementById("forgotform");
   if (fgf) {
     fgf.addEventListener("submit", function (e) {
       e.preventDefault();
       var email = document.getElementById("fg-email").value.trim();
       var cap = tsToken("fg");
       if (!cap) { say("Подтвердите, что вы не робот — нажмите на капчу."); return; }
       say("Отправляем код в Telegram…");
       api("/api/auth/forgot", {method: "POST",
           body: JSON.stringify({email: email, captcha: cap})})
         .then(function (r) {
           tsReset("fg");
           if (r.status === 200) {
             say("");
             document.getElementById("fg-code-wrap").classList.remove("hide");
             document.getElementById("pw-note").textContent =
               "Код отправлен в Telegram. Если его нет — проверьте, что почта та же, что в профиле.";
             return;
           }
           if (r.status === 429) { say("Слишком много запросов. Подождите 15 минут."); return; }
           if (r.status === 403) { say("Капча не пройдена. Попробуйте ещё раз."); return; }
           if (r.status === 503) { say("Сброс пароля пока не настроен."); return; }
           fail("отправить код", "ответ " + r.status);
         })
         .catch(function (e) { tsReset("fg"); fail("связаться с кабинетом", e); });
     });
   }
   var fr = document.getElementById("fg-reset");
   if (fr) {
     fr.onclick = function () {
       var email = document.getElementById("fg-email").value.trim();
       var code = document.getElementById("fg-code").value.trim();
       var pass = document.getElementById("fg-pass").value;
       if (!code) { say("Введите код из Telegram."); return; }
       if (pass.length < 8) { say("Новый пароль — от 8 символов."); return; }
       say("Меняем пароль…");
       api("/api/auth/reset", {method: "POST",
           body: JSON.stringify({email: email, code: code, password: pass})})
         .then(function (r) {
           if (r.status === 200) {
             say("");
             document.getElementById("forgotform").classList.add("hide");
             document.getElementById("fg-code-wrap").classList.add("hide");
             document.getElementById("pwform").classList.remove("hide");
             document.getElementById("forgot-open").classList.remove("hide");
             document.getElementById("pw-note").textContent = "Пароль сменён — войдите с новым паролем.";
             return;
           }
           if (r.status === 401) { say("Неверный код. Проверьте и попробуйте ещё раз."); return; }
           fail("сменить пароль", "ответ " + r.status);
         })
         .catch(function (e) { fail("связаться с кабинетом", e); });
     };
   }
 })();

 if (tg && tg.initData) {
   tg.ready(); tg.expand();
   // внутри Telegram красим шапку в цвет страницы
   try { tg.setHeaderColor("#020202"); tg.setBackgroundColor("#020202"); } catch (e) {}
   // Безопасная зона Telegram: в полном экране шапка клиента
   // (закрыть, меню) висит поверх страницы. Скрипт Telegram сам
   // выставляет --tg-content-safe-area-inset-top, но на старых
   // клиентах переменной может не быть — продублируем её из
   // contentSafeAreaInset и обновим при изменении зоны.
   (function applySafeArea() {
     try {
       var top = tg.contentSafeAreaInset && tg.contentSafeAreaInset.top;
       if (typeof top === "number" && top > 0) {
         document.documentElement.style.setProperty(
           "--tg-content-safe-area-inset-top", top + "px");
       }
     } catch (e) {}
   })();
   try {
     if (tg.onEvent) {
       tg.onEvent("contentSafeAreaChanged", function () {
         try {
           var top = tg.contentSafeAreaInset && tg.contentSafeAreaInset.top;
           if (typeof top === "number") {
             document.documentElement.style.setProperty(
               "--tg-content-safe-area-inset-top", top + "px");
           }
         } catch (e) {}
       });
     }
   } catch (e) {}
   if (token()) { load(); } else { login({initData: tg.initData}); }
 } else if (token()) {
   load();
 } else {
   showLogin();
 }
</script></body></html>
"""


def cabinet_page(bot_username: str) -> str:
    """Готовая страница кабинета: подставлены адрес API, имя бота и точный логотип с основного сайта."""
    from config import load_config, turnstile_keys
    from web.site_page import FAVICON_URL, LOGO_URL
    api = (load_config().get("webapi_public") or "").rstrip("/")
    logo_html = f'<img src="{LOGO_URL}" alt="Drebol VPN" width="760" height="346">'
    return (CABINET_PAGE.replace("__API__", api or "")
            .replace("__BOT__", bot_username or "")
            .replace("__LOGO__", logo_html)
            .replace("__FAVICON__", FAVICON_URL)
            .replace("__TURNSTILE__", turnstile_keys()[0]))


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


def seo_files() -> tuple[str, str]:
    """robots.txt и sitemap.xml для поисковиков.

    Без них сайт не находится в поиске: краулеры не знают, что
    индексировать можно, а карты сайта просто нет. Домен берём из
    настроек сайта — тот же, что в nginx. В карте только лендинг:
    кабинет без сессии Telegram поисковику не нужен.
    """
    from datetime import date
    base = site_url().rstrip("/")
    # /api/ — не страницы, а ручки кабинета: без сессии отдают 401,
    # а поисковику там делать нечего. Без запрета Googlebot лезет туда
    # при рендере кабинета и жалуется на 401 в Search Console.
    robots = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        + (f"Sitemap: {base}/sitemap.xml\n" if base else "")
    )
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        f"    <loc>{base}/</loc>\n"
        f"    <lastmod>{date.today().isoformat()}</lastmod>\n"
        "    <changefreq>weekly</changefreq>\n"
        "    <priority>1.0</priority>\n"
        "  </url>\n"
        "</urlset>\n"
    )
    return robots, sitemap


# Файл подтверждения Google Search Console. Google проверяет его при
# каждом подтверждении прав на сайт — не удалять и не переименовывать.
GOOGLE_VERIFICATION_FILE = "google7280fa10130c903e.html"
GOOGLE_VERIFICATION_CONTENT = "google-site-verification: google7280fa10130c903e.html"

# /favicon.ico на сервере: тот же «e», что в шапке сайта, в формате ICO.
# Сгенерирован из drebol-favicon-e.png (64x64). Браузеры и Googlebot
# запрашивают /favicon.ico по умолчанию — без файла это 404.
FAVICON_ICO_B64 = (
    "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"
    "iON+Ag6y3Ww1aVmhAAAAAElFTkSuQmCC"
)


def app_version_json() -> str:
    """Манифест версий приложения для автообновления в самом приложении.

    Файл web/app-version.json лежит в репозитории; при каждом обновлении
    сайта он уезжает на сервер как /app/version.json. Приложение сверяет
    versionCode со своим и, если на сервере новее, качает APK по apkUrl.
    Сам APK (drebolapp.apk) в репозитории НЕ лежит — он кладётся в
    {WEB_ROOT} вручную, deploy его не трогает.
    """
    path = os.path.join(PROJECT_DIR, "web", "app-version.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "{}"


def _deploy_sync(page: str, og_bytes: bytes, logo_bytes: bytes = b"",
                 cabinet: str = "", pay_pages: dict | None = None) -> dict:
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
            for kind in ("success", "fail", "back"):
                if pay_pages and pay_pages.get(kind):
                    with sftp.open(f"/tmp/drebol_pay_{kind}.html", "w") as f:
                        f.write(pay_pages[kind])
            robots_txt, sitemap_xml = seo_files()
            with sftp.open("/tmp/drebol_robots.txt", "w") as f:
                f.write(robots_txt)
            with sftp.open("/tmp/drebol_sitemap.xml", "w") as f:
                f.write(sitemap_xml)
            with sftp.open("/tmp/drebol_google_verification.html", "w") as f:
                f.write(GOOGLE_VERIFICATION_CONTENT)
            if logo_bytes:
                with sftp.open("/tmp/drebol_logo", "wb") as f:
                    f.write(logo_bytes)
            # /favicon.ico: браузеры и Googlebot запрашивают его по
            # умолчанию — без файла на сервере это 404 и жалоба в
            # Search Console. Тот же «e», что и в шапке, в формате ICO.
            with sftp.open("/tmp/drebol_favicon.ico", "wb") as f:
                f.write(base64.b64decode(FAVICON_ICO_B64))
            # Манифест версий приложения: /app/version.json для
            # автообновления в самом приложении (см. app_version_json).
            with sftp.open("/tmp/drebol_app_version.json", "w") as f:
                f.write(app_version_json())
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
mv /tmp/drebol_robots.txt {WEB_ROOT}/robots.txt
mv /tmp/drebol_sitemap.xml {WEB_ROOT}/sitemap.xml
mv /tmp/drebol_google_verification.html {WEB_ROOT}/{GOOGLE_VERIFICATION_FILE}
# Кабинет — по чистому адресу /cabinet: nginx отдаёт index.html из папки
# сам (try_files $uri $uri/). Старый cabinet.html оставляем — закладки
# и старые кнопки из бота не сломаются. Разделы — отдельными адресами
# /cabinet/lte, /cabinet/devices и т.д.: та же страница, нужный раздел
# она выбирает сама по адресу (см. sectionFromPath в её JS).
mkdir -p {WEB_ROOT}/cabinet
cp /tmp/drebol_cabinet.html {WEB_ROOT}/cabinet/index.html
for sec in sub lte devices payments friends profile; do
  mkdir -p {WEB_ROOT}/cabinet/$sec
  cp /tmp/drebol_cabinet.html {WEB_ROOT}/cabinet/$sec/index.html
done
mv /tmp/drebol_cabinet.html {WEB_ROOT}/cabinet.html
chmod 644 {WEB_ROOT}/add.html {WEB_ROOT}/cabinet.html {WEB_ROOT}/cabinet/index.html
chmod 644 {WEB_ROOT}/cabinet/*/index.html || true
# Страницы редиректов после оплаты: /pay/success/, /pay/fail/, /pay/back/
for kind in success fail back; do
  if [ -f /tmp/drebol_pay_$kind.html ]; then
    mkdir -p {WEB_ROOT}/pay/$kind
    mv /tmp/drebol_pay_$kind.html {WEB_ROOT}/pay/$kind/index.html
    chmod 644 {WEB_ROOT}/pay/$kind/index.html
  fi
done
[ -f /tmp/drebol_logo ] && mv /tmp/drebol_logo {WEB_ROOT}/{LOGO_NAME} || true
mv /tmp/drebol_favicon.ico {WEB_ROOT}/favicon.ico
# Манифест версий приложения: /app/version.json. Сам APK
# (drebolapp.apk) сюда НЕ заливается — он лежит в {WEB_ROOT} отдельно,
# deploy его не трогает.
mkdir -p {WEB_ROOT}/app
mv /tmp/drebol_app_version.json {WEB_ROOT}/app/version.json
chmod 644 {WEB_ROOT}/index.html {WEB_ROOT}/og.webp {WEB_ROOT}/robots.txt {WEB_ROOT}/sitemap.xml {WEB_ROOT}/{GOOGLE_VERIFICATION_FILE} {WEB_ROOT}/favicon.ico {WEB_ROOT}/app/version.json
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
        from core.database import list_tariffs
        from paidsub.time_parser import fmt_duration
        rows = await list_tariffs()
        # имя тарифа больше нигде не показывается — в карточке срок,
        # а цена рядом; кладём срок и в поле name, чтобы старые снапшоты
        # страницы, ждущие name, тоже показывали срок, а не пустоту
        tariffs = [{"name": fmt_duration(period), "price": price, "period": fmt_duration(period)}
                   for _, _name, period, price, is_active, _ in rows if is_active]
        return tariffs
    except Exception:
        return []


async def build_current(bot_username: str) -> tuple:
    """Страница по текущим данным бота и файлы, которые едут вместе с ней.

    Одна сборка на всех: и кнопка «Обновить», и автообновление смотрят
    ровно на то, что окажется на сервере.
    """
    from web.site_page import LOGO_URL, build_page
    cfg = load_config()
    og_bytes = _asset("og.webp")
    # /logo.png на сервере — новый логотип (тот же base64, что в шапке
    # сайта): его же можно вставить в настройки платёжной формы anore.
    # assets/logo.png — старый логотип, его сюда больше не кладём.
    try:
        logo_bytes = base64.b64decode(LOGO_URL.split(",", 1)[1])
    except Exception:
        logo_bytes = _asset(LOGO_NAME)
    # кабинет лежит рядом со страницей — ссылка относительная, без .html
    cabinet = "cabinet" if cfg.get("webapi_public") else ""
    page = build_page(
        bot_username=bot_username,
        cabinet_url=cabinet,
        privacy_url=cfg.get("privacy_url", "") or "",
        terms_url=cfg.get("terms_url", "") or "",
        channel_url=cfg.get("channel_url", "") or "",
        # Логотип — тот же файл, что и на странице подписки: прямая ссылка
        # на assets/logo.png в репозитории. /logo.png на сервере не берём:
        # там лежит залитый когда-то через бота кадр шёлковой картинки.
        logo_file=LOGO_URL,
        tariffs=await site_tariffs(cfg),
        poster_file="og.webp" if og_bytes else "",
        site_texts=cfg.get("site_texts") or {},
    )
    return page, og_bytes, logo_bytes


def cabinet_ready() -> bool:
    """Кабинет опубликован: есть домен, адрес API и страница уже уехала."""
    c = creds()
    cfg = load_config()
    return bool(c["domain"] and cfg.get("webapi_public") and cfg.get("site_cabinet"))


def cabinet_link() -> str:
    return f"{site_url()}/cabinet" if cabinet_ready() else ""


def pay_redirect_urls() -> dict:
    """Адреса страниц редиректов после оплаты на сайте.

    Пусто, если домен не задан, — тогда действуют редиректы магазина
    (t.me/drebolvpn_bot) или возврат в кабинет.
    """
    base = site_url().rstrip("/")
    if not base:
        return {}
    return {
        "success": f"{base}/pay/success/",
        "fail": f"{base}/pay/fail/",
        "back": f"{base}/pay/back/",
    }


def page_hash(page: str, og_bytes: bytes, logo_bytes: bytes, cabinet: str = "",
              pay: str = "") -> str:
    """Отпечаток того, что должно лежать на сервере.

    По нему автообновление понимает, поменялось ли хоть что-нибудь: цена
    тарифа, ссылка на канал, документы, логотип, сам кабинет. Не поменялось —
    не трогаем.
    """
    import hashlib
    h = hashlib.sha256()
    h.update(page.encode("utf-8"))
    h.update(og_bytes)
    h.update(logo_bytes)
    # адрес API кабинета тоже часть сайта: сменили — страницу надо перезалить
    h.update(str(load_config().get("webapi_public") or "").encode("utf-8"))
    h.update(cabinet.encode("utf-8"))
    h.update(pay.encode("utf-8"))
    # фавикон и robots.txt тоже едут на сервер — их смена должна
    # вызывать перезалив, а не молча пропускаться автообновлением
    h.update(base64.b64decode(FAVICON_ICO_B64))
    h.update(seo_files()[0].encode("utf-8"))
    # манифест версий приложения тоже едет на сервер
    h.update(app_version_json().encode("utf-8"))
    return h.hexdigest()


async def deploy(bot_username: str) -> dict:
    """Собирает страницу и раскатывает её на сервер."""
    from web.site_page import build_pay_pages
    page, og_bytes, logo_bytes = await build_current(bot_username)
    cabinet = cabinet_page(bot_username)
    pay_pages = build_pay_pages()
    pay = "".join(pay_pages[k] for k in ("success", "fail", "back"))
    res = await asyncio.to_thread(_deploy_sync, page, og_bytes, logo_bytes,
                                  cabinet, pay_pages)
    if res.get("ok"):
        # вместе со страницей уехал и переходник — можно показывать кнопки приложений
        save_creds(site_deployed_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                   site_page_hash=page_hash(page, og_bytes, logo_bytes, cabinet, pay),
                   site_add_page=True, site_cabinet=bool(load_config().get("webapi_public")))
    return res


async def _build_and_maybe_deploy(bot_username: str) -> tuple:
    """Собирает лендинг и кабинет, сравнивает отпечаток с сохранённым.

    Возвращает (статус, результат): "unchanged" — ничего не поменялось,
    сервер не трогаем; "deployed" — залили; "failed" — деплой не прошёл.
    Кабинет едет вместе со страницей: раньше автообновление заливало его
    пустым (аргумент не передавался), и кабинет бы стёрся.
    """
    from web.site_page import build_pay_pages
    page, og_bytes, logo_bytes = await build_current(bot_username)
    cabinet = cabinet_page(bot_username)
    pay_pages = build_pay_pages()
    pay = "".join(pay_pages[k] for k in ("success", "fail", "back"))
    fresh = page_hash(page, og_bytes, logo_bytes, cabinet, pay)
    if fresh == load_config().get("site_page_hash"):
        return "unchanged", None
    res = await asyncio.to_thread(_deploy_sync, page, og_bytes, logo_bytes,
                                  cabinet, pay_pages)
    if res.get("ok"):
        save_creds(site_deployed_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                   site_page_hash=fresh)
        return "deployed", res
    return "failed", res


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
        status, res = await _build_and_maybe_deploy(me.username)
    except Exception:
        return
    if status == "unchanged":
        return
    from core.log_channel import send_log
    if status == "deployed":
        await send_log(context.bot, "🌐 Сайт обновлён автоматически: данные изменились")
    else:
        # молчать нельзя: на сайте остались старые цены
        await send_log(context.bot,
            "⚠️ Сайт не обновился автоматически\n"
            f"<code>{escape(str(res.get('error'))[:300])}</code>")


async def site_update_pending_job(context):
    """После обновления бота с GitHub: проверить, поменялся ли сайт.

    Флаг site_update_pending ставит handle_git_update, когда в pull были
    правки сайта. Если собранная страница совпала с той, что на сервере, —
    сайт не трогаем. Это явное действие админа, поэтому настройка
    автообновления здесь не учитывается.
    """
    cfg = load_config()
    if not cfg.get("site_update_pending"):
        return
    cfg["site_update_pending"] = False
    save_config(cfg)
    if not configured() or not cfg.get("site_deployed_at"):
        return
    from core.log_channel import send_log
    try:
        me = await context.bot.get_me()
        status, res = await _build_and_maybe_deploy(me.username)
    except Exception as e:
        await send_log(context.bot,
            "⚠️ Не получилось проверить сайт после обновления бота\n"
            f"<code>{escape(str(e))[:300]}</code>")
        return
    if status == "deployed":
        await send_log(context.bot, "🌐 Сайт обновлён после обновления бота: в нём были изменения")
    elif status == "failed":
        await send_log(context.bot,
            "⚠️ Сайт не обновился после обновления бота\n"
            f"<code>{escape(str(res.get('error'))[:300])}</code>")
    else:
        await send_log(context.bot, "🌐 Сайт не менялся — после обновления бота его не трогали")


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
    """Старое имя экрана сайта: теперь это общий экран «Веб-доступ»."""
    from web.webapi import handle_web_menu
    await handle_web_menu(query)


async def handle_site_server(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.states import AWAITING_SITE_HOST
    context.user_data["state"] = AWAITING_SITE_HOST
    await query.edit_message_text(
        "🖥 <b>Сервер для сайта</b>  ·  <i>шаг 1 из 3</i>\n\n"
        "Пришли IP второго сервера.\n\n"
        "<i>Если SSH на другом порту — <code>1.2.3.4:2222</code></i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="site_menu")],
        ]),
    )


async def handle_site_domain(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.states import AWAITING_SITE_DOMAIN
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
    from core.log_channel import send_log
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


# ── Редактор текстов сайта ───────────────────────────────────────────────────

SITE_SECTIONS = {
    "hero": ("👑 Главный экран", [
        ("hero_pill", "Бейдж над заголовком"),
        ("hero_title", "Главный заголовок"),
        ("hero_shimmer", "Акцентный текст заголовка"),
        ("hero_lead", "Описание (лид)"),
        ("hero_btn", "Текст кнопки действия"),
        ("hero_hud_status", "Статус на постере"),
        ("hero_hud_speed", "Скорость на постере"),
    ]),
    "metrics": ("📊 Метрики сети (4 показателя)", [
        ("metric1_val", "Метрика 1: Число"),
        ("metric1_unit", "Метрика 1: Единица"),
        ("metric1_label", "Метрика 1: Название"),
        ("metric1_sub", "Метрика 1: Подпись"),
        ("metric2_val", "Метрика 2: Число"),
        ("metric2_unit", "Метрика 2: Единица"),
        ("metric2_label", "Метрика 2: Название"),
        ("metric2_sub", "Метрика 2: Подпись"),
        ("metric3_val", "Метрика 3: Число"),
        ("metric3_unit", "Метрика 3: Единица"),
        ("metric3_label", "Метрика 3: Название"),
        ("metric3_sub", "Метрика 3: Подпись"),
        ("metric4_val", "Метрика 4: Число"),
        ("metric4_unit", "Метрика 4: Единица"),
        ("metric4_label", "Метрика 4: Название"),
        ("metric4_sub", "Метрика 4: Подпись"),
    ]),
    "route": ("⚡ Схема защиты (маршрут)", [
        ("route_title", "Заголовок схемы"),
        ("route_sub", "Подзаголовок схемы"),
        ("route_node1", "Узел 1: Название"),
        ("route_badge1", "Узел 1: Бейдж"),
        ("route_node2", "Узел 2: Название"),
        ("route_badge2", "Узел 2: Бейдж"),
        ("route_node3", "Узел 3: Название"),
        ("route_badge3", "Узел 3: Бейдж"),
    ]),
    "features": ("🌟 Преимущества (6 карточек)", [
        ("feat1_title", "Карточка 1: Заголовок"),
        ("feat1_desc", "Карточка 1: Описание"),
        ("feat1_tag", "Карточка 1: Тег"),
        ("feat2_title", "Карточка 2: Заголовок"),
        ("feat2_desc", "Карточка 2: Описание"),
        ("feat2_tag", "Карточка 2: Тег"),
        ("feat3_title", "Карточка 3: Заголовок"),
        ("feat3_desc", "Карточка 3: Описание"),
        ("feat3_tag", "Карточка 3: Тег"),
        ("feat4_title", "Карточка 4: Заголовок"),
        ("feat4_desc", "Карточка 4: Описание"),
        ("feat4_tag", "Карточка 4: Тег"),
        ("feat5_title", "Карточка 5: Заголовок"),
        ("feat5_desc", "Карточка 5: Описание"),
        ("feat5_tag", "Карточка 5: Тег"),
        ("feat6_title", "Карточка 6: Заголовок"),
        ("feat6_desc", "Карточка 6: Описание"),
        ("feat6_tag", "Карточка 6: Тег"),
    ]),
    "steps": ("🚀 Инструкция (3 шага)", [
        ("step1_title", "Шаг 1: Заголовок"),
        ("step1_desc", "Шаг 1: Описание"),
        ("step2_title", "Шаг 2: Заголовок"),
        ("step2_desc", "Шаг 2: Описание"),
        ("step3_title", "Шаг 3: Заголовок"),
        ("step3_desc", "Шаг 3: Описание"),
    ]),
    "tariffs": ("💳 Блок тарифов", [
        ("tariffs_title", "Заголовок блока"),
        ("tariffs_sub", "Подзаголовок блока"),
        ("tariffs_note", "Примечание внизу"),
    ]),
    "faq": ("❓ Вопросы и ответы (FAQ)", [
        ("faq1_q", "Вопрос 1: Заголовок"),
        ("faq1_a", "Вопрос 1: Ответ"),
        ("faq2_q", "Вопрос 2: Заголовок"),
        ("faq2_a", "Вопрос 2: Ответ"),
        ("faq3_q", "Вопрос 3: Заголовок"),
        ("faq3_a", "Вопрос 3: Ответ"),
        ("faq4_q", "Вопрос 4: Заголовок"),
        ("faq4_a", "Вопрос 4: Ответ"),
        ("faq5_q", "Вопрос 5: Заголовок"),
        ("faq5_a", "Вопрос 5: Ответ"),
    ]),
    "cta": ("🎯 Финальный призыв (CTA)", [
        ("cta_title", "Заголовок призыва"),
        ("cta_sub", "Подзаголовок призыва"),
    ]),
}


def get_site_field_name(field: str) -> str:
    for _, items in SITE_SECTIONS.values():
        for k, name in items:
            if k == field:
                return name
    return field


def get_field_section(field: str) -> str:
    for sec_id, (_, items) in SITE_SECTIONS.items():
        for k, _ in items:
            if k == field:
                return sec_id
    return "hero"


def save_site_text(field: str, text: str) -> None:
    cfg = load_config()
    texts = cfg.get("site_texts") or {}
    if text.strip() == "-":
        texts.pop(field, None)
    else:
        texts[field] = text.strip()
    cfg["site_texts"] = texts
    save_config(cfg)


async def handle_site_texts_menu(query, context, section: str | None = None):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from web.site_page import get_site_texts
    cfg = load_config()
    texts = get_site_texts(cfg.get("site_texts"))

    if not section or section not in SITE_SECTIONS:
        # Главное меню разделов текстов
        kb = []
        for sec_id, (title, _) in SITE_SECTIONS.items():
            kb.append([InlineKeyboardButton(title, callback_data=f"site_txt_sec:{sec_id}")])
        kb.append([InlineKeyboardButton("🔄 Сбросить все тексты", callback_data="site_txt_reset")])
        kb.append([InlineKeyboardButton("◀️ В меню сайта", callback_data="site_menu")])

        await query.edit_message_text(
            "✍️ <b>Редактор текстов сайта</b>\n\n"
            "Выберите раздел, чтобы изменить текст на сайте. "
            "Каждый заголовок, карточку и ответ на вопрос можно настроить под себя.\n\n"
            "<blockquote>💡 <i>После редактирования текстов нажмите «Обновить сайт» в меню сайта, чтобы изменения появились онлайн.</i></blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    # Меню полей конкретного раздела
    sec_title, fields = SITE_SECTIONS[section]
    kb = []
    summary_lines = []
    for k, name in fields:
        val = texts.get(k, "")
        short_val = (val[:35] + "…") if len(val) > 35 else val
        summary_lines.append(f"• <b>{escape(name)}</b>: <i>{escape(short_val)}</i>")
        kb.append([InlineKeyboardButton(f"✏️ {name}", callback_data=f"site_txt_edit:{k}")])

    kb.append([InlineKeyboardButton("◀️ К разделам", callback_data="site_texts")])

    text_msg = (
        f"✍️ <b>{escape(sec_title)}</b>\n\n"
        "Нажмите на нужный пункт, чтобы изменить его текст:\n\n"
        "<blockquote>" + "\n".join(summary_lines[:8]) + "</blockquote>"
    )
    if len(summary_lines) > 8:
        text_msg += "\n<blockquote>" + "\n".join(summary_lines[8:]) + "</blockquote>"

    await query.edit_message_text(
        text_msg,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_site_text_edit_ask(query, context, field: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.states import AWAITING_SITE_TEXT
    from web.site_page import get_site_texts
    cfg = load_config()
    texts = get_site_texts(cfg.get("site_texts"))
    cur = texts.get(field, "")
    field_name = get_site_field_name(field)
    sec_id = get_field_section(field)

    context.user_data["state"] = AWAITING_SITE_TEXT
    context.user_data["site_text_field"] = field
    context.user_data["site_text_sec"] = sec_id

    await query.edit_message_text(
        f"✏️ <b>Редактирование: {escape(field_name)}</b>\n\n"
        f"<blockquote>Сейчас:\n<b>{escape(cur)}</b></blockquote>\n\n"
        "Отправьте новый текст следующим сообщением в чат.\n\n"
        "<i>Если хотите вернуть стандартное значение этого поля, отправьте знак <code>-</code>.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data=f"site_txt_sec:{sec_id}")],
        ]),
    )


async def handle_site_text_reset_ask(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(
        "⚠️ <b>Сброс всех текстов сайта</b>\n\n"
        "Вы действительно хотите сбросить абсолютно все тексты сайта к исходным стандартным значениям?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, сбросить все тексты", callback_data="site_txt_do_reset")],
            [InlineKeyboardButton("❌ Отмена", callback_data="site_texts")],
        ]),
    )


async def handle_site_text_reset_do(query, context):
    cfg = load_config()
    cfg["site_texts"] = {}
    save_config(cfg)
    await query.answer("Все тексты сброшены к стандартным", show_alert=True)
    await handle_site_texts_menu(query, context)

