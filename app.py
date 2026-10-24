"""WasteWise — веб-приложение для сортировки отходов с помощью компьютерного зрения.

Запуск:  streamlit run app.py
"""
import base64
import logging
import os
import hashlib
import importlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from dotenv import load_dotenv

from core import db
from core.content import (CITY_CENTER, GUEST_SCAN_NUDGE, LOW_CONFIDENCE, POINT_KINDS, POINTS_PER_CORRECT_ANSWER,
                          POINTS_PER_FEEDBACK, POINTS_PER_SCAN, QUIZ_REWARDS_PER_DAY, WASTE_INFO, HAZARD_MAYBE,
                          HAZARD_SURE, canonical, hazard_hint, level_for)
from core.model import DETECTOR_PATH, check_scene, classify, load_image, load_model
from core.pg import connection_hint
from core.quiz import random_questions
from core import assistant, i18n, qr as qrcodes, report, storage, ui
from core.i18n import _

# Streamlit Cloud после обновления кода перезапускает app.py, но модули из core/ держит в памяти старыми —
# новый CSS не появлялся, а новые функции падали с «has no attribute». ui.py — только оформление
# без состояния, поэтому его безопасно перечитывать при каждом запуске (это быстро).
ui = importlib.reload(ui)

ROOT = Path(__file__).resolve().parent

# Свой логгер: Streamlit настраивает только собственный, и без этого строки уровня INFO в логах не видны.
log = logging.getLogger("wastewise")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s wastewise: %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
ASSETS = ROOT / "assets"
FEEDBACK_DIR = ROOT / "data" / "feedback"

# ---------- Настройки и секреты ----------
load_dotenv(ROOT / ".env")
try:  # на Streamlit Cloud ключ OpenAI для ИИ-помощника хранится в «Secrets», а не в файле .env
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        if key in st.secrets and not os.getenv(key):
            os.environ[key] = str(st.secrets[key])
except Exception:
    pass


def setting(key):
    """Настройка из .env / переменной окружения (локально) или из st.secrets (Streamlit Cloud)."""
    if os.getenv(key):
        return os.getenv(key)
    try:
        return st.secrets.get(key)
    except Exception:  # файла secrets.toml нет — локально это нормально
        return None


st.set_page_config(page_title="WasteWise — сортировка отходов", page_icon="♻️", layout="wide")

# ---------- Язык и QR-код бака: до любых текстов на странице ----------
# Язык: переключатель RUS / QAZ (lang_pick) → ссылка ?lang=kk → русский. Хранится в session_state["lang"],
# откуда его берут _() и core/ui.py — у каждого посетителя свой (core/i18n.py).
st.session_state.lang = i18n.pick(st.session_state.get("lang_pick") or st.query_params.get("lang"))
lang = st.session_state.lang
# QR-код на школьном баке: ?school_id=nis_astana&box=plastic (core/qr.py). Неверные значения игнорируются.
qr = qrcodes.parse(st.query_params)

ui.inject()


@st.cache_resource  # модель и база загружаются один раз, а не при каждом клике
def get_model():
    return load_model()


@st.cache_resource
def get_detector():
    return load_model(DETECTOR_PATH)


# Streamlit перезапускает весь скрипт при КАЖДОМ клике (выбор в списке, кнопка и т.п.).
# Без кэша обе нейросети заново обрабатывали то же самое фото. Теперь результат
# запоминается по file_key (md5 файла). Аргумент _image с подчёркиванием Streamlit
# не хеширует — ключом служит только file_key.
@st.cache_data(max_entries=300, show_spinner=False)
def cached_check_scene(file_key: str, _image):
    return check_scene(get_detector(), _image)


@st.cache_data(max_entries=300, show_spinner=False)
def cached_classify(file_key: str, _image):
    return classify(get_model(), _image)


@st.cache_resource
def get_db():
    # DATABASE_URL (Streamlit Cloud → Settings → Secrets) → Supabase: аккаунты и баллы переживают
    # перезапуск сайта. Без него — локальный файл data/app.db, как раньше. Инструкция: docs/SUPABASE.md
    url = setting("DATABASE_URL")
    conn = db.get_conn(url)
    db.init_db(conn)
    # Один раз при запуске: какая база на самом деле используется. Без пароля и адреса — логи видят не только вы.
    log.info("База данных: %s", db.describe(conn))
    if not url and (misplaced := misplaced_database_url()):
        log.warning("В Secrets есть строка postgresql://… под именем «%s», а сайт ищет DATABASE_URL "
                    "на верхнем уровне (не внутри раздела [...]). Переименуйте ключ.", misplaced)
    return conn


def misplaced_database_url():
    """Частая ошибка: строка подключения лежит в Secrets под другим именем или внутри раздела [...].

    Возвращает имя ключа (например, «connections.supabase.url») — но не саму строку с паролем.
    """
    try:
        found = list(_postgres_keys(st.secrets.to_dict()))
    except Exception:
        return None
    return found[0] if found else None


def _postgres_keys(secrets, prefix=""):
    for key, value in secrets.items():
        if isinstance(value, dict):
            yield from _postgres_keys(value, f"{prefix}{key}.")
        elif isinstance(value, str) and value.strip().startswith(("postgres://", "postgresql://")):
            yield f"{prefix}{key}"


@st.cache_resource
def get_feedback_store():
    """Куда сохранять фото «Модель ошиблась» — это наш датасет для дообучения (core/storage.py).

    SUPABASE_URL + SUPABASE_SERVICE_KEY (Secrets) → приватный бакет Supabase Storage: фото не пропадают
    при перезапуске сайта. Без них — папка data/feedback, как раньше. Инструкция: docs/SUPABASE.md
    """
    url, key = setting("SUPABASE_URL"), setting("SUPABASE_SERVICE_KEY")
    if not (url and key):
        log.info("Фото «Модель ошиблась»: папка data/feedback (на Streamlit Cloud стирается; "
                 "задайте SUPABASE_URL и SUPABASE_SERVICE_KEY)")
        return storage.LocalFeedbackStore(FEEDBACK_DIR)
    log.info("Фото «Модель ошиблась»: Supabase Storage, приватный бакет %s", storage.BUCKET)
    store = storage.SupabaseFeedbackStore(url, key)
    try:
        if store.bucket_is_public():
            log.warning("Бакет feedback публичный — сделайте его приватным (docs/SUPABASE.md)")
    except Exception:
        pass  # проверка необязательная: бакета может ещё не быть — сайт создаст его приватным при первом фото
    return store


try:
    conn = get_db()
