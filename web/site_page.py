"""Сайт Drebol VPN — премиальный адаптивный лендинг нового поколения.

Футуристичный кибер-дизайн (deep space, neo-aurora, glassmorphism, border-beam,
bento grid с курсорным spotlight, интерактивный визуализатор маршрута,
3D-tilt эффект и живой HUD статус).
Все тексты полностью настраиваются через админку бота.
"""

from __future__ import annotations
from html import escape

# Логотип — тот же файл, что и на странице подписки (web/subpage.html):
# прозрачный вордмарк из assets репозитория. Прямая ссылка на raw GitHub,
# а не /logo.png: на сервере в assets/logo.png лежит залитый когда-то через
# бота кадр шёлковой картинки (817×774, логотип мелко в середине) — из-за
# него логотип на сайте был крошечным и с «белыми полосами» (складки шёлка).
LOGO_URL = "https://raw.githubusercontent.com/pratokwau/drebol-vpn/main/assets/logo.png"

# ── Иконки (обводка, currentColor) ──────────────────────────────────────────

_TG = ('<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
       '<path d="M21.9 4.3 18.7 19c-.2 1-.9 1.3-1.8.8l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5'
       'l.4-5 9.1-8.2c.4-.4-.1-.6-.6-.2L6.2 12.9l-4.8-1.5c-1-.3-1-1 .2-1.5l18.9-7.3'
       'c.9-.3 1.6.2 1.4 1.7z"/></svg>')


