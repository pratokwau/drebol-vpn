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
