"""Сайт Drebol VPN — одна самодостаточная страница.

Разделы: первый экран, «Почему Drebol», «Как подключить», тарифы, вопросы,
финальный призыв и подвал. Вёрстка адаптивная: одна и та же страница
перестраивается под телефон, планшет и большой экран.

Фон (шёлк) и анимации нарисованы CSS. Из файлов рядом со страницей нужны
только логотип (logo_file) и фирменная картинка og.webp — она же превью
ссылки в мессенджерах и постер на первом экране.

CSS лежит отдельной обычной строкой, а не внутри f-строки, чтобы не
удваивать каждую фигурную скобку — так его проще править руками.
"""

from html import escape

# ── Иконки (обводка, берут цвет из currentColor) ────────────────────────────

_TG = ('<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
       '<path d="M21.9 4.3 18.7 19c-.2 1-.9 1.3-1.8.8l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5'
       'l.4-5 9.1-8.2c.4-.4-.1-.6-.6-.2L6.2 12.9l-4.8-1.5c-1-.3-1-1 .2-1.5l18.9-7.3'
       'c.9-.3 1.6.2 1.4 1.7z"/></svg>')


def _icon(paths: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{paths}</svg>')


_ICONS = {
    "nolog": _icon('<path d="M3 3l18 18"/><path d="M10.6 5.1A10.6 10.6 0 0 1 12 5c6 0 9.5 7 '
                   '9.5 7a17 17 0 0 1-3.2 4.1M6.6 6.6A17.4 17.4 0 0 0 2.5 12S6 19 12 19a9.6 '
                   '9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
    "bolt": _icon('<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>'),
    "devices": _icon('<rect x="2" y="4" width="14" height="10" rx="1.5"/>'
                     '<path d="M6 18h6M9 14v4"/><rect x="17" y="8" width="5" height="12" rx="1.2"/>'),
    "gift": _icon('<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13M5 12v9h14v-9"/>'
                  '<path d="M12 8S10.5 3 8 3.5 7 8 12 8zM12 8s1.5-5 4-4.5S17 8 12 8z"/>'),
    "chat": _icon('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'
                  '<path d="M8.5 11h.01M12 11h.01M15.5 11h.01"/>'),
    "card": _icon('<rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M2.5 10h19M6.5 15h4"/>'),
    "shield": _icon('<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6L12 3z"/>'
                    '<path d="m8.8 12.2 2.3 2.3 4.3-4.6"/>'),
}
_CHECK = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
          'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
          '<path d="M5 12.5l4.5 4.5L19 7.5"/></svg>')

# ── Контент разделов (правь тексты здесь) ────────────────────────────────────

FEATURES = [
    ("nolog", "Без логов",
     "Не храним историю посещений и не смотрим, что вы делаете в сети. "
     "Нечего хранить — нечего отдать."),
    ("bolt", "Подключение за минуту",
     "Никаких сайтов, почты и паролей. Открыли бота, получили ключ, подключились."),
    ("devices", "Все ваши устройства",
     "iOS, Android, Windows и macOS. Один ключ в приложении — и всё работает."),
    ("gift", "Пробный период сразу",
     "Попробуйте до оплаты: доступ выдаётся автоматически, как только вы запускаете бота."),
    ("chat", "Поддержка в Telegram",
     "Что-то не работает — пишете в поддержку прямо в боте. Без почты и ожидания писем."),
    ("card", "Оплата в рублях",
     "Выбираете тариф и оплачиваете прямо в боте. Продление — в пару нажатий."),
]

STEPS = [
    ("Откройте бота", "Нажмите «Открыть в Telegram» и запустите бота кнопкой «Старт»."),
    ("Получите ключ", "Подпишитесь на наш канал — бот сразу выдаст пробный доступ."),
    ("Подключитесь", "Вставьте ключ в приложение на телефоне или компьютере. Готово."),
]

FAQ = [
    ("Вы храните логи?",
     "Нет. Мы не сохраняем историю посещений и не смотрим, какие сайты вы открываете."),
    ("Как оплатить подписку?",
     "Прямо в боте: выберите тариф и оплатите в рублях. Продлить можно там же, в пару нажатий."),
    ("На каких устройствах работает?",
     "На iOS, Android, Windows и macOS. Ключ из бота вставляется в приложение на нужном устройстве."),
    ("Есть пробный период?",
     "Да. Запустите бота и подпишитесь на наш канал — пробный доступ выдаётся автоматически."),
    ("Что делать, если не подключается?",
     "Напишите в поддержку прямо в боте — поможем разобраться."),
]

PLATFORMS = ["iOS", "Android", "Windows", "macOS"]
TARIFF_PERKS = ["Без логов", "iOS, Android, Windows, macOS", "Поддержка в боте"]

# ── Стили ────────────────────────────────────────────────────────────────────

CSS = """
:root {
  --bg: #05070c;
  --ink: #ffffff;
  --muted: rgba(255, 255, 255, .64);
  --soft: rgba(255, 255, 255, .56);
  --line: rgba(255, 255, 255, .12);
  --card: rgba(255, 255, 255, .03);
  --accent: #4f8cff;
  --accent-soft: rgba(79, 140, 255, .14);
  --pad: clamp(20px, 5vw, 120px);
  --section: clamp(64px, 9vw, 120px);
  --ease: cubic-bezier(.2, .8, .2, 1);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: Manrope, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased; overflow-x: hidden;
}
a { color: inherit; text-decoration: none; }
img { max-width: 100%; }
h1, h2, h3, p { margin: 0; }
.wrap { width: 100%; max-width: 1440px; margin: 0 auto; padding-inline: var(--pad); }

/* Шёлк: мягкие пятна плывут друг сквозь друга, поверх — складки и блик */
.bg { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.silk { position: absolute; inset: -20%; filter: blur(60px); opacity: .9; }
.silk span {
  position: absolute; border-radius: 50%;
  background: radial-gradient(circle at 30% 30%, rgba(79,140,255,.55), transparent 60%);
  animation: drift 26s ease-in-out infinite;
}
.silk span:nth-child(1) { width: 60vmax; height: 60vmax; top: -10%; left: -5%; }
.silk span:nth-child(2) {
  width: 50vmax; height: 50vmax; bottom: -15%; right: -10%;
  background: radial-gradient(circle at 60% 40%, rgba(120,140,190,.42), transparent 62%);
  animation-duration: 32s; animation-delay: -8s;
}
.silk span:nth-child(3) {
  width: 42vmax; height: 42vmax; top: 35%; left: 45%;
  background: radial-gradient(circle at 50% 50%, rgba(255,255,255,.12), transparent 65%);
  animation-duration: 38s; animation-delay: -16s;
}
@keyframes drift {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
  33%      { transform: translate3d(6vw, -4vh, 0) scale(1.12); }
  66%      { transform: translate3d(-5vw, 5vh, 0) scale(.94); }
}
.folds {
  position: absolute; inset: -25%;
  background: linear-gradient(104deg,
    transparent 6%, rgba(255,255,255,.09) 14%, transparent 24%,
    rgba(160,190,255,.08) 34%, transparent 44%,
    rgba(255,255,255,.06) 58%, transparent 68%,
    rgba(255,255,255,.04) 82%, transparent 92%);
  filter: blur(26px);
  animation: fold 22s ease-in-out infinite alternate;
}
@keyframes fold {
  from { transform: translate3d(-3%, 0, 0) skewY(-1.5deg) scaleY(1.05); }
  to   { transform: translate3d(3%, 0, 0) skewY(1.5deg) scaleY(.98); }
}
.vignette {
  position: absolute; inset: 0;
  background: radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,.7) 100%);
}
main, header, footer { position: relative; z-index: 1; }

/* Шапка */
.top {
  position: sticky; top: 0; z-index: 10;
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  background: rgba(5, 7, 12, .55); border-bottom: 1px solid transparent;
}
.top .wrap { display: flex; align-items: center; justify-content: space-between; gap: 24px; height: 84px; }
.brand { display: flex; align-items: center; min-height: 44px; }
.brand img { height: 30px; width: auto; display: block; }
.nav { display: flex; gap: 34px; font-size: 15px; font-weight: 600; }
.nav a { color: rgba(255,255,255,.66); transition: color .2s; }
.nav a:hover { color: #fff; }

/* Кнопки */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 10px;
  height: 58px; padding: 0 30px; border-radius: 999px;
  font-size: 17px; font-weight: 800; white-space: nowrap;
  transition: transform .25s ease, box-shadow .25s ease, background .2s, border-color .2s;
}
.btn svg { width: 20px; height: 20px; flex: none; }
.btn-main { background: #fff; color: var(--bg); box-shadow: 0 10px 40px rgba(255,255,255,.18); }
.btn-main:hover { transform: translateY(-2px); box-shadow: 0 16px 50px rgba(255,255,255,.28); }
.btn-ghost { border: 1px solid rgba(255,255,255,.2); color: #fff; font-weight: 700; }
.btn-ghost:hover { background: rgba(255,255,255,.08); border-color: rgba(255,255,255,.32); }
.btn-sm { height: 46px; padding: 0 20px; font-size: 15px; }
.btn-sm svg { width: 18px; height: 18px; }
.glow { animation: glow 3.6s 2s ease-in-out infinite; }
@keyframes glow {
  0%, 100% { box-shadow: 0 10px 40px rgba(255,255,255,.18); }
  50%      { box-shadow: 0 10px 52px rgba(120,170,255,.45); }
}

/* Первый экран */
.hero .wrap {
  display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: 64px; align-items: center;
  padding-top: clamp(28px, 4vw, 56px); padding-bottom: var(--section);
}
.hero-text { display: flex; flex-direction: column; align-items: flex-start; gap: 26px; }
.pill {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 8px 16px 8px 12px; border-radius: 999px;
  border: 1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.04);
  font-size: 14px; font-weight: 600; color: rgba(255,255,255,.82);
}
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: pulse 2.4s ease-in-out infinite; }
@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(79,140,255,.55); }
  50%      { box-shadow: 0 0 0 7px rgba(79,140,255,0); }
}
h1 {
  font-size: clamp(42px, 6.2vw, 80px); line-height: 1.02;
  font-weight: 800; letter-spacing: -.035em; text-wrap: balance;
}
h1 .dim { color: rgba(255,255,255,.5); }
.lead { max-width: 540px; font-size: clamp(17px, 1.5vw, 20px); line-height: 1.55; color: var(--muted); text-wrap: pretty; }
.actions { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 6px; }
.hint { font-size: 14px; color: var(--soft); }
.handle { color: rgba(255,255,255,.9); font-weight: 700; user-select: all; -webkit-user-select: all; }
.chips { display: flex; flex-wrap: wrap; gap: 10px; list-style: none; padding: 0; margin: 8px 0 0; }
.chips li {
  padding: 8px 14px; border-radius: 999px; border: 1px solid var(--line);
  font-size: 13px; font-weight: 600; color: var(--muted);
}

.visual { position: relative; display: flex; justify-content: center; }
.poster {
  width: min(100%, 480px); aspect-ratio: 4 / 5; border-radius: 32px; overflow: hidden;
  border: 1px solid rgba(255,255,255,.12);
  box-shadow: 0 40px 120px rgba(79,140,255,.22), 0 0 0 1px rgba(0,0,0,.4);
  animation: float 8s ease-in-out infinite;
}
.poster img { width: 100%; height: 100%; object-fit: cover; display: block; }
@keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-8px); } }
.status {
  position: absolute; left: 0; bottom: 56px;
  display: flex; align-items: center; gap: 14px; padding: 16px 20px; border-radius: 20px;
  background: rgba(12,16,26,.8); border: 1px solid rgba(255,255,255,.14);
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 20px 50px rgba(0,0,0,.45);
}
.status b { display: block; font-size: 15px; }
.status small { font-size: 13px; color: rgba(255,255,255,.6); }

/* Общие элементы разделов */
.section { padding-block: var(--section); }
.head { display: flex; flex-direction: column; gap: 16px; margin-bottom: clamp(28px, 4vw, 56px); }
.head.center { align-items: center; text-align: center; }
.head.split { flex-direction: row; align-items: flex-end; justify-content: space-between; gap: 48px; }
.eyebrow { font-size: 14px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--accent); }
h2 {
  font-size: clamp(32px, 4vw, 54px); line-height: 1.08;
  font-weight: 800; letter-spacing: -.03em; text-wrap: balance; max-width: 720px;
}
.sub { max-width: 560px; font-size: 17px; line-height: 1.6; color: var(--muted); }
.head.split .sub { max-width: 380px; }
.ico {
  flex: none; width: 52px; height: 52px; border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  background: var(--accent-soft); color: var(--accent);
}
.ico svg { width: 26px; height: 26px; }

/* Возможности */
.grid3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.feature {
  display: flex; flex-direction: column; gap: 18px; padding: 32px;
  border-radius: 24px; border: 1px solid rgba(255,255,255,.1); background: var(--card);
  transition: border-color .25s, background .25s, transform .25s;
}
.feature:hover { border-color: rgba(79,140,255,.45); background: rgba(255,255,255,.05); transform: translateY(-3px); }
.feature h3 { font-size: 22px; font-weight: 700; letter-spacing: -.01em; }
.feature h3, .step h3 { margin-bottom: 10px; }
.feature p, .step p { font-size: 16px; line-height: 1.6; color: var(--muted); }

/* Шаги */
.step {
  display: flex; flex-direction: column; gap: 20px; padding: 36px 32px; border-radius: 24px;
  border: 1px solid rgba(255,255,255,.1);
  background: linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.01));
}
.step:last-child { border-color: rgba(79,140,255,.35); background: linear-gradient(180deg, rgba(79,140,255,.12), rgba(79,140,255,.02)); }
.num {
  font-size: 64px; line-height: 1; font-weight: 800; letter-spacing: -.04em;
  color: transparent; -webkit-text-stroke: 1.5px rgba(255,255,255,.4);
}
.step:last-child .num { -webkit-text-stroke-color: var(--accent); }
.step h3 { font-size: 24px; font-weight: 700; }

/* Тарифы */
.plans { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 20px; }
.plan {
  display: flex; flex-direction: column; gap: 26px; padding: 40px 36px; border-radius: 28px;
  border: 1px solid rgba(255,255,255,.1); background: var(--card);
}
.plan.best {
  border-color: rgba(79,140,255,.55);
  background: linear-gradient(180deg, rgba(79,140,255,.16), rgba(79,140,255,.03));
  box-shadow: 0 30px 90px rgba(79,140,255,.18);
}
.plan-name { font-size: 18px; font-weight: 700; color: rgba(255,255,255,.85); }
.plan-period { font-size: 14px; color: var(--soft); margin-top: 4px; }
.price { display: flex; align-items: baseline; gap: 8px; margin-top: 10px; }
.price b { font-size: clamp(40px, 4vw, 52px); font-weight: 800; letter-spacing: -.03em; }
.price span { font-size: 20px; font-weight: 700; color: rgba(255,255,255,.6); }
.rule { height: 1px; background: var(--line); }
.perks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 14px; font-size: 16px; color: rgba(255,255,255,.82); }
.perks li { display: flex; align-items: center; gap: 12px; }
.perks svg { width: 20px; height: 20px; flex: none; color: var(--accent); }
.plan .btn { margin-top: auto; height: 56px; font-size: 16px; }
.note { margin-top: 28px; text-align: center; font-size: 15px; color: var(--soft); }

/* Вопросы: нативные <details>, работают без JS */
.faq .wrap { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr); gap: 80px; }
.faq .head { margin-bottom: 0; }
.qa { border-top: 1px solid var(--line); }
.qa details { border-bottom: 1px solid var(--line); }
.qa summary {
  list-style: none; cursor: pointer;
  display: flex; align-items: center; justify-content: space-between; gap: 24px;
  min-height: 76px; padding: 20px 8px; font-size: 19px; font-weight: 700;
  transition: background .2s;
}
.qa summary::-webkit-details-marker { display: none; }
.qa summary:hover { background: rgba(255,255,255,.03); }
.qa summary i {
  flex: none; position: relative; width: 36px; height: 36px; border-radius: 50%;
  border: 1px solid rgba(255,255,255,.18);
}
.qa summary i::before, .qa summary i::after {
  content: ""; position: absolute; left: 50%; top: 50%; width: 14px; height: 2px;
  margin: -1px 0 0 -7px; background: #fff; border-radius: 2px; transition: transform .25s var(--ease);
}
.qa summary i::after { transform: rotate(90deg); }
.qa details[open] summary i::after { transform: rotate(0deg); }
.qa p { padding: 0 64px 26px 8px; font-size: 16px; line-height: 1.65; color: var(--muted); }

/* Финальный призыв */
.cta-box {
  display: flex; flex-direction: column; align-items: center; gap: 22px; text-align: center;
  padding: clamp(48px, 7vw, 88px) clamp(22px, 4vw, 48px); border-radius: 36px;
  border: 1px solid rgba(255,255,255,.12);
  background: radial-gradient(ellipse at 50% 0%, rgba(79,140,255,.24), rgba(5,7,12,.2) 70%);
}
.cta-box .mark-img { height: 44px; width: auto; }
.cta-box h2 { font-size: clamp(34px, 5vw, 62px); }
.cta-box .actions { justify-content: center; }

/* Подвал */
.foot { border-top: 1px solid rgba(255,255,255,.08); }
.foot .wrap { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding-block: 36px 44px; }
.foot img { height: 26px; width: auto; opacity: .85; }
.foot nav { display: flex; flex-wrap: wrap; gap: 8px 28px; font-size: 14px; font-weight: 600; }
.foot nav a { color: rgba(255,255,255,.66); }
.foot nav a:hover { color: #fff; }
.copy { font-size: 14px; color: var(--soft); }

/* Логотип, нарисованный линиями (если картинку не залили) */
.logo { display: flex; align-items: center; gap: 12px; }
.logo .mark { width: 34px; height: 34px; }
.logo .mark circle, .logo .mark ellipse { fill: none; stroke: #fff; stroke-width: 7; }
.logo .word { font-size: 26px; font-weight: 800; letter-spacing: -.02em; }
.cta-box .logo .mark { width: 44px; height: 44px; }
.cta-box .logo .word { font-size: 34px; }

/* Появление при прокрутке (включается скриптом; без JS всё просто видно) */
.js .reveal { opacity: 0; transform: translateY(18px); transition: opacity .8s var(--ease), transform .8s var(--ease); }
.js .reveal.in { opacity: 1; transform: none; }

/* ── Планшет ── */
@media (max-width: 1080px) {
  .nav { display: none; }
  .hero .wrap { grid-template-columns: 1fr; gap: 48px; }
  .visual { justify-content: flex-start; }
  .poster { width: min(100%, 440px); }
  .status { left: 16px; bottom: 16px; }
  .grid3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .steps.grid3 { grid-template-columns: 1fr; }
  .faq .wrap { grid-template-columns: 1fr; gap: 28px; }
  .head.split { flex-direction: column; align-items: flex-start; gap: 16px; }
}

/* ── Телефон ── */
@media (max-width: 640px) {
  .top .wrap { height: 68px; }
  .brand img { height: 26px; }
  .top .btn-sm { height: 44px; padding: 0 16px; font-size: 14px; }
  .top .btn-sm .long { display: none; }
  .hero-text { gap: 20px; }
  .pill { font-size: 13px; }
  .actions { flex-direction: column; width: 100%; }
  .actions .btn { width: 100%; }
  .hint { align-self: center; text-align: center; font-size: 13px; }
  .visual { justify-content: center; }
  .poster { width: 100%; border-radius: 26px; }
  .status { left: 12px; right: 12px; bottom: 12px; padding: 12px 14px; }
  .chips { justify-content: center; width: 100%; }
  .eyebrow { font-size: 13px; }
  .sub { font-size: 16px; }
  .grid3 { grid-template-columns: 1fr; gap: 12px; }
  .feature { flex-direction: row; align-items: flex-start; gap: 16px; padding: 20px; border-radius: 20px; }
  .feature:hover { transform: none; }
  .feature .ico { width: 46px; height: 46px; border-radius: 14px; }
  .feature .ico svg { width: 23px; height: 23px; }
  .feature h3 { font-size: 18px; margin-bottom: 6px; }
  .feature p, .step p { font-size: 15px; line-height: 1.55; }
  .step { flex-direction: row; align-items: flex-start; gap: 18px; padding: 22px 20px; border-radius: 20px; }
  .num { flex: none; width: 52px; font-size: 40px; -webkit-text-stroke-width: 1.2px; }
  .step h3 { font-size: 19px; margin-bottom: 6px; }
  .plans { grid-template-columns: 1fr; gap: 12px; }
  .plan { padding: 24px; gap: 18px; border-radius: 22px; }
  .plan .perks, .plan .rule { display: none; }
  .plan-top { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
  .price { margin-top: 0; }
  .price b { font-size: 34px; }
  .price span { font-size: 17px; }
  .plan .btn { height: 52px; }
  .perks-mobile { display: flex !important; }
  .note { font-size: 14px; }
  .qa summary { min-height: 64px; padding: 16px 2px; font-size: 17px; gap: 16px; }
  .qa summary i { width: 32px; height: 32px; }
  .qa p { padding: 0 44px 20px 2px; font-size: 15px; }
  .cta-box { border-radius: 28px; }
  .cta-box .mark-img { height: 34px; }
  .foot .wrap { flex-direction: column; text-align: center; gap: 18px; padding-block: 28px 40px; }
  .foot nav { flex-direction: column; align-items: center; gap: 0; }
  .foot nav a { display: flex; align-items: center; min-height: 44px; }
}
.perks-mobile {
  display: none; margin-top: 12px; padding: 20px; border-radius: 20px;
  border: 1px dashed rgba(255,255,255,.14); font-size: 15px;
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
  .js .reveal { opacity: 1; transform: none; }
}
"""

# Появление блоков при прокрутке. Если JS выключен — класс .js не ставится
# и страница просто показывается целиком.
JS_HEAD = "document.documentElement.classList.add('js');"

JS = """
(function () {
  var items = document.querySelectorAll('.reveal');
  if (!('IntersectionObserver' in window)) {
    items.forEach(function (el) { el.classList.add('in'); });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    });
  }, { rootMargin: '0px 0px -8% 0px' });
  items.forEach(function (el) { io.observe(el); });
})();
"""


def _fmt_price(value) -> str:
    """12900 → «12 900» (неразрывный узкий пробел между разрядами)."""
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return escape(str(value))


def build_page(bot_username: str, title: str = "Drebol VPN",
               tagline: str = "Быстрый VPN без логов",
               privacy_url: str = "", terms_url: str = "",
               channel_url: str = "", logo_file: str = "",
               tariffs: list | None = None,
               poster_file: str = "og.webp") -> str:
    """Собирает страницу.

    logo_file — имя файла с настоящим логотипом рядом со страницей. Если его
    нет, логотип рисуется линиями — страница никогда не остаётся без знака.

    tariffs — список словарей {"name", "price", "period"} (period — срок
    текстом, необязателен). Пустой список — раздел «Тарифы» не показывается.

    poster_file — фирменная картинка для первого экрана (по умолчанию og.webp,
    её и так кладёт деплой). Пустая строка — первый экран без картинки.
    """
    handle = bot_username.lstrip("@")
    bot_url = escape(f"https://t.me/{handle}" if handle else "https://t.me/")
    name = escape(title)
    tariffs = tariffs or []

    # Логотип
    if logo_file:
        logo_src = escape(logo_file)
        brand_html = f'<img src="{logo_src}" alt="{name}" width="492" height="132">'
        cta_logo = f'<img class="mark-img" src="{logo_src}" alt="" width="492" height="132">'
        foot_logo = f'<img src="{logo_src}" alt="{name}" width="492" height="132">'
    else:
        word = escape(title.split()[0].lower())
        drawn = ('<span class="logo"><svg class="mark" viewBox="0 0 100 100" aria-hidden="true">'
                 '<circle cx="50" cy="50" r="40"/>'
                 '<ellipse cx="50" cy="50" rx="40" ry="13"/></svg>'
                 f'<span class="word">{word}</span></span>')
        brand_html = cta_logo = foot_logo = drawn

    hint_html = (f'<p class="hint">Не открылось? Найдите в Telegram '
                 f'<span class="handle">@{escape(handle)}</span></p>' if handle else "")

    chips = "".join(f"<li>{escape(p)}</li>" for p in PLATFORMS)

    visual_html = ""
    if poster_file:
        visual_html = f"""
    <div class="visual reveal">
      <div class="poster"><img src="{escape(poster_file)}" alt="Фирменный знак {name} на тёмном шёлке" width="1122" height="1402"></div>
      <div class="status">
        <span class="ico">{_ICONS["shield"]}</span>
        <span><b>Подключено</b><small>Соединение защищено</small></span>
      </div>
    </div>"""

    features_html = "".join(f"""
      <article class="feature reveal">
        <span class="ico">{_ICONS[icon]}</span>
        <div><h3>{escape(h)}</h3><p>{escape(t)}</p></div>
      </article>""" for icon, h, t in FEATURES)

    steps_html = "".join(f"""
      <article class="step reveal">
        <span class="num">{i:02d}</span>
        <div><h3>{escape(h)}</h3><p>{escape(t)}</p></div>
      </article>""" for i, (h, t) in enumerate(STEPS, 1))

    perks_html = "".join(f"<li>{_CHECK}{escape(p)}</li>" for p in TARIFF_PERKS)

    pricing_html = ""
    nav_pricing = ""
    hero_second = ""
    if tariffs:
        best = len(tariffs) // 2 if len(tariffs) >= 3 else -1
        cards = []
        for i, t in enumerate(tariffs):
            t_name = str(t.get("name", "")).strip()
            period = str(t.get("period", "") or "").strip()
            period_html = (f'<div class="plan-period">{escape(period)}</div>'
                           if period and period.lower() != t_name.lower() else "")
            is_best = i == best
            btn_cls = "btn btn-main" if is_best else "btn btn-ghost"
            cards.append(f"""
      <article class="plan{' best' if is_best else ''} reveal">
        <div class="plan-top">
          <div><div class="plan-name">{escape(t_name)}</div>{period_html}</div>
          <div class="price"><b>{_fmt_price(t.get("price", ""))}</b><span>₽</span></div>
        </div>
        <div class="rule"></div>
        <ul class="perks">{perks_html}</ul>
        <a class="{btn_cls}" href="{bot_url}">Выбрать в боте</a>
      </article>""")
        pricing_html = f"""
<section class="section" id="pricing">
  <div class="wrap">
    <div class="head center reveal">
      <span class="eyebrow">Тарифы</span>
      <h2>Простые цены. Без сюрпризов.</h2>
      <p class="sub">Все возможности — в любом тарифе. Разница только в сроке. Оплата и продление — в боте.</p>
    </div>
    <div class="plans">{"".join(cards)}</div>
    <ul class="perks perks-mobile">{perks_html}</ul>
    <p class="note">Не уверены? Начните с пробного периода — он выдаётся сразу после запуска бота.</p>
  </div>
</section>"""
        nav_pricing = '<a href="#pricing">Тарифы</a>'
        hero_second = '<a class="btn btn-ghost" href="#pricing">Тарифы</a>'
    elif channel_url:
        hero_second = f'<a class="btn btn-ghost" href="{escape(channel_url)}">Наш канал</a>'

    faq_html = "".join(f"""
      <details{' open' if i == 0 else ''}>
        <summary>{escape(q)}<i aria-hidden="true"></i></summary>
        <p>{escape(a)}</p>
      </details>""" for i, (q, a) in enumerate(FAQ))

    channel_btn = (f'<a class="btn btn-ghost" href="{escape(channel_url)}">Наш канал</a>'
                   if channel_url else "")

    docs = []
    if privacy_url:
        docs.append(f'<a href="{escape(privacy_url)}">Политика конфиденциальности</a>')
    if terms_url:
        docs.append(f'<a href="{escape(terms_url)}">Пользовательское соглашение</a>')
    if channel_url:
        docs.append(f'<a href="{escape(channel_url)}">Наш канал</a>')
    docs_html = f'<nav aria-label="Документы">{"".join(docs)}</nav>' if docs else ""

    year = "2026"
    og_meta = (f'<meta property="og:image" content="{escape(poster_file)}">'
               if poster_file else "")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{name} — {escape(tagline)}</title>
<meta name="description" content="{escape(tagline)}. Подключение за минуту прямо в Telegram, iOS, Android, Windows и macOS.">
<meta property="og:type" content="website">
<meta property="og:title" content="{name}">
<meta property="og:description" content="{escape(tagline)}">
{og_meta}
<meta name="theme-color" content="#05070c">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cg fill='none' stroke='white' stroke-width='7'%3E%3Ccircle cx='50' cy='50' r='40'/%3E%3Cellipse cx='50' cy='50' rx='40' ry='13'/%3E%3C/g%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{CSS}</style>
<script>{JS_HEAD}</script>
</head>
<body>
<div class="bg" aria-hidden="true">
  <div class="silk"><span></span><span></span><span></span></div>
  <div class="folds"></div>
  <div class="vignette"></div>
</div>

<header class="top">
  <div class="wrap">
    <a class="brand" href="#top" aria-label="{name} — наверх">{brand_html}</a>
    <nav class="nav" aria-label="Разделы">
      <a href="#features">Возможности</a>
      <a href="#how">Как подключить</a>
      {nav_pricing}
      <a href="#faq">Вопросы</a>
    </nav>
    <a class="btn btn-ghost btn-sm" href="{bot_url}">{_TG}<span>Открыть<span class="long"> бота</span></span></a>
  </div>
</header>

<main>
<section class="hero" id="top">
  <div class="wrap">
    <div class="hero-text reveal">
      <span class="pill"><span class="dot"></span>VPN прямо в Telegram</span>
      <h1>Интернет без границ. <span class="dim">И без логов.</span></h1>
      <p class="lead">Drebol — быстрый VPN, который подключается из Telegram. Открыли бота, получили ключ — и через минуту вы онлайн на любом устройстве.</p>
      <div class="actions">
        <a class="btn btn-main glow" href="{bot_url}">{_TG}Открыть в Telegram</a>
        {hero_second}
      </div>
      {hint_html}
      <ul class="chips" aria-label="Платформы">{chips}</ul>
    </div>{visual_html}
  </div>
</section>

<section class="section" id="features">
  <div class="wrap">
    <div class="head split reveal">
      <div class="head" style="margin:0">
        <span class="eyebrow">Почему Drebol</span>
        <h2>Всё, что нужно от VPN. Ничего лишнего.</h2>
      </div>
      <p class="sub">Мы убрали всё, что обычно мешает: регистрации, сложные настройки и долгие ответы поддержки.</p>
    </div>
    <div class="grid3">{features_html}
    </div>
  </div>
</section>

<section class="section" id="how">
  <div class="wrap">
    <div class="head center reveal">
      <span class="eyebrow">Как подключить</span>
      <h2>Три шага — и вы онлайн</h2>
    </div>
    <div class="grid3 steps">{steps_html}
    </div>
  </div>
</section>
{pricing_html}
<section class="section faq" id="faq">
  <div class="wrap">
    <div class="head reveal">
      <span class="eyebrow">Вопросы</span>
      <h2>Коротко о главном</h2>
      <p class="sub">Не нашли ответ — напишите в поддержку в боте.</p>
    </div>
    <div class="qa reveal">{faq_html}
    </div>
  </div>
</section>

<section class="section">
  <div class="wrap">
    <div class="cta-box reveal">
      {cta_logo}
      <h2>Подключитесь за минуту</h2>
      <p class="sub">Пробный доступ — сразу после запуска бота. Без регистрации на сайтах.</p>
      <div class="actions">
        <a class="btn btn-main" href="{bot_url}">{_TG}Открыть в Telegram</a>
        {channel_btn}
      </div>
    </div>
  </div>
</section>
</main>

<footer class="foot">
  <div class="wrap">
    {foot_logo}
    {docs_html}
    <span class="copy">© {year} {name}</span>
  </div>
</footer>

<script>{JS}</script>
</body>
</html>
"""