def _icon(paths: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{paths}</svg>')


_ICONS = {
    "nolog": _icon('<path d="M3 3l18 18"/><path d="M10.6 5.1A10.6 10.6 0 0 1 12 5c6 0 9.5 7 '
                   '9.5 7a17 17 0 0 1-3.2 4.1M6.6 6.6A17.4 17.4 0 0 0 2.5 12S6 19 12 19a9.6 '
                   '9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
    "bolt": _icon('<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>'),
    "devices": _icon('<rect x="2" y="4" width="14" height="10" rx="2"/>'
                     '<path d="M6 18h6M9 14v4"/><rect x="17" y="8" width="5" height="12" rx="1.5"/>'),
    "gift": _icon('<rect x="3" y="8" width="18" height="4" rx="1.5"/><path d="M12 8v13M5 12v9h14v-9"/>'
                  '<path d="M12 8S10.5 3 8 3.5 7 8 12 8zM12 8s1.5-5 4-4.5S17 8 12 8z"/>'),
    "chat": _icon('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'
                  '<path d="M8.5 11h.01M12 11h.01M15.5 11h.01"/>'),
    "card": _icon('<rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M2.5 10h19M6.5 15h4"/>'),
    "shield": _icon('<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6L12 3z"/>'
                    '<path d="m8.8 12.2 2.3 2.3 4.3-4.6"/>'),
    "cabinet": _icon('<rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/>'
                     '<circle cx="9" cy="11" r="2.2"/>'
                     '<path d="M5.5 16.5a3.8 3.8 0 0 1 7 0M15 10h4M15 14h2.5"/>'),
    "speed": _icon('<path d="M12 14v-4"/><path d="M3.34 17a10 10 0 1 1 17.32 0"/>'),
    "lock": _icon('<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>'
                  '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'),
    "sparkle": _icon('<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z"/>'),
    "globe": _icon('<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20M12 2a14.5 14.5 0 0 1 0 20M2 12h20"/>'),
}

_CHECK = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
          'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
          '<path d="M5 12.5l4.5 4.5L19 7.5"/></svg>')

PLATFORMS = ["iOS", "Android", "Windows", "macOS", "Linux", "Android TV"]
TARIFF_PERKS = ["Без ограничений по скорости", "Простая настройка в 1 клик", "Все платформы (iOS, Android, PC)", "Полная защита приватности", "Поддержка в Telegram 24/7"]

# ── Стандартные понятные тексты (без сложного IT-жаргона) ─────────────────────

DEFAULT_TEXTS = {
    # Главный экран (Hero)
    "hero_pill": "Быстрый VPN в Telegram · Без ограничений",
    "hero_title": "Интернет без ограничений.",
    "hero_shimmer": "И без цензуры.",
    "hero_lead": "Удобный и быстрый VPN прямо в Telegram. Подключение в пару нажатий: запустили бота, получили ключ и наслаждайтесь свободным интернетом на всех устройствах.",
    "hero_btn": "Открыть в Telegram",
    "hero_hud_status": "Защищённое соединение",
    "hero_hud_speed": "Высокая скорость · 4K Ready",

    # Метрики сети (4 показателя)
    "metric1_val": "4K",
    "metric1_unit": "HDR",
    "metric1_label": "Видео без задержек",
    "metric1_sub": "YouTube и фильмы в лучшем качестве",

    "metric2_val": "0",
    "metric2_unit": "%",
    "metric2_label": "Сохранения истории",
    "metric2_sub": "Полная приватность в интернете",

    "metric3_val": "< 15",
    "metric3_unit": "мс",
    "metric3_label": "Быстрый отклик",
    "metric3_sub": "Моментальная загрузка любых сайтов",

    "metric4_val": "99.9",
    "metric4_unit": "%",
    "metric4_label": "Стабильная работа",
    "metric4_sub": "VPN всегда онлайн и доступен",

    # Схема работы
    "route_title": "Как работает защита",
    "route_sub": "Прямое зашифрованное соединение между вашим устройством и нашими скоростными серверами.",
    "route_node1": "Ваш телефон или ПК",
    "route_badge1": "iOS · Android · PC",
    "route_node2": "Серверы Drebol",
    "route_badge2": "Безопасное соединение",
    "route_node3": "Свободный интернет",
    "route_badge3": "YouTube · Discord · Сайты",

    # Преимущества (6 карточек)
    "feat1_title": "Без сохранения истории",
    "feat1_desc": "Мы не следим за вами и не записываем, какие сайты вы открываете. Ваши действия в интернете остаются только вашими.",
    "feat1_tag": "ПРИВАТНОСТЬ",

    "feat2_title": "Подключение за минуту",
    "feat2_desc": "Никаких сайтов, подтверждений по почте и сложных паролей. Запустили бота в Telegram, нажали одну кнопку — и вы в сети.",
    "feat2_tag": "БЕЗ РЕГИСТРАЦИИ",

    "feat3_title": "Все ваши устройства",
    "feat3_desc": "Один ключ подходит для смартфона, планшета и компьютера: iOS, Android, Windows и macOS. Простая настройка в одно нажатие.",
    "feat3_tag": "ДЛЯ ВСЕХ УСТРОЙСТВ",

    "feat4_title": "Быстро и без зависаний",
    "feat4_desc": "Смотрите ролики в 4K 60fps, общайтесь в голосовых каналах Discord и открывайте нужные сервисы без падений скорости.",
    "feat4_tag": "ВЫСОКАЯ СКОРОСТЬ",

    "feat5_title": "Бесплатный тест-драйв",
    "feat5_desc": "Оцените скорость до оплаты: бесплатный пробный период выдаётся автоматически сразу после запуска бота без привязки карт.",
    "feat5_tag": "ТЕСТ БЕСПЛАТНО",

    "feat6_title": "Оплата через СБП",
    "feat6_desc": "Оплата за пару секунд через СБП с любого банка без комиссий. Моментальное зачисление и продление подписки в пару кликов.",
    "feat6_tag": "ОПЛАТА СБП",

    # Шаги (3 шага)
    "step1_title": "Запустите бота",
    "step1_desc": "Нажмите кнопку «Открыть в Telegram» и отправьте боту команду старт.",
    "step2_title": "Получите ключ",
    "step2_desc": "Подпишитесь на новостной канал — бот мгновенно выдаст персональный ключ доступа.",
    "step3_title": "Подключитесь",
    "step3_desc": "Нажмите кнопку «Подключить» или вставьте ключ в приложение на телефоне или ПК. Всё готово!",

    # Тарифы
    "tariffs_title": "Честные цены. Без скрытых платежей.",
    "tariffs_sub": "Все серверы и платформы доступны на любом тарифе. Разница только в длительности подписки.",
    "tariffs_note": "Не готовы сразу покупать? Начните с бесплатного пробного периода — он активируется мгновенно в боте.",

    # FAQ
    "faq1_q": "Вы сохраняете историю моих посещений?",
    "faq1_a": "Нет, никогда. Мы не сохраняем историю сайтов, которые вы открываете, и не ведём журналы подключений. Ваша приватность полностью защищена.",
    "faq2_q": "Как оплатить подписку?",
    "faq2_a": "Оплата происходит прямо в Telegram через СБП — быстро, безопасно и с любого удобного вам банка без комиссий.",
    "faq3_q": "Как настроить VPN на телефоне или компьютере?",
    "faq3_a": "Бот выдаст вам персональный ключ и готовую ссылку для быстрого подключения: нажимаете одну кнопку, и всё настраивается автоматически.",
    "faq4_q": "Хватит ли скорости для видео в высоком качестве?",
    "faq4_a": "Да, у нас нет ограничений по скорости или объёму трафика. Видео в YouTube 4K 60fps и фильмы воспроизводятся без пауз и буферизации.",
    "faq5_q": "Что делать, если возникнут трудности с подключением?",
    "faq5_a": "Прямо в боте работает служба заботы. Напишите нам свой вопрос — мы на связи и сразу поможем всё настроить.",

    # CTA
    "cta_title": "Подключитесь прямо сейчас",
    "cta_sub": "Пробный период активируется мгновенно. Попробуйте быстрый и надёжный VPN прямо сейчас.",
}


def get_site_texts(custom_texts: dict | None = None) -> dict:
    """Объединяет базовые тексты с пользовательскими настройками из админки."""
    if custom_texts is None:
        try:
            from config import load_config
            custom_texts = load_config().get("site_texts") or {}
        except Exception:
            custom_texts = {}
    merged = dict(DEFAULT_TEXTS)
    if custom_texts:
        for k, v in custom_texts.items():
            if v is not None and str(v).strip():
                merged[k] = str(v).strip()
    return merged


# ── Стили ────────────────────────────────────────────────────────────────────

CSS = """
:root {
  --bg: #05070c;
  --bg-elevated: #0a0e17;
  --ink: #ffffff;
  --muted: rgba(255, 255, 255, 0.72);
  --soft: rgba(255, 255, 255, 0.48);
  --line: rgba(255, 255, 255, 0.08);
  --line-strong: rgba(255, 255, 255, 0.16);
  --card: rgba(13, 18, 30, 0.65);
  --card-hover: rgba(20, 28, 48, 0.85);
  --accent: #4f8cff;
  --accent-cyan: #38ef7d;
  --accent-indigo: #7952ff;
  --accent-glow: rgba(79, 140, 255, 0.4);
  --pad: clamp(20px, 5vw, 120px);
  --section: clamp(70px, 9vw, 130px);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased; overflow-x: hidden;
  line-height: 1.5;
}
a { color: inherit; text-decoration: none; }
img { max-width: 100%; }
h1, h2, h3, h4, p { margin: 0; }
.wrap { width: 100%; max-width: 1360px; margin: 0 auto; padding-inline: var(--pad); }

/* ── Задний фон: Кибер-аура ── */
.bg { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.aurora {
  position: absolute; inset: -30%;
  filter: blur(80px); opacity: 0.85;
}
.aurora span {
  position: absolute; border-radius: 50%;
  animation: floatOrb 24s ease-in-out infinite;
  mix-blend-mode: screen;
}
.aurora span:nth-child(1) {
  width: 65vmax; height: 65vmax; top: -15%; left: -10%;
  background: radial-gradient(circle at center, rgba(79, 140, 255, 0.38), rgba(79, 140, 255, 0.08) 50%, transparent 70%);
}
.aurora span:nth-child(2) {
  width: 55vmax; height: 55vmax; bottom: -20%; right: -15%;
  background: radial-gradient(circle at center, rgba(121, 82, 255, 0.28), rgba(79, 140, 255, 0.06) 55%, transparent 75%);
  animation-duration: 30s; animation-delay: -6s;
}
.aurora span:nth-child(3) {
  width: 48vmax; height: 48vmax; top: 30%; left: 35%;
  background: radial-gradient(circle at center, rgba(56, 239, 125, 0.12), rgba(79, 140, 255, 0.08) 50%, transparent 70%);
  animation-duration: 36s; animation-delay: -14s;
}
.aurora span:nth-child(4) {
  width: 40vmax; height: 40vmax; top: 10%; right: 5%;
  background: radial-gradient(circle at center, rgba(79, 140, 255, 0.25), transparent 60%);
  animation-duration: 22s; animation-delay: -18s;
}

@keyframes floatOrb {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1) rotate(0deg); }
  33%      { transform: translate3d(5vw, -6vh, 0) scale(1.1) rotate(60deg); }
  66%      { transform: translate3d(-6vw, 4vh, 0) scale(0.92) rotate(120deg); }
}

.light-beam {
  position: absolute; top: -180px; left: 50%; transform: translateX(-50%);
  width: 800px; height: 500px;
  background: radial-gradient(ellipse at top, rgba(79, 140, 255, 0.32), transparent 70%);
  filter: blur(40px);
}

.vignette {
  position: absolute; inset: 0;
  background: radial-gradient(ellipse at center, transparent 40%, rgba(5, 7, 12, 0.85) 100%);
}

header, main, footer { position: relative; z-index: 1; }

/* ── Навигация (Header) ── */
.top {
  position: sticky; top: 0; z-index: 100;
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  background: rgba(5, 7, 12, 0.65);
  border-bottom: 1px solid var(--line);
  transition: border-color 0.3s;
}
.top .wrap { display: flex; align-items: center; justify-content: space-between; gap: 24px; height: 76px; }
.brand { display: flex; align-items: center; min-height: 36px; }
.brand img { height: 28px; max-height: 28px; width: auto; max-width: 180px; object-fit: contain; display: block; filter: drop-shadow(0 2px 8px rgba(79,140,255,.3)); }
.nav { display: flex; gap: 32px; font-size: 14px; font-weight: 600; }
.nav a {
  color: var(--muted); position: relative; padding: 6px 0;
  transition: color 0.2s ease;
}
.nav a::after {
  content: ""; position: absolute; left: 0; bottom: 0; width: 0; height: 2px;
  background: var(--accent); border-radius: 2px; transition: width 0.25s var(--ease);
}
.nav a:hover { color: #fff; }
.nav a:hover::after { width: 100%; }
.head-actions { display: flex; align-items: center; gap: 12px; }

/* ── Кнопки ── */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 10px;
  height: 54px; padding: 0 28px; border-radius: 999px;
  font-size: 16px; font-weight: 700; white-space: nowrap; cursor: pointer;
  position: relative; overflow: hidden;
  transition: transform 0.25s var(--ease), box-shadow 0.25s var(--ease), background 0.2s, border-color 0.2s;
}
.btn svg { width: 19px; height: 19px; flex: none; }

.btn-main {
  background: linear-gradient(135deg, #ffffff 0%, #e2e8f5 100%);
  color: #05070c;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.4), 0 8px 32px rgba(255, 255, 255, 0.16);
}
.btn-main:hover {
  transform: translateY(-2px) scale(1.01);
  box-shadow: 0 0 0 1px #fff, 0 14px 44px rgba(79, 140, 255, 0.4);
}
.btn-main:active { transform: translateY(0) scale(0.99); }

.btn-ghost {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--line-strong);
  color: #fff;
  backdrop-filter: blur(10px);
}
.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.35);
  transform: translateY(-2px);
}

.btn-sm { height: 42px; padding: 0 18px; font-size: 14px; }
.btn-sm svg { width: 16px; height: 16px; }

/* Бегущий луч по периметру кнопки (Border Beam) */
.btn-beam {
  position: relative;
  border: 1px solid rgba(79, 140, 255, 0.4);
}
.btn-beam::before {
  content: ""; position: absolute; inset: -2px; border-radius: 999px;
  background: conic-gradient(from 0deg, transparent 0deg, #4f8cff 60deg, transparent 120deg);
  animation: rotateBeam 4s linear infinite;
  z-index: -1;
}

@keyframes rotateBeam {
  to { transform: rotate(360deg); }
}

/* ── Первый экран (Hero) ── */
.hero { padding-top: clamp(36px, 5vw, 64px); padding-bottom: clamp(60px, 8vw, 100px); }
.hero .wrap {
  display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: clamp(40px, 6vw, 80px); align-items: center;
}
.hero-text { display: flex; flex-direction: column; align-items: flex-start; gap: 24px; }

/* Кибер-бейдж */
.cyber-pill {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 8px 18px 8px 12px; border-radius: 999px;
  border: 1px solid rgba(79, 140, 255, 0.3);
  background: rgba(79, 140, 255, 0.08);
  backdrop-filter: blur(12px);
  font-size: 13px; font-weight: 700; letter-spacing: 0.02em; color: #b6d0ff;
  box-shadow: 0 0 24px rgba(79, 140, 255, 0.2);
}
.pulse-beacon {
  width: 8px; height: 8px; border-radius: 50%; background: var(--accent-cyan);
  box-shadow: 0 0 10px var(--accent-cyan);
  animation: beaconPulse 2s ease-in-out infinite;
}
@keyframes beaconPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(56, 239, 125, 0.6); }
  50%      { box-shadow: 0 0 0 8px rgba(56, 239, 125, 0); }
}

h1 {
  font-size: clamp(36px, 5.6vw, 78px); line-height: 1.04;
  font-weight: 800; letter-spacing: -0.035em; text-wrap: balance;
  overflow-wrap: break-word;
}
.shimmer-text {
  background: linear-gradient(135deg, #ffffff 15%, #9bc2ff 55%, #ffffff 90%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: shine 6s linear infinite;
}
@keyframes shine {
  to { background-position: 200% center; }
}

.lead {
  max-width: 540px; font-size: clamp(16px, 1.4vw, 19px); line-height: 1.6;
  color: var(--muted); text-wrap: pretty;
}
.hero-actions { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 4px; }
.hint { font-size: 13px; color: var(--soft); }
.handle { color: #fff; font-weight: 700; user-select: all; -webkit-user-select: all; }

/* Чипсы платформ */
.chips-wrap { display: flex; flex-direction: column; gap: 10px; margin-top: 8px; }
.chips-label { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--soft); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; list-style: none; padding: 0; margin: 0; }
.chips li {
  padding: 6px 14px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.04); border: 1px solid var(--line);
  font-size: 12px; font-weight: 600; color: var(--muted);
  transition: all 0.2s ease;
}
.chips li:hover {
  background: rgba(79, 140, 255, 0.12);
  border-color: rgba(79, 140, 255, 0.4);
  color: #fff; transform: translateY(-1px);
}

/* ── 3D Hero Визуал и HUD ── */
.visual {
  position: relative; display: flex; justify-content: center;
  perspective: 1200px;
}
.visual-card {
  position: relative; width: min(100%, 460px); aspect-ratio: 4 / 4.8;
  border-radius: 32px;
  background: radial-gradient(circle at 50% 0%, rgba(79, 140, 255, 0.25), rgba(13, 18, 30, 0.9) 70%);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: 0 40px 100px rgba(0, 0, 0, 0.8), 0 0 60px rgba(79, 140, 255, 0.2);
  transition: transform 0.2s ease-out;
  transform-style: preserve-3d;
  overflow: hidden;
}
.visual-card img {
  width: 100%; height: 100%; object-fit: cover; display: block;
  opacity: 0.94;
  transition: opacity 0.3s ease;
}
.visual-card:hover img { opacity: 1; }

/* Угловые кибер-метки HUD */
.hud-corner {
  position: absolute; width: 14px; height: 14px;
  border: 2px solid rgba(79, 140, 255, 0.6); pointer-events: none; z-index: 2;
}
.hud-tl { top: 14px; left: 14px; border-right: none; border-bottom: none; }
.hud-tr { top: 14px; right: 14px; border-left: none; border-bottom: none; }
.hud-bl { bottom: 14px; left: 14px; border-right: none; border-top: none; }
.hud-br { bottom: 14px; right: 14px; border-left: none; border-top: none; }

/* Плавающие плашки HUD */
.hud-badge {
  position: absolute; z-index: 3;
  display: flex; align-items: center; gap: 12px;
  padding: 12px 18px; border-radius: 18px;
  background: rgba(10, 14, 24, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.16);
  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5), 0 0 25px rgba(79, 140, 255, 0.15);
  animation: hudFloat 7s ease-in-out infinite alternate;
}
@keyframes hudFloat {
  0%   { transform: translateY(0); }
  100% { transform: translateY(-8px); }
}

.hud-status { left: -10px; bottom: 36px; }
.hud-speed { right: -12px; top: 40px; animation-delay: -3.5s; }

.hud-icon {
  width: 38px; height: 38px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(79, 140, 255, 0.16); color: var(--accent);
  box-shadow: inset 0 0 12px rgba(79, 140, 255, 0.2);
}
.hud-icon svg { width: 20px; height: 20px; }
.hud-icon.success { background: rgba(56, 239, 125, 0.16); color: var(--accent-cyan); }

.hud-text { display: flex; flex-direction: column; gap: 2px; }
.hud-text b { font-size: 14px; font-weight: 700; color: #fff; }
.hud-text small { font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.ping-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent-cyan); }

/* ── Метрики (Stats Bar) ── */
.metrics { padding-top: 10px; padding-bottom: 50px; }
.metrics-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px;
}
.metric-card {
  padding: 24px 26px; border-radius: 22px;
  background: var(--card); border: 1px solid var(--line);
  backdrop-filter: blur(16px);
  transition: all 0.3s var(--ease);
  position: relative; overflow: hidden;
}
.metric-card::before {
  content: ""; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(79, 140, 255, 0.6), transparent);
  opacity: 0; transition: opacity 0.3s ease;
}
.metric-card:hover {
  transform: translateY(-4px);
  border-color: rgba(79, 140, 255, 0.35);
  background: var(--card-hover);
}
.metric-card:hover::before { opacity: 1; }

.metric-val {
  font-size: clamp(32px, 3vw, 44px); font-weight: 800; letter-spacing: -0.03em;
  color: #fff; line-height: 1; display: flex; align-items: baseline; gap: 4px;
}
.metric-unit { font-size: 20px; font-weight: 700; color: var(--accent); }
.metric-label { font-size: 14px; font-weight: 700; color: #fff; margin-top: 8px; }
.metric-sub { font-size: 12px; color: var(--soft); margin-top: 2px; }

/* ── Архитектура / Интерактивный маршрут ── */
.route-section { padding-block: 40px; }
.route-box {
  padding: clamp(32px, 4vw, 48px); border-radius: 32px;
  background: linear-gradient(180deg, rgba(13, 18, 30, 0.75), rgba(7, 10, 18, 0.85));
  border: 1px solid var(--line-strong);
  backdrop-filter: blur(20px);
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
  position: relative; overflow: hidden;
}
.route-box::after {
  content: ""; position: absolute; inset: 0;
  background: radial-gradient(ellipse at 50% 0%, rgba(79, 140, 255, 0.15), transparent 70%);
  pointer-events: none;
}
.route-head { text-align: center; max-width: 680px; margin: 0 auto 36px; }
.route-head h3 { font-size: clamp(22px, 2.5vw, 32px); font-weight: 800; letter-spacing: -0.02em; }
.route-head p { font-size: 15px; color: var(--muted); margin-top: 8px; }

.route-flow {
  display: grid; grid-template-columns: 1fr auto 1.3fr auto 1fr;
  align-items: center; gap: 16px; position: relative; z-index: 2;
}
.flow-node {
  padding: 20px; border-radius: 20px;
  background: rgba(255, 255, 255, 0.04); border: 1px solid var(--line);
  display: flex; flex-direction: column; align-items: center; text-align: center; gap: 12px;
  transition: all 0.3s ease;
}
.flow-node:hover {
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(79, 140, 255, 0.5);
  transform: translateY(-2px);
}
.flow-node.core {
  background: linear-gradient(180deg, rgba(79, 140, 255, 0.15), rgba(79, 140, 255, 0.04));
  border-color: rgba(79, 140, 255, 0.45);
  box-shadow: 0 0 40px rgba(79, 140, 255, 0.2);
}
.flow-icon {
  width: 48px; height: 48px; border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(79, 140, 255, 0.12); color: var(--accent);
}
.flow-node.core .flow-icon {
  background: var(--accent); color: #fff;
  box-shadow: 0 0 20px var(--accent-glow);
}
.flow-title { font-size: 15px; font-weight: 700; color: #fff; }
.flow-badge {
  font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.06); color: var(--muted);
}
.flow-node.core .flow-badge {
  background: rgba(56, 239, 125, 0.18); color: var(--accent-cyan);
}

.flow-beam {
  position: relative; width: 60px; height: 2px;
  background: rgba(255, 255, 255, 0.15);
  overflow: hidden;
}
.beam-pulse {
  position: absolute; top: 0; left: 0; width: 30px; height: 100%;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: beamFlow 1.8s linear infinite;
}
.beam-pulse.delayed { animation-delay: 0.9s; }
@keyframes beamFlow {
  0%   { transform: translateX(-30px); }
  100% { transform: translateX(60px); }
}

/* ── Разделы (Общее) ── */
.section { padding-block: var(--section); }
.head { display: flex; flex-direction: column; gap: 14px; margin-bottom: clamp(36px, 5vw, 64px); }
.head.center { align-items: center; text-align: center; }
.head.split { flex-direction: row; align-items: flex-end; justify-content: space-between; gap: 48px; }

.eyebrow {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--accent);
}
.eyebrow::before {
  content: ""; width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent); box-shadow: 0 0 8px var(--accent);
}

h2 {
  font-size: clamp(32px, 4.2vw, 56px); line-height: 1.08;
  font-weight: 800; letter-spacing: -0.03em; text-wrap: balance; max-width: 740px;
}
.sub { max-width: 580px; font-size: 17px; line-height: 1.6; color: var(--muted); }
.head.split .sub { max-width: 400px; }

/* ── Bento Grid (Преимущества) ── */
.bento-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;
}
.bento-card {
  position: relative; border-radius: 26px; padding: 34px;
  background: var(--card); border: 1px solid var(--line);
  backdrop-filter: blur(16px);
  display: flex; flex-direction: column; justify-content: space-between; gap: 24px;
  overflow: hidden; cursor: default;
  transition: transform 0.3s var(--ease), border-color 0.3s ease, background 0.3s ease;
}

/* Курсорный Spotlight */
.bento-card::after {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background: radial-gradient(500px circle at var(--mx, 50%) var(--my, 50%), rgba(79, 140, 255, 0.12), transparent 45%);
  opacity: 0; transition: opacity 0.3s ease;
}
.bento-card:hover::after { opacity: 1; }

.bento-card:hover {
  transform: translateY(-4px);
  border-color: rgba(79, 140, 255, 0.45);
  background: var(--card-hover);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4);
}

.bento-card.wide { grid-column: span 2; }

.card-top { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.card-ico {
  width: 54px; height: 54px; border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(79, 140, 255, 0.12); color: var(--accent);
  border: 1px solid rgba(79, 140, 255, 0.25);
  box-shadow: 0 0 24px rgba(79, 140, 255, 0.2);
  transition: transform 0.3s var(--ease);
}
.bento-card:hover .card-ico {
  transform: scale(1.08) rotate(4deg);
  background: var(--accent); color: #fff;
  box-shadow: 0 0 35px var(--accent-glow);
}
.card-ico svg { width: 26px; height: 26px; }

.card-tag {
  font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase;
  padding: 5px 12px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.05); border: 1px solid var(--line);
  color: var(--soft);
}

.bento-card h3 { font-size: 22px; font-weight: 700; letter-spacing: -0.01em; color: #fff; margin-bottom: 8px; }
.bento-card p { font-size: 15px; line-height: 1.6; color: var(--muted); }

/* ── Шаги подключения ── */
.steps-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;
  position: relative;
}
.step-card {
  padding: 38px 32px; border-radius: 26px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.01));
  border: 1px solid var(--line);
  backdrop-filter: blur(16px);
  display: flex; flex-direction: column; gap: 20px;
  position: relative; overflow: hidden;
  transition: transform 0.3s var(--ease), border-color 0.3s ease;
}
.step-card:hover {
  transform: translateY(-4px);
  border-color: rgba(79, 140, 255, 0.4);
}
.step-card:last-child {
  border-color: rgba(79, 140, 255, 0.4);
  background: linear-gradient(180deg, rgba(79, 140, 255, 0.12), rgba(79, 140, 255, 0.02));
  box-shadow: 0 20px 50px rgba(79, 140, 255, 0.12);
}

.step-num {
  font-size: 56px; line-height: 1; font-weight: 800; letter-spacing: -0.04em;
  color: transparent; -webkit-text-stroke: 1.5px rgba(255, 255, 255, 0.35);
  font-family: "Space Grotesk", sans-serif;
}
.step-card:last-child .step-num { -webkit-text-stroke-color: var(--accent); }
.step-card h3 { font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 6px; }
.step-card p { font-size: 15px; line-height: 1.6; color: var(--muted); }

/* ── Тарифы ── */
.plans {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px; align-items: stretch;
}
.plan {
  padding: 42px 34px; border-radius: 28px;
  background: var(--card); border: 1px solid var(--line);
  backdrop-filter: blur(18px);
  display: flex; flex-direction: column; gap: 24px;
  position: relative; overflow: hidden;
  transition: transform 0.3s var(--ease), border-color 0.3s ease, box-shadow 0.3s ease;
}
.plan:hover {
  transform: translateY(-4px);
  border-color: rgba(255, 255, 255, 0.25);
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.5);
}

.plan.best {
  border-color: rgba(79, 140, 255, 0.6);
  background: linear-gradient(180deg, rgba(79, 140, 255, 0.18), rgba(13, 18, 30, 0.95));
  box-shadow: 0 30px 90px rgba(79, 140, 255, 0.25);
  transform: scale(1.02);
}
.plan.best:hover {
  transform: scale(1.03) translateY(-4px);
  box-shadow: 0 35px 100px rgba(79, 140, 255, 0.35);
}

.best-tag {
  align-self: flex-start;
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 14px; border-radius: 999px;
  background: linear-gradient(135deg, #4f8cff, #7952ff);
  color: #fff; font-size: 11px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase;
  box-shadow: 0 0 20px rgba(79, 140, 255, 0.5);
}

.plan-top { display: flex; flex-direction: column; gap: 6px; }
.plan-name { font-size: 20px; font-weight: 700; color: #fff; }
.plan-period { font-size: 14px; color: var(--soft); }

.price-box { display: flex; align-items: baseline; gap: 8px; margin-top: 8px; }
.price-box b {
  font-size: clamp(44px, 4.5vw, 56px); font-weight: 800; letter-spacing: -0.04em;
  color: #fff; line-height: 1; font-family: "Space Grotesk", sans-serif;
}
.price-box span { font-size: 20px; font-weight: 700; color: var(--muted); }

.rule { height: 1px; background: var(--line); }

.perks {
  list-style: none; margin: 0; padding: 0;
  display: flex; flex-direction: column; gap: 14px;
  font-size: 15px; color: rgba(255, 255, 255, 0.85);
}
.perks li { display: flex; align-items: center; gap: 12px; }
.perks svg { width: 18px; height: 18px; flex: none; color: var(--accent); }
.plan.best .perks svg { color: var(--accent-cyan); }

.plan .btn { margin-top: auto; }
.note { margin-top: 32px; text-align: center; font-size: 15px; color: var(--soft); }

/* ── FAQ ── */
.faq .wrap { display: grid; grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr); gap: 70px; }
.qa { display: flex; flex-direction: column; gap: 12px; }
.qa details {
  border-radius: 18px;
  background: var(--card); border: 1px solid var(--line);
  backdrop-filter: blur(14px);
  overflow: hidden; transition: all 0.25s ease;
}
.qa details[open] {
  border-color: rgba(79, 140, 255, 0.4);
  background: var(--card-hover);
}
.qa summary {
  list-style: none; cursor: pointer;
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
  padding: 22px 24px; font-size: 17px; font-weight: 700; color: #fff;
  transition: color 0.2s ease;
}
.qa summary::-webkit-details-marker { display: none; }
.qa summary:hover { color: var(--accent); }

.qa-toggle {
  width: 32px; height: 32px; border-radius: 50%;
  border: 1px solid var(--line-strong);
  display: flex; align-items: center; justify-content: center;
  position: relative; flex: none; transition: transform 0.25s var(--ease), border-color 0.25s;
}
.qa-toggle::before, .qa-toggle::after {
  content: ""; position: absolute; background: #fff; border-radius: 2px;
  transition: transform 0.25s var(--ease);
}
.qa-toggle::before { width: 12px; height: 2px; }
.qa-toggle::after { width: 2px; height: 12px; }
.qa details[open] .qa-toggle { transform: rotate(45deg); border-color: var(--accent); }
.qa details[open] .qa-toggle::before,
.qa details[open] .qa-toggle::after { background: var(--accent); }

.qa p { padding: 0 24px 24px; font-size: 15px; line-height: 1.65; color: var(--muted); }

/* ── Финальный CTA портал ── */
.cta-box {
  position: relative; overflow: hidden;
  display: flex; flex-direction: column; align-items: center; gap: 26px; text-align: center;
  padding: clamp(60px, 8vw, 100px) clamp(24px, 5vw, 60px); border-radius: 40px;
  border: 1px solid rgba(79, 140, 255, 0.35);
  background: radial-gradient(ellipse at 50% -20%, rgba(79, 140, 255, 0.4), rgba(5, 7, 12, 0.95) 75%);
  box-shadow: 0 40px 120px rgba(0, 0, 0, 0.8), 0 0 80px rgba(79, 140, 255, 0.2);
}
.cta-box .mark-img { height: 64px; width: auto; filter: drop-shadow(0 0 20px rgba(79, 140, 255, 0.5)); }
.cta-box h2 { font-size: clamp(36px, 5.2vw, 64px); position: relative; z-index: 1; }
.cta-box p { position: relative; z-index: 1; }
.cta-box .actions { justify-content: center; position: relative; z-index: 1; }

/* ── Подвал (Footer) ── */
.foot { border-top: 1px solid var(--line); }
.foot .wrap {
  display: flex; align-items: center; justify-content: space-between; gap: 24px;
  padding-block: 36px 44px;
}
.foot img { height: 32px; width: auto; opacity: 0.85; }
.foot nav { display: flex; flex-wrap: wrap; gap: 12px 28px; font-size: 14px; font-weight: 600; }
.foot nav a { color: var(--muted); transition: color 0.2s; }
.foot nav a:hover { color: #fff; }
.copy { font-size: 13px; color: var(--soft); }


/* ── Скролл-появление (Reveal) ── */
.js .reveal {
  opacity: 0; transform: translateY(22px);
  transition: opacity 0.85s var(--ease), transform 0.85s var(--ease);
}
.js .reveal.in { opacity: 1; transform: none; }

/* ── Адаптивность (Планшет) ── */
@media (max-width: 1080px) {
  .nav { display: none; }
  .hero .wrap { grid-template-columns: 1fr; gap: 48px; }
  .visual { justify-content: center; }
  .visual-card { width: min(100%, 420px); }
  .metrics-grid { grid-template-columns: repeat(2, 1fr); gap: 14px; }
  .route-flow { grid-template-columns: 1fr; gap: 14px; }
  .flow-beam { display: none; }
  .bento-grid { grid-template-columns: 1fr; }
  .bento-card.wide { grid-column: auto; }
  .steps-grid { grid-template-columns: 1fr; gap: 14px; }
  .faq .wrap { grid-template-columns: 1fr; gap: 32px; }
  .head.split { flex-direction: column; align-items: flex-start; gap: 16px; }
}

/* ── Адаптивность (Телефон) ── */
@media (max-width: 640px) {
  .top .wrap { height: 64px; }
  .top .btn-sm { height: 40px; padding: 0 16px; font-size: 13px; }
  .top .btn-sm .long { display: none; }
  .head-actions { gap: 8px; }

  .hero-text { gap: 20px; }
  .hero-actions { flex-direction: column; width: 100%; }
  .hero-actions .btn { width: 100%; }
  .hint { align-self: center; text-align: center; font-size: 12px; }
  .chips-wrap { align-items: center; }
  .chips { justify-content: center; }

  .visual-card { width: 100%; border-radius: 24px; }
  .hud-status { left: 10px; right: 10px; bottom: 12px; }
  .hud-speed { display: none; }

  .metrics-grid { grid-template-columns: 1fr; }
  .metric-card { padding: 18px 20px; }

  .bento-card { padding: 24px; border-radius: 20px; }
  .card-ico { width: 46px; height: 46px; }
  .card-ico svg { width: 22px; height: 22px; }
  .bento-card h3 { font-size: 19px; }

  .step-card { padding: 26px 22px; border-radius: 20px; }
  .step-num { font-size: 42px; }

  .plans { grid-template-columns: 1fr; gap: 14px; }
  .plan { padding: 28px 24px; border-radius: 22px; }
  .plan.best { transform: none; }
  .plan.best:hover { transform: translateY(-3px); }
  .price-box b { font-size: 38px; }

  .cta-box { padding: 48px 20px; border-radius: 28px; }
  .cta-box .actions { flex-direction: column; width: 100%; }
  .cta-box .btn { width: 100%; }

  .foot .wrap { flex-direction: column; text-align: center; gap: 20px; padding-block: 28px 36px; }
  .foot nav { flex-direction: column; align-items: center; gap: 8px; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
  .js .reveal { opacity: 1; transform: none; }
}
"""

JS_HEAD = "document.documentElement.classList.add('js');"

JS = """
(function () {
  var items = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: '0px 0px -6% 0px' });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add('in'); });
  }

  var bentoCards = document.querySelectorAll('.bento-card');
  bentoCards.forEach(function (card) {
    card.addEventListener('mousemove', function (e) {
      var rect = card.getBoundingClientRect();
      var x = e.clientX - rect.left;
      var y = e.clientY - rect.top;
      card.style.setProperty('--mx', x + 'px');
      card.style.setProperty('--my', y + 'px');
    });
  });

  var visual = document.querySelector('.visual');
  var visualCard = document.querySelector('.visual-card');
  if (visual && visualCard && window.matchMedia('(min-width: 768px)').matches) {
    visual.addEventListener('mousemove', function (e) {
      var rect = visual.getBoundingClientRect();
      var x = (e.clientX - rect.left) / rect.width - 0.5;
      var y = (e.clientY - rect.top) / rect.height - 0.5;
      visualCard.style.transform = 'perspective(1000px) rotateY(' + (x * 12) + 'deg) rotateX(' + (-y * 12) + 'deg)';
    });
    visual.addEventListener('mouseleave', function () {
      visualCard.style.transform = 'perspective(1000px) rotateY(0deg) rotateX(0deg)';
    });
  }

  var pingEl = document.getElementById('heroPing');
  if (pingEl) {
    setInterval(function () {
      var p = Math.floor(Math.random() * 5) + 11;
      pingEl.textContent = p;
    }, 2800);
  }
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
               channel_url: str = "", logo_file: str = LOGO_URL,
               tariffs: list | None = None,
               poster_file: str = "og.webp",
               cabinet_url: str = "",
               site_texts: dict | None = None) -> str:
    """Собирает ультрасовременную страницу с поддержкой динамических текстов."""
    handle = bot_username.lstrip("@")
    bot_url = escape(f"https://t.me/{handle}" if handle else "https://t.me/")
    name = escape(title)
    tariffs = tariffs or []

    # Получаем актуальные тексты (с учётом правок из админки)
    txt = get_site_texts(site_texts)

    # Логотип — блок 1:1 со страницы подписки (web/subpage.html): всегда
    # картинка PNG из assets репозитория, без рисованного SVG-запасника.
    logo_src = escape(logo_file or LOGO_URL)
    brand_html = f'<img id="brandLogo" src="{logo_src}" alt="{name}" width="492" height="132">'
    cta_logo = f'<img class="mark-img" src="{logo_src}" alt="" width="492" height="132">'
    foot_logo = f'<img src="{logo_src}" alt="{name}" width="492" height="132">'

    hint_html = (f'<p class="hint">Не открылось? Найдите в Telegram: '
                 f'<span class="handle">@{escape(handle)}</span></p>' if handle else "")

    chips = "".join(f"<li>{escape(p)}</li>" for p in PLATFORMS)

    # 3D Hero Poster / Terminal
    visual_html = ""
    if poster_file:
        visual_html = f"""
    <div class="visual reveal">
      <div class="visual-card">
        <div class="hud-corner hud-tl"></div>
        <div class="hud-corner hud-tr"></div>
        <div class="hud-corner hud-bl"></div>
        <div class="hud-corner hud-br"></div>
        <img src="{escape(poster_file)}" alt="Drebol VPN Shield" width="1122" height="1402">
      </div>
      <div class="hud-badge hud-speed">
        <div class="hud-icon">{_ICONS["speed"]}</div>
        <div class="hud-text">
          <b>{escape(txt['hero_hud_speed'])}</b>
        </div>
      </div>
      <div class="hud-badge hud-status">
        <div class="hud-icon success">{_ICONS["shield"]}</div>
        <div class="hud-text">
          <b>{escape(txt['hero_hud_status'])}</b>
          <small><span class="ping-dot"></span>Пинг: <span id="heroPing">12</span> ms</small>
        </div>
      </div>
    </div>"""

    # Bento карточки возможностей
    features_data = [
        ("nolog", txt["feat1_title"], txt["feat1_desc"], txt["feat1_tag"]),
        ("bolt", txt["feat2_title"], txt["feat2_desc"], txt["feat2_tag"]),
        ("devices", txt["feat3_title"], txt["feat3_desc"], txt["feat3_tag"]),
        ("shield", txt["feat4_title"], txt["feat4_desc"], txt["feat4_tag"]),
        ("gift", txt["feat5_title"], txt["feat5_desc"], txt["feat5_tag"]),
        ("card", txt["feat6_title"], txt["feat6_desc"], txt["feat6_tag"]),
    ]
    bento_items = []
    for i, (icon, h, t, tag) in enumerate(features_data):
        is_wide = (i == 0 or i == 3)
        bento_items.append(f"""
      <article class="bento-card{' wide' if is_wide else ''} reveal">
        <div class="card-top">
          <div class="card-ico">{_ICONS[icon]}</div>
          <span class="card-tag">{escape(tag)}</span>
        </div>
        <div>
          <h3>{escape(h)}</h3>
          <p>{escape(t)}</p>
        </div>
      </article>""")
    features_html = "".join(bento_items)

    # Шаги подключения
    steps_data = [
        (txt["step1_title"], txt["step1_desc"], "01"),
        (txt["step2_title"], txt["step2_desc"], "02"),
        (txt["step3_title"], txt["step3_desc"], "03"),
    ]
    steps_html = "".join(f"""
      <article class="step-card reveal">
        <span class="step-num">{num}</span>
        <div>
          <h3>{escape(h)}</h3>
          <p>{escape(t)}</p>
        </div>
      </article>""" for h, t, num in steps_data)

    perks_html = "".join(f"<li>{_CHECK}{escape(p)}</li>" for p in TARIFF_PERKS)

    pricing_html = ""
    cab = escape(cabinet_url) if cabinet_url else ""
    cab_nav = (f'<a class="btn btn-ghost btn-sm" href="{cab}">{_ICONS["cabinet"]}'
               '<span>Кабинет</span></a>' if cab else "")
    cab_cta = (f'<a class="btn btn-ghost" href="{cab}">{_ICONS["cabinet"]}Личный кабинет</a>'
               if cab else "")

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
            is_best = (i == best)
            btn_cls = "btn btn-main" if is_best else "btn btn-ghost"
            best_badge = '<span class="best-tag">🔥 Самый популярный</span>' if is_best else ""
            cards.append(f"""
      <article class="plan{' best' if is_best else ''} reveal">
        {best_badge}
        <div class="plan-top">
          <div class="plan-name">{escape(t_name)}</div>
          {period_html}
          <div class="price-box">
            <b>{_fmt_price(t.get("price", ""))}</b>
            <span>₽</span>
          </div>
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
      <h2>{escape(txt['tariffs_title'])}</h2>
      <p class="sub">{escape(txt['tariffs_sub'])}</p>
    </div>
    <div class="plans">{"".join(cards)}</div>
    <p class="note">{escape(txt['tariffs_note'])}</p>
  </div>
</section>"""
        nav_pricing = '<a href="#pricing">Тарифы</a>'
        hero_second = '<a class="btn btn-ghost" href="#pricing">Тарифы</a>'
    elif channel_url:
        hero_second = f'<a class="btn btn-ghost" href="{escape(channel_url)}">Наш канал</a>'

    faq_data = [
        (txt["faq1_q"], txt["faq1_a"]),
        (txt["faq2_q"], txt["faq2_a"]),
        (txt["faq3_q"], txt["faq3_a"]),
        (txt["faq4_q"], txt["faq4_a"]),
        (txt["faq5_q"], txt["faq5_a"]),
    ]
    faq_html = "".join(f"""
      <details{' open' if i == 0 else ''}>
        <summary>
          <span>{escape(q)}</span>
          <span class="qa-toggle" aria-hidden="true"></span>
        </summary>
        <p>{escape(a)}</p>
      </details>""" for i, (q, a) in enumerate(faq_data))

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
<meta name="description" content="{escape(tagline)}. Быстрое и надёжное подключение прямо в Telegram. Поддержка iOS, Android, Windows и macOS.">
<meta property="og:type" content="website">
<meta property="og:title" content="{name}">
<meta property="og:description" content="{escape(tagline)}">
{og_meta}
<meta name="theme-color" content="#05070c">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cg fill='none' stroke='%234f8cff' stroke-width='7'%3E%3Ccircle cx='50' cy='50' r='40'/%3E%3Cellipse cx='50' cy='50' rx='40' ry='13'/%3E%3C/g%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@600;700;800&display=swap" rel="stylesheet">
<style>{CSS}</style>
<script>{JS_HEAD}</script>
</head>
<body>
<div class="bg" aria-hidden="true">
  <div class="aurora">
    <span></span><span></span><span></span><span></span>
  </div>
  <div class="light-beam"></div>
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
    <div class="head-actions">
      {cab_nav}
      <a class="btn btn-ghost btn-sm" href="{bot_url}">{_TG}<span>Открыть<span class="long"> бота</span></span></a>
    </div>
  </div>
</header>

<main>
<!-- ── Первый экран (Hero) ── -->
<section class="hero" id="top">
  <div class="wrap">
    <div class="hero-text reveal">
      <div class="cyber-pill">
        <span class="pulse-beacon"></span>
        <span>{escape(txt['hero_pill'])}</span>
      </div>
      <h1>{escape(txt['hero_title'])} <span class="shimmer-text">{escape(txt['hero_shimmer'])}</span></h1>
      <p class="lead">{escape(txt['hero_lead'])}</p>
      <div class="hero-actions">
        <a class="btn btn-main btn-beam" href="{bot_url}">{_TG}{escape(txt['hero_btn'])}</a>
        {hero_second}
      </div>
      {hint_html}
      <div class="chips-wrap">
        <span class="chips-label">Доступно для всех устройств</span>
        <ul class="chips" aria-label="Платформы">{chips}</ul>
      </div>
    </div>{visual_html}
  </div>
</section>

<!-- ── Метрики сети ── -->
<section class="metrics">
  <div class="wrap">
    <div class="metrics-grid reveal">
      <div class="metric-card">
        <div class="metric-val">{escape(txt['metric1_val'])}<span class="metric-unit">{escape(txt['metric1_unit'])}</span></div>
        <div class="metric-label">{escape(txt['metric1_label'])}</div>
        <div class="metric-sub">{escape(txt['metric1_sub'])}</div>
      </div>
      <div class="metric-card">
        <div class="metric-val">{escape(txt['metric2_val'])}<span class="metric-unit">{escape(txt['metric2_unit'])}</span></div>
        <div class="metric-label">{escape(txt['metric2_label'])}</div>
        <div class="metric-sub">{escape(txt['metric2_sub'])}</div>
      </div>
      <div class="metric-card">
        <div class="metric-val">{escape(txt['metric3_val'])}<span class="metric-unit">{escape(txt['metric3_unit'])}</span></div>
        <div class="metric-label">{escape(txt['metric3_label'])}</div>
        <div class="metric-sub">{escape(txt['metric3_sub'])}</div>
      </div>
      <div class="metric-card">
        <div class="metric-val">{escape(txt['metric4_val'])}<span class="metric-unit">{escape(txt['metric4_unit'])}</span></div>
        <div class="metric-label">{escape(txt['metric4_label'])}</div>
        <div class="metric-sub">{escape(txt['metric4_sub'])}</div>
      </div>
    </div>
  </div>
</section>

<!-- ── Визуализатор архитектуры ── -->
<section class="route-section">
  <div class="wrap">
    <div class="route-box reveal">
      <div class="route-head">
        <span class="eyebrow">Архитектура</span>
        <h3>{escape(txt['route_title'])}</h3>
        <p>{escape(txt['route_sub'])}</p>
      </div>
      <div class="route-flow">
        <div class="flow-node">
          <div class="flow-icon">{_ICONS["devices"]}</div>
          <div class="flow-title">{escape(txt['route_node1'])}</div>
          <span class="flow-badge">{escape(txt['route_badge1'])}</span>
        </div>
        <div class="flow-beam"><div class="beam-pulse"></div></div>
        <div class="flow-node core">
          <div class="flow-icon">{_ICONS["shield"]}</div>
          <div class="flow-title">{escape(txt['route_node2'])}</div>
          <span class="flow-badge">{escape(txt['route_badge2'])}</span>
        </div>
        <div class="flow-beam"><div class="beam-pulse delayed"></div></div>
        <div class="flow-node">
          <div class="flow-icon">{_ICONS["globe"]}</div>
          <div class="flow-title">{escape(txt['route_node3'])}</div>
          <span class="flow-badge">{escape(txt['route_badge3'])}</span>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- ── Bento Grid: Преимущества ── -->
<section class="section" id="features">
  <div class="wrap">
    <div class="head split reveal">
      <div class="head" style="margin:0">
        <span class="eyebrow">Преимущества</span>
        <h2>Создан для скорости, простоты и надёжности.</h2>
      </div>
      <p class="sub">Мы избавились от всего лишнего: громоздких регистраций, ведения истории и падений скорости в часы пик.</p>
    </div>
    <div class="bento-grid">
      {features_html}
    </div>
  </div>
</section>

<!-- ── Как подключить ── -->
<section class="section" id="how">
  <div class="wrap">
    <div class="head center reveal">
      <span class="eyebrow">Инструкция</span>
      <h2>Всего 3 простых шага</h2>
      <p class="sub">Вам не нужно разбираться в настройках — бот подготовит всё за вас в один клик.</p>
    </div>
    <div class="steps-grid">
      {steps_html}
    </div>
  </div>
</section>

{pricing_html}

<!-- ── Вопросы и ответы ── -->
<section class="section faq" id="faq">
  <div class="wrap">
    <div class="head reveal">
      <span class="eyebrow">FAQ</span>
      <h2>Частые вопросы</h2>
      <p class="sub">Если у вас останутся вопросы — наша служба заботы на связи прямо в боте.</p>
    </div>
    <div class="qa reveal">
      {faq_html}
    </div>
  </div>
</section>

<!-- ── Финальный призыв ── -->
<section class="section">
  <div class="wrap">
    <div class="cta-box reveal">
      {cta_logo}
      <h2>{escape(txt['cta_title'])}</h2>
      <p class="sub">{escape(txt['cta_sub'])}</p>
      <div class="actions">
        <a class="btn btn-main btn-beam" href="{bot_url}">{_TG}{escape(txt['hero_btn'])}</a>
        {cab_cta}
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
