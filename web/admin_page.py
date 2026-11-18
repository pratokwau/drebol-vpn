"""Статическая страница веб-админки Drebol VPN.

Luxury-дизайн сайта: крем #F7F3EB, чернила #0E0E0E, золото #C9B896, Manrope. Левая
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
:root{
  --bg:#F7F3EB; --card:#FFFFFF; --card2:#FDFAF1; --line:#E4DDCC; --line2:#D8CFB8;
  --txt:#0E0E0E; --mut:#6E6A61; --mut2:#9A938A; --acc:#0A0A0A; --acc-dim:#EFE7D3;
  --gold:#C9B896; --dark:#0A0A0A; --dark-2:#161513; --dark-line:#26241F; --dark-mut:#9B968A;
  --ok:#1E7A4C; --warn:#8A5E00; --bad:#C22E2E; --violet:#6D28D9;
  --radius:20px; --ease:cubic-bezier(.22,.61,.36,1);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scrollbar-color:#D8CFB8 #F7F3EB}
body{background:var(--bg);color:var(--txt);font:15px/1.6 "Manrope","Inter",-apple-system,"Segoe UI",sans-serif;min-height:100vh}
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
.layout{display:flex;min-height:100vh}
.sidebar{width:264px;flex:0 0 264px;background:var(--dark);border-right:1px solid var(--dark-line);padding:20px 14px;position:sticky;top:0;height:100vh;overflow-y:auto}
.brand{font-family:"Manrope",sans-serif;font-size:17px;font-weight:800;color:#F7F3EB;padding:2px 10px 16px;border-bottom:1px solid var(--dark-line);margin-bottom:14px}
.brand span{color:var(--gold)}
.brand small{display:block;font-family:"Manrope",sans-serif;font-size:12px;color:var(--dark-mut);margin-top:4px}
.nav-group{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--dark-mut);padding:16px 10px 6px}
.nav-item{display:flex;align-items:center;gap:10px;width:100%;text-align:left;background:none;border:0;border-radius:12px;color:var(--dark-mut);font:600 14.5px "Manrope",sans-serif;padding:9px 10px;cursor:pointer;margin:1px 0;transition:background .25s var(--ease),color .25s var(--ease)}
.nav-item .ic{width:22px;text-align:center;font-size:15px}
.nav-item:hover{background:rgba(255,255,255,.07);color:#F7F3EB}
.nav-item.active{background:rgba(201,184,150,.18);color:#F7F3EB}
.nav-item.active .ic{color:var(--gold)}
.main{flex:1;min-width:0;padding:0 28px 64px}
.topbar{position:sticky;top:0;z-index:20;background:rgba(247,243,235,.92);backdrop-filter:blur(8px);display:flex;align-items:center;gap:16px;padding:16px 0;border-bottom:1px solid var(--line);margin-bottom:22px}
.topbar h1{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.who{color:var(--mut);font-size:13.5px;white-space:nowrap}
.wrap{max-width:1020px}

/* --- Карточки, таблицы, формы --- */
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:20px 22px;margin-top:16px;box-shadow:0 1px 2px rgba(14,14,14,.04),0 10px 30px rgba(14,14,14,.05);transition:transform .35s var(--ease),box-shadow .35s var(--ease)}
.card:hover{transform:translateY(-2px);box-shadow:0 2px 4px rgba(14,14,14,.05),0 16px 40px rgba(14,14,14,.08)}
.card > p.sub{color:var(--mut);font-size:13.5px;margin-bottom:12px}
.card h2 + p.sub{margin-top:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:0 1px 2px rgba(14,14,14,.04),0 10px 30px rgba(14,14,14,.05);transition:transform .35s var(--ease),box-shadow .35s var(--ease)}
.stat:hover{transform:translateY(-3px);box-shadow:0 2px 4px rgba(14,14,14,.05),0 16px 40px rgba(14,14,14,.08)}
.stat b{display:block;font-size:24px;font-family:"Manrope",sans-serif;font-weight:800}
.stat span{color:var(--mut);font-size:13px}
.stat small{display:block;color:var(--mut2);font-size:12px;margin-top:2px}
.chartgrid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.chart text{font:11px "Manrope",sans-serif;fill:var(--mut)}
.chart{overflow:visible}
.hbar{display:flex;align-items:center;gap:10px;margin:9px 0;font-size:13.5px}
.hbar-lab{width:110px;flex:0 0 110px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hbar-track{flex:1;background:var(--card2);border:1px solid var(--line);border-radius:999px;height:12px;overflow:hidden}
.hbar-fill{height:100%;background:var(--acc);border-radius:999px}
.hbar b{min-width:36px;text-align:right;font-variant-numeric:tabular-nums}
.donut-wrap{display:flex;align-items:center;gap:20px;flex-wrap:wrap}
.legend{font-size:13.5px}
.legend div{margin:6px 0;white-space:nowrap}
.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:8px;vertical-align:-1px}
tr[data-sub]{cursor:pointer}
tr[data-sub]:hover td{background:var(--card2)}
input,select,textarea{width:100%;background:var(--card2);border:1px solid var(--line);border-radius:12px;color:var(--txt);padding:10px 12px;font:inherit;margin:6px 0;transition:border-color .2s,box-shadow .2s}
input:focus,select:focus,textarea:focus{outline:2px solid var(--gold);outline-offset:0;border-color:var(--gold)}
textarea{min-height:84px;resize:vertical}
label{font-size:13px;color:var(--mut);display:block;margin-top:8px}
label input[type=checkbox]{width:auto;margin-right:6px}
button{background:var(--acc);color:#F7F3EB;border:0;border-radius:999px;padding:10px 18px;font:700 14px "Manrope",sans-serif;cursor:pointer;margin:6px 6px 0 0;box-shadow:0 8px 20px rgba(14,14,14,.16);transition:transform .3s var(--ease),box-shadow .3s var(--ease),background .2s}
button:hover{transform:translateY(-2px);box-shadow:0 12px 26px rgba(14,14,14,.22)}
button.ghost{background:transparent;color:var(--txt);border:1px solid var(--line2);box-shadow:none}
button.ghost:hover{border-color:var(--txt)}
button.danger{background:transparent;color:var(--bad);border:1px solid rgba(194,46,46,.4);box-shadow:none}
button.danger:hover{border-color:var(--bad)}
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
.pill.ok{background:rgba(30,122,76,.12);color:var(--ok)}
.pill.bad{background:rgba(194,46,46,.10);color:var(--bad)}
.pill.warn{background:rgba(138,94,0,.12);color:var(--warn)}
.pill.info{background:rgba(14,14,14,.08);color:var(--acc)}
.pill.grey{background:rgba(110,106,97,.12);color:var(--mut)}
.kv{display:grid;grid-template-columns:180px 1fr;gap:6px 14px;font-size:14px}
.kv dt{color:var(--mut)}
.kv dd{word-break:break-word}
.empty{text-align:center;color:var(--mut);padding:26px 10px}
.empty .big{font-size:26px;display:block;margin-bottom:6px}
pre{white-space:pre-wrap;word-break:break-word;font:13px/1.55 ui-monospace,Menlo,Consolas,monospace;background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:12px;margin-top:10px}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;background:var(--card2);border:1px solid var(--line);border-radius:6px;padding:1px 5px}
details{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:10px;background:var(--card2)}
details summary{cursor:pointer;font-weight:700;font-size:14px}
details p,details ul{margin-top:8px}
#toast{position:fixed;right:20px;bottom:20px;z-index:50;display:flex;flex-direction:column;gap:8px;max-width:360px}
.toast{background:var(--dark);color:#F7F3EB;border:1px solid var(--dark-line);border-left:4px solid var(--gold);border-radius:12px;padding:12px 16px;font-size:14px;box-shadow:0 12px 30px rgba(14,14,14,.3);animation:toastIn .3s var(--ease) backwards}
.toast.err{border-left-color:var(--bad)}
.toast.ok{border-left-color:var(--ok)}
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--line2);border-top-color:var(--acc);border-radius:50%;animation:sp 0.8s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes sp{to{transform:rotate(360deg)}}
.loginwrap{max-width:460px;margin:80px auto 0;padding:0 18px}
.loginwrap .card{padding:26px}

/* --- Редактор записи: выезжающая панель --- */
.drawer-overlay{position:fixed;inset:0;z-index:60;background:rgba(14,14,14,.45);backdrop-filter:blur(2px);opacity:0;pointer-events:none;transition:opacity .3s var(--ease)}
.drawer-overlay.open{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;bottom:0;z-index:61;width:min(560px,100%);background:var(--card2);box-shadow:-20px 0 60px rgba(14,14,14,.25);transform:translateX(100%);transition:transform .35s var(--ease);display:flex;flex-direction:column}
.drawer.open{transform:none}
.drawer-head{background:var(--dark);color:#F7F3EB;padding:18px 22px;display:flex;align-items:flex-start;gap:12px}
.drawer-head h2{color:#F7F3EB;font-size:17px}
.drawer-head .sub{color:var(--dark-mut);font-size:13px}
.drawer-close{margin-left:auto;background:transparent;border:1px solid var(--dark-line);color:#F7F3EB;border-radius:999px;width:34px;height:34px;padding:0;box-shadow:none;flex:0 0 auto;font-size:16px;line-height:1}
.drawer-close:hover{border-color:var(--gold);transform:none}
.drawer-body{padding:18px 22px 28px;overflow-y:auto}
.drawer-foot{padding:14px 22px;border-top:1px solid var(--line);display:flex;gap:8px;flex-wrap:wrap;background:var(--card)}

/* --- Скелетоны загрузки --- */
.skel{border-radius:8px;background:linear-gradient(90deg,#EFE7D3 25%,#F7F3EB 50%,#EFE7D3 75%);background-size:200% 100%;animation:shimmer 1.2s linear infinite}
@media (max-width:900px){
  .layout{display:block}
  .sidebar{position:static;width:100%;height:auto;border-right:0;border-bottom:1px solid var(--dark-line);padding:12px}
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
      <button class="nav-item" data-nav="promos"><span class="ic">🏷️</span>Промокоды</button>
      <button class="nav-item" data-nav="tariffs"><span class="ic">💲</span>Тарифы</button>
      <div class="nav-group">Инфраструктура</div>
      <button class="nav-item" data-nav="panel"><span class="ic">🖥️</span>Панель Remnawave</button>
      <button class="nav-item" data-nav="nodes"><span class="ic">🌐</span>Узлы</button>
      <button class="nav-item" data-nav="logs"><span class="ic">📜</span>Логи</button>
      <button class="nav-item" data-nav="sync"><span class="ic">⏰</span>Синхронизация</button>
      <button class="nav-item" data-nav="netcheck"><span class="ic">📡</span>Проверка операторов</button>
      <button class="nav-item" data-nav="site"><span class="ic">🌍</span>Сайт</button>
      <button class="nav-item" data-nav="backup"><span class="ic">💾</span>Бэкап</button>
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
        <div class="card"><h2>Выручка и новые юзеры — 30 дней</h2><p class="sub">Выручка — нетто: оплаченные счета минус возвраты. Наведи курсор на столбец или точку — увидишь дату и значение.</p>
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
        <div class="card"><h2>Пользователи</h2><p class="sub">Все пользователи. Нажми на строку, чтобы открыть карточку. Поиск — по ID, @username, имени или email.</p>
          <input id="q-user" placeholder="Поиск: имя, @username, email, tg_id" style="flex:1;min-width:200px">
          <div class="btnrow"><button id="btn-find">Найти</button><button id="btn-recent" class="ghost">Недавние</button><button id="btn-users-prev" class="ghost">← Назад</button><button id="btn-users-next" class="ghost">Вперёд →</button><span id="users-page-label" class="mut"></span></div>
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
        <div class="card"><h2>Повторные триалы</h2><p class="sub">Пары аккаунтов, которые, возможно, берут триал повторно.</p>
          <div class="btnrow"><button id="btn-fraud" class="ghost">Показать пары</button><button id="btn-fraud-scan" class="ghost">Запустить скан</button></div>
          <input id="fraud-a" type="number" placeholder="tg_id первого аккаунта пары">
          <input id="fraud-b" type="number" placeholder="tg_id второго аккаунта пары (other_tg)">
          <button id="btn-fraud-stop" class="ghost">Остановить пару</button>
          <div id="fraud-out"></div>
        </div>
      </section>

      <!-- Подписки -->
      <section id="sec-subs" class="page hidden">
        <div class="card"><h2>Платные подписки</h2><p class="sub">Все платные подписки. Нажми на строку, чтобы открыть и поменять параметры — изменения сразу уходят в базу бота и в панель Remnawave. Удаление и перевыпуск — с подтверждением.</p>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <input id="subs-q" placeholder="Поиск: имя, @username, email, tg_id" style="flex:1;min-width:200px">
            <select id="subs-status" style="width:auto;min-width:150px">
              <option value="">Все статусы</option>
              <option value="active">Активна</option>
              <option value="expired">Истекла</option>
              <option value="frozen">Заморожена</option>
            </select>
            <button id="btn-subs-search">Найти</button>
            <button id="btn-subs-refresh" class="ghost">Обновить</button>
          </div>
          <div id="subs-table"></div>
          <div class="btnrow" style="margin-top:10px;align-items:center">
            <button id="btn-subs-prev" class="ghost">← Назад</button>
            <span class="mut" id="subs-page-label"></span>
            <button id="btn-subs-next" class="ghost">Вперёд →</button>
          </div>
        </div>
        <div class="card"><h2>Массовые действия</h2><p class="sub">Применяются ко всем активным платным подпискам.</p>
          <select id="bulk-kind"><option value="extend">Продлить всем</option><option value="limits">Сменить лимиты всем</option><option value="lte">Сменить LTE всем</option></select>
          <input id="bulk-days" type="number" placeholder="дней (+ продлить / − сократить)">
          <input id="bulk-value" type="number" placeholder="значение лимита, ГБ">
          <select id="bulk-kind-limit"><option value="">лимит: трафик</option><option value="hwid">лимит: устройства</option><option value="lte">лимит: LTE</option></select>
          <button id="btn-bulk">Применить ко всем</button>
          <div id="bulk-out"></div>
        </div>
        <div class="card"><h2>Пресеты подписок</h2><p class="sub">Значения по умолчанию для новых платных подписок.</p>
          <div class="btnrow"><button id="btn-presets" class="ghost">Показать пресеты</button></div>
          <div id="presets-out"></div>
        </div>
        <div class="card"><h2>Админские подписки</h2><p class="sub">Подписки, выданные вручную администратором.</p>
          <input id="asub-tg" type="number" placeholder="tg_id — создать админскую подписку">
          <div class="btnrow"><button id="btn-asub" class="ghost">Создать админскую подписку</button><button id="btn-asub-list" class="ghost">Список админских</button></div>
          <input id="asub-id" type="number" placeholder="ID админской подписки — показать карточку">
          <div class="btnrow"><button id="btn-asub-card" class="ghost">Показать карточку</button></div>
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
          <select id="fin-period"><option value="day">День</option><option value="week">Неделя</option><option value="month" selected>Месяц</option><option value="all">Всё время</option></select>
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
            <select id="pay-status" style="width:auto;min-width:170px"><option value="">Все статусы</option><option value="paid">Оплаченные</option><option value="pending">Ожидают</option><option value="refunded">Возвращённые</option><option value="failed">Неудачные</option></select>
            <button id="btn-payments">Показать оплаты</button>
          </div>
          <div id="payments-out"></div>
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
      </section>

      <!-- Промокоды -->
      <section id="sec-promos" class="page hidden">
        <div class="card"><h2>Промокоды</h2><p class="sub">Скидки и бонусы для новых и действующих пользователей. Нажми на строку, чтобы изменить промокод, выключить его или удалить.</p>
          <div class="btnrow"><button id="btn-promos">Показать промокоды</button></div>
          <input id="pr-code" placeholder="код, напр. DREBOL10">
          <input id="pr-exp" placeholder="истекает, напр. 2026-12-31 (пусто — без срока)">
          <input id="pr-owner" type="number" placeholder="tg_id владельца (необязательно)">
          <input id="pr-note" placeholder="заметка (необязательно)">
          <div class="btnrow"><button id="btn-pr-add">Создать промокод</button><button id="btn-pr-find" class="ghost">Найти по коду</button></div>
          <input id="pr-count" type="number" placeholder="сколько кодов сгенерировать пачкой">
          <div class="btnrow"><button id="btn-pr-batch" class="ghost">Сгенерировать пачку</button></div>
          <div id="promos-out"></div>
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
          <div class="btnrow"><button id="btn-panel" class="ghost">Обновить списки</button><button id="btn-yandex" class="ghost">Яндекс Клауд: зеркало</button></div>
          <div id="panel-out"></div>
          <h3>Профили</h3>
          <div id="profiles-table"></div>
          <h3>Хосты</h3>
          <div id="hosts-table"></div>
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
        <div class="card" id="panel-hosts-card"><h2>Хосты</h2><p class="sub">Новый хост создаётся выключенным — включите его после проверки.</p>
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
          <div class="btnrow"><button id="btn-nodes">Здоровье узлов</button><button id="btn-squads" class="ghost">Сквады</button></div>
          <div id="nodes-table"></div>
          <input id="node-id" placeholder="UUID ноды — или клик по строке таблицы">
          <input id="node-start" placeholder="с даты, напр. 2026-11-01 (пусто — 30 дней назад)">
          <input id="node-end" placeholder="по дату, напр. 2026-11-15 (пусто — сегодня)">
          <div class="btnrow"><button id="btn-node-users" class="ghost">Трафик ноды</button></div>
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
          <select id="logs-kind"><option value="activity">Действия</option><option value="error">Ошибки</option></select>
          <input id="logs-user" type="number" placeholder="tg_id (необязательно)">
          <input id="logs-from" placeholder="с даты, напр. 2026-11-01">
          <input id="logs-to" placeholder="по дату, напр. 2026-11-15">
          <div class="btnrow"><button id="btn-logs">Показать журнал</button><a id="btn-logs-export" href="/api/admin/logs/export?kind=activity"><button type="button" class="ghost">Скачать CSV</button></a><button id="btn-logs-purge" class="danger">Очистить старые записи</button></div>
          <div id="logs-out"></div>
        </div>
        <div class="card"><h2>Падения и сбои</h2><p class="sub">Когда узлы и панель были недоступны.</p>
          <div class="btnrow"><button id="btn-downtime" class="ghost">Показать падения</button><button id="btn-online" class="ghost">Кто онлайн</button></div>
          <div id="downtime-out"></div>
        </div>
      </section>

      <!-- Синхронизация -->
      <section id="sec-sync" class="page hidden">
        <div class="card"><h2>Синхронизация с панелью</h2><p class="sub">Сверка пользователей бота с клиентами Remnawave.</p>
          <div class="btnrow"><button id="btn-psync">Запустить синхронизацию</button><button id="btn-psync-set" class="ghost">Показать расписание</button></div>
          <div id="psync-out"></div>
        </div>
        <div class="card"><h2>Утренняя сводка 09:00</h2><p class="sub">Что входит в ежедневную сводку и во сколько она приходит.</p>
          <div class="btnrow"><button id="btn-morning">Показать настройки</button><button id="btn-morning-run">Запустить сводку сейчас</button></div>
          <input id="mor-time" placeholder="время, напр. 09:00 (пусто — не менять)">
          <label><input id="mor-enabled" type="checkbox"> сводка включена</label>
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
          <div class="btnrow"><button id="btn-site-show" class="ghost">Показать состояние</button><button id="btn-deploy">Деплой сайта</button></div>
          <div id="site-out"></div>
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
        <div class="card"><h2>Бэкап и перенос</h2><p class="sub">Архив базы и настроек. Восстановление — только Mark, с подтверждением, и только после свежего бэкапа: текущие данные будут заменены, бот перезапустится.</p>
          <div class="btnrow"><a id="btn-backup" href="/api/admin/backup/export"><button type="button" class="ghost">Скачать бэкап</button></a></div>
          <label>Файл архива (.zip)</label>
          <input id="bk-file" type="file" accept=".zip,application/zip">
          <label><input id="bk-fresh" type="checkbox"> свежий бэкап сделан, я понимаю, что данные заменятся</label>
          <div class="btnrow"><button id="btn-backup-restore" class="danger">Восстановить из архива</button></div>
          <div id="backup-out"></div>
        </div>
        <div class="card"><h2>Обновление с GitHub</h2><p class="sub">Mark и Muse. Подтягивает main и перезапускает бота и сап-бота.</p>
          <button id="btn-git" class="danger">Обновиться с GitHub</button>
          <div id="git-out"></div>
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
          <input id="helper-tg" type="number" placeholder="tg_id помощника">
          <select id="helper-perm-sel"><option value="users">users</option><option value="dm">dm</option></select>
          <div class="btnrow"><button id="btn-helper-add" class="ghost">Добавить</button><button id="btn-helper-perm" class="ghost">Переключить право</button><button id="btn-helper-del" class="danger">Удалить</button><button id="btn-helpers" class="ghost">Список</button></div>
          <div id="helpers-out"></div>
        </div>
        <div class="card"><h2>Веб-доступ</h2><p class="sub">Смена порта/bind вступает в силу только после рестарта бота. Выключить сам веб-API из веба нельзя — это убьёт и эту админку, делается только из ТГ.</p>
          <div class="btnrow"><button id="btn-webacc" class="ghost">Показать настройки</button></div>
          <input id="wa-port" type="number" placeholder="порт, напр. 8088">
          <input id="wa-bind" placeholder="bind: 127.0.0.1 или 0.0.0.0">
          <div class="btnrow"><button id="btn-wa-save" class="ghost">Сохранить порт/bind</button></div>
          <div id="wa-out"></div>
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
const SECTION_TITLES = {overview:"Обзор", users:"Пользователи", subs:"Подписки", finance:"Финансы", payments:"Оплаты", broadcast:"Рассылка", promos:"Промокоды", tariffs:"Тарифы", panel:"Панель Remnawave", nodes:"Узлы", logs:"Логи", sync:"Синхронизация", netcheck:"Проверка операторов", site:"Сайт", backup:"Бэкап", support:"Поддержка", settings:"Настройки"};
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
    s += '<line x1="' + PL + '" y1="' + y.toFixed(1) + '" x2="' + (W - 4) + '" y2="' + y.toFixed(1) + '" stroke="#E4DDCC"/>';
    s += '<text x="' + (PL - 6) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end">' + fmtNum(Math.round(max * f)) + '</text>';
  });
  series.forEach(function(p, i){
    const h = p.sum > 0 ? Math.max(2, (p.sum / max) * (H - PT - PB)) : 0;
    const x = PL + i * bw + 1, y = H - PB - h;
    s += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + Math.max(1, bw - 2).toFixed(1) + '" height="' + h.toFixed(1) + '" rx="1.5" fill="#0E0E0E"><title>' + fmtDay(p.date) + ' · ' + esc(fmtVal(p.sum)) + '</title></rect>';
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
    s += '<line x1="' + PL + '" y1="' + y.toFixed(1) + '" x2="' + (W - 4) + '" y2="' + y.toFixed(1) + '" stroke="#E4DDCC"/>';
    s += '<text x="' + (PL - 6) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end">' + fmtNum(Math.round(max * f)) + '</text>';
  });
  const line = pt.map(function(p){ return p.x.toFixed(1) + "," + p.y.toFixed(1); }).join(" ");
  s += '<polygon points="' + PL + ',' + (H - PB) + ' ' + line + ' ' + pt[pt.length - 1].x.toFixed(1) + ',' + (H - PB) + '" fill="#C9B896" opacity="0.25"/>';
  s += '<polyline points="' + line + '" fill="none" stroke="#0E0E0E" stroke-width="2" stroke-linejoin="round"/>';
  pt.forEach(function(p, i){
    s += '<circle cx="' + p.x.toFixed(1) + '" cy="' + p.y.toFixed(1) + '" r="2.6" fill="#0E0E0E"><title>' + fmtDay(p.d) + ' · +' + p.v + '</title></circle>';
    if (i % 5 === 0) s += '<text x="' + p.x.toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle">' + fmtDay(p.d) + '</text>';
  });
  return s + '</svg>';
}
function donutChart(parts){
  const colors = ["#0E0E0E", "#C9B896", "#1E7A4C", "#C22E2E", "#8A5E00", "#9A938A"];
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
  const kpi = $("kpi-expiring");
  if (kpi) kpi.textContent = fmtNum(items.length);
  if (!items.length) { $("expiring-out").innerHTML = '<div class="empty"><span class="big">✅</span>В ближайшие 3 дня ничего не истекает</div>'; return; }
  $("expiring-out").innerHTML = '<div class="tblwrap"><table><thead><tr><th>Пользователь</th><th>Подписка</th><th>Истекает</th><th>Статус</th><th></th></tr></thead><tbody>' +
    items.map(function(it){
      const name = esc(it.name || "—") + (it.username ? ' <span class="mut">@' + esc(it.username) + '</span>' : "") + ' <span class="mono small">#' + it.tg_id + '</span>';
      return '<tr><td>' + name + '</td><td><span class="mono">#' + it.sub_id + '</span></td><td><span class="mono">' + fmtDate(it.expire_date) + '</span></td><td>' + pill(statusRu(it.status)) + '</td><td><button class="ghost" data-open-sub="' + it.sub_id + '">Открыть</button></td></tr>';
    }).join("") + "</tbody></table></div>";
}
async function loadDashboard(){
  const r = await api("/dashboard");
  if (r.status !== 200) return;
  const s = r.data.stats || {};
  const m = r.data.money || {};
  const today = m.today || [0, 0], month = m.month || [0, 0];
  const cells = [
    ["Выручка сегодня", fmtMoney(today[1]), "оплат: " + fmtNum(today[0])],
    ["Выручка за 30 дней", fmtMoney(month[1]), "оплат: " + fmtNum(month[0])],
    ["Активных подписок", fmtNum(s.paid_active), "платящих: " + fmtNum(s.paying_active)],
    ["Новых сегодня", "+" + fmtNum(s.users_today || 0), "за неделю: +" + fmtNum(s.users_week || 0)],
    ["Пользователей", fmtNum(s.users_total), "платили: " + fmtNum(m.payers || 0)],
    ["Истекает ≤ 3 дней", '<span id="kpi-expiring">…</span>', ""]
  ];
  $("stats").innerHTML = cells.map(function(c){
    return '<div class="stat"><b>' + c[1] + '</b><span>' + c[0] + "</span>" + (c[2] ? "<small>" + c[2] + "</small>" : "") + "</div>";
  }).join("");
  const p = r.data.panel || {};
  $("panel-line").textContent = p.success ?
    ("Панель: клиентов " + fmtNum(p.total) + " (платных " + fmtNum(p.paid) + ")") :
    "Панель недоступна — сверка не выполнена";
  const rs = await api("/dashboard/series");
  if (rs.status === 200) {
    const d = rs.data || {};
    $("chart-revenue").innerHTML = barChart(d.revenue || [], function(v){ return fmtMoney(v); });
    $("chart-users").innerHTML = lineChart(d.users || []);
    $("chart-status").innerHTML = donutChart((d.by_status || []).map(function(x){ return {label: statusRu(x.status), count: x.count}; }));
    $("chart-term").innerHTML = hbars((d.by_term || []).map(function(x){ return {label: x.term_days ? fmtDays(x.term_days * 86400) : "Триал", count: x.count}; }));
  }
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
  $("quick-upd-msg").textContent = r.status === 200 ? "Обновление запущено: бот перезапускается, страница обновится сама." : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) toast("Обновление с GitHub запущено", "ok");
});
$("btn-quick-deploy").onclick = withSpin($("btn-quick-deploy"), async function(){
  const r = await postConfirm("/site/deploy", {});
  $("quick-upd-msg").textContent = r.status === 200 ? "Сайт развёрнут." : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) toast("Сайт развёрнут", "ok");
});
const EDITABLE = ["channel_url","force_subscribe","paid_trial_period","paid_preset_hwid","paid_preset_traffic","paid_preset_lte","referral_bonus","referral_invited_bonus","maintenance_enabled","maintenance_text","device_price","device_max_extra"];
async function loadSettings(){
  const r = await api("/settings");
  if (r.status !== 200) return;
  const s = r.data.settings || {};
  $("settings").innerHTML = EDITABLE.map(function(k){
    const v = s[k];
    const type = typeof v === "boolean" ? "checkbox" : (typeof v === "number" ? "number" : "text");
    const val = type === "checkbox" ? (v ? "checked" : "") : ('value="' + (v == null ? "" : String(v).replace(/"/g, "&quot;")) + '"');
    return "<label>" + esc(k) + '<input data-k="' + k + '" type="' + type + '" ' + val + "></label>";
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
    patch[inp.dataset.k] = inp.type === "checkbox" ? inp.checked : (inp.type === "number" ? parseInt(inp.value || "0", 10) : inp.value);
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
      return '<tr data-tg="' + u.tg_id + '"><td>' + esc(u.name) + '</td><td class="mono">@' + esc(u.username) + '</td><td class="mono">' + u.tg_id + '</td><td>' + (u.sub ? pill(u.sub) : "—") + '</td><td class="mono">' + fmtDate(u.date) + "</td></tr>";
    }).join("") + "</tbody></table></div>";
  host.querySelectorAll("tr[data-tg]").forEach(function(tr){
    tr.onclick = function(){ openUserEditor(parseInt(tr.dataset.tg, 10)); };
  });
}
let usersPage = 1, usersTotalPages = 1, usersLoaded = false;
async function loadUsers(page){
  usersPage = page;
  const q = $("q-user").value.trim();
  $("users-out").innerHTML = '<div class="skel" style="height:18px;width:90%;margin-bottom:8px"></div><div class="skel" style="height:18px;width:70%;margin-bottom:8px"></div><div class="skel" style="height:120px"></div>';
  let r;
  try { r = await api("/users/list?page=" + page + (q ? "&q=" + encodeURIComponent(q) : "")); }
  catch(e) { $("users-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("users-out", r.data); return; }
  usersTotalPages = r.data.total_pages || 1;
  $("users-page-label").textContent = "Стр. " + r.data.page + " из " + usersTotalPages;
  const rows = (r.data.users || []).map(function(u){
    return {tg_id: u.tg_id, name: u.first_name || "", username: u.username || "", sub: u.sub_status || "", date: u.created_at || ""};
  });
  renderUsersTable($("users-out"), rows, "Создан");
}
$("btn-find").onclick = withSpin($("btn-find"), async function(){ loadUsers(1); });
$("q-user").addEventListener("keydown", function(e){ if (e.key === "Enter") loadUsers(1); });
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
    h += kvRow("Email подписки", '<span class="mono">' + esc(s.email || "") + '</span>');
  } else h += kvRow("Подписка", "нет");
  if (d.referral) h += kvRow("Рефералка", "пригласил " + (d.referral.invited || 0) + " · вознаграждено " + (d.referral.rewarded || 0));
  if (d.payments_total) h += kvRow("Оплат", d.payments_total.count + " на " + fmtMoney(d.payments_total.sum));
  if (d.blacklist) h += kvRow("Чёрный список", esc(d.blacklist.reason || d.blacklist.source || ""));
  h += '</dl>';
  if ((d.payments || []).length) {
    h += '<h3>Последние оплаты</h3><div class="tblwrap"><table><thead><tr><th>ID</th><th>Сумма</th><th>Статус</th><th>Дата</th></tr></thead><tbody>';
    d.payments.forEach(function(p){
      h += '<tr><td class="mono">' + p.id + '</td><td class="num">' + fmtMoney(p.amount) + '</td><td>' + statusPill(p.status, PAY_LABELS[p.status] || p.status) + '</td><td><span class="mono">' + fmtDate(p.date) + '</span></td></tr>';
    });
    h += '</tbody></table></div>';
  }
  $("drawer-body").innerHTML = h;
  $("drawer-foot").innerHTML = '<button class="ghost" id="ed-user-dm">Написать</button><button class="ghost" id="ed-user-gift">Подарить подписку</button>' + (d.subscription ? '<button class="ghost" id="ed-user-sub">Открыть подписку</button>' : "");
  $("ed-user-dm").onclick = function(){ closeDrawer(); showSection("users"); $("dm-id").value = tgId; $("dm-text").focus(); window.scrollTo(0, 0); };
  $("ed-user-gift").onclick = function(){ closeDrawer(); showSection("users"); $("gift-tg").value = tgId; $("gift-amount").focus(); window.scrollTo(0, 0); };
  const sb = $("ed-user-sub");
  if (sb) sb.onclick = function(){ openSubEditor(d.subscription.id); };
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
    h += '<tr data-tg="' + e.tg_id + '"><td>' + esc(e.first_name || "") + '</td><td class="mono">@' + esc(e.username || "") + '</td><td class="mono">' + e.tg_id + '</td><td>' + esc(e.reason || "") + '</td></tr>';
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
$("btn-fraud").onclick = async function(){
  const r = await api("/fraud");
  if (r.status !== 200) { renderOut("fraud-out", r.data); return; }
  const rows = r.data.pairs || [];
  if (!rows.length) { $("fraud-out").innerHTML = '<div class="empty">Подозрительных пар нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Аккаунт A</th><th>Аккаунт B</th><th>Совпадение</th><th>Статус</th></tr></thead><tbody>';
  rows.forEach(function(p){
    h += '<tr data-a="' + p.tg_a + '" data-b="' + p.tg_b + '"><td class="mono">' + p.tg_a + '</td><td class="mono">' + p.tg_b + '</td><td>' + esc(p.kind + ": " + p.value) + '</td><td>' + statusPill(p.status, p.status) + '</td></tr>';
  });
  h += '</tbody></table></div>';
  $("fraud-out").innerHTML = h;
  $("fraud-out").querySelectorAll("tr[data-a]").forEach(function(tr){
    tr.onclick = function(){ $("fraud-a").value = tr.dataset.a; $("fraud-b").value = tr.dataset.b; };
  });
};
$("btn-fraud-scan").onclick = withSpin($("btn-fraud-scan"), async function(){
  const r = await postConfirm("/fraud/scan", {});
  renderOut("fraud-out", r.data);
});
$("btn-fraud-stop").onclick = async function(){
  const r = await postConfirm("/fraud/" + $("fraud-a").value + "/stop", {other_tg: parseInt($("fraud-b").value || "0", 10)});
  renderOut("fraud-out", r.data);
};

/* --- Подписки: список + редактор --- */
let subsPage = 1, subsTotalPages = 1, subsLoaded = false, subsCurrentId = null;
function statusPill(code, label){
  const s = String(code == null ? "" : code).toLowerCase();
  const cls = ["active","paid","ok","success","online","enabled","true","1"].indexOf(s) >= 0 ? "ok"
    : ["expired","refunded","failed","error","offline","disabled","false","0","blocked","banned"].indexOf(s) >= 0 ? "bad"
    : ["pending","trial","warning","frozen","paused"].indexOf(s) >= 0 ? "warn" : "info";
  return '<span class="pill ' + cls + '">' + esc(label == null ? code : label) + "</span>";
}
function subStatusPill(s){ return statusPill(s, s === "active" ? "Активна" : s === "expired" ? "Истекла" : s === "frozen" ? "Заморожена" : (s || "—")); }
async function loadSubs(page){
  const q = encodeURIComponent($("subs-q").value.trim());
  const st = $("subs-status").value;
  let r;
  try { r = await api("/subs?page=" + page + (q ? "&q=" + q : "") + (st ? "&status=" + st : "")); }
  catch(e) { $("subs-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { $("subs-table").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  const items = r.data.subs || [];
  subsPage = r.data.page || page; subsTotalPages = r.data.total_pages || 1;
  $("subs-page-label").textContent = "Страница " + subsPage + " из " + subsTotalPages;
  show("btn-subs-prev", subsPage > 1); show("btn-subs-next", subsPage < subsTotalPages);
  if (!items.length) { $("subs-table").innerHTML = '<div class="empty"><span class="big">🔍</span>Подписок не найдено</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Пользователь</th><th>Email</th><th>Статус</th><th>Истекает</th><th>Трафик</th><th>Устройства</th></tr></thead><tbody>';
  items.forEach(function(it){
    const name = esc(it.first_name || "—") + (it.username ? ' <span class="mut">@' + esc(it.username) + '</span>' : "") + ' <span class="mono small">#' + it.tg_id + '</span>';
    h += '<tr data-sub-id="' + it.id + '"><td>' + name + '</td><td class="trunc"><span class="mono">' + esc(it.email || "") + '</span></td><td>' + subStatusPill(it.status) + '</td><td><span class="mono">' + fmtDate(it.expire_date) + '</span></td><td class="num">' + (it.total_gb || 0) + ' ГБ</td><td class="num">' + (it.limit_hwid || 0) + '</td></tr>';
  });
  $("subs-table").innerHTML = h + '</tbody></table></div>';
}
$("btn-subs-search").onclick = function(){ loadSubs(1); };
$("btn-subs-refresh").onclick = function(){ loadSubs(subsPage); };
$("subs-q").addEventListener("keydown", function(e){ if (e.key === "Enter") loadSubs(1); });
$("subs-status").onchange = function(){ loadSubs(1); };
$("btn-subs-prev").onclick = function(){ if (subsPage > 1) loadSubs(subsPage - 1); };
$("btn-subs-next").onclick = function(){ if (subsPage < subsTotalPages) loadSubs(subsPage + 1); };
$("subs-table").addEventListener("click", function(e){
  const tr = e.target.closest("tr[data-sub-id]");
  if (tr) openSubEditor(parseInt(tr.dataset.subId, 10));
});
document.querySelector('[data-nav="subs"]').addEventListener("click", function(){
  if (!subsLoaded) { subsLoaded = true; loadSubs(1); }
});

/* --- Редактор записи (drawer) --- */
function openDrawer(){ $("drawer-overlay").classList.add("open"); $("drawer").classList.add("open"); $("drawer").setAttribute("aria-hidden", "false"); }
function closeDrawer(){ $("drawer-overlay").classList.remove("open"); $("drawer").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true"); }
$("drawer-close").onclick = closeDrawer;
$("drawer-overlay").onclick = closeDrawer;
document.addEventListener("keydown", function(e){ if (e.key === "Escape") closeDrawer(); });
function kvRow(k, v){ return "<dt>" + esc(k) + "</dt><dd>" + v + "</dd>"; }
async function openSubEditor(id){
  subsCurrentId = id;
  $("drawer-title").textContent = "Подписка #" + id;
  $("drawer-sub").textContent = "Загрузка…";
  $("drawer-body").innerHTML = '<div class="skel" style="height:18px;width:70%;margin-bottom:10px"></div><div class="skel" style="height:18px;width:50%;margin-bottom:10px"></div><div class="skel" style="height:120px"></div>';
  $("drawer-foot").innerHTML = "";
  openDrawer();
  let r;
  try { r = await api("/subs/" + id); }
  catch(e) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить подписку</p>'; return; }
  if (r.status !== 200) { $("drawer-body").innerHTML = '<p class="err">Не удалось загрузить подписку</p>'; return; }
  renderSubEditor(r.data);
}
function renderSubEditor(data){
  const s = data.subscription || {};
  const p = data.panel || {};
  $("drawer-title").textContent = "Подписка #" + s.id;
  $("drawer-sub").textContent = (s.first_name || "") + (s.username ? " @" + s.username : "") + " · tg #" + s.tg_id;
  let h = '<dl class="kv">';
  h += kvRow("Email", '<span class="mono">' + esc(s.email || "") + '</span>');
  h += kvRow("UUID", '<span class="mono">' + esc(s.uuid || "") + '</span>');
  h += kvRow("Sub ID", '<span class="mono">' + esc(s.sub_id || "") + '</span>');
  h += kvRow("Истекает", '<span class="mono">' + fmtDate(s.expire_date) + '</span>');
  h += kvRow("Статус", subStatusPill(s.status));
  h += kvRow("Продлений", s.times_renewed == null ? "—" : s.times_renewed);
  h += kvRow("Лимит трафика", (s.total_gb || 0) + " ГБ");
  h += kvRow("Лимит устройств", s.limit_hwid == null ? "—" : s.limit_hwid);
  h += kvRow("LTE", s.lte_gb == null ? "без лимита" : s.lte_gb + " ГБ");
  h += kvRow("Триал, дней", s.trial_period == null ? "—" : s.trial_period);
  if (p && typeof p.enabled !== "undefined") h += kvRow("В панели", p.enabled ? "включена" : "выключена");
  h += '</dl>';
  h += '<h3>Продлить / изменить</h3>';
  h += '<label>Продлить на дней<input id="ed-days" type="number" placeholder="дней"></label><div class="btnrow"><button class="ghost" data-ed="extend">Продлить</button></div>';
  h += '<label>Новая дата истечения<input id="ed-until" placeholder="напр. 2026-12-31 23:59" value="' + esc(s.expire_date || "") + '"></label><div class="btnrow"><button class="ghost" data-ed="expire">Установить дату</button></div>';
  h += '<label>Лимит устройств (HWID)<input id="ed-hwid" type="number" value="' + (s.limit_hwid || 0) + '"></label><div class="btnrow"><button class="ghost" data-ed="hwid">Сохранить лимит</button></div>';
  h += '<label>Лимит трафика, ГБ<input id="ed-traffic" type="number" value="' + (s.total_gb || 0) + '"></label><div class="btnrow"><button class="ghost" data-ed="traffic">Сохранить лимит</button></div>';
  h += '<label>Лимит LTE, ГБ (пусто — без лимита)<input id="ed-lte" type="number" value="' + (s.lte_gb == null ? "" : s.lte_gb) + '"></label><div class="btnrow"><button class="ghost" data-ed="lte">Сохранить LTE</button></div>';
  h += '<label>Триал, дней<input id="ed-trial" type="number" value="' + (s.trial_period || 0) + '"></label><div class="btnrow"><button class="ghost" data-ed="trial">Установить триал</button></div>';
  h += '<h3>Устройства</h3><div class="btnrow"><button class="ghost" id="ed-devices">Показать устройства</button></div><div id="ed-devices-out"></div>';
  h += '<p class="mut" id="ed-msg" style="margin-top:10px"></p>';
  $("drawer-body").innerHTML = h;
  $("drawer-foot").innerHTML = '<button class="ghost" data-ed="toggle">Вкл / выкл</button><button class="ghost" data-ed="freeze">Заморозить</button><button class="ghost" data-ed="reissue">Перевыпустить</button><button class="danger" data-ed="delete">Удалить</button>';
  const bind = function(root){
    root.querySelectorAll("[data-ed]").forEach(function(b){
      b.onclick = withSpin(b, function(){ return subEditorAction(b.dataset.ed); });
    });
  };
  bind($("drawer-body")); bind($("drawer-foot"));
  $("ed-devices").onclick = async function(){
    const r = await api("/subs/" + subsCurrentId + "/devices");
    renderOut("ed-devices-out", r.data);
  };
}
async function subEditorAction(a){
  const id = subsCurrentId;
  let body = {};
  if (a === "extend") body = {days: parseInt($("ed-days").value || "0", 10)};
  if (a === "expire") body = {until: $("ed-until").value};
  if (a === "hwid") body = {limit: parseInt($("ed-hwid").value || "0", 10)};
  if (a === "traffic") body = {gb: parseInt($("ed-traffic").value || "0", 10)};
  if (a === "lte") { const v = $("ed-lte").value.trim(); body = v === "" ? {gb: null} : {gb: parseInt(v, 10)}; }
  if (a === "trial") body = {period_days: parseInt($("ed-trial").value || "0", 10)};
  const r = await postConfirm("/subs/" + id + "/" + a, body);
  const msg = $("ed-msg");
  if (msg) msg.textContent = r.status === 200 ? "Готово" : ("Ошибка: " + (r.data.error || r.status));
  if (r.status === 200) {
    toast("Подписка обновлена", "ok");
    const c = await api("/subs/" + id);
    if (c.status === 200) renderSubEditor(c.data);
    loadSubs(subsPage);
  }
}
$("btn-bulk").onclick = async function(){
  const kind = $("bulk-kind").value;
  const body = {};
  if (kind === "extend") { body.days = parseInt($("bulk-days").value || "0", 10); body.direction = body.days >= 0 ? "extend" : "reduce"; }
  else { body.value = parseInt($("bulk-value").value || "0", 10); body.kind_limit = $("bulk-kind-limit").value || "hwid"; }
  const r = await postConfirm("/subs/bulk/" + kind, body);
  renderOut("bulk-out", r.data);
};
$("btn-presets").onclick = async function(){
  const r = await api("/subs/presets");
  renderOut("presets-out", r.data);
  if (r.status === 200 && r.data.presets) {
    const p = r.data.presets;
    const div = document.createElement("div");
    div.innerHTML = '<h3>Изменить пресеты</h3>' +
      '<label>Триал, дней<input id="pr-trial" type="number" value="' + (p.paid_trial_period || 0) + '"></label>' +
      '<label>Лимит устройств<input id="pr-hwid" type="number" value="' + (p.paid_preset_hwid || 0) + '"></label>' +
      '<label>Лимит трафика, ГБ<input id="pr-traffic" type="number" value="' + (p.paid_preset_traffic || 0) + '"></label>' +
      '<label>Лимит LTE, ГБ<input id="pr-lte" type="number" value="' + (p.paid_preset_lte || 0) + '"></label>' +
      '<button id="btn-pr-save" class="ghost">Сохранить пресеты</button>';
    $("presets-out").appendChild(div);
    $("btn-pr-save").onclick = async function(){
      const rr = await api("/subs/presets", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({
        paid_trial_period: parseInt($("pr-trial").value || "0", 10),
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
});
$("btn-asub-list").onclick = async function(){ const r = await api("/admin-subs"); renderOut("asub-out", r.data); };
$("btn-asub-card").onclick = async function(){ const r = await api("/admin-subs/" + $("asub-id").value); renderOut("asub-out", r.data); };
$("btn-referrals").onclick = async function(){ const r = await api("/referrals"); renderOut("ref-out", r.data); };
$("btn-lte").onclick = async function(){ const r = await postConfirm("/subs/lte/check-now", {}); renderOut("ref-out", r.data); };

/* --- Финансы и оплаты --- */
$("btn-finance").onclick = async function(){
  const r = await api("/finance?period=" + $("fin-period").value);
  renderOut("finance-out", r.data);
};
$("btn-servers").onclick = async function(){ const r = await api("/servers"); renderOut("finance-out", r.data); };
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
  let r;
  try { r = await api("/servers"); }
  catch(e) { $("srv-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("srv-out", r.data); return; }
  const items = r.data.servers || [];
  if (!items.length) { $("srv-out").innerHTML = '<div class="empty"><span class="big">🔍</span>Серверов нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Название</th><th>Цена</th><th>День оплаты</th><th>Активен</th></tr></thead><tbody>';
  items.forEach(function(it){
    h += '<tr data-sid="' + it.id + '"><td>' + esc(it.name) + '</td><td class="num">' + fmtMoney(it.price_rub) + '</td><td class="num">' + (it.pay_day || "—") + '</td><td>' + statusPill(it.active ? "active" : "disabled", it.active ? "Активен" : "Выключен") + '</td></tr>';
  });
  $("srv-out").innerHTML = h + '</tbody></table></div>';
  $("srv-out").querySelectorAll("tr[data-sid]").forEach(function(tr){
    tr.onclick = function(){ openServerEditor(parseInt(tr.dataset.sid, 10)); };
  });
}
$("btn-servers-list").onclick = function(){ loadServers(); };
document.querySelector('[data-nav="finance"]').addEventListener("click", function(){
  if (!serversLoaded) { serversLoaded = true; loadServers(); }
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
const PAY_LABELS = {paid: "Оплачено", pending: "Ожидает", refunded: "Возвращён", failed: "Неудачный"};
async function loadPayments(){
  const st = $("pay-status").value;
  let r;
  try { r = await api("/payments" + (st ? "?status=" + st : "")); }
  catch(e) { $("payments-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("payments-out", r.data); return; }
  const items = r.data.payments || [];
  if (!items.length) { $("payments-out").innerHTML = '<div class="empty"><span class="big">🔍</span>Оплат не найдено</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>ID</th><th>Пользователь</th><th>Сумма</th><th>Статус</th><th>Дата</th><th>Провайдер</th></tr></thead><tbody>';
  items.forEach(function(it){
    const name = esc(it.first_name || "—") + (it.username ? ' <span class="mut">@' + esc(it.username) + '</span>' : "") + ' <span class="mono small">#' + it.tg_id + '</span>';
    h += '<tr data-pay-id="' + it.id + '"><td class="mono">' + it.id + '</td><td>' + name + '</td><td class="num">' + fmtMoney(it.amount) + '</td><td>' + statusPill(it.status, PAY_LABELS[it.status] || it.status) + '</td><td><span class="mono">' + fmtDate(it.date) + '</span></td><td>' + esc(it.provider || "") + '</td></tr>';
  });
  $("payments-out").innerHTML = h + '</tbody></table></div>';
  $("payments-out").querySelectorAll("tr[data-pay-id]").forEach(function(tr){
    tr.onclick = function(){ openPaymentEditor(parseInt(tr.dataset.payId, 10)); };
  });
}
$("btn-payments").onclick = function(){ loadPayments(); };
$("pay-status").onchange = function(){ loadPayments(); };
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
  h += kvRow("Провайдер", esc(p.provider || ""));
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
  if (p.status === "paid") {
    h += '<label><input id="ed-pay-revoke" type="checkbox"> отозвать подписку при возврате</label>';
    h += '<p class="mut" id="ed-pay-msg" style="margin-top:10px"></p>';
  }
  $("drawer-body").innerHTML = h;
  if (p.status === "paid") {
    $("drawer-foot").innerHTML = '<button class="danger" id="ed-pay-refund">Вернуть оплату</button>';
    $("ed-pay-refund").onclick = withSpin($("ed-pay-refund"), async function(){
      const rr = await postConfirm("/payments/" + pid + "/refund", {revoke: $("ed-pay-revoke").checked});
      const msg = $("ed-pay-msg");
      if (msg) msg.textContent = rr.status === 200 ? "Возврат оформлен" : ("Ошибка: " + (rr.data.error || rr.status));
      if (rr.status === 200) { toast("Возврат оформлен", "ok"); openPaymentEditor(pid); loadPayments(); }
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
/* --- Промокоды: список + редактор --- */
let promosLoaded = false;
async function loadPromos(){
  let r;
  try { r = await api("/promos"); }
  catch(e) { $("promos-out").innerHTML = '<p class="err">Ошибка загрузки</p>'; return; }
  if (r.status !== 200) { renderOut("promos-out", r.data); return; }
  const items = r.data.promos || [];
  if (!items.length) { $("promos-out").innerHTML = '<div class="empty"><span class="big">🔍</span>Промокодов нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Код</th><th>Скидка</th><th>Использовано</th><th>Истекает</th><th>Активен</th></tr></thead><tbody>';
  items.forEach(function(it){
    const used = (it.uses || 0) + (it.max_uses ? " / " + it.max_uses : "");
    h += '<tr data-promo-code="' + esc(it.code) + '"><td><span class="mono">' + esc(it.code) + '</span></td><td class="num">' + (it.percent || 0) + '%</td><td class="num">' + used + '</td><td><span class="mono">' + fmtDate(it.expires_at) + '</span></td><td>' + statusPill(it.active ? "active" : "disabled", it.active ? "Активен" : "Выключен") + '</td></tr>';
  });
  $("promos-out").innerHTML = h + '</tbody></table></div>';
  $("promos-out").querySelectorAll("tr[data-promo-code]").forEach(function(tr){
    tr.onclick = function(){ openPromoEditor(tr.dataset.promoCode); };
  });
}
$("btn-promos").onclick = function(){ loadPromos(); };
document.querySelector('[data-nav="promos"]').addEventListener("click", function(){
  if (!promosLoaded) { promosLoaded = true; loadPromos(); }
});
$("btn-pr-add").onclick = withSpin($("btn-pr-add"), async function(){
  const body = {code: $("pr-code").value.trim()};
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
  const r = await api("/promos/batch", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({count: parseInt($("pr-count").value || "10", 10)})});
  if (r.status === 200) { toast("Пачка промокодов создана", "ok"); loadPromos(); }
  else renderOut("promos-out", r.data);
});
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
  if (!profiles.length) { $("profiles-table").innerHTML = '<div class="empty">Профилей нет</div>'; }
  else {
    let h = '<div class="tblwrap"><table><thead><tr><th>Профиль</th><th>UUID</th><th>Инбаунды</th></tr></thead><tbody>';
    profiles.forEach(function(p){
      h += '<tr data-uuid="' + esc(p.uuid) + '"><td>' + esc(p.name || "") + '</td><td class="mono">' + esc(String(p.uuid).slice(0, 8)) + '…</td><td>' + (p.inbounds || []).map(function(ib){ return esc(ib.tag || ""); }).join(", ") + '</td></tr>';
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
      h2 += '<tr data-uuid="' + esc(x.uuid) + '" data-disabled="' + (x.isDisabled ? "true" : "false") + '"><td>' + esc(x.remark || "") + '</td><td class="mono">' + esc(x.address || "") + '</td><td class="num">' + (x.port == null ? "—" : x.port) + '</td><td>' + statusPill(x.isDisabled ? "disabled" : "enabled", x.isDisabled ? "Выключен" : "Включён") + '</td></tr>';
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
  if (!panelLoaded) { panelLoaded = true; loadPanel(); }
});
$("btn-yandex").onclick = async function(){ const r = await api("/yandex"); renderOut("panel-out", r.data); };
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
    h += '<tr data-uuid="' + esc(n.uuid || "") + '"><td>' + esc(n.name || n.address || "") + '</td><td class="mono">' + esc(n.address || "") + '</td><td>' + statusPill(n.isDisabled ? "disabled" : alive ? "online" : "offline", st) + '</td><td class="num">' + (n.usersOnline == null ? "—" : n.usersOnline) + '</td></tr>';
  });
  h += '</tbody></table></div>';
  $("nodes-table").innerHTML = h;
  $("nodes-table").querySelectorAll("tr[data-uuid]").forEach(function(tr){
    tr.onclick = function(){ $("node-id").value = tr.dataset.uuid; loadNodeUsers(); };
  });
}
document.querySelector('[data-nav="nodes"]').addEventListener("click", function(){
  if (!nodesLoaded) { nodesLoaded = true; loadNodes(); $("btn-nodes").click(); }
});
$("btn-nodes").onclick = async function(){ const r = await api("/nodes"); renderOut("nodes-out", r.data); };
$("btn-squads").onclick = async function(){ const r = await api("/squads"); renderOut("nodes-out", r.data); };
async function loadNodeUsers(){
  let q = "";
  const s = $("node-start").value.trim(), e = $("node-end").value.trim();
  if (s) q += (q ? "&" : "?") + "start=" + encodeURIComponent(s);
  if (e) q += (q ? "&" : "?") + "end=" + encodeURIComponent(e);
  const r = await api("/nodes/" + $("node-id").value + "/users" + q);
  renderOut("nodes-out", r.data);
}
$("btn-node-users").onclick = loadNodeUsers;

/* --- Логи, синхронизация, операторы, сайт, бэкап --- */
let logsLoaded = false;
document.querySelector('[data-nav="logs"]').addEventListener("click", function(){
  if (!logsLoaded) { logsLoaded = true; $("btn-logs").click(); }
});
$("btn-logs").onclick = async function(){
  let q = "?kind=" + $("logs-kind").value;
  const u = $("logs-user").value.trim(); if (u) q += "&user_id=" + u;
  const f = $("logs-from").value.trim(); if (f) q += "&date_from=" + encodeURIComponent(f);
  const t = $("logs-to").value.trim(); if (t) q += "&date_to=" + encodeURIComponent(t);
  const r = await api("/logs" + q);
  renderOut("logs-out", r.data);
};
$("btn-logs-export").onclick = function(){
  $("btn-logs-export").href = "/api/admin/logs/export?kind=" + $("logs-kind").value;
};
$("btn-logs-purge").onclick = async function(){
  const r = await postConfirm("/logs/purge", {});
  renderOut("logs-out", r.data);
};
$("btn-downtime").onclick = async function(){ const r = await api("/downtime"); renderOut("downtime-out", r.data); };
$("btn-online").onclick = async function(){ const r = await api("/online"); renderOut("downtime-out", r.data); };
$("btn-psync").onclick = async function(){ const r = await postConfirm("/panel-sync", {}); renderOut("psync-out", r.data); };
$("btn-psync-set").onclick = async function(){ const r = await api("/panel-sync/settings"); renderOut("psync-out", r.data); };
$("btn-morning").onclick = async function(){ const r = await api("/morning"); renderOut("morning-out", r.data); };
$("btn-morning-run").onclick = async function(){ const r = await postConfirm("/morning/run-now", {}); renderOut("morning-out", r.data); };
$("btn-morning-save").onclick = async function(){
  const body = {morning_sync: {}};
  const t = $("mor-time").value.trim();
  if (t) body.morning_sync.time = t;
  body.morning_sync.enabled = $("mor-enabled").checked;
  const r = await api("/morning", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
  renderOut("morning-out", r.data);
};
$("btn-job").onclick = async function(){
  const r = await postConfirm("/jobs/run-now", {job: $("job-sel").value});
  renderOut("job-out", r.data);
};
$("btn-netcheck-show").onclick = async function(){ const r = await api("/netcheck"); renderOut("netcheck-out", r.data); };
$("btn-netcheck").onclick = withSpin($("btn-netcheck"), async function(){
  const r = await postConfirm("/netcheck/run", {});
  renderOut("netcheck-out", r.data);
});
$("btn-site-show").onclick = async function(){ const r = await api("/site"); renderOut("site-out", r.data); };
$("btn-deploy").onclick = async function(){ const r = await postConfirm("/site/deploy", {}); renderOut("site-out", r.data); };
$("btn-st-save").onclick = async function(){
  const r = await api("/site/texts", {method: "PATCH", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({field: $("st-field").value, text: $("st-text").value})});
  renderOut("st-out", r.data);
};
$("btn-st-show").onclick = async function(){
  const r = await api("/site/texts");
  if (r.status !== 200) { renderOut("st-out", r.data); return; }
  const texts = r.data.texts || {};
  const keys = Object.keys(texts);
  if (!keys.length) { $("st-out").innerHTML = '<div class="empty">Текстов нет</div>'; return; }
  let h = '<div class="tblwrap"><table><thead><tr><th>Поле</th><th>Текст</th></tr></thead><tbody>';
  keys.forEach(function(k){
    h += '<tr data-field="' + esc(k) + '"><td class="mono">' + esc(k) + '</td><td>' + esc(String(texts[k]).slice(0, 80)) + '</td></tr>';
  });
  h += '</tbody></table></div>';
  $("st-out").innerHTML = h;
  $("st-out").querySelectorAll("tr[data-field]").forEach(function(tr){
    tr.onclick = function(){
      $("st-field").value = tr.dataset.field;
      $("st-text").value = texts[tr.dataset.field] || "";
      $("st-text").focus();
    };
  });
};
$("btn-site-del").onclick = async function(){ const r = await postConfirm("/site/delete", {}); renderOut("site-del-out", r.data); };
$("btn-backup-restore").onclick = async function(){
  const f = $("bk-file").files[0];
  if (!f) { toast("Выберите файл архива", "err"); return; }
  if (!$("bk-fresh").checked) { toast("Подтвердите, что свежий бэкап сделан", "err"); return; }
  const b64 = await new Promise(function(res, rej){
    const rd = new FileReader();
    rd.onload = function(){ res(String(rd.result).split(",")[1] || ""); };
    rd.onerror = rej;
    rd.readAsDataURL(f);
  });
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
  let h = '<div class="tblwrap"><table><thead><tr><th>Тема</th><th>Юзер</th></tr></thead><tbody>';
  topics.forEach(function(t){
    h += '<tr data-user="' + t.user_id + '"><td>' + esc(t.topic_name || "") + '</td><td class="mono">' + t.user_id + '</td></tr>';
  });
  h += '</tbody></table></div>';
  $("topics-out").innerHTML = h;
  $("topics-out").querySelectorAll("tr[data-user]").forEach(function(tr){
    tr.onclick = function(){ $("sup-user").value = tr.dataset.user; openTopic(); };
  });
}
document.querySelector('[data-nav="support"]').addEventListener("click", function(){
  if (!supportLoaded) { supportLoaded = true; loadTopics(); }
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
$("btn-ss-save").onclick = async function(){
  const r = await api("/support/settings", {method: "PATCH", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({support_group_id: parseInt($("ss-group").value || "0", 10),
      log_channel_id: parseInt($("ss-log").value || "0", 10)})});
  renderOut("ss-out", r.data);
};
$("btn-helper-add").onclick = async function(){
  const r = await api("/helpers/add", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({tg_id: parseInt($("helper-tg").value || "0", 10)})});
  renderOut("helpers-out", r.data);
};
$("btn-helper-perm").onclick = async function(){
  const id = $("helper-tg").value;
  const r = await api("/helpers/" + id + "/perm", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({perm: $("helper-perm-sel").value})});
  renderOut("helpers-out", r.data);
};
$("btn-helper-del").onclick = async function(){
  const id = $("helper-tg").value;
  const r = await postConfirm("/helpers/" + id + "/delete", {});
  renderOut("helpers-out", r.data);
};
$("btn-helpers").onclick = async function(){ const r = await api("/helpers"); renderOut("helpers-out", r.data); };
$("btn-webacc").onclick = async function(){ const r = await api("/web-access"); renderOut("wa-out", r.data); };
$("btn-wa-save").onclick = async function(){
  const body = {};
  const port = $("wa-port").value;
  if (port) body.webapi_port = parseInt(port, 10);
  const bind = $("wa-bind").value.trim();
  if (bind) body.webapi_bind = bind;
  const r = await api("/web-access", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
  renderOut("wa-out", r.data);
};
$("btn-ch-show").onclick = async function(){ const r = await api("/connect-help"); renderOut("ch-out", r.data); };

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
