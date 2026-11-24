"""Статическая страница веб-админки Drebol VPN.

Дизайн — как сайт и кабинет: тёмный стеклянный премиум, фон #050505,
серебристые градиенты #FFFFFF→#C9CDD3, Manrope. Левая
боковая навигация с разделами, верхняя панель с актором и выходом,
карточки с заголовками, читаемые таблицы (числа — справа, ID и даты —
моноширинным, статусы — плашками), пустые состояния, тосты и спиннеры.
API — same-origin /api/admin/, токен сессии — только в HttpOnly-куке,
CSRF — из куки в заголовок X-CSRF-Token. Никаких токенов в localStorage
и в URL, кроме одноразовой ссылки на установку пароля (?token= — живёт
15 минут и гасится после первого использования).
"""

ADMIN_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Админка — Drebol VPN</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
/* Дизайн — как кабинет и сайт: тёмный стеклянный премиум, фон #050505,
   серебристые градиенты и свечения, Manrope. Имена переменных сохранены —
   на них завязаны инлайн-стили разметки и JS. */
:root{
  color-scheme:dark;
  --bg:#050505; --card:#0C0C0F; --card2:#121216; --line:rgba(255,255,255,.10); --line2:rgba(255,255,255,.22);
  --txt:#FFFFFF; --mut:#ACACB2; --mut2:#8A8A92; --acc:#FFFFFF; --acc-dim:rgba(255,255,255,.09);
  --gold:#C9CDD3; --dark:#0A0A0A; --dark-2:#121216; --dark-line:rgba(255,255,255,.10); --dark-mut:#8A8A92;
  --ok:#4ADE80; --warn:#FBBF24; --bad:#F87171; --violet:#C9CDD3;
  --grad:linear-gradient(120deg,#FFFFFF 0%,#C9CDD3 45%,#8f959e 70%,#E8EAED 100%);
  --radius:22px; --ease:cubic-bezier(.22,.61,.36,1);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scrollbar-color:#2C2C31 #050505}
body{background:
  radial-gradient(820px 520px at 88% -120px, rgba(255,255,255,.075), rgba(255,255,255,0) 62%),
  radial-gradient(760px 560px at -180px 108%, rgba(190,200,215,.05), rgba(255,255,255,0) 62%),
  var(--bg);
  background-attachment:fixed;
  color:var(--txt);font:15px/1.6 "Manrope","Inter",-apple-system,"Segoe UI",sans-serif;min-height:100vh;
  -webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.5;
  background:
    linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size:56px 56px;
  -webkit-mask-image:radial-gradient(ellipse 90% 55% at 50% 0%, #000 25%, transparent 72%);
          mask-image:radial-gradient(ellipse 90% 55% at 50% 0%, #000 25%, transparent 72%)}
::selection{background:rgba(255,255,255,.85);color:#050505}
a{color:var(--acc);text-decoration:none}
a:hover{text-decoration:underline}
h1{font-family:"Manrope",sans-serif;font-size:22px;font-weight:800;letter-spacing:-.02em}
h2{font-family:"Manrope",sans-serif;font-size:16px;font-weight:800;margin:0 0 4px}
h3{font-size:14px;font-weight:700;margin:18px 0 8px}
.mut{color:var(--mut);font-size:13.5px;line-height:1.55}
.small{font-size:12.5px;color:var(--mut2)}
.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:13px}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.hidden{display:none !important}
:focus-visible{outline:2px solid rgba(255,255,255,.55);outline-offset:2px}

/* --- Анимации --- */
@keyframes pageIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes cardIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
@keyframes toastIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes shimmer{from{background-position:200% 0}to{background-position:-200% 0}}
.page:not(.hidden){animation:pageIn .3s var(--ease) backwards}
.page .card{animation:cardIn .4s var(--ease) backwards}
.page .card:nth-child(2){animation-delay:.05s}
.page .card:nth-child(3){animation-delay:.1s}
.page .card:nth-child(4){animation-delay:.15s}
.page .card:nth-child(5){animation-delay:.2s}
@media (prefers-reduced-motion: reduce){*{animation:none !important;transition:none !important}}

/* --- Каркас: боковая панель + контент --- */
.layout{display:flex;min-height:100vh;position:relative;z-index:1}
.sidebar{width:264px;flex:0 0 264px;background:rgba(10,10,11,.88);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border-right:1px solid var(--line);padding:20px 14px;position:sticky;top:0;height:100vh;overflow-y:auto}
.brand{font-family:"Manrope",sans-serif;font-size:17px;font-weight:800;color:#FFFFFF;padding:2px 10px 16px;border-bottom:1px solid var(--line);margin-bottom:14px}
.brand span{color:var(--gold)}
.brand small{display:block;font-family:"Manrope",sans-serif;font-size:12px;color:var(--dark-mut);margin-top:4px}
.nav-group{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--dark-mut);padding:16px 10px 6px}
.nav-item{display:flex;align-items:center;gap:10px;width:100%;text-align:left;background:none;border:0;border-radius:12px;color:var(--dark-mut);font:600 14.5px "Manrope",sans-serif;padding:9px 10px;cursor:pointer;margin:1px 0;transition:background .25s var(--ease),color .25s var(--ease);box-shadow:none}
.nav-item .ic{width:22px;text-align:center;font-size:15px}
.nav-item:hover{background:rgba(255,255,255,.07);color:#FFFFFF;transform:none;box-shadow:none}
.nav-item.active{background:var(--grad);background-size:160% 100%;color:#050505;box-shadow:0 6px 18px rgba(255,255,255,.14)}
.nav-item.active .ic{color:#050505}
.main{flex:1;min-width:0;padding:0 28px 64px}
.topbar{position:sticky;top:0;z-index:20;background:rgba(5,5,5,.82);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);display:flex;align-items:center;gap:16px;padding:16px 0;border-bottom:1px solid var(--line);margin-bottom:22px}
.topbar h1{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.who{color:var(--mut);font-size:13.5px;white-space:nowrap}
.wrap{max-width:1020px}

/* --- Карточки, таблицы, формы --- */
.card{position:relative;background:linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.028));border:1px solid var(--line);border-radius:var(--radius);padding:20px 22px;margin-top:16px;box-shadow:0 12px 34px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.05);transition:transform .35s var(--ease),box-shadow .35s var(--ease),border-color .3s ease}
.card::before{content:"";position:absolute;top:0;left:26px;right:26px;height:1px;background:linear-gradient(90deg, transparent, rgba(220,225,232,.5), transparent);pointer-events:none}
.card:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.18);box-shadow:0 18px 42px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.06)}
.card > p.sub{color:var(--mut);font-size:13.5px;margin-bottom:12px}
.card h2 + p.sub{margin-top:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.stat{background:linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.028));border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:0 12px 34px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.05);transition:transform .35s var(--ease),box-shadow .35s var(--ease)}
.stat:hover{transform:translateY(-3px);box-shadow:0 18px 42px rgba(0,0,0,.55)}
.stat b{display:block;font-size:24px;font-family:"Manrope",sans-serif;font-weight:800}
.stat span{color:var(--mut);font-size:13px}
.stat small{display:block;color:var(--mut2);font-size:12px;margin-top:2px}
.chartgrid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.chart text{font:11px "Manrope",sans-serif;fill:var(--mut)}
.chart{overflow:visible}
.hbar{display:flex;align-items:center;gap:10px;margin:9px 0;font-size:13.5px}
.hbar-lab{width:110px;flex:0 0 110px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hbar-track{flex:1;background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:999px;height:12px;overflow:hidden}
.hbar-fill{height:100%;background:var(--grad);border-radius:999px}
.hbar b{min-width:36px;text-align:right;font-variant-numeric:tabular-nums}
.donut-wrap{display:flex;align-items:center;gap:20px;flex-wrap:wrap}
.legend{font-size:13.5px}
.legend div{margin:6px 0;white-space:nowrap}
.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:8px;vertical-align:-1px}
tr[data-sub]{cursor:pointer}
tr[data-sub]:hover td{background:rgba(255,255,255,.045)}
input,select,textarea{width:100%;background:rgba(255,255,255,.05);border:1px solid var(--line);border-radius:12px;color:var(--txt);padding:10px 12px;font:inherit;margin:6px 0;transition:border-color .2s,box-shadow .2s}
input:focus,select:focus,textarea:focus{outline:none;border-color:#FFFFFF;box-shadow:0 0 0 3px rgba(255,255,255,.12)}
input::placeholder,textarea::placeholder{color:var(--mut2)}
textarea{min-height:84px;resize:vertical}
label{font-size:13px;color:var(--mut);display:block;margin-top:8px}
label input[type=checkbox]{width:auto;margin-right:6px;accent-color:#E8EAED}
button{background:var(--grad);background-size:160% 100%;color:#050505;border:0;border-radius:999px;padding:10px 18px;font:700 14px "Manrope",sans-serif;cursor:pointer;margin:6px 6px 0 0;box-shadow:0 8px 20px rgba(255,255,255,.13);transition:transform .3s var(--ease),box-shadow .3s var(--ease),background .2s,border-color .2s}
button:hover{transform:translateY(-2px);background-position:90% 0;box-shadow:0 12px 26px rgba(255,255,255,.18)}
button:active{transform:scale(.98)}
button.ghost{background:rgba(255,255,255,.03);color:var(--txt);border:1px solid var(--line2);box-shadow:none}
a.btnlike{display:inline-block;padding:8px 14px;border-radius:10px;background:rgba(255,255,255,.03);color:var(--txt);border:1px solid var(--line2);text-decoration:none;font-size:14px}
a.btnlike:hover{border-color:rgba(255,255,255,.55);background:rgba(255,255,255,.06)}
button.ghost:hover{border-color:rgba(255,255,255,.55);background:rgba(255,255,255,.06)}
button.ghost.active{background:var(--grad);background-size:160% 100%;color:#050505;border-color:transparent}
button.danger{background:transparent;color:var(--bad);border:1px solid rgba(248,113,113,.4);box-shadow:none}
button.danger:hover{border-color:var(--bad);background:rgba(248,113,113,.08)}
button:disabled{opacity:.55;cursor:default;transform:none}
.btnrow{display:flex;flex-wrap:wrap;gap:0}
.btnrow button{margin-right:8px}
.err{color:var(--bad);margin-top:8px;min-height:18px}
.ok{color:var(--ok)}
table{width:100%;border-collapse:collapse;font-size:14px}
th{color:var(--mut);font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;text-align:left;padding:8px 10px;border-bottom:1px solid var(--line2);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
tbody tr{transition:background .2s}
.tblwrap{overflow-x:auto;margin:8px -4px 0}
.tblwrap table{min-width:560px}
td.trunc{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pill{display:inline-block;font-size:12px;font-weight:700;padding:2px 9px;border-radius:999px;white-space:nowrap}
.pill.ok{background:rgba(74,222,128,.14);color:var(--ok)}
.pill.bad{background:rgba(248,113,113,.12);color:var(--bad)}
.pill.warn{background:rgba(251,191,36,.14);color:var(--warn)}
.pill.info{background:rgba(255,255,255,.09);color:#E8EAED}
.pill.grey{background:rgba(255,255,255,.06);color:var(--mut)}
.kv{display:grid;grid-template-columns:180px 1fr;gap:6px 14px;font-size:14px}
.kv dt{color:var(--mut)}
.kv dd{word-break:break-word}
.empty{text-align:center;color:var(--mut);padding:26px 10px}
.empty .big{font-size:26px;display:block;margin-bottom:6px}
pre{white-space:pre-wrap;word-break:break-word;font:13px/1.55 ui-monospace,Menlo,Consolas,monospace;background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:10px;padding:12px;margin-top:10px}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;background:rgba(255,255,255,.05);border:1px solid var(--line);border-radius:6px;padding:1px 5px}
details{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:10px;background:rgba(255,255,255,.03)}
details summary{cursor:pointer;font-weight:700;font-size:14px}
details p,details ul{margin-top:8px}
#toast{position:fixed;right:20px;bottom:20px;z-index:50;display:flex;flex-direction:column;gap:8px;max-width:360px}
.toast{background:rgba(16,16,19,.92);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);color:var(--txt);border:1px solid var(--line2);border-left:4px solid var(--gold);border-radius:12px;padding:12px 16px;font-size:14px;box-shadow:0 18px 44px rgba(0,0,0,.6);animation:toastIn .3s var(--ease) backwards}
.toast.err{border-left-color:var(--bad)}
.toast.ok{border-left-color:var(--ok)}
.spin{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.18);border-top-color:#FFFFFF;border-radius:50%;animation:sp 0.8s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes sp{to{transform:rotate(360deg)}}
.loginwrap{max-width:460px;margin:80px auto 0;padding:0 18px;position:relative;z-index:1}
.loginwrap .card{padding:26px}

/* --- Редактор записи: выезжающая панель --- */
.drawer-overlay{position:fixed;inset:0;z-index:60;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);opacity:0;pointer-events:none;transition:opacity .3s var(--ease)}
.drawer-overlay.open{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;bottom:0;z-index:61;width:min(560px,100%);background:#0C0C0F;border-left:1px solid var(--line);box-shadow:-20px 0 60px rgba(0,0,0,.6);transform:translateX(100%);transition:transform .35s var(--ease);display:flex;flex-direction:column}
.drawer.open{transform:none}
.drawer-head{background:linear-gradient(180deg,#101013,#0A0A0B);color:#FFFFFF;padding:18px 22px;display:flex;align-items:flex-start;gap:12px;border-bottom:1px solid var(--line)}
.drawer-head h2{color:#FFFFFF;font-size:17px}
.drawer-head .sub{color:var(--dark-mut);font-size:13px}
.drawer-close{margin-left:auto;background:transparent;border:1px solid var(--dark-line);color:#FFFFFF;border-radius:999px;width:34px;height:34px;padding:0;box-shadow:none;flex:0 0 auto;font-size:16px;line-height:1}
.drawer-close:hover{border-color:var(--gold);transform:none;background:rgba(255,255,255,.06)}
.drawer-body{padding:18px 22px 28px;overflow-y:auto}
.drawer-foot{padding:14px 22px;border-top:1px solid var(--line);display:flex;gap:8px;flex-wrap:wrap;background:rgba(255,255,255,.03)}
label.chk{display:flex;gap:8px;align-items:center;color:var(--txt);font-size:14px;margin-top:6px}
label.chk input{width:auto;margin:0}
.chkgrid{margin:10px 0}
.chkgrid>b{display:block;margin-bottom:4px}
.tbar{display:block;height:6px;background:rgba(255,255,255,.08);border-radius:99px;margin-top:6px;overflow:hidden}
.tbar-fill{display:block;height:100%;background:#D8DBE0;border-radius:99px}
.tbar-fill.hi{background:#E5484D}
.sublink{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.sublink .mono{word-break:break-all;flex:1;min-width:200px}

/* --- Консоль серверов (xterm) --- */
#console-term{background:#0A0A0C;border:1px solid var(--line);border-radius:14px;padding:8px;height:480px;overflow:hidden}
#console-term .xterm{height:100%}
#console-pubkey{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}

/* --- Скелетоны загрузки --- */
.skel{border-radius:8px;background:linear-gradient(90deg,rgba(255,255,255,.05) 25%,rgba(255,255,255,.11) 50%,rgba(255,255,255,.05) 75%);background-size:200% 100%;animation:shimmer 1.2s linear infinite}
@media (max-width:900px){
  .layout{display:block}
  .sidebar{position:static;width:100%;height:auto;border-right:0;border-bottom:1px solid var(--line);padding:12px}
  .sidebar nav{display:flex;overflow-x:auto;gap:4px;padding-bottom:4px}
  .nav-group{display:none}
  .nav-item{width:auto;white-space:nowrap;padding:8px 10px}
  .brand{border-bottom:0;padding-bottom:6px;margin-bottom:6px}
  .main{padding:0 16px 48px}
  .kv{grid-template-columns:1fr}
  .chartgrid{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div id="toast"></div>

<div id="drawer-overlay" class="drawer-overlay"></div>
<aside id="drawer" class="drawer" aria-hidden="true">
  <div class="drawer-head"><div><h2 id="drawer-title">Подписка</h2><div class="sub" id="drawer-sub"></div></div><button class="drawer-close" id="drawer-close" aria-label="Закрыть">✕</button></div>
  <div class="drawer-body" id="drawer-body"></div>
  <div class="drawer-foot" id="drawer-foot"></div>
</aside>

<div id="login-view" class="loginwrap hidden">
  <div class="card">
    <h1>Drebol VPN · <span style="color:var(--acc)">Админка</span></h1>
    <p class="mut" style="margin-top:6px">Веб-версия админки бота. Вход — через Telegram (Mark) или по почте с паролем (Muse).</p>
    <div id="tg-widget" style="margin-top:14px"></div>
    <p class="mut" style="margin-top:14px">или по почте с паролем:</p>
    <input id="email" type="email" placeholder="почта" autocomplete="username">
    <input id="pw" type="password" placeholder="пароль" autocomplete="current-password">
    <button id="btn-login">Войти</button>
    <div id="login-err" class="err"></div>
  </div>
  <div id="setup" class="card hidden">
    <h2>Установка пароля</h2>
    <p class="mut">Ссылка одноразовая, живёт 15 минут. Пароль — от 8 до 128 символов.</p>
    <input id="pw2" type="password" placeholder="новый пароль" autocomplete="new-password">
    <button id="btn-setup">Задать пароль и войти</button>
    <div id="setup-err" class="err"></div>
  </div>
</div>

<div id="app-view" class="layout hidden">
  <aside class="sidebar">
    <div class="brand">Drebol VPN <span>· Админка</span><small>веб-версия админки бота</small></div>
    <nav id="nav">
      <div class="nav-group">Основное</div>
      <button class="nav-item" data-nav="overview"><span class="ic">📊</span>Обзор</button>
      <button class="nav-item" data-nav="users"><span class="ic">👤</span>Пользователи</button>
      <button class="nav-item" data-nav="subs"><span class="ic">💳</span>Подписки</button>
      <div class="nav-group">Деньги</div>
      <button class="nav-item" data-nav="finance"><span class="ic">💰</span>Финансы</button>
      <button class="nav-item" data-nav="payments"><span class="ic">🧾</span>Оплаты</button>
      <button class="nav-item" data-nav="broadcast"><span class="ic">📣</span>Рассылка</button>
      <button class="nav-item" data-nav="retention"><span class="ic">🔔</span>Напоминания и возврат</button>
      <button class="nav-item" data-nav="promos"><span class="ic">🏷️</span>Промокоды</button>
      <button class="nav-item" data-nav="tariffs"><span class="ic">💲</span>Тарифы</button>
      <div class="nav-group">Инфраструктура</div>
      <button class="nav-item" data-nav="panel"><span class="ic">🖥️</span>Панель Remnawave</button>
      <button class="nav-item" data-nav="nodes"><span class="ic">🌐</span>Узлы</button>
      <button class="nav-item" data-nav="console"><span class="ic">⌨️</span>Консоль</button>
      <button class="nav-item" data-nav="logs"><span class="ic">📜</span>Логи</button>
      <button class="nav-item" data-nav="sync"><span class="ic">⏰</span>Синхронизация</button>
      <button class="nav-item" data-nav="netcheck"><span class="ic">📡</span>Проверка операторов</button>
      <button class="nav-item" data-nav="site"><span class="ic">🌍</span>Сайт</button>
      <button class="nav-item" data-nav="backup"><span class="ic">💾</span>Бэкап</button>
      <button class="nav-item" data-nav="maintenance"><span class="ic">🛠️</span>Техработы</button>
      <div class="nav-group">Люди</div>
      <button class="nav-item" data-nav="support"><span class="ic">🛟</span>Поддержка</button>
      <button class="nav-item" data-nav="settings"><span class="ic">⚙️</span>Настройки</button>
    </nav>
  </aside>
  <main class="main">
    <div class="topbar">
      <h1 id="sec-title">Обзор</h1>
      <span id="who" class="who"></span>
      <button id="btn-logout" class="ghost" style="margin:0">Выйти</button>
    </div>
    <div class="wrap">
      <!-- Обзор -->
      <section id="sec-overview" class="page">
        <div id="stats" class="grid"></div>
        <div class="card"><h2 id="chart-period-title">Выручка и новые юзеры — 30 дней</h2><p class="sub">Выручка — нетто: оплаченные счета минус возвраты. Наведи курсор на столбец или точку — увидишь дату и значение.</p>
          <div class="btnrow" id="chart-period" style="margin-bottom:10px"><button class="ghost" data-days="7">7 дней</button><button class="ghost active" data-days="30">30 дней</button></div>
          <div class="chartgrid">
            <div><h3 style="margin-top:0">Выручка по дням</h3><div id="chart-revenue"></div></div>
            <div><h3 style="margin-top:0">Новые юзеры по дням</h3><div id="chart-users"></div></div>
          </div>
        </div>
        <div class="card"><h2>Подписки по статусу и сроку</h2><p class="sub">Живой срез базы подписок.</p>
          <div class="chartgrid">
            <div><h3 style="margin-top:0">По статусу</h3><div id="chart-status"></div></div>
            <div><h3 style="margin-top:0">По сроку тарифа</h3><div id="chart-term"></div></div>
          </div>
        </div>
        <div class="card"><h2>Платные подписки</h2><p class="sub">Последние оплаченные — сверху. Нажми на строку, чтобы открыть подписку.</p>
          <div id="paid-table"></div>
          <div class="btnrow"><button id="btn-paid-more" class="ghost">Показать ещё</button></div>
        </div>
        <div class="card"><h2>Истекают в ближайшие 3 дня</h2><p class="sub">Продлить — кнопкой «Открыть» рядом с подпиской.</p>
          <div id="expiring-out"></div>
        </div>
        <div class="card"><h2>Панель Remnawave</h2><p id="panel-line" class="mut">—</p></div>
        <div class="card"><h2>Быстрые действия</h2><p class="sub">Частые задачи — в один клик, без поиска по разделам.</p>
          <div class="btnrow">
            <button class="ghost" data-goto="users">Найти юзера</button>
            <button class="ghost" data-goto="broadcast">Новая рассылка</button>
            <button class="ghost" data-goto="payments">Оплаты</button>
            <button class="ghost" data-goto="logs">Журнал действий</button>
            <button class="ghost" data-goto="nodes">Здоровье узлов</button>
            <button class="ghost" id="btn-quick-git">Обновиться с GitHub</button>
            <button class="ghost" id="btn-quick-deploy">Деплой сайта</button>
          </div>
          <div id="quick-upd-msg" class="mut" style="margin-top:8px"></div>
        </div>
      </section>

      <!-- Пользователи -->
      <section id="sec-users" class="page hidden">
        <div class="card"><h2>Пользователи</h2><p class="sub">Все пользователи. Нажми на строку, чтобы открыть карточку. Поиск — по ID, @username, имени или email. Вкладки — по статусу последней платной подписки.</p>
          <div class="btnrow" id="users-tabs" style="flex-wrap:wrap"></div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <input id="q-user" placeholder="Поиск: имя, @username, email, tg_id" style="flex:1;min-width:200px">
            <select id="users-sort" style="width:auto;min-width:150px">
              <option value="new">Новые сверху</option>
              <option value="name">По имени</option>
              <option value="id">По TG ID</option>
            </select>
          </div>
          <div class="btnrow"><button id="btn-find">Найти</button><button id="btn-users-export" class="ghost">⬇️ CSV</button><button id="btn-recent" class="ghost">Недавние</button><button id="btn-users-prev" class="ghost">← Назад</button><button id="btn-users-next" class="ghost">Вперёд →</button><span id="users-page-label" class="mut"></span></div>
          <div id="users-out"></div>
        </div>
        <div class="card"><h2>Сообщение пользователю</h2><p class="sub">Отправляется от имени бота Drebol VPN.</p>
          <input id="dm-id" type="number" placeholder="tg_id">
          <textarea id="dm-text" placeholder="текст сообщения"></textarea>
          <button id="btn-dm">Отправить</button>
          <span id="dm-msg" class="mut"></span>
        </div>
        <div class="card"><h2>Подарок подписки</h2><p class="sub">Начислить подписку другому пользователю. Сумма — в рублях, срок — в секундах.</p>
          <input id="gift-tg" type="number" placeholder="tg_id получателя">
          <input id="gift-amount" type="number" placeholder="сумма, ₽">
          <input id="gift-seconds" type="number" placeholder="срок, секунды (напр. 2592000 = 30 дней)">
          <input id="gift-promo" placeholder="промокод (необязательно)">
          <button id="btn-gift">Подарить подписку</button>
          <div id="gift-out"></div>
        </div>
        <div class="card"><h2>Чёрный список</h2><p class="sub">Остановка подписок мошенников и нарушителей. Действие «Остановить» — с подтверждением.</p>
          <div class="btnrow"><button id="btn-blacklist" class="ghost">Показать список</button></div>
          <input id="bl-tg" type="number" placeholder="tg_id">
          <input id="bl-reason" placeholder="причина">
          <select id="bl-term"><option value="">Срок: навсегда</option><option value="day">1 день</option><option value="week">Неделя</option><option value="month">Месяц</option></select>
          <div class="btnrow"><button id="btn-bl-add" class="ghost">Добавить в ЧС</button><button id="btn-bl-stop" class="ghost">Остановить подписку</button><button id="btn-bl-readd" class="ghost">Вернуть из ЧС</button></div>
          <div id="bl-out"></div>
        </div>
        <div class="card"><h2>Повторные триалы</h2><p class="sub">Пары аккаунтов, которые, возможно, берут триал повторно. Нажми на строку, чтобы разобрать находку.</p>
          <div id="fraud-stats"></div>
          <div class="btnrow"><button id="btn-fraud" class="ghost">Показать пары</button><button id="btn-fraud-scan" class="ghost">Запустить скан</button><button id="btn-fraud-toggle" class="ghost hidden">Слежка: …</button><button id="btn-fraud-ip" class="ghost hidden">Адрес как улика: …</button></div>
          <div id="fraud-tabs" class="btnrow"></div>
          <div id="fraud-out"></div>
        </div>
      </section>

      <!-- Подписки -->
      <section id="sec-subs" class="page hidden">
        <div class="card"><h2>📥 Заявки на подписку</h2><p class="sub">Люди без подписки, которые попросили доступ. Одобрение выдаёт пробный период по пресетам, как кнопка ✅ в ТГ, и уведомляет человека в Telegram. Отклонение — тоже с уведомлением. Оба действия — с подтверждением.</p>
          <div class="btnrow"><button id="btn-requests" class="ghost">Обновить</button></div>
          <div id="requests-table"></div>
          <div id="requests-out"></div>
        </div>
        <div class="card"><h2>Платные подписки</h2><p class="sub">Вкладки и сортировка — как в ТГ. Значки: 🟢 работает · ⏳ скоро кончится · 🔴 истекла · ⏸ выключена в панели. Нажми на строку, чтобы открыть и поменять параметры — изменения сразу уходят в базу бота и в панель Remnawave. Удаление и перевыпуск — с подтверждением.</p>
          <div class="btnrow" id="subs-tabs" style="flex-wrap:wrap"></div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <input id="subs-q" placeholder="Поиск: имя, @username, email, tg_id, uuid" style="flex:1;min-width:200px">
            <select id="subs-sort" style="width:auto;min-width:150px">
              <option value="new">Новые сверху</option>
              <option value="expire">По сроку</option>
              <option value="name">По имени</option>
            </select>
            <button id="btn-subs-search">Найти</button>
            <button id="btn-subs-refresh" class="ghost">Обновить</button>
            <button id="btn-subs-export" class="ghost">⬇️ CSV</button>
          </div>
          <div id="subs-panel-warn" class="mut" style="margin-top:6px"></div>
          <div id="subs-table"></div>
          <div class="btnrow" style="margin-top:10px;align-items:center">
            <button id="btn-subs-prev" class="ghost">← Назад</button>
            <span class="mut" id="subs-page-label"></span>
            <button id="btn-subs-next" class="ghost">Вперёд →</button>
          </div>
        </div>
        <div class="card"><h2>Массовые действия</h2><p class="sub">Действие применится ко всей выбранной вкладке сразу — как в ТГ (Массовые действия).</p>
          <div class="btnrow" id="bulk-tabs" style="flex-wrap:wrap"></div>
          <div id="bulk-scope-info" class="mut" style="margin:4px 0 8px"></div>
          <select id="bulk-kind"><option value="extend">Сдвинуть срок</option><option value="limits">Сменить лимиты</option><option value="lte">Сменить LTE</option></select>
          <input id="bulk-days" type="number" placeholder="дней (+ продлить / − сократить)">
          <input id="bulk-value" type="number" placeholder="значение лимита, ГБ">
          <select id="bulk-kind-limit"><option value="hwid">лимит: устройства</option><option value="lte">лимит: LTE</option></select>
          <button id="btn-bulk">Применить к выборке</button>
          <div id="bulk-out"></div>
        </div>
        <div class="card"><h2>Пресеты подписок</h2><p class="sub">Значения по умолчанию для новых платных подписок.</p>
          <div class="btnrow"><button id="btn-presets" class="ghost">Показать пресеты</button></div>
          <div id="presets-out"></div>
        </div>
        <div class="card"><h2>Админские подписки</h2><p class="sub">Подписки, выданные вручную администратором. Вкладки и сортировка — как в ТГ, нажми на строку, чтобы открыть карточку со всеми действиями: заморозка, продление, устройства, история.</p>
          <div class="btnrow" id="asub-tabs" style="flex-wrap:wrap"></div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <input id="asub-q" placeholder="Поиск: имя, @username, email, tg_id" style="flex:1;min-width:200px">
            <select id="asub-sort" style="width:auto;min-width:150px">
              <option value="new">Новые сверху</option>
              <option value="expire">По сроку</option>
              <option value="name">По имени</option>
            </select>
            <button id="btn-asub-search">Найти</button>
            <button id="btn-asub-refresh" class="ghost">Обновить</button>
          </div>
          <div id="asub-table"></div>
          <div class="btnrow" style="margin-top:10px;align-items:center">
            <button id="btn-asub-prev" class="ghost">← Назад</button>
            <span class="mut" id="asub-page-label"></span>
            <button id="btn-asub-next" class="ghost">Вперёд →</button>
          </div>
          <input id="asub-tg" type="number" placeholder="tg_id — создать админскую подписку">
          <div class="btnrow"><button id="btn-asub" class="ghost">Создать админскую подписку</button></div>
          <div id="asub-out"></div>
        </div>
        <div class="card"><h2>Рефералка</h2><p class="sub">Кто приводит друзей и какие бонусы настроены.</p>
          <div class="btnrow"><button id="btn-referrals" class="ghost">Показать рефералку</button><button id="btn-lte" class="ghost">Проверить LTE сейчас</button></div>
          <div id="ref-out"></div>
        </div>
      </section>

      <!-- Финансы -->
      <section id="sec-finance" class="page hidden">
        <div class="card"><h2>Финансовая сводка</h2><p class="sub">Доход за вычетом возвратов, расходы на серверы.</p>
          <select id="fin-period"></select>
          <div class="btnrow"><button id="btn-finance">Показать сводку</button><button id="btn-servers" class="ghost">Серверы (расходы)</button></div>
          <div id="finance-out"></div>
        </div>
        <div class="card"><h2>Платёжная система — Platega</h2><p class="sub">Секретный ключ и Merchant ID — только для записи, в ответе они не показываются.</p>
          <div class="btnrow"><button id="btn-platega" class="ghost">Показать состояние</button></div>
          <input id="pl-merchant" placeholder="Merchant ID">
          <input id="pl-secret" type="password" placeholder="API-ключ (секрет, только запись)" autocomplete="off">
          <button id="btn-platega-save">Сохранить</button>
          <div id="platega-out"></div>
        </div>
        <div class="card"><h2>Сверка с Platega</h2><p class="sub">Проверяет счета за 60 дней. «Исправить» меняет только денежные поля — сроки подписок не трогает.</p>
          <div class="btnrow"><button id="btn-reconcile">Запустить сверку</button><button id="btn-reconcile-fix" class="ghost">Исправить расхождения</button></div>
          <div id="reconcile-out"></div>
        </div>
        <div class="card"><h2>Серверы (расходы)</h2><p class="sub">Ежемесячные расходы на серверы и их оплата. Нажми на строку, чтобы изменить сервер или отметить оплату.</p>
          <input id="srv-name" placeholder="название сервера">
          <input id="srv-price" type="number" placeholder="цена, ₽/мес">
          <input id="srv-day" type="number" placeholder="день оплаты (1–31)">
          <div class="btnrow"><button id="btn-srv-add">Добавить сервер</button><button id="btn-servers-list" class="ghost">Обновить список</button></div>
          <div id="srv-out"></div>
        </div>
      </section>

      <!-- Оплаты -->
      <section id="sec-payments" class="page hidden">
        <div class="card"><h2>Оплаты</h2><p class="sub">Счета платёжной системы. Нажми на строку, чтобы открыть карточку. Возврат — с подтверждением, повторный возврат невозможен.</p>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <select id="pay-status" style="width:auto;min-width:170px"><option value="">Все статусы</option><option value="paid">Оплаченные</option><option value="pending">Ожидают</option><option value="refunds">Возвращённые</option><option value="failed">Неудачные</option></select>
            <select id="pay-provider" style="width:auto;min-width:150px"><option value="">Все провайдеры</option></select>
            <input id="pay-q" type="search" placeholder="Имя, @username, TG ID или № счёта" style="flex:1;min-width:200px">
            <button id="btn-payments">Показать оплаты</button>
            <button id="btn-payments-export" class="ghost">⬇️ CSV</button>
          </div>
          <div id="payments-summary" class="mut" style="margin-top:8px"></div>
          <div id="payments-out"></div>
          <div class="btnrow"><button id="btn-payments-prev" class="ghost">← Назад</button><span id="payments-page-label" class="mut"></span><button id="btn-payments-next" class="ghost">Вперёд →</button></div>
        </div>
      </section>

      <!-- Рассылка -->
      <section id="sec-broadcast" class="page hidden">
        <div class="card"><h2>Рассылка</h2><p class="sub">Сначала предпросмотр — сколько человек получит сообщение, — потом отправка с подтверждением.</p>
          <textarea id="bc-text" placeholder="текст рассылки (HTML)"></textarea>
          <select id="bc-seg">
            <option value="all">Все</option><option value="active">Активные</option>
            <option value="expired">Истёкшие</option><option value="trial">Триал</option>
            <option value="paying">Платящие</option><option value="no_sub">Без подписки</option>
          </select>
          <label>Фото (необязательно, до 10 МБ — загрузится в Telegram и прикрепится к рассылке)</label>
          <input id="bc-photo" type="file" accept="image/*">
          <div class="btnrow"><button id="btn-bc-upload" class="ghost">Загрузить фото</button><span id="bc-photo-msg" class="mut"></span></div>
          <div class="btnrow"><button id="btn-bc-preview" class="ghost">Предпросмотр</button><button id="btn-bc-send">Отправить</button></div>
          <div id="bc-out" class="mut"></div>
        </div>
        <div class="card"><h2>📢 Пост в ТГ-канал</h2><p class="sub">Публикация в канал — как кнопка «Пост в ТГК» в админке бота: текст с подписью, фото и кнопки из меню /start. Сначала предпросмотр, потом публикация с подтверждением.</p>
          <div id="ch-status" class="mut">Загрузка…</div>
          <textarea id="ch-text" placeholder="текст поста (HTML: b, i, a href, code, blockquote)"></textarea>
          <label>Фото (необязательно, до 10 МБ каждое — можно несколько; альбом из 2+ фото уйдёт без кнопок)</label>
          <input id="ch-photo" type="file" accept="image/*" multiple>
          <div class="btnrow"><button id="btn-ch-upload" class="ghost">Загрузить фото</button><span id="ch-photo-msg" class="mut"></span></div>
          <div id="ch-photos" class="mut"></div>
          <label class="chk"><input id="ch-use-sign" type="checkbox" checked> Добавлять подпись к посту</label>
          <div id="ch-buttons"></div>
          <div class="btnrow"><button id="btn-ch-preview" class="ghost">👀 Предпросмотр</button><button id="btn-ch-publish">🚀 Опубликовать</button></div>
          <div id="ch-out" class="mut"></div>
          <h3>Подпись к постам</h3>
          <p class="sub">Дописывается в конец каждого поста. Та же подпись, что в админке бота.</p>
          <textarea id="ch-sign" placeholder="текст подписи (HTML)"></textarea>
          <div class="btnrow"><button id="btn-ch-sign-save" class="ghost">Сохранить подпись</button><button id="btn-ch-sign-del" class="danger">Убрать подпись</button></div>
          <div id="ch-sign-out" class="mut"></div>
        </div>
      </section>

      <!-- Напоминания и возврат -->
      <section id="sec-retention" class="page hidden">
        <div class="card"><h2>⏰ Напоминания о конце подписки</h2><p class="sub">Бот заранее пишет, что срок подходит к концу, и зовёт продлить — остаток при оплате не сгорает. Каждое напоминание уходит один раз за период, продление сбрасывает счёт. Срок — «3 дня», «12 часов» или «0» (выключено).</p>
          <div id="ret-remind-status" class="mut">Загрузка…</div>
          <div id="ret-remind-stats" class="mut"></div>
          <label class="chk"><input id="ret-remind-enabled" type="checkbox"> Напоминания включены</label>
          <label class="chk"><input id="ret-remind-trials" type="checkbox"> Писать пробным подпискам</label>
          <label>Первое напоминание<input id="ret-remind-first" placeholder="напр. 3 дня"></label>
          <label>Второе напоминание<input id="ret-remind-second" placeholder="напр. 1 день"></label>
          <label>Третье напоминание<input id="ret-remind-third" placeholder="напр. 12 часов"></label>
          <label>Тихие часы — с (час, 0–23)<input id="ret-remind-quiet-from" type="number" min="0" max="23" placeholder="23"></label>
          <label>Тихие часы — до (час, 0–23)<input id="ret-remind-quiet-to" type="number" min="0" max="23" placeholder="9"></label>
          <p class="sub">В тихие часы бот не пишет — отправит, когда окно закончится. Оба поля пустые — тихих часов нет.</p>
          <div class="btnrow"><button id="btn-ret-remind-save">Сохранить напоминания</button><button id="btn-ret-remind-test" class="ghost hidden">📨 Прислать пример</button></div>
          <div id="ret-remind-out" class="mut"></div>
        </div>
        <div class="card"><h2>🎯 Возврат ушедших</h2><p class="sub">Бот пишет тем, у кого подписка закончилась, и даёт личный промокод с коротким сроком. Людям из чёрного списка не пишет.</p>
          <div id="ret-winback-status" class="mut">Загрузка…</div>
          <div id="ret-winback-stats" class="mut"></div>
          <label class="chk"><input id="ret-winback-enabled" type="checkbox"> Возврат включён</label>
          <label class="chk"><input id="ret-winback-paid-only" type="checkbox"> Только тем, кто платил</label>
          <label>Первая волна — через дней<input id="ret-winback-days" type="number" min="1" placeholder="3"></label>
          <label>Скидка первой волны, %<input id="ret-winback-percent" type="number" min="1" max="100" placeholder="20"></label>
          <label>Вторая волна — через дней (0 — выключена)<input id="ret-winback-days2" type="number" min="0" placeholder="0"></label>
          <label>Скидка второй волны, %<input id="ret-winback-percent2" type="number" min="1" max="100" placeholder="35"></label>
          <label>Промокод живёт, дней<input id="ret-winback-life" type="number" min="1" placeholder="3"></label>
          <div class="btnrow"><button id="btn-ret-winback-save">Сохранить возврат</button><button id="btn-ret-winback-test" class="ghost hidden">📨 Прислать пример</button></div>
          <div id="ret-winback-out" class="mut"></div>
        </div>
      </section>

      <!-- Промокоды -->
      <section id="sec-promos" class="page hidden">
        <div class="card"><h2>Промокоды</h2><p class="sub">Скидки и бонусы для новых и действующих пользователей. Нажми на строку, чтобы изменить промокод, выключить его или удалить.</p>
          <div class="btnrow"><button id="btn-promos">Показать промокоды</button></div>
          <input id="pr-code" placeholder="код, напр. DREBOL10">
          <label>Награда<select id="pr-kind"><option value="percent">Скидка, %</option><option value="days">Дни подписки</option></select></label>
          <input id="pr-value" type="number" placeholder="размер: % (1–100) или дни (1–365)">
          <input id="pr-max" type="number" placeholder="лимит использований (пусто/0 — без лимита)">
          <label class="chk"><input id="pr-first" type="checkbox"> Только для первой покупки</label>
          <input id="pr-exp" placeholder="истекает, напр. 2026-12-31 (пусто — без срока)">
          <input id="pr-owner" type="number" placeholder="tg_id владельца (необязательно)">
          <input id="pr-note" placeholder="заметка (необязательно)">
          <div class="btnrow"><button id="btn-pr-add">Создать промокод</button><button id="btn-pr-find" class="ghost">Найти по коду</button></div>
          <input id="pr-count" type="number" placeholder="сколько кодов сгенерировать пачкой (награда — та же, что выше)">
          <div class="btnrow"><button id="btn-pr-batch" class="ghost">Сгенерировать пачку</button></div>
          <div id="promos-out"></div>
        </div>
        <div class="card"><h2>🎁 Выдать промокод</h2><p class="sub">Личный код для одного человека: действует 14 дней, одно применение, работает только у него. Бот сразу отправит ему код сообщением. Награда — как в ТГ: пресеты или своя величина («35» — скидка 35%, «10 дней» — дни в подарок).</p>
          <input id="give-target" placeholder="TG ID или @username">
          <div class="btnrow" id="give-presets" style="flex-wrap:wrap"></div>
          <input id="give-custom" placeholder="своя величина: 35 или 10 дней (необязательно)">
          <div class="btnrow"><button id="btn-give">Выдать промокод</button></div>
          <div id="give-out"></div>
        </div>
        <div class="card"><h2>📤 Раздать сегменту</h2><p class="sub">Каждый получит свой личный код — переслать его другому не выйдет. Админ и люди из чёрного списка пропускаются. Отправка идёт с паузами, как в ТГ.</p>
          <label>Кому<select id="seg-select"></select></label>
          <div class="btnrow" id="seg-presets" style="flex-wrap:wrap"></div>
          <input id="seg-custom" placeholder="своя величина: 35 или 10 дней (необязательно)">
          <div class="btnrow"><button id="btn-seg">Раздать промокоды</button></div>
          <div id="seg-out"></div>
        </div>
        <div class="card"><h2>📊 Что принесли промокоды</h2><p class="sub">Сколько оплат прошло с промокодами и на какую сумму. Сумма — то, что реально заплатили со скидкой. Подарочные дни денег не приносят, они держат людей.</p>
          <div class="btnrow"><button id="btn-promo-income" class="ghost">Показать доход</button></div>
          <div id="promo-income-out"></div>
        </div>
      </section>

      <!-- Тарифы -->
      <section id="sec-tariffs" class="page hidden">
        <div class="card"><h2>Тарифы</h2><p class="sub">Варианты продления, которые видит клиент. Цена и срок влияют на продление в кабинете и на сайте. Нажми на строку, чтобы изменить тариф.</p>
          <div class="btnrow"><button id="btn-tariff-add">Новый тариф</button><button id="btn-tariffs" class="ghost">Обновить</button></div>
          <div id="tariffs-out"></div>
        </div>
      </section>
      <!-- Панель Remnawave -->
      <section id="sec-panel" class="page hidden">
        <div class="card"><h2>Панель Remnawave</h2><p class="sub">Профили, инбаунды и хосты — живые данные из панели. Нажми на строку, чтобы открыть профиль или хост в редакторе ниже. Правка инбаундов и хостов — только Mark, с проверкой конфига после сохранения.</p>
          <div class="btnrow"><button id="btn-panel" class="ghost">Обновить списки</button><button id="btn-yandex" class="ghost">Яндекс Клауд: зеркало</button><button id="btn-links-panel" class="ghost">🔗 Основные ссылки</button></div>
          <div id="panel-out"></div>
          <h3>Профили</h3>
          <div id="profiles-table"></div>
          <h3>Хосты</h3>
          <div id="hosts-table"></div>
        </div>
        <div class="card"><h2>🏷 Теги подписчиков</h2><p class="sub">Тег стоит у клиента в панели и показывает статус человека. Счётчики — по данным бота. «Применить ко всем» приведёт теги в панели к этим статусам; дальше бот обновляет тег сам при смене статуса: оплата, выдача, истечение, бан и разбан. Применение — только Mark, с подтверждением.</p>
          <div class="btnrow"><button id="btn-tags" class="ghost">Обновить счётчики</button><button id="btn-tags-apply">Применить ко всем</button></div>
          <div id="tags-table"></div>
          <div id="tags-out"></div>
        </div>
        <div class="card" id="panel-profile-card"><h2>Редактор инбаунда</h2><p class="sub">Меняются только заполненные поля. Приватные ключи и shortId здесь не трогаются.</p>
          <input id="pf-uuid" placeholder="UUID профиля">
          <div class="btnrow"><button id="btn-pf-load" class="ghost">Показать профиль</button></div>
          <input id="pf-tag" placeholder="тег инбаунда, напр. VTR-Germany-1">
          <input id="pf-port" type="number" placeholder="порт (пусто — не менять)">
          <input id="pf-sni" placeholder="SNI, через запятую (пусто — не менять)">
          <input id="pf-dest" placeholder="target/dest, напр. www.google.com:443 (пусто — не менять)">
          <input id="pf-fp" placeholder="fingerprint: chrome/firefox (пусто — не менять)">
          <div class="btnrow"><button id="btn-pf-save" class="ghost">Сохранить инбаунд</button></div>
          <div id="pf-out"></div>
        </div>
        <div class="card" id="panel-hosts-card"><h2>Создание и правка хостов</h2><p class="sub">Новый хост создаётся выключенным — включите его после проверки.</p>
          <input id="ph-inbound" placeholder="UUID инбаунда (для нового хоста)">
          <input id="ph-remark" placeholder="имя хоста">
          <input id="ph-addr" placeholder="адрес">
          <input id="ph-port" type="number" placeholder="порт">
          <input id="ph-sni" placeholder="SNI">
          <div class="btnrow"><button id="btn-ph-create" class="ghost">Создать хост</button></div>
          <input id="ph-uuid" placeholder="UUID хоста — правка / удаление">
          <select id="ph-disabled"><option value="false">Включён</option><option value="true">Выключен</option></select>
          <div class="btnrow"><button id="btn-ph-toggle" class="ghost">Вкл / выкл хост</button><button id="btn-ph-del" class="danger">Удалить хост</button></div>
          <div id="ph-out"></div>
        </div>
        <div class="card"><h2>Настройки панели</h2><p class="sub">Адрес панели. Токен панели в вебе не показывается и не меняется — только из ТГ.</p>
          <input id="ps-url" placeholder="адрес панели https://panelremna.drbl.tech">
          <div class="btnrow"><button id="btn-ps-show" class="ghost">Показать</button><button id="btn-ps-save" class="ghost">Сохранить адрес панели</button><button id="btn-ps-test" class="ghost">Проверить связь с панелью</button></div>
          <div id="ps-out"></div>
        </div>
      </section>

      <!-- Узлы -->
      <section id="sec-nodes" class="page hidden">
        <div class="card"><h2>Узлы и здоровье</h2><p class="sub">Живой статус нод, панели и сайта подписки. Нажми на строку ноды, чтобы посмотреть её трафик.</p>
          <div class="btnrow"><button id="btn-nodes">Здоровье узлов</button><button id="btn-squads" class="ghost">Сквады</button><button id="btn-links-nodes" class="ghost">🔗 Основные ссылки</button></div>
          <div id="nodes-table"></div>
          <div id="nodes-snapshot"></div>
          <h3>Трафик</h3>
          <p class="sub">Потребление пользователей по узлам за период — как экран «Трафик» в боте.</p>
          <div class="btnrow" id="usage-period"></div>
          <div class="btnrow hidden" id="usage-custom"><input id="node-start" type="date"><input id="node-end" type="date"><button id="btn-usage-custom" class="ghost">Показать</button></div>
          <div class="btnrow"><button id="btn-usage-all" class="ghost">Все ноды</button></div>
          <div id="nodes-usage"></div>
          <div id="nodes-out"></div>
        </div>
        <div class="card" id="yandex-cdn-doc"><h2>Yandex Cloud CDN перед нодами</h2><p class="sub">Инструкция: сертификат, дубликат ноды, CDN-ресурс, хост в панели. Источник — INSTRUCTION.md, карточка пересобирается скриптом build_admin_html.py.</p>
        <p>Цель: поставить перед нодой Швеции (потом Румынии) Yandex Cloud CDN, как уже сделано для Германии и Финляндии. CDN прячет реальный IP ноды и даёт свой сертификат. Порядок: Швеция → Румыния.</p>
        <p>Доменная схема:</p>
        <ul><li>Германия: нода <code class="mono">denode1.drbl.tech</code>, CDN-домен <code class="mono">de1cdn.drbl.tech</code></li><li>Швеция: нода <code class="mono">senode1.drbl.tech</code>, CDN-домен <code class="mono">se1cdn.drbl.tech</code></li><li>Румыния: нода <code class="mono">ronode1.drbl.tech</code>, CDN-домен <code class="mono">ro1cdn.drbl.tech</code></li></ul>
        <details><summary>Образец: рабочий ресурс Финляндии <code class="mono">fin1cdn.drbl.tech</code></summary>
        <p>ID <code class="mono">bc8r6d1c6663p5pte2n7</code>, создан 19.10.2026. Точные настройки из его карточки (скриншоты 2026-11-16 01:20):</p>
        <ul><li>Группа источников: <code class="mono">common-95-85-251-169</code> (авто-группа Яндекса, её искать не надо)</li><li>Протокол для источников: <b>HTTP</b></li><li>Доступ к контенту: Разрешен</li><li>Заголовок Host: <b>Как у клиента</b></li><li>Тип сертификата: <code class="mono">fin1cdn</code>, статус <b>Выпущен</b></li><li>Переадресация клиентов: <b>Не использовать</b></li><li>Доступ по защищённому токену / по IP-адресам / по странам: выключено</li><li>Перенаправление запросов / следование перенаправлениям: выключено</li><li>Кеширование в CDN: <b>Выключено</b>, в браузере: <b>Выключено</b>, Cookie — <b>Не игнорировать</b>, query-параметры — <b>Не кешировать</b></li><li>Скрытие заголовков источника: <b>Не скрывать</b></li><li>CORS: <b>Не добавлять</b></li><li>Настраиваемый HTTP-ответ: <b>Включено</b></li><li>gzip-сжатие: <b>Не сжимать</b>, сегментация больших файлов: <b>Не сегментировать</b></li><li>DNS: <code class="mono">fin1cdn.drbl.tech</code> → CNAME <code class="mono">8d4319fdecfff922.topology.gslb.yccdn.ru</code></li><li>Метрики за 30 дней: 37,14 ГБ из источников, 2 435 046 запросов, ответы из кеша — 0 (кэш выключен, всё идёт в origin). Финляндия через CDN реально работает, хотя IP ноды заблочен.</li></ul>
        <p>Образец сертификата Германии <code class="mono">de1cdn</code>: ID <code class="mono">fpqbh7g6dhv19nfb1dud</code>, Issued, Managed, LETS_ENCRYPT, <code class="mono">de1cdn.drbl.tech</code>, 19.10.2026 → 17.01.2027. Проверка прав — <b>CNAME-запись</b> (не TXT!): <code class="mono">_acme-challenge.de1cdn.drbl.tech</code> → <code class="mono">fpqbh7g6dhv19nfb1dud.cm.yandexcloud.net</code>, статус Valid. CNAME делегирует проверку Яндексу — Managed-сертификат продлевается сам. CNAME и TXT одновременно НЕ добавлять.</p>
        </details>
        <details><summary>Шаг 1. Сертификат</summary>
        <p>В консоли Yandex Cloud: Certificate Manager → «Создать сертификат от Let&#x27;s Encrypt».</p>
        <ul><li><b>Имя:</b> <code class="mono">se1cdn</code> (для Румынии — <code class="mono">ro1cdn</code>)</li><li><b>Описание:</b> пусто</li><li><b>Защита от удаления:</b> включить</li><li><b>Домены</b> (каждый с новой строки): <code class="mono">se1cdn.drbl.tech</code></li><li><b>Тип проверки:</b> <b>DNS</b></li></ul>
        <p>Нажать «Создать». Яндекс покажет CNAME-запись для проверки (имя <code class="mono">_acme-challenge.se1cdn.drbl.tech</code>, значение <code class="mono">&lt;id-сертификата&gt;.cm.yandexcloud.net</code> — ID будет свой).</p>
        <p>Добавить эту CNAME-запись у DNS-провайдера домена <code class="mono">drbl.tech</code>. Дождаться статуса <b>Valid</b> и <b>Issued</b> в карточке сертификата.</p>
        </details>
        <details><summary>Шаг 2. Дубликат ноды «Швеция [CDN]» в панели и на сервере</summary>
        <p>CDN-инбаунд живёт в отдельной ноде-дубликате на том же физическом сервере — как «Германия [CDN]» (<code class="mono">denode1.drbl.tech</code>) и «Финляндия [CDN]» (<code class="mono">finnode1.drbl.tech</code>).</p>
        <p><b>В панели Remnawave: Nodes → Management → у ноды «Швеция» — кнопка дубликата.</b> В копии поменять:</p>
        <ul><li>Имя: <b>«Швеция [CDN]»</b></li><li>Address: <code class="mono">senode1.drbl.tech</code> (A-запись → <code class="mono">81.90.21.84</code>)</li><li>Node Port: <code class="mono">12222</code> (как у <code class="mono">remnanode2</code> в Германии и Финляндии)</li><li>Кнопка <b>Copy docker-compose.yml</b> — в ней новый порт и секретный ключ.</li></ul>
        <p>Проверить, что порт свободен на сервере Швеции:</p>
        <pre>ss -tlnp | grep 12222</pre>
        <p>(пусто — свободен).</p>
        <p><b>На сервере Швеции (<code class="mono">81.90.21.84</code>):</b></p>
        <pre>mkdir -p /opt/remnanode2 &amp;&amp; cd /opt/remnanode2
        nano docker-compose.yml</pre>
        <p>Вставить скопированный compose и поменять одну строку — <code class="mono">container_name: remnanode</code> → <code class="mono">container_name: remnanode2</code>, иначе конфликт с первой нодой. Итоговый файл (шаблон панели, одинаковый для всех [CDN]-дубликатов):</p>
        <pre>services:
          remnanode:
            container_name: remnanode2
            image: remnawave/node:latest
            # network_mode: host
            ports:
              - &quot;12222:12221&quot;  # API: внешний 12222 = Node Port в панели
              - &quot;8880:8880&quot;    # XHTTP-инбаунд (VXC)
            restart: always
            cap_add:
              - NET_ADMIN
            ulimits:
              nofile:
                soft: 1048576
                hard: 1048576
            environment:
              - NODE_PORT=12221
              - SECRET_KEY=&quot;...&quot;  # из панели</pre>
        <p>Пояснения к шаблону:</p>
        <ul><li><code class="mono">network_mode: host</code> НЕ используется — вместо него проброс портов.</li><li>Внешний API-порт <code class="mono">12222</code> = Node Port в панели; внутри контейнера API слушает <code class="mono">12221</code> (<code class="mono">NODE_PORT=12221</code>).</li><li>XHTTP-инбаунд дубликата — порт <code class="mono">8880</code> (тот же номер, что VXC у основной ноды, но инбаунды распределены между нодами: на основной ноде VXC не слушается, поэтому конфликта нет). Прецедент: у Фин VXC 8880 висит именно на ноде [CDN] (<code class="mono">finnode1.drbl.tech</code>).</li><li>Монт letsencrypt НЕ нужен (у [CDN]-ноды только XHTTP без TLS).</li><li>ВНИМАНИЕ: кавычки вокруг SECRET_KEY должны быть обычными прямыми <code class="mono">&quot;</code> — если там «ёлочки» (вставка их подменила), панель не примет ключ и нода не позеленеет.</li></ul>
        <p>Сохранить и запустить:</p>
        <pre>docker compose up -d &amp;&amp; docker compose logs -f -t</pre>
        <p>Проверка: <code class="mono">docker ps</code> — у <code class="mono">remnanode2</code> должны быть <code class="mono">0.0.0.0:8880-&gt;8880</code> и <code class="mono">0.0.0.0:12222-&gt;12221</code> (как у Финляндии). В панели нода «Швеция [CDN]» должна стать зелёной.</p>
        <p><b>В панели:</b> Next → выбрать Config Profile → Create. Профиль — тот же, что у «Германия [CDN]» (там XHTTP-инбаунд под CDN).</p>
        <p><b>Файрвол:</b> порт <code class="mono">12222</code> открыть только для IP панели <code class="mono">144.31.223.252</code> — то же правило, что и для порта первой ноды.</p>
        </details>
        <details><summary>Шаг 3. CDN-ресурс в Yandex Cloud</summary>
        <p>В консоли Yandex Cloud: <b>Cloud CDN → Create resource</b>.</p>
        <p><b>Копирование конфигурации:</b> вверху формы — <b>Copy a configuration → <code class="mono">de1cdn</code></b> (или <code class="mono">fin1cdn</code>). Копия подставляет почти все поля. ОБЯЗАТЕЛЬНО поменять после копирования (консоль подставляет и их!):</p>
        <ul><li><b>Доменное имя</b> — там будет <code class="mono">de1cdn.drbl.tech</code> → поменять на <code class="mono">se1cdn.drbl.tech</code> (иначе Яндекс не даст создать ресурс — домен занят).</li><li><b>Доменное имя источника</b> — <code class="mono">senode1.drbl.tech:8880</code>.</li><li><b>Сертификат</b> — <code class="mono">se1cdn</code>.</li></ul>
        <p><b>Шаг 1 из 4 — Основные настройки:</b></p>
        <ul><li>Доступ к контенту: включён</li><li>Запрос контента: <code class="mono">Из одного источника</code></li><li>Тип источника: <code class="mono">Сервер</code></li><li>Доменное имя источника: <code class="mono">senode1.drbl.tech:8880</code> — домен ноды-дубликата + порт XHTTP-инбаунда. <b>IP НИКОГДА не указывается</b> (как у зеркала подписки origin = <code class="mono">key.drbl.tech</code> — домен, не IP). Без <code class="mono">:8880</code> CDN пойдёт на 80-й порт, а там декой-сайт, не Xray.</li><li>Протокол для источников: <code class="mono">HTTP</code></li><li>Заголовок Host: <code class="mono">Как у клиента</code> (НЕ «Свое значение» — оно требует заполнять поле)</li><li>Доменное имя: <code class="mono">se1cdn.drbl.tech</code> (primary; после создания не меняется)</li><li>Тип сертификата: <code class="mono">Сертификат из Certificate Manager</code> → <code class="mono">se1cdn</code> (НЕ «Не использовать» — иначе будет только HTTP)</li><li>Перенаправление запросов: выключено</li><li>Следование перенаправлениям от источника: выключено</li><li>Профиль безопасности TLS: <code class="mono">Безопасный (TLSv1.2+)</code></li><li>Переадресация клиентов: <code class="mono">Не использовать</code> (как у Фин; НЕ «С HTTP на HTTPS»)</li><li>Доступ по защищённому токену / по IP-адресам / по странам: выключено</li></ul>
        <p><b>Шаг 2 из 4 — Кеширование:</b></p>
        <ul><li>Кеширование в CDN: <b>ВЫКЛЮЧИТЬ</b> — в форме тумблер по умолчанию ВКЛЮЧЁН, обязательно выключить (для VPN кэш нельзя включать).</li><li>Кеширование в браузере: выключено</li><li>Кеширование query-параметров: <code class="mono">Не кешировать</code></li><li>Игнорировать файлы cookie: галочка НЕ стоит (т.е. не игнорировать)</li><li>gzip-сжатие: выключено, сегментация больших файлов: выключено</li></ul>
        <p><b>Шаг 3 из 4 — HTTP-заголовки и методы:</b></p>
        <ul><li>Заголовки запроса к источнику / ответа клиенту: ничего не добавлять</li><li>Скрытие заголовков источника: <code class="mono">Не скрывать</code></li><li>CORS: <code class="mono">Не добавлять</code></li><li>Разрешенные методы: не трогать (по умолчанию)</li><li>Настраиваемый HTTP-ответ: <b>Включить</b> (у Фин включён)</li></ul>
        <p><b>Шаг 4 из 4 — Дополнительно:</b> ничего не включать (лог-экспорт, shielding — выключены).</p>
        <p>Нажать <b>Создать</b> и дождаться активации (до 15 минут).</p>
        <p><b>DNS после создания ресурса:</b> в карточке ресурса взять домен провайдера (вида <code class="mono">xxx.topology.gslb.yccdn.ru</code>) и направить на него <code class="mono">se1cdn.drbl.tech</code> через <b>CNAME</b>. Не путать с CNAME-записью <code class="mono">_acme-challenge</code> из шага 1 — она остаётся как есть.</p>
        </details>
        <details><summary>Шаг 4. Хост в панели и проверка</summary>
        <ul><li>В ноде «Швеция [CDN]» создать хост CDN-инбаунда (XHTTP VLESS) на домене <code class="mono">se1cdn.drbl.tech</code>, порт 443.</li><li>Добавить хост в шаблон автовыбора (по аналогии с Германией [LTE]).</li><li>Проверить в клиенте (INCY/Happ): подключение через <code class="mono">se1cdn.drbl.tech:443</code> работает, IP не палится.</li><li>Проверка origin без клиента: <code class="mono">curl -sk https://se1cdn.drbl.tech/api/...</code> (путь XHTTP-инбаунда) — должен вернуть 404 (не 502/000); 502 = CDN не достаёт origin, 000 = DNS/edge не готов.</li></ul>
        </details>
        <details><summary>Румыния — то же самое, подстановки</summary>
        <ul><li>Сертификат: имя <code class="mono">ro1cdn</code>, домен <code class="mono">ro1cdn.drbl.tech</code>, проверка DNS (CNAME).</li><li>Дубликат ноды: «Румыния [CDN]», адрес <code class="mono">ronode1.drbl.tech</code> → A-запись на <code class="mono">89.125.166.26</code>, Node Port <code class="mono">12222</code> (проверить <code class="mono">ss -tlnp | grep 12222</code> на сервере Румынии), второй remnanode в <code class="mono">/opt/remnanode2</code>, <code class="mono">container_name: remnanode2</code>, тот же шаблон compose (порты <code class="mono">12222:12221</code> + <code class="mono">8880:8880</code>).</li><li>CDN-ресурс: копия конфигурации с <code class="mono">de1cdn</code>, домен <code class="mono">ro1cdn.drbl.tech</code>, origin <code class="mono">ronode1.drbl.tech:8880</code>, протокол HTTP, Host «Как у клиента», сертификат <code class="mono">ro1cdn</code>, переадресация клиентов «Не использовать», кеширование в CDN выключено (тумблер по умолчанию включён!), настраиваемый HTTP-ответ включён.</li><li>DNS: <code class="mono">ro1cdn.drbl.tech</code> → CNAME на домен провайдера из карточки ресурса.</li><li>Хост в панели: XHTTP VLESS <code class="mono">ro1cdn.drbl.tech:443</code> + тест в клиенте.</li></ul>
        <p>_Написано по итогам настройки Швеции, 2026-11-16. Mark правит, если что-то не так._</p>
        </details>
        </div>
        <!-- /yandex-cdn-doc -->
      </section>

      <!-- Логи -->
      <section id="sec-logs" class="page hidden">
        <div class="card"><h2>Журнал действий и ошибок</h2><p class="sub">Аудит всех действий админов — и в ТГ, и в вебе — в одной ленте. Секреты в журнал не попадают.</p>
          <div class="btnrow" id="logs-tabs" style="flex-wrap:wrap"></div>
          <div class="btnrow" id="logs-filters" style="flex-wrap:wrap">
            <select id="logs-kind-filter"><option value="">Вид действия: все</option><option value="cb">Кнопки</option><option value="cmd">Команды</option><option value="msg">Сообщения</option><option value="ev">События</option></select>
            <select id="logs-date"><option value="">Дата: все</option><option value="today">Сегодня</option><option value="yesterday">Вчера</option><option value="week">7 дней</option></select>
            <input id="logs-user" type="number" placeholder="tg_id (необязательно)">
            <input id="logs-from" placeholder="с даты, напр. 2026-11-01">
            <input id="logs-to" placeholder="по дату, напр. 2026-11-15">
          </div>
          <div class="btnrow"><button id="btn-logs">Показать журнал</button><a id="btn-logs-export" href="/api/admin/logs/export?kind=activity"><button type="button" class="ghost">Скачать CSV</button></a><button id="btn-logs-reset" class="ghost" type="button">Сбросить фильтры</button><button id="btn-logs-purge" class="danger">Очистить старые записи</button></div>
          <div id="logs-out"></div>
          <div class="btnrow"><button id="btn-logs-prev" class="ghost">← Назад</button><span id="logs-page-label" class="mut"></span><button id="btn-logs-next" class="ghost">Вперёд →</button></div>
        </div>
        <div class="card"><h2>Падения и сбои</h2><p class="sub">Когда узлы и панель были недоступны.</p>
          <div class="btnrow"><button id="btn-downtime" class="ghost">Показать падения</button><button id="btn-online" class="ghost">Кто онлайн</button></div>
          <div id="downtime-out"></div>
        </div>
      </section>

      <!-- Синхронизация -->
      <section id="sec-sync" class="page hidden">
        <div class="card"><h2>Полная синхронизация</h2><p class="sub">Одним проходом: подписки и ники ↔ панель, узлы и хосты, сквады, сайт, чёрный список, сверка Platega. Только вручную.</p>
          <div class="btnrow"><button id="btn-psync">Запустить полную синхронизацию</button><button id="btn-psync-set" class="ghost">Последний отчёт</button></div>
          <div id="psync-out"></div>
        </div>
        <div class="card"><h2>Утренняя сводка 09:00</h2><p class="sub">Что входит в ежедневную сводку, какие фоновые задачи работают, и во сколько приходит сводка. Галочки — те же тумблеры, что в ТГ на экране «⏰ Синхронизация».</p>
          <div class="btnrow"><button id="btn-morning">Показать настройки</button><button id="btn-morning-run">Запустить сводку сейчас</button></div>
          <input id="mor-time" placeholder="время, напр. 09:00 (пусто — не менять)">
          <label><input id="mor-enabled" type="checkbox"> сводка включена</label>
          <div id="morning-toggles"></div>
          <div class="btnrow"><button id="btn-morning-save" class="ghost">Сохранить</button></div>
          <div id="morning-out"></div>
        </div>
        <div class="card"><h2>Задания (run-now)</h2><p class="sub">Запустить любую фоновую задачу вручную, не дожидаясь расписания.</p>
          <select id="job-sel">
            <option value="expiry_reminder">Напоминания об истечении</option>
            <option value="lte_fallback">Проверка LTE</option>
            <option value="check_expired">Проверка истёкших подписок</option>
            <option value="winback">Возврат ушедших</option>
            <option value="fraud">Фрод-скан</option>
            <option value="blacklist_sync">Синхронизация ЧС</option>
            <option value="blacklist_expire">Истечение ЧС</option>
            <option value="connect_help">Помощь при подключении</option>
            <option value="purge">Чистка логов</option>
            <option value="site_sync">Синхронизация сайта</option>
          </select>
          <button id="btn-job" class="ghost">Запустить сейчас</button>
          <div id="job-out"></div>
        </div>
      </section>

      <!-- Проверка операторов -->
      <section id="sec-netcheck" class="page hidden">
        <div class="card"><h2>Проверка операторов</h2><p class="sub">Доступность доменов у МТС, МегаФона, Билайна, Т2 и Ростелекома (Globalping, без ключа API).</p>
          <div class="btnrow"><button id="btn-netcheck-show" class="ghost">Показать настройки</button><button id="btn-netcheck">Запустить проверку</button></div>
          <div id="netcheck-out"></div>
        </div>
      </section>

      <!-- Сайт -->
      <section id="sec-site" class="page hidden">
        <div class="card"><h2>Сайт</h2><p class="sub">Деплой сайта и кабинета на сервер. Тексты применяются после деплоя.</p>
          <div class="btnrow"><button id="btn-site-show" class="ghost">Показать состояние</button><button id="btn-deploy">Деплой сайта</button><button id="btn-site-check" class="ghost">Проверить сайт</button></div>
          <div id="site-out"></div>
          <div id="site-check-out"></div>
        </div>
        <div class="card"><h2>Настройки сайта</h2><p class="sub">Домен, автообновление и доступ к серверу сайта — то же, что в ТГ. Пароль сервера меняется только владельцем (Mark) и нигде не показывается.</p>
          <label>Домен сайта<input id="ss-domain" placeholder="vpn.example.com"></label>
          <label><input id="ss-auto" type="checkbox"> автообновление сайта после обновления бота</label>
          <label>Хост сервера<input id="ss-host" placeholder="IP или домен сервера"></label>
          <label>SSH-порт<input id="ss-port" type="number" placeholder="22"></label>
          <label>Пользователь<input id="ss-user" placeholder="root"></label>
          <label>Пароль сервера (только Mark)<input id="ss-pass" type="password" placeholder="оставь пустым — не менять" autocomplete="new-password"></label>
          <div class="btnrow"><button id="btn-ss2-save" class="ghost">Сохранить настройки сайта</button><button id="btn-site-cert" class="ghost">Выпустить HTTPS-сертификат</button></div>
          <div id="ss2-out"></div>
        </div>
        <div class="card"><h2>Тексты сайта</h2>
          <input id="st-field" placeholder="поле, напр. hero_title">
          <textarea id="st-text" placeholder="новый текст"></textarea>
          <div class="btnrow"><button id="btn-st-save" class="ghost">Сохранить текст</button><button id="btn-st-show" class="ghost">Показать тексты</button></div>
          <div id="st-out"></div>
        </div>
        <div class="card"><h2>Удаление сайта</h2><p class="sub">Только Mark, с подтверждением. Действие необратимое.</p>
          <button id="btn-site-del" class="danger">Удалить сайт</button>
          <div id="site-del-out"></div>
        </div>
      </section>

      <!-- Бэкап -->
      <section id="sec-backup" class="page hidden">
        <div class="card"><h2>Бэкап и перенос</h2><p class="sub">Полный архив бота: база, все настройки, .env с токеном и все файлы assets, с контрольными суммами. Внутри — ключи от всего проекта, архив никому не пересылать. Восстановление — только Mark, с подтверждением, и только после свежего бэкапа: текущие данные будут заменены полностью, бот перезапустится.</p>
          <div id="backup-info" class="mut">Загрузка…</div>
          <div class="btnrow"><a id="btn-backup" href="/api/admin/backup/export"><button type="button" class="ghost">Скачать бэкап</button></a></div>
          <label>Файл архива (.zip)</label>
          <input id="bk-file" type="file" accept=".zip,application/zip">
          <div id="backup-preview"></div>
          <label><input id="bk-fresh" type="checkbox"> свежий бэкап сделан, я понимаю, что данные заменятся</label>
          <div class="btnrow"><button id="btn-backup-inspect" class="ghost">Проверить архив</button><button id="btn-backup-restore" class="danger">Восстановить из архива</button></div>
          <div id="backup-out"></div>
        </div>
        <div class="card"><h2>Обновление с GitHub</h2><p class="sub">Mark и Muse. Подтягивает main и перезапускает бота и сап-бота.</p>
          <button id="btn-git" class="danger">Обновиться с GitHub</button>
          <div id="git-out"></div>
        </div>
      </section>

      <!-- Техработы и функции -->
      <section id="sec-maintenance" class="page hidden">
        <div class="card"><h2>🛠 Техработы</h2><p class="sub">Когда техработы включены, бот закрыт для пользователей — админ работает как обычно. Оплаты, сроки подписок и мониторинг продолжают работать. Переключение — только Mark, с подтверждением.</p>
          <div id="mnt-status" class="mut">Загрузка…</div>
          <div id="mnt-readonly" class="mut hidden">Только Mark может менять техработы — у вас доступ только для чтения.</div>
          <div class="btnrow"><button id="btn-mnt-toggle">Включить техработы</button></div>
          <div id="mnt-toggle-out" class="mut"></div>
          <h3>Что увидят пользователи</h3>
          <div id="mnt-text-preview" class="mut"></div>
          <label>Текст сообщения (HTML: b, i, a href, code, blockquote; пусто или «-» — вернуть стандартный)</label>
          <textarea id="mnt-text" placeholder="текст на время техработ"></textarea>
          <div class="btnrow"><button id="btn-mnt-text-save" class="ghost">Сохранить текст</button><button id="btn-mnt-text-reset" class="ghost">Вернуть стандартный</button></div>
          <div id="mnt-text-out" class="mut"></div>
        </div>
        <div class="card"><h2>⚙️ Функции</h2><p class="sub">Отдельные функции можно выключить, не останавливая остальное: например, выдачу триалов или поддержку. Нажми на функцию, чтобы выключить или включить её.</p>
          <div id="mnt-features"></div>
          <div id="mnt-features-out" class="mut"></div>
        </div>
      </section>

      <!-- Консоль серверов -->
      <section id="sec-console" class="page hidden">
        <div class="card"><h2>🖥 Консоль серверов</h2><p class="sub">Веб-терминал: подключение к серверам проекта прямо из админки. Доступ — Mark и Muse. Одна активная сессия на аккаунт (новая вытесняет старую), простой — 10 минут, предел сессии — 60 минут. Все подключения пишутся в журнал действий.</p>
          <div id="console-status" class="mut">Загрузка…</div>
          <div id="console-servers" class="btnrow" style="margin-top:10px"></div>
          <div id="console-pubkey-box" class="hidden">
            <h3>Ключ консоли (только Mark)</h3>
            <p class="sub">Добавь этот публичный ключ в authorized_keys на каждом сервере — без него SSH не пустит. Ключ создаётся на главном сервере при первом открытии раздела и не меняется.</p>
            <textarea id="console-pubkey" readonly rows="3"></textarea>
            <div class="btnrow"><button id="btn-console-pubkey-copy" class="ghost">Скопировать ключ</button></div>
          </div>
        </div>
        <div class="card hidden" id="console-term-card"><h2 id="console-term-title">Терминал</h2>
          <div class="btnrow"><button id="btn-console-close" class="danger">Отключиться</button><span id="console-term-state" class="mut"></span></div>
          <div id="console-term"></div>
        </div>
      </section>

      <!-- Поддержка -->
      <section id="sec-support" class="page hidden">
        <div class="card"><h2>Открытые обращения</h2><p class="sub">Темы в группе поддержки. Ответ уходит юзеру тем же путём, что и ответ из группы.</p>
          <div class="btnrow"><button id="btn-support">Показать открытые темы</button></div>
          <div id="topics-out"></div>
        </div>
        <div class="card"><h2>Ответ пользователю</h2>
          <input id="sup-user" type="number" placeholder="tg_id юзера">
          <div class="btnrow"><button id="btn-sup-open" class="ghost">Открыть тему</button></div>
          <div id="sup-msgs"></div>
          <textarea id="sup-text" placeholder="ответ юзеру"></textarea>
          <label><input id="sup-close" type="checkbox"> закрыть обращение после ответа</label>
          <div class="btnrow"><button id="btn-sup-reply">Ответить</button><button id="btn-sup-close" class="ghost">Закрыть обращение</button></div>
          <span id="sup-msg" class="mut"></span>
        </div>
        <div class="card"><h2>Настройки поддержки</h2>
          <input id="ss-group" type="number" placeholder="ID группы поддержки (0 — очистить)">
          <input id="ss-log" type="number" placeholder="ID лог-канала (0 — очистить)">
          <button id="btn-ss-save" class="ghost">Сохранить настройки поддержки</button>
          <div id="ss-out"></div>
        </div>
        <div class="card"><h2>🤖 Бот поддержки</h2><p class="sub">Второй бот, который ведёт темы обращений. Токен берётся у @BotFather — после сохранения сервис бота перезапускается сам. Сам токен нигде не показывается.</p>
          <div id="sb-status" class="mut"></div>
          <div id="sb-stats" class="mut"></div>
          <div id="sb-form">
            <input id="sb-token" type="password" placeholder="токен бота из @BotFather" autocomplete="off">
            <div class="btnrow"><button id="btn-sb-save" class="ghost">Сохранить токен</button></div>
          </div>
          <div id="sb-out"></div>
        </div>
      </section>

      <!-- Настройки -->
      <section id="sec-settings" class="page hidden">
        <div class="card"><h2>Настройки</h2><p class="sub">Только безопасные настройки. Секреты здесь не показываются и не меняются.</p>
          <div id="settings"></div>
          <button id="btn-save">Сохранить настройки</button>
          <span id="save-msg" class="mut"></span>
        </div>
        <div id="muse-box" class="card hidden"><h2>Аккаунт Muse</h2><p class="sub">Только для входа через Telegram. Два способа создать аккаунт Muse — выберите один:</p>
          <h3>Способ 1 — одноразовая ссылка</h3>
          <p class="mut">Введите почту — аккаунт создастся отключённым, а одноразовая ссылка на установку пароля покажется один раз. Muse сам задаст пароль по этой ссылке.</p>
          <input id="muse-email" type="email" placeholder="почта для Muse">
          <button id="btn-muse">Создать аккаунт и ссылку</button>
          <div id="muse-out" class="mut"></div>
          <h3>Способ 2 — пароль задаёте вы</h3>
          <p class="mut">Введите почту и пароль сами — аккаунт сразу включится с этим паролем. Пароль передайте Muse отдельно, он нигде здесь не сохраняется в открытом виде.</p>
          <input id="md-email" type="email" placeholder="почта для Muse">
          <input id="md-pw" type="password" placeholder="пароль (8–128 символов)" autocomplete="new-password">
          <input id="md-pw2" type="password" placeholder="пароль ещё раз" autocomplete="new-password">
          <button id="btn-muse-direct">Создать аккаунт с паролем</button>
          <div id="md-out" class="mut"></div>
          <h3>Аккаунты</h3>
          <div class="btnrow"><button id="btn-muse-list" class="ghost">Показать аккаунты</button></div>
          <div id="muse-list-out"></div>
        </div>
        <div class="card"><h2>Помощники (только Mark)</h2><p class="sub">Помощники работают только в Telegram-боте, в вебе у них доступа нет.</p>
          <input id="helper-tg" placeholder="TG ID или @username">
          <select id="helper-perm-sel"><option value="users">Карточки людей</option><option value="dm">Писать людям</option><option value="support">Поддержка</option><option value="subs">Подписки — смотреть</option><option value="subs_edit">Подписки — менять</option><option value="payments">Оплаты</option><option value="promos">Промокоды</option><option value="blacklist">Чёрный список</option><option value="broadcast">Рассылки</option><option value="stats">Статистика</option></select>
          <div class="btnrow"><button id="btn-helper-add" class="ghost">Добавить</button><button id="btn-helper-perm" class="ghost">Переключить право</button><button id="btn-helper-del" class="danger">Удалить</button><button id="btn-helpers" class="ghost">Список</button></div>
          <div id="helpers-out"></div>
        </div>
        <div class="card"><h2>Веб-доступ</h2><p class="sub">Смена порта/bind вступает в силу только после рестарта бота. Выключить сам веб-API из веба нельзя — это убьёт и эту админку, делается только из ТГ.</p>
          <div class="btnrow"><button id="btn-webacc" class="ghost">Показать настройки</button></div>
          <input id="wa-port" type="number" placeholder="порт, напр. 8088">
          <input id="wa-bind" placeholder="bind: 127.0.0.1 или 0.0.0.0">
          <input id="wa-public" placeholder="публичный адрес кабинета, напр. https://vpn.example.com">
          <input id="wa-upstream" placeholder="upstream (куда проксируется API), напр. http://127.0.0.1:8088">
          <input id="wa-ts-site" placeholder="Turnstile site key (оставь пустым — не менять)">
          <input id="wa-ts-secret" type="password" placeholder="Turnstile secret key (оставь пустым — не менять)" autocomplete="new-password">
          <div class="btnrow"><button id="btn-wa-save" class="ghost">Сохранить веб-доступ</button><button id="btn-wa-check" class="ghost">Проверить кабинет</button></div>
          <div id="wa-out"></div>
          <div id="wa-check-out"></div>
        </div>
        <div class="card"><h2>Помощь при подключении</h2><p class="sub">Подсказки новичкам, которые не смогли подключиться.</p>
          <div class="btnrow"><button id="btn-ch-show" class="ghost">Показать настройки</button></div>
          <div id="ch-out"></div>
        </div>
      </section>
    </div>
  </main>
</div>
<script>
const API = "/api/admin";
const SECTION_TITLES = {overview:"Обзор", users:"Пользователи", subs:"Подписки", finance:"Финансы", payments:"Оплаты", broadcast:"Рассылка", retention:"Напоминания и возврат", promos:"Промокоды", tariffs:"Тарифы", panel:"Панель Remnawave", nodes:"Узлы", console:"Консоль серверов", logs:"Логи", sync:"Синхронизация", netcheck:"Проверка операторов", site:"Сайт", backup:"Бэкап", maintenance:"Техработы и функции", support:"Поддержка", settings:"Настройки"};
function $(id){ return document.getElementById(id); }
function esc(s){ return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function fmtNum(n){ if (n == null || n === "") return "—"; const v = Number(n); if (isNaN(v)) return esc(n); return v.toLocaleString("ru-RU"); }
function fmtMoney(n){ if (n == null || n === "") return "—"; return fmtNum(n) + " ₽"; }
function fmtDate(s){
  if (!s) return "—";
  const m = String(s).match(/(\\d{4})-(\\d{2})-(\\d{2})[T ](\\d{2}):(\\d{2})/);
  if (m) return m[3] + "." + m[2] + "." + m[1] + " " + m[4] + ":" + m[5];
  return esc(s);
}
function pill(v){
  const s = String(v == null ? "" : v).toLowerCase();
  if (["active","paid","ok","success","online","enabled","true","1"].indexOf(s) >= 0) return '<span class="pill ok">' + esc(v) + "</span>";
  if (["expired","refunded","failed","error","offline","disabled","false","0","blocked","banned"].indexOf(s) >= 0) return '<span class="pill bad">' + esc(v) + "</span>";
  if (["pending","trial","warning","frozen","paused"].indexOf(s) >= 0) return '<span class="pill warn">' + esc(v) + "</span>";
  if (s) return '<span class="pill info">' + esc(v) + "</span>";
  return "—";
}
function toast(msg, kind){
  const t = document.createElement("div");
  t.className = "toast" + (kind ? " " + kind : "");
  t.textContent = msg;
  $("toast").appendChild(t);
  setTimeout(function(){ t.remove(); }, 5000);
}
function show(id, on){ $(id).classList.toggle("hidden", !on); }
function showSection(name){
  document.querySelectorAll(".page").forEach(function(p){ p.classList.add("hidden"); });
  const sec = $("sec-" + name);
  if (sec) sec.classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach(function(b){ b.classList.toggle("active", b.dataset.nav === name); });
  $("sec-title").textContent = SECTION_TITLES[name] || name;
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  window.scrollTo(0, 0);
}
document.querySelectorAll(".nav-item").forEach(function(b){
  b.addEventListener("click", function(){ showSection(b.dataset.nav); });
});
document.querySelectorAll("[data-goto]").forEach(function(b){
  b.addEventListener("click", function(){ showSection(b.dataset.goto); });
});

/* --- Умный вывод: таблицы вместо JSON-дампов --- */
const DATE_KEYS = ["created_at","paid_at","expires_at","last_login_at","seen_at","date","updated_at","start","end","expires","until","paid_until"];
const MONEY_KEYS = ["amount","price","revenue","revenue_total","balance","total","price_rub"];
const NUM_KEYS = ["count","users","paid","total","tg_id","id","sub_id","payment_id","devices","hwid","limit","gb","traffic","days","period","uses","renamed","failed","skipped","online"];
function cellVal(k, v){
  if (v == null) return "—";
  if (DATE_KEYS.indexOf(k) >= 0) return '<span class="mono">' + fmtDate(v) + "</span>";
  if (MONEY_KEYS.indexOf(k) >= 0) return '<span class="num">' + fmtMoney(v) + "</span>";
  if (NUM_KEYS.indexOf(k) >= 0 && typeof v === "number") return '<span class="num">' + fmtNum(v) + "</span>";
  if (typeof v === "boolean") return pill(v ? "да" : "нет");
  if (k === "status" || k === "state" || k === "active" || k === "enabled" || k === "disabled" || k === "is_disabled") return pill(v);
  if (typeof v === "object") return '<span class="mono">' + esc(JSON.stringify(v)).slice(0, 120) + "</span>";
  const s = String(v);
  if (s.length > 60) return '<span title="' + esc(s) + '">' + esc(s.slice(0, 60)) + "…</span>";
  if (k === "id" || k === "uuid" || k === "tg_id" || k === "email" || k === "username") return '<span class="mono">' + esc(s) + "</span>";
  return esc(s);
}
function renderTable(el, rows){
  const host = $(el);
  if (!rows || !rows.length) { host.innerHTML = '<div class="empty"><span class="big">🔍</span>Ничего не найдено</div>'; return; }
  const cols = [];
  rows.forEach(function(r){ Object.keys(r).forEach(function(k){ if (cols.indexOf(k) < 0 && cols.length < 9) cols.push(k); }); });
  let h = '<div class="tblwrap"><table><thead><tr>' + cols.map(function(c){ return "<th>" + esc(c) + "</th>"; }).join("") + "</tr></thead><tbody>";
  rows.forEach(function(r){
    h += "<tr>" + cols.map(function(c){
      const v = r[c];
      const right = (typeof v === "number" || MONEY_KEYS.indexOf(c) >= 0) ? ' class="num"' : (String(v || "").length > 60 ? ' class="trunc"' : "");
      return "<td" + right + ">" + cellVal(c, v) + "</td>";
    }).join("") + "</tr>";
  });
  host.innerHTML = h + "</tbody></table></div>";
}
function renderKV(el, obj){
  const host = $(el);
  const keys = Object.keys(obj || {});
  if (!keys.length) { host.innerHTML = '<div class="empty"><span class="big">🔍</span>Нет данных</div>'; return; }
  host.innerHTML = '<dl class="kv">' + keys.map(function(k){
    return "<dt>" + esc(k) + "</dt><dd>" + cellVal(k, obj[k]) + "</dd>";
  }).join("") + "</dl>";
}
function renderOut(el, data){
  const host = $(el);
  if (data == null) { host.innerHTML = '<div class="empty"><span class="big">🔍</span>Нет данных</div>'; return; }
  if (data.error) { host.innerHTML = '<p class="err">Ошибка: ' + esc(data.error) + (data.details ? " — " + esc(data.details) : "") + "</p>"; return; }
  if (Array.isArray(data)) { renderTable(el, data); return; }
  const LIST_KEYS = ["users","payments","rows","entries","topics","logs","accounts","pairs","profiles","nodes","tariffs","promos","servers","helpers","messages","devices","squads","events","reviews"];
  for (let i = 0; i < LIST_KEYS.length; i++) {
    const k = LIST_KEYS[i];
    if (Array.isArray(data[k])) {
      if (data[k].length) { renderTable(el, data[k]); }
      else { host.innerHTML = '<div class="empty"><span class="big">🔍</span>Ничего не найдено</div>'; }
      return;
    }
  }
  if (data.subscription) { renderKV(el, data.subscription); return; }
  if (data.profile) { renderKV(el, data.profile); return; }
  if (data.stats) { renderKV(el, data.stats); return; }
  renderKV(el, data);
}
function csrf(){ const m = document.cookie.match(/(?:^|; )drebol_admin_csrf=([^;]*)/); return m ? decodeURIComponent(m[1]) : ""; }
async function api(path, opts){
  opts = opts || {};
  opts.headers = Object.assign({"Content-Type": "application/json"}, opts.headers || {});
  const r = await fetch(API + path, Object.assign({credentials: "same-origin"}, opts));
  let data = {}; try { data = await r.json(); } catch(e) {}
  return {status: r.status, data: data};
}
async function postConfirm(path, body){
  let r = await api(path, {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body || {})});
  if (r.data && r.data.need_confirm) {
    if (!confirm(r.data.summary || "Подтвердить действие?")) return {status: 0, data: {error: "cancelled"}};
    r = await api(path, {method: "POST", headers: {"X-CSRF-Token": csrf()},
      body: JSON.stringify(Object.assign({}, body || {}, {confirm_token: r.data.confirm_token}))});
  }
  return r;
}
async function downloadCsv(url){
  // Скачивание CSV-экспорта: сессия — в куках, как у api(); ошибка
  // (401/400/409 too_large) — тостом, а не битым файлом.
  let r;
  try { r = await fetch(API + url, {credentials: "same-origin"}); }
  catch(e) { toast("Ошибка загрузки", "err"); return; }
  if (r.status !== 200) {
    let d = {};
    try { d = await r.json(); } catch(e) {}
    if (d.error === "too_large") toast("Слишком много строк (" + (d.total || "?") + ") — сузьте фильтр", "err");
    else toast("Ошибка: " + (d.error || r.status), "err");
    return;
  }
  const blob = await r.blob();
  const a = document.createElement("a");
  const disp = r.headers.get("Content-Disposition") || "";
  const m = disp.match(/filename="([^"]+)"/);
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : "export.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(function(){ URL.revokeObjectURL(a.href); }, 5000);
  toast("Файл скачан", "ok");
}
async function postConfirmAny(path, method, body){
  let r = await api(path, {method: method, headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body || {})});
  if (r.data && r.data.need_confirm) {
    if (!confirm(r.data.summary || "Подтвердить действие?")) return {status: 0, data: {error: "cancelled"}};
    r = await api(path, {method: method, headers: {"X-CSRF-Token": csrf()},
      body: JSON.stringify(Object.assign({}, body || {}, {confirm_token: r.data.confirm_token}))});
  }
  return r;
}
function withSpin(btn, fn){
  return async function(){
    const old = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>Ждите…';
    try { await fn(); } finally { btn.disabled = false; btn.textContent = old; }
  };
}
async function refreshMe(){
  const r = await api("/me");
  if (r.status !== 200) { show("login-view", true); show("app-view", false); return false; }
  show("login-view", false); show("app-view", true);
  $("who").textContent = r.data.actor === "mark" ? "Вошли как Mark (Telegram)" : "Вошли как Muse · " + (r.data.email || "");
  show("muse-box", r.data.actor === "mark");
  return true;
}
/* --- Дашборд: графики рисуются руками, inline SVG, без внешних CDN --- */
function fmtDay(s){ const m = String(s || "").match(/(\\d{4})-(\\d{2})-(\\d{2})/); return m ? m[3] + "." + m[2] : esc(s); }
function fmtDays(n){ if (n == null) return "—"; n = Math.round(n / 86400); return n <= 0 ? "—" : fmtNum(n) + " дн."; }
function statusRu(s){
  const m = {active:"Активна", expired:"Истекла", frozen:"Заморожена", renewal:"Продление", trial:"Триал", blocked:"Заблокирована", banned:"Заблокирована"};
  return m[String(s || "").toLowerCase()] || String(s || "—");
}
function barChart(series, fmtVal){
  const W = 480, H = 190, PL = 46, PB = 22, PT = 8;
  const max = Math.max.apply(null, series.map(function(p){ return p.sum; }).concat([1]));
  const n = Math.max(series.length, 1), bw = (W - PL - 6) / n;
  let s = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" width="100%" role="img">';
  [0, 0.5, 1].forEach(function(f){
    const y = PT + (1 - f) * (H - PT - PB);
    s += '<line x1="' + PL + '" y1="' + y.toFixed(1) + '" x2="' + (W - 4) + '" y2="' + y.toFixed(1) + '" stroke="#26262B"/>';
    s += '<text x="' + (PL - 6) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end">' + fmtNum(Math.round(max * f)) + '</text>';
  });
  series.forEach(function(p, i){
    const h = p.sum > 0 ? Math.max(2, (p.sum / max) * (H - PT - PB)) : 0;
    const x = PL + i * bw + 1, y = H - PB - h;
    s += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + Math.max(1, bw - 2).toFixed(1) + '" height="' + h.toFixed(1) + '" rx="1.5" fill="#D8DBE0"><title>' + fmtDay(p.date) + ' · ' + esc(fmtVal(p.sum)) + '</title></rect>';
    if (i % 5 === 0) s += '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle">' + fmtDay(p.date) + '</text>';
  });
  return s + '</svg>';
}
function lineChart(series){
  const W = 480, H = 190, PL = 46, PB = 22, PT = 8;
  const max = Math.max.apply(null, series.map(function(p){ return p.count; }).concat([1]));
  const n = Math.max(series.length, 1), step = (W - PL - 6) / Math.max(n - 1, 1);
  const pt = series.map(function(p, i){
    return {x: PL + i * step, y: PT + (1 - p.count / max) * (H - PT - PB), d: p.date, v: p.count};
  });
  let s = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" width="100%" role="img">';
  [0, 0.5, 1].forEach(function(f){
    const y = PT + (1 - f) * (H - PT - PB);
    s += '<line x1="' + PL + '" y1="' + y.toFixed(1) + '" x2="' + (W - 4) + '" y2="' + y.toFixed(1) + '" stroke="#26262B"/>';
    s += '<text x="' + (PL - 6) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end">' + fmtNum(Math.round(max * f)) + '</text>';
  });
  const line = pt.map(function(p){ return p.x.toFixed(1) + "," + p.y.toFixed(1); }).join(" ");
  s += '<polygon points="' + PL + ',' + (H - PB) + ' ' + line + ' ' + pt[pt.length - 1].x.toFixed(1) + ',' + (H - PB) + '" fill="#C9CDD3" opacity="0.16"/>';
  s += '<polyline points="' + line + '" fill="none" stroke="#F2F3F5" stroke-width="2" stroke-linejoin="round"/>';
  pt.forEach(function(p, i){
    s += '<circle cx="' + p.x.toFixed(1) + '" cy="' + p.y.toFixed(1) + '" r="2.6" fill="#D8DBE0"><title>' + fmtDay(p.d) + ' · +' + p.v + '</title></circle>';
    if (i % 5 === 0) s += '<text x="' + p.x.toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle">' + fmtDay(p.d) + '</text>';
  });
  return s + '</svg>';
}
function donutChart(parts){
  const colors = ["#E8EAED", "#9BA1A9", "#4ADE80", "#F87171", "#FBBF24", "#565B63"];
  const total = parts.reduce(function(a, p){ return a + p.count; }, 0);
  if (!total) return '<div class="empty"><span class="big">🔍</span>Нет подписок</div>';
  const R = 62, C = 2 * Math.PI * R;
  let off = 0, rings = "";
  parts.forEach(function(p, i){
    const len = p.count / total * C;
    rings += '<circle cx="80" cy="80" r="' + R + '" fill="none" stroke="' + colors[i % colors.length] + '" stroke-width="26" stroke-dasharray="' + len.toFixed(1) + ' ' + (C - len).toFixed(1) + '" stroke-dashoffset="' + (-off).toFixed(1) + '" transform="rotate(-90 80 80)"><title>' + esc(p.label) + ' · ' + p.count + '</title></circle>';
    off += len;
  });
  const legend = parts.map(function(p, i){
    return '<div><span class="dot" style="background:' + colors[i % colors.length] + '"></span>' + esc(p.label) + ' — <b>' + fmtNum(p.count) + '</b></div>';
  }).join("");
  return '<div class="donut-wrap"><svg class="chart" viewBox="0 0 160 160" width="170" role="img">' + rings +
    '<text x="80" y="77" text-anchor="middle" style="font-size:20px;font-weight:700;fill:#f2f5f9">' + fmtNum(total) + '</text>' +
    '<text x="80" y="95" text-anchor="middle">подписок</text></svg><div class="legend">' + legend + '</div></div>';
}
function hbars(parts){
  const max = Math.max.apply(null, parts.map(function(p){ return p.count; }).concat([1]));
  if (!parts.length) return '<div class="empty"><span class="big">🔍</span>Нет данных</div>';
  return parts.map(function(p){
    const w = Math.max(p.count > 0 ? 3 : 0, Math.round(p.count / max * 100));
    return '<div class="hbar"><span class="hbar-lab">' + esc(p.label) + '</span><div class="hbar-track"><div class="hbar-fill" style="width:' + w + '%"></div></div><b>' + fmtNum(p.count) + '</b></div>';
  }).join("");
}
function gotoSub(id){
  if (!id) return;
  openSubEditor(parseInt(id, 10));
}
let paidPage = 0, paidTotalPages = 1;
async function loadPaid(page){
  const r = await api("/dashboard/paid?page=" + page);
  if (r.status !== 200) { $("paid-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  const items = r.data.items || [];
  paidPage = r.data.page || page; paidTotalPages = r.data.total_pages || 1;
  if (page === 1 && !items.length) { $("paid-table").innerHTML = '<div class="empty"><span class="big">🔍</span>Оплаченных подписок пока нет</div>'; show("btn-paid-more", false); return; }
  let h = page === 1 ? '<div class="tblwrap"><table><thead><tr><th>Пользователь</th><th>Срок</th><th>Сумма</th><th>Оплачено</th><th>Истекает</th><th>Статус</th></tr></thead><tbody id="paid-rows">' : "";
  items.forEach(function(it){
    const name = esc(it.name || "—") + (it.username ? ' <span class="mut">@' + esc(it.username) + '</span>' : "") + ' <span class="mono small">#' + it.tg_id + '</span>';
    h += '<tr data-sub="' + (it.sub_id || "") + '"><td>' + name + '</td><td>' + fmtDays(it.period_seconds) + '</td><td class="num">' + fmtMoney(it.amount) + '</td><td><span class="mono">' + fmtDate(it.paid_at) + '</span></td><td><span class="mono">' + fmtDate(it.expire_date) + '</span></td><td>' + subStatusPill(it.status) + '</td></tr>';
  });
  if (page === 1) {
    $("paid-table").innerHTML = h + "</tbody></table></div>";
  } else {
    const tb = $("paid-rows");
    if (tb) tb.insertAdjacentHTML("beforeend", h);
  }
  show("btn-paid-more", paidPage < paidTotalPages);
}
async function loadExpiring(){
  const r = await api("/dashboard/expiring");
  if (r.status !== 200) { $("expiring-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  const items = r.data.items || [];
  expiringCount = items.length;
  const kpi = $("kpi-expiring");
  if (kpi) kpi.textContent = fmtNum(items.length);
  if (!items.length) { $("expiring-out").innerHTML = '<div class="empty"><span class="big">✅</span>В ближайшие 3 дня ничего не истекает</div>'; return; }
  $("expiring-out").innerHTML = '<div class="tblwrap"><table><thead><tr><th>Пользователь</th><th>Подписка</th><th>Истекает</th><th>Статус</th><th></th></tr></thead><tbody>' +
    items.map(function(it){
      const name = esc(it.name || "—") + (it.username ? ' <span class="mut">@' + esc(it.username) + '</span>' : "") + ' <span class="mono small">#' + it.tg_id + '</span>';
      return '<tr><td>' + name + '</td><td><span class="mono">#' + it.sub_id + '</span></td><td><span class="mono">' + fmtDate(it.expire_date) + '</span></td><td>' + pill(statusRu(it.status)) + '</td><td><button class="ghost" data-open-sub="' + it.sub_id + '">Открыть</button></td></tr>';
    }).join("") + "</tbody></table></div>";
}
let chartDays = 30, dashStats = null, dashMoney = null, expiringCount = null;
function renderStats(){
  const s = dashStats || {};
  const m = dashMoney || {};
  const today = m.today || [0, 0];
  // Период графиков — тот же переключатель 7/30 дней, что в ТГ
  // (handle_payment_stats): неделя и месяц уже есть в payments_summary.
  const period = chartDays === 7 ? (m.week || [0, 0]) : (m.month || [0, 0]);
  const cells = [
    ["Выручка сегодня", fmtMoney(today[1]), "оплат: " + fmtNum(today[0])],
    ["Выручка за " + chartDays + " дней", fmtMoney(period[1]), "оплат: " + fmtNum(period[0])],
    ["Активных подписок", fmtNum(s.paid_active), "платящих: " + fmtNum(s.paying_active)],
    ["Новых сегодня", "+" + fmtNum(s.users_today || 0), "за неделю: +" + fmtNum(s.users_week || 0)],
    ["Пользователей", fmtNum(s.users_total), "платили: " + fmtNum(m.payers || 0)],
    ["Истекает ≤ 3 дней", '<span id="kpi-expiring">' + (expiringCount == null ? "…" : fmtNum(expiringCount)) + "</span>", ""]
  ];
  $("stats").innerHTML = cells.map(function(c){
    return '<div class="stat"><b>' + c[1] + '</b><span>' + c[0] + "</span>" + (c[2] ? "<small>" + c[2] + "</small>" : "") + "</div>";
  }).join("");
}
async function loadCharts(){
  const rs = await api("/dashboard/series?days=" + chartDays);
  if (rs.status !== 200) return;
  const d = rs.data || {};
  $("chart-revenue").innerHTML = barChart(d.revenue || [], function(v){ return fmtMoney(v); });
  $("chart-users").innerHTML = lineChart(d.users || []);
  $("chart-status").innerHTML = donutChart((d.by_status || []).map(function(x){ return {label: statusRu(x.status), count: x.count}; }));
  $("chart-term").innerHTML = hbars((d.by_term || []).map(function(x){ return {label: x.term_days ? fmtDays(x.term_days * 86400) : "Триал", count: x.count}; }));
  const t = $("chart-period-title");
  if (t) t.textContent = "Выручка и новые юзеры — " + chartDays + " дней";
}
$("chart-period").addEventListener("click", function(e){
  const b = e.target.closest("button[data-days]");
  if (!b) return;
  const d = parseInt(b.dataset.days, 10);
  if (d === chartDays) return;
  chartDays = d;
  document.querySelectorAll("#chart-period button[data-days]").forEach(function(x){ x.classList.toggle("active", x === b); });
  renderStats();
  loadCharts();
});
async function loadDashboard(){
  const r = await api("/dashboard");
  if (r.status !== 200) return;
  dashStats = r.data.stats || {};
  dashMoney = r.data.money || {};
  renderStats();
  const p = r.data.panel || {};
  $("panel-line").textContent = p.success ?
    ("Панель: клиентов " + fmtNum(p.total) + " (платных " + fmtNum(p.paid) + ")") :
    "Панель недоступна — сверка не выполнена";
  await loadCharts();
  paidPage = 0;
  loadPaid(1);
  loadExpiring();
}
$("paid-table").addEventListener("click", function(e){
  const tr = e.target.closest("tr[data-sub]");
  if (tr && tr.dataset.sub) gotoSub(tr.dataset.sub);
});
$("expiring-out").addEventListener("click", function(e){
  const b = e.target.closest("[data-open-sub]");
  if (b) gotoSub(b.dataset.openSub);
});
$("btn-paid-more").onclick = withSpin($("btn-paid-more"), async function(){ if (paidPage < paidTotalPages) await loadPaid(paidPage + 1); });
$("btn-quick-git").onclick = withSpin($("btn-quick-git"), async function(){
  const r = await postConfirm("/git-update", {});
  $("quick-upd-msg").textContent = r.status === 200 ? (r.data.up_to_date ? "Новых обновлений нет: бот уже на последней версии, перезапуск не нужен." : "Обновление запущено: бот перезапускается, страница обновится сама.") : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) toast(r.data.up_to_date ? "Бот уже обновлён" : "Обновление с GitHub запущено", "ok");
});
$("btn-quick-deploy").onclick = withSpin($("btn-quick-deploy"), async function(){
  const r = await postConfirm("/site/deploy", {});
  $("quick-upd-msg").textContent = r.status === 200 ? "Сайт развёрнут." : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) toast("Сайт развёрнут", "ok");
});
const EDITABLE = ["channel_url","force_subscribe","sub_link_domain","paid_trial_period","paid_preset_hwid","paid_preset_traffic","paid_preset_lte","referral_bonus","referral_invited_bonus","device_price","device_max_extra"];
const SETTINGS_LABELS = {channel_url: "Ссылка на канал", force_subscribe: "Обязательная подписка на канал", sub_link_domain: "Домен ссылки подписки", paid_trial_period: "Триал, дней", paid_preset_hwid: "Лимит устройств в подписке", paid_preset_traffic: "Лимит трафика, ГБ (0 — безлимит)", paid_preset_lte: "Лимит LTE, ГБ", referral_bonus: "Бонус пригласившему, дней", referral_invited_bonus: "Бонус приглашённому, дней", device_price: "Цена доп. устройства, ₽", device_max_extra: "Максимум доп. устройств"};
const SETTINGS_DAY_KEYS = ["paid_trial_period", "referral_bonus", "referral_invited_bonus"];
async function loadSettings(){
  const r = await api("/settings");
  if (r.status !== 200) return;
  const s = r.data.settings || {};
  $("settings").innerHTML = EDITABLE.map(function(k){
    if (k === "sub_link_domain") {
      const cur = s[k] === "key" ? "key" : "sub";
      return "<label>" + esc(SETTINGS_LABELS[k]) + '<select data-k="sub_link_domain">' +
        '<option value="sub"' + (cur === "sub" ? " selected" : "") + '>sub.drbl.tech (через CDN)</option>' +
        '<option value="key"' + (cur === "key" ? " selected" : "") + '>key.drbl.tech (напрямую)</option></select></label>';
    }
    let v = s[k];
    // В днях показываем только значения, кратные суткам: 12-часовой бонус
    // честнее оставить секундами, чем округлить до «1 день» и переписать.
    const isDay = SETTINGS_DAY_KEYS.indexOf(k) >= 0 && typeof v === "number" && v % 86400 === 0;
    if (isDay) v = Math.round(v / 86400);
    const type = typeof s[k] === "boolean" ? "checkbox" : (typeof s[k] === "number" ? "number" : "text");
    const val = type === "checkbox" ? (s[k] ? "checked" : "") : ('value="' + (v == null ? "" : String(v).replace(/"/g, "&quot;")) + '"');
    return "<label>" + esc(SETTINGS_LABELS[k] || k) + '<input data-k="' + k + '"' + (isDay ? ' data-days="1"' : "") + ' type="' + type + '" ' + val + "></label>";
  }).join("");
}
$("btn-login").onclick = withSpin($("btn-login"), async function(){
  const r = await api("/auth/password", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({email: $("email").value, password: $("pw").value})});
  if (r.status !== 200) { $("login-err").textContent = r.data.error === "too_many" ? "Слишком много попыток — подождите 15 минут" : "Неверная почта или пароль"; return; }
  $("login-err").textContent = "";
  toast("Вход выполнен", "ok");
  await refreshMe(); await loadDashboard(); await loadSettings();
});
$("btn-logout").onclick = async function(){
  await api("/logout", {method: "POST", headers: {"X-CSRF-Token": csrf()}});
  location.reload();
};
$("btn-save").onclick = withSpin($("btn-save"), async function(){
  const patch = {};
  document.querySelectorAll("#settings input").forEach(function(inp){
    let v = inp.type === "checkbox" ? inp.checked : (inp.type === "number" ? parseInt(inp.value || "0", 10) : inp.value);
    if (inp.dataset.days && typeof v === "number") v = v * 86400;
    patch[inp.dataset.k] = v;
  });
  document.querySelectorAll("#settings select").forEach(function(sel){
    patch[sel.dataset.k] = sel.value;
  });
  const r = await api("/settings", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({settings: patch})});
  $("save-msg").textContent = r.status === 200 ? "Сохранено" : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) toast("Настройки сохранены", "ok"); else toast("Ошибка сохранения", "err");
});
$("btn-muse").onclick = withSpin($("btn-muse"), async function(){
  const r = await api("/muse-account", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({email: $("muse-email").value})});
  $("muse-out").textContent = r.status === 200 ?
    ("Ссылка (показывается один раз): " + r.data.setup_url) : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) toast("Аккаунт создан, ссылка показана один раз", "ok");
});
$("btn-muse-direct").onclick = withSpin($("btn-muse-direct"), async function(){
  const r = await api("/muse-account/direct", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({email: $("md-email").value, password: $("md-pw").value, password_confirm: $("md-pw2").value})});
  if (r.status === 200) {
    $("md-out").textContent = "Аккаунт " + r.data.email + " создан и включён. Пароль передайте Muse отдельно.";
    $("md-pw").value = ""; $("md-pw2").value = "";
    toast("Аккаунт Muse создан с паролем", "ok");
  } else {
    const msg = {"bad_email":"Неверная почта", "bad_password":"Пароль — от 8 до 128 символов", "password_mismatch":"Пароли не совпадают", "email_taken":"Такая почта уже занята", "mark_only":"Только для Mark"}[r.data.error] || ("Ошибка: " + (r.data.error || r.status));
    $("md-out").textContent = msg;
  }
});
$("btn-muse-list").onclick = async function(){
  const r = await api("/muse-account");
  renderOut("muse-list-out", r.data);
};
$("btn-setup").onclick = async function(){
  const token = new URLSearchParams(location.search).get("token") || "";
  const r = await api("/auth/setup", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({token: token, password: $("pw2").value})});
  if (r.status !== 200) { $("setup-err").textContent = "Ссылка недействительна или пароль короче 8 символов"; return; }
  history.replaceState(null, "", location.pathname);
  await refreshMe(); await loadDashboard(); await loadSettings();
};
/* --- Пользователи --- */
/* --- Пользователи: список + карточка в редакторе --- */
function renderUsersTable(host, rows, dateLabel){
  if (!rows.length) { host.innerHTML = '<div class="empty"><span class="big">🔍</span>Никого не нашёл</div>'; return; }
  host.innerHTML = '<div class="tblwrap"><table><thead><tr><th>Имя</th><th>Username</th><th>TG ID</th><th>Подписка</th><th>' + dateLabel + '</th></tr></thead><tbody>' +
    rows.map(function(u){
      return '<tr data-tg="' + u.tg_id + '"><td>' + esc(u.name) + '</td><td class="mono">' + (u.username ? "@" + esc(u.username) : "—") + '</td><td class="mono">' + u.tg_id + '</td><td>' + (u.sub ? subStatusPill(u.sub) : "—") + '</td><td class="mono">' + fmtDate(u.date) + "</td></tr>";
    }).join("") + "</tbody></table></div>";
  host.querySelectorAll("tr[data-tg]").forEach(function(tr){
    tr.onclick = function(){ openUserEditor(parseInt(tr.dataset.tg, 10)); };
  });
}
let usersPage = 1, usersTotalPages = 1, usersLoaded = false, usersScope = "all";
const USERS_TABS = {all: ["📋", "Все"], active: ["🟢", "Активна"], expired: ["🔴", "Истекла"], none: ["⚪", "Без подписки"]};
async function loadUsers(page){
  usersPage = page;
  const q = $("q-user").value.trim();
  const sort = $("users-sort").value;
  $("users-out").innerHTML = '<div class="skel" style="height:18px;width:90%;margin-bottom:8px"></div><div class="skel" style="height:18px;width:70%;margin-bottom:8px"></div><div class="skel" style="height:120px"></div>';
  let r;
  try { r = await api("/users/list?page=" + page + "&scope=" + usersScope + "&sort=" + sort + (q ? "&q=" + encodeURIComponent(q) : "")); }
  catch(e) { $("users-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("users-out", r.data); return; }
  usersTotalPages = r.data.total_pages || 1;
  $("users-page-label").textContent = "Стр. " + r.data.page + " из " + usersTotalPages;
  const counts = r.data.counts || {};
  $("users-tabs").innerHTML = Object.keys(USERS_TABS).map(function(k){
    const c = counts[k];
    return '<button class="ghost' + (k === usersScope ? " active" : "") + '" data-users-tab="' + k + '">' + USERS_TABS[k][0] + " " + USERS_TABS[k][1] + (c == null ? "" : " · " + c) + "</button>";
  }).join("");
  const rows = (r.data.users || []).map(function(u){
    return {tg_id: u.tg_id, name: u.first_name || "", username: u.username || "", sub: u.sub_status || "", date: u.created_at || ""};
  });
  renderUsersTable($("users-out"), rows, "Создан");
}
$("btn-find").onclick = withSpin($("btn-find"), async function(){ loadUsers(1); });
$("btn-users-export").onclick = function(){
  const q = $("q-user").value.trim();
  downloadCsv("/users/export?scope=" + usersScope + "&sort=" + $("users-sort").value + (q ? "&q=" + encodeURIComponent(q) : ""));
};
$("q-user").addEventListener("keydown", function(e){ if (e.key === "Enter") loadUsers(1); });
$("users-sort").onchange = function(){ loadUsers(1); };
$("users-tabs").addEventListener("click", function(e){
  const b = e.target.closest("button[data-users-tab]");
  if (!b) return;
  usersScope = b.dataset.usersTab;
  loadUsers(1);
});
$("btn-users-prev").onclick = function(){ if (usersPage > 1) loadUsers(usersPage - 1); };
$("btn-users-next").onclick = function(){ if (usersPage < usersTotalPages) loadUsers(usersPage + 1); };
document.querySelector('[data-nav="users"]').addEventListener("click", function(){
  if (!usersLoaded) { usersLoaded = true; loadUsers(1); }
});
$("btn-recent").onclick = async function(){
  let r;
  try { r = await api("/users/recent"); }
  catch(e) { $("users-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("users-out", r.data); return; }
  $("users-page-label").textContent = "";
  const rows = (r.data.users || []).map(function(u){
    return {tg_id: u.tg_id, name: u.first_name || "", username: u.username || "", sub: "", date: u.last_seen || ""};
  });
  renderUsersTable($("users-out"), rows, "Последний визит");
};
async function openUserEditor(tgId){
  $("drawer-title").textContent = "Пользователь #" + tgId;
  $("drawer-sub").textContent = "Загрузка…";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:18px;width:50%;margin-bottom:10px"></div><div class="skel" style="height:120px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  let r;
  try { r = await api("/users/" + tgId); }
  catch(e) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить пользователя</p>'; return; }
  if (r.status !== 200) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить пользователя</p>'; return; }
  const d = r.data;
  $("drawer-sub").textContent = (d.first_name || "") + (d.username ? " @" + d.username : "");
  let h = '<dl class="kv">';
  h += kvRow("TG ID", '<span class="mono">' + d.tg_id + '</span>');
  if (d.subscription) {
    const s = d.subscription;
    h += kvRow("Подписка", subStatusPill(s.status) + ' · <span class="mono">' + fmtDate(s.expire_date) + '</span>');
    h += kvRow("Логин в панели", '<span class="mono">' + esc(s.email || "") + '</span>');
  } else h += kvRow("Подписка", "нет");
  if (d.referral) h += kvRow("Рефералка", "пригласил " + (d.referral.invited || 0) + " · вознаграждено " + (d.referral.rewarded || 0));
  if (d.payments_total) h += kvRow("Оплат (успешных)", d.payments_total.count + " на " + fmtMoney(d.payments_total.sum));
  if (d.blacklist) h += kvRow("Чёрный список", esc(d.blacklist.reason || d.blacklist.source || ""));
  h += '</dl>';
  if ((d.payments || []).length) {
    h += '<h3>Последние оплаты</h3><div class="tblwrap"><table><thead><tr><th>ID</th><th>Сумма</th><th>Статус</th><th>Дата</th></tr></thead><tbody>';
    d.payments.forEach(function(p){
      h += '<tr><td class="mono">' + p.id + '</td><td class="num">' + fmtMoney(p.amount) + '</td><td>' + statusPill(p.status, PAY_LABELS[p.status] || p.status) + '</td><td><span class="mono">' + fmtDate(p.date) + '</span></td></tr>';
    });
    h += '</tbody></table></div>';
  }
  h += '<h3>📜 Активность</h3><p class="sub">Что человек делал в боте — те же вкладки, что «📜 Его действия» в ТГ. Нажми на строку, чтобы открыть подробности записи.</p><div class="btnrow" id="user-act-tabs" style="flex-wrap:wrap"></div><div id="user-act-out"></div>'
     + '<div class="btnrow" style="margin-top:8px;align-items:center"><button id="btn-user-act-prev" class="ghost">← Назад</button><span class="mut" id="user-act-page-label"></span><button id="btn-user-act-next" class="ghost">Вперёд →</button></div>';
  $("drawer-body").innerHTML = h;
  $("drawer-foot").innerHTML = '<button class="ghost" id="ed-user-dm">Написать</button><button class="ghost" id="ed-user-gift">Подарить подписку</button><button class="ghost" id="ed-user-promo">🎁 Промокод</button>' + (d.subscription ? '<button class="ghost" id="ed-user-sub">Открыть подписку</button>' : "");
  $("ed-user-dm").onclick = function(){ closeDrawer(); showSection("users"); $("dm-id").value = tgId; $("dm-text").focus(); window.scrollTo(0, 0); };
  $("ed-user-gift").onclick = function(){ closeDrawer(); showSection("users"); $("gift-tg").value = tgId; $("gift-amount").focus(); window.scrollTo(0, 0); };
  $("ed-user-promo").onclick = function(){ closeDrawer(); showSection("promos"); loadGiveMeta(); $("give-target").value = tgId; $("give-target").focus(); window.scrollTo(0, 0); };
  const sb = $("ed-user-sub");
  if (sb) sb.onclick = function(){ openSubEditor(d.subscription.id); };
  loadUserActivity(tgId, "all", 1);
}
/* Активность одного пользователя — вкладки как USER_TABS в ТГ
   (handle_user_activity): всё / важное (только события ev:) /
   подписка (история подписок). */
let userActTg = 0, userActScope = "all", userActPage = 1, userActPages = 1;
const USER_ACT_TABS = [["all", "📜 Всё"], ["important", "⭐ Важное"], ["subs", "💳 Подписка"]];
async function loadUserActivity(tgId, scope, page){
  userActTg = tgId; userActScope = scope; userActPage = page;
  const out = $("user-act-out"); if (!out) return;
  out.innerHTML = '<p class="mut">Загрузка…</p>';
  let r;
  try { r = await api("/users/" + tgId + "/activity?scope=" + scope + "&page=" + page); }
  catch(e) { out.innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("user-act-out", r.data); return; }
  userActPages = r.data.pages || 1; userActPage = r.data.page || page;
  const tabs = $("user-act-tabs");
  if (tabs) tabs.innerHTML = USER_ACT_TABS.map(function(t){
    return '<button type="button" class="' + (t[0] === userActScope ? "" : "ghost") + '" data-user-act-tab="' + t[0] + '">' + t[1] + "</button>";
  }).join("");
  $("user-act-page-label").textContent = "Стр. " + userActPage + " из " + userActPages;
  show("btn-user-act-prev", userActPage > 1); show("btn-user-act-next", userActPage < userActPages);
  const rows = r.data.activity || [];
  if (!rows.length) { out.innerHTML = '<div class="empty">Записей пока нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Время (МСК)</th><th>Действие</th><th>Детали</th></tr></thead><tbody>';
  rows.forEach(function(it){
    const ep = userActScope === "subs" ? "history" : "activity";
    h += '<tr data-user-act-id="' + it.id + '" data-user-act-ep="' + ep + '"><td class="mono">' + fmtDate(it.time) + '</td><td title="' + esc(it.action || "") + '">' + esc(it.label || it.action || "") + '</td><td class="trunc" title="' + esc(it.details || "") + '">' + esc(it.details || "") + "</td></tr>";
  });
  out.innerHTML = h + "</tbody></table></div>";
}
$("btn-dm").onclick = withSpin($("btn-dm"), async function(){
  const r = await api("/users/" + $("dm-id").value + "/dm",
    {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({text: $("dm-text").value})});
  $("dm-msg").textContent = r.status === 200 ? "Отправлено" : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) toast("Сообщение отправлено", "ok");
});
$("btn-gift").onclick = withSpin($("btn-gift"), async function(){
  const body = {amount: parseInt($("gift-amount").value || "0", 10), period_seconds: parseInt($("gift-seconds").value || "0", 10)};
  const promo = $("gift-promo").value.trim();
  if (promo) body.promo_code = promo;
  const r = await api("/users/" + $("gift-tg").value + "/gift",
    {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
  renderOut("gift-out", r.data);
  if (r.status === 200) toast("Подписка подарена", "ok");
});
$("btn-blacklist").onclick = async function(){
  const r = await api("/blacklist");
  if (r.status !== 200) { renderOut("bl-out", r.data); return; }
  const rows = r.data.entries || [];
  if (!rows.length) { $("bl-out").innerHTML = '<div class="empty">Чёрный список пуст</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Имя</th><th>Username</th><th>TG ID</th><th>Причина</th></tr></thead><tbody>';
  rows.forEach(function(e){
    h += '<tr data-tg="' + e.tg_id + '"><td>' + esc(e.first_name || "") + '</td><td class="mono">' + (e.username ? "@" + esc(e.username) : "—") + '</td><td class="mono">' + e.tg_id + '</td><td>' + esc(e.reason || "") + '</td></tr>';
  });
  h += '</tbody></table></div>';
  $("bl-out").innerHTML = h;
  $("bl-out").querySelectorAll("tr[data-tg]").forEach(function(tr){
    tr.onclick = function(){ $("bl-tg").value = tr.dataset.tg; };
  });
};
$("btn-bl-add").onclick = withSpin($("btn-bl-add"), async function(){
  const r = await api("/blacklist/add", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({tg_id: parseInt($("bl-tg").value || "0", 10), reason: $("bl-reason").value, term: $("bl-term").value || undefined})});
  renderOut("bl-out", r.data);
});
$("btn-bl-stop").onclick = async function(){
  const r = await postConfirm("/blacklist/" + $("bl-tg").value + "/stop", {});
  renderOut("bl-out", r.data);
};
$("btn-bl-readd").onclick = async function(){
  const r = await api("/blacklist/" + $("bl-tg").value + "/readd",
    {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({})});
  renderOut("bl-out", r.data);
};
let fraudStatus = "new", fraudIsMark = false;
const FRAUD_TABS = [["new", "🆕 Новые"], ["blocked", "⛔ Блок"], ["ignored", "🙈 Не фрод"], ["all", "📚 Все"]];
const FRAUD_STATUS_LABEL = {new: "🆕 не разобрано", ignored: "🙈 не фрод", blocked: "⛔ блокировка"};
async function loadFraud(){
  const r = await api("/fraud?status=" + fraudStatus);
  if (r.status !== 200) { renderOut("fraud-out", r.data); return; }
  const d = r.data, st = d.stats || {};
  fraudIsMark = !!d.is_mark;
  let h = '<dl class="kv">';
  h += kvRow("Слежка", d.enabled ? "🟢 включена" : "🔴 выключена");
  h += kvRow("Устройств запомнено", String(st.devices != null ? st.devices : "—"));
  h += kvRow("Адресов запомнено", String(st.ips != null ? st.ips : "—"));
  h += kvRow("Находок всего", String(st.pairs != null ? st.pairs : "—"));
  h += kvRow("Не разобрано", String(st.new != null ? st.new : "—"));
  h += kvRow("Похожи на абуз (50+ баллов)", String(st.abuse != null ? st.abuse : "—"));
  h += kvRow("Закончились блокировкой", String(st.blocked != null ? st.blocked : "—"));
  h += kvRow("Отмечено «не фрод»", String(st.ignored != null ? st.ignored : "—"));
  if (st.clusters) h += kvRow("Устройств на трёх и более аккаунтах", String(st.clusters));
  h += '</dl>';
  $("fraud-stats").innerHTML = h;
  show("btn-fraud-toggle", fraudIsMark);
  show("btn-fraud-ip", fraudIsMark);
  $("btn-fraud-toggle").textContent = d.enabled ? "🔴 Выключить слежку" : "🟢 Включить слежку";
  $("btn-fraud-ip").textContent = "🌐 Адрес как улика: " + (d.use_ip ? "да" : "нет");
  $("fraud-tabs").innerHTML = FRAUD_TABS.map(function(t){
    return '<button type="button" class="' + (t[0] === fraudStatus ? "" : "ghost") + '" data-fraud-tab="' + t[0] + '">' + (t[0] === fraudStatus ? "• " : "") + t[1] + "</button>";
  }).join("");
  $("fraud-tabs").querySelectorAll("[data-fraud-tab]").forEach(function(b){
    b.onclick = function(){ fraudStatus = b.dataset.fraudTab; loadFraud(); };
  });
  const rows = d.pairs || [];
  if (!rows.length) { $("fraud-out").innerHTML = '<div class="empty">Подозрительных пар нет</div>'; return; }
  let t = '<div class="tblwrap"><table><thead><tr><th>Аккаунт A</th><th>Аккаунт B</th><th>Совпадение</th><th>Баллы</th><th>Статус</th></tr></thead><tbody>';
  rows.forEach(function(p){
    t += '<tr data-a="' + p.tg_a + '" data-b="' + p.tg_b + '"><td class="mono">' + p.tg_a + '</td><td class="mono">' + p.tg_b + '</td><td>' + esc(p.kind + ": " + p.value) + '</td><td><b>' + (p.score || 0) + '</b></td><td>' + esc(FRAUD_STATUS_LABEL[p.status] || p.status) + '</td></tr>';
  });
  t += '</tbody></table></div>';
  $("fraud-out").innerHTML = t;
  $("fraud-out").querySelectorAll("tr[data-a]").forEach(function(tr){
    tr.onclick = function(){ openFraudPair(parseInt(tr.dataset.a, 10), parseInt(tr.dataset.b, 10)); };
  });
}
$("btn-fraud").onclick = async function(){ loadFraud(); };
$("btn-fraud-scan").onclick = withSpin($("btn-fraud-scan"), async function(){
  const r = await postConfirm("/fraud/scan", {});
  renderOut("fraud-out", r.data);
  if (r.status === 200) loadFraud();
});
$("btn-fraud-toggle").onclick = withSpin($("btn-fraud-toggle"), async function(){
  const r = await postConfirm("/fraud/toggle", {});
  if (r.status === 200) { toast("Слежка " + (r.data.enabled ? "включена" : "выключена"), "ok"); loadFraud(); }
  else renderOut("fraud-out", r.data);
});
$("btn-fraud-ip").onclick = withSpin($("btn-fraud-ip"), async function(){
  const r = await postConfirm("/fraud/ip-toggle", {});
  if (r.status === 200) { toast("Адрес как улика: " + (r.data.enabled ? "да" : "нет"), "ok"); loadFraud(); }
  else renderOut("fraud-out", r.data);
});
let fraudPairA = 0, fraudPairB = 0;
async function openFraudPair(a, b){
  fraudPairA = a; fraudPairB = b;
  $("drawer-title").textContent = "🕵 Находка";
  $("drawer-sub").textContent = "Загрузка…";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:120px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  let r;
  try { r = await api("/fraud/pair?a=" + a + "&b=" + b); }
  catch(e) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить находку</p>'; return; }
  if (r.status !== 200) { $("drawer-body").innerHTML = '<p class="err">Находка не найдена</p>'; return; }
  const d = r.data, p = d.pair;
  $("drawer-sub").textContent = p.verdict + " · " + p.score + " баллов · " + (FRAUD_STATUS_LABEL[p.status] || p.status) + " · " + fmtDate(p.created_at);
  let h = "";
  d.who.forEach(function(w, i){
    h += '<h3>' + (i === 0 ? "👤 Первый" : "👤 Второй") + '</h3><dl class="kv">';
    h += kvRow("Имя", esc(w.name || "—") + (w.username ? " · @" + esc(w.username) : "") + ' · <span class="mono">' + w.tg_id + '</span>');
    h += kvRow("Подписка", w.sub ? (esc(w.sub.kind) + ", " + esc(w.sub.status) + (w.sub.until ? ", до " + esc(w.sub.until) : "")) : "нет");
    h += kvRow("Отпечатки", "устройств: " + w.hwid + " · адресов: " + w.ip);
    h += '</dl>';
  });
  h += '<h3>Улики</h3><dl class="kv">';
  d.evidence.forEach(function(e){
    h += kvRow(e.label, "+" + e.weight + ' · <span class="mono">' + esc(e.value) + '</span>');
  });
  h += '</dl>';
  const cl = d.cluster || {};
  if (cl.first_seen) h += '<dl class="kv">' + kvRow("Впервые", '<span class="mono">' + fmtDate(cl.first_seen) + '</span>') + kvRow("Последний раз", '<span class="mono">' + fmtDate(cl.last_seen) + '</span>') + '</dl>';
  if (cl.others_count) {
    h += '<p class="mut">👥 Тот же отпечаток ещё у <b>' + cl.others_count + '</b>: ' + cl.others.map(function(o){ return esc(o.name || ("#" + o.tg_id)) + (o.username ? " @" + esc(o.username) : ""); }).join(", ") + '</p>';
  }
  if (d.weak_only) h += '<p class="mut">⚠️ Сильной улики (устройства) нет: адрес и прочее по отдельности слабы, смотри на сумму.</p>';
  $("drawer-body").innerHTML = h;
  let foot = '<button class="ghost" id="fp-recheck">🔄 Перепроверить пару</button>';
  if (p.status !== "ignored") foot += '<button class="ghost" id="fp-ignore">🙈 Не фрод</button>';
  d.who.forEach(function(w, i){
    foot += '<button class="ghost" id="fp-user-' + i + '">👤 ' + (i === 0 ? "Первый" : "Второй") + '</button>';
    if (w.can_stop) foot += '<button class="danger" id="fp-stop-' + i + '">🚫 Закрыть триал ' + (i === 0 ? "первому" : "второму") + '</button>';
    foot += '<button class="ghost" id="fp-bl-' + i + '">⛔ В ЧС ' + (i === 0 ? "первого" : "второго") + '</button>';
  });
  $("drawer-foot").innerHTML = foot;
  $("fp-recheck").onclick = withSpin($("fp-recheck"), async function(){
    const rr = await api("/fraud/" + fraudPairA + "/" + fraudPairB + "/recheck", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({})});
    if (rr.status === 200) { toast("Перепроверил: " + rr.data.score + " баллов — " + rr.data.verdict, "ok"); openFraudPair(fraudPairA, fraudPairB); loadFraud(); }
    else toast("Ошибка: " + (rr.data.error || rr.status), "err");
  });
  const ign = $("fp-ignore");
  if (ign) ign.onclick = withSpin(ign, async function(){
    const rr = await api("/fraud/" + fraudPairA + "/" + fraudPairB + "/ignore", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({})});
    if (rr.status === 200) { toast("Больше про эту пару не напомню", "ok"); openFraudPair(fraudPairA, fraudPairB); loadFraud(); }
    else toast("Ошибка: " + (rr.data.error || rr.status), "err");
  });
  d.who.forEach(function(w, i){
    $("fp-user-" + i).onclick = function(){ openUserEditor(w.tg_id); };
    const stopBtn = $("fp-stop-" + i);
    if (stopBtn) stopBtn.onclick = withSpin(stopBtn, async function(){
      const rr = await postConfirm("/fraud/" + w.tg_id + "/stop", {other_tg: (i === 0 ? fraudPairB : fraudPairA)});
      if (rr.status === 200) { toast("Триал закрыт" + (rr.data.trouble ? " · " + rr.data.trouble : ""), "ok"); openFraudPair(fraudPairA, fraudPairB); loadFraud(); }
      else toast("Ошибка: " + (rr.data.error || rr.status), "err");
    });
    $("fp-bl-" + i).onclick = withSpin($("fp-bl-" + i), async function(){
      const rr = await api("/blacklist/add", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({tg_id: w.tg_id, reason: "Повторный триал (антифрод)"})});
      if (rr.status === 200) toast("Внесён в чёрный список", "ok");
      else toast("Ошибка: " + (rr.data.error || rr.status), "err");
    });
  });
}

/* --- Подписки: список + редактор --- */
let subsPage = 1, subsTotalPages = 1, subsLoaded = false, subsCurrentId = null, subsCurrentKind = "paid", subsScope = "all";
const SUBS_TABS = {all: ["📋", "Все"], active: ["🟢", "Активные"], soon: ["⏳", "Скоро кончатся"], expired: ["🔴", "Истёкшие"], off: ["⏸", "Выключены в панели"], trial: ["🆓", "Пробные"], paying: ["💳", "Платящие"]};
function statusPill(code, label){
  const s = String(code == null ? "" : code).toLowerCase();
  const cls = ["active","paid","ok","success","online","enabled","true","1"].indexOf(s) >= 0 ? "ok"
    : ["expired","refunded","failed","error","offline","disabled","false","0","blocked","banned"].indexOf(s) >= 0 ? "bad"
    : ["pending","trial","warning","frozen","paused","canceled","cancelled"].indexOf(s) >= 0 ? "warn" : "info";
  return '<span class="pill ' + cls + '">' + esc(label == null ? code : label) + "</span>";
}
function subStatusPill(s){ return statusPill(s, s === "active" ? "Активна" : s === "expired" ? "Истекла" : s === "frozen" ? "Заморожена" : (s || "—")); }
async function loadSubs(page){
  const q = encodeURIComponent($("subs-q").value.trim());
  const sort = $("subs-sort").value;
  let r;
  try { r = await api("/subs?page=" + page + "&scope=" + subsScope + "&sort=" + sort + (q ? "&q=" + q : "")); }
  catch(e) { $("subs-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { $("subs-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  const counts = r.data.counts || {};
  $("subs-tabs").innerHTML = Object.keys(SUBS_TABS).map(function(k){
    const c = counts[k];
    return '<button class="ghost' + (k === subsScope ? " active" : "") + '" data-subs-tab="' + k + '">' + SUBS_TABS[k][0] + " " + SUBS_TABS[k][1] + (c == null ? "" : " · " + c) + "</button>";
  }).join("");
  $("subs-panel-warn").textContent = r.data.panel_ok === false ? "⚠️ Панель не ответила — не знаю, кто выключен, вкладка «Выключены в панели» пуста." : "";
  const items = r.data.subs || [];
  subsPage = r.data.page || page; subsTotalPages = r.data.total_pages || 1;
  $("subs-page-label").textContent = "Страница " + subsPage + " из " + subsTotalPages;
  show("btn-subs-prev", subsPage > 1); show("btn-subs-next", subsPage < subsTotalPages);
  if (!items.length) { $("subs-table").innerHTML = '<div class="empty"><span class="big">🔍</span>Подписок не найдено</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Пользователь</th><th>Логин в панели</th><th>Статус</th><th>Истекает</th><th>Трафик (лимит)</th><th>Устройства (лимит)</th></tr></thead><tbody>';
  items.forEach(function(it){
    const name = esc(it.first_name || "—") + (it.username ? ' <span class="mut">@' + esc(it.username) + '</span>' : "") + ' <span class="mono small">#' + it.tg_id + '</span>';
    const traf = it.total_gb > 0 ? "до " + it.total_gb + " ГБ" : "безлимит";
    const devs = (it.limit_hwid || 0) + (it.extra_devices || 0);
    const mark = it.mark ? esc(it.mark) + " " : "";
    h += '<tr data-sub-id="' + it.id + '"><td>' + name + '</td><td class="trunc"><span class="mono">' + esc(it.email || "") + '</span></td><td>' + mark + subStatusPill(it.status) + '</td><td><span class="mono">' + fmtDate(it.expire_date) + '</span></td><td class="num">' + traf + '</td><td class="num">до ' + devs + '</td></tr>';
  });
  $("subs-table").innerHTML = h + '</tbody></table></div>';
}
$("btn-subs-search").onclick = function(){ loadSubs(1); };
$("btn-subs-refresh").onclick = function(){ loadSubs(subsPage); };
$("btn-subs-export").onclick = function(){
  const q = encodeURIComponent($("subs-q").value.trim());
  downloadCsv("/subs/export?scope=" + subsScope + "&sort=" + $("subs-sort").value + (q ? "&q=" + q : ""));
};
$("subs-q").addEventListener("keydown", function(e){ if (e.key === "Enter") loadSubs(1); });
$("subs-sort").onchange = function(){ loadSubs(1); };
$("subs-tabs").addEventListener("click", function(e){
  const b = e.target.closest("button[data-subs-tab]");
  if (!b) return;
  subsScope = b.dataset.subsTab;
  loadSubs(1);
});
$("btn-subs-prev").onclick = function(){ if (subsPage > 1) loadSubs(subsPage - 1); };
$("btn-subs-next").onclick = function(){ if (subsPage < subsTotalPages) loadSubs(subsPage + 1); };
$("subs-table").addEventListener("click", function(e){
  const tr = e.target.closest("tr[data-sub-id]");
  if (tr) openSubEditor(parseInt(tr.dataset.subId, 10));
});
document.querySelector('[data-nav="subs"]').addEventListener("click", function(){
  if (!subsLoaded) { subsLoaded = true; loadSubs(1); loadRequests(); loadAdminSubs(1); loadBulkScopes(); }
});

/* --- Админские подписки: список с вкладками --- */
let asubPage = 1, asubTotalPages = 1, asubScope = "all";
const ASUB_TABS = {all: ["📋", "Все"], active: ["🟢", "Активные"], soon: ["⏳", "Скоро кончатся"], expired: ["🔴", "Истёкшие"]};
async function loadAdminSubs(page){
  const q = encodeURIComponent($("asub-q").value.trim());
  const sort = $("asub-sort").value;
  let r;
  try { r = await api("/admin-subs?page=" + page + "&scope=" + asubScope + "&sort=" + sort + (q ? "&q=" + q : "")); }
  catch(e) { $("asub-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { $("asub-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  const counts = r.data.counts || {};
  $("asub-tabs").innerHTML = Object.keys(ASUB_TABS).map(function(k){
    const c = counts[k];
    return '<button class="ghost' + (k === asubScope ? " active" : "") + '" data-asub-tab="' + k + '">' + ASUB_TABS[k][0] + " " + ASUB_TABS[k][1] + (c == null ? "" : " · " + c) + "</button>";
  }).join("");
  const items = r.data.subs || [];
  asubPage = r.data.page || page; asubTotalPages = r.data.pages || 1;
  $("asub-page-label").textContent = "Страница " + asubPage + " из " + asubTotalPages;
  show("btn-asub-prev", asubPage > 1); show("btn-asub-next", asubPage < asubTotalPages);
  if (!items.length) { $("asub-table").innerHTML = '<div class="empty"><span class="big">🔍</span>Админских подписок не найдено</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Пользователь</th><th>Логин в панели</th><th>Истекает</th><th>Трафик (лимит)</th><th>Создана</th></tr></thead><tbody>';
  items.forEach(function(it){
    const name = esc(it.first_name || "—") + (it.username ? ' <span class="mut">@' + esc(it.username) + '</span>' : "") + (it.tg_id ? ' <span class="mono small">#' + it.tg_id + '</span>' : "");
    const traf = it.total_gb > 0 ? "до " + it.total_gb + " ГБ" : "безлимит";
    h += '<tr data-asub-id="' + it.id + '"><td>' + name + '</td><td class="trunc"><span class="mono">' + esc(it.email || "") + '</span></td><td><span class="mono">' + fmtDate(it.expire_date) + '</span></td><td class="num">' + traf + '</td><td><span class="mono">' + fmtDate(it.created_at) + '</span></td></tr>';
  });
  $("asub-table").innerHTML = h + '</tbody></table></div>';
}
$("btn-asub-search").onclick = function(){ loadAdminSubs(1); };
$("btn-asub-refresh").onclick = function(){ loadAdminSubs(asubPage); };
$("asub-q").addEventListener("keydown", function(e){ if (e.key === "Enter") loadAdminSubs(1); });
$("asub-sort").onchange = function(){ loadAdminSubs(1); };
$("btn-asub-prev").onclick = function(){ if (asubPage > 1) loadAdminSubs(asubPage - 1); };
$("btn-asub-next").onclick = function(){ if (asubPage < asubTotalPages) loadAdminSubs(asubPage + 1); };
$("asub-tabs").addEventListener("click", function(e){
  const b = e.target.closest("button[data-asub-tab]");
  if (!b) return;
  asubScope = b.dataset.asubTab;
  loadAdminSubs(1);
});
$("asub-table").addEventListener("click", function(e){
  const tr = e.target.closest("tr[data-asub-id]");
  if (tr) openSubEditor(parseInt(tr.dataset.asubId, 10), "admin");
});

/* --- Заявки на подписку --- */
async function loadRequests(){
  let r;
  try { r = await api("/subs/requests"); }
  catch(e) { $("requests-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("requests-table", r.data); return; }
  const items = r.data.requests || [];
  if (!items.length) { $("requests-table").innerHTML = '<div class="empty"><span class="big">📥</span>Ждущих заявок нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Человек</th><th>TG ID</th><th>Заявка</th><th></th></tr></thead><tbody>';
  items.forEach(function(it){
    const name = esc(it.first_name || "—") + (it.username ? ' <span class="mut">@' + esc(it.username) + '</span>' : "");
    h += '<tr><td>' + name + '</td><td class="mono">' + it.tg_id + '</td><td class="mono">' + fmtDate(it.created_at) + '</td>'
      + '<td style="white-space:nowrap"><button class="ghost" data-req-act="approve" data-req-tg="' + it.tg_id + '">✅ Одобрить</button> <button class="ghost" data-req-act="reject" data-req-tg="' + it.tg_id + '">❌ Отклонить</button></td></tr>';
  });
  $("requests-table").innerHTML = h + '</tbody></table></div>';
}
$("btn-requests").onclick = loadRequests;
$("requests-table").addEventListener("click", async function(e){
  const btn = e.target.closest("button[data-req-act]");
  if (!btn || btn.disabled) return;
  const tgId = btn.dataset.reqTg, act = btn.dataset.reqAct;
  btn.disabled = true;
  try {
    const r = await postConfirm("/subs/requests/" + tgId + "/" + act, {});
    if (r.status === 0) return; // отмена подтверждения
    if (r.status !== 200) { renderOut("requests-out", r.data); return; }
    if (r.data.already_has_sub) { toast("У человека уже есть подписка", "warn"); }
    else if (act === "approve") { toast("Триал выдан: " + (r.data.subscription ? r.data.subscription.email : tgId), "ok"); }
    else { toast("Заявка отклонена", "ok"); }
    if (r.data.notified === false) { $("requests-out").innerHTML = '<p class="err">Уведомление в Telegram не дошло — проверь, что бот запущен и человек его не заблокировал.</p>'; }
    else { $("requests-out").innerHTML = ""; }
    if (r.data.referral_bonus_error) { $("requests-out").innerHTML = '<p class="err">Реферальный бонус не начислился: ' + esc(r.data.referral_bonus_error) + '</p>'; }
    loadRequests();
    if (subsLoaded) loadSubs(subsPage);
  } finally { btn.disabled = false; }
});

/* --- Редактор записи (drawer) --- */
function openDrawer(){ $("drawer-overlay").classList.add("open"); $("drawer").classList.add("open"); $("drawer").setAttribute("aria-hidden", "false"); }
function closeDrawer(){ $("drawer-overlay").classList.remove("open"); $("drawer").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true"); }
$("drawer-close").onclick = closeDrawer;
$("drawer-overlay").onclick = closeDrawer;
document.addEventListener("keydown", function(e){ if (e.key === "Escape") closeDrawer(); });
function kvRow(k, v){ return "<dt>" + esc(k) + "</dt><dd>" + v + "</dd>"; }
async function openSubEditor(id, kind){
  subsCurrentId = id;
  subsCurrentKind = kind || "paid";
  $("drawer-title").textContent = (subsCurrentKind === "admin" ? "Админская подписка #" : "Подписка #") + id;
  $("drawer-sub").textContent = "Загрузка…";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:18px;width:50%;margin-bottom:10px"></div><div class="skel" style="height:120px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  let r;
  try { r = await api((subsCurrentKind === "admin" ? "/admin-subs/" : "/subs/") + id); }
  catch(e) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить подписку</p>'; return; }
  if (r.status !== 200) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить подписку</p>'; return; }
  renderSubEditor(r.data);
}
function fmtBytesAdmin(n){
  n = Number(n || 0);
  if (n <= 0) return "0 Б";
  const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i === 0 ? String(Math.round(n)) : n.toFixed(n >= 100 ? 0 : 1)) + " " + u[i];
}
function renderSubEditor(data){
  const s = data.subscription || {};
  const p = data.panel || {};
  const usr = data.user || {};
  const ref = data.referrer || null;
  const pays = data.payments || {items: [], count: 0, sum: 0};
  $("drawer-title").textContent = (subsCurrentKind === "admin" ? "Админская подписка #" : "Подписка #") + s.id;
  $("drawer-sub").textContent = ((usr.first_name || "") + (usr.username ? " @" + usr.username : "") + " · tg #" + s.tg_id).trim();
  const usedBytes = Number(p.up || 0) + Number(p.down || 0);
  const limitBytes = Number(s.total_gb || 0) * 1073741824;
  let leftTxt = "";
  if (s.expire_date) {
    const dl = Math.ceil((new Date(s.expire_date).getTime() - Date.now()) / 86400000);
    leftTxt = dl > 0 ? " (ещё " + dl + " дн.)" : " (истекла)";
  }
  let h = '<dl class="kv">';
  h += kvRow("Логин в панели", '<span class="mono">' + esc(s.email || "") + '</span>');
  h += kvRow("Владелец", esc((usr.first_name || "—") + (usr.username ? " @" + usr.username : "")) + ' · <span class="mono">tg ' + s.tg_id + '</span>');
  if (ref) h += kvRow("Пригласил", esc(ref.first_name || "") + ' · <span class="mono">tg ' + ref.tg_id + '</span>');
  h += kvRow("UUID", '<span class="mono">' + esc(s.uuid || "") + '</span>');
  h += kvRow("Sub ID", '<span class="mono">' + esc(s.sub_id || "") + '</span>');
  h += kvRow("Создана", '<span class="mono">' + esc(String(s.created_at || "").slice(0, 16)) + '</span>');
  h += kvRow("Истекает", '<span class="mono">' + fmtDate(s.expire_date) + '</span>' + leftTxt);
  h += kvRow("Статус", subStatusPill(s.status));
  // Продлений и триал — только у платных: у админских их нет (как в ТГ).
  if (subsCurrentKind !== "admin") h += kvRow("Продлений", s.times_renewed == null ? "—" : s.times_renewed);
  if (typeof p.enabled !== "undefined") h += kvRow("В панели", p.enabled ? "включена" : "выключена");
  if (p.traffic_ok) {
    let t = fmtBytesAdmin(usedBytes) + (limitBytes > 0 ? " из " + (s.total_gb || 0) + " ГБ" : " · лимит не задан");
    if (limitBytes > 0) {
      const pct = Math.min(100, Math.round(usedBytes / limitBytes * 100));
      t += '<span class="tbar"><span class="tbar-fill' + (pct >= 90 ? " hi" : "") + '" style="width:' + pct + '%"></span></span>';
    }
    h += kvRow("Трафик", t);
  } else {
    h += kvRow("Лимит трафика", Number(s.total_gb || 0) > 0 ? (s.total_gb + " ГБ") : "безлимит");
  }
  h += kvRow("Устройства", "лимит " + (s.limit_hwid == null ? "—" : s.limit_hwid) + (s.extra_devices ? " (включая купленные: +" + s.extra_devices + ")" : ""));
  h += kvRow("LTE", s.lte_gb == null ? "без лимита" : s.lte_gb + " ГБ");
  if (subsCurrentKind !== "admin") h += kvRow("Триал", s.trial_period == null ? "—" : fmtDays(s.trial_period));
  h += '</dl>';
  if (data.url_sub || data.url_key) {
    h += '<h3>Ссылки подписки</h3>';
    if (data.url_sub) h += '<div class="sublink"><span class="mut">sub</span><span class="mono">' + esc(data.url_sub) + '</span><button class="ghost" data-copy="' + esc(data.url_sub) + '">Копировать</button></div>';
    if (data.url_key) h += '<div class="sublink"><span class="mut">key</span><span class="mono">' + esc(data.url_key) + '</span><button class="ghost" data-copy="' + esc(data.url_key) + '">Копировать</button></div>';
  }
  if (pays.items && pays.items.length) {
    h += '<h3>Платежи владельца</h3><div class="tblwrap"><table><thead><tr><th>Дата</th><th>Провайдер</th><th>Сумма</th><th>Статус</th></tr></thead><tbody>' +
      pays.items.map(function(it){
        return '<tr><td class="mono">' + fmtDate(it.date) + '</td><td>' + esc(PROVIDER_LABELS[it.provider] || it.provider || "") + '</td><td class="num">' + fmtMoney(it.amount) + '</td><td>' + statusPill(it.status, PAY_LABELS[it.status] || it.status) + '</td></tr>';
      }).join("") + '</tbody></table></div><p class="mut">Всего платежей: ' + pays.count + ' · на сумму ' + fmtMoney(pays.sum) + '</p>';
  }
  h += '<h3>Продлить / изменить</h3>';
  h += '<label>Продлить на дней<input id="ed-days" type="number" placeholder="дней"></label><div class="btnrow"><button class="ghost" data-ed="extend">Продлить</button><button class="ghost" data-quick="30">+30</button><button class="ghost" data-quick="90">+90</button><button class="ghost" data-quick="365">+365</button></div>';
  h += '<label>Новая дата истечения<input id="ed-until" placeholder="напр. 2026-12-31 23:59" value="' + esc(s.expire_date || "") + '"></label><div class="btnrow"><button class="ghost" data-ed="expire">Установить дату</button></div>';
  h += '<label>Лимит устройств (HWID)<input id="ed-hwid" type="number" value="' + (s.limit_hwid || 0) + '"></label><div class="btnrow"><button class="ghost" data-ed="hwid">Сохранить лимит</button></div>';
  h += '<label>Лимит трафика, ГБ<input id="ed-traffic" type="number" value="' + (s.total_gb || 0) + '"></label><div class="btnrow"><button class="ghost" data-ed="traffic">Сохранить лимит</button></div>';
  h += '<label>Лимит LTE, ГБ (пусто — без лимита)<input id="ed-lte" type="number" value="' + (s.lte_gb == null ? "" : s.lte_gb) + '"></label><div class="btnrow"><button class="ghost" data-ed="lte">Сохранить LTE</button></div>';
  if (subsCurrentKind !== "admin") h += '<label>Триал, дней<input id="ed-trial" type="number" value="' + Math.round((s.trial_period || 0) / 86400) + '"></label><div class="btnrow"><button class="ghost" data-ed="trial">Установить триал</button></div>';
  h += '<h3>Устройства и подключения</h3><div class="btnrow"><button class="ghost" id="ed-devices">Показать устройства</button><button class="ghost" id="ed-ips">IP-адреса</button></div><div id="ed-devices-out"></div>';
  h += '<h3>История</h3><div class="btnrow"><button class="ghost" id="ed-history">Показать историю</button></div><div id="ed-history-out"></div>';
  h += '<p class="mut" id="ed-msg" style="margin-top:10px"></p>';
  $("drawer-body").innerHTML = h;
  $("drawer-foot").innerHTML = '<button class="ghost" data-ed="toggle">Вкл / выкл</button><button class="ghost" data-ed="freeze">Заморозить</button><button class="ghost" data-ed="reissue">Перевыпустить</button><button class="danger" data-ed="delete">Удалить</button>';
  const bind = function(root){
    root.querySelectorAll("[data-ed]").forEach(function(b){
      b.onclick = withSpin(b, function(){ return subEditorAction(b.dataset.ed); });
    });
  };
  bind($("drawer-body")); bind($("drawer-foot"));
  $("drawer-body").querySelectorAll("[data-quick]").forEach(function(b){
    b.onclick = withSpin(b, function(){ $("ed-days").value = b.dataset.quick; return subEditorAction("extend"); });
  });
  $("drawer-body").querySelectorAll("[data-copy]").forEach(function(b){
    b.onclick = function(){
      if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(function(){ toast("Ссылка скопирована", "ok"); });
    };
  });
  $("ed-devices").onclick = loadSubDevices;
  $("ed-ips").onclick = loadSubIps;
  $("ed-history").onclick = function(){ loadSubHistory(1); };
}
let subHistoryPage = 1;
async function loadSubHistory(page){
  const out = $("ed-history-out");
  if (!out) return;
  out.innerHTML = '<p class="mut">Загрузка…</p>';
  const prefix = subsCurrentKind === "admin" ? "/admin-subs/" : "/subs/";
  const r = await api(prefix + subsCurrentId + "/history?page=" + page);
  if (r.status !== 200) { out.innerHTML = '<p class="err">Не удалось получить историю</p>'; return; }
  if (r.data.no_tg_id) { out.innerHTML = '<p class="mut">У подписки нет TG ID — истории нет</p>'; return; }
  const items = r.data.events || [];
  subHistoryPage = r.data.page || page;
  const total = r.data.total_pages || 1;
  let h = "";
  if (!items.length) h += '<p class="mut">Событий пока не было</p>';
  else {
    h += '<div class="tblwrap"><table><thead><tr><th>Когда</th><th>Событие</th><th>Подробности</th></tr></thead><tbody>' +
      items.map(function(it){
        return '<tr><td class="mono">' + fmtDate(it.created_at) + '</td><td>' + esc(it.label || it.action || "") + '</td><td class="mut">' + esc(String(it.details || "").slice(0, 140)) + '</td></tr>';
      }).join("") + '</tbody></table></div>';
  }
  if (total > 1) {
    h += '<div class="btnrow" style="margin-top:8px;align-items:center"><button class="ghost" id="ed-hist-prev"' + (subHistoryPage <= 1 ? " disabled" : "") + '>← Назад</button><span class="mut">Страница ' + subHistoryPage + ' из ' + total + '</span><button class="ghost" id="ed-hist-next"' + (subHistoryPage >= total ? " disabled" : "") + '>Вперёд →</button></div>';
  }
  out.innerHTML = h;
  const pv = $("ed-hist-prev"), nx = $("ed-hist-next");
  if (pv) pv.onclick = function(){ if (subHistoryPage > 1) loadSubHistory(subHistoryPage - 1); };
  if (nx) nx.onclick = function(){ if (subHistoryPage < total) loadSubHistory(subHistoryPage + 1); };
}
async function loadSubDevices(){
  const out = $("ed-devices-out");
  if (!out) return;
  out.innerHTML = '<p class="mut">Загрузка…</p>';
  const prefix = subsCurrentKind === "admin" ? "/admin-subs/" : "/subs/";
  const r = await api(prefix + subsCurrentId + "/devices");
  if (r.status !== 200 || !r.data.ok) { out.innerHTML = '<p class="err">Не удалось получить устройства</p>'; return; }
  const items = r.data.items || [];
  let h = "";
  if (!items.length) h += '<p class="mut">Устройств нет</p>';
  else {
    h += '<div class="tblwrap"><table><thead><tr><th>Устройство</th><th>Платформа</th><th>IP</th><th>Последний визит</th><th></th></tr></thead><tbody>' +
      items.map(function(d){
        return '<tr><td>' + esc(d.deviceModel || "Устройство") + '</td><td>' + esc(d.platform || "") + '</td><td class="mono">' + esc(d.requestIp || "") + '</td><td class="mono">' + esc(String(d.lastSeen || "").slice(0, 16).replace("T", " ")) + '</td><td><button class="ghost" data-dev-del="' + esc(d.hwid || d.id || "") + '">Убрать</button></td></tr>';
      }).join("") + '</tbody></table></div>';
  }
  h += '<div class="btnrow"><button class="danger" id="ed-dev-clear">Сбросить все устройства</button></div>';
  out.innerHTML = h;
  out.querySelectorAll("[data-dev-del]").forEach(function(b){
    b.onclick = withSpin(b, async function(){
      const prefix = subsCurrentKind === "admin" ? "/admin-subs/" : "/subs/";
      const rr = await postConfirm(prefix + subsCurrentId + "/devices/delete", {ref: b.dataset.devDel});
      if (rr.status === 200) { toast("Устройство убрано", "ok"); loadSubDevices(); }
      else toast("Ошибка: " + (rr.data.error || rr.status), "err");
    });
  });
  const clr = $("ed-dev-clear");
  if (clr) clr.onclick = withSpin(clr, async function(){
    const prefix = subsCurrentKind === "admin" ? "/admin-subs/" : "/subs/";
    const rr = await postConfirm(prefix + subsCurrentId + "/devices/clear", {});
    if (rr.status === 200) { toast("Устройства сброшены", "ok"); loadSubDevices(); }
    else toast("Ошибка: " + (rr.data.error || rr.status), "err");
  });
}
async function loadSubIps(){
  const out = $("ed-devices-out");
  if (!out) return;
  out.innerHTML = '<p class="mut">Загрузка…</p>';
  const prefix = subsCurrentKind === "admin" ? "/admin-subs/" : "/subs/";
  const r = await api(prefix + subsCurrentId + "/ips");
  if (r.status !== 200 || !r.data.ok) { out.innerHTML = '<p class="err">Не удалось получить IP-адреса</p>'; return; }
  const items = r.data.items || [];
  if (!items.length) { out.innerHTML = '<p class="mut">IP-адресов нет</p>'; return; }
  out.innerHTML = '<div class="tblwrap"><table><thead><tr><th>IP</th><th>Устройство</th><th>Когда</th></tr></thead><tbody>' +
    items.map(function(it){ return '<tr><td class="mono">' + esc(it.ip || "") + '</td><td>' + esc(it.node || "") + '</td><td class="mono">' + esc(String(it.ts || "").slice(0, 16).replace("T", " ")) + '</td></tr>'; }).join("") +
    '</tbody></table></div>';
}
async function subEditorAction(a){
  const id = subsCurrentId;
  let body = {};
  // Действия админской подписки идут тем же маршрутом, что у платной,
  // но с kind="admin" — сервис тогда правит таблицу admin_subs.
  if (subsCurrentKind === "admin") body.kind = "admin";
  if (a === "extend") body.days = parseInt($("ed-days").value || "0", 10);
  if (a === "expire") body.until = $("ed-until").value;
  if (a === "hwid") body.limit = parseInt($("ed-hwid").value || "0", 10);
  if (a === "traffic") body.gb = parseInt($("ed-traffic").value || "0", 10);
  if (a === "lte") { const v = $("ed-lte").value.trim(); body.gb = v === "" ? null : parseInt(v, 10); }
  if (a === "trial") body.period_days = parseInt($("ed-trial").value || "0", 10);
  const r = await postConfirm("/subs/" + id + "/" + a, body);
  const msg = $("ed-msg");
  if (msg) msg.textContent = r.status === 200 ? "Готово" : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) {
    toast("Подписка обновлена", "ok");
    const c = await api((subsCurrentKind === "admin" ? "/admin-subs/" : "/subs/") + id);
    if (c.status === 200) renderSubEditor(c.data);
    loadSubs(subsPage);
    if (subsCurrentKind === "admin") loadAdminSubs(asubPage);
  }
}
/* --- Массовые действия: вкладки как в ТГ (BULK_SCOPES) --- */
let bulkScope = "all", bulkCounts = {};
const BULK_TABS = {all: ["📋", "Все"], active: ["🟢", "Активные"], trial: ["🆓", "Пробные"], paying: ["💳", "Платящие"], soon: ["⏳", "Скоро кончатся"], expired: ["🔴", "Истёкшие"]};
function renderBulkTabs(){
  $("bulk-tabs").innerHTML = Object.keys(BULK_TABS).map(function(k){
    const c = bulkCounts[k];
    return '<button class="ghost' + (k === bulkScope ? " active" : "") + '" data-bulk-tab="' + k + '">' + BULK_TABS[k][0] + " " + BULK_TABS[k][1] + (c == null ? "" : " · " + c) + "</button>";
  }).join("");
  const c = bulkCounts[bulkScope];
  $("bulk-scope-info").textContent = "Выборка: " + BULK_TABS[bulkScope][0] + " " + BULK_TABS[bulkScope][1] + (c == null ? "" : " — подписок: " + c) + ". Действие применится ко всей выборке сразу.";
}
async function loadBulkScopes(){
  try {
    const r = await api("/subs/bulk/scopes");
    if (r.status === 200 && r.data.counts) bulkCounts = r.data.counts;
  } catch(e) {}
  renderBulkTabs();
}
$("bulk-tabs").addEventListener("click", function(e){
  const b = e.target.closest("button[data-bulk-tab]");
  if (!b) return;
  bulkScope = b.dataset.bulkTab;
  renderBulkTabs();
});
$("btn-bulk").onclick = async function(){
  const kind = $("bulk-kind").value;
  const body = {scope: bulkScope};
  if (kind === "extend") { body.days = parseInt($("bulk-days").value || "0", 10); body.direction = body.days >= 0 ? "extend" : "reduce"; }
  else { body.value = parseInt($("bulk-value").value || "0", 10); body.kind_limit = $("bulk-kind-limit").value || "hwid"; }
  const r = await postConfirm("/subs/bulk/" + kind, body);
  renderOut("bulk-out", r.data);
  if (r.status === 200) loadBulkScopes();
};
$("btn-presets").onclick = async function(){
  const r = await api("/subs/presets");
  renderOut("presets-out", r.data);
  if (r.status === 200 && r.data.presets) {
    const p = r.data.presets;
    const div = document.createElement("div");
    div.innerHTML = '<h3>Изменить пресеты</h3>' +
      '<label>Триал, дней<input id="pr-trial" type="number" value="' + Math.round((p.paid_trial_period || 0) / 86400) + '"></label>' +
      '<label>Лимит устройств<input id="pr-hwid" type="number" value="' + (p.paid_preset_hwid || 0) + '"></label>' +
      '<label>Лимит трафика, ГБ<input id="pr-traffic" type="number" value="' + (p.paid_preset_traffic || 0) + '"></label>' +
      '<label>Лимит LTE, ГБ<input id="pr-lte" type="number" value="' + (p.paid_preset_lte || 0) + '"></label>' +
      '<button id="btn-pr-save" class="ghost">Сохранить пресеты</button>';
    $("presets-out").appendChild(div);
    $("btn-pr-save").onclick = async function(){
      const rr = await api("/subs/presets", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({
        paid_trial_period: parseInt($("pr-trial").value || "0", 10) * 86400,
        paid_preset_hwid: parseInt($("pr-hwid").value || "0", 10),
        paid_preset_traffic: parseInt($("pr-traffic").value || "0", 10),
        paid_preset_lte: parseInt($("pr-lte").value || "0", 10)})});
      toast(rr.status === 200 ? "Пресеты сохранены" : "Ошибка: " + (rr.data.error || rr.status), rr.status === 200 ? "ok" : "err");
    };
  }
};
$("btn-asub").onclick = withSpin($("btn-asub"), async function(){
  const r = await api("/admin-subs", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({tg_id: parseInt($("asub-tg").value || "0", 10)})});
  renderOut("asub-out", r.data);
  if (r.status === 200) loadAdminSubs(1);
});
$("btn-referrals").onclick = async function(){ const r = await api("/referrals"); renderOut("ref-out", r.data); };
$("btn-lte").onclick = async function(){ const r = await postConfirm("/subs/lte/check-now", {}); renderOut("ref-out", r.data); };

/* --- Финансы и оплаты --- */
const MONTHS_RU = ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
function fillFinPeriods(){
  const sel = $("fin-period");
  if (!sel || sel.options.length) return;
  const now = new Date();
  for (let i = 0; i < 6; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const v = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
    const o = document.createElement("option");
    o.value = v; o.textContent = MONTHS_RU[d.getMonth()] + " " + d.getFullYear();
    sel.appendChild(o);
  }
}
function finPeriodTitle(){
  const v = $("fin-period").value || "";
  const m = v.match(/^(\d{4})-(\d{2})$/);
  return m ? MONTHS_RU[parseInt(m[2], 10) - 1] + " " + m[1] : v;
}
async function loadFinance(){
  fillFinPeriods();
  let r;
  try { r = await api("/finance?period=" + $("fin-period").value); }
  catch(e) { $("finance-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { $("finance-out").innerHTML = '<p class="err">Ошибка: ' + esc((r.data && r.data.error) || r.status) + "</p>"; return; }
  const sm = r.data.summary || {}, pm = r.data.payments || {}, srvs = r.data.servers || [];
  const cells = [
    ["Доход (нетто)", fmtMoney(sm.income), "с возвратами было: " + fmtMoney(sm.income_gross)],
    ["Возвраты", fmtMoney(sm.refunds), ""],
    ["Расходы на серверы", fmtMoney(sm.expenses), "оплачено: " + fmtMoney(sm.expenses_paid) + " · не оплачено: " + fmtMoney(sm.expenses_unpaid)],
    ["Прибыль", fmtMoney(sm.profit), "доход минус все расходы месяца"],
    ["Оплат сегодня", fmtNum((pm.today || [0])[0]), fmtMoney((pm.today || [0, 0])[1])],
    ["Оплат за 30 дней", fmtNum((pm.month || [0])[0]), fmtMoney((pm.month || [0, 0])[1])],
    ["Всего оплат", fmtNum(pm.total_count), fmtMoney(pm.total_sum) + " · платящих: " + fmtNum(pm.payers || 0) + " · средний чек: " + fmtMoney(pm.avg || 0)],
    ["Ожидают оплаты", fmtNum(pm.pending_count), fmtMoney(pm.pending_sum)]
  ];
  let h = '<div class="grid">' + cells.map(function(c){
    return '<div class="stat"><b>' + c[1] + '</b><span>' + c[0] + "</span>" + (c[2] ? "<small>" + c[2] + "</small>" : "") + "</div>";
  }).join("") + "</div>";
  if ((pm.by_provider || []).length) {
    h += '<h3>По провайдерам (за всё время)</h3><div class="tblwrap"><table><thead><tr><th>Провайдер</th><th>Оплат</th><th>Сумма</th></tr></thead><tbody>';
    pm.by_provider.forEach(function(bp){
      h += '<tr><td>' + esc(PROVIDER_LABELS[bp[0]] || bp[0] || "—") + '</td><td class="num">' + fmtNum(bp[1]) + '</td><td class="num">' + fmtMoney(bp[2]) + "</td></tr>";
    });
    h += "</tbody></table></div>";
  }
  h += '<h3>Серверы — оплата за ' + esc(finPeriodTitle()) + '</h3>';
  if (!srvs.length) h += '<div class="empty">Серверов в учёте нет</div>';
  else {
    h += '<div class="tblwrap"><table><thead><tr><th>Сервер</th><th>Цена</th><th>День оплаты</th><th>Статус</th></tr></thead><tbody>';
    srvs.forEach(function(sv){
      const st = sv.status === "paid" ? statusPill("paid", "Оплачено") : sv.status === "unpaid" ? statusPill("failed", "Не оплачено") : '<span class="pill warn">Не отмечено</span>';
      h += '<tr><td>' + esc(sv.name) + '</td><td class="num">' + fmtMoney(sv.price) + '</td><td class="num">' + (sv.day || "—") + "</td><td>" + st + "</td></tr>";
    });
    h += "</tbody></table></div>";
  }
  $("finance-out").innerHTML = h;
}
$("btn-finance").onclick = withSpin($("btn-finance"), loadFinance);
$("btn-servers").onclick = function(){
  loadServers();
  const el = $("srv-out");
  if (el) el.scrollIntoView({behavior: "smooth", block: "start"});
};
$("fin-period").addEventListener("change", function(){ loadFinance(); loadServers(); });
$("btn-platega").onclick = async function(){ const r = await api("/platega"); renderOut("platega-out", r.data); };
$("btn-platega-save").onclick = withSpin($("btn-platega-save"), async function(){
  const body = {};
  const m = $("pl-merchant").value.trim();
  const s = $("pl-secret").value;
  if (m) body.platega_merchant_id = m;
  if (s) body.platega_secret = s;
  const r = await api("/platega", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
  renderOut("platega-out", r.data);
  if (r.status === 200) { $("pl-secret").value = ""; toast("Данные Platega сохранены", "ok"); }
});
let lastReconcile = null;
$("btn-reconcile").onclick = withSpin($("btn-reconcile"), async function(){
  const r = await postConfirm("/reconcile/run", {});
  lastReconcile = r.data;
  renderOut("reconcile-out", r.data);
});
$("btn-reconcile-fix").onclick = async function(){
  const fixes = (lastReconcile && lastReconcile.fixable) || [];
  if (!fixes.length) { toast("Сначала запустите сверку — расхождений нет", "err"); return; }
  const r = await postConfirm("/reconcile/fix", {fixes: fixes});
  renderOut("reconcile-out", r.data);
};
/* --- Серверы (расходы): список + редактор --- */
let serversLoaded = false;
async function loadServers(){
  fillFinPeriods();
  let r;
  try { r = await api("/servers?period=" + $("fin-period").value); }
  catch(e) { $("srv-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("srv-out", r.data); return; }
  const items = r.data.servers || [];
  if (!items.length) { $("srv-out").innerHTML = '<div class="empty"><span class="big">🔍</span>Серверов нет</div>'; return; }
  let h = '<p class="sub">Период: ' + esc(finPeriodTitle()) + '</p><div class="tblwrap"><table><thead><tr><th>Название</th><th>Цена</th><th>День оплаты</th><th>Оплата за период</th></tr></thead><tbody>';
  items.forEach(function(it){
    const st = it.status === "paid" ? statusPill("paid", "Оплачено") : it.status === "unpaid" ? statusPill("failed", "Не оплачено") : '<span class="pill warn">Не отмечено</span>';
    h += '<tr data-sid="' + it.id + '"><td>' + esc(it.name) + '</td><td class="num">' + fmtMoney(it.price) + '</td><td class="num">' + (it.day || "—") + '</td><td>' + st + '</td></tr>';
  });
  $("srv-out").innerHTML = h + '</tbody></table></div>';
  $("srv-out").querySelectorAll("tr[data-sid]").forEach(function(tr){
    tr.onclick = function(){ openServerEditor(parseInt(tr.dataset.sid, 10)); };
  });
}
$("btn-servers-list").onclick = function(){ loadServers(); };
document.querySelector('[data-nav="finance"]').addEventListener("click", function(){
  if (!serversLoaded) { serversLoaded = true; loadFinance(); loadServers(); }
});
$("btn-srv-add").onclick = withSpin($("btn-srv-add"), async function(){
  const r = await api("/servers", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({name: $("srv-name").value, price_rub: parseInt($("srv-price").value || "0", 10), pay_day: parseInt($("srv-day").value || "1", 10)})});
  if (r.status === 200) { toast("Сервер добавлен", "ok"); loadServers(); }
  else renderOut("srv-out", r.data);
});
async function openServerEditor(sid){
  $("drawer-title").textContent = "Сервер #" + sid;
  $("drawer-sub").textContent = "Загрузка…";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:18px;width:50%;margin-bottom:10px"></div><div class="skel" style="height:120px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  let r;
  try { r = await api("/servers/" + sid); }
  catch(e) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить сервер</p>'; return; }
  if (r.status !== 200) { $("drawer-body").innerHTML = '<p class="err">Сервер не найден</p>'; return; }
  const s = r.data.server || {};
  $("drawer-sub").textContent = s.name || "";
  let h = '<dl class="kv">';
  h += kvRow("ID", '<span class="mono">' + s.id + '</span>');
  h += kvRow("Активен", statusPill(s.active ? "active" : "disabled", s.active ? "Активен" : "Выключен"));
  if (s.period) h += kvRow("Период", esc(s.period));
  if (s.status) h += kvRow("Оплата за период", s.status === "paid" ? "Оплачено" : s.status === "unpaid" ? "Не оплачено" : esc(s.status));
  h += '</dl>';
  h += '<h3>Изменить</h3>';
  h += '<label>Название<input id="ed-srv-name" value="' + esc(s.name || "") + '"></label>';
  h += '<label>Цена, ₽/мес<input id="ed-srv-price" type="number" value="' + (s.price_rub || 0) + '"></label>';
  h += '<label>День оплаты (1–31)<input id="ed-srv-day" type="number" value="' + (s.pay_day || 1) + '"></label>';
  h += '<div class="btnrow"><button class="ghost" id="ed-srv-save">Сохранить</button></div>';
  h += '<p class="mut" id="ed-srv-msg" style="margin-top:10px"></p>';
  $("drawer-body").innerHTML = h;
  $("drawer-foot").innerHTML = '<button class="ghost" id="ed-srv-mark">Отметить оплаченным</button><button class="danger" id="ed-srv-del">Удалить</button>';
  $("ed-srv-save").onclick = withSpin($("ed-srv-save"), async function(){
    const body = {
      name: $("ed-srv-name").value,
      price_rub: parseInt($("ed-srv-price").value || "0", 10),
      pay_day: parseInt($("ed-srv-day").value || "1", 10),
    };
    const rr = await api("/servers/" + sid, {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
    const msg = $("ed-srv-msg");
    if (msg) msg.textContent = rr.status === 200 ? "Готово" : ("Ошибка: " + (rr.data.error || rr.status));
    if (rr.status === 200) { toast("Сервер обновлён", "ok"); openServerEditor(sid); loadServers(); }
  });
  $("ed-srv-mark").onclick = withSpin($("ed-srv-mark"), async function(){
    const rr = await api("/servers/" + sid + "/mark", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({status: "paid"})});
    const msg = $("ed-srv-msg");
    if (msg) msg.textContent = rr.status === 200 ? "Отмечено оплаченным" : ("Ошибка: " + (rr.data.error || rr.status));
    if (rr.status === 200) { toast("Оплата отмечена", "ok"); openServerEditor(sid); loadServers(); }
  });
  $("ed-srv-del").onclick = withSpin($("ed-srv-del"), async function(){
    const rr = await postConfirmAny("/servers/" + sid, "DELETE", {});
    if (rr.status === 200) { toast("Сервер удалён", "ok"); closeDrawer(); loadServers(); }
    else { const msg = $("ed-srv-msg"); if (msg) msg.textContent = "Ошибка: " + (rr.data.error || rr.status); }
  });
}
/* --- Оплаты: список + карточка в редакторе --- */
let paymentsLoaded = false;
const PAY_LABELS = {paid: "Оплачено", pending: "Ожидает", refunded: "Возвращён", failed: "Неудачный", expired: "Истёк", canceled: "Отменён", cancelled: "Отменён"};
const PROVIDER_LABELS = {platega: "Platega", anore: "Anore", yookassa: "ЮKassa", telegram: "Telegram", stars: "Stars", crypto: "Крипта", manual: "Вручную"};
let paymentsPage = 1, paymentsTotalPages = 1, paymentsQTimer = null;
async function loadPayments(page){
  paymentsPage = page || 1;
  const st = $("pay-status").value;
  const prov = $("pay-provider").value;
  const q = $("pay-q").value.trim();
  let url = "/payments?status=" + (st || "all") + "&page=" + paymentsPage;
  if (prov) url += "&provider=" + encodeURIComponent(prov);
  if (q) url += "&q=" + encodeURIComponent(q);
  let r;
  try { r = await api(url); }
  catch(e) { $("payments-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("payments-out", r.data); return; }
  paymentsTotalPages = r.data.total_pages || 1;
  paymentsPage = r.data.page || paymentsPage;
  $("payments-page-label").textContent = "Стр. " + paymentsPage + " из " + paymentsTotalPages;
  show("btn-payments-prev", paymentsPage > 1); show("btn-payments-next", paymentsPage < paymentsTotalPages);
  $("payments-summary").textContent = "Найдено " + (r.data.total || 0) + " · на сумму " + fmtMoney(r.data.total_amount || 0);
  // селект провайдеров — со счётчиками в текущей выборке; выбранный
  // провайдер держим в списке, даже если под текущий статус у него
  // ноль счетов, чтобы фильтр не сбрасывался молча
  const provs = r.data.providers || [];
  const cur = prov;
  let opts = '<option value="">Все провайдеры</option>';
  if (cur && !provs.some(function(p){ return p.provider === cur; })) {
    opts += '<option value="' + esc(cur) + '" selected>' + esc(PROVIDER_LABELS[cur] || cur) + ' (0)</option>';
  }
  provs.forEach(function(p){
    opts += '<option value="' + esc(p.provider) + '"' + (p.provider === cur ? ' selected' : '') + '>' + esc(PROVIDER_LABELS[p.provider] || p.provider) + ' (' + p.count + ')</option>';
  });
  $("pay-provider").innerHTML = opts;
  const items = r.data.payments || [];
  if (!items.length) { $("payments-out").innerHTML = '<div class="empty"><span class="big">🔍</span>Оплат не найдено</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>ID</th><th>Пользователь</th><th>Сумма</th><th>Статус</th><th>Дата</th><th>Провайдер</th></tr></thead><tbody>';
  items.forEach(function(it){
    const name = esc(it.first_name || "—") + (it.username ? ' <span class="mut">@' + esc(it.username) + '</span>' : "") + ' <span class="mono small">#' + it.tg_id + '</span>';
    h += '<tr data-pay-id="' + it.id + '"><td class="mono">' + it.id + '</td><td>' + name + '</td><td class="num">' + fmtMoney(it.amount) + '</td><td>' + statusPill(it.status, PAY_LABELS[it.status] || it.status) + '</td><td><span class="mono">' + fmtDate(it.date) + '</span></td><td>' + esc(PROVIDER_LABELS[it.provider] || it.provider || "") + '</td></tr>';
  });
  $("payments-out").innerHTML = h + '</tbody></table></div>';
  $("payments-out").querySelectorAll("tr[data-pay-id]").forEach(function(tr){
    tr.onclick = function(){ openPaymentEditor(parseInt(tr.dataset.payId, 10)); };
  });
}
$("btn-payments").onclick = function(){ loadPayments(1); };
$("btn-payments-export").onclick = function(){
  const st = $("pay-status").value;
  const prov = $("pay-provider").value;
  const q = $("pay-q").value.trim();
  let url = "/payments/export?status=" + (st || "all");
  if (prov) url += "&provider=" + encodeURIComponent(prov);
  if (q) url += "&q=" + encodeURIComponent(q);
  downloadCsv(url);
};
$("pay-status").onchange = function(){ loadPayments(1); };
$("pay-provider").onchange = function(){ loadPayments(1); };
$("pay-q").addEventListener("input", function(){
  clearTimeout(paymentsQTimer);
  paymentsQTimer = setTimeout(function(){ loadPayments(1); }, 500);
});
$("pay-q").addEventListener("keydown", function(e){
  if (e.key === "Enter") { clearTimeout(paymentsQTimer); loadPayments(1); }
});
$("btn-payments-prev").onclick = function(){ if (paymentsPage > 1) loadPayments(paymentsPage - 1); };
$("btn-payments-next").onclick = function(){ if (paymentsPage < paymentsTotalPages) loadPayments(paymentsPage + 1); };
document.querySelector('[data-nav="payments"]').addEventListener("click", function(){
  if (!paymentsLoaded) { paymentsLoaded = true; loadPayments(); }
});
async function openPaymentEditor(pid){
  $("drawer-title").textContent = "Оплата #" + pid;
  $("drawer-sub").textContent = "Загрузка…";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:18px;width:50%;margin-bottom:10px"></div><div class="skel" style="height:120px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  let r;
  try { r = await api("/payments/" + pid); }
  catch(e) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить оплату</p>'; return; }
  if (r.status !== 200) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить оплату</p>'; return; }
  const p = r.data.payment || {};
  $("drawer-sub").textContent = (p.first_name || p.username ? ((p.first_name || "") + (p.username ? " @" + p.username : "")) : "") + " · tg #" + p.tg_id;
  let h = '<dl class="kv">';
  h += kvRow("Сумма", fmtMoney(p.amount));
  h += kvRow("Статус", statusPill(p.status, PAY_LABELS[p.status] || p.status));
  h += kvRow("Провайдер", esc(PROVIDER_LABELS[p.provider] || p.provider || ""));
  h += kvRow("Внешний ID", '<span class="mono">' + esc(p.external_id || "") + '</span>');
  h += kvRow("Срок", fmtDays(p.period_seconds));
  h += kvRow("Промокод", esc(p.promo || "—"));
  h += kvRow("Создан", '<span class="mono">' + fmtDate(p.created) + '</span>');
  h += kvRow("Оплачен", '<span class="mono">' + fmtDate(p.paid) + '</span>');
  if (p.refunded_at) h += kvRow("Возвращён", '<span class="mono">' + fmtDate(p.refunded_at) + '</span>');
  if (p.partial_refunded) h += kvRow("Возвращено частично", fmtMoney(p.partial_refunded));
  if (p.pay_url) h += kvRow("Ссылка на оплату", '<a href="' + esc(p.pay_url) + '" target="_blank" rel="noopener">открыть</a>');
  if (p.error) h += kvRow("Ошибка", esc(p.error));
  h += '</dl>';
  if (p.provider === "platega" && p.external_id) {
    h += '<div class="btnrow" style="margin-top:12px"><button id="ed-pay-check" class="ghost">🔍 Проверить в Platega</button></div>';
    h += '<div id="ed-pay-platega" style="margin-top:8px"></div>';
  }
  if (p.status === "paid") {
    h += '<label><input id="ed-pay-revoke" type="checkbox"> отозвать подписку при возврате</label>';
    h += '<p class="mut" id="ed-pay-msg" style="margin-top:10px"></p>';
  }
  $("drawer-body").innerHTML = h;
  const chkBtn = $("ed-pay-check");
  if (chkBtn) {
    chkBtn.onclick = withSpin(chkBtn, async function(){
      const box = $("ed-pay-platega");
      if (box) box.innerHTML = '<p class="mut">Запрашиваю счёт в Platega…</p>';
      let rr;
      try { rr = await api("/payments/" + pid + "/platega"); }
      catch(e) { if (box) box.innerHTML = '<p class="err">Не удалось проверить счёт</p>'; return; }
      if (!box) return;
      if (rr.status !== 200) {
        const d = rr.data || {};
        box.innerHTML = '<p class="err">' + esc(d.error === "platega_not_found" ? "Счёт не найден в Platega" : "Platega не ответила: " + (d.details || d.error || rr.status)) + '</p>';
        return;
      }
      const d = rr.data || {}, live = d.live || {}, bot = d.bot || {};
      let hh = '<dl class="kv">';
      hh += kvRow("Статус в Platega", esc(live.status_label || live.status || ""));
      hh += kvRow("Сумма в Platega", fmtMoney(live.amount));
      hh += kvRow("Оплачен в Platega", live.paid ? "да" : "нет");
      if (live.method) hh += kvRow("Способ", esc(live.method));
      if (live.payload) hh += kvRow("Заказ", '<span class="mono">' + esc(String(live.payload)) + '</span>');
      hh += kvRow("Начисление", d.credited ? "✅ записано в журнале" : "— нет записи");
      hh += '</dl>';
      if (!d.match) hh += '<p style="color:var(--warn);margin-top:10px">Статусы расходятся: в базе бота — ' + esc(PAY_LABELS[bot.status] || bot.status || "") + ', в Platega — ' + esc(live.status_label || live.status || "") + '. Сверьте в «Финансах» → «Сверка».</p>';
      box.innerHTML = hh;
    });
  }
  if (p.status === "paid") {
    $("drawer-foot").innerHTML = '<button class="danger" id="ed-pay-refund">Вернуть оплату</button>';
    $("ed-pay-refund").onclick = withSpin($("ed-pay-refund"), async function(){
      const rr = await postConfirm("/payments/" + pid + "/refund", {revoke: $("ed-pay-revoke").checked});
      const msg = $("ed-pay-msg");
      if (msg) msg.textContent = rr.status === 200 ? "Возврат оформлен" : ("Ошибка: " + (rr.data.error || rr.status));
      if (rr.status === 200) { toast("Возврат оформлен", "ok"); openPaymentEditor(pid); loadPayments(paymentsPage); }
    });
  }
}

/* --- Рассылка, промокоды, тарифы --- */
let bcPhoto = "";
$("btn-bc-upload").onclick = async function(){
  const f = $("bc-photo").files[0];
  if (!f) { $("bc-photo-msg").textContent = "Выберите файл"; return; }
  const fd = new FormData(); fd.append("photo", f);
  const r = await fetch(API + "/broadcast/upload", {method: "POST", credentials: "same-origin", headers: {"X-CSRF-Token": csrf()}, body: fd});
  let data = {}; try { data = await r.json(); } catch(e) {}
  if (r.status === 200) { bcPhoto = data.photo_file_id || ""; $("bc-photo-msg").textContent = "Фото загружено (" + (data.width || "?") + "×" + (data.height || "?") + ")"; }
  else $("bc-photo-msg").textContent = "Ошибка: " + (data.error || r.status);
};
$("btn-bc-preview").onclick = async function(){
  const r = await api("/broadcast/preview", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({text: $("bc-text").value, segment: $("bc-seg").value, photo: bcPhoto || undefined})});
  $("bc-out").textContent = r.status === 200 ? ("Получателей: " + (r.data.count || 0)) : ("Ошибка: " + (r.data.error || r.status));
};
$("btn-bc-send").onclick = async function(){
  const r = await postConfirm("/broadcast/send", {text: $("bc-text").value, segment: $("bc-seg").value, photo: bcPhoto || undefined});
  $("bc-out").textContent = r.status === 200 ? "Рассылка запущена" : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) { bcPhoto = ""; toast("Рассылка запущена", "ok"); }
};
/* --- Пост в ТГ-канал --- */
let chPhotos = [], chButtonsSel = [], chButtonsDef = [], channelLoaded = false;
function chPayload(){
  return {text: $("ch-text").value, photos: chPhotos.slice(),
    buttons: chButtonsSel.slice(), use_sign: $("ch-use-sign").checked};
}
function renderChPhotos(){
  $("ch-photos").innerHTML = chPhotos.length ? chPhotos.map(function(fid, i){
    return '<div>🖼 Фото ' + (i + 1) + ' <span class="mono">' + esc(fid.slice(0, 12)) + '…</span> <button class="ghost" data-ch-del="' + i + '">✕</button></div>';
  }).join("") : "";
  $("ch-photos").querySelectorAll("[data-ch-del]").forEach(function(b){
    b.onclick = function(){ chPhotos.splice(parseInt(b.dataset.chDel, 10), 1); renderChPhotos(); };
  });
}
async function loadChannel(){
  let r;
  try { r = await api("/channel"); }
  catch(e) { $("ch-status").textContent = "Ошибка загрузки"; return; }
  if (r.status !== 200) { $("ch-status").textContent = "Ошибка: " + (r.data.error || r.status); return; }
  const d = r.data;
  $("ch-status").innerHTML = d.channel
    ? ("Канал: <b>" + esc(d.channel) + "</b>" + (d.signature_plain ? " · подпись: <i>" + esc(d.signature_plain.slice(0, 80)) + "</i>" : " · подпись не задана"))
    : "⚠️ Канал не настроен — задайте ссылку на канал в Настройках (channel_url).";
  $("ch-sign").value = d.signature || "";
  chButtonsDef = d.buttons || [];
  let h = "";
  chButtonsDef.forEach(function(b){
    h += '<label class="chk"><input type="checkbox" data-ch-btn="' + esc(b.key) + '"' + (chButtonsSel.indexOf(b.key) >= 0 ? " checked" : "") + '> ' + esc(b.label) + '</label>';
  });
  $("ch-buttons").innerHTML = h || "";
  $("ch-buttons").querySelectorAll("[data-ch-btn]").forEach(function(cb){
    cb.onchange = function(){
      const k = cb.dataset.chBtn;
      if (cb.checked) { if (chButtonsSel.indexOf(k) < 0) chButtonsSel.push(k); }
      else chButtonsSel = chButtonsSel.filter(function(x){ return x !== k; });
    };
  });
}
document.querySelector('[data-nav="broadcast"]').addEventListener("click", function(){
  if (!channelLoaded) { channelLoaded = true; loadChannel(); }
});
/* --- Напоминания и возврат --- */
let retentionLoaded = false;
function pluralRu(n, forms){
  n = Math.abs(Math.round(n));
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return n + " " + forms[0];
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return n + " " + forms[1];
  return n + " " + forms[2];
}
function durText(sec){
  sec = Math.round(sec || 0);
  if (!sec) return "0";
  if (sec % 86400 === 0) return pluralRu(sec / 86400, ["день", "дня", "дней"]);
  if (sec % 3600 === 0) return pluralRu(sec / 3600, ["час", "часа", "часов"]);
  if (sec % 60 === 0) return pluralRu(sec / 60, ["минута", "минуты", "минут"]);
  return String(sec);
}
function retErr(r){
  let s = "Ошибка: " + (r.data.error || r.status);
  if (r.data.details && r.data.details.length) s += " — " + r.data.details.join("; ");
  return s;
}
async function loadRetention(){
  let r;
  try { r = await api("/retention"); }
  catch(e) { $("ret-remind-status").textContent = "Ошибка загрузки"; return; }
  if (r.status !== 200) { $("ret-remind-status").textContent = "Ошибка: " + (r.data.error || r.status); return; }
  const d = r.data, rem = d.remind || {}, wb = d.winback || {};
  $("ret-remind-status").innerHTML = rem.enabled ? '<span class="pill ok">включены</span>' : '<span class="pill bad">выключены</span>';
  const rs = d.remind_stats || {};
  $("ret-remind-stats").textContent = "За 30 дней: отправлено " + fmtNum(rs.sent) + " · людям " + fmtNum(rs.people) + " · заплатили после напоминания " + fmtNum(rs.paid) + " (" + fmtNum(rs.percent) + "%)";
  $("ret-remind-enabled").checked = !!rem.enabled;
  $("ret-remind-trials").checked = !!rem.trials;
  $("ret-remind-first").value = durText(rem.first);
  $("ret-remind-second").value = durText(rem.second);
  $("ret-remind-third").value = durText(rem.third);
  $("ret-remind-quiet-from").value = (rem.quiet_from == null ? "" : rem.quiet_from);
  $("ret-remind-quiet-to").value = (rem.quiet_to == null ? "" : rem.quiet_to);
  $("ret-winback-status").innerHTML = wb.enabled ? '<span class="pill ok">включён</span>' : '<span class="pill bad">выключен</span>';
  const ws = d.winback_stats || {};
  $("ret-winback-stats").textContent = "Отправлено писем " + fmtNum(ws.sent) + " · людям " + fmtNum(ws.people) + " · промокод применили " + fmtNum(ws.used) + " · вернулись и заплатили " + fmtNum(ws.returned) + " (" + fmtNum(ws.percent) + "%)";
  $("ret-winback-enabled").checked = !!wb.enabled;
  $("ret-winback-paid-only").checked = !!wb.paid_only;
  $("ret-winback-days").value = wb.days;
  $("ret-winback-percent").value = wb.percent;
  $("ret-winback-days2").value = wb.days2;
  $("ret-winback-percent2").value = wb.percent2;
  $("ret-winback-life").value = wb.life_days;
  show("btn-ret-remind-test", !!d.is_mark);
  show("btn-ret-winback-test", !!d.is_mark);
}
document.querySelector('[data-nav="retention"]').addEventListener("click", function(){
  if (!retentionLoaded) { retentionLoaded = true; loadRetention(); }
});
$("btn-ret-remind-save").onclick = withSpin($("btn-ret-remind-save"), async function(){
  const r = await api("/retention/save", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({
    remind_enabled: $("ret-remind-enabled").checked,
    remind_trials: $("ret-remind-trials").checked,
    remind_first: $("ret-remind-first").value,
    remind_second: $("ret-remind-second").value,
    remind_third: $("ret-remind-third").value,
    remind_quiet_from: $("ret-remind-quiet-from").value,
    remind_quiet_to: $("ret-remind-quiet-to").value})});
  if (r.status === 200) { $("ret-remind-out").textContent = "Сохранено"; toast("Напоминания сохранены", "ok"); loadRetention(); }
  else $("ret-remind-out").textContent = retErr(r);
});
$("btn-ret-remind-test").onclick = withSpin($("btn-ret-remind-test"), async function(){
  const r = await api("/retention/remind/test", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: "{}"});
  if (r.status === 200) { $("ret-remind-out").textContent = "Пример отправлен вам в Telegram"; toast("Пример отправлен", "ok"); }
  else $("ret-remind-out").textContent = retErr(r);
});
function retInt(id, min, max){
  const v = parseInt($(id).value, 10);
  if (isNaN(v) || v < min || (max != null && v > max)) { $(id).focus(); return null; }
  return v;
}
$("btn-ret-winback-save").onclick = withSpin($("btn-ret-winback-save"), async function(){
  const days = retInt("ret-winback-days", 1, null), pct = retInt("ret-winback-percent", 1, 100),
        days2 = retInt("ret-winback-days2", 0, null), pct2 = retInt("ret-winback-percent2", 1, 100),
        life = retInt("ret-winback-life", 1, null);
  if (days == null || pct == null || days2 == null || pct2 == null || life == null) {
    $("ret-winback-out").textContent = "Проверьте числа: дни ≥ 1, скидки 1–100, вторая волна 0 — выключена";
    return;
  }
  const r = await api("/retention/save", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({
    winback_enabled: $("ret-winback-enabled").checked,
    winback_paid_only: $("ret-winback-paid-only").checked,
    winback_days: days, winback_percent: pct, winback_days2: days2,
    winback_percent2: pct2, winback_life_days: life})});
  if (r.status === 200) { $("ret-winback-out").textContent = "Сохранено"; toast("Возврат сохранён", "ok"); loadRetention(); }
  else $("ret-winback-out").textContent = retErr(r);
});
$("btn-ret-winback-test").onclick = withSpin($("btn-ret-winback-test"), async function(){
  const r = await api("/retention/winback/test", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: "{}"});
  if (r.status === 200) { $("ret-winback-out").textContent = "Пример письма отправлен вам в Telegram (промокод " + (r.data.code || "") + ")"; toast("Пример отправлен", "ok"); }
  else $("ret-winback-out").textContent = retErr(r);
});

/* --- Техработы и функции: как mnt_menu в ТГ --- */
let maintenanceLoaded = false;
function renderMaintenance(d){
  $("mnt-status").innerHTML = d.maintenance_enabled ? '<span class="pill bad">техработы включены — бот закрыт для пользователей</span>' : '<span class="pill ok">техработы выключены</span>';
  $("btn-mnt-toggle").textContent = d.maintenance_enabled ? "Выключить техработы" : "Включить техработы";
  // Предпросмотр — тот же текст, что увидят пользователи (HTML из ТГ).
  $("mnt-text-preview").innerHTML = d.maintenance_text || "";
  // В поле — только свой текст; стандартный не подставляем, иначе
  // сохранение перепишет его как свой.
  if (document.activeElement !== $("mnt-text")) $("mnt-text").value = d.text_custom ? d.maintenance_text : "";
  show("mnt-readonly", !d.is_mark);
  show("btn-mnt-toggle", !!d.is_mark);
  show("btn-mnt-text-save", !!d.is_mark);
  show("btn-mnt-text-reset", !!d.is_mark);
  $("mnt-text").disabled = !d.is_mark;
  const host = $("mnt-features");
  host.innerHTML = (d.features || []).map(function(f){
    return '<div class="btnrow" style="align-items:center"><span style="flex:1">' + (f.enabled ? "✅ " : "⏸ ") + esc(f.emoji) + " " + esc(f.name) + '</span>' +
      '<button class="ghost" data-mnt-feature="' + esc(f.key) + '"' + (d.is_mark ? "" : " disabled") + '>' + (f.enabled ? "Выключить" : "Включить") + '</button></div>';
  }).join("");
  host.querySelectorAll("[data-mnt-feature]").forEach(function(b){
    b.onclick = withSpin(b, async function(){
      const r = await api("/maintenance/feature", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({key: b.dataset.mntFeature})});
      if (r.status === 200) { toast("Функция переключена", "ok"); loadMaintenance(); }
      else $("mnt-features-out").textContent = "Ошибка: " + (r.data.error || r.status) + (r.data.details ? " — " + r.data.details : "");
    });
  });
}
async function loadMaintenance(){
  let r;
  try { r = await api("/maintenance"); }
  catch(e) { $("mnt-status").textContent = "Ошибка загрузки"; return; }
  if (r.status !== 200) { $("mnt-status").textContent = "Ошибка: " + (r.data.error || r.status); return; }
  renderMaintenance(r.data);
}
document.querySelector('[data-nav="maintenance"]').addEventListener("click", function(){
  if (!maintenanceLoaded) { maintenanceLoaded = true; loadMaintenance(); }
});
$("btn-mnt-toggle").onclick = withSpin($("btn-mnt-toggle"), async function(){
  const r = await postConfirm("/maintenance/toggle", {});
  if (r.status === 200) { $("mnt-toggle-out").textContent = ""; toast(r.data.maintenance_enabled ? "Техработы включены" : "Техработы выключены", "ok"); loadMaintenance(); }
  else if (r.status !== 0) $("mnt-toggle-out").textContent = "Ошибка: " + (r.data.error || r.status);
});
async function saveMaintenanceText(text){
  const r = await api("/maintenance/text", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({text: text})});
  if (r.status === 200) { $("mnt-text-out").textContent = "Сохранено — предпросмотр отправлен вам в Telegram"; toast("Текст техработ сохранён", "ok"); loadMaintenance(); }
  else $("mnt-text-out").textContent = "Ошибка: " + (r.data.error || r.status) + (r.data.details ? " — " + r.data.details : "");
}
$("btn-mnt-text-save").onclick = withSpin($("btn-mnt-text-save"), async function(){ await saveMaintenanceText($("mnt-text").value); });
$("btn-mnt-text-reset").onclick = withSpin($("btn-mnt-text-reset"), async function(){ await saveMaintenanceText("-"); });
$("btn-ch-upload").onclick = withSpin($("btn-ch-upload"), async function(){
  const files = $("ch-photo").files;
  if (!files.length) { $("ch-photo-msg").textContent = "Выберите файл"; return; }
  let ok = 0, lastErr = "";
  for (let i = 0; i < files.length; i++) {
    const fd = new FormData(); fd.append("photo", files[i]);
    const r = await fetch(API + "/channel/post/upload", {method: "POST", credentials: "same-origin", headers: {"X-CSRF-Token": csrf()}, body: fd});
    let data = {}; try { data = await r.json(); } catch(e) {}
    if (r.status === 200 && data.photo_file_id) { chPhotos.push(data.photo_file_id); ok++; }
    else lastErr = data.error || r.status;
  }
  renderChPhotos();
  $("ch-photo-msg").textContent = ok ? ("Загружено фото: " + ok + (lastErr ? (" · ошибка: " + lastErr) : "")) : ("Ошибка: " + lastErr);
});
$("btn-ch-preview").onclick = withSpin($("btn-ch-preview"), async function(){
  const r = await api("/channel/post/preview", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(chPayload())});
  if (r.status !== 200) { $("ch-out").textContent = "Ошибка: " + (r.data.error || r.status); return; }
  const d = r.data;
  let h = "Фото: " + d.photos + " · кнопок: " + (d.buttons || []).length + " · подпись: " + (d.signature_on ? "да" : "нет");
  if (d.album) h += "\\n⚠️ Альбом из нескольких фото — кнопки в канал не попадут.";
  if (d.caption_split) h += "\\n⚠️ Текст длиннее подписи к фото — уйдёт отдельным сообщением после фото.";
  h += "\\n\\n" + d.text;
  if (d.preview_sent) h += "\\n\\n✅ Предпросмотр отправлен вам в Telegram.";
  else if (d.preview_error) h += "\\n\\n⚠️ Живой предпросмотр не отправлен: " + d.preview_error;
  $("ch-out").innerText = h;
});
$("btn-ch-publish").onclick = withSpin($("btn-ch-publish"), async function(){
  const r = await postConfirm("/channel/post/publish", chPayload());
  if (r.status === 200) {
    $("ch-out").textContent = "✅ Пост опубликован в канале " + (r.data.channel || "");
    chPhotos = []; renderChPhotos(); toast("Пост опубликован", "ok");
  } else if (r.status !== 0) {
    $("ch-out").textContent = "Ошибка: " + (r.data.error || r.status) + (r.data.details ? (" — " + r.data.details) : "");
  }
});
$("btn-ch-sign-save").onclick = withSpin($("btn-ch-sign-save"), async function(){
  const r = await api("/channel/signature", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({signature: $("ch-sign").value})});
  if (r.status === 200) { $("ch-sign-out").textContent = "Подпись сохранена"; loadChannel(); }
  else $("ch-sign-out").textContent = "Ошибка: " + (r.data.error || r.status);
});
$("btn-ch-sign-del").onclick = withSpin($("btn-ch-sign-del"), async function(){
  const r = await api("/channel/signature", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({signature: ""})});
  if (r.status === 200) { $("ch-sign").value = ""; $("ch-sign-out").textContent = "Подпись убрана"; loadChannel(); }
  else $("ch-sign-out").textContent = "Ошибка: " + (r.data.error || r.status);
});
/* --- Промокоды: список + редактор --- */
let promosLoaded = false;
async function loadPromos(){
  let r;
  try { r = await api("/promos"); }
  catch(e) { $("promos-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("promos-out", r.data); return; }
  const items = r.data.promos || [];
  if (!items.length) { $("promos-out").innerHTML = '<div class="empty"><span class="big">🔍</span>Промокодов нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Код</th><th>Скидка</th><th>Использовано</th><th>Истекает</th><th>Статус</th></tr></thead><tbody>';
  items.forEach(function(it){
    const used = (it.uses || 0) + (it.max_uses ? " / " + it.max_uses : "");
    let st;
    if (!it.active) st = statusPill("disabled", "Выключен");
    else if (it.max_uses && (it.uses || 0) >= it.max_uses) st = statusPill("warning", "Исчерпан");
    else if (it.expires_at && !isNaN(new Date(it.expires_at).getTime()) && new Date(it.expires_at).getTime() < Date.now()) st = statusPill("warning", "Истёк");
    else st = statusPill("active", "Активен");
    h += '<tr data-promo-code="' + esc(it.code) + '"><td><span class="mono">' + esc(it.code) + '</span></td><td class="num">' + (it.percent || 0) + '%</td><td class="num">' + used + '</td><td><span class="mono">' + fmtDate(it.expires_at) + '</span></td><td>' + st + '</td></tr>';
  });
  $("promos-out").innerHTML = h + '</tbody></table></div>';
  $("promos-out").querySelectorAll("tr[data-promo-code]").forEach(function(tr){
    tr.onclick = function(){ openPromoEditor(tr.dataset.promoCode); };
  });
}
$("btn-promos").onclick = function(){ loadPromos(); };
document.querySelector('[data-nav="promos"]').addEventListener("click", function(){
  if (!promosLoaded) { promosLoaded = true; loadPromos(); }
  loadGiveMeta();
});
function promoReward(){
  return {kind: $("pr-kind").value, value: parseInt($("pr-value").value || "0", 10)};
}
$("btn-pr-add").onclick = withSpin($("btn-pr-add"), async function(){
  const rw = promoReward();
  if (!rw.value) { toast("Укажи размер награды (скидку % или дни)", "err"); return; }
  const body = {code: $("pr-code").value.trim(), kind: rw.kind, value: rw.value};
  const mx = parseInt($("pr-max").value || "0", 10); if (mx > 0) body.max_uses = mx;
  if ($("pr-first").checked) body.first_only = true;
  const exp = $("pr-exp").value.trim(); if (exp) body.expires_at = exp;
  const owner = $("pr-owner").value.trim(); if (owner) body.owner_tg_id = parseInt(owner, 10);
  const note = $("pr-note").value.trim(); if (note) body.note = note;
  const r = await api("/promos", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
  if (r.status === 200) { toast("Промокод создан", "ok"); loadPromos(); }
  else renderOut("promos-out", r.data);
});
$("btn-pr-find").onclick = function(){
  const code = $("pr-code").value.trim();
  if (code) openPromoEditor(code);
};
$("btn-pr-batch").onclick = withSpin($("btn-pr-batch"), async function(){
  const rw = promoReward();
  if (!rw.value) { toast("Укажи размер награды (скидку % или дни)", "err"); return; }
  const r = await api("/promos/batch", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({count: parseInt($("pr-count").value || "10", 10), kind: rw.kind, value: rw.value})});
  if (r.status === 200) { toast("Пачка промокодов создана", "ok"); loadPromos(); }
  else renderOut("promos-out", r.data);
});
/* --- Промокоды: выдача личного кода и раздача сегменту --- */
/* Паритет с ТГ (features/promos.py handle_promo_give_*, handle_promo_seg_*):
   те же пресеты награды, та же своя величина («35» — скидка, «10 дней» —
   дни), тот же confirm-гейт перед выдачей. */
let giveMeta = null, givePicker = null, segPicker = null;
function parseCustomReward(raw){
  const low = (raw || "").trim().toLowerCase();
  const digits = low.replace(/[^0-9]/g, "");
  if (!digits) return null;
  const value = parseInt(digits, 10);
  const kind = (low.indexOf("дн") !== -1 || low.indexOf("day") !== -1) ? "days" : "percent";
  if (kind === "percent" && (value < 1 || value > 100)) return null;
  if (kind === "days" && (value < 1 || value > 365)) return null;
  return {kind: kind, value: value};
}
function makeRewardPicker(boxId, customId, presets){
  const box = $(boxId);
  let sel = null;
  box.innerHTML = presets.map(function(p, i){
    const label = p.kind === "days" ? "+" + p.value + " дн." : "−" + p.value + "%";
    return '<button type="button" class="ghost" data-rw-idx="' + i + '">' + label + "</button>";
  }).join("");
  box.querySelectorAll("button[data-rw-idx]").forEach(function(b){
    b.onclick = function(){
      sel = presets[parseInt(b.dataset.rwIdx, 10)];
      $(customId).value = "";
      box.querySelectorAll("button").forEach(function(x){ x.className = "ghost"; });
      b.className = "";
    };
  });
  return {get: function(){
    const custom = $(customId).value.trim();
    if (custom) return parseCustomReward(custom);
    return sel;
  }};
}
async function loadGiveMeta(){
  if (giveMeta) return giveMeta;
  let r;
  try { r = await api("/promos/give"); }
  catch(e) { return null; }
  if (r.status !== 200) return null;
  giveMeta = r.data;
  $("seg-select").innerHTML = (giveMeta.segments || []).map(function(s){
    return '<option value="' + esc(s.key) + '">' + esc(s.label) + " · " + s.recipients + "</option>";
  }).join("");
  givePicker = makeRewardPicker("give-presets", "give-custom", giveMeta.presets || []);
  segPicker = makeRewardPicker("seg-presets", "seg-custom", giveMeta.presets || []);
  return giveMeta;
}
$("btn-give").onclick = withSpin($("btn-give"), async function(){
  const target = $("give-target").value.trim();
  if (!target) { toast("Укажи TG ID или @username", "err"); return; }
  if (!givePicker) await loadGiveMeta();
  const rw = givePicker ? givePicker.get() : null;
  if (!rw) { toast("Выбери награду или укажи свою величину", "err"); return; }
  const r = await postConfirm("/promos/give", {target: target, kind: rw.kind, value: rw.value});
  if (r.status === 200) {
    let msg = "✅ Промокод <span class=\\"mono\\">" + esc(r.data.code || "") + "</span> выдан";
    if (!r.data.delivered) msg += "<br>⚠️ Сообщение не доставлено — возможно, бот заблокирован";
    $("give-out").innerHTML = "<p>" + msg + "</p>";
    toast("Промокод выдан", "ok");
  } else if (r.status !== 0) {
    renderOut("give-out", r.data);
  }
});
$("btn-seg").onclick = withSpin($("btn-seg"), async function(){
  if (!segPicker) await loadGiveMeta();
  const rw = segPicker ? segPicker.get() : null;
  if (!rw) { toast("Выбери награду или укажи свою величину", "err"); return; }
  const r = await postConfirm("/promos/segment", {segment: $("seg-select").value, kind: rw.kind, value: rw.value});
  if (r.status === 200) {
    $("seg-out").innerHTML = "<p>✅ Раздача закончена: доставлено <b>" + r.data.sent + "</b>"
      + (r.data.failed ? ", не дошло <b>" + r.data.failed + "</b>" : "")
      + (r.data.skipped ? ", пропущено <b>" + r.data.skipped + "</b>" : "") + "</p>";
    toast("Промокоды розданы", "ok");
  } else if (r.status !== 0) {
    renderOut("seg-out", r.data);
  }
});
/* Паритет с ТГ (features/promos.py handle_promo_income,
   handle_promo_clean/_do): та же сводка раздела и те же итоги по кодам,
   чистка мёртвых — с подтверждением. */
async function loadPromoIncome(){
  let r;
  try { r = await api("/promos/income"); }
  catch(e) { $("promo-income-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("promo-income-out", r.data); return; }
  const d = r.data, st = d.stats || {};
  let h = '<dl class="kv">'
    + kvRow("🎫 Всего кодов", fmtNum(st.total))
    + kvRow("🟢 Активных", fmtNum(st.active))
    + kvRow("🎯 Личных", fmtNum(st.personal))
    + kvRow("🙋 Применений", fmtNum(st.uses))
    + kvRow("Применений за 30 дней", fmtNum(st.uses_30d))
    + kvRow("💰 Оплат с кодом", fmtNum(st.pays) + " на " + fmtMoney(st.revenue))
    + "</dl>";
  const items = d.items || [];
  if (!items.length) {
    h += '<p class="mut">Пока ни одного применения.</p>';
  } else {
    h += '<div class="tblwrap"><table><thead><tr><th>Код</th><th>Награда</th><th class="num">Применён</th><th class="num">Оплат</th><th class="num">Сумма</th></tr></thead><tbody>';
    items.forEach(function(it){
      h += '<tr><td><span class="mono">' + esc(it.code) + '</span></td><td>' + esc(it.reward) + '</td><td class="num">' + fmtNum(it.uses) + '</td><td class="num">' + fmtNum(it.pays) + '</td><td class="num">' + fmtMoney(it.amount) + "</td></tr>";
    });
    h += "</tbody></table></div>";
    if (d.total_pays) h += "<p>💰 Итого с промокодами: <b>" + fmtNum(d.total_pays) + "</b> оплат на <b>" + fmtMoney(d.total_sum) + "</b></p>";
  }
  const dead = d.dead_count || 0;
  h += '<p class="mut">🧹 Мёртвых кодов без применений: <b>' + fmtNum(dead) + "</b> — выключенные и просроченные, которыми ни разу не воспользовались.</p>";
  h += '<div class="btnrow"><button id="btn-promo-clean"' + (dead ? "" : " disabled") + ">🧹 Убрать мёртвые</button></div>";
  $("promo-income-out").innerHTML = h;
  const cleanBtn = $("btn-promo-clean");
  if (cleanBtn) cleanBtn.onclick = withSpin(cleanBtn, async function(){
    const r2 = await postConfirm("/promos/clean", {});
    if (r2.status === 200) {
      toast("Убрано кодов: " + r2.data.removed, "ok");
      loadPromoIncome();
      if (promosLoaded) loadPromos();
    } else if (r2.status !== 0) {
      renderOut("promo-income-out", r2.data);
    }
  });
}
$("btn-promo-income").onclick = withSpin($("btn-promo-income"), loadPromoIncome);
async function openPromoEditor(code){
  code = (code || "").toUpperCase();
  $("drawer-title").textContent = "Промокод " + code;
  $("drawer-sub").textContent = "Загрузка…";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:18px;width:50%;margin-bottom:10px"></div><div class="skel" style="height:120px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  let r;
  try { r = await api("/promos/" + encodeURIComponent(code)); }
  catch(e) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить промокод</p>'; return; }
  if (r.status !== 200) { $("drawer-body").innerHTML = '<p class="err">Промокод не найден</p>'; return; }
  const p = r.data.promo || {};
  $("drawer-sub").textContent = "использований: " + (r.data.uses || 0) + (r.data.income ? " · доход " + fmtMoney(r.data.income) : "");
  let h = '<dl class="kv">';
  h += kvRow("Код", '<span class="mono">' + esc(p.code || "") + '</span>');
  h += kvRow("Скидка", (p.percent || 0) + "%");
  h += kvRow("Тип", esc(p.kind || ""));
  h += kvRow("Дней подписки", p.days == null ? "—" : p.days);
  h += kvRow("Активен", statusPill(p.active ? "active" : "disabled", p.active ? "Активен" : "Выключен"));
  h += kvRow("Использований", (r.data.uses || 0) + (p.max_uses ? " / " + p.max_uses : ""));
  h += kvRow("Истекает", '<span class="mono">' + fmtDate(p.expires_at) + '</span>');
  h += kvRow("Создан", '<span class="mono">' + fmtDate(p.created_at) + '</span>');
  h += kvRow("Владелец", p.owner_tg_id ? '<span class="mono">#' + p.owner_tg_id + '</span>' : "—");
  h += kvRow("Только для новых", p.first_only ? "да" : "нет");
  h += kvRow("Заметка", esc(p.note || "—"));
  h += kvRow("Источник", esc(p.source || "—"));
  h += '</dl>';
  h += '<h3>Изменить</h3>';
  h += '<label>Истекает<input id="ed-pr-exp" placeholder="напр. 2026-12-31 (пусто — без срока)" value="' + esc(p.expires_at || "") + '"></label>';
  h += '<label>Макс. использований<input id="ed-pr-max" type="number" value="' + (p.max_uses == null ? "" : p.max_uses) + '"></label>';
  h += '<label>Только для новых<select id="ed-pr-first"><option value="1"' + (p.first_only ? " selected" : "") + '>да</option><option value="0"' + (p.first_only ? "" : " selected") + '>нет</option></select></label>';
  h += '<label>Заметка<input id="ed-pr-note" value="' + esc(p.note || "") + '"></label>';
  h += '<div class="btnrow"><button class="ghost" id="ed-pr-save">Сохранить</button></div>';
  if ((r.data.users || []).length) {
    h += '<h3>Кто использовал</h3><div class="tblwrap"><table><thead><tr><th>Пользователь</th><th>Когда</th><th>Оплатил</th></tr></thead><tbody>';
    r.data.users.forEach(function(u){
      h += '<tr><td>' + esc(u.first_name || "—") + (u.username ? ' <span class="mut">@' + esc(u.username) + '</span>' : "") + ' <span class="mono small">#' + u.tg_id + '</span></td><td><span class="mono">' + fmtDate(u.used_at) + '</span></td><td class="num">' + fmtMoney(u.paid) + '</td></tr>';
    });
    h += '</tbody></table></div>';
  }
  h += '<p class="mut" id="ed-pr-msg" style="margin-top:10px"></p>';
  $("drawer-body").innerHTML = h;
  $("drawer-foot").innerHTML = '<button class="ghost" id="ed-pr-toggle">Вкл / выкл</button><button class="danger" id="ed-pr-del">Удалить</button>';
  $("ed-pr-save").onclick = withSpin($("ed-pr-save"), async function(){
    const body = {};
    const exp = $("ed-pr-exp").value.trim(); body.expires_at = exp === "" ? null : exp;
    const mx = $("ed-pr-max").value.trim(); body.max_uses = mx === "" ? null : parseInt(mx, 10);
    body.first_only = $("ed-pr-first").value === "1";
    body.note = $("ed-pr-note").value;
    const rr = await api("/promos/" + encodeURIComponent(code), {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
    const msg = $("ed-pr-msg");
    if (msg) msg.textContent = rr.status === 200 ? "Готово" : ("Ошибка: " + (rr.data.error || rr.status));
    if (rr.status === 200) { toast("Промокод обновлён", "ok"); openPromoEditor(code); loadPromos(); }
  });
  $("ed-pr-toggle").onclick = withSpin($("ed-pr-toggle"), async function(){
    const rr = await api("/promos/" + encodeURIComponent(code) + "/toggle", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({})});
    if (rr.status === 200) { toast("Промокод переключён", "ok"); openPromoEditor(code); loadPromos(); }
  });
  $("ed-pr-del").onclick = withSpin($("ed-pr-del"), async function(){
    const rr = await postConfirmAny("/promos/" + encodeURIComponent(code), "DELETE", {});
    if (rr.status === 200) { toast("Промокод удалён", "ok"); closeDrawer(); loadPromos(); }
    else { const msg = $("ed-pr-msg"); if (msg) msg.textContent = "Ошибка: " + (rr.data.error || rr.status); }
  });
}
/* --- Тарифы: список + редактор --- */
let tariffsLoaded = false;
async function loadTariffs(){
  let r;
  try { r = await api("/tariffs"); }
  catch(e) { $("tariffs-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("tariffs-out", r.data); return; }
  const items = r.data.tariffs || [];
  if (!items.length) { $("tariffs-out").innerHTML = '<div class="empty"><span class="big">🔍</span>Тарифов нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Название</th><th>Срок</th><th>Цена</th><th>Активен</th><th>Порядок</th></tr></thead><tbody>';
  items.forEach(function(it){
    h += '<tr data-tid="' + it.id + '"><td>' + esc(it.name) + '</td><td>' + fmtDays(it.period_seconds) + '</td><td class="num">' + fmtMoney(it.price) + '</td><td>' + statusPill(it.active ? "active" : "disabled", it.active ? "Активен" : "Выключен") + '</td><td class="num">' + (it.sort_order || 0) + '</td></tr>';
  });
  $("tariffs-out").innerHTML = h + '</tbody></table></div>';
  $("tariffs-out").querySelectorAll("tr[data-tid]").forEach(function(tr){
    tr.onclick = function(){ openTariffEditor(parseInt(tr.dataset.tid, 10)); };
  });
}
$("btn-tariffs").onclick = function(){ loadTariffs(); };
$("btn-tariff-add").onclick = function(){ openTariffEditor(null); };
document.querySelector('[data-nav="tariffs"]').addEventListener("click", function(){
  if (!tariffsLoaded) { tariffsLoaded = true; loadTariffs(); }
});
async function openTariffEditor(tid){
  if (tid == null) {
    $("drawer-title").textContent = "Новый тариф";
    $("drawer-sub").textContent = "Появится у клиентов после сохранения";
    $("drawer-body").innerHTML = '<label>Название<input id="ed-tf-name" placeholder="напр. 1 месяц"></label>' +
      '<label>Срок, секунды (2592000 = 30 дней)<input id="ed-tf-seconds" type="number" placeholder="2592000"></label>' +
      '<label>Цена, ₽<input id="ed-tf-price" type="number" placeholder="299"></label>' +
      '<p class="mut" id="ed-tf-msg" style="margin-top:10px"></p>';
    $("drawer-foot").innerHTML = '<button id="ed-tf-create">Создать тариф</button>';
    openDrawer();
    $("ed-tf-create").onclick = withSpin($("ed-tf-create"), async function(){
      const rr = await api("/tariffs", {method: "POST", headers: {"X-CSRF-Token": csrf()},
        body: JSON.stringify({name: $("ed-tf-name").value, period_seconds: parseInt($("ed-tf-seconds").value || "0", 10), price: parseInt($("ed-tf-price").value || "0", 10)})});
      const msg = $("ed-tf-msg");
      if (msg) msg.textContent = rr.status === 200 ? "Готово" : ("Ошибка: " + (rr.data.error || rr.status));
      if (rr.status === 200) { toast("Тариф создан", "ok"); closeDrawer(); loadTariffs(); }
    });
    return;
  }
  $("drawer-title").textContent = "Тариф #" + tid;
  $("drawer-sub").textContent = "Загрузка…";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:18px;width:50%;margin-bottom:10px"></div><div class="skel" style="height:120px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  let r;
  try { r = await api("/tariffs/" + tid); }
  catch(e) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить тариф</p>'; return; }
  if (r.status !== 200) { $("drawer-body").innerHTML = '<p class="err">Тариф не найден</p>'; return; }
  const t = r.data.tariff || {};
  $("drawer-sub").textContent = t.name || "";
  let h = '<dl class="kv">';
  h += kvRow("ID", '<span class="mono">' + t.id + '</span>');
  h += kvRow("Активен", statusPill(t.active ? "active" : "disabled", t.active ? "Активен" : "Выключен"));
  h += '</dl>';
  h += '<h3>Изменить</h3>';
  h += '<label>Название<input id="ed-tf-name" value="' + esc(t.name || "") + '"></label>';
  h += '<label>Срок, секунды<input id="ed-tf-seconds" type="number" value="' + (t.period_seconds || 0) + '"></label>';
  h += '<label>Цена, ₽<input id="ed-tf-price" type="number" value="' + (t.price || 0) + '"></label>';
  h += '<label>Порядок<input id="ed-tf-sort" type="number" value="' + (t.sort_order || 0) + '"></label>';
  h += '<label>Активен<select id="ed-tf-active"><option value="1"' + (t.active ? " selected" : "") + '>да</option><option value="0"' + (t.active ? "" : " selected") + '>нет</option></select></label>';
  h += '<div class="btnrow"><button class="ghost" id="ed-tf-save">Сохранить</button></div>';
  h += '<p class="mut" id="ed-tf-msg" style="margin-top:10px"></p>';
  $("drawer-body").innerHTML = h;
  $("drawer-foot").innerHTML = '<button class="danger" id="ed-tf-del">Удалить тариф</button>';
  $("ed-tf-save").onclick = withSpin($("ed-tf-save"), async function(){
    const body = {
      name: $("ed-tf-name").value,
      period_seconds: parseInt($("ed-tf-seconds").value || "0", 10),
      price: parseInt($("ed-tf-price").value || "0", 10),
      sort_order: parseInt($("ed-tf-sort").value || "0", 10),
      active: $("ed-tf-active").value === "1",
    };
    const rr = await api("/tariffs/" + tid, {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
    const msg = $("ed-tf-msg");
    if (msg) msg.textContent = rr.status === 200 ? "Готово" : ("Ошибка: " + (rr.data.error || rr.status));
    if (rr.status === 200) { toast("Тариф обновлён", "ok"); openTariffEditor(tid); loadTariffs(); }
  });
  $("ed-tf-del").onclick = withSpin($("ed-tf-del"), async function(){
    const rr = await postConfirmAny("/tariffs/" + tid, "DELETE", {});
    if (rr.status === 200) { toast("Тариф удалён", "ok"); closeDrawer(); loadTariffs(); }
    else { const msg = $("ed-tf-msg"); if (msg) msg.textContent = "Ошибка: " + (rr.data.error || rr.status); }
  });
}

/* --- Панель Remnawave и узлы --- */
let panelLoaded = false;
async function loadPanel(){
  let r;
  try { r = await api("/panel"); }
  catch(e) { $("profiles-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("profiles-table", r.data); return; }
  const profiles = r.data.profiles || [];
  if (!profiles.length) { $("profiles-table").innerHTML = r.data.profiles_ok === false ? '<p class="err">Панель недоступна — список профилей не получен. Попробуйте «Обновить списки».</p>' : '<div class="empty">Профилей нет</div>'; }
  else {
    let h = '<div class="tblwrap"><table><thead><tr><th>Профиль</th><th>UUID</th><th>Инбаунды</th></tr></thead><tbody>';
    profiles.forEach(function(p){
      const stub = (p.name === "None" || p.name === "None-Bridge") ? ' <span class="pill warn">служебный</span>' : "";
      h += '<tr data-uuid="' + esc(p.uuid) + '"><td>' + esc(p.name || "") + stub + '</td><td class="mono">' + esc(String(p.uuid).slice(0, 8)) + '…</td><td>' + (p.inbounds || []).map(function(ib){ return esc(ib.tag || ""); }).join(", ") + '</td></tr>';
    });
    h += '</tbody></table></div>';
    $("profiles-table").innerHTML = h;
    $("profiles-table").querySelectorAll("tr[data-uuid]").forEach(function(tr){
      tr.onclick = function(){ $("pf-uuid").value = tr.dataset.uuid; loadProfile(); $("panel-profile-card").scrollIntoView(); };
    });
  }
  let rh;
  try { rh = await api("/panel/hosts"); }
  catch(e) { $("hosts-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (rh.status !== 200) { renderOut("hosts-table", rh.data); return; }
  const hosts = rh.data.hosts || [];
  if (!hosts.length) { $("hosts-table").innerHTML = '<div class="empty">Хостов нет</div>'; }
  else {
    let h2 = '<div class="tblwrap"><table><thead><tr><th>Хост</th><th>Адрес</th><th>Порт</th><th>Вкл</th></tr></thead><tbody>';
    hosts.forEach(function(x){
      const stub = (x.port === 1234 || x.address === "12345");
      const marks = (stub ? ' <span class="pill warn">служебный</span>' : "") + (x.isHidden ? ' <span class="pill info">скрыт</span>' : "");
      h2 += '<tr data-uuid="' + esc(x.uuid) + '" data-disabled="' + (x.isDisabled ? "true" : "false") + '"><td>' + esc(x.remark || "") + marks + '</td><td class="mono">' + (stub ? "—" : esc(x.address || "")) + '</td><td class="num">' + (stub || x.port == null ? "—" : x.port) + '</td><td>' + statusPill(x.isDisabled ? "disabled" : "enabled", x.isDisabled ? "Выключен" : "Включён") + '</td></tr>';
    });
    h2 += '</tbody></table></div>';
    $("hosts-table").innerHTML = h2;
    $("hosts-table").querySelectorAll("tr[data-uuid]").forEach(function(tr){
      tr.onclick = function(){ $("ph-uuid").value = tr.dataset.uuid; $("ph-disabled").value = tr.dataset.disabled; $("panel-hosts-card").scrollIntoView(); };
    });
  }
}
$("btn-panel").onclick = loadPanel;
document.querySelector('[data-nav="panel"]').addEventListener("click", function(){
  if (!panelLoaded) { panelLoaded = true; loadPanel(); loadTags(); }
});
/* --- Теги подписчиков в панели --- */
const TAG_ORDER = ["BANNED", "TRIAL", "PAID", "ADMIN", "EXPIRED"];
async function loadTags(){
  let r;
  try { r = await api("/panel/tags"); }
  catch(e) { $("tags-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("tags-table", r.data); return; }
  const counts = r.data.counts || {}, labels = r.data.labels || {};
  let h = '<div class="tblwrap"><table><thead><tr><th>Тег</th><th class="num">Людей</th></tr></thead><tbody>';
  TAG_ORDER.forEach(function(t){
    h += '<tr><td>' + esc(labels[t] || t) + '</td><td class="num">' + (counts[t] == null ? "—" : counts[t]) + '</td></tr>';
  });
  h += '<tr><td><b>Всего</b></td><td class="num"><b>' + (counts.total == null ? "—" : counts.total) + '</b></td></tr>';
  h += '</tbody></table></div>';
  $("tags-table").innerHTML = h;
}
$("btn-tags").onclick = loadTags;
$("btn-tags-apply").onclick = withSpin($("btn-tags-apply"), async function(){
  const r = await postConfirm("/panel/tags/apply", {});
  if (r.status !== 200) { renderOut("tags-out", r.data); return; }
  const rep = r.data.report || {}, counts = rep.counts || {};
  let h = '<div class="tblwrap"><table><thead><tr><th>Итог прогона</th><th class="num"></th></tr></thead><tbody>';
  h += '<tr><td>Обработано людей</td><td class="num">' + (rep.people == null ? "—" : rep.people) + '</td></tr>';
  TAG_ORDER.forEach(function(t){
    h += '<tr><td>' + esc(t) + '</td><td class="num">' + (counts[t] == null ? "—" : counts[t]) + '</td></tr>';
  });
  h += '<tr><td>Клиентов обновлено</td><td class="num">' + (rep.updated == null ? "—" : rep.updated) + '</td></tr>';
  h += '<tr><td>Без изменений</td><td class="num">' + (rep.unchanged == null ? "—" : rep.unchanged) + '</td></tr>';
  h += '<tr><td>Ошибок</td><td class="num">' + (rep.errors == null ? "—" : rep.errors) + '</td></tr>';
  h += '</tbody></table></div>';
  if (rep.error_samples && rep.error_samples.length) {
    h += '<p class="err">Первые ошибки: ' + esc(rep.error_samples.join("; ")) + '</p>';
  }
  $("tags-out").innerHTML = h;
  toast("Теги применены", "ok");
  loadTags();
});
$("btn-yandex").onclick = async function(){ const r = await api("/yandex"); renderOut("panel-out", r.data); };
/* --- Основные ссылки: справка по адресам проекта ---
   Адреса подтягиваются сами: панель и сайт — из конфига бота, домены
   подписки — из констант, ноды и хосты — живьём из панели Remnawave.
   Поля можно подкорректировать: правка перекрывает авто-значение и
   хранится в config.main_links; значение, равное авто, правкой не
   считается и не сохраняется. */
async function openLinksDrawer(){
  $("drawer-title").textContent = "Основные ссылки";
  $("drawer-sub").textContent = "Адреса панели, подписок и серверов";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:18px;width:50%;margin-bottom:10px"></div><div class="skel" style="height:160px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  const rl = await api("/links");
  if (rl.status !== 200) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить ссылки</p>'; return; }
  const auto = rl.data.auto || {}, ov = rl.data.overrides || {};
  const eff = function(k){ return (ov[k] || "").trim() || auto[k] || ""; };
  const FIELDS = [
    ["panel_url", "Панель Remnawave", "https://…"],
    ["site_url", "Сайт и кабинет", "https://…"],
    ["key_domain", "Подписка — основной домен (origin)", "домен, напр. key.drbl.tech"],
    ["sub_domain", "Подписка — через CDN", "домен, напр. sub.drbl.tech"]];
  let h = '<p class="sub">Значения определены автоматически. Если что-то переехало — поправь здесь: правка перекрывает авто-значение, пустое поле возвращает авто.</p>';
  FIELDS.forEach(function(f){
    const k = f[0], val = eff(k);
    const shown = (k === "key_domain" || k === "sub_domain") && val && val.indexOf("://") < 0 ? "https://" + val : val;
    h += '<label>' + f[1] + '<input id="ml-' + k + '" value="' + esc(val) + '" placeholder="' + esc(f[2]) + '"></label>';
    h += '<div class="sublink" style="margin:4px 0 10px"><span class="mono small">' + esc(shown || "—") + '</span>'
      + (shown ? '<button class="ghost" data-copy="' + esc(shown) + '">Копировать</button><a class="ghost btnlike" href="' + esc(shown) + '" target="_blank" rel="noopener">Открыть</a>' : "")
      + (ov[k] ? ' <span class="pill warn">правка</span>' : ' <span class="pill info">авто</span>') + "</div>";
  });
  h += '<div class="btnrow"><button id="ml-save">Сохранить правки</button></div><div id="ml-out"></div>';
  const rp = await api("/panel");
  let nodes = (rp.status === 200 && rp.data && rp.data.nodes) || [];
  if (nodes && !Array.isArray(nodes)) nodes = nodes.nodes || nodes.response || [];
  h += '<h3>Ноды (из панели)</h3>';
  if (nodes.length) {
    h += '<div class="tblwrap"><table><thead><tr><th>Нода</th><th>Адрес</th><th>Статус</th><th>Онлайн</th></tr></thead><tbody>';
    nodes.forEach(function(n){
      const alive = n.isConnected && n.isXrayRunning !== false;
      h += '<tr><td>' + esc(n.name || "") + '</td><td class="mono">' + esc(n.address || "") + '</td><td>' + statusPill(n.isDisabled ? "disabled" : alive ? "online" : "offline", n.isDisabled ? "Выключена" : alive ? "Онлайн" : "Офлайн") + '</td><td class="num">' + (n.usersOnline == null ? "—" : n.usersOnline) + "</td></tr>";
    });
    h += "</tbody></table></div>";
  } else h += '<p class="mut">Панель не ответила — список нод недоступен.</p>';
  const rh = await api("/panel/hosts");
  const hosts = (rh.status === 200 && rh.data && rh.data.hosts) || [];
  h += '<h3>Хосты подписки (из панели)</h3>';
  if (hosts.length) {
    h += '<div class="tblwrap"><table><thead><tr><th>Хост</th><th>Адрес:порт</th><th>SNI</th><th>Статус</th></tr></thead><tbody>';
    hosts.forEach(function(x){
      const stub = (x.port === 1234 || x.address === "12345");
      const marks = (stub ? ' <span class="pill warn">служебный</span>' : "") + (x.isHidden ? ' <span class="pill info">скрыт</span>' : "");
      h += '<tr><td>' + esc(x.remark || "") + marks + '</td><td class="mono">' + (stub ? "—" : esc(x.address || "") + ":" + (x.port == null ? "—" : x.port)) + '</td><td class="mono">' + esc(x.sni || x.serverName || "") + '</td><td>' + statusPill(x.isDisabled ? "disabled" : "enabled", x.isDisabled ? "Выключен" : "Включён") + "</td></tr>";
    });
    h += "</tbody></table></div>";
  } else h += '<p class="mut">Панель не ответила — список хостов недоступен.</p>';
  $("drawer-body").innerHTML = h;
  $("drawer-body").querySelectorAll("[data-copy]").forEach(function(b){
    b.onclick = function(){
      if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(function(){ toast("Скопировано", "ok"); });
    };
  });
  $("ml-save").onclick = withSpin($("ml-save"), async function(){
    const body = {};
    FIELDS.forEach(function(f){
      const k = f[0], v = $("ml-" + k).value.trim();
      body[k] = (v === (auto[k] || "")) ? "" : v;
    });
    const r = await api("/links", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
    if (r.status === 200) { toast("Ссылки сохранены", "ok"); openLinksDrawer(); }
    else toast("Ошибка: " + ((r.data && r.data.error) || r.status), "err");
  });
}
$("btn-links-panel").onclick = openLinksDrawer;
$("btn-links-nodes").onclick = openLinksDrawer;
async function loadProfile(){
  const r = await api("/panel/profiles/" + $("pf-uuid").value);
  renderOut("pf-out", r.data);
}
$("btn-pf-load").onclick = loadProfile;
$("btn-pf-save").onclick = async function(){
  const uuid = $("pf-uuid").value, tag = $("pf-tag").value;
  const body = {};
  const port = $("pf-port").value;
  if (port) body.port = parseInt(port, 10);
  const sni = $("pf-sni").value.trim();
  if (sni) body.serverNames = sni.split(",").map(function(s){ return s.trim(); }).filter(Boolean);
  const dest = $("pf-dest").value.trim();
  if (dest) body.dest = dest;
  const fp = $("pf-fp").value.trim();
  if (fp) body.fingerprint = fp;
  const r = await postConfirmAny("/panel/profiles/" + uuid + "/inbounds/" + encodeURIComponent(tag), "PATCH", body);
  renderOut("pf-out", r.data);
};
$("btn-ph-create").onclick = async function(){
  const r = await postConfirm("/panel/hosts", {inboundUuid: $("ph-inbound").value,
    remark: $("ph-remark").value, address: $("ph-addr").value,
    port: parseInt($("ph-port").value || "0", 10), sni: $("ph-sni").value});
  renderOut("ph-out", r.data);
  if (r.status === 200) loadPanel();
};
$("btn-ph-toggle").onclick = async function(){
  const uuid = $("ph-uuid").value;
  const r = await postConfirmAny("/panel/hosts/" + uuid, "PATCH", {isDisabled: $("ph-disabled").value === "true"});
  renderOut("ph-out", r.data);
  if (r.status === 200) loadPanel();
};
$("btn-ph-del").onclick = async function(){
  const uuid = $("ph-uuid").value;
  const r = await postConfirmAny("/panel/hosts/" + uuid, "DELETE", {});
  renderOut("ph-out", r.data);
  if (r.status === 200) loadPanel();
};
$("btn-ps-show").onclick = async function(){ const r = await api("/panel/settings"); renderOut("ps-out", r.data); };
$("btn-ps-save").onclick = async function(){
  const r = await api("/panel/settings", {method: "PATCH", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({rw_url: $("ps-url").value})});
  renderOut("ps-out", r.data);
};
$("btn-ps-test").onclick = async function(){
  const r = await api("/panel/settings/test", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({})});
  renderOut("ps-out", r.data);
};
let nodesLoaded = false;
async function loadNodes(){
  let r;
  try { r = await api("/panel"); }
  catch(e) { $("nodes-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("nodes-table", r.data); return; }
  let nodes = r.data.nodes || [];
  if (nodes && !Array.isArray(nodes)) nodes = nodes.nodes || nodes.response || [];
  if (!nodes.length) { $("nodes-table").innerHTML = '<div class="empty">Нод нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Нода</th><th>Адрес</th><th>Статус</th><th>Онлайн</th></tr></thead><tbody>';
  nodes.forEach(function(n){
    const alive = n.isConnected && n.isXrayRunning !== false;
    const st = n.isDisabled ? "Выключена" : alive ? "Онлайн" : "Офлайн";
    h += '<tr data-uuid="' + esc(n.uuid || "") + '" data-name="' + esc(n.name || n.address || "") + '"><td>' + esc(n.name || n.address || "") + '</td><td class="mono">' + esc(n.address || "") + '</td><td>' + statusPill(n.isDisabled ? "disabled" : alive ? "online" : "offline", st) + '</td><td class="num">' + (n.usersOnline == null ? "—" : n.usersOnline) + '</td></tr>';
  });
  h += '</tbody></table></div>';
  $("nodes-table").innerHTML = h;
  $("nodes-table").querySelectorAll("tr[data-uuid]").forEach(function(tr){
    tr.onclick = function(){ usageNode = tr.dataset.uuid; usageNodeName = tr.dataset.name || tr.dataset.uuid; loadUsage(1); };
  });
}
document.querySelector('[data-nav="nodes"]').addEventListener("click", function(){
  if (!nodesLoaded) {
    nodesLoaded = true;
    $("nodes-table").innerHTML = '<div class="skel" style="height:120px"></div>';
    $("nodes-out").innerHTML = '<div class="skel" style="height:80px"></div>';
    loadNodes(); $("btn-nodes").click();
    renderUsagePeriods(); loadSnapshot(); loadUsage(1);
  }
});
async function loadHealth(){
  const r = await api("/nodes");
  if (r.status !== 200) { renderOut("nodes-out", r.data); return; }
  const sv = r.data.servers || {}, sites = r.data.sites || {};
  let h = '<h3>Сервисы</h3><div class="tblwrap"><table><thead><tr><th>Сервис</th><th>Статус</th><th>Отклик</th><th>Ошибка</th></tr></thead><tbody>';
  if (sv.panel) h += '<tr><td>Панель Remnawave <span class="mono small mut">' + esc(sv.panel.host || "") + '</span></td><td>' + (sv.panel.ok ? '<span class="pill ok">Работает</span>' : '<span class="pill bad">Недоступна</span>') + '</td><td class="num">' + (sv.panel.ms != null ? sv.panel.ms + " мс" : "—") + '</td><td class="trunc">' + esc(sv.panel.error || "") + "</td></tr>";
  if (sv.sub) h += '<tr><td>Выдача подписок <span class="mono small mut">' + esc(sv.sub.url || "") + '</span></td><td>' + (sv.sub.ok ? '<span class="pill ok">Работает</span>' : '<span class="pill bad">Недоступна</span>') + '</td><td class="num">' + (sv.sub.ms != null ? sv.sub.ms + " мс" : "—") + '</td><td class="trunc">' + esc(sv.sub.error || "") + "</td></tr>";
  h += "</tbody></table></div>";
  const nds = sv.nodes || [];
  if (nds.length) {
    h += '<h3>Ноды по данным панели</h3><div class="tblwrap"><table><thead><tr><th>Нода</th><th>Адрес</th><th>Xray</th><th>Онлайн</th><th>Статус</th></tr></thead><tbody>';
    nds.forEach(function(n){
      h += "<tr><td>" + esc(n.tag || "") + '</td><td class="mono">' + esc(n.host || "") + '</td><td>' + esc(n.xray || "—") + '</td><td class="num">' + (n.clients || 0) + "</td><td>" + (!n.enabled ? '<span class="pill warn">Выключена</span>' : n.reachable ? '<span class="pill ok">Доступна</span>' : '<span class="pill bad">' + esc(n.error || "Недоступна") + "</span>") + "</td></tr>";
    });
    h += "</tbody></table></div>";
  }
  const siteKeys = Object.keys(sites);
  if (siteKeys.length) {
    const SITE_LABELS = {"site:vpn.drbl.tech": "Сайт", "site:key.drbl.tech": "Страница подписки"};
    h += '<h3>Сайты</h3><div class="tblwrap"><table><thead><tr><th>Сайт</th><th>Статус</th><th>Код</th><th>Отклик</th></tr></thead><tbody>';
    siteKeys.forEach(function(k){
      const v = sites[k] || {};
      h += "<tr><td>" + esc(SITE_LABELS[k] || k) + "</td><td>" + (v.ok ? '<span class="pill ok">Жив</span>' : '<span class="pill bad">Лежит' + (v.error ? ": " + esc(v.error) : "") + "</span>") + '</td><td class="num">' + (v.code || "—") + '</td><td class="num">' + (v.ms != null ? v.ms + " мс" : "—") + "</td></tr>";
    });
    h += "</tbody></table></div>";
  }
  $("nodes-out").innerHTML = h;
}
$("btn-nodes").onclick = function(){ loadHealth(); };
async function loadSquads(){
  const r = await api("/squads");
  if (r.status !== 200 || !r.data.ok) { $("nodes-out").innerHTML = '<p class="err">Панель недоступна — сквады не получены</p>'; return; }
  const items = r.data.squads || [];
  if (!items.length) { $("nodes-out").innerHTML = '<div class="empty">Сквадов нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Сквад</th><th>Участников</th><th>Инбаундов</th></tr></thead><tbody>';
  items.forEach(function(sq){
    h += "<tr><td>" + esc(sq.name || "") + '</td><td class="num">' + fmtNum(sq.members || 0) + '</td><td class="num">' + fmtNum(sq.inbounds || 0) + "</td></tr>";
  });
  $("nodes-out").innerHTML = h + "</tbody></table></div>";
}
$("btn-squads").onclick = function(){ loadSquads(); };
/* --- Трафик по узлам: те же периоды и подписи, что в ТГ (handle_rw_usage). --- */
const USAGE_PERIODS = {month: "Текущий месяц", prev: "Прошлый месяц", "7d": "Последние 7 дней", "30d": "Последние 30 дней", "90d": "Последние 90 дней", custom: "Свой период…"};
let usagePeriod = "month", usagePage = 1, usageNode = "all", usageNodeName = "Все ноды";
function fmtGB(b){ if (b == null) return "—"; return (Number(b) / 1073741824).toFixed(2) + " ГБ"; }
function fmtExpire(s){
  if (!s) return "";
  const d = String(s).slice(0, 10).split("-");
  return d.length === 3 ? d[2] + "." + d[1] + "." + d[0] : String(s).slice(0, 10);
}
function usageLabelHTML(l){
  if (!l) return "";
  const head = [l.name, l.tg_username ? "@" + l.tg_username : null].filter(Boolean).join(" ");
  let h = head ? esc(head) + " · " : "";
  h += '<code class="mono">' + esc(l.tg_id != null ? l.tg_id : l.username) + "</code>";
  if (l.in_db && l.expire) h += " · до " + esc(fmtExpire(l.expire));
  if (!l.in_db) h += ' · <i class="mut">нет в базе</i>';
  return h;
}
function renderUsagePeriods(){
  $("usage-period").innerHTML = Object.keys(USAGE_PERIODS).map(function(k){
    return '<button class="ghost' + (k === usagePeriod ? " active" : "") + '" data-usage-period="' + k + '">' + USAGE_PERIODS[k] + "</button>";
  }).join("");
  $("usage-period").querySelectorAll("[data-usage-period]").forEach(function(b){
    b.onclick = function(){
      usagePeriod = b.dataset.usagePeriod;
      show("usage-custom", usagePeriod === "custom");
      renderUsagePeriods();
      if (usagePeriod !== "custom") loadUsage(1);
    };
  });
}
async function loadSnapshot(){
  let r;
  try { r = await api("/nodes/usage/snapshot"); }
  catch(e) { $("nodes-snapshot").innerHTML = '<p class="err">Ошибка загрузки сводки</p>'; return; }
  if (r.status !== 200 || !r.data.ok) { $("nodes-snapshot").innerHTML = '<p class="err">Сводка недоступна</p>'; return; }
  const d = r.data;
  if (!d.snapshot_ok || !d.items.length) { $("nodes-snapshot").innerHTML = '<p class="mut">Сводка за всё время пока недоступна — счётчики панели пусты.</p>'; return; }
  let h = "<h3>За всё время</h3><p>Всего по всем клиентам: <b>" + fmtGB(d.total_bytes) + "</b> · клиентов: <b>" + fmtNum(d.users) + "</b></p><p class=\\"mut small\\">Счётчики панели с последнего сброса.</p>";
  h += '<div class="tblwrap"><table><thead><tr><th>#</th><th>Пользователь</th><th>Трафик</th></tr></thead><tbody>';
  d.items.forEach(function(it, i){
    h += "<tr><td class=\\"num\\">" + (i + 1) + "</td><td>" + usageLabelHTML(it.label) + '</td><td class="num">' + fmtGB(it.bytes) + "</td></tr>";
  });
  $("nodes-snapshot").innerHTML = h + "</tbody></table></div>";
}
async function loadUsage(page){
  usagePage = page || 1;
  let q = "period=" + encodeURIComponent(usagePeriod) + "&page=" + usagePage;
  if (usagePeriod === "custom") {
    const s = $("node-start").value, e = $("node-end").value;
    if (!s || !e) { $("nodes-usage").innerHTML = '<p class="err">Выбери обе даты периода</p>'; return; }
    q += "&start=" + encodeURIComponent(s) + "&end=" + encodeURIComponent(e);
  }
  const path = usageNode === "all" ? "/nodes/usage?" + q : "/nodes/" + encodeURIComponent(usageNode) + "/users?" + q;
  let r;
  try { r = await api(path); }
  catch(e) { $("nodes-usage").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200 || !r.data.ok) { $("nodes-usage").innerHTML = '<p class="err">' + esc((r.data && r.data.error) || "Панель недоступна") + "</p>"; return; }
  const d = r.data;
  let h = "<h3>" + esc(usageNodeName) + ' — <span class="mut">' + esc(d.period || "") + "</span></h3>";
  h += "<p>Всего: <b>" + fmtGB(d.total_bytes) + "</b> · пользователей: <b>" + fmtNum(d.users) + "</b></p>";
  if (!d.items.length) { $("nodes-usage").innerHTML = h + '<div class="empty">За этот период трафика пока нет</div>'; return; }
  h += '<div class="tblwrap"><table><thead><tr><th>#</th><th>Пользователь</th><th>Трафик</th></tr></thead><tbody>';
  d.items.forEach(function(it, i){
    const n = (d.page - 1) * 20 + i + 1;
    h += "<tr><td class=\\"num\\">" + n + "</td><td>" + usageLabelHTML(it.label) + '</td><td class="num">' + fmtGB(it.bytes) + "</td></tr>";
  });
  h += "</tbody></table></div>";
  if (d.total_pages > 1) {
    h += '<div class="btnrow"><button class="ghost" id="usage-prev"' + (d.page <= 1 ? " disabled" : "") + ">◀️</button><span class=\\"mut\\">" + d.page + " / " + d.total_pages + "</span><button class=\\"ghost\\" id=\\"usage-next\\"" + (d.page >= d.total_pages ? " disabled" : "") + ">▶️</button></div>";
  }
  $("nodes-usage").innerHTML = h;
  const prev = $("usage-prev"), next = $("usage-next");
  if (prev) prev.onclick = function(){ loadUsage(d.page - 1); };
  if (next) next.onclick = function(){ loadUsage(d.page + 1); };
}
$("btn-usage-all").onclick = function(){ usageNode = "all"; usageNodeName = "Все ноды"; loadUsage(1); };
$("btn-usage-custom").onclick = function(){ loadUsage(1); };

/* --- Логи, синхронизация, операторы, сайт, бэкап --- */
let logsLoaded = false;
document.querySelector('[data-nav="logs"]').addEventListener("click", function(){
  if (!logsLoaded) { logsLoaded = true; $("btn-logs").click(); }
});
/* Вкладки ленты — те же 6, что FEED_TITLES в handlers/control.py. */
const LOGS_TABS = {all: "📜 Лента действий", important: "⭐ Важные события", admin: "⚙️ Аудит админки", helpers: "👥 Помощники", subs: "💳 История подписок", errors: "🚨 Ошибки"};
let logsScope = "all", logsPage = 1, logsPages = 1;
function logsDates(){
  /* Быстрые даты как LOG_DATE_LABELS в ТГ: today/yesterday/week. */
  const d = $("logs-date").value;
  const now = new Date();
  const iso = function(dt){ return dt.getFullYear() + "-" + String(dt.getMonth() + 1).padStart(2, "0") + "-" + String(dt.getDate()).padStart(2, "0"); };
  if (d === "today") return [iso(now), iso(now)];
  if (d === "yesterday") { const y = new Date(now); y.setDate(y.getDate() - 1); return [iso(y), iso(y)]; }
  if (d === "week") { const w = new Date(now); w.setDate(w.getDate() - 6); return [iso(w), iso(now)]; }
  return [$("logs-from").value.trim(), $("logs-to").value.trim()];
}
function renderLogsTabs(){
  $("logs-tabs").innerHTML = Object.keys(LOGS_TABS).map(function(k){
    return '<button class="ghost' + (k === logsScope ? " active" : "") + '" data-logs-tab="' + k + '">' + LOGS_TABS[k] + "</button>";
  }).join("");
  /* Как в ТГ: фильтры действуют только на вкладках ленты, не на подписках и ошибках. */
  show("logs-filters", logsScope !== "subs" && logsScope !== "errors");
}
function logsParams(forExport){
  const p = [];
  if (!forExport) { p.push("page=" + logsPage); p.push("per_page=25"); }
  if (logsScope === "errors") { p.push("kind=errors"); return p; }
  p.push("kind=activity");
  p.push("scope=" + logsScope);
  if (logsScope === "subs") return p;
  const fk = $("logs-kind-filter").value; if (fk) p.push("filter_kind=" + fk);
  const u = $("logs-user").value.trim(); if (u) p.push("user_id=" + encodeURIComponent(u));
  const df = logsDates();
  if (df[0]) p.push("date_from=" + encodeURIComponent(df[0]));
  if (df[1]) p.push("date_to=" + encodeURIComponent(df[1]));
  return p;
}
async function loadLogs(page){
  logsPage = page || 1;
  renderLogsTabs();
  let r;
  try { r = await api("/logs?" + logsParams(false).join("&")); }
  catch(e) { $("logs-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("logs-out", r.data); return; }
  logsPages = r.data.pages || 1; logsPage = r.data.page || logsPage;
  $("logs-page-label").textContent = "Стр. " + logsPage + " из " + logsPages;
  show("btn-logs-prev", logsPage > 1); show("btn-logs-next", logsPage < logsPages);
  const rows = r.data.rows || [];
  if (!rows.length) { $("logs-out").innerHTML = '<div class="empty">Записей нет</div>'; return; }
  let h;
  if (r.data.kind === "errors") {
    h = '<div class="tblwrap"><table><thead><tr><th>Время (МСК)</th><th>Источник</th><th>Уровень</th><th>Сообщение</th><th>Детали</th></tr></thead><tbody>';
    rows.forEach(function(it){
      h += '<tr data-log-id="' + it.id + '"><td class="mono">' + fmtDate(it.time) + '</td><td>' + esc(it.source || "") + '</td><td>' + pill(it.level || "") + '</td><td>' + esc(it.message || "") + '</td><td class="trunc" title="' + esc(it.details || "") + '">' + esc(it.details || "") + "</td></tr>";
    });
  } else {
    h = '<div class="tblwrap"><table><thead><tr><th>Время (МСК)</th><th>Пользователь</th><th>Действие</th><th>Детали</th></tr></thead><tbody>';
    rows.forEach(function(it){
      const who = it.tg_id ? (esc(it.first_name || "") + (it.username ? ' <span class="mut">@' + esc(it.username) + "</span>" : "") + ' <span class="mono small">#' + it.tg_id + "</span>") : '<span class="mut">система</span>';
      h += '<tr data-log-id="' + it.id + '"><td class="mono">' + fmtDate(it.time) + "</td><td>" + who + '</td><td title="' + esc(it.action || "") + '">' + esc(it.label || it.action || "") + '</td><td class="trunc" title="' + esc(it.details || "") + '">' + esc(it.details || "") + "</td></tr>";
    });
  }
  $("logs-out").innerHTML = h + "</tbody></table></div>";
}
async function openLogEntry(entryId, epOverride){
  /* Подробности записи — как /a123, /e123 и /h123 в ТГ-ленте.
     epOverride — явный вид записи (из карточки пользователя),
     иначе — по текущей вкладке ленты. */
  const ep = epOverride || (logsScope === "errors" ? "errors" : logsScope === "subs" ? "history" : "activity");
  $("drawer-title").textContent = "Запись #" + entryId;
  $("drawer-sub").textContent = "Загрузка…";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:120px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  let r;
  try { r = await api("/logs/" + ep + "/" + entryId); }
  catch(e) { $("drawer-body").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { $("drawer-body").innerHTML = '<p class="err">' + esc((r.data && r.data.error) || "Ошибка загрузки") + "</p>"; return; }
  const it = r.data.entry || {};
  $("drawer-sub").textContent = fmtDate(it.time);
  let h = "<dl>";
  if (ep === "errors") {
    h += kvRow("Источник", esc(it.source || ""));
    h += kvRow("Уровень", pill(it.level || ""));
    h += kvRow("Сообщение", esc(it.message || ""));
    if (it.tg_id) h += kvRow("tg_id", '<span class="mono">' + it.tg_id + "</span>");
  } else {
    const who = it.tg_id ? (esc(it.first_name || "") + (it.username ? " @" + esc(it.username) : "") + " #" + it.tg_id) : "система";
    h += kvRow("Пользователь", who);
    h += kvRow("Действие", esc(it.label || it.action || ""));
    h += kvRow("Код", '<span class="mono">' + esc(it.action || "") + "</span>");
  }
  h += "</dl>";
  if (it.details) h += '<h3>Подробности</h3><pre class="mono" style="white-space:pre-wrap;word-break:break-word">' + esc(it.details) + "</pre>";
  $("drawer-body").innerHTML = h;
  if (it.tg_id) {
    $("drawer-foot").innerHTML = '<button class="ghost" id="btn-log-entry-user">👤 Профиль</button>';
    $("btn-log-entry-user").onclick = function(){ closeDrawer(); openUserEditor(it.tg_id); };
  }
}
$("btn-logs").onclick = function(){ loadLogs(1); };
$("logs-tabs").addEventListener("click", function(e){
  const b = e.target.closest("button[data-logs-tab]");
  if (!b) return;
  logsScope = b.dataset.logsTab;
  loadLogs(1);
});
$("logs-kind-filter").onchange = function(){ loadLogs(1); };
$("logs-date").onchange = function(){ loadLogs(1); };
$("logs-from").oninput = function(){ $("logs-date").value = ""; };
$("logs-to").oninput = function(){ $("logs-date").value = ""; };
$("logs-user").addEventListener("keydown", function(e){ if (e.key === "Enter") loadLogs(1); });
$("btn-logs-prev").onclick = function(){ if (logsPage > 1) loadLogs(logsPage - 1); };
$("btn-logs-next").onclick = function(){ if (logsPage < logsPages) loadLogs(logsPage + 1); };
$("logs-out").addEventListener("click", function(e){
  const tr = e.target.closest("tr[data-log-id]");
  if (tr) openLogEntry(parseInt(tr.dataset.logId, 10));
});
/* Делегирование кликов по активности в карточке пользователя:
   вкладки, пагинация и подробности записи (как /a123 и /h123 в ТГ).
   Слушатель один на стабильный drawer-body — его содержимое
   перерисовывается при каждом открытии карточки. */
$("drawer-body").addEventListener("click", function(e){
  const tab = e.target.closest("button[data-user-act-tab]");
  if (tab) { loadUserActivity(userActTg, tab.dataset.userActTab, 1); return; }
  if (e.target.closest("#btn-user-act-prev")) { if (userActPage > 1) loadUserActivity(userActTg, userActScope, userActPage - 1); return; }
  if (e.target.closest("#btn-user-act-next")) { if (userActPage < userActPages) loadUserActivity(userActTg, userActScope, userActPage + 1); return; }
  const tr = e.target.closest("tr[data-user-act-id]");
  if (tr) openLogEntry(parseInt(tr.dataset.userActId, 10), tr.dataset.userActEp);
});
$("btn-logs-reset").onclick = function(){
  logsScope = "all";
  $("logs-kind-filter").value = "";
  $("logs-date").value = "";
  $("logs-user").value = "";
  $("logs-from").value = "";
  $("logs-to").value = "";
  loadLogs(1);
};
$("btn-logs-export").onclick = function(){
  $("btn-logs-export").href = "/api/admin/logs/export?" + logsParams(true).join("&");
};
$("btn-logs-purge").onclick = async function(){
  const r = await postConfirm("/logs/purge", {});
  renderOut("logs-out", r.data);
};
function fmtDur(sec){
  sec = Math.max(0, Math.round(sec || 0));
  const d = Math.floor(sec / 86400), hh = Math.floor(sec % 86400 / 3600), mm = Math.floor(sec % 3600 / 60);
  if (d) return d + " д " + hh + " ч";
  if (hh) return hh + " ч " + mm + " мин";
  if (mm) return mm + " мин";
  return sec + " сек";
}
function fmtUnix(ts){
  if (!ts) return "—";
  try { return new Date(ts * 1000).toLocaleString("ru-RU", {timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit"}); }
  catch(e) { return String(ts); }
}
$("btn-downtime").onclick = async function(){
  const r = await api("/downtime");
  if (r.status !== 200) { renderOut("downtime-out", r.data); return; }
  const sm = r.data.summary || {}, evs = r.data.events || [];
  let h = '<p class="sub">За последние ' + (r.data.days || 30) + ' дней</p>';
  const targets = Object.keys(sm);
  if (targets.length) {
    h += '<div class="tblwrap"><table><thead><tr><th>Цель</th><th>Инцидентов</th><th>Простой суммарно</th><th>Статус</th></tr></thead><tbody>';
    targets.forEach(function(t){
      const v = sm[t];
      h += "<tr><td>" + esc(t) + '</td><td class="num">' + fmtNum(v.incidents) + '</td><td class="num">' + fmtDur(v.downtime_sec) + "</td><td>" + (v.open_since ? '<span class="pill bad">лежит с ' + fmtUnix(v.open_since) + "</span>" : '<span class="pill ok">работает</span>') + "</td></tr>";
    });
    h += "</tbody></table></div>";
  }
  if (!evs.length) h += '<div class="empty"><span class="big">✅</span>Падений не зафиксировано</div>';
  else {
    h += '<h3>События</h3><div class="tblwrap"><table><thead><tr><th>Цель</th><th>Начало (МСК)</th><th>Конец (МСК)</th><th>Длительность</th><th>Детали</th></tr></thead><tbody>';
    evs.forEach(function(ev){
      h += "<tr><td>" + esc(ev.target || "") + '</td><td class="mono">' + esc(ev.started_str || "") + '</td><td class="mono">' + (ev.ended_str ? esc(ev.ended_str) : '<span class="pill bad">ещё лежит</span>') + '</td><td class="num">' + fmtDur(ev.duration_sec) + '</td><td class="trunc">' + esc(ev.detail || "") + "</td></tr>";
    });
    h += "</tbody></table></div>";
  }
  $("downtime-out").innerHTML = h;
};
$("btn-online").onclick = async function(){
  const r = await api("/online");
  if (r.status !== 200) { renderOut("downtime-out", r.data); return; }
  const on = (r.data.online && r.data.online.emails) || [];
  const last = (r.data.last_online && r.data.last_online.last) || {};
  let h = '<h3>Сейчас онлайн: ' + on.length + "</h3>";
  h += on.length ? '<p>' + on.map(function(e){ return '<span class="pill ok">' + esc(e) + "</span>"; }).join(" ") + "</p>" : '<div class="empty">Никого</div>';
  const keys = Object.keys(last);
  if (keys.length) {
    h += '<h3>Последняя активность (МСК)</h3><div class="tblwrap"><table><thead><tr><th>Клиент</th><th>Был онлайн</th></tr></thead><tbody>';
    keys.sort(function(a, b){ return (last[b] || 0) - (last[a] || 0); }).slice(0, 50).forEach(function(k){
      h += '<tr><td class="mono">' + esc(k) + '</td><td class="mono">' + fmtUnix(last[k]) + "</td></tr>";
    });
    h += "</tbody></table></div>";
  }
  $("downtime-out").innerHTML = h;
};
$("btn-psync").onclick = async function(){ const r = await postConfirm("/panel-sync", {}); renderOut("psync-out", r.data); };
async function loadSyncSettings(){
  const r = await api("/panel-sync/settings");
  if (r.status !== 200) { renderOut("psync-out", r.data); return; }
  const st = r.data.settings || {};
  let h = '<dl class="kv">';
  h += kvRow("Режим", "Только вручную — кнопкой «Синхронизировать» выше");
  h += kvRow("Последний запуск", st.last_run ? fmtDate(st.last_run) : "ещё не запускалась");
  h += "</dl>";
  const rep = st.last_report || {};
  const repKeys = Object.keys(rep);
  if (repKeys.length) {
    const REP_LABELS = {at: "Время", checked: "Проверено подписок", updated: "Обновлено", orphans: "Сироты (нет в панели)", missing: "Отсутствуют в панели", names_updated: "Имён обновлено", names_errors: "Ошибок имён", disabled: "Отключено", enabled: "Включено"};
    h += '<h3>Последний отчёт</h3><dl class="kv">';
    repKeys.forEach(function(k){
      const v = k === "at" ? fmtDate(rep[k]) : String(rep[k]);
      h += kvRow(esc(REP_LABELS[k] || k), esc(v));
    });
    h += "</dl>";
  }
  $("psync-out").innerHTML = h;
}
$("btn-psync-set").onclick = function(){ loadSyncSettings(); };
// Тумблеры утренней сводки — те же 12, что в ТГ (handle_morning_menu):
// «enabled» — отдельный чекбокс mor-enabled, остальные — здесь, двумя
// группами как в ТГ: ежедневно в это время / фоновые проверки.
const MORNING_TOGGLES = {reconcile: "🔍 Сверка с Platega", netcheck: "🌐 Проверка операторов", support_topics: "👥 Темы поддержки", server_reminder: "🖥 Напоминание о серверах", backup: "💾 Бэкап со сводкой", tags: "🏷 Теги панели со сводкой"};
const MORNING_TOGGLES_BG = {blacklist_sync: "🚫 Синхронизация ЧС", site_sync: "🌐 Автообновление сайта", healthcheck: "💓 Проверка здоровья", device_watch: "📱 Новые устройства", alerts: "🔔 Алерты о падениях"};
function morningTogglesHtml(m, map){
  let h = "";
  Object.keys(map).forEach(function(k){
    // Отсутствующий ключ — как в ТГ job_enabled(key, True): включён.
    h += '<label class="chk"><input type="checkbox" class="mor-tgl" data-k="' + k + '"' + (m[k] !== false ? " checked" : "") + "> " + map[k] + "</label>";
  });
  return h;
}
async function loadMorning(){
  const r = await api("/morning");
  if (r.status !== 200) { renderOut("morning-out", r.data); return; }
  const m = r.data.morning_sync || {};
  $("mor-time").value = m.time || "";
  $("mor-enabled").checked = !!m.enabled;
  let h = '<dl class="kv">';
  h += kvRow("Время сводки", esc(m.time || "—") + " (МСК)");
  h += kvRow("Сводка", m.enabled ? '<span class="pill ok">Включена</span>' : '<span class="pill bad">Выключена</span>');
  h += kvRow("Проверка операторов: раз в (дней)", String(m.netcheck_days != null ? m.netcheck_days : "—"));
  h += kvRow("Проверка операторов: последний запуск", m.netcheck_last_run ? fmtDate(m.netcheck_last_run) : "ещё не запускалась");
  $("morning-out").innerHTML = h + "</dl>";
  $("morning-toggles").innerHTML = '<h3>Ежедневно в это время</h3><div class="chkgrid">' + morningTogglesHtml(m, MORNING_TOGGLES) + '</div><h3>Фоновые проверки (на своих интервалах)</h3><div class="chkgrid">' + morningTogglesHtml(m, MORNING_TOGGLES_BG) + "</div>";
}
$("btn-morning").onclick = function(){ loadMorning(); };
$("btn-morning-run").onclick = async function(){
  const r = await postConfirm("/morning/run-now", {});
  if (r.status === 200) { toast("Сводка запущена", "ok"); $("morning-out").innerHTML = '<p class="mut">Сводка формируется и придёт в Telegram.</p>'; }
  else renderOut("morning-out", r.data);
};
$("btn-morning-save").onclick = async function(){
  const body = {morning_sync: {}};
  const t = $("mor-time").value.trim();
  if (t) body.morning_sync.time = t;
  body.morning_sync.enabled = $("mor-enabled").checked;
  document.querySelectorAll(".mor-tgl").forEach(function(cb){
    body.morning_sync[cb.dataset.k] = cb.checked;
  });
  const r = await api("/morning", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
  if (r.status === 200) { toast("Настройки сводки сохранены", "ok"); loadMorning(); }
  else renderOut("morning-out", r.data);
};
$("btn-job").onclick = async function(){
  const r = await postConfirm("/jobs/run-now", {job: $("job-sel").value});
  renderOut("job-out", r.data);
};
async function loadNetcheck(){
  const r = await api("/netcheck");
  if (r.status !== 200) { renderOut("netcheck-out", r.data); return; }
  const d = r.data;
  let h = '<dl class="kv">';
  h += kvRow("Автопроверка", d.netcheck_days ? "раз в " + d.netcheck_days + " дн." : "—");
  h += kvRow("Последний запуск", d.netcheck_last_run ? fmtDate(d.netcheck_last_run) : "ещё не запускалась");
  h += "</dl>";
  h += '<h3>Домены</h3><div class="tblwrap"><table><thead><tr><th>Название</th><th>Домен</th></tr></thead><tbody>';
  (d.domains || []).forEach(function(x){ h += "<tr><td>" + esc(x.label || "") + '</td><td class="mono">' + esc(x.domain || "") + "</td></tr>"; });
  h += '</tbody></table></div><h3>Операторы</h3><div class="tblwrap"><table><thead><tr><th>Оператор</th><th>ASN</th></tr></thead><tbody>';
  (d.operators || []).forEach(function(x){ h += "<tr><td>" + esc(x.label || "") + '</td><td class="mono">' + esc((x.asns || []).join(", ")) + "</td></tr>"; });
  h += "</tbody></table></div>";
  // Форма настроек: что проверять. Пустой выбор в конфиге = «все», поэтому
  // галочки ставим так: выбраны явно — по списку, список пуст — все.
  const selD = d.selected_domains || [], selO = d.selected_operators || [];
  const allD = d.all_domains || d.domains || [], allO = d.all_operators || d.operators || [];
  h += '<h3>Настройки проверки</h3><p class="sub">Что проверять автоматически и вручную. Хотя бы один домен и один оператор должны остаться включёнными.</p>';
  h += '<div class="chkgrid"><b>Домены</b>';
  allD.forEach(function(x){
    const on = !selD.length || selD.indexOf(x.label) >= 0;
    h += '<label class="chk"><input type="checkbox" class="nc-dom" value="' + esc(x.label) + '"' + (on ? " checked" : "") + "> " + esc(x.label) + ' <span class="mut mono small">' + esc(x.domain) + "</span></label>";
  });
  h += '</div><div class="chkgrid"><b>Операторы</b>';
  allO.forEach(function(x){
    const on = !selO.length || selO.indexOf(x.label) >= 0;
    h += '<label class="chk"><input type="checkbox" class="nc-op" value="' + esc(x.label) + '"' + (on ? " checked" : "") + "> " + esc(x.label) + "</label>";
  });
  h += '</div><label>Автопроверка раз в (дней)<input id="nc-days" type="number" min="1" value="' + (d.netcheck_days || 2) + '"></label>';
  h += '<div class="btnrow"><button id="nc-save">Сохранить настройки</button></div>';
  $("netcheck-out").innerHTML = h;
  $("nc-save").onclick = withSpin($("nc-save"), async function(){
    const doms = Array.prototype.map.call(document.querySelectorAll(".nc-dom:checked"), function(c){ return c.value; });
    const ops = Array.prototype.map.call(document.querySelectorAll(".nc-op:checked"), function(c){ return c.value; });
    if (!doms.length || !ops.length) { toast("Нужен хотя бы один домен и один оператор", "err"); return; }
    const body = {netcheck: {
      domains: doms.length === allD.length ? [] : doms,
      operators: ops.length === allO.length ? [] : ops,
      netcheck_days: parseInt($("nc-days").value || "2", 10),
      netcheck_last_run: d.netcheck_last_run || null}};
    const r = await api("/settings", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
    if (r.status === 200) { toast("Настройки проверки сохранены", "ok"); loadNetcheck(); }
    else toast("Ошибка: " + ((r.data && r.data.error) || r.status), "err");
  });
}
$("btn-netcheck-show").onclick = function(){ loadNetcheck(); };
const NC_STATE = {ok: ["ok", "Доступен"], blocked: ["bad", "Заблокирован"], error: ["warn", "Ошибка"], no_probe: ["warn", "Нет пробы"]};
$("btn-netcheck").onclick = withSpin($("btn-netcheck"), async function(){
  const r = await postConfirm("/netcheck/run", {});
  if (r.status !== 200) { renderOut("netcheck-out", r.data); return; }
  const d = r.data, sm = d.summary || {};
  let h = '<p>Итого проверок: <b>' + (sm.total || 0) + "</b> · доступно: <b>" + (sm.ok || 0) + "</b> · заблокировано: <b>" + (sm.blocked || 0) + "</b> · нет пробы: <b>" + (sm.no_probe || 0) + "</b> · ошибок: <b>" + (sm.errors || 0) + "</b></p>";
  const bo = d.by_operator || {};
  const boKeys = Object.keys(bo);
  if (boKeys.length) {
    h += '<h3>По операторам</h3><p>' + boKeys.map(function(k){ return esc(k) + " " + esc(bo[k]); }).join(" · ") + "</p>";
  }
  const res = d.results || [];
  if (res.length) {
    h += '<div class="tblwrap"><table><thead><tr><th>Домен</th><th>Оператор</th><th>Состояние</th></tr></thead><tbody>';
    res.forEach(function(row){
      const ops = row.operators || {};
      Object.keys(ops).forEach(function(op){
        const st = NC_STATE[(ops[op] || {}).state] || ["info", (ops[op] || {}).state || "—"];
        h += '<tr><td class="mono">' + esc(row.domain || row.label || "") + "</td><td>" + esc(op) + '</td><td><span class="pill ' + st[0] + '">' + st[1] + "</span></td></tr>";
      });
      if (row.error) h += '<tr><td class="mono">' + esc(row.domain || "") + '</td><td colspan="2">' + esc(row.error) + "</td></tr>";
    });
    h += "</tbody></table></div>";
  }
  $("netcheck-out").innerHTML = h;
});
async function loadSite(){
  const r = await api("/site");
  if (r.status !== 200) { renderOut("site-out", r.data); return; }
  const st = r.data.site || {};
  let h = '<dl class="kv">';
  h += kvRow("Домен", '<span class="mono">' + esc(st.domain || "—") + "</span>");
  if (st.url) h += kvRow("Адрес", '<a href="' + esc(st.url) + '" target="_blank" rel="noopener">' + esc(st.url) + "</a>");
  h += kvRow("Настроен", st.configured ? '<span class="pill ok">Да</span>' : '<span class="pill bad">Нет</span>');
  h += kvRow("HTTPS", st.https ? "да" : "нет");
  h += kvRow("Задеплоен", st.deployed_at ? fmtDate(st.deployed_at) : "ещё не деплоился");
  h += kvRow("Автообновление", st.auto ? "включено" : "выключено");
  h += kvRow("Ожидает обновления", st.update_pending ? '<span class="pill warn">Да — нужен деплой</span>' : "нет");
  if (st.host) h += kvRow("Хост", '<span class="mono">' + esc(st.host) + "</span>");
  if (st.user) h += kvRow("Пользователь", '<span class="mono">' + esc(st.user) + "</span>");
  h += kvRow("Пароль сервера", st.password_set ? "задан" : "не задан");
  $("site-out").innerHTML = h + "</dl>";
  $("ss-domain").value = st.domain || "";
  $("ss-auto").checked = !!st.auto;
  $("ss-host").value = st.host || "";
  $("ss-port").value = st.port || 22;
  $("ss-user").value = st.user || "";
  $("ss-pass").value = "";
}
$("btn-ss2-save").onclick = async function(){
  const body = {domain: $("ss-domain").value.trim(), auto: $("ss-auto").checked,
    host: $("ss-host").value.trim(), user: $("ss-user").value.trim()};
  const port = parseInt($("ss-port").value, 10);
  if (port) body.port = port;
  const pass = $("ss-pass").value;
  if (pass) body.password = pass;
  const r = await api("/site/settings", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
  if (r.status === 200) { toast("Настройки сайта сохранены", "ok"); loadSite(); }
  else renderOut("ss2-out", r.data);
};
$("btn-site-cert").onclick = async function(){ const r = await postConfirm("/site/cert", {}); renderOut("ss2-out", r.data); if (r.status === 200) loadSite(); };
$("btn-site-check").onclick = async function(){
  const r = await api("/site/check");
  if (r.status !== 200) { renderOut("site-check-out", r.data); return; }
  const d = r.data.data || {};
  let h = '<dl class="kv">';
  Object.keys(d).forEach(function(k){ h += kvRow(esc(k), '<span class="mono">' + esc(String(d[k])) + "</span>"); });
  $("site-check-out").innerHTML = h + "</dl>";
  loadSite();
};
$("btn-site-show").onclick = function(){ loadSite(); };
let siteLoaded = false;
document.querySelector('[data-nav="site"]').addEventListener("click", function(){
  if (!siteLoaded) { siteLoaded = true; loadSite(); $("btn-st-show").click(); }
});
$("btn-deploy").onclick = async function(){ const r = await postConfirm("/site/deploy", {}); renderOut("site-out", r.data); };
$("btn-st-show").onclick = async function(){
  const r = await api("/site/texts");
  if (r.status !== 200) { renderOut("st-out", r.data); return; }
  const texts = r.data.texts || {};
  const sections = r.data.sections || {};
  const secIds = Object.keys(sections);
  if (!secIds.length) { $("st-out").innerHTML = '<div class="empty">Разделов текстов нет</div>'; return; }
  let h = '<p class="sub">Пустое значение — на сайте работает текст по умолчанию. Нажми на строку, чтобы изменить поле; тексты применяются при следующем деплое.</p>';
  secIds.forEach(function(secId){
    const sec = sections[secId];
    h += "<h3>" + esc(sec.title || secId) + '</h3><div class="tblwrap"><table><thead><tr><th>Поле</th><th>Сейчас</th></tr></thead><tbody>';
    (sec.fields || []).forEach(function(f){
      const val = texts[f.field];
      h += '<tr data-field="' + esc(f.field) + '"><td>' + esc(f.label || f.field) + ' <span class="mono small mut">' + esc(f.field) + '</span></td><td>' + (val ? esc(String(val).slice(0, 100)) : '<span class="mut">по умолчанию</span>') + "</td></tr>";
    });
    h += "</tbody></table></div>";
  });
  $("st-out").innerHTML = h;
  $("st-out").querySelectorAll("tr[data-field]").forEach(function(tr){
    tr.onclick = function(){
      $("st-field").value = tr.dataset.field;
      $("st-text").value = texts[tr.dataset.field] || "";
      $("st-text").focus();
    };
  });
};
$("btn-st-save").onclick = async function(){
  const r = await api("/site/texts", {method: "PATCH", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({field: $("st-field").value, text: $("st-text").value})});
  if (r.status === 200) { toast("Текст сохранён — применится при деплое", "ok"); $("btn-st-show").click(); }
  else renderOut("st-out", r.data);
};
$("btn-site-del").onclick = async function(){ const r = await postConfirm("/site/delete", {}); renderOut("site-del-out", r.data); };
/* Предпросмотр архива перед восстановлением — как offer_restore в ТГ:
   сначала показываем, что внутри архива, и только потом разрешаем
   восстановление. Флаг сбрасывается при смене файла. */
let backupInspected = false;
let backupLoaded = false;
document.querySelector('[data-nav="backup"]').addEventListener("click", function(){
  if (!backupLoaded) { backupLoaded = true; loadBackupInfo(); }
});
async function loadBackupInfo(){
  let r;
  try { r = await api("/backup/info"); }
  catch(e) { $("backup-info").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("backup-info", r.data); return; }
  const d = r.data || {};
  const counts = d.counts || {};
  const rows = Object.keys(counts).map(function(k){
    return "<tr><td>" + esc(k) + "</td><td class='num'>" + fmtNum(counts[k]) + "</td></tr>";
  }).join("");
  $("backup-info").innerHTML = "<table><tbody>" + rows + "</tbody></table>"
    + (d.db_size_human ? "<p>База: <b>" + esc(d.db_size_human) + "</b></p>" : "");
}
$("bk-file").addEventListener("change", function(){
  backupInspected = false;
  $("backup-preview").innerHTML = "";
});
function readBkFile(){
  const f = $("bk-file").files[0];
  if (!f) return Promise.resolve("");
  return new Promise(function(res, rej){
    const rd = new FileReader();
    rd.onload = function(){ res(String(rd.result).split(",")[1] || ""); };
    rd.onerror = rej;
    rd.readAsDataURL(f);
  });
}
$("btn-backup-inspect").onclick = async function(){
  if (!$("bk-file").files[0]) { toast("Выберите файл архива", "err"); return; }
  $("backup-preview").innerHTML = "<p class='mut'>Проверяю архив…</p>";
  let b64 = "";
  try { b64 = await readBkFile(); }
  catch(e) { $("backup-preview").innerHTML = "<p class='err'>Не прочитать файл</p>"; return; }
  const r = await api("/backup/inspect", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({archive: b64})});
  if (r.status !== 200) {
    backupInspected = false;
    const msg = (r.data && r.data.details) ? r.data.details : (r.data && r.data.error) || r.status;
    $("backup-preview").innerHTML = "<p class='err'>Архив не подходит: " + esc(msg) + "</p>";
    return;
  }
  const d = r.data || {};
  const counts = d.counts || {};
  const rows = Object.keys(counts).map(function(k){
    return "<tr><td>" + esc(k) + "</td><td class='num'>" + fmtNum(counts[k]) + "</td></tr>";
  }).join("");
  const extras = [];
  if (d.has_config) extras.push("настройки");
  if (d.has_env) extras.push(".env с токеном");
  if (d.assets_count) extras.push("файлов assets: " + d.assets_count);
  if (d.checksum === "ok") extras.push("контрольные суммы сошлись ✅");
  else if (d.checksum === "none") extras.push("старый формат — без контрольных сумм");
  $("backup-preview").innerHTML = "<h3>Проверил архив</h3><table><tbody>" + rows + "</tbody></table>"
    + (d.created_at ? "<p>📅 Создан: <b>" + fmtDate(d.created_at) + "</b></p>" : "")
    + (extras.length ? "<p>📦 Внутри: " + esc(extras.join(", ")) + "</p>" : "")
    + (d.checksum === "none" ? "<p class='warn'>Старый архив без контрольных сумм — проверьте, что это файл от нашего бота.</p>" : "")
    + "<p class='warn'>⚠️ Текущие данные бота будут заменены полностью.</p>";
  backupInspected = true;
  toast("Архив проверен", "ok");
};
$("btn-backup-restore").onclick = async function(){
  const f = $("bk-file").files[0];
  if (!f) { toast("Выберите файл архива", "err"); return; }
  if (!backupInspected) { toast("Сначала проверьте архив кнопкой «Проверить архив»", "err"); return; }
  if (!$("bk-fresh").checked) { toast("Подтвердите, что свежий бэкап сделан", "err"); return; }
  const b64 = await readBkFile();
  const r = await postConfirm("/backup/restore", {fresh_backup: true, archive: b64});
  renderOut("backup-out", r.data);
  if (r.status === 200) toast("Бэкап восстановлен, бот перезапускается", "ok");
};
$("btn-git").onclick = async function(){ const r = await postConfirm("/git-update", {}); renderOut("git-out", r.data); };

/* --- Поддержка и настройки --- */
let supportLoaded = false;
async function loadTopics(){
  let r;
  try { r = await api("/support/topics"); }
  catch(e) { $("topics-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("topics-out", r.data); return; }
  const topics = r.data.topics || [];
  if (!topics.length) { $("topics-out").innerHTML = '<div class="empty"><span class="big">🛟</span>Открытых обращений нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Обращение</th><th>Топик</th></tr></thead><tbody>';
  topics.forEach(function(t){
    const who = esc(t.first_name || "") + (t.username ? ' <span class="mut">@' + esc(t.username) + "</span>" : "") + ' <span class="mono small">#' + t.user_id + "</span>";
    // Название топика в поддержке обычно повторяет имя юзера — тогда
    // показываем только юзера, отдельная тема — отдельной строкой.
    const topic = t.topic_name && t.topic_name !== t.first_name
      ? '<b>' + esc(t.topic_name) + '</b><br><span class="mut">' + who + "</span>" : who;
    h += '<tr data-user="' + t.user_id + '"><td>' + topic + '</td><td class="mono">#' + (t.topic_id || "—") + "</td></tr>";
  });
  h += '</tbody></table></div>';
  $("topics-out").innerHTML = h;
  $("topics-out").querySelectorAll("tr[data-user]").forEach(function(tr){
    tr.onclick = function(){ $("sup-user").value = tr.dataset.user; openTopic(); };
  });
}
document.querySelector('[data-nav="support"]').addEventListener("click", function(){
  if (!supportLoaded) { supportLoaded = true; loadTopics(); loadSupportSettings(); }
});
$("btn-support").onclick = loadTopics;
async function openTopic(){
  const id = $("sup-user").value;
  const r = await api("/support/topics/" + id);
  if (r.status !== 200) { $("sup-msgs").textContent = "Ошибка: " + (r.data.error || r.status); return; }
  $("sup-msgs").innerHTML = (r.data.messages || []).map(function(m){
    return "<p><b>" + (m.from_admin ? "Админ" : "Юзер") + ":</b> " + esc(m.text) + ' <span class="mut">' + fmtDate(m.created_at) + "</span></p>";
  }).join("") || '<div class="empty"><span class="big">💬</span>Сообщений нет</div>';
}
$("btn-sup-open").onclick = openTopic;
$("btn-sup-reply").onclick = withSpin($("btn-sup-reply"), async function(){
  const id = $("sup-user").value;
  const r = await api("/support/topics/" + id + "/reply", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({text: $("sup-text").value, close: $("sup-close").checked})});
  $("sup-msg").textContent = r.status === 200 ? ("Отправлено (" + (r.data.delivered_via || "?") + ")") : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) { $("sup-text").value = ""; toast("Ответ отправлен", "ok"); }
});
$("btn-sup-close").onclick = async function(){
  const id = $("sup-user").value;
  const r = await api("/support/topics/" + id + "/close", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({})});
  $("sup-msg").textContent = r.status === 200 ? "Обращение закрыто" : ("Ошибка: " + (r.data.error || r.status));
};
async function loadSupportSettings(){
  const r = await api("/support/settings");
  if (r.status !== 200) return;
  const st = r.data.settings || {};
  $("ss-group").value = st.support_group_id || "";
  $("ss-log").value = st.log_channel_id || "";
  const sb = $("sb-status");
  if (sb) {
    sb.innerHTML = st.token_set
      ? "Токен задан" + (st.support_bot_username ? " — <b>@" + esc(st.support_bot_username) + "</b>" : "")
      : "Токен не задан — бот поддержки не запущен";
    const s = st.stats || {};
    $("sb-stats").textContent = "📊 Открытых тем: " + (s.open_topics || 0) + " · новых вчера: " + (s.new_yesterday || 0) + " · закрыто всего: " + (s.closed_total || 0);
    if (!st.is_mark) $("sb-form").innerHTML = '<p class="mut">Токен меняет только Mark.</p>';
  }
}
$("btn-ss-save").onclick = async function(){
  const r = await api("/support/settings", {method: "PATCH", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({support_group_id: parseInt($("ss-group").value || "0", 10),
      log_channel_id: parseInt($("ss-log").value || "0", 10)})});
  if (r.status === 200) { toast("Настройки поддержки сохранены", "ok"); $("ss-out").innerHTML = ""; loadSupportSettings(); }
  else renderOut("ss-out", r.data);
};
$("btn-sb-save").onclick = withSpin($("btn-sb-save"), async function(){
  const r = await postConfirm("/support/token", {token: $("sb-token").value});
  if (r.status === 200) {
    toast("Токен бота поддержки сохранён", "ok");
    $("sb-token").value = "";
    $("sb-out").innerHTML = r.data.service_ok
      ? "✅ Сервис drebol-support-bot запущен"
      : '<p class="err">⚠️ Сервис не запустился сам: ' + esc(r.data.service_detail || "ошибка") + ". Запусти вручную: systemctl restart drebol-support-bot.</p>";
    loadSupportSettings();
  } else if (r.status) renderOut("sb-out", r.data);
});
$("btn-helper-add").onclick = async function(){
  const target = ($("helper-tg").value || "").trim();
  const r = await api("/helpers/add", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({target: target})});
  if (r.status === 200) {
    if (r.data.already) toast("Уже помощник", "ok");
    else if (r.data.dm_sent) toast("Помощник добавлен, приглашение отправлено в Telegram", "ok");
    else toast("Помощник добавлен, но написать ему не удалось — пригласи из списка", "");
    loadHelpers();
  } else renderOut("helpers-out", r.data);
};
$("btn-helper-perm").onclick = async function(){
  const id = $("helper-tg").value;
  const r = await api("/helpers/" + id + "/perm", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({perm: $("helper-perm-sel").value})});
  if (r.status === 200) { toast("Право переключено", "ok"); loadHelpers(); } else renderOut("helpers-out", r.data);
};
$("btn-helper-del").onclick = async function(){
  const id = $("helper-tg").value;
  const r = await postConfirm("/helpers/" + id + "/delete", {});
  if (r.status === 200) {
    toast(r.data.dm_sent ? "Помощник удалён, уведомление отправлено" : "Помощник удалён", "ok");
    loadHelpers();
  } else renderOut("helpers-out", r.data);
};
const PERM_LABELS = {users: "Карточки людей", dm: "Писать людям", support: "Поддержка", subs: "Подписки — смотреть", subs_edit: "Подписки — менять", payments: "Оплаты", promos: "Промокоды", blacklist: "Чёрный список", broadcast: "Рассылки", stats: "Статистика"};
async function loadHelpers(){
  const r = await api("/helpers");
  if (r.status !== 200) { renderOut("helpers-out", r.data); return; }
  const items = r.data.helpers || r.data || [];
  const list = Array.isArray(items) ? items : (items.helpers || []);
  if (!list.length) { $("helpers-out").innerHTML = '<div class="empty">Помощников нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Помощник</th><th>TG ID</th><th>Права</th><th>Группа поддержки</th><th></th></tr></thead><tbody>';
  list.forEach(function(x){
    const perms = (x.perms || []).map(function(pp){ return '<span class="pill info">' + esc(PERM_LABELS[pp] || pp) + "</span>"; }).join(" ") || "—";
    const grp = x.in_group === "in" ? '<span class="pill ok">в группе</span>'
      : x.in_group === "out" ? '<span class="pill warn">не в группе</span>'
      : x.in_group === "no_group" ? '<span class="mut">группа не настроена</span>' : '<span class="mut">не проверено</span>';
    const inv = x.in_group === "out" ? '<button class="ghost" data-invite="' + x.tg_id + '">Пригласить в группу</button>' : "";
    h += '<tr data-tg="' + x.tg_id + '"><td>' + esc(x.first_name || "") + (x.username ? ' <span class="mut">@' + esc(x.username) + "</span>" : "") + '</td><td class="mono">' + x.tg_id + "</td><td>" + perms + "</td><td>" + grp + "</td><td>" + inv + "</td></tr>";
  });
  $("helpers-out").innerHTML = h + "</tbody></table></div>";
  $("helpers-out").querySelectorAll("tr[data-tg]").forEach(function(tr){
    tr.onclick = function(){ $("helper-tg").value = tr.dataset.tg; };
  });
  $("helpers-out").querySelectorAll("[data-invite]").forEach(function(b){
    b.onclick = async function(ev){
      ev.stopPropagation();
      const r = await api("/helpers/" + b.dataset.invite + "/invite", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({})});
      if (r.status === 200 && r.data.sent) toast("Приглашение отправлено помощнику в Telegram", "ok");
      else if (r.status === 200 && r.data.invite_link) { prompt("Бот не смог написать помощнику сам. Перешли ему ссылку вручную:", r.data.invite_link); }
      else toast("Ошибка: " + ((r.data && r.data.error) || r.status), "err");
      loadHelpers();
    };
  });
}
$("btn-helpers").onclick = function(){ loadHelpers(); };
async function loadWebAccess(){
  const r = await api("/web-access");
  if (r.status !== 200) { renderOut("wa-out", r.data); return; }
  const d = r.data, w = d.webapi || {};
  $("wa-port").value = w.port || "";
  $("wa-bind").value = w.bind || "";
  $("wa-public").value = d.public || "";
  $("wa-upstream").value = d.upstream || "";
  const ss = d.sessions || {};
  let h = '<dl class="kv">';
  h += kvRow("Веб-API", w.enabled ? '<span class="pill ok">Включён</span>' : '<span class="pill bad">Выключен</span>');
  h += kvRow("Порт", String(w.port || "—"));
  h += kvRow("Bind", '<span class="mono">' + esc(w.bind || "—") + "</span>");
  if (d.public) h += kvRow("Публичный адрес", '<span class="mono">' + esc(d.public) + "</span>");
  if (d.upstream) h += kvRow("Upstream", '<span class="mono">' + esc(d.upstream) + "</span>");
  h += kvRow("Ключ Turnstile задан", d.turnstile_site_key_set ? "да" : "нет");
  h += kvRow("Секрет Turnstile задан", d.turnstile_secret_set ? "да" : "нет");
  h += kvRow("Живых сессий кабинета", fmtNum(ss.live || 0) + " · пользователей: " + fmtNum(ss.people || 0) + " · сегодня: " + fmtNum(ss.today || 0));
  $("wa-out").innerHTML = h + "</dl>";
}
$("btn-webacc").onclick = function(){ loadWebAccess(); };
$("btn-wa-save").onclick = async function(){
  const body = {};
  const port = $("wa-port").value;
  if (port) body.webapi_port = parseInt(port, 10);
  const bind = $("wa-bind").value.trim();
  if (bind) body.webapi_bind = bind;
  body.webapi_public = $("wa-public").value.trim();
  body.webapi_upstream = $("wa-upstream").value.trim();
  const tsSite = $("wa-ts-site").value.trim();
  if (tsSite) body.turnstile_site_key = tsSite;
  const tsSecret = $("wa-ts-secret").value.trim();
  if (tsSecret) body.turnstile_secret_key = tsSecret;
  const r = await api("/web-access", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
  if (r.status === 200) { toast("Сохранено — применится после рестарта бота", "ok"); $("wa-ts-site").value = ""; $("wa-ts-secret").value = ""; loadWebAccess(); } else renderOut("wa-out", r.data);
};
$("btn-wa-check").onclick = async function(){
  const r = await api("/web-access/check", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({})});
  if (r.status !== 200) { renderOut("wa-check-out", r.data); return; }
  const c = r.data.check || {};
  let h = '<dl class="kv">';
  h += kvRow("API включён", c.enabled ? "да" : "нет");
  h += kvRow("Сервер поднят", c.running ? "да" : "нет");
  if (c.local) h += kvRow("Отвечает себе", c.local.ok ? "да" : "нет");
  if (c.outside) h += kvRow("Отвечает снаружи", c.outside.ok ? "да" : "нет");
  if (c.public) h += kvRow("Проверял", '<span class="mono">' + esc(c.public) + "</span>");
  $("wa-check-out").innerHTML = h + "</dl>" + ((c.advice || []).map(function(a){ return '<p class="sub">⚠️ ' + esc(a) + "</p>"; }).join(""));
};
async function loadConnectHelp(){
  const r = await api("/connect-help");
  if (r.status !== 200) { renderOut("ch-out", r.data); return; }
  const d = r.data, st = d.stats || {};
  let h = '<dl class="kv">';
  h += kvRow("Подсказки", d.enabled ? '<span class="pill ok">Включены</span>' : '<span class="pill bad">Выключены</span>');
  h += kvRow("Отправлять через", (d.hours || "—") + " ч после регистрации без подключения");
  h += kvRow("Отправлено всего", fmtNum(st.total || 0));
  h += kvRow("Отправлено за 7 дней", fmtNum(st.week || 0));
  h += "</dl>";
  h += '<label><input id="ch-enabled" type="checkbox"' + (d.enabled ? " checked" : "") + "> подсказки включены</label>";
  h += '<label>Через сколько часов<input id="ch-hours" type="number" min="1" value="' + (d.hours || 3) + '"></label>';
  h += '<div class="btnrow"><button class="ghost" id="ch-save">Сохранить</button></div>';
  $("ch-out").innerHTML = h;
  $("ch-save").onclick = withSpin($("ch-save"), async function(){
    const rr = await api("/connect-help", {method: "PATCH", headers: {"X-CSRF-Token": csrf()},
      body: JSON.stringify({enabled: $("ch-enabled").checked, hours: parseInt($("ch-hours").value || "3", 10)})});
    if (rr.status === 200) { toast("Настройки помощи сохранены", "ok"); loadConnectHelp(); }
    else toast("Ошибка: " + ((rr.data && rr.data.error) || rr.status), "err");
  });
}
$("btn-ch-show").onclick = function(){ loadConnectHelp(); };

/* --- Консоль серверов: xterm.js с CDN + WebSocket в PTY --- */
let consoleLoaded = false;
let consoleLibs = null;
let consoleWS = null;
let consoleTerm = null;
let consoleFit = null;

function consoleLibsLoad(){
  if (consoleLibs) return consoleLibs;
  consoleLibs = new Promise(function(resolve, reject){
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css";
    document.head.appendChild(css);
    function loadScript(src, next){
      const s = document.createElement("script");
      s.src = src;
      s.onload = next;
      s.onerror = function(){ reject(new Error("cdn")); };
      document.head.appendChild(s);
    }
    loadScript("https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js", function(){
      loadScript("https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js", function(){
        if (typeof Terminal === "undefined" || typeof FitAddon === "undefined") reject(new Error("cdn"));
        else resolve();
      });
    });
  });
  return consoleLibs;
}

async function loadConsole(){
  let r;
  try { r = await api("/console/servers"); }
  catch(e) { $("console-status").textContent = "Ошибка загрузки"; return; }
  if (r.status !== 200) { $("console-status").textContent = "Ошибка: " + (r.data.error || r.status); return; }
  if (!r.data.enabled) {
    $("console-status").textContent = "Консоль выключена настройкой console_enabled в конфиге бота.";
    $("console-servers").innerHTML = "";
    return;
  }
  $("console-status").textContent = "Выбери сервер — терминал откроется здесь же. Для главного сервера — локальная оболочка, для остальных — SSH с главного.";
  const host = $("console-servers");
  host.innerHTML = "";
  (r.data.servers || []).forEach(function(s){
    const b = document.createElement("button");
    b.className = "ghost";
    b.textContent = s.name;
    b.title = s.target || "";
    b.onclick = function(){ openConsole(s); };
    host.appendChild(b);
  });
  // Публичный ключ — только Mark; у Muse эндпоинт отвечает 403, блок не показываем.
  const pk = await api("/console/pubkey");
  if (pk.status === 200 && pk.data.pubkey) {
    show("console-pubkey-box", true);
    $("console-pubkey").value = pk.data.pubkey;
  }
}

function closeConsole(){
  if (consoleWS) { try { consoleWS.close(); } catch(e) {} consoleWS = null; }
  if (consoleTerm) { try { consoleTerm.dispose(); } catch(e) {} consoleTerm = null; consoleFit = null; }
  show("console-term-card", false);
  $("console-term-state").textContent = "";
}

async function openConsole(srv){
  closeConsole();
  show("console-term-card", true);
  $("console-term-title").textContent = "Терминал — " + srv.name;
  $("console-term-state").textContent = "Подключение…";
  try { await consoleLibsLoad(); }
  catch(e) {
    $("console-term-state").textContent = "Не удалось загрузить терминал: CDN xterm.js недоступен. Проверь сеть и открой раздел заново.";
    return;
  }
  const term = new Terminal({cursorBlink: true, fontSize: 13,
    fontFamily: "ui-monospace, Menlo, Consolas, monospace",
    theme: {background: "#0A0A0C", foreground: "#E8EAED"}});
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  $("console-term").innerHTML = "";
  term.open($("console-term"));
  try { fit.fit(); } catch(e) {}
  consoleTerm = term; consoleFit = fit;
  const proto = location.protocol === "https:" ? "wss://" : "ws://";
  const ws = new WebSocket(proto + location.host + API + "/console/ws?server=" + encodeURIComponent(srv.id));
  ws.binaryType = "arraybuffer";
  consoleWS = ws;
  ws.onopen = function(){
    $("console-term-state").textContent = "Подключено · " + (srv.target || "");
    try { ws.send(JSON.stringify({type: "resize", cols: term.cols, rows: term.rows})); } catch(e) {}
    term.focus();
  };
  ws.onmessage = function(ev){
    if (ev.data instanceof ArrayBuffer) term.write(new Uint8Array(ev.data));
    else term.write(String(ev.data));
  };
  ws.onclose = function(){
    $("console-term-state").textContent = "Отключено";
    if (consoleWS === ws) consoleWS = null;
  };
  ws.onerror = function(){ $("console-term-state").textContent = "Ошибка соединения"; };
  term.onData(function(d){
    if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(d));
  });
  term.onResize(function(size){
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type: "resize", cols: size.cols, rows: size.rows}));
  });
}
document.querySelector('[data-nav="console"]').addEventListener("click", function(){
  if (!consoleLoaded) { consoleLoaded = true; loadConsole(); }
});
$("btn-console-close").onclick = function(){ closeConsole(); toast("Консоль отключена"); };
$("btn-console-pubkey-copy").onclick = function(){
  const ta = $("console-pubkey");
  ta.select();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(ta.value).then(function(){ toast("Ключ скопирован", "ok"); });
  } else {
    document.execCommand("copy");
    toast("Ключ скопирован", "ok");
  }
};
window.addEventListener("resize", function(){ if (consoleFit) { try { consoleFit.fit(); } catch(e) {} } });

(function init(){
  const params = new URLSearchParams(location.search);
  if (params.get("token")) { show("setup", true); }
  const s = document.createElement("script");
  s.src = "https://telegram.org/js/telegram-widget.js?22";
  s.async = true;
  s.setAttribute("data-telegram-login", "__BOT__");
  s.setAttribute("data-size", "large");
  s.setAttribute("data-auth-url", location.origin + "/admin/?tg=1");
  $("tg-widget").appendChild(s);
  const start = (location.hash || "#overview").slice(1);
  if (SECTION_TITLES[start]) showSection(start); else showSection("overview");
  if (params.get("tg") === "1") {
    const user = {};
    params.forEach(function(v, k){ if (k !== "tg") user[k] = v; });
    api("/auth/telegram", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({user})})
      .then(async function(r){ history.replaceState(null, "", location.pathname); if (r.status === 200) { await refreshMe(); await loadDashboard(); await loadSettings(); } });
  } else {
    refreshMe().then(function(ok){ if (ok) { loadDashboard(); loadSettings(); } });
  }
})();
</script>
</body>
</html>
"""


def admin_page(bot_username: str = "") -> str:
    """Готовая страница веб-админки: подставлено имя бота для виджета Telegram."""
    return ADMIN_PAGE.replace("__BOT__", bot_username or "")