except Exception:  # база недоступна: Supabase на паузе, неверный пароль, нет сети
    log.exception("Не удалось подключиться к базе данных")  # подробности — в логах
    st.error(_("Не удалось подключиться к базе данных. Попробуйте обновить страницу через минуту."))
    hint = connection_hint(setting("DATABASE_URL") or "")
    if hint:  # подсказка без секретов: пароль и адрес не показываются
        st.caption(hint)
    st.stop()


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def rus(cls):
    """Название типа отходов на языке сайта (имя осталось с тех времён, когда язык был один)."""
    return i18n.waste_name(cls) if canonical(cls) in WASTE_INFO else cls


def info_for(cls):
    """Описание типа отходов (куда нести, советы…) на языке сайта; {} — для неизвестного класса."""
    return i18n.waste(cls) if canonical(cls) in WASTE_INFO else {}


def emoji(cls):
    return WASTE_INFO.get(canonical(cls), {}).get("emoji", "")


def color(cls):
    return WASTE_INFO.get(canonical(cls), {}).get("color", ui.GREEN)


BIN_COLORS = [info["color"] for info in WASTE_INFO.values()]  # полоса под заголовками страниц


def model_classes():
    """Какие типы знает загруженная модель: старая — 4, новая — 7 (порядок — как в WASTE_INFO)."""
    known = {canonical(name) for name in get_model().names.values()}
    return [c for c in WASTE_INFO if c in known] + sorted(known - set(WASTE_INFO))


def plural(n, one, few, many):
    """1 тип, 2 типа, 5 типов. По-казахски после числа слово не меняется: 1 түр, 5 түр."""
    if lang == "kk":
        return _(one)
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


AUTHOR = "Адильжан Кадыргажы"
TELEGRAM = "https://t.me/crybaby_c"
INSTAGRAM = "https://www.instagram.com/_kadyrgazhy_a"
GITHUB = "https://github.com/adekaa11/wastewise"  # исходный код проекта

_TG_ICON = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">'
            '<path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12'
            'c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81'
            'c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/></svg>')
_IG_ICON = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2"><rect x="2.5" y="2.5" width="19" height="19" rx="5"/>'
            '<circle cx="12" cy="12" r="4"/>'
            '<circle cx="17.3" cy="6.7" r="1.1" fill="currentColor" stroke="none"/></svg>')

_GH_ICON = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5C5.65.5.5 5.65.5 12'
            'c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.56v-1.97c-3.2.7-3.87-1.37-3.87-1.37-.52-1.33-1.28-1.69'
            '-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73'
            '-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18'
            'a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42'
            '-2.69 5.39-5.26 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35'
            '.5 12 .5z"/></svg>')


def social_links(align="flex-start"):
    """Иконки Telegram и Instagram как HTML-ссылки."""
    return (f'<div class="ww-foot" style="justify-content:{align}">'
            f'<a href="{TELEGRAM}" target="_blank">{_TG_ICON}Telegram</a>'
            f'<a href="{INSTAGRAM}" target="_blank">{_IG_ICON}Instagram</a>'
            f'<a href="{GITHUB}" target="_blank">{_GH_ICON}GitHub</a>'
            f'</div>')


# ---------- Состояние сессии ----------
for k, v in {"user_id": None, "quiz": None, "quiz_answers": {}, "quiz_done": False, "seen_scans": {},
             "guest_id": uuid.uuid4().hex, "guest_scans": 0}.items():
    st.session_state.setdefault(k, v)

user = db.get_user(conn, st.session_state.user_id) if st.session_state.user_id else None
access = db.user_access(conn, user["id"]) if user else None
role = access["role"] if access else None  # student / teacher / admin — назначается только core/roles.py
is_staff = role in ("teacher", "admin")

# ---------- Боковое меню ----------
with st.sidebar:
    st.markdown(f'<div class="ww-logo"><img src="data:image/jpeg;base64,'
                f'{b64(ASSETS / "Logo_waste_seg.jpg")}" alt="WasteWise"></div>',
                unsafe_allow_html=True)
    st.markdown("### ♻️ WasteWise")
    # Язык — переключатель-«таблетка»; выбор запоминается в ссылке (?lang=kk), как и тема
    st.segmented_control("Язык / Тіл", list(i18n.LANGS), format_func=i18n.LANGS.get, default=lang,
                         key="lang_pick", label_visibility="collapsed")
    st.query_params["lang"] = lang
    if user:
        points_slot = st.empty()  # заполняется в конце скрипта, чтобы баллы были свежими
        pages = ["Главная", "Распознать отходы", "Спросить ИИ", "Викторина", "Рейтинг", "Эко-карта"]
        pages += ["Панель учителя"] if is_staff else []
        pages += ["Профиль"]
    else:
        pages = ["Главная", "Распознать отходы", "Спросить ИИ", "Викторина", "Рейтинг", "Эко-карта",
                 "Вход", "Регистрация"]
    # Открытая страница хранится сама по себе (session_state.page): при смене языка или входе в аккаунт
    # меню перерисовывается с новыми подписями, а страница остаётся та же. По QR-коду бака сайт
    # сразу открывает «Распознать отходы».
    current = st.session_state.get("page")
    if current not in pages:
        current = "Распознать отходы" if qr else pages[0]
    labels = {_(p): p for p in pages}  # подпись на языке сайта → страница (внутри — всегда русское имя)
    choice = st.radio("Навигация", list(labels), index=pages.index(current), label_visibility="collapsed",
                      key=f"nav:{lang}:{len(pages)}")
    page = st.session_state.page = labels[choice]
    # Тема запоминается в ссылке (?theme=dark): переживает обновление страницы и открывается так же по ссылке
    if "dark" not in st.session_state:
        st.session_state.dark = st.query_params.get("theme") == "dark"
    dark = st.toggle(_("🌙 Тёмная тема"), key="dark")
    st.query_params["theme"] = "dark" if dark else "light"
    if user and st.button(_("Выйти")):
        st.session_state.user_id = None
        st.session_state.pop("ai_answer", None)  # ответ ИИ — личный, следующему не показываем
        st.rerun()
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.caption(_(AUTHOR))
    st.markdown(social_links(), unsafe_allow_html=True)


ui.theme(dark)

if st.session_state.pop("welcome", False) and user:
    st.toast(_("Добро пожаловать, {name}! Аккаунт создан, вы вошли.").format(name=user["name"]), icon="🎉")


