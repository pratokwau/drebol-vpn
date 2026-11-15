"""Статическая страница веб-админки Drebol VPN.

Тот же midnight-дизайн, что у сайта: #020202, #2ea8ff, Unbounded + Inter.
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
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Unbounded:wght@500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#020202;--card:#0b0e13;--line:#1c2330;--txt:#f2f5f9;--mut:#8b95a7;--acc:#2ea8ff;--ok:#34d399;--bad:#f87171}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:15px/1.55 "Inter",-apple-system,"Segoe UI",sans-serif;min-height:100vh}
a{color:var(--acc)}
.wrap{max-width:960px;margin:0 auto;padding:28px 18px 60px}
h1{font-family:"Unbounded",sans-serif;font-size:22px;letter-spacing:-.02em}
h2{font-family:"Unbounded",sans-serif;font-size:15px;margin:26px 0 10px}
.mut{color:var(--mut);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-top:14px}
input,select,textarea{width:100%;background:#0e1218;border:1px solid var(--line);border-radius:10px;color:var(--txt);padding:10px 12px;font:inherit;margin:6px 0}
button{background:var(--acc);color:#02131f;border:0;border-radius:10px;padding:10px 18px;font:600 14px "Inter",sans-serif;cursor:pointer;margin-top:8px}
button.ghost{background:transparent;color:var(--acc);border:1px solid var(--acc)}
button:disabled{opacity:.5;cursor:default}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.stat b{display:block;font-size:22px;font-family:"Unbounded",sans-serif}
.stat span{color:var(--mut);font-size:12px}
.err{color:var(--bad);margin-top:8px;min-height:18px}
.ok{color:var(--ok)}
label{font-size:13px;color:var(--mut)}
.row{display:flex;gap:10px;align-items:center;justify-content:space-between}
.hidden{display:none}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left}
</style>
</head>
<body>
<div class="wrap">
  <h1>Drebol VPN · Админка</h1>
  <p class="mut">Веб-версия админки бота. Вход — через Telegram или по почте с паролем.</p>

  <div id="login" class="card">
    <h2 style="margin-top:0">Вход</h2>
    <div id="tg-widget"></div>
    <p class="mut">или по почте с паролем:</p>
    <input id="email" type="email" placeholder="почта" autocomplete="username">
    <input id="pw" type="password" placeholder="пароль" autocomplete="current-password">
    <button id="btn-login">Войти</button>
    <div id="login-err" class="err"></div>
  </div>

  <div id="setup" class="card hidden">
    <h2 style="margin-top:0">Установка пароля</h2>
    <p class="mut">Ссылка одноразовая, живёт 15 минут. Пароль — от 8 до 128 символов.</p>
    <input id="pw2" type="password" placeholder="новый пароль" autocomplete="new-password">
    <button id="btn-setup">Задать пароль и войти</button>
    <div id="setup-err" class="err"></div>
  </div>

  <div id="app" class="hidden">
    <div class="row">
      <p id="who" class="mut"></p>
      <button id="btn-logout" class="ghost">Выйти</button>
    </div>
    <h2>Статистика</h2>
    <div id="stats" class="grid"></div>
    <div id="panel-line" class="mut"></div>
    <h2>Настройки</h2>
    <div class="card">
      <p class="mut">Фаза 1 — только безопасные настройки. Секреты здесь не показываются и не меняются.</p>
      <div id="settings"></div>
      <button id="btn-save">Сохранить настройки</button>
      <span id="save-msg" class="mut"></span>
    </div>
    <div id="muse-box" class="card hidden">
      <h2 style="margin-top:0">Аккаунт Muse</h2>
      <p class="mut">Только для входа через Telegram. Введите почту — аккаунт создастся отключённым, а одноразовая ссылка на установку пароля покажется один раз.</p>
      <input id="muse-email" type="email" placeholder="почта для Muse">
      <button id="btn-muse">Создать аккаунт и ссылку</button>
      <div id="muse-out" class="mut"></div>
    </div>

    <h2>Пользователи</h2>
    <div class="card">
      <input id="q-user" placeholder="ID, @username, имя или paid_123">
      <button id="btn-find">Найти</button>
      <div id="users-out"></div>
      <div id="profile-out"></div>
      <h2>Сообщение пользователю</h2>
      <input id="dm-id" type="number" placeholder="tg_id">
      <textarea id="dm-text" placeholder="текст от имени Drebol VPN"></textarea>
      <button id="btn-dm">Отправить</button>
      <span id="dm-msg" class="mut"></span>
    </div>

    <h2>Подписка</h2>
    <div class="card">
      <input id="sub-id" type="number" placeholder="ID подписки (paid_subs.id)">
      <input id="sub-days" type="number" placeholder="дней для продления">
      <div>
        <button class="ghost" data-sub="toggle">Вкл/выкл</button>
        <button class="ghost" data-sub="freeze">Заморозить</button>
        <button class="ghost" data-sub="extend">Продлить</button>
        <button class="ghost" data-sub="reissue">Перевыпустить</button>
        <button class="ghost" data-sub="delete">Удалить</button>
      </div>
      <span id="sub-msg" class="mut"></span>
    </div>

    <h2>Финансы и оплаты</h2>
    <div class="card">
      <button id="btn-finance" class="ghost">Сводка</button>
      <button id="btn-payments" class="ghost">Оплаты</button>
      <button id="btn-reconcile" class="ghost">Сверка с Platega</button>
      <button id="btn-tariffs" class="ghost">Тарифы</button>
      <button id="btn-promos" class="ghost">Промокоды</button>
      <button id="btn-servers" class="ghost">Серверы (расходы)</button>
      <div id="finance-out"></div>
    </div>

    <h2>Рассылка</h2>
    <div class="card">
      <textarea id="bc-text" placeholder="текст рассылки (HTML)"></textarea>
      <select id="bc-seg">
        <option value="all">Все</option><option value="active">Активные</option>
        <option value="expired">Истёкшие</option><option value="trial">Триал</option>
        <option value="paying">Платящие</option><option value="no_sub">Без подписки</option>
      </select>
      <button id="btn-bc-preview" class="ghost">Предпросмотр</button>
      <button id="btn-bc-send">Отправить</button>
      <div id="bc-out" class="mut"></div>
    </div>

    <h2>Узлы и панель</h2>
    <div class="card">
      <button id="btn-nodes" class="ghost">Здоровье узлов</button>
      <button id="btn-panel" class="ghost">Панель Remnawave</button>
      <button id="btn-psync" class="ghost">Синхронизация с панелью</button>
      <div id="nodes-out"></div>
    </div>

    <h2>Логи и синхронизация</h2>
    <div class="card">
      <button id="btn-logs" class="ghost">Журнал действий</button>
      <button id="btn-morning" class="ghost">Утренняя сводка 09:00</button>
      <button id="btn-morning-run" class="ghost">Запустить сводку сейчас</button>
      <button id="btn-netcheck" class="ghost">Проверка операторов</button>
      <button id="btn-downtime" class="ghost">Падения</button>
      <div id="logs-out"></div>
    </div>

    <h2>Сайт, бэкап, защита</h2>
    <div class="card">
      <button id="btn-deploy" class="ghost">Деплой сайта</button>
      <button id="btn-git" class="ghost">Обновиться с GitHub (только Mark)</button>
      <a id="btn-backup" href="/api/admin/backup/export"><button type="button" class="ghost">Скачать бэкап</button></a>
      <button id="btn-support" class="ghost">Темы поддержки</button>
      <button id="btn-blacklist" class="ghost">Чёрный список</button>
      <button id="btn-fraud" class="ghost">Повторные триалы</button>
      <div id="infra-out"></div>
    </div>
  </div>
</div>
<script>
const API = "/api/admin";
function csrf(){ const m = document.cookie.match(/(?:^|; )drebol_admin_csrf=([^;]*)/); return m ? decodeURIComponent(m[1]) : ""; }
async function api(path, opts){
  opts = opts || {};
  opts.headers = Object.assign({"Content-Type": "application/json"}, opts.headers || {});
  const r = await fetch(API + path, Object.assign({credentials: "same-origin"}, opts));
  let data = {}; try { data = await r.json(); } catch(e) {}
  return {status: r.status, data};
}
function show(id, on){ document.getElementById(id).classList.toggle("hidden", !on); }
async function refreshMe(){
  const r = await api("/me");
  if (r.status !== 200) { show("login", true); show("app", false); return false; }
  show("login", false); show("app", true);
  document.getElementById("who").textContent = r.data.actor === "mark" ? "Вошли как Mark (Telegram)" : "Вошли как Muse · " + (r.data.email || "");
  show("muse-box", r.data.actor === "mark");
  return true;
}
async function loadDashboard(){
  const r = await api("/dashboard");
  if (r.status !== 200) return;
  const s = r.data.stats || {};
  const cells = [["Пользователей", s.users_total], ["Сегодня", "+" + (s.users_today || 0)],
    ["Активных подписок", s.paid_active], ["Выручка", (s.revenue_total || 0) + " ₽"],
    ["Оплат сегодня", s.payments_today], ["Триалов выдано", s.trials_issued]];
  document.getElementById("stats").innerHTML = cells.map(c =>
    '<div class="card stat"><b>' + c[1] + '</b><span>' + c[0] + '</span></div>').join("");
  const p = r.data.panel || {};
  document.getElementById("panel-line").textContent = p.success ?
    ("Панель: клиентов " + p.total + " (платных " + p.paid + ")") :
    "Панель недоступна — сверка не выполнена";
}
const EDITABLE = ["channel_url","force_subscribe","paid_trial_period","paid_preset_hwid","paid_preset_traffic","paid_preset_lte","referral_bonus","referral_invited_bonus","maintenance_enabled","maintenance_text","device_price","device_max_extra"];
async function loadSettings(){
  const r = await api("/settings");
  if (r.status !== 200) return;
  const s = r.data.settings || {};
  document.getElementById("settings").innerHTML = EDITABLE.map(k => {
    const v = s[k];
    const type = typeof v === "boolean" ? "checkbox" : (typeof v === "number" ? "number" : "text");
    const val = type === "checkbox" ? (v ? "checked" : "") : ('value="' + (v == null ? "" : String(v).replace(/"/g, "&quot;")) + '"');
    return '<label>' + k + '<input data-k="' + k + '" type="' + type + '" ' + val + '></label>';
  }).join("");
}
document.getElementById("btn-login").onclick = async () => {
  const r = await api("/auth/password", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({email: document.getElementById("email").value, password: document.getElementById("pw").value})});
  if (r.status !== 200) { document.getElementById("login-err").textContent = r.data.error === "too_many" ? "Слишком много попыток — подождите 15 минут" : "Неверная почта или пароль"; return; }
  document.getElementById("login-err").textContent = "";
  await refreshMe(); await loadDashboard(); await loadSettings();
};
document.getElementById("btn-logout").onclick = async () => {
  await api("/logout", {method: "POST", headers: {"X-CSRF-Token": csrf()}});
  location.reload();
};
document.getElementById("btn-save").onclick = async () => {
  const patch = {};
  document.querySelectorAll("#settings input").forEach(inp => {
    patch[inp.dataset.k] = inp.type === "checkbox" ? inp.checked : (inp.type === "number" ? parseInt(inp.value || "0", 10) : inp.value);
  });
  const r = await api("/settings", {method: "PATCH", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({settings: patch})});
  document.getElementById("save-msg").textContent = r.status === 200 ? "Сохранено" : ("Ошибка: " + (r.data.error || r.status));
};
document.getElementById("btn-muse").onclick = async () => {
  const r = await api("/muse-account", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({email: document.getElementById("muse-email").value})});
  document.getElementById("muse-out").textContent = r.status === 200 ?
    ("Ссылка (показывается один раз): " + r.data.setup_url) : ("Ошибка: " + (r.data.error || r.status));
};
document.getElementById("btn-setup").onclick = async () => {
  const token = new URLSearchParams(location.search).get("token") || "";
  const r = await api("/auth/setup", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({token, password: document.getElementById("pw2").value})});
  if (r.status !== 200) { document.getElementById("setup-err").textContent = "Ссылка недействительна или пароль короче 8 символов"; return; }
  history.replaceState(null, "", location.pathname);
  await refreshMe(); await loadDashboard(); await loadSettings();
};
function esc(s){ return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;"); }
async function postConfirm(path, body){
  let r = await api(path, {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify(body || {})});
  if (r.data && r.data.need_confirm) {
    if (!confirm(r.data.summary || "Подтвердить действие?")) return {status: 0, data: {error: "cancelled"}};
    r = await api(path, {method: "POST", headers: {"X-CSRF-Token": csrf()},
      body: JSON.stringify(Object.assign({}, body || {}, {confirm_token: r.data.confirm_token}))});
  }
  return r;
}
function renderRows(el, rows){
  document.getElementById(el).innerHTML = "<pre>" + esc(JSON.stringify(rows, null, 2)).slice(0, 8000) + "</pre>";
}
document.getElementById("btn-find").onclick = async () => {
  const q = document.getElementById("q-user").value;
  const r = await api("/users?search=" + encodeURIComponent(q));
  if (r.status !== 200) return;
  document.getElementById("users-out").innerHTML = (r.data.users || []).map(u =>
    '<p><a href="#" data-tg="' + u.tg_id + '">' + esc(u.first_name || "") + " @" + esc(u.username || "") + " · " + u.tg_id + " · " + esc(u.sub_status || "") + "</a></p>").join("") || "<p class='mut'>Никого не нашёл</p>";
  document.querySelectorAll("#users-out a").forEach(a => a.onclick = async e => {
    e.preventDefault();
    const p = await api("/users/" + a.dataset.tg);
    renderRows("profile-out", p.data);
  });
};
document.getElementById("btn-dm").onclick = async () => {
  const r = await api("/users/" + document.getElementById("dm-id").value + "/dm",
    {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({text: document.getElementById("dm-text").value})});
  document.getElementById("dm-msg").textContent = r.status === 200 ? "Отправлено" : ("Ошибка: " + (r.data.error || r.status));
};
document.querySelectorAll("[data-sub]").forEach(b => b.onclick = async () => {
  const id = document.getElementById("sub-id").value;
  const body = b.dataset.sub === "extend" ? {days: parseInt(document.getElementById("sub-days").value || "0", 10)} : {};
  const r = await postConfirm("/subs/" + id + "/" + b.dataset.sub, body);
  document.getElementById("sub-msg").textContent = r.status === 200 ? "Готово" : ("Ошибка: " + (r.data.error || r.status));
});
document.getElementById("btn-finance").onclick = async () => { const r = await api("/finance"); renderRows("finance-out", r.data); };
document.getElementById("btn-payments").onclick = async () => { const r = await api("/payments"); renderRows("finance-out", r.data); };
document.getElementById("btn-reconcile").onclick = async () => { const r = await postConfirm("/reconcile/run", {}); renderRows("finance-out", r.data); };
document.getElementById("btn-tariffs").onclick = async () => { const r = await api("/tariffs"); renderRows("finance-out", r.data); };
document.getElementById("btn-promos").onclick = async () => { const r = await api("/promos"); renderRows("finance-out", r.data); };
document.getElementById("btn-servers").onclick = async () => { const r = await api("/servers"); renderRows("finance-out", r.data); };
document.getElementById("btn-bc-preview").onclick = async () => {
  const r = await api("/broadcast/preview", {method: "POST", headers: {"X-CSRF-Token": csrf()},
    body: JSON.stringify({text: document.getElementById("bc-text").value, segment: document.getElementById("bc-seg").value})});
  document.getElementById("bc-out").textContent = r.status === 200 ? ("Получателей: " + (r.data.count || 0)) : ("Ошибка: " + (r.data.error || r.status));
};
document.getElementById("btn-bc-send").onclick = async () => {
  const r = await postConfirm("/broadcast/send", {text: document.getElementById("bc-text").value, segment: document.getElementById("bc-seg").value});
  document.getElementById("bc-out").textContent = r.status === 200 ? "Рассылка запущена" : ("Ошибка: " + (r.data.error || r.status));
};
document.getElementById("btn-nodes").onclick = async () => { const r = await api("/nodes"); renderRows("nodes-out", r.data); };
document.getElementById("btn-panel").onclick = async () => { const r = await api("/panel"); renderRows("nodes-out", r.data); };
document.getElementById("btn-psync").onclick = async () => { const r = await postConfirm("/panel-sync", {}); renderRows("nodes-out", r.data); };
document.getElementById("btn-logs").onclick = async () => { const r = await api("/logs"); renderRows("logs-out", r.data); };
document.getElementById("btn-morning").onclick = async () => { const r = await api("/morning"); renderRows("logs-out", r.data); };
document.getElementById("btn-morning-run").onclick = async () => { const r = await postConfirm("/morning/run-now", {}); renderRows("logs-out", r.data); };
document.getElementById("btn-netcheck").onclick = async () => { const r = await postConfirm("/netcheck/run", {}); renderRows("logs-out", r.data); };
document.getElementById("btn-downtime").onclick = async () => { const r = await api("/downtime"); renderRows("logs-out", r.data); };
document.getElementById("btn-deploy").onclick = async () => { const r = await postConfirm("/site/deploy", {}); renderRows("infra-out", r.data); };
document.getElementById("btn-git").onclick = async () => { const r = await postConfirm("/git-update", {}); renderRows("infra-out", r.data); };
document.getElementById("btn-support").onclick = async () => { const r = await api("/support/topics"); renderRows("infra-out", r.data); };
document.getElementById("btn-blacklist").onclick = async () => { const r = await api("/blacklist"); renderRows("infra-out", r.data); };
document.getElementById("btn-fraud").onclick = async () => { const r = await api("/fraud"); renderRows("infra-out", r.data); };
(function init(){
  const params = new URLSearchParams(location.search);
  if (params.get("token")) { show("setup", true); }
  const s = document.createElement("script");
  s.src = "https://telegram.org/js/telegram-widget.js?22";
  s.async = true;
  s.setAttribute("data-telegram-login", "__BOT__");
  s.setAttribute("data-size", "large");
  s.setAttribute("data-auth-url", location.origin + "/admin/?tg=1");
  document.getElementById("tg-widget").appendChild(s);
  if (params.get("tg") === "1") {
    const user = {};
    params.forEach((v, k) => { if (k !== "tg") user[k] = v; });
    api("/auth/telegram", {method: "POST", headers: {"X-CSRF-Token": csrf()}, body: JSON.stringify({user})})
      .then(async r => { history.replaceState(null, "", location.pathname); if (r.status === 200) { await refreshMe(); await loadDashboard(); await loadSettings(); } });
  } else {
    refreshMe().then(ok => { if (ok) { loadDashboard(); loadSettings(); } });
  }
})();
</script>
</body>
</html>
"""


def admin_page(bot_username: str = "") -> str:
    """Готовая страница веб-админки: подставлено имя бота для виджета Telegram."""
    return ADMIN_PAGE.replace("__BOT__", bot_username or "")
