"""Внешний вид сайта: цвета, шрифты и готовые блоки интерфейса.

Весь CSS и HTML собраны здесь, чтобы app.py остался про логику, а не про оформление.
Палитра совпадает с презентацией проекта — сайт и слайды выглядят как одно целое.

Фирменный приём — цвета баков: у каждого типа отходов свой цвет (core/content.py, поле "color"),
как у настоящих контейнеров. Он проходит через все страницы: полоса под заголовком, «бирка»
с ответом модели, столбики рейтинга и история в профиле.

Всё, что вводят пользователи (имя, школа), попадает в HTML только через esc() — иначе можно было бы
вставить на чужую страницу свой код.
"""
import html
from datetime import datetime, timedelta

import streamlit as st

from .i18n import _, lang as current_lang

INK = "#102A1E"      # почти чёрный зелёный — текст и тёмные фоны (светлая тема)
PAPER = "#F7F6F1"    # тёплый белый — фон страницы
SURFACE = "#FFFFFF"  # карточки
LINE = "#E3E6E0"     # границы
GREEN = "#2F9E68"    # акцент
AMBER = "#E08A2E"    # второй акцент
MUTED = "#4A5A52"    # приглушённый текст
LIME = "#C8F169"     # яркая подсветка: активный пункт меню, выделенное слово в заголовке

# Цвета, которые меняются вместе с темой. CSS ниже пишет только var(--имя), поэтому тёмная тема —
# это просто другой набор значений (DESIGN.md, раздел «Цвета»). Цвета баков от темы не зависят.
LIGHT = {
    "bg": PAPER, "surface": SURFACE, "line": LINE, "ink": INK, "muted": MUTED,
    "edge": INK,          # обводка «наклеек»
    "shadow": INK,        # жёсткая тень «наклеек»
    "panel": INK,         # тёмные плашки: герой, заголовок страницы, табло с числами, итог викторины
    "sidebar": INK,
    "mint": "#EEF5F0",    # мягкий зелёный фон: факт, «это вы», выбранный ответ
    "warm": "#FFF4E6",    # мягкий оранжевый фон: «не принимают», цитата, предупреждение
    "rose": "#FDECEC",    # мягкий красный фон: ошибка
    "track": "#E9ECE6",   # дорожка столбиков
    "off": "#8A968F",     # «скоро» — тип, который модель ещё не знает
    "scheme": "light",
}
DARK = {
    "bg": "#0F1A15", "surface": "#18291F", "line": "#2B4135", "ink": "#ECF3EE", "muted": "#A9BDB2",
    "edge": "#3F6352", "shadow": "#030806", "panel": "#0A1410", "sidebar": "#08110D",
    "mint": "#1D3529", "warm": "#352819", "rose": "#3A1E1E", "track": "#283C31", "off": "#73897D",
    "scheme": "dark",
}


def _vars(theme):
    return ("".join(f"--{k}:{v};" for k, v in theme.items() if k != "scheme")
            + f"color-scheme:{theme['scheme']};")


STICKER = "4px 4px 0 var(--shadow)"  # тень «наклейки» — только у главных блоков, см. DESIGN.md

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rubik:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {{ {_vars(LIGHT)} --green:{GREEN}; --amber:{AMBER}; --lime:{LIME}; }}