def show_points():
    """Баллы в меню. Вызывается в самом конце скрипта (после всех начислений) и перед st.stop():
    st.stop() обрывает скрипт, и раньше строка с баллами в меню из-за этого пропадала."""
    if user:
        fresh = db.get_user(conn, user["id"])
        points_slot.success(_("👤 {name} · ⭐ {points} баллов").format(name=fresh["name"], points=fresh["points"]))


def qr_banner():
    """Плашка «Школа · Бак» — когда страницу открыли по QR-коду со школьного бака."""
    if not qr:
        return
    parts = []
    if qr.school_id:
        parts.append(_("Школа: {school}").format(school=ui.esc(qr.school_id)))
    if qr.bin:
        parts.append(_("Бак: {bin}").format(bin=f"{emoji(qr.bin)} {ui.esc(rus(qr.bin))}"))
    hint = (_("Сфотографируй предмет — проверим, подходит ли он для этого бака.") if qr.bin else
            _("Сфотографируй предмет — подскажем, в какой бак его нести."))
    ui.bin_banner("🏫 " + " · ".join(parts), ui.esc(hint), color(qr.bin) if qr.bin else ui.GREEN)


# =====================================================================
# ГЛАВНАЯ
# =====================================================================
if page == "Главная":
    ui.hero(
        b64(ASSETS / "123.jpg"),
        _("♻️ Сортировка отходов с помощью ИИ"),
        _("Сфотографируй мусор — узнай, <mark>куда</mark> его выбросить"),
        _("Нейросеть определяет тип отхода, а приложение подсказывает, куда его нести, "
          "как подготовить и что туда не принимают."),
        # короткая подпись бака: «Бумага и картон» → «Бумага», «Прочее (несортируемое)» → «Прочее»
        [(i["emoji"], rus(c).split()[0], i["color"]) for c, i in WASTE_INFO.items()],
    )

    ui.cards([
        (_("Шаг 1"), _("Сфотографируй"), _("Загрузи готовое фото или сними предмет камерой телефона прямо в браузере.")),
        (_("Шаг 2"), _("ИИ распознаёт"), _("Модель определит тип отхода и покажет, насколько она уверена.")),
        (_("Шаг 3"), _("Сортируй правильно"), _("Куда нести, как подготовить и что туда точно не примут.")),
    ], colors=[WASTE_INFO["plastic"]["color"], WASTE_INFO["glass"]["color"], WASTE_INFO["ewaste"]["color"]])

    st.markdown("## " + _("WasteWise в цифрах"))
    stats = db.global_stats(conn)
    m1, m2, m3 = st.columns(3)
    m1.metric(_("Распознано фото"), stats["scans"])
    m2.metric(_("Участников"), stats["users"])
    m3.metric(_("Исправлений от пользователей"), stats["corrected"])

    st.markdown("## " + _("Почему это важно"))
    ui.quote(_(
        "По данным Всемирного банка, объём твёрдых бытовых отходов в мире к 2050 году может вырасти "
        "на 70% по сравнению с 2016 годом. Главный барьер переработки — неправильная сортировка: "
        "одна грязная или «чужая» вещь может испортить целую партию вторсырья."
    ))

    st.divider()
    st.markdown("**" + _("Автор проекта: {author}, г. Астана.").format(author=_(AUTHOR)) + "**")
    st.markdown(social_links(), unsafe_allow_html=True)

