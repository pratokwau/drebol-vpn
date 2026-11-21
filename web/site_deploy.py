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
 <img id="appicon" alt="" width="84" height="84" style="border-radius:22px;margin-bottom:14px;box-shadow:0 4px 18px rgba(0,0,0,.45)">
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
   happ: {name: "Happ", scheme: "happ://add/", icon: "__HAPP_ICON__",
          store: "https://apps.apple.com/us/app/happ-proxy-utility/id6504287215"},
   incy: {name: "INCY", scheme: "incy://add/", icon: "__INCY_ICON__",
          store: "https://apps.apple.com/ru/app/incy/id6756943388"}
 };
 var cfg = apps[app] || apps.happ;
 var link = sub ? cfg.scheme + sub : "";
 document.getElementById("head").textContent = "Добавляем подписку в " + cfg.name;
 document.getElementById("appicon").src = cfg.icon;
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


HAPP_ICON_DATA = "data:image/jpeg;base64,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"
INCY_ICON_DATA = "data:image/jpeg;base64,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"


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
<meta name="theme-color" content="#050505">
<title>Личный кабинет · Drebol VPN</title>
<link rel="icon" href="__FAVICON__">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
/* Drebol VPN — кабинет (Mini App и веб). Тёмный стеклянный премиум в языке
   лендинга: фон #050505, живое серебристое свечение, стеклянные карточки
   с градиентной кромкой, Manrope. Акцент — белый/серебро, статусы — цвет. */
