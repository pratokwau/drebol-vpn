"""Страница-визитка Drebol VPN.

Один самодостаточный файл: фон, логотип и анимации нарисованы кодом, поэтому
страница одинаково хорошо выглядит и на телефоне, и на большом экране, и не
зависит от сторонних картинок. Фирменная картинка нужна только для превью
ссылки в мессенджерах — её отдаём как og:image.
"""

from html import escape


def build_page(bot_username: str, title: str = "Drebol VPN",
               tagline: str = "Быстрый VPN без логов",
               privacy_url: str = "", terms_url: str = "",
               channel_url: str = "", logo_file: str = "") -> str:
    """logo_file — имя файла с настоящим логотипом рядом со страницей.

    Если его нет, страница рисует логотип линиями — так она никогда не
    остаётся без знака, даже когда картинку не залили.
    """
    handle = bot_username.lstrip("@")
    bot_url = f"https://t.me/{handle}" if handle else "https://t.me/"
    hint_html = (f'<p class="hint">Не открылось? Введите в Telegram '
                 f'<span class="handle">@{escape(handle)}</span></p>'
                 if handle else "")
    docs = []
    if privacy_url:
        docs.append(f'<a href="{escape(privacy_url)}">Политика</a>')
    if terms_url:
        docs.append(f'<a href="{escape(terms_url)}">Соглашение</a>')
    docs_html = " · ".join(docs)
    channel_html = (
        f'<a class="ghost" href="{escape(channel_url)}">Наш канал</a>'
        if channel_url else ""
    )
    year = "2026"
    if logo_file:
        logo_html = (f'<img class="logo-img" src="{escape(logo_file)}" '
                     f'alt="{escape(title)}" width="523" height="162">')
    else:
        logo_html = (
            '<div class="logo">'
            '<svg class="mark" viewBox="0 0 100 100" aria-hidden="true">'
            '<circle cx="50" cy="50" r="40"></circle>'
            '<ellipse class="flat" cx="50" cy="50" rx="40" ry="13"></ellipse>'
            '<ellipse class="lens" cx="50" cy="50" rx="22" ry="40"></ellipse>'
            '</svg>'
            f'<div class="word">{escape(title.split()[0].lower())}</div>'
            '</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{escape(title)}</title>
<meta name="description" content="{escape(tagline)}. Подключение за минуту, любые устройства.">
<meta property="og:type" content="website">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(tagline)}">
<meta property="og:image" content="og.webp">
<meta name="theme-color" content="#05070c">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cg fill='none' stroke='white' stroke-width='7'%3E%3Ccircle cx='50' cy='50' r='40'/%3E%3Cellipse cx='50' cy='50' rx='40' ry='13'/%3E%3Cellipse cx='50' cy='50' rx='22' ry='40'/%3E%3C/g%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #05070c;
    --ink: #ffffff;
    --muted: rgba(255, 255, 255, .62);
    --line: rgba(255, 255, 255, .14);
    --accent: #4f8cff;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ height: 100%; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: Manrope, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    -webkit-font-smoothing: antialiased;
    overflow-x: hidden;
    display: grid;
    place-items: center;
    min-height: 100svh;
    padding: 40px 16px;
  }}

  /* Шёлк: несколько мягких пятен, которые медленно плывут друг сквозь друга */
  .silk {{ position: fixed; inset: -20%; z-index: 0; filter: blur(60px); opacity: .9; }}
  .silk span {{
    position: absolute; border-radius: 50%;
    background: radial-gradient(circle at 30% 30%, rgba(79,140,255,.62), transparent 60%);
    animation: drift 26s ease-in-out infinite;
  }}
  .silk span:nth-child(1) {{ width: 60vmax; height: 60vmax; top: -10%; left: -5%; }}
  .silk span:nth-child(2) {{
    width: 50vmax; height: 50vmax; bottom: -15%; right: -10%;
    background: radial-gradient(circle at 60% 40%, rgba(120,140,190,.48), transparent 62%);
    animation-duration: 32s; animation-delay: -8s;
  }}
  .silk span:nth-child(3) {{
    width: 42vmax; height: 42vmax; top: 35%; left: 45%;
    background: radial-gradient(circle at 50% 50%, rgba(255,255,255,.14), transparent 65%);
    animation-duration: 38s; animation-delay: -16s;
  }}
  @keyframes drift {{
    0%, 100% {{ transform: translate3d(0, 0, 0) scale(1); }}
    33%      {{ transform: translate3d(6vw, -4vh, 0) scale(1.12); }}
    66%      {{ transform: translate3d(-5vw, 5vh, 0) scale(.94); }}
  }}
  /* Складки ткани: широкие мягкие полосы света под углом */
  .folds {{
    position: fixed; inset: -25%; z-index: 1; pointer-events: none;
    background:
      linear-gradient(104deg,
        transparent 6%, rgba(255,255,255,.10) 14%, transparent 24%,
        rgba(160,190,255,.09) 34%, transparent 44%,
        rgba(255,255,255,.07) 58%, transparent 68%,
        rgba(255,255,255,.05) 82%, transparent 92%);
    filter: blur(26px);
    animation: fold 22s ease-in-out infinite alternate;
  }}
  @keyframes fold {{
    from {{ transform: translate3d(-3%, 0, 0) skewY(-1.5deg) scaleY(1.05); }}
    to   {{ transform: translate3d(3%, 0, 0) skewY(1.5deg) scaleY(.98); }}
  }}

  /* Блик, будто по ткани проходит свет */
  .sheen {{
    position: fixed; inset: 0; z-index: 1; pointer-events: none;
    background: linear-gradient(115deg, transparent 35%, rgba(255,255,255,.07) 50%, transparent 65%);
    background-size: 300% 300%;
    animation: sweep 14s linear infinite;
  }}
  @keyframes sweep {{ from {{ background-position: 120% 0; }} to {{ background-position: -60% 0; }} }}
  .grain {{
    position: fixed; inset: 0; z-index: 2; pointer-events: none; opacity: .5;
    background: radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,.75) 100%);
  }}

  main {{ position: relative; z-index: 3; text-align: center; max-width: 560px; width: 100%; }}

  .logo-img {{
    display: block; width: min(78vw, 360px); height: auto; margin: 0 auto;
    opacity: 0; filter: drop-shadow(0 8px 30px rgba(120,170,255,.25));
    animation: rise 1s .2s cubic-bezier(.2,.8,.2,1) forwards, float 8s 1.2s ease-in-out infinite;
  }}
  @keyframes float {{
    0%, 100% {{ transform: translateY(0); }}
    50%      {{ transform: translateY(-7px); }}
  }}

  .logo {{ display: flex; align-items: center; justify-content: center; gap: 18px; }}
  .mark {{ width: 68px; height: 68px; flex: none; animation: breathe 7s ease-in-out infinite; }}
  .mark circle, .mark ellipse {{
    fill: none; stroke: #fff; stroke-width: 6;
    stroke-dasharray: 300; stroke-dashoffset: 300;
    animation: draw 1.6s cubic-bezier(.65,0,.35,1) forwards;
  }}
  .mark ellipse.flat {{ animation-delay: .25s; }}
  .mark ellipse.lens {{ animation-delay: .5s; transform-origin: 50% 50%; }}
  @keyframes draw {{ to {{ stroke-dashoffset: 0; }} }}
  @keyframes breathe {{
    0%, 100% {{ transform: rotate(0deg) scale(1); }}
    50%      {{ transform: rotate(4deg) scale(1.04); }}
  }}
  .word {{
    font-size: clamp(42px, 11vw, 68px); font-weight: 800; letter-spacing: -.02em;
    opacity: 0; animation: rise .9s .5s cubic-bezier(.2,.8,.2,1) forwards;
  }}

  .tagline {{
    margin: 18px 0 0; font-size: clamp(15px, 4vw, 19px); color: var(--muted);
    opacity: 0; animation: rise .9s .75s cubic-bezier(.2,.8,.2,1) forwards;
  }}

  .cta {{
    display: inline-flex; align-items: center; gap: 10px;
    margin-top: 34px; padding: 17px 34px; border-radius: 999px;
    background: #fff; color: #05070c; text-decoration: none;
    font-weight: 800; font-size: 17px;
    box-shadow: 0 10px 40px rgba(255,255,255,.18);
    opacity: 0; animation: rise .9s 1s cubic-bezier(.2,.8,.2,1) forwards, glow 3.6s 2s ease-in-out infinite;
    transition: transform .25s ease, box-shadow .25s ease;
  }}
  .cta:hover {{ transform: translateY(-2px); box-shadow: 0 16px 50px rgba(255,255,255,.28); }}
  .cta svg {{ width: 20px; height: 20px; }}
  @keyframes glow {{
    0%, 100% {{ box-shadow: 0 10px 40px rgba(255,255,255,.18); }}
    50%      {{ box-shadow: 0 10px 52px rgba(120,170,255,.45); }}
  }}

  .hint {{
    margin: 14px 0 0; font-size: 14px; color: rgba(255,255,255,.45);
    opacity: 0; animation: rise .9s 1.1s cubic-bezier(.2,.8,.2,1) forwards;
  }}
  .handle {{
    color: rgba(255,255,255,.85); font-weight: 600;
    user-select: all; -webkit-user-select: all;
  }}

  .feats {{
    list-style: none; padding: 0; margin: 40px 0 0;
    display: flex; flex-wrap: wrap; gap: 10px; justify-content: center;
    opacity: 0; animation: rise .9s 1.2s cubic-bezier(.2,.8,.2,1) forwards;
  }}
  .feats li {{
    border: 1px solid var(--line); border-radius: 999px;
    padding: 9px 16px; font-size: 14px; color: var(--muted);
    backdrop-filter: blur(6px);
  }}

  footer {{
    margin-top: 44px; font-size: 13px; color: rgba(255,255,255,.38);
    opacity: 0; animation: rise .9s 1.4s cubic-bezier(.2,.8,.2,1) forwards;
  }}
  footer a, .ghost {{ color: rgba(255,255,255,.62); text-decoration: none; }}
  footer a:hover, .ghost:hover {{ color: #fff; }}
  .ghost {{ display: inline-block; margin-top: 18px; font-size: 15px; border-bottom: 1px solid var(--line); }}

  @keyframes rise {{ from {{ opacity: 0; transform: translateY(14px); }} to {{ opacity: 1; transform: none; }} }}

  @media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{ animation: none !important; transition: none !important; }}
    .word, .tagline, .cta, .hint, .feats, footer, .logo-img {{ opacity: 1; }}
    .mark circle, .mark ellipse {{ stroke-dashoffset: 0; }}
  }}
</style>
</head>
<body>
<div class="silk"><span></span><span></span><span></span></div>
<div class="folds"></div>
<div class="sheen"></div>
<div class="grain"></div>

<main>
  {logo_html}

  <p class="tagline">{escape(tagline)}</p>

  <a class="cta" href="{escape(bot_url)}">
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M21.9 4.3 18.7 19c-.2 1-.9 1.3-1.8.8l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5l.4-5 9.1-8.2c.4-.4-.1-.6-.6-.2L6.2 12.9l-4.8-1.5c-1-.3-1-1 .2-1.5l18.9-7.3c.9-.3 1.6.2 1.4 1.7z"/>
    </svg>
    Открыть в Telegram
  </a>

  {hint_html}

  <ul class="feats">
    <li>Без логов</li>
    <li>iOS · Android · Windows · macOS</li>
    <li>Подключение за минуту</li>
  </ul>

  {channel_html}

  <footer>
    {docs_html}{" · " if docs_html else ""}© {year} {escape(title)}
  </footer>
</main>
</body>
</html>
"""