# =====================================================================
# РАСПОЗНАВАНИЕ
# =====================================================================
elif page == "Распознать отходы":
    known = model_classes()  # тексты подстраиваются под модель: старая знает 4 типа, новая — 7
    ui.page_header(_("Распознать отходы"), _("Сфотографируй предмет — нейросеть подскажет, в какой бак его нести "
                   "и как подготовить."), BIN_COLORS)
    qr_banner()
    count = f"{len(known)} {plural(len(known), 'тип', 'типа', 'типов')}"
    st.caption(_("Модель знает {count}").format(count=count)
               + (_(" из {total}: серые ещё учатся. ").format(total=len(WASTE_INFO)) if len(known) < len(WASTE_INFO)
                  else _(" отходов. "))
               + _("Лучше всего работает, если на фото один предмет крупным планом."))
    ui.waste_types([(i["emoji"], rus(c), i["color"], c in known) for c, i in WASTE_INFO.items()])

    tab_upload, tab_camera = st.tabs([_("Загрузить фото"), _("Снять камерой")])
    with tab_upload:
        uploaded = st.file_uploader(_("Выберите изображение"), type=["jpg", "jpeg", "png", "webp"])
    with tab_camera:
        shot = st.camera_input(_("Сделайте снимок")) if st.toggle(_("Включить камеру")) else None
    file = shot or uploaded

    raw = file.getvalue() if file is not None else None
    image = load_image(raw) if raw else None
    if raw and image is None:  # раньше битый файл ронял страницу с длинной ошибкой Python
        st.error(_("Не удалось открыть файл как изображение. Попробуйте другое фото (JPG, PNG или WEBP)."))

    if image is None:
        st.session_state.shown_scan = None  # фото убрали — следующее открытие уже «возврат»
    else:
        file_key = hashlib.md5(raw).hexdigest()

        with st.spinner(_("Нейросеть анализирует фото…")):
            problem = cached_check_scene(file_key, image)
        if problem and st.session_state.get("force_key") != file_key:
            c_img, c_msg = st.columns([1, 1.3], gap="large")
            c_img.image(image, width="stretch")
            with c_msg:
                st.warning(f"🤔 {i18n.scene(problem)}")
                st.caption(_("Модель обучена только на отходах. На других фото она всё равно выберет "
                             "один из {count}, поэтому сначала мы проверяем, что в кадре.").format(count=count))
                if st.button(_("Это точно отход — распознать")):
                    st.session_state.force_key = file_key
                    st.rerun()
            show_points()
            st.stop()

        with st.spinner(_("Нейросеть анализирует фото…")):
            ranked = cached_classify(file_key, image)
        best_cls, best_p = ranked[0]
        info = info_for(best_cls)
        best_color = color(best_cls)

        # Одно и то же фото не даёт баллы повторно.
        # Раньше помнилось только ПОСЛЕДНЕЕ фото сессии: чередуя два снимка (А→Б→А→Б…),
        # можно было бесконечно получать баллы за распознавание и за «исправление».
        # Теперь: (1) в сессии помним все проверенные фото, (2) у вошедшего пользователя
        # дополнительно смотрим в базу — так не помогает и выход/вход в аккаунт.
        scan_key = f"{user['id'] if user else 0}:{file_key}"
        seen = st.session_state.seen_scans
        if scan_key not in seen:
            prev = db.find_scan(conn, user["id"], file_key) if user else None
            if prev:
                seen[scan_key] = {"id": prev[0], "fixed": prev[1] is not None, "repeat": True}
            else:
                # QR-режим: фото запоминается с кодом школы и бака — для отчёта учителя (core/report.py)
                scan_id = db.save_scan(conn, user["id"] if user else None, best_cls, best_p, file_key,
                                       school_id=qr.school_id, bin=qr.bin,
                                       class_label=(access["class_label"] or None) if access else None)
                seen[scan_key] = {"id": scan_id, "fixed": False, "repeat": False}
                if user:
                    db.add_points(conn, user["id"], POINTS_PER_SCAN)
                    st.toast(_("+{n} баллов!").format(n=POINTS_PER_SCAN), icon="⭐")
                else:
                    st.session_state.guest_scans += 1
        elif st.session_state.get("shown_scan") != scan_key:
            seen[scan_key]["repeat"] = True  # вернулись к фото, которое уже проверяли (А→Б→А)
        st.session_state.shown_scan = scan_key  # клики на том же фото повтором не считаются
        scan = seen[scan_key]

        col_img, col_res = st.columns([1, 1.3], gap="large")
        with col_img:
            st.image(image, width="stretch")
            others = [(c, p) for c, p in ranked[1:] if p >= 0.01]  # что ещё предполагала модель
            if others:
                st.markdown("##### " + _("Другие варианты модели"))
                ui.bars([(f"{emoji(c)} {ui.esc(rus(c))}", p, f"{p:.0%}", color(c)) for c, p in others], max_value=1)
        with col_res:
            if scan["repeat"] and user:
                st.caption(_("Это фото вы уже проверяли — баллы за него были начислены раньше."))
            if best_p < LOW_CONFIDENCE:
                unknown = [rus(c).lower() for c in WASTE_INFO if c not in known]
                st.warning(
                    _("Модель не уверена ({p}). Возможно, это **{a}** или **{b}**. Если предмет из смешанного "
                      "материала, ответ может быть неточным.").format(p=f"{best_p:.0%}", a=rus(best_cls),
                                                                       b=rus(ranked[1][0]))
                    + (_(" А если это {types} — такие типы модель ещё не знает.").format(types=", ".join(unknown))
                       if unknown else "")
                )
            ui.result_tag(emoji(best_cls), rus(best_cls), best_color, best_p)
            # QR-режим: тот ли это бак? Ученик стоит у конкретного бака — ответ должен быть прямым.
            at_bin = qrcodes.verdict(qr.bin, best_cls)
            if at_bin == "ok":
                st.success(_("✅ Верно! Этот предмет — для бака «{bin}». Можно выбрасывать.").format(bin=rus(qr.bin)))
            elif at_bin == "wrong":
                st.error(_("⛔ Не в этот бак! Это «{cls}», а бак — «{bin}». Найди бак «{cls}».").format(
                    cls=rus(best_cls), bin=rus(qr.bin)))
            hazard = hazard_hint(ranked)  # батарейки и электроника — только в спецпункты
            if hazard == "sure":
                st.warning(_(HAZARD_SURE))
            elif hazard == "maybe":
                st.info(_(HAZARD_MAYBE))
            if best_p < LOW_CONFIDENCE:
                st.caption(_("Советы ниже — для варианта «{cls}».").format(cls=rus(best_cls)))
            ui.block(_("📍 Куда нести"), ui.esc(info.get("where", "")))
            ui.steps(_("Как подготовить"), info.get("tips", []), best_color)
            ui.block(_("🚫 Не принимают"), ui.esc(info.get("not_accepted", "")), "warn")
            ui.block(_("💡 Интересный факт"), ui.esc(info.get("fact", "")), "fact")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        with st.container(border=True, key="wwbox_feedback"):
            st.markdown("#### " + _("Модель ошиблась?"))
            st.caption(_("Выберите правильный тип — фото попадёт в набор, на котором модель учится дальше")
                       + (_(", а вам +{n} баллов.").format(n=POINTS_PER_FEEDBACK) if user else "."))
            fc1, fc2 = st.columns([2, 1], vertical_alignment="bottom")
            options = list(WASTE_INFO)  # все 7 типов, даже если модель пока знает меньше: так и собираем датасет
            labels = {c: rus(c) for c in options}
            correct = fc1.selectbox(_("Правильный тип"), options, format_func=lambda c: labels[c])
            if fc2.button(_("Отправить исправление"), disabled=scan["fixed"]):
                try:  # фото + метка пользователя → наш датасет (Supabase Storage или data/feedback)
                    path = get_feedback_store().save(correct, file_key, storage.encode_photo(image))
                except storage.StorageError:
                    log.exception("Не удалось сохранить фото для дообучения")
                    st.error(_("Не удалось сохранить фото. Попробуйте ещё раз через минуту."))
                else:  # баллы и отметка «исправлено» — только если фото действительно сохранилось
                    db.correct_scan(conn, scan["id"], correct, path)
                    scan["fixed"] = True  # одно исправление (и одни баллы за него) на фото
                    if user:
                        db.add_points(conn, user["id"], POINTS_PER_FEEDBACK)
                    st.success(_("Спасибо! Фото сохранено как «{cls}».").format(cls=labels[correct])
                               + (_(" +{n} баллов.").format(n=POINTS_PER_FEEDBACK) if user else ""))
        if not user:
            if st.session_state.guest_scans >= GUEST_SCAN_NUDGE:
                # Гость уже распознал несколько фото — самое время предложить аккаунт (а не запрещать фото:
                # по QR-кодам на баках дети фотографируют без входа, и это должно работать всегда).
                st.info(_("Вы проверили уже {n} фото без входа. Зарегистрируйтесь — за каждое фото +{p} баллов, "
                          "рейтинг класса и история в профиле.").format(n=st.session_state.guest_scans,
                                                                       p=POINTS_PER_SCAN))
            else:
                st.caption(_("Войдите, чтобы получать баллы и участвовать в рейтинге."))