:root {
  color-scheme: dark;
  --bg: #050505; --bg-2: #0A0A0A; --ink: #FFFFFF;
  --muted: #ACACB2; --soft: #8A8A92;
  --line: rgba(255,255,255,.10); --line-strong: rgba(255,255,255,.22);
  --card: rgba(255,255,255,.045); --card-2: rgba(255,255,255,.075);
  --accent: #FFFFFF; --accent-soft: rgba(255,255,255,.09);
  --silver: #C9CDD3; --silver-dark: #8A8A92; --dark: #0A0A0A;
  --ok: #4ADE80; --ok-bg: rgba(74,222,128,.14);
  --warn: #FBBF24; --warn-bg: rgba(251,191,36,.14);
  --bad: #F87171; --bad-bg: rgba(248,113,113,.12);
  --grad: linear-gradient(120deg, #FFFFFF 0%, #C9CDD3 45%, #8f959e 70%, #E8EAED 100%);
  --ease: cubic-bezier(.22,.9,.28,1);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin:0; min-height:100vh; background:var(--bg); color:var(--ink); overflow-x:hidden;
       font:15px/1.55 "Manrope","Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }
body { min-height:var(--tg-viewport-height, 100vh); }
a { color:inherit; text-decoration:none; }
h1, h2, p { margin:0; }
button { -webkit-tap-highlight-color: transparent; }
:focus-visible { outline:2px solid rgba(255,255,255,.65); outline-offset:2px; border-radius:8px; }

/* Живой фон: два серебристых пятна медленно дрейфуют, поверх — тонкая сетка */
.bg { position:fixed; inset:0; z-index:0; pointer-events:none; overflow:hidden; }
.bg .glow { position:absolute; top:-340px; right:-220px; width:820px; height:820px; border-radius:50%;
  background:radial-gradient(circle at center, rgba(255,255,255,.10), rgba(255,255,255,0) 62%);
  animation:drift 26s ease-in-out infinite alternate; }
.bg .glow-b { top:auto; bottom:-420px; left:-260px; right:auto;
  background:radial-gradient(circle at center, rgba(190,200,215,.07), rgba(255,255,255,0) 62%);
  animation:drift 32s ease-in-out infinite alternate-reverse; }
.bg .grid { position:absolute; inset:0; opacity:.5;
  background:
    linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size:56px 56px;
  -webkit-mask-image:radial-gradient(ellipse 90% 60% at 50% 0%, #000 30%, transparent 75%);
          mask-image:radial-gradient(ellipse 90% 60% at 50% 0%, #000 30%, transparent 75%); }
@keyframes drift { from { transform:translate(0,0) scale(1); } to { transform:translate(-70px,50px) scale(1.12); } }

.wrap { position:relative; z-index:1; max-width:520px; margin:0 auto;
        padding:12px 12px 40px;
        padding-top:max(12px, env(safe-area-inset-top, 0px),
                         var(--tg-content-safe-area-inset-top, 0px)); }

.top { display:flex; align-items:center; justify-content:space-between; gap:10px;
       min-height:46px; margin-bottom:14px; background:rgba(10,10,10,.66);
       border:1px solid var(--line); backdrop-filter:blur(18px) saturate(1.3); -webkit-backdrop-filter:blur(18px) saturate(1.3);
       padding:7px 12px; border-radius:18px; box-shadow:0 8px 28px rgba(0,0,0,.45); }
body.tg-fullscreen .wrap { padding-top:116px; }
body.tg-fullscreen .tabs { top:96px; }
.brand { display:flex; align-items:center; gap:10px; min-height:36px; text-decoration:none; }
.brand img { height:40px; max-height:40px; width:auto; max-width:200px; object-fit:contain; display:block; }
.brand-name { font-size:17px; font-weight:800; letter-spacing:-.01em; color:var(--ink); }
.brand-name b { font-weight:500; color:var(--muted); }

.btn { display:flex; align-items:center; justify-content:center; gap:10px; width:100%; position:relative;
       min-height:52px; padding:0 22px; border-radius:999px; border:1px solid transparent;
       font:inherit; font-size:15px; font-weight:800; cursor:pointer; text-align:center;
       transition:transform .18s var(--ease), box-shadow .25s ease, background .2s, border-color .2s, opacity .2s; }
.btn svg { width:19px; height:19px; flex:none; }
.btn:active { transform:scale(.975); }
.btn:disabled { opacity:.55; cursor:default; }
.btn-main { background:var(--grad); background-size:160% 100%; color:#050505;
            box-shadow:0 10px 26px rgba(255,255,255,.16), inset 0 1px 0 rgba(255,255,255,.7); }
.btn-main:hover { transform:translateY(-2px); background-position:90% 0;
  box-shadow:0 16px 36px rgba(255,255,255,.22), inset 0 1px 0 rgba(255,255,255,.7); }
.btn-ghost { background:rgba(255,255,255,.03); color:#FFFFFF; border-color:var(--line-strong); font-weight:700; }
.btn-ghost:hover { background:rgba(255,255,255,.07); border-color:rgba(255,255,255,.55); transform:translateY(-2px); }
.btn-sm { width:auto; min-height:40px; padding:0 16px; font-size:13px; }
.stack { display:flex; flex-direction:column; gap:10px; }
.pair { display:grid; grid-template-columns:1fr 1fr; gap:10px; }

/* Карточка: стекло с градиентной кромкой сверху и мягкой глубиной */
.card { background:linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.028));
        border:1px solid var(--line); border-radius:22px;
        padding:16px; margin:10px 0;
        box-shadow:0 12px 34px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.05); position:relative;
        backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px); }
.card::before { content:""; position:absolute; top:0; left:26px; right:26px; height:1px;
  background:linear-gradient(90deg, transparent, rgba(220,225,232,.55), transparent); pointer-events:none; }
@media (hover:hover) { .card { transition:transform .25s var(--ease), border-color .25s ease, box-shadow .25s ease; }
  .card:hover { transform:translateY(-2px); border-color:rgba(255,255,255,.18); box-shadow:0 18px 42px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.06); }
  .card.hero:hover { transform:none; } }
.card.hero { border-color:rgba(255,255,255,.18); color:#FFFFFF; overflow:hidden;
             background:
               radial-gradient(560px 300px at 85% -10%, rgba(255,255,255,.13), rgba(255,255,255,0) 60%),
               radial-gradient(420px 260px at -10% 110%, rgba(170,182,200,.10), rgba(255,255,255,0) 55%),
               linear-gradient(180deg, #101013, #0A0A0B);
             box-shadow:0 22px 50px rgba(0,0,0,.65), inset 0 1px 0 rgba(255,255,255,.09);
             animation:heroIn .55s var(--ease) both; }
.card.hero::after { content:""; position:absolute; inset:0; border-radius:22px; padding:1px;
  background:linear-gradient(130deg, rgba(255,255,255,.35), rgba(255,255,255,.04) 40%, rgba(255,255,255,.16));
  -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite:xor; mask-composite:exclude; pointer-events:none; }
.card.hero > * { position:relative; z-index:1; }
.card.hero .card-sub { color:rgba(255,255,255,.72); }
.card.hero .plan { color:#FFFFFF; }
.card.hero .big { color:#FFFFFF; }
.card.hero .big-sub { color:rgba(255,255,255,.66); }
.card.hero .card-title { color:#FFFFFF; }
.card.hero .card-title .ico { background:rgba(255,255,255,.10); color:#FFFFFF; box-shadow:none; }
.card.hero .btn-main { box-shadow:0 10px 26px rgba(0,0,0,.4); }
.card.hero .stat { background:rgba(255,255,255,.06); border-color:rgba(255,255,255,.13); }
.card.hero .stat b { color:#FFFFFF; }
.card.hero .stat span { color:rgba(255,255,255,.62); }
.card.hero .stat span::before { background:var(--silver); box-shadow:none; }
.card.hero .bar { background:rgba(255,255,255,.14); }
.card.hero .bar-note { color:rgba(255,255,255,.62); }
@keyframes heroIn { from { opacity:0; transform:translateY(14px) scale(.99); } to { opacity:1; transform:none; } }
.card-title { display:flex; align-items:center; gap:9px; font-size:15px; font-weight:800; margin-bottom:2px; }
.card-title .ico { width:31px; height:31px; border-radius:10px; display:flex; align-items:center;
                   justify-content:center; background:var(--accent-soft); color:var(--ink);
                   box-shadow:inset 0 1px 0 rgba(255,255,255,.12); }
.card-title .ico svg { width:16px; height:16px; }
.card-sub { color:var(--muted); font-size:13px; margin-bottom:10px; }

.eyebrow { font-size:11px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; color:var(--silver-dark); }
.hello { font-size:clamp(27px, 7vw, 35px); line-height:1.08; font-weight:800; letter-spacing:-.03em; margin:6px 0 4px; }
.muted { color:var(--muted); font-size:14px; }

.hero-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.plan { font-weight:800; display:inline-flex; align-items:center; gap:8px; }
.plan .gem { font-size:16px; filter:drop-shadow(0 2px 6px rgba(255,255,255,.35)); }
.big { font-size:clamp(29px, 8vw, 40px); line-height:1.08; font-weight:800; letter-spacing:-.03em; margin:16px 0 2px;
       background:linear-gradient(180deg, #FFFFFF 30%, #C9CDD3); -webkit-background-clip:text; background-clip:text; color:transparent; }
.card.hero .big { color:transparent; }
.big-sub { color:var(--muted); font-size:14px; }
.stats { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:8px; margin-top:18px; }
.stat { background:var(--card-2); border:1px solid var(--line); border-radius:16px; padding:12px; min-width:0; }
.stat b { display:block; font-size:15px; font-weight:800; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.stat span { display:block; font-size:12px; color:var(--soft); margin-top:2px; }
.stat span::before { content:""; display:inline-block; width:5px; height:5px; border-radius:50%;
  background:var(--silver); margin-right:6px; vertical-align:1px; }

.pill { display:inline-flex; align-items:center; gap:7px; padding:6px 12px; border-radius:999px;
        font-size:12px; font-weight:700; white-space:nowrap; }
.pill::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; }
.pill.ok::before { animation:pulseDot 2.2s ease-in-out infinite; }
@keyframes pulseDot { 0%,100% { box-shadow:0 0 0 0 rgba(74,222,128,.45); } 50% { box-shadow:0 0 0 5px rgba(74,222,128,0); } }
.ok { background:var(--ok-bg); color:var(--ok); }
.warn { background:var(--warn-bg); color:var(--warn); }
.bad { background:var(--bad-bg); color:var(--bad); }

.link { display:flex; align-items:center; gap:10px; margin-top:12px; padding:10px 10px 10px 14px;
        background:rgba(0,0,0,.32); border:1px solid var(--line); border-radius:16px; }
.link code { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
             color:var(--muted); font-size:13px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.copy { flex:none; min-height:40px; padding:0 14px; border-radius:999px; border:1px solid var(--line-strong);
        background:transparent; color:var(--ink); font:inherit; font-size:13px; font-weight:700; cursor:pointer;
        transition:background .2s, border-color .2s, transform .15s var(--ease); }
.copy:hover { background:rgba(255,255,255,.07); border-color:#FFFFFF; }
.copy:active { transform:scale(.95); }
.copy.done { background:var(--ok-bg); border-color:rgba(74,222,128,.5); color:var(--ok); }

.row { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:11px 0;
       border-top:1px solid var(--line); font-size:14px; }
.row:first-of-type { border-top:0; }
.row span:first-child { color:var(--ink); min-width:0; overflow-wrap:anywhere; }
.row span:last-child { color:var(--soft); text-align:right; }

.bar { height:10px; border-radius:999px; background:rgba(255,255,255,.12); overflow:hidden; margin-top:14px; }
.bar-fill { height:100%; border-radius:999px; background:linear-gradient(90deg, #FFFFFF, #9aa1ab);
            transition:width .8s var(--ease); }
.bar-fill.mid { background:linear-gradient(90deg, #FDE68A, #FBBF24); }
.bar-fill.full { background:linear-gradient(90deg, #FBBF24, #F87171); }
.bar-note { display:flex; justify-content:space-between; gap:12px; margin-top:8px; font-size:13px; color:var(--soft); }

.dev { display:flex; align-items:center; gap:12px; padding:11px 8px;
       border-top:1px solid var(--line); border-radius:12px; transition:background .2s ease; }
.dev:hover { background:rgba(255,255,255,.04); }
.dev:first-of-type { border-top:0; }
.dev .dico { flex:none; width:38px; height:38px; border-radius:12px; display:flex; align-items:center; justify-content:center;
             background:var(--accent-soft); color:var(--silver); }
.dev .dico svg { width:19px; height:19px; }
.dev .dbody { flex:1; min-width:0; }
.dev b { display:block; font-size:15px; overflow-wrap:anywhere; }
.dev small { color:var(--soft); font-size:13px; }
.btn-mini { flex:none; min-height:36px; padding:0 14px; border-radius:999px;
            border:1px solid rgba(248,113,113,.4); background:transparent; color:var(--bad);
            font:inherit; font-size:13px; font-weight:700; cursor:pointer; transition:background .2s, transform .15s var(--ease); }
.btn-mini:hover { background:var(--bad-bg); }
.btn-mini:active { transform:scale(.95); }
.btn-mini:disabled { opacity:.5; }
.btn-danger { border-color:rgba(248,113,113,.45); color:var(--bad); }
.btn-danger:hover { background:var(--bad-bg); border-color:rgba(248,113,113,.6); }

/* Вкладки: сверху — пилюли, на телефоне — нижняя стеклянная навигация */
.tabs { position:sticky; top:var(--tg-content-safe-area-inset-top, 0px); z-index:5; display:flex; gap:6px; overflow-x:auto;
        margin:0 -12px; padding:7px 12px;
        background:rgba(5,5,5,.82); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px);
        scrollbar-width:none; }
.tabs::-webkit-scrollbar { display:none; }
.tab { flex:none; display:inline-flex; align-items:center; gap:7px; min-height:36px; padding:0 15px; border-radius:999px; position:relative;
       border:1px solid var(--line-strong); background:rgba(255,255,255,.04); color:var(--muted);
       font:inherit; font-size:13px; font-weight:700; cursor:pointer; white-space:nowrap;
       transition:all .22s var(--ease); }
.tab svg { width:15px; height:15px; flex:none; }
.tab:active { transform:scale(.96); }
.tab.active { background:var(--grad); background-size:160% 100%; color:#050505; border-color:transparent;
  box-shadow:0 3px 12px rgba(255,255,255,.18); }
.tab .dot { position:absolute; top:5px; right:5px; width:8px; height:8px; border-radius:50%;
            background:#ff4d4d; box-shadow:0 0 0 0 rgba(255,77,77,.55);
            animation:dotPulse 1.6s ease-out infinite; pointer-events:none; }
@keyframes dotPulse { 0% { box-shadow:0 0 0 0 rgba(255,77,77,.55); }
  70% { box-shadow:0 0 0 7px rgba(255,77,77,0); } 100% { box-shadow:0 0 0 0 rgba(255,77,77,0); } }
.breadcrumb { font-size:11px; color:var(--soft); margin:4px 0 6px; display:flex; align-items:center; gap:4px; letter-spacing:.01em; }
.breadcrumb span { color:var(--muted); font-weight:600; }
.breadcrumb span:last-child { color:var(--ink); }
@media (max-width: 760px) {
  .tabs { position:fixed; top:auto; left:10px; right:10px; bottom:calc(10px + env(safe-area-inset-bottom, 0px));
          margin:0; padding:8px; border-radius:22px; border:1px solid var(--line);
          background:rgba(12,12,14,.86); box-shadow:0 16px 40px rgba(0,0,0,.6);
          justify-content:space-between; overflow:visible; }
  .tab { flex:1; flex-direction:column; gap:3px; min-height:52px; padding:6px 2px; border:0; background:transparent;
         font-size:10.5px; border-radius:16px; }
  .tab svg { width:20px; height:20px; }
  .tab.active { background:rgba(255,255,255,.12); color:#FFFFFF; box-shadow:inset 0 1px 0 rgba(255,255,255,.14); }
  .tab .dot { top:6px; right:calc(50% - 16px); }
  .breadcrumb { display:none; }
  .wrap { padding-bottom:calc(96px + env(safe-area-inset-bottom, 0px)); }
  body.tg-fullscreen .tabs { top:auto; }
}

/* Тарифы продления — карточки выбора */
.tariffs { display:grid; gap:9px; margin-top:4px; }
.tariff { display:flex; align-items:center; justify-content:space-between; gap:12px; width:100%;
          padding:14px 16px; border-radius:18px; border:1px solid var(--line-strong);
          background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.02));
          color:var(--ink); font:inherit; cursor:pointer; text-align:left;
          transition:transform .18s var(--ease), border-color .2s, background .2s, box-shadow .2s; }
.tariff:hover { border-color:rgba(255,255,255,.55); transform:translateY(-2px); box-shadow:0 12px 26px rgba(0,0,0,.4); }
.tariff:active { transform:scale(.985); }
.tariff .t-per { font-weight:800; font-size:15px; }
.tariff .t-sub { display:block; font-size:12px; color:var(--soft); font-weight:600; margin-top:1px; }
.tariff .t-price { font-size:19px; font-weight:800; letter-spacing:-.01em; white-space:nowrap; }
.tariff .t-price small { font-size:12px; color:var(--soft); font-weight:700; }

/* Приложения: кнопки с настоящими логотипами приложений */
.appbtn { gap:12px; }
.appbtn .appicon { flex:none; width:34px; height:34px; border-radius:11px; display:block;
                   box-shadow:0 1px 5px rgba(0,0,0,.4), inset 0 0 0 1px rgba(255,255,255,.14); }
.steps { display:flex; gap:8px; margin-top:12px; }
.steps span { flex:1; font-size:11.5px; line-height:1.35; color:var(--soft); background:rgba(255,255,255,.03);
              border:1px solid var(--line); border-radius:12px; padding:8px 9px; }
.steps b { display:block; color:var(--silver); font-size:13px; margin-bottom:2px; }

.pay { padding:13px 0; border-top:1px solid var(--line); }
.pay:first-of-type { border-top:0; }
.pay-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.pay-amount { font-size:18px; font-weight:800; letter-spacing:-.01em; }
.pay-date { font-size:13px; color:var(--soft); margin-top:2px; }
.pay-meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
.chip { padding:4px 10px; border-radius:999px; border:1px solid var(--line);
        font-size:12px; font-weight:600; color:var(--muted); background:var(--card-2); }

/* Скелетоны загрузки */
.skel { border-radius:22px; border:1px solid var(--line); padding:16px; margin:10px 0;
        background:rgba(255,255,255,.03); overflow:hidden; position:relative; }
.skel::after { content:""; position:absolute; inset:0;
  background:linear-gradient(100deg, transparent 30%, rgba(255,255,255,.06) 50%, transparent 70%);
  animation:shimmer 1.4s infinite; transform:translateX(-100%); }
@keyframes shimmer { to { transform:translateX(100%); } }
.skel .ln { height:14px; border-radius:7px; background:rgba(255,255,255,.09); margin:10px 0; }
.skel .ln.big { height:30px; width:62%; }
.skel .ln.w40 { width:40%; } .skel .ln.w70 { width:70%; }

/* Тост вместо alert() */
#toast { position:fixed; left:50%; bottom:calc(24px + env(safe-area-inset-bottom, 0px)); transform:translate(-50%, 20px);
         z-index:50; max-width:min(92vw, 420px); padding:12px 18px; border-radius:16px;
         background:rgba(18,18,20,.92); border:1px solid var(--line-strong); color:var(--ink);
         font-size:14px; font-weight:700; text-align:center; box-shadow:0 18px 44px rgba(0,0,0,.6);
         backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);
         opacity:0; pointer-events:none; transition:opacity .3s ease, transform .3s var(--ease); }
#toast.show { opacity:1; transform:translate(-50%, 0); }
@media (max-width: 760px) { #toast { bottom:calc(88px + env(safe-area-inset-bottom, 0px)); } }

@keyframes secIn { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:none; } }
@keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
#app:not(.hide) { animation:fadeIn .35s ease both; }
[data-sec].sec-show { animation:secIn .38s var(--ease) both; }

#login { text-align:center; padding:4vh 0 0; animation:fadeIn .4s ease both; }
#login .card { padding:30px 22px; box-shadow:0 24px 64px rgba(0,0,0,.65); }
#login h1 { font-size:clamp(28px, 7vw, 36px); line-height:1.1; font-weight:800; letter-spacing:-.03em; margin:10px 0 10px; }
#widget { display:flex; justify-content:center; min-height:48px; margin:22px 0 6px; }
#loginerr { margin-top:10px; }
#loginerr code { display:block; margin:8px 0; word-break:break-all; color:var(--soft); font-size:12px; }
.perks { display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin-top:18px; }
.perks span { display:inline-flex; align-items:center; gap:6px; padding:7px 12px; border-radius:999px; border:1px solid var(--line); font-size:13px; color:var(--muted); background:var(--card-2); }
.perks svg { width:13px; height:13px; color:var(--ok); }

.foot { text-align:center; margin-top:28px; font-size:13px; color:var(--soft); }
.hide { display:none !important; }

.login-logo { display:flex; justify-content:center; margin:10px 0 22px; position:relative; }
.login-logo::before { content:""; position:absolute; top:50%; left:50%; width:280px; height:160px;
  transform:translate(-50%,-50%); border-radius:50%;
  background:radial-gradient(circle, rgba(255,255,255,.13), transparent 65%); pointer-events:none; }
.login-logo img { width:240px; max-width:70vw; height:auto; position:relative; }
.renew-tariff { justify-content:center; gap:8px; }
.renew-tariff .rt-price { color:var(--ink); font-size:16px; }

@media (max-width: 480px) {
  .stats { grid-template-columns:1fr 1fr; }
  .stat:first-child { grid-column:1 / -1; }
  .pair { grid-template-columns:1fr; }
  .card { padding:14px; }
  .steps { flex-direction:column; }
}

@media (min-width: 900px) {
  .wrap { max-width:960px; }
  #body.tab-sub { display:grid; grid-template-columns:1fr 1fr; gap:0 20px; align-items:start; }
  #body.tab-sub > #tabs, #body.tab-sub > .breadcrumb,
  #body.tab-sub > .stack, #body.tab-sub > .sub-hero { grid-column:1 / -1; }
  [data-sec="sub"] > .card { margin:14px 0; }
}

.field { display:block; text-align:left; margin:12px 0 0; font-size:13px; font-weight:700; color:var(--muted); }
.field input { display:block; width:100%; margin-top:6px; padding:12px 14px; border-radius:14px;
  border:1px solid var(--line-strong); background:rgba(255,255,255,.06); color:var(--ink);
  font:inherit; font-size:15px; outline:none; transition:border-color .2s, box-shadow .2s; }
.field input:focus { border-color:#FFFFFF; box-shadow:0 0 0 3px rgba(255,255,255,.12); }
.or { display:flex; align-items:center; gap:12px; margin:22px 0 4px; color:var(--soft); font-size:13px; }
.or::before, .or::after { content:""; flex:1; height:1px; background:var(--line); }
#pwform .btn, #forgotform .btn, #prof-email-form .btn, #prof-pass-form .btn { width:100%; margin-top:14px; }
#turnstile-box, #turnstile-box2 { display:flex; justify-content:center; margin-top:14px; }
#turnstile-box:empty, #turnstile-box2:empty { display:none; }
.form-note { font-size:13px; color:var(--soft); margin-top:10px; }
.linklike { background:none; border:0; color:var(--ink); font:inherit; font-size:14px; cursor:pointer; padding:0; margin-top:12px; text-decoration:underline; text-underline-offset:3px; }

@media (prefers-reduced-motion: reduce) {
  .btn, .tab, .tariff, .card, .bar-fill { transition:none; }
  .tab .dot, .pill.ok::before, .bg .glow, .skel::after { animation:none; }
  .card.hero, #app:not(.hide), [data-sec].sec-show, #login { animation:none; }
  html { scroll-behavior:auto; }
}
</style></head>
<body>
<div class="bg" aria-hidden="true">
  <div class="glow"></div>
  <div class="glow glow-b"></div>
  <div class="grid"></div>
</div>

<div class="wrap">
 <header class="top">
   <a class="brand" href="/" aria-label="Drebol VPN — на сайт">
     __LOGO__<span class="brand-name">Drebol <b>VPN</b></span>
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
   <p class="foot">Нет подписки? <a id="botlink" href="#" style="color:var(--ink);font-weight:700">Откройте бота</a></p>
 </div>

 <div id="app" class="hide">
   <span class="eyebrow">Личный кабинет</span>
   <h1 class="hello" id="hello">Личный кабинет</h1>
   <div class="muted" id="whoami"></div>
   <div id="body"></div>
 </div>

 <p class="foot">Drebol VPN</p>
</div>
<div id="toast" role="status" aria-live="polite"></div>

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

 // Тост вместо alert(): не блокирует страницу и сам исчезает
 var toastTimer = null;
 function toast(msg) {
   var t = document.getElementById("toast");
   if (!t) { return; }
   t.textContent = msg;
   t.classList.add("show");
   if (toastTimer) { clearTimeout(toastTimer); }
   toastTimer = setTimeout(function () { t.classList.remove("show"); }, 3400);
 }
 function haptic(kind) {
   try { if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred(kind || "success"); } } catch (e) {}
 }
 function hapticSelect() {
   try { if (tg && tg.HapticFeedback) { tg.HapticFeedback.selectionChanged(); } } catch (e) {}
 }
 // Подтверждение по-telegramовски: нативный попап Mini App вместо
 // браузерного confirm(), который в WebView выглядит чужеродно.
 function askConfirm(text, cb) {
   if (tg && tg.showConfirm) {
     try { tg.showConfirm(text, function (ok) { if (ok) { cb(); } }); return; } catch (e) {}
   }
   if (confirm(text)) { cb(); }
 }

 // Иконки обводкой — те же, что на главной, плюс разделы кабинета
 var ICON = {
   tg: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M21.9 4.3 18.7 19c-.2 1-.9 1.3-1.8.8l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5l.4-5 9.1-8.2c.4-.4-.1-.6-.6-.2L6.2 12.9l-4.8-1.5c-1-.3-1-1 .2-1.5l18.9-7.3c.9-.3 1.6.2 1.4 1.7z"/></svg>',
   key: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 8.7-8.7M16 7l3 3M14 9l2 2"/></svg>',
   dev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="4" width="14" height="10" rx="1.5"/><path d="M6 18h6M9 14v4"/><rect x="17" y="8" width="5" height="12" rx="1.2"/></svg>',
   card: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M2.5 10h19M6.5 15h4"/></svg>',
   lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
   user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5"/></svg>',
   lte: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5a10 10 0 0 1 14 0M8.1 15.7a5.5 5.5 0 0 1 7.8 0"/><circle cx="12" cy="19" r="1" fill="currentColor"/><path d="M12 9V3M8.5 5.5 12 3l3.5 2.5"/></svg>',
   users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.4 3.2-5 6.5-5s5.9 1.6 6.5 5"/><path d="M16 4.7a3.5 3.5 0 0 1 0 6.6M18.5 15.3c1.6.7 2.7 2.1 3 4.2"/></svg>',
   phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="7" y="2.5" width="10" height="19" rx="2.2"/><path d="M10.5 18.5h3"/></svg>',
   monitor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="4" width="19" height="12.5" rx="2"/><path d="M9 20.5h6M12 16.5v4"/></svg>',
   refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.6M20 3v4h-4"/></svg>',
   check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m4.5 12.5 5 5 10-11"/></svg>'
 };
 var SEC_ICONS = {sub: "key", lte: "lte", devices: "dev", payments: "card", friends: "users", profile: "user"};
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
       // Истёкшая сессия в любом действии — на экран входа, а не
       // безликий тост «попробуйте позже». Авторизацию не трогаем:
       // её 401 — это «неверный пароль», а не конец сессии.
       if (r.status === 401 && path.indexOf("/api/auth") !== 0 && token()) {
         setToken("");
         showLogin();
         say("Сессия истекла — войдите заново.");
       }
       return {status: r.status, data: data};
     });
   });
 }

 // Человеку — человеческий текст; технические детали (адрес API, сырая
 // ошибка) — только в консоль, на экране входа им не место.
 function fail(where, err) {
   try { console.warn("cabinet:", where, err); } catch (e) {}
   say("Не получилось " + where + ". Проверьте соединение и попробуйте ещё раз.");
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
 function barClass(pct) { return pct >= 100 ? " full" : pct >= 75 ? " mid" : ""; }

 // Статусы платежей — человеческим языком, а не кодами из базы
 var PAY_STATUS = {
   paid: {text: "Оплачено", kind: "ok"},
   pending: {text: "Ожидает оплаты", kind: "warn"},
   failed: {text: "Не прошла", kind: "bad"},
   cancelled: {text: "Отменена", kind: "bad"},
   canceled: {text: "Отменена", kind: "bad"},
   expired: {text: "Истекла", kind: "bad"},
   refunded: {text: "Возврат", kind: "warn"},
   refund_pending: {text: "Возврат в обработке", kind: "warn"},
   partial_refunded: {text: "Частичный возврат", kind: "warn"}
 };
 function payProvider(raw) {
   var map = {anore: "Anore", platega: "Platega", yookassa: "ЮKassa", telegram: "Telegram", stars: "Stars", crypto: "Крипта", manual: "Вручную"};
   return map[String(raw).toLowerCase()] || String(raw);
 }
 function fmtMoney(n) {
   var v = Number(n || 0);
   return String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " ₽";
 }
 // "2026-10-20 10:00" -> "20.10.2026 · 10:00"
 function fmtDate(raw) {
   var m = String(raw || "").match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/);
   return m ? m[3] + "." + m[2] + "." + m[1] + " · " + m[4] : String(raw || "");
 }

 // Платежи: API отдавал список всегда, а страница его не показывала —
 // раздел обещан на экране входа, теперь он есть.
 function paymentsCard(p) {
   var items = p.payments || [];
   if (!items.length) {
     // Пустое состояние вместо молча исчезающей вкладки: раздел обещан,
     // человек должен видеть, что платежей просто ещё не было.
     return '<div data-sec="payments"><div class="card">' + title("card", "Платежи") +
            '<p class="card-sub">Платежей пока не было. Когда оплатите подписку, ' +
            "они появятся здесь.</p></div></div>";
   }
   var tot = p.payments_total || {};
   var sub = "Всего оплат: " + esc(tot.count != null ? tot.count : items.length) +
             (tot.sum ? " · на сумму " + esc(fmtMoney(tot.sum)) : "") +
             ". Показаны последние " + items.length + ".";
   var list = items.map(function (x) {
     var st = PAY_STATUS[String(x.status || "").toLowerCase()] || {text: String(x.status || ""), kind: "warn"};
     var meta = "";
     if (x.provider) { meta += '<span class="chip">' + esc(payProvider(x.provider)) + "</span>"; }
     if (x.promo) { meta += '<span class="chip">🎟 ' + esc(x.promo) + "</span>"; }
     return '<div class="pay"><div class="pay-head"><div>' +
       '<div class="pay-amount">' + esc(fmtMoney(x.amount)) + '</div>' +
       '<div class="pay-date">' + esc(fmtDate(x.date)) + "</div></div>" +
       pill(st.text, st.kind) + "</div>" +
       (meta ? '<div class="pay-meta">' + meta + "</div>" : "") + "</div>";
   }).join("");
   return '<div data-sec="payments"><div class="card">' + title("card", "Платежи") +
          '<p class="card-sub">' + sub + "</p>" + list + "</div></div>";
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

 // Скелетон на время загрузки /api/me — вместо пустого экрана
 function showSkeleton() {
   document.getElementById("login").className = "hide";
   document.getElementById("app").className = "";
   document.getElementById("body").innerHTML =
     '<div class="skel"><div class="ln w40"></div><div class="ln big"></div><div class="ln w70"></div><div class="ln"></div></div>' +
     '<div class="skel"><div class="ln w40"></div><div class="ln"></div><div class="ln w70"></div></div>';
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
     var pay0 = paymentsCard(p);
     if (pay0) { out.push(pay0); }
     out.push(profileCard(p));
     document.getElementById("body").innerHTML = out.join("");
     buildTabs();
     bindActions();
     return;
   }

   var s = p.subscription;
   var mark = s.status === "expired" ? pill("закончилась", "bad")
            : !s.enabled ? pill("на паузе", "warn") : pill("активна", "ok");
   var plan = s.plan === "paid" ? '<span class="gem">💎</span> Премиум' : "🆓 Пробный период";
   var big = s.status === "expired" ? "Подписка закончилась"
           : (s.left_text ? esc(s.left_text) : "до " + esc(s.until));
   var bigSub = s.status === "expired" ? "Продлите здесь — доступ вернётся сразу."
              : (s.left_text ? "осталось · до " + esc(fmtDate(s.until)) : "действует");
   if (s.status !== "expired" && s.left > 0 && s.left <= 3 * 86400) {
     bigSub += " · скоро закончится — продлите, чтобы не терять доступ";
   }
   var traffic = esc(s.traffic_used_text) + (s.traffic_limit_gb ? " / " + esc(s.traffic_limit_gb) + " ГБ" : "");
   var trafficBar = "";
   if (s.traffic_limit_gb) {
     var pct = Math.min(100, Math.round(s.traffic_used / (s.traffic_limit_gb * 1024 * 1024 * 1024) * 100));
     trafficBar = '<div class="bar"><div class="bar-fill' + barClass(pct) +
                  '" style="width:' + pct + '%"></div></div>' +
                  '<div class="bar-note"><span>Использовано ' + pct + "%</span><span>" + traffic + "</span></div>";
   }

   // Главная карточка: статус и сколько осталось
   out.push('<div data-sec="sub" class="sub-hero"><div class="card hero">' +
            '<div class="hero-head"><span class="plan">' + plan + "</span>" + mark + "</div>" +
            '<div class="big">' + big + "</div>" +
            '<div class="big-sub">' + bigSub + "</div>" +
            '<div class="stats">' +
              stat(esc(fmtDate(s.until)), "действует до") +
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
   if (s.created_at) { details.push(row("Подписка с", esc(fmtDate(s.created_at)))); }
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
                 esc(p.lte.limit_gb) + " ГБ · осталось <b style=\"color:var(--ink)\">" +
                 esc(p.lte.left_gb) + " ГБ</b></p>" +
                 '<div class="bar"><div class="bar-fill' + barClass(lpct) +
                 '" style="width:' + lpct + '%"></div></div>' +
                 '<div class="bar-note"><span>Лимит обновляется каждый месяц</span><span>' + lpct + "%</span></div>" +
                 (p.lte.fallback_active
                   ? '<p class="card-sub" style="margin-top:12px">⚠️ LTE на этот месяц закончился — ' +
                     "сейчас работают обычные серверы, в новом месяце LTE вернётся.</p>"
                   : "");
     }
     out.push('<div data-sec="lte"><div class="card">' + title("lte", "LTE-интернет") + lteBody + "</div></div>");
   } else if (!p.lte) {
     // Панель не ответила — раздел не прячем молча, а честно говорим,
     // что данные временно недоступны.
     out.push('<div data-sec="lte"><div class="card">' + title("lte", "LTE-интернет") +
              '<p class="card-sub">Не удалось получить данные LTE — панель временно ' +
              "не отвечает. Нажмите «Обновить данные» чуть позже.</p></div></div>");
   }

   // Подключение: приложение в одно нажатие и ссылка с копированием
   out.push('<div data-sec="sub"><div class="card">' + title("key", "Подключение") +
            '<p class="card-sub">Добавьте подписку в приложение одним нажатием.</p>' +
            '<div class="pair">' +
              '<a class="btn btn-main appbtn" target="_blank" rel="noopener" href="' + esc(location.origin + "/add.html?app=happ&u=" + encodeURIComponent(s.url)) + '" onclick="return openAppLink(this)"><img class="appicon" alt="" src="__HAPP_ICON__">HAPP</a>' +
              '<a class="btn btn-ghost appbtn" target="_blank" rel="noopener" href="' + esc(location.origin + "/add.html?app=incy&u=" + encodeURIComponent(s.url)) + '" onclick="return openAppLink(this)"><img class="appicon" alt="" src="__INCY_ICON__">INCY</a>' +
            "</div>" +
            '<div class="steps"><span><b>1</b>Нажмите кнопку приложения</span><span><b>2</b>Разрешите открыть приложение</span><span><b>3</b>Подписка добавится сама</span></div>' +
            '<div class="link"><code id="suburl">' + esc(s.url) + "</code>" +
            '<button class="copy" type="button" data-copy="' + esc(s.url) + '">Скопировать</button></div>' +
            '<button class="btn btn-ghost" type="button" id="qr-btn" style="margin-top:12px">📷 QR-код для другого устройства</button>' +
            '<div id="qr-box" class="hide" style="text-align:center;margin-top:12px">' +
            '<img id="qr-img" alt="QR-код подписки" style="width:220px;height:220px;border-radius:16px;background:#fff;padding:10px;box-sizing:border-box">' +
            '<p class="card-sub" style="margin-top:8px">Наведите камеру второго устройства — подписка добавится сама.</p></div>' +
            "</div></div>");

   // Устройства: каждое можно отключить прямо здесь
   var devList = (p.devices || []).map(function (x) {
     var isPhone = /iphone|android|ios|phone/i.test(x.platform || x.model || "");
     return '<div class="dev"><span class="dico">' + (isPhone ? ICON.phone : ICON.monitor) + '</span><div class="dbody"><b>' + esc(x.model) + "</b><small>" +
            esc(x.seen ? fmtDate(x.seen) || x.seen : "был недавно") + "</small></div>" +
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

   var payN = paymentsCard(p);
   if (payN) { out.push(payN); }
   var ref = referralCard(p);
   if (ref) { out.push('<div data-sec="friends">' + ref + "</div>"); }
   out.push(profileCard(p));

   out.push('<div class="stack" style="margin-top:6px">' +
            '<button class="btn btn-ghost" type="button" onclick="load()">' + ICON.refresh + "Обновить данные</button>" +
            '<a class="btn btn-ghost" href="' + botUrl() + '">' +
            ICON.tg + "Открыть бота</a></div>");
   document.getElementById("body").innerHTML = '<div class="tabs" id="tabs" role="tablist"></div><div class="breadcrumb" id="breadcrumb"></div>' + out.join("");
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
     b.setAttribute("role", "tab");
     b.setAttribute("data-tab", name);
     b.innerHTML = (ICON[SEC_ICONS[name]] || "") + "<span>" + esc(SEC_LABELS[name] || name) + "</span>";
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
   var idx = 0;
   document.querySelectorAll("#body [data-sec]").forEach(function (el) {
     var show = el.getAttribute("data-sec") === name;
     el.style.display = show ? "" : "none";
     if (show) {
       // перезапускаем анимацию появления при каждом переключении,
       // карточки одного раздела выходят лёгкой лесенкой
       el.classList.remove("sec-show");
       void el.offsetWidth;
       el.style.animationDelay = (idx++ * 55) + "ms";
       el.classList.add("sec-show");
     }
   });
   document.querySelectorAll("#tabs .tab").forEach(function (b) {
     b.classList.toggle("active", b.getAttribute("data-tab") === name);
   });
   var bc = document.getElementById("breadcrumb");
   if (bc) { bc.innerHTML = '<span>Кабинет</span> <span style="opacity:.4">/</span> <span>' + (SEC_LABELS[name] || name) + "</span>"; }
   if (!silent) {
     hapticSelect();
     try { localStorage.setItem("drebol_tab", name); } catch (e) {}
     try { history.replaceState(null, "", cabinetBase() + "/" + name); } catch (e) {}
     try { window.scrollTo({top: 0, behavior: "smooth"}); } catch (e) {}
   }
 }

 // Рефералка: статистика и ссылка — имя бота страница уже знает (BOT)
 function referralCard(p) {
   if (!p.referral) { return ""; }
   var r = p.referral;
   var link = "https://t.me/" + BOT + "?start=ref_" + p.user.id;
   var share = "https://t.me/share/url?url=" + encodeURIComponent(link) +
               "&text=" + encodeURIComponent("Попробуй Drebol VPN — быстрый и безопасный VPN!");
   return '<div class="card">' + title("users", "Приглашайте друзей") +
     '<p class="card-sub">Приглашено: <b style="color:var(--ink)">' + esc(r.invited) + "</b>" +
     " · бонус получили: <b style=\"color:var(--ink)\">" + esc(r.rewarded) + "</b>" +
     (r.bonus_text ? " · вам начислено: <b style=\"color:var(--ink)\">+" + esc(r.bonus_text) + "</b>" : "") + "</p>" +
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
       askConfirm("Отключить " + name + "? Оно потеряет доступ, слот освободится.", function () {
         btn.disabled = true; btn.textContent = "Отключаем…";
         api("/api/device/delete", {method: "POST",
             body: JSON.stringify({hwid: btn.getAttribute("data-del")})})
           .then(function (r) {
             if (r.status === 200) { toast("Устройство отключено"); haptic(); return load(); }
             haptic("error");
             toast(r.data && r.data.error === "already_gone"
               ? "Это устройство уже отключено." : "Не получилось — попробуйте позже.");
             load();
           })
           .catch(function () { haptic("error"); toast("Не получилось — попробуйте позже."); load(); });
       });
     };
   });
   var re = document.getElementById("reissue");
   if (re) {
     re.onclick = function () {
       askConfirm("Перевыпустить ключ? Старая ссылка перестанет работать на всех устройствах, " +
                  "новую нужно будет заново вставить в приложение.", function () {
         re.disabled = true; re.textContent = "Перевыпускаем…";
         api("/api/reissue", {method: "POST", body: "{}"})
           .then(function (r) {
             if (r.status === 200) { toast("Готово — новая ссылка уже в карточке «Подключение»"); haptic(); }
             else { haptic("error"); toast("Не получилось — попробуйте позже."); }
             load();
           })
           .catch(function () { haptic("error"); toast("Не получилось — попробуйте позже."); load(); });
       });
     };
   }
   // QR-код: картинку отдаёт наш API (сессионный запрос с токеном),
   // ссылка подписки не уходит в сторонние QR-сервисы.
   var qb = document.getElementById("qr-btn");
   if (qb) {
     qb.onclick = function () {
       var box = document.getElementById("qr-box");
       var img = document.getElementById("qr-img");
       if (!box || !img) { return; }
       var opening = box.classList.contains("hide");
       box.classList.toggle("hide");
       if (opening && !img.getAttribute("src")) {
         fetch(API + "/api/qr", {headers: {"Authorization": "Bearer " + token()}})
           .then(function (r) { if (!r.ok) { throw new Error("qr"); } return r.blob(); })
           .then(function (b) { img.src = URL.createObjectURL(b); })
           .catch(function () { haptic("error"); toast("Не получилось показать QR — попробуйте позже."); });
       }
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
           if (r.status === 200) { note.textContent = "Почта сохранена."; toast("Почта сохранена"); load(); return; }
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
           if (r.status === 200) { note.textContent = "Пароль сохранён."; toast("Пароль сохранён"); load(); return; }
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
 // приходит колбэком Platega, а опрос — страховка: страница опрашивает
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
       html += '<p class="card-sub">⏳ У вас есть неоплаченный счёт на <b style="color:var(--ink)">' +
               esc(fmtMoney(d.pending.amount)) + "</b>.</p>" +
               '<div class="stack"><button class="btn btn-main" type="button" ' +
               'onclick="openPay(pendingPayUrl)">Продолжить оплату</button>' +
               '<button class="btn btn-ghost" type="button" onclick="pollPayment(' +
               d.pending.id + ', 90)">Проверить оплату</button></div>';
     }
     html += '<p class="card-sub">Выберите тариф — счёт создастся здесь же, оплата через платёжную систему.</p>';
     html += '<div class="tariffs">';
     d.tariffs.forEach(function (t) {
       html += '<button class="tariff" type="button" onclick="renewPay(' +
               t.id + ')"><span><span class="t-per">' + esc(t.period) + '</span>' +
               '<span class="t-sub">продление подписки</span></span>' +
               '<span class="t-price">' + esc(fmtMoney(t.price)) + "</span></button>";
     });
     html += "</div>";
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
       body.innerHTML = '<div id="renew-wait"><p class="card-sub">Счёт на <b style="color:var(--ink)">' +
         esc(fmtMoney(r.data.amount)) + "</b> готов. Оплатите его — подтверждение придёт само, " +
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
       toast("Оплата прошла — подписка продлена"); haptic();
       load();
       return;
     }
     if (st === "canceled" || st === "cancelled" || st === "expired" || st === "error" ||
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
     btn.classList.add("done");
     btn.textContent = "Скопировано ✓";
     toast("Ссылка скопирована");
     haptic();
     setTimeout(function () { btn.classList.remove("done"); btn.textContent = "Скопировать"; }, 1600);
   }
   function select() {
     var el = document.getElementById("suburl") || document.getElementById("reflink");
     if (!el) { return; }
     var r = document.createRange(); r.selectNodeContents(el);
     var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
   }
   if (navigator.clipboard && navigator.clipboard.writeText) {
     navigator.clipboard.writeText(text).then(done, select);
   } else { select(); }
 });

 var lastLoadAt = 0;
 function load(quiet) {
   stopRenewPoll();
   lastLoadAt = Date.now();
   if (!quiet) { showSkeleton(); }
   return api("/api/me").then(function (r) {
     if (r.status === 200) { say(""); return render(r.data); }
     setToken("");
     showLogin();
     if (r.status !== 401) { fail("получить данные", "ответ " + r.status); }
   }).catch(function (e) { showLogin(); fail("связаться с кабинетом", e); });
 }

 // Вернулись в приложение — тихо освежаем данные: остаток срока и
 // трафик не должны устаревать в давно открытом кабинете. Не мешаем
 // человеку, который прямо сейчас что-то печатает в форме профиля.
 document.addEventListener("visibilitychange", function () {
   if (document.visibilityState !== "visible") { return; }
   if (!token() || !window.LOGIN) { return; }
   if (Date.now() - lastLoadAt < 60000) { return; }
   var ae = document.activeElement;
   if (ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA")) { return; }
   load(true);
 });

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
   // Полный экран (Bot API 8.0+, мобильный Telegram): кабинет открывается
   // на весь дисплей, а не в шторке на пол-экрана. Класс tg-fullscreen
   // включает CSS-отступы под плавающие кнопки клиента (закрыть, меню) —
   // правила для него уже есть в стилях выше. Если клиент старый или
   // запрос отклонён (fullscreenFailed), остаёмся в expand() — максимум
   // по высоте, как раньше. При ручном выходе из полного экрана класс
   // снимается по событию fullscreenChanged.
   function applyFsClass() {
     try {
       document.body.classList.toggle("tg-fullscreen", !!tg.isFullscreen);
     } catch (e) {}
   }
   try {
     if (tg.requestFullscreen) { tg.requestFullscreen(); }
   } catch (e) {}
   applyFsClass();
   try {
     if (tg.onEvent) {
       tg.onEvent("fullscreenChanged", applyFsClass);
       tg.onEvent("fullscreenFailed", applyFsClass);
     }
   } catch (e) {}
   // В полном экране вертикальный свайп вниз сворачивает приложение —
   // отключаем, чтобы случайный скролл не закрывал кабинет.
   try { if (tg.disableVerticalSwipes) { tg.disableVerticalSwipes(); } } catch (e) {}
   // внутри Telegram красим шапку в цвет страницы
   try { tg.setHeaderColor("#050505"); tg.setBackgroundColor("#050505"); } catch (e) {}
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
            .replace("__HAPP_ICON__", HAPP_ICON_DATA)
            .replace("__INCY_ICON__", INCY_ICON_DATA)
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
    "/h/jZt0C/V5fGwAAAABJRU5ErkJggg=="
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
                 cabinet: str = "", pay_pages: dict | None = None,
                 doc_pages: dict | None = None,
                 admin: str = "") -> dict:
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
                f.write(ADD_PAGE.replace("__HAPP_ICON__", HAPP_ICON_DATA).replace("__INCY_ICON__", INCY_ICON_DATA))
            with sftp.open("/tmp/drebol_cabinet.html", "w") as f:
                f.write(cabinet or "")
            with sftp.open("/tmp/drebol_admin.html", "w") as f:
                f.write(admin or "")
            for kind in ("success", "fail", "back"):
                if pay_pages and pay_pages.get(kind):
                    with sftp.open(f"/tmp/drebol_pay_{kind}.html", "w") as f:
                        f.write(pay_pages[kind])
            for kind in ("privacy", "terms", "refund", "rules", "consent"):
                if doc_pages and doc_pages.get(kind):
                    with sftp.open(f"/tmp/drebol_doc_{kind}.html", "w") as f:
                        f.write(doc_pages[kind])
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
    }}
    location /api/admin/ {{
        proxy_pass http://{upstream}/api/admin/;
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
# Веб-админка — по чистому адресу /admin/: та же страница, что отдаёт
# API-сервер на /admin/ (запасной путь), только на сайте.
mkdir -p {WEB_ROOT}/admin
cp /tmp/drebol_admin.html {WEB_ROOT}/admin/index.html
chmod 644 {WEB_ROOT}/admin/index.html
chmod 644 {WEB_ROOT}/cabinet/*/index.html || true
# Страницы редиректов после оплаты: /pay/success/, /pay/fail/, /pay/back/
for kind in success fail back; do
  if [ -f /tmp/drebol_pay_$kind.html ]; then
    mkdir -p {WEB_ROOT}/pay/$kind
    mv /tmp/drebol_pay_$kind.html {WEB_ROOT}/pay/$kind/index.html
    chmod 644 {WEB_ROOT}/pay/$kind/index.html
  fi
done
# Документы: /privacy/, /terms/, /refund/, /rules/, /consent/
for kind in privacy terms refund rules consent; do
  if [ -f /tmp/drebol_doc_$kind.html ]; then
    mkdir -p {WEB_ROOT}/$kind
    mv /tmp/drebol_doc_$kind.html {WEB_ROOT}/$kind/index.html
    chmod 644 {WEB_ROOT}/$kind/index.html
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
    from web.site_page import LOGO_URL, MARK_URL, build_page
    cfg = load_config()
    og_bytes = _asset("og.webp")
    # /logo.png на сервере — новый логотип (тот же base64, что в шапке
    # сайта): его же можно вставить в настройки платёжной формы Platega.
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
        privacy_url=doc_url("privacy"),
        terms_url=doc_url("terms"),
        channel_url=cfg.get("channel_url", "") or "",
        # Знак D (тайт-кроп нового логотипа) — для шапки, hero и футера.
        # Полный логотип (LOGO_URL) по-прежнему заливается в /logo.png.
        logo_file=MARK_URL,
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


def doc_url(kind: str) -> str:
    """Действующая ссылка на документ Сервиса.

    Ссылка из настроек (privacy_url, terms_url, refund_url, rules_url,
    consent_url) действует, пока это не Teletype: документы переехали
    с Teletype на сайт, и старая ссылка в настройках считается
    незаданной — ведёт на страницу сайта.
    """
    keys = {"privacy": "privacy_url", "terms": "terms_url",
            "refund": "refund_url", "rules": "rules_url",
            "consent": "consent_url"}
    stored = (load_config().get(keys[kind]) or "").strip()
    if stored and "teletype.in" not in stored:
        return stored
    base = site_url().rstrip("/")
    return f"{base}/{kind}/" if base else stored


def page_hash(page: str, og_bytes: bytes, logo_bytes: bytes, cabinet: str = "",
              pay: str = "", doc: str = "", admin: str = "") -> str:
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
    h.update(doc.encode("utf-8"))
    h.update(admin.encode("utf-8"))
    # фавикон и robots.txt тоже едут на сервер — их смена должна
    # вызывать перезалив, а не молча пропускаться автообновлением
    h.update(base64.b64decode(FAVICON_ICO_B64))
    h.update(seo_files()[0].encode("utf-8"))
    # манифест версий приложения тоже едет на сервер
    h.update(app_version_json().encode("utf-8"))
    return h.hexdigest()


async def deploy(bot_username: str) -> dict:
    """Собирает страницу и раскатывает её на сервер."""
    from web.admin_page import admin_page
    from web.site_page import build_pay_pages, build_doc_pages
    page, og_bytes, logo_bytes = await build_current(bot_username)
    cabinet = cabinet_page(bot_username)
    admin = admin_page(bot_username)
    pay_pages = build_pay_pages()
    pay = "".join(pay_pages[k] for k in ("success", "fail", "back"))
    doc_pages = build_doc_pages()
    doc = "".join(doc_pages[k] for k in ("privacy", "terms", "refund", "rules", "consent"))
    res = await asyncio.to_thread(_deploy_sync, page, og_bytes, logo_bytes,
                                  cabinet, pay_pages, doc_pages, admin)
    if res.get("ok"):
        # вместе со страницей уехал и переходник — можно показывать кнопки приложений
        save_creds(site_deployed_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                   site_page_hash=page_hash(page, og_bytes, logo_bytes, cabinet, pay, doc, admin),
                   site_add_page=True, site_cabinet=bool(load_config().get("webapi_public")),
                   site_admin=bool(load_config().get("webapi_public")))
    return res


async def _build_and_maybe_deploy(bot_username: str) -> tuple:
    """Собирает лендинг и кабинет, сравнивает отпечаток с сохранённым.

    Возвращает (статус, результат): "unchanged" — ничего не поменялось,
    сервер не трогаем; "deployed" — залили; "failed" — деплой не прошёл.
    Кабинет едет вместе со страницей: раньше автообновление заливало его
    пустым (аргумент не передавался), и кабинет бы стёрся.
    """
    from web.admin_page import admin_page
    from web.site_page import build_pay_pages, build_doc_pages
    page, og_bytes, logo_bytes = await build_current(bot_username)
    cabinet = cabinet_page(bot_username)
    admin = admin_page(bot_username)
    pay_pages = build_pay_pages()
    pay = "".join(pay_pages[k] for k in ("success", "fail", "back"))
    doc_pages = build_doc_pages()
    doc = "".join(doc_pages[k] for k in ("privacy", "terms", "refund", "rules", "consent"))
    fresh = page_hash(page, og_bytes, logo_bytes, cabinet, pay, doc, admin)
    if fresh == load_config().get("site_page_hash"):
        return "unchanged", None
    res = await asyncio.to_thread(_deploy_sync, page, og_bytes, logo_bytes,
                                  cabinet, pay_pages, doc_pages, admin)
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

