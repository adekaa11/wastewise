"""Внешний вид сайта: цвета, шрифты и готовые блоки интерфейса.

Весь CSS собран здесь, чтобы app.py остался про логику, а не про оформление.
Палитра совпадает с презентацией проекта — сайт и слайды выглядят как одно целое.
"""
import streamlit as st

INK = "#102A1E"      # почти чёрный зелёный — текст и тёмные фоны
PAPER = "#F7F6F1"    # тёплый белый — фон страницы
SURFACE = "#FFFFFF"  # карточки
LINE = "#E3E6E0"     # границы
GREEN = "#2F9E68"    # акцент
AMBER = "#E08A2E"    # второй акцент
MUTED = "#4A5A52"    # приглушённый текст

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rubik:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

html, body, [class*="css"], .stApp {{ font-family:'IBM Plex Sans', system-ui, sans-serif; }}
.stApp {{ background:{PAPER}; color:{INK}; }}
h1, h2, h3 {{ font-family:'Rubik', system-ui, sans-serif; letter-spacing:-.01em; color:{INK}; }}
h1 {{ font-size:2.3rem; }}
h2 {{ font-size:1.7rem; padding-top:.6rem; }}

/* ---------- Боковое меню ---------- */
section[data-testid="stSidebar"] {{ background:{INK}; border-right:none; }}
section[data-testid="stSidebar"] * {{ color:#C9DCD2; }}
section[data-testid="stSidebar"] h3 {{ color:{PAPER}; }}
section[data-testid="stSidebar"] [role="radiogroup"] label {{
    padding:.3rem .2rem; border-radius:10px; }}
section[data-testid="stSidebar"] .stButton button {{
    background:transparent; border:1px solid #2C5443; color:#C9DCD2; width:100%; }}
.ww-logo {{ background:{SURFACE}; border-radius:16px; padding:10px; display:inline-block; }}
.ww-logo img {{ display:block; border-radius:8px; width:150px; }}

/* ---------- Кнопки, вкладки, поля ---------- */
.stButton button, .stFormSubmitButton button, .stDownloadButton button {{
    border-radius:999px; font-weight:600; padding:.5rem 1.4rem; border:1px solid {LINE};
    transition:transform .08s ease; }}
.stButton button:hover, .stFormSubmitButton button:hover {{ transform:translateY(-1px); }}
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] {{
    background:{GREEN}; border-color:{GREEN}; color:#fff; }}
.stTabs [data-baseweb="tab"] {{ font-weight:600; }}
.stTabs [aria-selected="true"] {{ color:{GREEN}; }}

/* ---------- Метрики ---------- */
[data-testid="stMetric"] {{
    background:{SURFACE}; border:1px solid {LINE}; border-radius:16px; padding:18px 22px; }}
[data-testid="stMetricValue"] {{
    font-family:'Rubik', sans-serif; font-weight:600; color:{GREEN}; }}
[data-testid="stMetricLabel"] p {{ color:{MUTED}; font-size:.9rem; }}

/* ---------- Свои блоки ---------- */
.ww-hero {{
    position:relative; border-radius:22px; overflow:hidden; padding:72px 56px;
    display:flex; flex-direction:column; gap:14px; margin-bottom:34px; }}
.ww-hero h1 {{ color:#fff; font-size:clamp(1.7rem, 3.4vw, 3rem); line-height:1.12;
    margin:0; max-width:17ch; text-shadow:0 2px 18px rgba(0,0,0,.35); }}
.ww-hero p {{ color:#D9E8DF; font-size:clamp(1rem, 1.3vw, 1.2rem); margin:0; max-width:46ch; }}
.ww-eyebrow {{ color:#8FD5AE; font-weight:600; font-size:.8rem;
    letter-spacing:.16em; text-transform:uppercase; margin:0; }}

.ww-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:18px; }}
.ww-card {{ background:{SURFACE}; border:1px solid {LINE}; border-radius:18px;
    padding:26px 24px; display:flex; flex-direction:column; gap:8px; }}
.ww-card h3 {{ margin:0; font-size:1.15rem; }}
.ww-card p {{ margin:0; color:{MUTED}; font-size:.95rem; line-height:1.5; }}
.ww-num {{ font-family:'Rubik', sans-serif; font-size:1.6rem; font-weight:600; color:{GREEN};
    line-height:1; }}

.ww-quote {{ background:{SURFACE}; border-left:5px solid {AMBER}; border-radius:14px;
    padding:22px 26px; color:{MUTED}; font-size:1rem; line-height:1.6; }}

.ww-result {{ background:{SURFACE}; border:1px solid {LINE}; border-radius:18px; padding:26px 28px; }}
.ww-chip {{ display:inline-block; background:#EAF5EF; color:{GREEN}; font-weight:600;
    border-radius:999px; padding:4px 14px; font-size:.85rem; }}

.ww-foot {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
.ww-foot a {{ display:inline-flex; align-items:center; gap:7px; text-decoration:none;
    color:{GREEN}; font-weight:600; font-size:.9rem; border:1px solid {GREEN};
    border-radius:999px; padding:5px 14px; }}
section[data-testid="stSidebar"] .ww-foot a {{ color:#8FD5AE; border-color:#2C5443; }}
</style>
"""


def inject():
    """Подключить оформление. Вызывается один раз в начале app.py."""
    st.markdown(CSS, unsafe_allow_html=True)


def hero(image_b64, eyebrow, title, subtitle):
    """Крупный блок вверху главной: картинка с затемнением и текст поверх."""
    scrim = ("linear-gradient(95deg, rgba(16,42,30,.93) 0%, rgba(16,42,30,.78) 42%,"
             " rgba(16,42,30,.30) 100%)")
    st.markdown(
        f'<div class="ww-hero" style="background-image:{scrim},'
        f"url('data:image/jpeg;base64,{image_b64}');background-size:cover;"
        f'background-position:center">'
        f'<p class="ww-eyebrow">{eyebrow}</p><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def cards(items):
    """Ряд карточек. items — список (номер, заголовок, текст)."""
    html = "".join(
        f'<div class="ww-card"><div class="ww-num">{num}</div>'
        f"<h3>{title}</h3><p>{text}</p></div>"
        for num, title, text in items
    )
    st.markdown(f'<div class="ww-grid">{html}</div>', unsafe_allow_html=True)


def quote(text):
    st.markdown(f'<div class="ww-quote">{text}</div>', unsafe_allow_html=True)