# =====================================================================
# СПРОСИТЬ ИИ — текстовый помощник для предметов, которых нет среди 7 типов (core/assistant.py)
# =====================================================================
elif page == "Спросить ИИ":
    ui.page_header(_("Не знаешь, куда выбросить?"), _("Напиши, что за предмет, — ИИ подскажет, куда его нести "
                   "и как подготовить. Например: «блистер от таблеток», «старый градусник», «коробка от сока»."),
                   BIN_COLORS)
    if not assistant.available():
        st.info(_("ИИ-помощник сейчас выключен. Распознавание по фото и викторина работают как обычно."))
    else:
        # Гость может задать GUEST_PER_SESSION пробных вопросов — чтобы попробовать до регистрации
        who = user["id"] if user else assistant.GUEST_PREFIX + st.session_state.guest_id
        left = assistant.left_today(who)
        if user:
            st.caption(_("Осталось вопросов на сегодня: {left} из {total}. Баллы за вопросы не начисляются.").format(
                left=left, total=assistant.PER_USER_PER_DAY))
        elif left:
            st.caption(_("Пробный режим без входа: осталось вопросов — {left} из {total}. Войдите, чтобы задавать "
                         "до {daily} вопросов в сутки.").format(left=left, total=assistant.GUEST_PER_SESSION,
                                                               daily=assistant.PER_USER_PER_DAY))
        else:
            st.info(_("Пробные вопросы закончились. Войдите или зарегистрируйтесь — и задавайте до {daily} "
                      "вопросов в сутки.").format(daily=assistant.PER_USER_PER_DAY))
        with st.form("ask_ai", clear_on_submit=False):
            question = st.text_input(_("Что за предмет?"), max_chars=assistant.MAX_LEN,
                                     placeholder=_("например, крышка от йогурта"))
            asked = st.form_submit_button(_("Спросить"), type="primary", disabled=not user and not left)
        if asked:
            try:
                with st.spinner(_("ИИ думает…")):
                    st.session_state.ai_answer = assistant.ask(question, who, lang=lang)[0]
                    st.session_state.ai_question = question
                st.rerun()  # обновить «Осталось вопросов»
            except assistant.AssistantError as e:
                st.session_state.pop("ai_answer", None)
                st.warning(_(e.template).format(**e.params))

        ans = st.session_state.get("ai_answer")
        if ans:
            kind = ans["type"]
            info = info_for(kind) if kind in WASTE_INFO else None
            if kind == "off_topic":
                st.info(_("Я отвечаю только на вопросы о том, куда выбросить или сдать предмет. "
                          "Опишите предмет, например: «пустая банка из-под краски»."))
            else:
                if info:
                    title, icon, tone = info["name"], info.get("emoji", ""), info["color"]
                elif kind == "hazardous":
                    title, icon, tone = _("Опасные отходы"), "☣️", ui.AMBER
                else:
                    title, icon, tone = _("Не удалось определить"), "❔", "#616161"
                item = f" — {ans['item']}" if ans.get("item") else ""
                ui.block(f"{icon} {ui.esc(title)}{ui.esc(item)}", ui.esc(ans["answer"]))
                if kind == "hazardous" or (info and info.get("hazardous")):
                    st.warning(_("Опасные отходы — только в специальные пункты приёма, не в мусорный бак "
                                 "и не в канализацию. Ближайшие пункты — на странице «Эко-карта»."))
                if ans["steps"]:
                    ui.steps(_("Как подготовить"), ans["steps"], tone)
                if info:
                    ui.block(_("📍 Куда нести (правила WasteWise)"), ui.esc(info["where"]))
            st.caption(_("Ответ составил ИИ и может ошибаться. Сомневаетесь — уточните в пункте приёма."))

# =====================================================================
# ВИКТОРИНА
# =====================================================================
elif page == "Викторина":
    ui.page_header(_("Викторина по сортировке"), _("Пять вопросов о том, что и куда выбрасывать. "
                   "За каждый правильный ответ — +{n} баллов.").format(n=POINTS_PER_CORRECT_ANSWER), BIN_COLORS)
    if user:
        left = max(0, QUIZ_REWARDS_PER_DAY - db.rewarded_quizzes_last_day(conn, user["id"]))
        st.caption(_("Викторин с баллами осталось: {left} из {total} в сутки. "
                     "Без баллов можно тренироваться сколько угодно.").format(left=left, total=QUIZ_REWARDS_PER_DAY))
    else:
        st.caption(_("Войдите, чтобы получать баллы за правильные ответы."))
    if st.button(_("Начать новую викторину (5 вопросов)"), type="primary"):
        st.session_state.quiz = {"mode": "bank", "questions": random_questions(5), "uid": uuid.uuid4().hex}
        st.session_state.quiz_answers, st.session_state.quiz_done = {}, False

    quiz = st.session_state.quiz
    if quiz:
        questions = quiz["questions"]
        total = len(questions)
        if st.session_state.quiz_done:  # итог — сверху, чтобы не листать до конца
            score = st.session_state.get("quiz_score", 0)
            verdict = (_("Отлично — ты знаешь, как сортировать!") if score == total else
                       _("Хороший результат") if score >= total * 0.6 else _("Есть что подтянуть"))
            if not user:
                note = _("Войдите, чтобы получать баллы за правильные ответы.")
            else:
                earned = st.session_state.get("quiz_points", 0)
                note = (_("+{n} баллов в рейтинг.").format(n=earned) if earned else
                        _("Разберите ошибки ниже и попробуйте ещё раз.") if not score else
                        _("Баллы за сегодня уже получены."))
            ui.score(score, total, ui.esc(verdict), ui.esc(note))
            if user and not (st.session_state.get("quiz_points", 0) or not score):
                st.info(_("Баллы начисляются за первые {n} викторины в сутки — лимит исчерпан. "
                          "Результат сохранён в профиле, тренироваться можно дальше.").format(n=QUIZ_REWARDS_PER_DAY))
            st.markdown("#### " + _("Разбор ответов"))
            for i, q in enumerate(questions):
                ui.review(i18n.quiz_text(q["q"]), st.session_state.quiz_answers[i] == q["correct"],
                          i18n.quiz_text(q["correct"]), i18n.quiz_text(q.get("why", "")))
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        # Пока игра идёт — вопросы просто списком; после проверки они сворачиваются под разбором.
        # Ключи у вариантов ответа постоянные, поэтому ответы не теряются при переносе в «Ваши ответы».
        # Ответы хранятся по-русски (их и сравниваем с правильным), на экран выводится перевод.
        holder = st.expander(_("Ваши ответы")) if st.session_state.quiz_done else st.container()
        with holder:
            for i, q in enumerate(questions):
                with st.container(border=True, key=f"wwbox_q{i}"):
                    ui.question_number(i + 1, total, BIN_COLORS[i % len(BIN_COLORS)])
                    st.session_state.quiz_answers[i] = st.radio(
                        f"**{i18n.quiz_text(q['q'])}**", q["options"], index=None, key=f"q_{quiz['uid']}_{i}",
                        format_func=i18n.quiz_text, disabled=st.session_state.quiz_done,
                    )
        if not st.session_state.quiz_done:
            answered = sum(a is not None for a in st.session_state.quiz_answers.values())
            st.progress(answered / total, text=_("Отвечено {n} из {total}").format(n=answered, total=total))
            if st.button(_("Проверить ответы"), type="primary"):
                if None in st.session_state.quiz_answers.values():
                    st.warning(_("Ответьте на все вопросы."))
                else:
                    st.session_state.quiz_done = True
                    score = sum(st.session_state.quiz_answers[i] == q["correct"] for i, q in enumerate(questions))
                    st.session_state.quiz_score = score
                    if user:
                        # лимит: баллы только за первые QUIZ_REWARDS_PER_DAY викторин за 24 часа (см. content.py)
                        earned = score * POINTS_PER_CORRECT_ANSWER
                        if db.rewarded_quizzes_last_day(conn, user["id"]) >= QUIZ_REWARDS_PER_DAY:
                            earned = 0
                        db.save_quiz(conn, user["id"], score, total, quiz["mode"], earned)
                        db.add_points(conn, user["id"], earned)
                        st.session_state.quiz_points = earned
                    st.rerun()
    else:
        ui.empty(ui.esc(_("Здесь появятся вопросы")), ui.esc(_("Нажмите «Начать новую викторину» — пять случайных "
                 "вопросов из базы. Повторять можно сколько угодно.")))