html, body, [class*="css"], .stApp {{ font-family:'IBM Plex Sans', system-ui, sans-serif; }}
.stApp {{ background:var(--bg); color:var(--ink); transition:background .2s ease; }}
[data-testid="stHeader"] {{ background:var(--bg); }}
[data-testid="stHeader"] *, [data-testid="stExpandSidebarButton"] * {{ color:var(--ink); }}
[data-testid="stMain"] p, [data-testid="stMain"] li, [data-testid="stMain"] label,
[data-testid="stMain"] [data-testid="stWidgetLabel"] * {{ color:var(--ink); }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {{ color:var(--muted) !important; }}
hr {{ border-color:var(--line) !important; }}
h1, h2, h3, h4, h5 {{ font-family:'Rubik', system-ui, sans-serif; letter-spacing:-.02em; color:var(--ink); }}
h1 {{ font-size:2.3rem; font-weight:700; }}
h2 {{ font-size:1.7rem; font-weight:700; padding-top:.6rem; }}
/* Подзаголовки разделов (## и ### из st.markdown) — с маленькой «крышкой бака» слева */
[data-testid="stHeadingWithActionElements"] h2, [data-testid="stHeadingWithActionElements"] h3 {{
    display:flex; align-items:center; gap:12px; }}
[data-testid="stHeadingWithActionElements"] h2::before, [data-testid="stHeadingWithActionElements"] h3::before {{
    content:""; flex:none; width:22px; height:10px; border-radius:4px 4px 2px 2px;
    background:var(--green); box-shadow:0 3px 0 var(--edge); }}
[data-testid="stHeadingWithActionElements"] h3::before {{ width:18px; height:8px; }}
.ww-score [data-testid="stHeadingWithActionElements"] h3::before, .ww-card [data-testid="stHeadingWithActionElements"] h3::before,
.ww-tag [data-testid="stHeadingWithActionElements"] h2::before {{ content:none; }}
.ww-score h3::before, .ww-card h3::before, .ww-tag h2::before {{ content:none !important; }}

/* ---------- Боковое меню ---------- */
section[data-testid="stSidebar"] {{ background:var(--sidebar); border-right:none; }}
section[data-testid="stSidebar"] * {{ color:#C9DCD2; }}
section[data-testid="stSidebar"] h3 {{ color:{PAPER}; font-size:1.4rem; }}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {{ color:#8FA79B !important; }}
/* Пункты меню — крупные строки без кружков; активный подсвечен лаймом, как наклейка */
section[data-testid="stSidebar"] [role="radiogroup"] {{ gap:4px; }}
section[data-testid="stSidebar"] [role="radiogroup"] label {{
    padding:.55rem .85rem; border-radius:12px; width:100%; max-width:none; margin:0; border:2px solid transparent;
    box-sizing:border-box; transition:background .12s ease; }}
section[data-testid="stSidebar"] [role="radiogroup"] label > div > div:not([data-testid="stMarkdownContainer"]) {{
    display:none; }}
section[data-testid="stSidebar"] [role="radiogroup"] label p {{ font-size:1rem; font-weight:500; }}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background:#1B3D2D; }}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
    background:var(--lime); border-color:var(--lime); box-shadow:3px 3px 0 #000; }}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color:{INK}; font-weight:600; }}
section[data-testid="stSidebar"] .stButton button {{
    background:transparent; border:1px solid #2C5443; color:#C9DCD2; width:100%; box-shadow:none; }}
/* Переключатель языка RUS / QAZ в меню: пилюли, выбранная — лайм, как активный пункт меню */
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button {{
    border-radius:999px; border:1px solid #2C5443; background:transparent; color:#C9DCD2;
    font-weight:600; padding:.2rem .9rem; min-height:0; }}
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button p {{ color:inherit !important; }}
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button:hover {{ background:#1B3D2D; color:#fff; }}
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button[data-selected="true"] {{
    background:var(--lime); border-color:var(--lime); color:{INK}; box-shadow:2px 2px 0 #000; }}
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button[data-selected="true"] * {{ color:{INK} !important; }}
section[data-testid="stSidebar"] [data-testid="stAlert"] {{ background:#1B3D2D; border:none; box-shadow:none; }}
section[data-testid="stSidebar"] [data-testid="stAlert"] * {{ color:var(--lime) !important; font-weight:600; }}
.ww-logo {{ background:{SURFACE}; border-radius:16px; padding:10px; display:inline-block;
    box-shadow:4px 4px 0 #000; }}
.ww-logo img {{ display:block; border-radius:8px; width:150px; }}

/* ---------- Кнопки ---------- */
.stButton button, .stFormSubmitButton button, .stDownloadButton button {{
    border-radius:999px; font-weight:600; padding:.55rem 1.5rem; border:2px solid var(--edge);
    background:var(--surface); color:var(--ink); box-shadow:3px 3px 0 var(--shadow);
    transition:transform .08s ease, box-shadow .08s ease; }}
.stButton button p, .stFormSubmitButton button p {{ color:inherit !important; }}
.stButton button:hover, .stFormSubmitButton button:hover, .stDownloadButton button:hover {{
    transform:translate(-1px, -1px); box-shadow:4px 4px 0 var(--shadow); border-color:var(--edge); color:var(--ink); }}
.stButton button:active, .stFormSubmitButton button:active {{
    transform:translate(3px, 3px); box-shadow:0 0 0 var(--shadow); }}
.stButton button[kind^="primary"], .stFormSubmitButton button[kind^="primary"] {{
    background:var(--green); border-color:var(--edge); color:#fff; }}
.stButton button[kind^="primary"]:hover, .stFormSubmitButton button[kind^="primary"]:hover {{ color:#fff; }}
.stButton button:disabled {{ opacity:.55; box-shadow:none; transform:none; }}
.stButton button:focus-visible, .stFormSubmitButton button:focus-visible {{
    outline:3px solid #8FD5AE; outline-offset:2px; }}

/* ---------- Вкладки — переключатель-«таблетка» ---------- */
[data-testid="stTabs"] [role="tablist"] {{ gap:6px; background:var(--surface); border:2px solid var(--edge);
    border-radius:999px; padding:4px; width:fit-content; max-width:100%; box-shadow:3px 3px 0 var(--shadow);
    margin-bottom:12px; }}
[data-testid="stTab"] {{ border-radius:999px; padding:6px 18px; height:auto; background:transparent; }}
[data-testid="stTab"] p {{ font-weight:600; color:var(--muted) !important; }}
[data-testid="stTab"][aria-selected="true"] {{ background:var(--green); }}
[data-testid="stTab"][aria-selected="true"] p {{ color:#fff !important; }}
[data-testid="stTabs"] .react-aria-SelectionIndicator {{ display:none; }}
[data-testid="stTabs"] [role="tablist"]::after, [data-testid="stTabs"] [role="tablist"]::before {{ display:none; }}

/* ---------- Поля ввода и выпадающие списки ---------- */
[data-testid="stTextInputRootElement"], [data-testid="stSelectbox"] [role="group"], [data-testid="stTextArea"] textarea {{
    background:var(--surface) !important; border:2px solid var(--edge) !important; border-radius:12px !important; }}
[data-testid="stTextInputField"], [data-testid="stSelectbox"] input, [data-testid="stTextArea"] textarea {{
    color:var(--ink) !important; -webkit-text-fill-color:var(--ink); background:transparent !important; }}
[data-testid="stTextInputField"]::placeholder {{ color:var(--muted) !important; -webkit-text-fill-color:var(--muted); }}
[data-testid="stTextInputRootElement"]:focus-within, [data-testid="stSelectbox"] [role="group"]:focus-within {{
    border-color:var(--green) !important; box-shadow:3px 3px 0 var(--green); }}
[data-testid="stTextInputRootElement"] button, [data-testid="stSelectbox"] button {{ background:transparent !important;
    color:var(--muted) !important; }}
[role="listbox"] {{ background:var(--surface) !important; border:2px solid var(--edge); border-radius:12px; }}
[role="listbox"] [role="option"], [role="listbox"] [role="option"] * {{ color:var(--ink) !important; }}
[role="listbox"] [role="option"]:hover, [role="listbox"] [role="option"][data-focused],
[role="listbox"] [role="option"][aria-selected="true"] {{ background:var(--mint) !important; }}

/* Переключатели (тема, камера) */
[data-testid="stCheckbox"] label > div:first-of-type {{ background:var(--track) !important; border:2px solid var(--edge); }}
[data-testid="stCheckbox"] label:has(input:checked) > div:first-of-type {{ background:var(--green) !important; }}
[data-testid="stCheckbox"] label > div:first-of-type > div {{ background:#fff !important; }}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label > div:first-of-type {{
    background:#2C5443 !important; border-color:#2C5443; }}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:checked) > div:first-of-type {{
    background:var(--lime) !important; border-color:var(--lime); }}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:checked) > div:first-of-type > div {{
    background:{INK} !important; }}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] {{ margin:10px 0 4px; }}

/* Загрузка фото: большая зона с пунктиром — сразу видно, куда тянуть файл */
[data-testid="stFileUploaderDropzone"] {{
    background:var(--surface); border:2px dashed var(--edge); border-radius:18px; padding:32px 26px;
    box-shadow:{STICKER}; }}
[data-testid="stFileUploaderDropzone"]:hover {{ background:var(--mint); }}
[data-testid="stFileUploaderDropzone"] * {{ color:var(--ink); }}
[data-testid="stFileUploaderDropzone"] button {{ border:2px solid var(--edge); background:var(--bg);
    border-radius:999px; color:var(--ink); }}
[data-testid="stFileUploaderFile"] * {{ color:var(--ink); }}

/* Варианты ответов (викторина) — крупные строки, на которые удобно нажимать с телефона */
[data-testid="stMain"] [role="radiogroup"] {{ gap:8px; }}
[data-testid="stMain"] [role="radiogroup"] label {{
    background:var(--surface); border:2px solid var(--edge); border-radius:12px; padding:10px 14px;
    margin:0; width:100%; transition:transform .08s ease, box-shadow .08s ease; }}
[data-testid="stMain"] [role="radiogroup"][aria-orientation="vertical"] > label {{
    width:100%; max-width:680px; box-sizing:border-box; }}
[data-testid="stMain"] [role="radiogroup"][aria-orientation="horizontal"] > label {{ width:auto; }}
[data-testid="stMain"] [data-testid="stRadio"] [data-testid="stWidgetLabel"] p {{
    font-family:'Rubik', sans-serif; font-size:1.15rem; font-weight:600; line-height:1.35; margin-bottom:6px; }}
[data-testid="stMain"] [role="radiogroup"] label:hover {{ transform:translate(-1px, -1px);
    box-shadow:3px 3px 0 var(--shadow); }}
[data-testid="stMain"] [role="radiogroup"] label:has(input:checked) {{
    background:var(--lime); border-color:{INK}; box-shadow:3px 3px 0 var(--shadow); }}
[data-testid="stMain"] [role="radiogroup"] label:has(input:checked) * {{ color:{INK} !important; font-weight:600; }}
[data-testid="stMain"] [role="radiogroup"] label:has(input:disabled) {{ transform:none; box-shadow:none; }}

/* Рамки (st.container(border=True)), формы, раскрывашки — «наклейки» */
/* Только контейнеры с key="wwbox_…" (в app.py) — у обычного st.container() рамки нет, а в CSS их не отличить */
[data-testid="stMain"] [class*="st-key-wwbox"] {{ padding:18px 20px;
    border:2px solid var(--edge) !important; border-radius:18px; background:var(--surface);
    box-shadow:{STICKER}; }}
[data-testid="stForm"] {{ background:var(--surface); border:2px solid var(--edge); border-top:12px solid var(--green);
    border-radius:18px; padding:22px 22px 20px; box-shadow:{STICKER}; }}
[data-testid="stExpander"] details {{ border:2px solid var(--edge) !important; border-radius:14px;
    background:var(--surface); box-shadow:3px 3px 0 var(--shadow); }}
[data-testid="stExpander"] summary * {{ color:var(--ink); font-weight:600; }}
[data-testid="stExpander"] summary:hover * {{ color:var(--green); }}

/* Сообщения Streamlit — плашки с толстой полосой слева по смыслу */
[data-testid="stAlert"] {{ border-radius:14px; border:2px solid var(--edge); border-left-width:8px;
    background:var(--surface); }}
[data-testid="stAlert"] > div {{ background:transparent !important; }}
[data-testid="stAlert"] * {{ color:var(--ink) !important; }}
[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) {{ border-left-color:#1565C0; background:var(--surface); }}
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) {{ border-left-color:var(--amber); background:var(--warm); }}
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) {{ border-left-color:#C62828; background:var(--rose); }}
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) {{ border-left-color:var(--green); background:var(--mint); }}

/* Полоса прогресса — толстая, как столбики */
[data-testid="stProgress"] [role="progressbar"] > div {{ height:14px; border-radius:7px; background:var(--track);
    border:2px solid var(--edge); }}
[data-testid="stProgress"] [role="progressbar"] > div > div {{ border-radius:5px; }}
[data-testid="stProgress"] [role="progressbar"] > div > div > div {{ background:var(--green); border-radius:5px; }}

/* Всплывашки и подсказки */
[data-testid="stToast"] {{ background:var(--surface); border:2px solid var(--edge); box-shadow:{STICKER}; }}
[data-testid="stToast"] * {{ color:var(--ink); }}
[data-testid="stSpinner"] * {{ color:var(--ink); }}

/* ---------- Метрики ---------- */
/* Числа на главной — тёмная плитка с лаймовым числом, как табло на станции */
[data-testid="stMetric"] {{
    background:var(--panel); border:2px solid var(--edge); border-radius:18px; padding:20px 24px;
    box-shadow:4px 4px 0 var(--green); }}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * {{
    font-family:'Rubik', sans-serif; font-weight:700; color:var(--lime) !important; font-size:2.6rem; }}
[data-testid="stMetricLabel"] p {{ color:#C9DCD2 !important; font-size:.95rem; }}

/* ---------- Главная ---------- */
.ww-hero {{
    position:relative; border-radius:24px; overflow:hidden; background:var(--panel);
    border:2px solid var(--edge); box-shadow:6px 6px 0 var(--green);
    display:grid; grid-template-columns:minmax(0, 1.15fr) minmax(0, .85fr); margin:8px 0 38px; }}
.ww-hero-text {{ padding:56px 48px 40px; display:flex; flex-direction:column; gap:16px; }}
.ww-hero h1 {{ color:#fff; font-size:clamp(2rem, 4vw, 3.5rem); line-height:1.14; letter-spacing:-.03em;
    margin:0; padding:0; max-width:14ch; }}
.ww-hero h1 mark {{ background:var(--lime); color:{INK}; padding:0 .16em; border-radius:10px; line-height:1;
    box-decoration-break:clone; -webkit-box-decoration-break:clone; }}
.ww-hero p {{ color:#D9E8DF !important; font-size:clamp(1rem, 1.3vw, 1.15rem); margin:0; max-width:44ch; line-height:1.55; }}
.ww-hero .ww-eyebrow {{ align-self:flex-start; color:{INK} !important; background:#8FD5AE; font-weight:600; font-size:.85rem;
    border-radius:999px; padding:5px 14px; margin:0; }}
.ww-hero-art {{ background-size:cover; background-position:center; min-height:320px;
    border-left:2px solid var(--edge); }}
/* Ряд баков внизу героя: крышка, корпус цвета бака и подпись — фирменный приём крупно */
.ww-bins {{ grid-column:1 / -1; display:grid; grid-template-columns:repeat(7, 1fr); gap:10px;
    padding:22px 28px 26px; background:rgba(0,0,0,.28); border-top:2px solid #000; }}
.ww-bin {{ display:flex; flex-direction:column; align-items:center; gap:7px; min-width:0; }}
.ww-bin i {{ display:block; width:100%; height:9px; border-radius:6px 6px 2px 2px; background:var(--c);
    filter:brightness(1.25); }}
.ww-bin b {{ display:flex; align-items:center; justify-content:center; width:86%; height:46px;
    margin-top:-4px; background:var(--c); border-radius:4px 4px 10px 10px; font-size:1.4rem; font-weight:400;
    box-shadow:inset 0 -6px 0 rgba(0,0,0,.18); }}
.ww-bin span {{ color:#C9DCD2; font-size:.8rem; text-align:center; overflow-wrap:anywhere; line-height:1.2; }}

.ww-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:20px;
    margin-bottom:26px; }}
.ww-card {{ position:relative; background:var(--surface); border:2px solid var(--edge); border-top:12px solid var(--c, {GREEN});
    border-radius:18px; padding:24px 24px 26px; display:flex; flex-direction:column; gap:10px;
    box-shadow:{STICKER}; }}
.ww-card h3 {{ margin:0; font-size:1.3rem; }}
.ww-card p {{ margin:0; color:var(--muted) !important; font-size:.98rem; line-height:1.5; }}
.ww-num {{ font-family:'Rubik', sans-serif; font-size:1rem; font-weight:700; color:#fff; line-height:1;
    background:var(--c, {GREEN}); align-self:flex-start; border-radius:999px; padding:7px 12px; }}

.ww-quote {{ position:relative; background:var(--warm); border:2px solid var(--edge); border-radius:18px;
    padding:26px 30px 26px 84px; color:var(--ink); font-size:1.12rem; line-height:1.6; box-shadow:4px 4px 0 var(--amber); }}
.ww-quote::before {{ content:"“"; position:absolute; left:24px; top:6px; font-family:'Rubik', sans-serif;
    font-size:5rem; font-weight:700; color:var(--amber); line-height:1; }}

.ww-chip {{ display:inline-block; background:var(--mint); color:var(--green); font-weight:600;
    border-radius:999px; padding:4px 14px; font-size:.85rem; }}

.ww-foot {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
.ww-foot a {{ display:inline-flex; align-items:center; gap:7px; text-decoration:none;
    color:var(--green); font-weight:600; font-size:.9rem; border:2px solid var(--green);
    border-radius:999px; padding:5px 14px; }}
section[data-testid="stSidebar"] .ww-foot a {{ color:#8FD5AE; border-color:#2C5443; }}

/* ---------- Заголовок внутренних страниц: тёмная плашка, как герой главной, и «крышки» баков ---------- */
.ww-head {{ background:var(--panel); border:2px solid var(--edge); border-radius:22px; padding:30px 32px 0;
    box-shadow:5px 5px 0 var(--green); margin:8px 0 22px; overflow:hidden; }}
.ww-head h1 {{ color:#fff; font-size:clamp(1.9rem, 3.6vw, 2.9rem); line-height:1.06; letter-spacing:-.03em;
    margin:0; padding:0; }}
.ww-head p {{ color:#D9E8DF !important; font-size:1.05rem; margin:10px 0 0; max-width:60ch; line-height:1.5; }}
.ww-head:not(:has(.ww-stripe)) {{ padding-bottom:28px; }}
.ww-stripe {{ display:flex; gap:8px; margin:22px 0 0; max-width:420px; }}
.ww-stripe span {{ flex:1; height:16px; border-radius:6px 6px 0 0; }}

/* Типы отходов: цветные «крышки» */
.ww-types {{ display:flex; flex-wrap:wrap; gap:8px; margin:6px 0 10px; }}
.ww-type {{ display:inline-flex; align-items:center; gap:6px; background:var(--surface); color:var(--ink);
    border:2px solid var(--edge); border-top:7px solid var(--c); border-radius:10px;
    padding:6px 12px 7px; font-size:.9rem; font-weight:500; }}
.ww-type.off {{ border-top-color:var(--line); color:var(--off); border-style:dashed; border-top-style:solid; }}
.ww-type.off small {{ font-size:.75rem; }}

/* ---------- Ответ модели: бирка цвета бака ---------- */
.ww-tag {{ position:relative; background:var(--c); color:#fff; border-radius:20px; border:2px solid var(--edge);
    padding:24px 26px 22px 54px; margin-bottom:16px; box-shadow:{STICKER}; }}
.ww-tag::before {{ content:""; position:absolute; left:20px; top:30px; width:16px; height:16px;
    border-radius:50%; background:var(--bg); box-shadow:inset 0 0 0 3px rgba(0,0,0,.18); }}
.ww-tag h2 {{ color:#fff; margin:0; padding:0; font-size:clamp(1.6rem, 2.6vw, 2.2rem); line-height:1.1; }}
.ww-tag .ww-tag-emoji {{ font-size:1.6rem; margin-right:6px; }}
.ww-meter {{ height:10px; background:rgba(255,255,255,.28); border-radius:5px; margin:16px 0 8px;
    overflow:hidden; }}
.ww-meter div {{ height:100%; background:#fff; border-radius:5px; }}
.ww-tag p {{ margin:0; color:rgba(255,255,255,.92) !important; font-size:.95rem; }}

.ww-block {{ background:var(--surface); border:2px solid var(--edge); border-radius:16px; padding:16px 20px;
    margin-bottom:12px; }}
.ww-block-title {{ font-family:'Rubik', sans-serif; font-weight:600; font-size:1rem; margin:0 0 6px; color:var(--ink); }}
.ww-block p {{ margin:0; color:var(--ink); line-height:1.55; }}
.ww-block.warn {{ border-left:8px solid var(--amber); background:var(--warm); }}
.ww-block.fact {{ background:var(--mint); border-style:dashed; }}
/* Плашка QR-режима «Школа · Бак»: левая граница цвета бака (DESIGN.md: акцент — граница, а не заливка) */
.ww-block.bin {{ border-left:10px solid var(--c, var(--green)); background:var(--mint); }}
.ww-block.fact p {{ color:var(--muted) !important; }}
.ww-steps {{ list-style:none; counter-reset:s; margin:4px 0 0; padding:0; }}
.ww-steps li {{ counter-increment:s; position:relative; padding:4px 0 4px 34px; line-height:1.5; }}
.ww-steps li::before {{ content:counter(s); position:absolute; left:0; top:4px; width:23px; height:23px;
    border-radius:50%; background:var(--c, {GREEN}); color:#fff; font-size:.8rem; font-weight:600;
    display:flex; align-items:center; justify-content:center; }}

/* ---------- Столбики (варианты модели, рейтинг, профиль) ---------- */
.ww-bars {{ display:flex; flex-direction:column; gap:10px; margin-bottom:22px; }}
.ww-bar-top {{ display:flex; justify-content:space-between; gap:12px; font-size:.95rem; margin-bottom:4px; }}
.ww-bar-top b {{ font-weight:600; }}
.ww-bar-top span {{ color:var(--muted); white-space:nowrap; }}
.ww-bar-track {{ height:12px; background:var(--track); border-radius:6px; overflow:hidden; }}
.ww-bar-track div {{ height:100%; border-radius:6px; }}

/* ---------- Таблица (история в профиле) ---------- */
.ww-table {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
.ww-table th {{ text-align:left; color:var(--muted); font-weight:600; padding:8px 10px;
    border-bottom:2px solid var(--edge); }}
.ww-table td {{ padding:8px 10px; border-bottom:1px solid var(--line); color:var(--ink); }}
.ww-table tr:last-child td {{ border-bottom:none; }}

/* ---------- Рейтинг ---------- */
.ww-rules {{ display:flex; flex-wrap:wrap; gap:10px; margin:4px 0 14px; }}
.ww-rule {{ background:var(--surface); border:2px solid var(--edge); border-radius:12px; padding:8px 14px;
    font-size:.92rem; color:var(--ink); }}
.ww-rule b {{ font-family:'Rubik', sans-serif; color:var(--green); font-size:1.05rem; margin-right:4px; }}

.ww-podium {{ display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; align-items:end;
    margin:10px 0 18px; }}
.ww-step {{ background:var(--surface); border:2px solid var(--edge); border-radius:18px 18px 10px 10px; box-shadow:{STICKER};
    padding:16px 12px; text-align:center; display:flex; flex-direction:column; gap:4px;
    justify-content:flex-end; min-width:0; }}
.ww-step.p1 {{ min-height:210px; border-top:10px solid #E3B33B; }}
.ww-step.p2 {{ min-height:175px; border-top:10px solid #AEB7BF; }}
.ww-step.p3 {{ min-height:150px; border-top:10px solid #C98A55; }}
.ww-step .medal {{ font-size:2rem; line-height:1; }}
.ww-step .ww-you {{ display:inline-block; margin:4px 0 0; }}
.ww-step b {{ font-family:'Rubik', sans-serif; font-size:1.05rem; overflow-wrap:anywhere; }}
.ww-step small {{ color:var(--muted); overflow-wrap:anywhere; }}
.ww-step .pts {{ font-family:'Rubik', sans-serif; font-weight:700; color:var(--green); font-size:1.5rem; }}
.ww-step.me, .ww-row.me {{ background:var(--mint); border-color:var(--green); }}

.ww-rows {{ display:flex; flex-direction:column; gap:8px; }}
.ww-row {{ display:grid; grid-template-columns:42px 1fr auto; align-items:center; gap:12px;
    background:var(--surface); border:2px solid var(--edge); border-radius:14px; padding:10px 16px; }}
.ww-row .pos {{ font-family:'Rubik', sans-serif; font-weight:700; color:var(--muted); text-align:center; }}
.ww-row .who {{ min-width:0; }}
.ww-row .who b {{ display:block; overflow-wrap:anywhere; }}
.ww-row .who small {{ color:var(--muted); overflow-wrap:anywhere; }}
.ww-row .pts {{ font-family:'Rubik', sans-serif; font-weight:700; color:var(--green); }}
.ww-you {{ font-size:.75rem; font-weight:600; color:{INK}; background:var(--lime); border-radius:999px;
    padding:1px 8px; margin-left:6px; vertical-align:middle; }}

/* ---------- Викторина ---------- */
.ww-qnum {{ display:inline-block; font-family:'Rubik', sans-serif; font-weight:700; color:#fff; font-size:.85rem;
    background:var(--c, {GREEN}); border-radius:999px; padding:4px 12px; margin-bottom:6px; }}
.ww-score {{ background:var(--panel); color:#fff; border:2px solid var(--edge); border-radius:20px; padding:26px 28px;
    margin:6px 0 16px; box-shadow:6px 6px 0 var(--green);
    display:flex; align-items:center; gap:22px; flex-wrap:wrap; }}
.ww-score .big {{ font-family:'Rubik', sans-serif; font-size:3.4rem; font-weight:700; line-height:1; color:var(--lime); }}
.ww-score h3 {{ color:#fff; margin:0 0 4px; font-size:1.3rem; }}
.ww-score p {{ margin:0; color:#C9DCD2 !important; }}
.ww-review {{ background:var(--surface); border:2px solid var(--edge); border-left:8px solid var(--c);
    border-radius:12px; padding:12px 16px; margin-bottom:8px; line-height:1.5; color:var(--ink); }}
.ww-review small {{ color:var(--muted); display:block; margin-top:3px; }}

/* ---------- Профиль ---------- */
.ww-me {{ display:flex; align-items:center; gap:18px; flex-wrap:wrap; background:var(--panel);
    border:2px solid var(--edge); border-radius:22px; padding:24px 28px; box-shadow:5px 5px 0 var(--green);
    margin:8px 0 18px; }}
.ww-avatar {{ width:72px; height:72px; border-radius:50%; background:var(--lime); color:{INK}; border:2px solid #000;
    box-shadow:3px 3px 0 #000;
    font-family:'Rubik', sans-serif; font-size:2rem; font-weight:600; display:flex;
    align-items:center; justify-content:center; flex:none; }}
.ww-me h1 {{ margin:0; padding:0; font-size:clamp(1.8rem, 3.4vw, 2.6rem); line-height:1.1; color:#fff; }}
.ww-me p {{ margin:4px 0 0; color:#C9DCD2 !important; }}
.ww-level {{ background:var(--surface); border:2px solid var(--edge); border-radius:18px; padding:18px 22px; box-shadow:{STICKER};
    margin:10px 0 16px; }}
.ww-level-top {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; flex-wrap:wrap; }}
.ww-level-top b {{ font-family:'Rubik', sans-serif; font-size:1.25rem; }}
.ww-level-top span {{ color:var(--muted); font-size:.92rem; }}
.ww-level .ww-bar-track {{ margin-top:10px; height:14px; border-radius:7px; }}
.ww-level .ww-bar-track div {{ background:var(--green); }}
.ww-stats {{ display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; margin:0 0 22px; }}
.ww-stat {{ background:var(--surface); border:2px solid var(--edge); border-radius:16px; padding:14px 18px; min-width:0;
    box-shadow:3px 3px 0 var(--shadow); }}
.ww-stat b {{ display:block; font-family:'Rubik', sans-serif; font-weight:700; color:var(--green);
    font-size:clamp(1.4rem, 3vw, 2rem); line-height:1.1; }}
.ww-stat span {{ color:var(--muted); font-size:.88rem; }}
.ww-history {{ display:flex; flex-direction:column; gap:8px; margin-bottom:12px; }}
.ww-hist {{ display:grid; grid-template-columns:auto 1fr auto; gap:12px; align-items:center;
    background:var(--surface); border:2px solid var(--edge); border-left:8px solid var(--c); border-radius:12px;
    padding:10px 14px; color:var(--ink); }}
.ww-hist .em {{ font-size:1.4rem; }}
.ww-hist b {{ display:block; }}
.ww-hist small {{ color:var(--muted); }}
.ww-hist .when {{ color:var(--muted); font-size:.85rem; text-align:right; white-space:nowrap; }}

.ww-empty {{ background:var(--surface); border:2px dashed var(--edge); border-radius:16px; padding:24px;
    color:var(--muted); }}
.ww-empty b {{ color:var(--ink); }}

@media (max-width: 640px) {{
    .ww-hero {{ grid-template-columns:1fr; box-shadow:4px 4px 0 var(--green); }}
    .ww-hero-text {{ padding:30px 22px 22px; }}
    .ww-hero-art {{ min-height:190px; border-left:none; border-top:2px solid var(--edge); }}
    .ww-bins {{ grid-template-columns:repeat(4, 1fr); gap:12px 8px; padding:18px 16px 20px; }}
    .ww-bin b {{ height:38px; font-size:1.15rem; }}
    .ww-head {{ padding:22px 20px 0; box-shadow:4px 4px 0 var(--green); }}
    .ww-head:not(:has(.ww-stripe)) {{ padding-bottom:20px; }}
    .ww-me {{ padding:18px 18px; }}
    .ww-quote {{ padding:22px 20px 20px 62px; font-size:1.02rem; }}
    .ww-quote::before {{ left:14px; font-size:4rem; }}
    .ww-podium {{ gap:6px; }}
    .ww-step {{ padding:12px 6px; }}
    .ww-step.p1 {{ min-height:180px; }} .ww-step.p2 {{ min-height:150px; }} .ww-step.p3 {{ min-height:130px; }}
    .ww-tag {{ padding:20px 20px 18px 46px; }}
    .ww-tag::before {{ left:16px; top:26px; width:14px; height:14px; }}
    .ww-hist {{ grid-template-columns:auto 1fr; }}
    .ww-hist .when {{ grid-column:2; text-align:left; }}
}}
</style>
"""


def esc(value):
    """Текст для вставки в HTML: < > & и кавычки превращаются в безопасные символы."""
    return html.escape("" if value is None else str(value))


def inject():
    """Подключить оформление. Вызывается один раз в начале app.py."""
    st.markdown(CSS, unsafe_allow_html=True)


def theme(dark):
    """Тёмная тема: подменить значения цветовых переменных. Вызывается после переключателя в меню."""
    if dark:
        st.markdown(f"<style>:root {{ {_vars(DARK)} }}</style>", unsafe_allow_html=True)


def _html(markup):
    st.markdown(markup, unsafe_allow_html=True)


# ---------- Главная ----------

def hero(image_b64, eyebrow, title, subtitle, bins=()):
    """Крупный блок вверху главной: текст на тёмном, картинка справа и ряд баков снизу.
    В title можно выделить слово тегом <mark> — оно подсветится лаймом. bins — (emoji, подпись, цвет)."""
    row = "".join(f'<div class="ww-bin" style="--c:{c}"><i></i><b>{e}</b><span>{esc(n)}</span></div>'
                  for e, n, c in bins)
    _html(
        f'<div class="ww-hero"><div class="ww-hero-text"><p class="ww-eyebrow">{eyebrow}</p>'
        f"<h1>{title}</h1><p>{subtitle}</p></div>"
        f'<div class="ww-hero-art" role="img" aria-label="{esc(_("Люди сортируют мусор по бакам"))}" '
        f"style=\"background-image:url('data:image/jpeg;base64,{image_b64}')\"></div>"
        + (f'<div class="ww-bins">{row}</div>' if row else "") + "</div>"
    )


def cards(items, colors=()):
    """Ряд карточек. items — список (номер, заголовок, текст); colors — цвета «крышек» по порядку."""
    markup = "".join(
        f'<div class="ww-card" style="--c:{colors[i % len(colors)] if colors else GREEN}">'
        f'<div class="ww-num">{num}</div><h3>{title}</h3><p>{text}</p></div>'
        for i, (num, title, text) in enumerate(items)
    )
    _html(f'<div class="ww-grid">{markup}</div>')


def quote(text):
    _html(f'<div class="ww-quote">{text}</div>')


# ---------- Общие блоки внутренних страниц ----------

def page_header(title, subtitle="", colors=()):
    """Название страницы и полоса из цветов баков под ним."""
    stripe = "".join(f'<span style="background:{c}"></span>' for c in colors)
    _html(f'<div class="ww-head"><h1>{esc(title)}</h1>'
          + (f"<p>{subtitle}</p>" if subtitle else "")
          + (f'<div class="ww-stripe">{stripe}</div>' if stripe else "") + "</div>")


def waste_types(items):
    """Типы отходов «крышками» своего цвета. items — (emoji, название, цвет, знает ли модель)."""
    chips = "".join(
        f'<span class="ww-type" style="--c:{color}">{emoji} {esc(name)}</span>' if known else
        f'<span class="ww-type off">{emoji} {esc(name)} <small>— {esc(_("скоро"))}</small></span>'
        for emoji, name, color, known in items
    )
    _html(f'<div class="ww-types">{chips}</div>')


def bars(rows, max_value=None):
    """Горизонтальные столбики. rows — (подпись, значение для длины, текст справа, цвет)."""
    if not rows:
        return
    top = max_value or max(value for _, value, _, _ in rows) or 1
    markup = "".join(
        f'<div><div class="ww-bar-top"><b>{label}</b><span>{esc(note)}</span></div>'
        f'<div class="ww-bar-track"><div style="width:{max(2, min(100, value / top * 100)):.1f}%;'
        f'background:{color}"></div></div></div>'
        for label, value, note, color in rows
    )
    _html(f'<div class="ww-bars">{markup}</div>')


def table(columns, rows):
    """Простая таблица в стиле сайта (st.dataframe рисуется на canvas и не меняет цвета с темой)."""
    head = "".join(f"<th>{esc(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in rows)
    _html(f'<table class="ww-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


def empty(title, text):
    """Пустое состояние: что здесь появится и что для этого сделать."""
    _html(f'<div class="ww-empty"><b>{title}</b><br>{text}</div>')


# ---------- Распознавание ----------

def result_tag(emoji, name, color, prob):
    """Ответ модели — бирка цвета бака: тип отхода крупно и уверенность модели."""
    _html(
        f'<div class="ww-tag" style="--c:{color}">'
        f'<h2><span class="ww-tag-emoji">{emoji}</span>{esc(name)}</h2>'
        f'<div class="ww-meter"><div style="width:{prob * 100:.0f}%"></div></div>'
        f"<p>{esc(_('Модель уверена на {p}').format(p=f'{prob:.0%}'))}</p></div>"
    )


def block(title, body, kind=""):
    """Карточка с подзаголовком: «Куда нести», «Не принимают», факт."""
    _html(f'<div class="ww-block {kind}"><div class="ww-block-title">{title}</div><p>{body}</p></div>')


def bin_banner(title, body, color):
    """Плашка с левой границей цвета бака — например, «Школа · Бак» в QR-режиме."""
    _html(f'<div class="ww-block bin" style="--c:{color}"><div class="ww-block-title">{title}</div><p>{body}</p></div>')


def steps(title, items, color):
    """Нумерованные шаги «Как подготовить» — в цвет бака."""
    lis = "".join(f"<li>{esc(t)}</li>" for t in items)
    _html(f'<div class="ww-block" style="--c:{color}"><div class="ww-block-title">{title}</div>'
          f'<ol class="ww-steps">{lis}</ol></div>')


# ---------- Рейтинг ----------

def rules(items):
    """Как зарабатывать баллы. items — (баллы, за что)."""
    _html('<div class="ww-rules">' + "".join(
        f'<span class="ww-rule"><b>+{pts}</b>{esc(text)}</span>' for pts, text in items) + "</div>")


def _you(is_me):
    return f'<span class="ww-you">{esc(_("это вы"))}</span>' if is_me else ""


def podium(rows, me_id=None):
    """Тройка лидеров на пьедестале. rows — до трёх (имя, школа, баллы, id), по убыванию баллов."""
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    places = [(2, rows[1]) if len(rows) > 1 else None, (1, rows[0]), (3, rows[2]) if len(rows) > 2 else None]
    cells = []
    for place in places:
        if place is None:
            cells.append("<div></div>")
            continue
        pos, (name, school, points, uid) = place
        me = " me" if uid == me_id else ""
        cells.append(
            f'<div class="ww-step p{pos}{me}"><span class="medal">{medals[pos]}</span>'
            f"<b>{esc(name)}{_you(uid == me_id)}</b><small>{esc(school) or '&nbsp;'}</small>"
            f'<span class="pts">{points}</span></div>'
        )
    _html(f'<div class="ww-podium">{"".join(cells)}</div>')


def ranking(rows, start=4, me_id=None):
    """Остальные места списком. rows — (имя, школа, баллы, id)."""
    markup = "".join(
        f'<div class="ww-row{" me" if uid == me_id else ""}"><span class="pos">{pos}</span>'
        f'<div class="who"><b>{esc(name)}{_you(uid == me_id)}</b><small>{esc(school)}</small></div>'
        f'<span class="pts">{points}</span></div>'
        for pos, (name, school, points, uid) in enumerate(rows, start=start)
    )
    _html(f'<div class="ww-rows">{markup}</div>')


# ---------- Викторина ----------

def question_number(i, total, color=GREEN):
    """Номер вопроса — бейдж; цвет меняется от вопроса к вопросу (цвета баков)."""
    _html(f'<div class="ww-qnum" style="--c:{color}">{esc(_("Вопрос {i} из {total}").format(i=i, total=total))}</div>')


def score(correct, total, title, text):
    """Итог викторины крупно."""
    _html(f'<div class="ww-score"><div class="big">{correct}/{total}</div>'
          f"<div><h3>{title}</h3><p>{text}</p></div></div>")


def review(question, ok, right, why):
    """Разбор одного вопроса: зелёная полоса — верно, оранжевая — ошибка."""
    color = GREEN if ok else AMBER
    mark = "✅" if ok else "❌"
    _html(f'<div class="ww-review" style="--c:{color}">{mark} <b>{esc(question)}</b>'
          f"<small>{esc(_('Правильно'))}: {esc(right)}. {esc(why)}</small></div>")


# ---------- Профиль ----------

def profile_header(name, details):
    initial = esc((name or "?").strip()[:1].upper() or "?")
    _html(f'<div class="ww-me"><div class="ww-avatar">{initial}</div>'
          f"<div><h1>{esc(name)}</h1><p>{esc(details)}</p></div></div>")


def level(emoji, title, points, next_title=None, next_at=None, start_at=0):
    """Уровень игрока и сколько осталось до следующего."""
    if next_at:
        share = (points - start_at) / max(1, next_at - start_at) * 100
        note = esc(_("до уровня «{title}» — {n}").format(title=next_title, n=next_at - points))
    else:
        share, note = 100, esc(_("максимальный уровень"))
    _html(f'<div class="ww-level"><div class="ww-level-top"><b>{emoji} {esc(title)}</b>'
          f"<span>{esc(_('{n} баллов').format(n=points))} · {note}</span></div>"
          f'<div class="ww-bar-track"><div style="width:{max(3, min(100, share)):.0f}%"></div></div></div>')


def stats(items):
    """Три числа в ряд — и на телефоне тоже в ряд. items — (значение, подпись)."""
    _html('<div class="ww-stats">' + "".join(
        f'<div class="ww-stat"><b>{esc(value)}</b><span>{esc(label)}</span></div>' for value, label in items) + "</div>")


def history(items):
    """Последние распознавания. items — (emoji, название, цвет, подпись, когда)."""
    markup = "".join(
        f'<div class="ww-hist" style="--c:{color}"><span class="em">{emoji}</span>'
        f"<div><b>{esc(name)}</b><small>{esc(note)}</small></div>"
        f'<span class="when">{esc(when)}</span></div>'
        for emoji, name, color, note, when in items
    )
    _html(f'<div class="ww-history">{markup}</div>')


MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_KK = ["қаң", "ақп", "нау", "сәу", "мам", "мау", "шіл", "там", "қыр", "қаз", "қар", "жел"]
LOCAL_OFFSET = timedelta(hours=5)  # база хранит время в UTC, а сайт — для Казахстана (UTC+5)


def nice_date(value):
    """«2026-10-05 11:31:31» (UTC) → «5 окт, 16:31» по времени Казахстана."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if not isinstance(value, datetime):
        return str(value or "")
    value = value.replace(tzinfo=None) + LOCAL_OFFSET
    months = MONTHS_KK if current_lang() == "kk" else MONTHS
    return f"{value.day} {months[value.month - 1]}, {value:%H:%M}"