# =====================================================================
# РЕЙТИНГ
# =====================================================================
elif page == "Рейтинг":
    ui.page_header(_("Рейтинг"), _("Кто сортирует больше всех — среди участников и школ."), BIN_COLORS)
    ui.rules([(POINTS_PER_SCAN, _("за распознанное фото")),
              (POINTS_PER_CORRECT_ANSWER, _("за правильный ответ в викторине ({n} в сутки)").format(
                  n=QUIZ_REWARDS_PER_DAY)),
              (POINTS_PER_FEEDBACK, _("за исправление ошибки модели"))])
    me_id = user["id"] if user else None
    t1, t2 = st.tabs([_("Участники"), _("Школы")])
    with t1:
        rows = db.leaderboard_users(conn, with_ids=True)
        if rows:
            ui.podium(rows[:3], me_id)
            if len(rows) > 3:
                ui.ranking(rows[3:], start=4, me_id=me_id)
            if user and all(r[3] != me_id for r in rows):
                place = db.user_place(conn, me_id)
                st.caption(_("Ваше место: {place}. Ещё немного — и вы в топ-{n}!").format(place=place, n=len(rows)))
        else:
            ui.empty(ui.esc(_("Пока никого нет")),
                     ui.esc(_("Зарегистрируйтесь и распознайте первое фото — и вы станете первым.")))
    with t2:
        rows = db.leaderboard_schools(conn)
        if rows:
            ui.bars([(ui.esc(school), pts, _("{pts} баллов · {n} {word}").format(
                pts=pts, n=people, word=plural(people, "участник", "участника", "участников")), ui.GREEN)
                for school, pts, people in rows])
        else:
            ui.empty(ui.esc(_("Школ пока нет")),
                     ui.esc(_("Укажите школу и класс при регистрации — и она появится в рейтинге.")))

    stats = db.global_stats(conn)
    if stats["by_class"]:
        st.markdown("## " + _("Что чаще всего распознают"))
        merged = {}  # старые метки («cardboard») складываются с новыми («paper»)
        for c, n in stats["by_class"]:
            merged[canonical(c)] = merged.get(canonical(c), 0) + n
        rows = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
        ui.bars([(f"{emoji(c)} {ui.esc(rus(c))}", n, f"{n} {plural(n, 'фото', 'фото', 'фото')}", color(c))
                 for c, n in rows])

# =====================================================================
# ЭКО-КАРТА — пункты приёма опасных и редких фракций (батарейки, электроника, ртутные лампы, вторсырьё)
# =====================================================================
elif page == "Эко-карта":
    ui.page_header(_("Эко-карта Астаны"), _("Куда сдать батарейки, электронику, ртутные лампы и вторсырьё. "
                   "Опасные отходы — только в специальные пункты, не в обычный бак."), BIN_COLORS)
    kinds = list(POINT_KINDS)
    chosen = st.pills(_("Что сдаёте?"), kinds, selection_mode="multi", default=kinds,
                      format_func=lambda k: f"{POINT_KINDS[k]['emoji']} {_(POINT_KINDS[k]['name'])}")
    points = [p for p in db.eco_points(conn) if p["kind"] in (chosen or [])]

    if points:
        import pydeck as pdk  # входит в Streamlit: отдельная зависимость не нужна

        def rgb(hex_color):
            return [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)] + [230]

        # Текст подсказки на карте — HTML: всё, что ввёл администратор, экранируется.
        data = [{"lat": p["lat"], "lon": p["lon"], "color": rgb(POINT_KINDS[p["kind"]]["color"]),
                 "name": ui.esc(p["name"]), "kind": ui.esc(_(POINT_KINDS[p["kind"]]["name"])),
                 "address": ui.esc(p["address"]), "hours": ui.esc(p["hours"])} for p in points]
        layer = pdk.Layer("ScatterplotLayer", data=data, get_position="[lon, lat]", get_fill_color="color",
                          get_radius=90, radius_min_pixels=7, radius_max_pixels=18, pickable=True,
                          stroked=True, get_line_color=[16, 42, 30], line_width_min_pixels=2)
        st.pydeck_chart(pdk.Deck(
            layers=[layer], map_style=pdk.map_styles.DARK if dark else pdk.map_styles.LIGHT,
            initial_view_state=pdk.ViewState(latitude=CITY_CENTER[0], longitude=CITY_CENTER[1], zoom=11),
            tooltip={"html": "<b>{name}</b><br/>{kind}<br/>{address}<br/>{hours}"}), width="stretch")
        ui.table([_("Пункт"), _("Что принимают"), _("Адрес"), _("Часы работы")],
                 [(p["name"], f"{POINT_KINDS[p['kind']]['emoji']} {_(POINT_KINDS[p['kind']]['name'])}",
                   p["address"], p["hours"]) for p in points])
    else:
        ui.empty(ui.esc(_("Пунктов на карте пока нет")),
                 ui.esc(_("Мы добавляем на карту только проверенные адреса. А пока найдите ближайший пункт "
                          "в 2ГИС по ссылкам ниже.")))

    st.markdown("### " + _("Найти рядом в 2ГИС"))
    st.markdown("  \n".join(
        f"{POINT_KINDS[k]['emoji']} [{_(POINT_KINDS[k]['name'])}]"
        f"(https://2gis.kz/astana/search/{quote(_(POINT_KINDS[k]['search']))})" for k in kinds))
    st.caption(_("Перед поездкой позвоните в пункт: часы работы и список принимаемого меняются."))

    if role == "admin":  # точки добавляет только администратор — так на карте нет случайных адресов
        with st.expander(_("Управление картой (администратор)")):
            with st.form("add_point", clear_on_submit=True):
                name = st.text_input(_("Название пункта"))
                kind = st.selectbox(_("Что принимают"), kinds, format_func=lambda k: _(POINT_KINDS[k]["name"]))
                address = st.text_input(_("Адрес"))
                hours = st.text_input(_("Часы работы"), placeholder="10:00–20:00")
                coords = st.text_input(_("Координаты: широта, долгота"), placeholder="51.128000, 71.430400",
                                       help=_("В 2ГИС или Google Картах нажмите на точку и скопируйте координаты."))
                if st.form_submit_button(_("Добавить на карту"), type="primary"):
                    lat, _sep, lon = coords.replace(";", ",").partition(",")
                    ok, msg = db.add_eco_point(conn, name, kind, address, hours, lat.strip() or None,
                                               lon.strip() or None, user["id"])
                    (st.success if ok else st.error)(_(msg))
                    if ok:
                        st.rerun()
            existing = db.eco_points(conn)
            if existing:
                victim = st.selectbox(_("Удалить пункт"), existing,
                                      format_func=lambda p: f"{p['name']} — {p['address']}")
                if st.button(_("Удалить с карты")):
                    db.delete_eco_point(conn, victim["id"])
                    st.rerun()

# =====================================================================
# ПАНЕЛЬ УЧИТЕЛЯ — отчёт по школе (QR-режим) и QR-коды для баков
# =====================================================================
elif page == "Панель учителя" and is_staff:
    ui.page_header(_("Панель учителя"), _("Как ваша школа сортирует у экобоксов: активность классов, частые "
                   "ошибки и динамика. Данные — из фото, сделанных по QR-кодам на баках."), BIN_COLORS)
    if role == "admin":  # администратор видит любую школу
        schools = sorted(set(db.school_ids(conn)) | ({access["school_id"]} if access["school_id"] else set()))
        typed = st.text_input(_("Код школы"), placeholder="nis_astana",
                              help=_("Латиница, цифры, _ и -. Такой же код стоит в QR-кодах на баках."))
        school = typed.strip().lower() if typed.strip() else (
            st.selectbox(_("Или выберите из школ с данными"), schools) if schools else None)
    else:
        school = access["school_id"]
    if school and not qrcodes.valid_school_id(school):
        st.error(_("Код школы: латиница, цифры, _ и -, от 2 до 40 символов (например nis_astana)."))
        school = None

    if not school:
        st.info(_("Учётной записи ещё не назначена школа. Администратор назначает её командой "
                  "python -m core.roles teacher <логин> <код_школы>."))
    else:
        tab_report, tab_codes = st.tabs([_("Отчёт"), _("QR-коды для баков")])
        with tab_report:
            days = st.selectbox(_("Период"), [7, 30, 90, 365], index=1,
                                format_func=lambda d: _("последние {n} дней").format(n=d))
            since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
            rows = db.school_scans(conn, school, since)
            if not rows:
                ui.empty(ui.esc(_("Данных пока нет")),
                         ui.esc(_("Распечатайте QR-коды на вкладке «QR-коды для баков» и наклейте на баки — "
                                  "фото учеников появятся здесь.")))
            else:
                s = report.summarize(rows)
                accuracy = f"{s['accuracy']:.0%}" if s["accuracy"] is not None else "—"
                named = [c for c, _n, _a in s["classes"] if c != report.NO_CLASS]
                ui.stats([(s["total"], _("фото у баков школы")), (accuracy, _("выброшено в верный бак")),
                          (len(named), _("классов участвуют"))])

                left_col, right_col = st.columns(2, gap="large")
                with left_col:
                    st.markdown("### " + _("Активность классов"))
                    ui.bars([(ui.esc(c if c != report.NO_CLASS else _("без класса / гости")), n,
                              _("{n} фото").format(n=n) + (_(" · верно {p}").format(p=f"{a:.0%}") if a is not None
                                                          else ""), ui.GREEN) for c, n, a in s["classes"]])
                with right_col:
                    st.markdown("### " + _("Частые ошибки у баков"))
                    if s["mistakes"]:
                        ui.bars([(f"{emoji(b)} {ui.esc(rus(b))} → {emoji(f)} {ui.esc(rus(f))}", n,
                                  _("{n} раз").format(n=n), color(b)) for (b, f), n in s["mistakes"][:8]])
                        st.caption(_("Слева — бак, у которого сфотографировали; справа — что это было на самом "
                                     "деле. Разберите самые частые ошибки на классном часе."))
                    elif s["at_bins"]:
                        st.success(_("Ошибок у баков нет — отлично!"))
                    else:
                        st.caption(_("В QR-кодах этих фото не указан бак, поэтому ошибки не считаются."))

                st.markdown("### " + _("Динамика сортировки"))
                import altair as alt
                import pandas as pd

                daily = pd.DataFrame([{"day": d.isoformat(), "photos": n,
                                       "accuracy": round(a * 100) if a is not None else None}
                                      for d, n, a in s["daily"]])
                chart = alt.Chart(daily).mark_bar(color=ui.GREEN, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                    x=alt.X("day:T", title=None),
                    y=alt.Y("photos:Q", title=_("Фото за день")),
                    tooltip=[alt.Tooltip("day:T", title=_("День")), alt.Tooltip("photos:Q", title=_("Фото")),
                             alt.Tooltip("accuracy:Q", title=_("Верно у баков, %"))])
                st.altair_chart(chart, width="stretch")

                st.markdown("### " + _("Что выбрасывают"))
                ui.bars([(f"{emoji(c)} {ui.esc(rus(c))}", n, _("{n} фото").format(n=n), color(c))
                         for c, n in s["types"]])

                st.download_button(
                    _("⬇️ Скачать отчёт для пилота (CSV)"), report.to_csv(rows, tr=_, name=rus),
                    file_name=f"wastewise_{school}_{datetime.now():%Y-%m-%d}.csv", mime="text/csv")

        with tab_codes:
            # Адрес сайта для ссылок в QR: APP_URL из Secrets, иначе — адрес, по которому открыт сайт.
            base = setting("APP_URL") or getattr(st.context, "url", "") or ""
            st.caption(_("Распечатайте и наклейте на баки. Ученик наводит камеру телефона — сайт открывается "
                         "сразу для вашей школы и этого бака, без входа в аккаунт."))
            if not base.startswith("http"):
                st.warning(_("Не удалось определить адрес сайта. Укажите APP_URL в Secrets, например "
                             "https://wastewise.streamlit.app"))
            else:
                qr_lang = st.selectbox(_("Язык сайта по QR-коду"), list(i18n.LANGS),
                                       index=list(i18n.LANGS).index(lang),
                                       format_func=lambda code: {"ru": "Русский", "kk": "Қазақша"}[code])
                cols = st.columns(4)
                for i, box in enumerate(WASTE_INFO):
                    url = qrcodes.link(base, school, box, qr_lang)
                    with cols[i % 4], st.container(border=True, key=f"wwbox_qr_{box}"):
                        st.markdown(f"**{emoji(box)} {rus(box)}**")
                        png = qrcodes.png(url)
                        st.image(png, width="stretch")
                        st.download_button(_("Скачать PNG"), png, file_name=f"qr_{school}_{box}.png",
                                           mime="image/png", key=f"dl_{box}")
                with st.expander(_("Все ссылки текстом")):
                    st.code("\n".join(f"{rus(b)}: {qrcodes.link(base, school, b, qr_lang)}" for b in WASTE_INFO),
                            language=None)

# =====================================================================
# ПРОФИЛЬ
# =====================================================================
elif page == "Профиль" and user:
    scans = db.user_scans(conn, user["id"])
    quizzes = db.user_quizzes(conn, user["id"])
    place = db.user_place(conn, user["id"])
    details = [user["school"] or _("Школа не указана")]
    if access["class_label"]:
        details.append(_("класс {c}").format(c=access["class_label"]))
    details.append(_("логин {login}").format(login=user["username"]))
    ui.profile_header(user["name"], " · ".join(details))
    (start_at, title, level_icon), following = level_for(user["points"])
    ui.level(level_icon, _(title), user["points"], following and _(following[1]), following and following[0],
             start_at)

    n_scans, n_quizzes = db.user_totals(conn, user["id"])  # всего, а не только последние 20
    ui.stats([(place or "—", _("место в рейтинге")),
              (n_scans, plural(n_scans, "распознавание", "распознавания", "распознаваний")),
              (n_quizzes, plural(n_quizzes, "викторина", "викторины", "викторин"))])

    left_col, right_col = st.columns([1.4, 1], gap="large")
    with left_col:
        st.markdown("### " + _("Последние распознавания"))
        if scans:
            ui.history([
                (emoji(f or p), rus(f or p), color(f or p),
                 _("вы исправили: модель думала «{cls}»").format(cls=rus(p)) if f else
                 _("модель уверена на {p}").format(p=f"{conf:.0%}"),
                 ui.nice_date(d))
                for p, conf, f, d in scans[:8]
            ])
            with st.expander(_("Вся история таблицей")):
                ui.table([_("Ответ модели"), _("Уверенность"), _("Исправлено на"), _("Когда")],
                         [(rus(p), f"{conf:.0%}", rus(f) if f else "", ui.nice_date(d)) for p, conf, f, d in scans])
        else:
            ui.empty(ui.esc(_("Пока пусто")), ui.esc(_("Откройте «Распознать отходы» и сфотографируйте первый "
                                                       "предмет — +{n} баллов.").format(n=POINTS_PER_SCAN)))
    with right_col:
        counts = {}
        for cls, n in db.user_class_counts(conn, user["id"]):
            counts[canonical(cls)] = counts.get(canonical(cls), 0) + n
        if counts:
            st.markdown("### " + _("Что вы сортировали"))
            ui.bars([(f"{emoji(cl)} {ui.esc(rus(cl))}", n, str(n), color(cl))
                     for cl, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)])
        st.markdown("### " + _("Викторины"))
        if quizzes:
            ui.history([("🧩", _("{s} из {t} правильно").format(s=s, t=t), ui.GREEN if s == t else ui.AMBER,
                         (_("ИИ-вопросы") if m == "ai" else _("готовые вопросы"))
                         + (_(" · +{n} баллов").format(n=pts) if pts else ""),
                         ui.nice_date(d)) for s, t, m, pts, d in quizzes[:6]])
        else:
            ui.empty(ui.esc(_("Ещё ни одной")),
                     ui.esc(_("Пройдите викторину — до +{n} баллов за раз.").format(n=5 * POINTS_PER_CORRECT_ANSWER)))

# =====================================================================
# ВХОД / РЕГИСТРАЦИЯ
# =====================================================================
elif page == "Вход":
    _l, mid, _r = st.columns([1, 2, 1])
    with mid:
        ui.page_header(_("Вход"), _("Баллы, рейтинг и история распознаваний — в вашем профиле."), BIN_COLORS)
        with st.form("login"):
            username = st.text_input(_("Логин"))
            password = st.text_input(_("Пароль"), type="password")
            if st.form_submit_button(_("Войти"), type="primary", width="stretch"):
                uid = db.authenticate(conn, username, password)
                if uid:
                    st.session_state.user_id = uid
                    st.rerun()
                else:
                    st.error(_("Неверный логин или пароль"))
        st.caption(_("Нет аккаунта? Откройте «Регистрация» в меню слева."))

elif page == "Регистрация":
    _l, mid, _r = st.columns([1, 2, 1])
    with mid:
        ui.page_header(_("Регистрация"), _("Получайте баллы за каждое фото и правильный ответ, соревнуйтесь "
                       "с одноклассниками."), BIN_COLORS)
        with st.form("register"):
            username = st.text_input(_("Логин"))
            password = st.text_input(_("Пароль (минимум 6 символов)"), type="password")
            name = st.text_input(_("Имя"))
            school = st.text_input(_("Школа и класс (необязательно), например «Гимназия №5, 10А»"))
            class_label = st.text_input(_("Класс для отчёта учителя (необязательно), например 7А"), max_chars=10)
            if st.form_submit_button(_("Зарегистрироваться"), type="primary", width="stretch"):
                if not (username and password and name):
                    st.error(_("Заполните логин, пароль и имя."))
                else:
                    ok, msg = db.register_user(conn, username, password, name, school, class_label)
                    if ok:  # сразу входим: второй раз вводить логин и пароль незачем
                        st.session_state.user_id = db.authenticate(conn, username, password)
                        st.session_state.welcome = True
                        st.rerun()
                    st.error(_(msg))

# ---------- Баллы в меню (в самом конце, после всех начислений) ----------
show_points()
