"""WasteWise — веб-приложение для сортировки отходов с помощью компьютерного зрения.

Запуск:  streamlit run app.py
"""
import base64
import logging
import os
import hashlib
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core import db
from core.content import (LOW_CONFIDENCE, POINTS_PER_CORRECT_ANSWER, POINTS_PER_FEEDBACK,
                          POINTS_PER_SCAN, QUIZ_REWARDS_PER_DAY, WASTE_INFO, HAZARD_MAYBE, HAZARD_SURE,
                          canonical, hazard_hint, level_for)
from core.model import DETECTOR_PATH, check_scene, classify, load_image, load_model
from core.pg import connection_hint
from core.quiz import random_questions
from core import storage, ui

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


def setting(key):
    """Настройка из .env / переменной окружения (локально) или из st.secrets (Streamlit Cloud)."""
    if os.getenv(key):
        return os.getenv(key)
    try:
        return st.secrets.get(key)
    except Exception:  # файла secrets.toml нет — локально это нормально
        return None


st.set_page_config(page_title="WasteWise — сортировка отходов", page_icon="♻️", layout="wide")
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
    st.error("Не удалось подключиться к базе данных. Попробуйте обновить страницу через минуту.")
    hint = connection_hint(setting("DATABASE_URL") or "")
    if hint:  # подсказка без секретов: пароль и адрес не показываются
        st.caption(hint)
    st.stop()


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def rus(cls):
    return WASTE_INFO.get(canonical(cls), {}).get("name", cls)


BIN_COLORS = [info["color"] for info in WASTE_INFO.values()]  # полоса под заголовками страниц


def model_classes():
    """Какие типы знает загруженная модель: старая — 4, новая — 7 (порядок — как в WASTE_INFO)."""
    known = {canonical(name) for name in get_model().names.values()}
    return [c for c in WASTE_INFO if c in known] + sorted(known - set(WASTE_INFO))


def plural(n, one, few, many):
    """1 тип, 2 типа, 5 типов."""
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
for k, v in {"user_id": None, "quiz": None, "quiz_answers": {}, "quiz_done": False, "seen_scans": {}}.items():
    st.session_state.setdefault(k, v)

user = db.get_user(conn, st.session_state.user_id) if st.session_state.user_id else None

# ---------- Боковое меню ----------
with st.sidebar:
    st.markdown(f'<div class="ww-logo"><img src="data:image/jpeg;base64,'
                f'{b64(ASSETS / "Logo_waste_seg.jpg")}" alt="WasteWise"></div>',
                unsafe_allow_html=True)
    st.markdown("### ♻️ WasteWise")
    if user:
        points_slot = st.empty()  # заполняется в конце скрипта, чтобы баллы были свежими
        pages = ["Главная", "Распознать отходы", "Викторина", "Рейтинг", "Профиль"]
    else:
        pages = ["Главная", "Распознать отходы", "Викторина", "Рейтинг", "Вход", "Регистрация"]
    page = st.radio("Навигация", pages, label_visibility="collapsed")
    if user and st.button("Выйти"):
        st.session_state.user_id = None
        st.rerun()
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.caption(AUTHOR)
    st.markdown(social_links(), unsafe_allow_html=True)


if st.session_state.pop("welcome", False) and user:
    st.toast(f"Добро пожаловать, {user['name']}! Аккаунт создан, вы вошли.", icon="🎉")


def show_points():
    """Баллы в меню. Вызывается в самом конце скрипта (после всех начислений) и перед st.stop():
    st.stop() обрывает скрипт, и раньше строка с баллами в меню из-за этого пропадала."""
    if user:
        fresh = db.get_user(conn, user["id"])
        points_slot.success(f"👤 {fresh['name']} · ⭐ {fresh['points']} баллов")


# =====================================================================
# ГЛАВНАЯ
# =====================================================================
if page == "Главная":
    ui.hero(
        b64(ASSETS / "123.jpg"),
        "Сортировка отходов с помощью ИИ",
        "Сфотографируй мусор — узнай, куда его выбросить",
        "Нейросеть определяет тип отхода, а приложение подсказывает, куда его нести, "
        "как подготовить и что туда не принимают.",
    )

    ui.cards([
        ("01", "Сфотографируй", "Загрузи готовое фото или сними предмет камерой телефона прямо в браузере."),
        ("02", "ИИ распознаёт", "Модель определит тип отхода и покажет, насколько она уверена."),
        ("03", "Сортируй правильно", "Куда нести, как подготовить и что туда точно не примут."),
    ])

    st.markdown("## WasteWise в цифрах")
    stats = db.global_stats(conn)
    m1, m2, m3 = st.columns(3)
    m1.metric("Распознано фото", stats["scans"])
    m2.metric("Участников", stats["users"])
    m3.metric("Исправлений от пользователей", stats["corrected"])

    st.markdown("## Почему это важно")
    ui.quote(
        "По данным Всемирного банка, объём твёрдых бытовых отходов в мире к 2050 году может вырасти "
        "на 70% по сравнению с 2016 годом. Главный барьер переработки — неправильная сортировка: "
        "одна грязная или «чужая» вещь может испортить целую партию вторсырья."
    )

    st.divider()
    st.markdown(f"**Автор проекта: {AUTHOR}, г. Астана.**")
    st.markdown(social_links(), unsafe_allow_html=True)

# =====================================================================
# РАСПОЗНАВАНИЕ
# =====================================================================
elif page == "Распознать отходы":
    known = model_classes()  # тексты подстраиваются под модель: старая знает 4 типа, новая — 7
    ui.page_header("Распознать отходы", "Сфотографируй предмет — нейросеть подскажет, в какой бак его нести "
                   "и как подготовить.", BIN_COLORS)
    count = f"{len(known)} {plural(len(known), 'тип', 'типа', 'типов')}"
    st.caption(f"Модель знает {count}" + (f" из {len(WASTE_INFO)}: серые ещё учатся. " if len(known) < len(WASTE_INFO)
                                          else " отходов. ")
               + "Лучше всего работает, если на фото один предмет крупным планом.")
    ui.waste_types([(i["emoji"], i["name"], i["color"], c in known) for c, i in WASTE_INFO.items()])

    tab_upload, tab_camera = st.tabs(["Загрузить фото", "Снять камерой"])
    with tab_upload:
        uploaded = st.file_uploader("Выберите изображение", type=["jpg", "jpeg", "png", "webp"])
    with tab_camera:
        shot = st.camera_input("Сделайте снимок") if st.toggle("Включить камеру") else None
    file = shot or uploaded

    raw = file.getvalue() if file is not None else None
    image = load_image(raw) if raw else None
    if raw and image is None:  # раньше битый файл ронял страницу с длинной ошибкой Python
        st.error("Не удалось открыть файл как изображение. Попробуйте другое фото (JPG, PNG или WEBP).")

    if image is None:
        st.session_state.shown_scan = None  # фото убрали — следующее открытие уже «возврат»
    else:
        file_key = hashlib.md5(raw).hexdigest()

        with st.spinner("Нейросеть анализирует фото…"):
            problem = cached_check_scene(file_key, image)
        if problem and st.session_state.get("force_key") != file_key:
            c_img, c_msg = st.columns([1, 1.3], gap="large")
            c_img.image(image, width="stretch")
            with c_msg:
                st.warning(f"🤔 {problem}")
                st.caption(f"Модель обучена только на отходах. На других фото она всё равно выберет "
                           f"один из {count}, поэтому сначала мы проверяем, что в кадре.")
                if st.button("Это точно отход — распознать"):
                    st.session_state.force_key = file_key
                    st.rerun()
            show_points()
            st.stop()

        with st.spinner("Нейросеть анализирует фото…"):
            ranked = cached_classify(file_key, image)
        best_cls, best_p = ranked[0]
        info = WASTE_INFO.get(canonical(best_cls), {})
        color = info.get("color", ui.GREEN)

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
                scan_id = db.save_scan(conn, user["id"] if user else None, best_cls, best_p, file_key)
                seen[scan_key] = {"id": scan_id, "fixed": False, "repeat": False}
                if user:
                    db.add_points(conn, user["id"], POINTS_PER_SCAN)
                    st.toast(f"+{POINTS_PER_SCAN} баллов!", icon="⭐")
        elif st.session_state.get("shown_scan") != scan_key:
            seen[scan_key]["repeat"] = True  # вернулись к фото, которое уже проверяли (А→Б→А)
        st.session_state.shown_scan = scan_key  # клики на том же фото повтором не считаются
        scan = seen[scan_key]

        col_img, col_res = st.columns([1, 1.3], gap="large")
        with col_img:
            st.image(image, width="stretch")
            others = [(c, p) for c, p in ranked[1:] if p >= 0.01]  # что ещё предполагала модель
            if others:
                st.markdown("##### Другие варианты модели")
                ui.bars([(f"{WASTE_INFO.get(canonical(c), {}).get('emoji', '')} {ui.esc(rus(c))}", p, f"{p:.0%}",
                          WASTE_INFO.get(canonical(c), {}).get("color", ui.GREEN)) for c, p in others],
                        max_value=1)
        with col_res:
            if scan["repeat"] and user:
                st.caption("Это фото вы уже проверяли — баллы за него были начислены раньше.")
            if best_p < LOW_CONFIDENCE:
                unknown = [rus(c).lower() for c in WASTE_INFO if c not in known]
                st.warning(
                    f"Модель не уверена ({best_p:.0%}). Возможно, это **{rus(best_cls)}** или "
                    f"**{rus(ranked[1][0])}**. Если предмет из смешанного материала, ответ может быть неточным."
                    + (f" А если это {', '.join(unknown)} — такие типы модель ещё не знает." if unknown else "")
                )
            ui.result_tag(info.get("emoji", ""), rus(best_cls), color, best_p)
            hazard = hazard_hint(ranked)  # батарейки и электроника — только в спецпункты
            if hazard == "sure":
                st.warning(HAZARD_SURE)
            elif hazard == "maybe":
                st.info(HAZARD_MAYBE)
            if best_p < LOW_CONFIDENCE:
                st.caption(f"Советы ниже — для варианта «{rus(best_cls)}».")
            ui.block("📍 Куда нести", ui.esc(info.get("where", "")))
            ui.steps("Как подготовить", info.get("tips", []), color)
            ui.block("🚫 Не принимают", ui.esc(info.get("not_accepted", "")), "warn")
            ui.block("💡 Интересный факт", ui.esc(info.get("fact", "")), "fact")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("#### Модель ошиблась?")
            st.caption("Выберите правильный тип — фото попадёт в набор, на котором модель учится дальше"
                       + (f", а вам +{POINTS_PER_FEEDBACK} баллов." if user else "."))
            fc1, fc2 = st.columns([2, 1], vertical_alignment="bottom")
            options = list(WASTE_INFO)  # все 7 типов, даже если модель пока знает меньше: так и собираем датасет
            labels = {c: rus(c) for c in options}
            correct = fc1.selectbox("Правильный тип", options, format_func=lambda c: labels[c])
            if fc2.button("Отправить исправление", disabled=scan["fixed"]):
                try:  # фото + метка пользователя → наш датасет (Supabase Storage или data/feedback)
                    path = get_feedback_store().save(correct, file_key, storage.encode_photo(image))
                except storage.StorageError:
                    log.exception("Не удалось сохранить фото для дообучения")
                    st.error("Не удалось сохранить фото. Попробуйте ещё раз через минуту.")
                else:  # баллы и отметка «исправлено» — только если фото действительно сохранилось
                    db.correct_scan(conn, scan["id"], correct, path)
                    scan["fixed"] = True  # одно исправление (и одни баллы за него) на фото
                    if user:
                        db.add_points(conn, user["id"], POINTS_PER_FEEDBACK)
                    st.success(f"Спасибо! Фото сохранено как «{labels[correct]}»."
                               + (f" +{POINTS_PER_FEEDBACK} баллов." if user else ""))
        if not user:
            st.caption("Войдите, чтобы получать баллы и участвовать в рейтинге.")

# =====================================================================
# ВИКТОРИНА
# =====================================================================
elif page == "Викторина":
    ui.page_header("Викторина по сортировке", "Пять вопросов о том, что и куда выбрасывать. "
                   f"За каждый правильный ответ — +{POINTS_PER_CORRECT_ANSWER} баллов.", BIN_COLORS)
    if user:
        left = max(0, QUIZ_REWARDS_PER_DAY - db.rewarded_quizzes_last_day(conn, user["id"]))
        st.caption(f"Викторин с баллами осталось: {left} из {QUIZ_REWARDS_PER_DAY} в сутки. "
                   "Без баллов можно тренироваться сколько угодно.")
    else:
        st.caption("Войдите, чтобы получать баллы за правильные ответы.")
    if st.button("Начать новую викторину (5 вопросов)", type="primary"):
        st.session_state.quiz = {"mode": "bank", "questions": random_questions(5), "uid": uuid.uuid4().hex}
        st.session_state.quiz_answers, st.session_state.quiz_done = {}, False

    quiz = st.session_state.quiz
    if quiz:
        questions = quiz["questions"]
        total = len(questions)
        if st.session_state.quiz_done:  # итог — сверху, чтобы не листать до конца
            score = st.session_state.get("quiz_score", 0)
            verdict = ("Отлично — ты знаешь, как сортировать!" if score == total else
                       "Хороший результат" if score >= total * 0.6 else "Есть что подтянуть")
            if not user:
                note = "Войдите, чтобы получать баллы за правильные ответы."
            else:
                earned = st.session_state.get("quiz_points", 0)
                note = (f"+{earned} баллов в рейтинг." if earned else
                        "Разберите ошибки ниже и попробуйте ещё раз." if not score else "Баллы за сегодня уже получены.")
            ui.score(score, total, verdict, note)
            if user and not (st.session_state.get("quiz_points", 0) or not score):
                st.info(f"Баллы начисляются за первые {QUIZ_REWARDS_PER_DAY} викторины в сутки — "
                        "лимит исчерпан. Результат сохранён в профиле, тренироваться можно дальше.")
            st.markdown("#### Разбор ответов")
            for i, q in enumerate(questions):
                ui.review(q["q"], st.session_state.quiz_answers[i] == q["correct"], q["correct"], q.get("why", ""))
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        # Пока игра идёт — вопросы просто списком; после проверки они сворачиваются под разбором.
        # Ключи у вариантов ответа постоянные, поэтому ответы не теряются при переносе в «Ваши ответы».
        holder = st.expander("Ваши ответы") if st.session_state.quiz_done else st.container()
        with holder:
            for i, q in enumerate(questions):
                with st.container(border=True):
                    ui.question_number(i + 1, total)
                    st.session_state.quiz_answers[i] = st.radio(
                        f"**{q['q']}**", q["options"], index=None, key=f"q_{quiz['uid']}_{i}",
                        disabled=st.session_state.quiz_done,
                    )
        if not st.session_state.quiz_done:
            answered = sum(a is not None for a in st.session_state.quiz_answers.values())
            st.progress(answered / total, text=f"Отвечено {answered} из {total}")
            if st.button("Проверить ответы", type="primary"):
                if None in st.session_state.quiz_answers.values():
                    st.warning("Ответьте на все вопросы.")
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
        ui.empty("Здесь появятся вопросы", "Нажмите «Начать новую викторину» — пять случайных вопросов "
                 "из базы. Повторять можно сколько угодно.")

# =====================================================================
# РЕЙТИНГ
# =====================================================================
elif page == "Рейтинг":
    ui.page_header("Рейтинг", "Кто сортирует больше всех — среди участников и школ.", BIN_COLORS)
    ui.rules([(POINTS_PER_SCAN, "за распознанное фото"),
              (POINTS_PER_CORRECT_ANSWER, f"за правильный ответ в викторине ({QUIZ_REWARDS_PER_DAY} в сутки)"),
              (POINTS_PER_FEEDBACK, "за исправление ошибки модели")])
    me_id = user["id"] if user else None
    t1, t2 = st.tabs(["Участники", "Школы"])
    with t1:
        rows = db.leaderboard_users(conn, with_ids=True)
        if rows:
            ui.podium(rows[:3], me_id)
            if len(rows) > 3:
                ui.ranking(rows[3:], start=4, me_id=me_id)
            if user and all(r[3] != me_id for r in rows):
                place = db.user_place(conn, me_id)
                st.caption(f"Ваше место: {place}. Ещё немного — и вы в топ-{len(rows)}!")
        else:
            ui.empty("Пока никого нет", "Зарегистрируйтесь и распознайте первое фото — и вы станете первым.")
    with t2:
        rows = db.leaderboard_schools(conn)
        if rows:
            ui.bars([(ui.esc(school), pts, f"{pts} баллов · {people} {plural(people, 'участник', 'участника', 'участников')}",
                      ui.GREEN) for school, pts, people in rows])
        else:
            ui.empty("Школ пока нет", "Укажите школу и класс при регистрации — и она появится в рейтинге.")

    stats = db.global_stats(conn)
    if stats["by_class"]:
        st.markdown("## Что чаще всего распознают")
        merged = {}  # старые метки («cardboard») складываются с новыми («paper»)
        for c, n in stats["by_class"]:
            merged[canonical(c)] = merged.get(canonical(c), 0) + n
        rows = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
        ui.bars([(f"{WASTE_INFO.get(c, {}).get('emoji', '')} {ui.esc(rus(c))}", n,
                  f"{n} {plural(n, 'фото', 'фото', 'фото')}", WASTE_INFO.get(c, {}).get("color", ui.GREEN))
                 for c, n in rows])

# =====================================================================
# ПРОФИЛЬ
# =====================================================================
elif page == "Профиль" and user:
    scans = db.user_scans(conn, user["id"])
    quizzes = db.user_quizzes(conn, user["id"])
    place = db.user_place(conn, user["id"])
    ui.profile_header(user["name"], f"{user['school'] or 'Школа не указана'} · логин {user['username']}")
    (start_at, title, emoji), following = level_for(user["points"])
    ui.level(emoji, title, user["points"], following and following[1], following and following[0], start_at)

    n_scans, n_quizzes = db.user_totals(conn, user["id"])  # всего, а не только последние 20
    ui.stats([(place or "—", "место в рейтинге"),
              (n_scans, plural(n_scans, "распознавание", "распознавания", "распознаваний")),
              (n_quizzes, plural(n_quizzes, "викторина", "викторины", "викторин"))])

    left_col, right_col = st.columns([1.4, 1], gap="large")
    with left_col:
        st.markdown("### Последние распознавания")
        if scans:
            ui.history([
                (WASTE_INFO.get(canonical(f or p), {}).get("emoji", ""), rus(f or p),
                 WASTE_INFO.get(canonical(f or p), {}).get("color", ui.GREEN),
                 f"вы исправили: модель думала «{rus(p)}»" if f else f"модель уверена на {conf:.0%}",
                 ui.nice_date(d))
                for p, conf, f, d in scans[:8]
            ])
            with st.expander("Вся история таблицей"):
                st.dataframe(pd.DataFrame(
                    [(rus(p), f"{conf:.0%}", rus(f) if f else "", ui.nice_date(d)) for p, conf, f, d in scans],
                    columns=["Ответ модели", "Уверенность", "Исправлено на", "Когда"]), width="stretch", hide_index=True)
        else:
            ui.empty("Пока пусто", "Откройте «Распознать отходы» и сфотографируйте первый предмет — "
                     f"+{POINTS_PER_SCAN} баллов.")
    with right_col:
        counts = {}
        for cls, n in db.user_class_counts(conn, user["id"]):
            counts[canonical(cls)] = counts.get(canonical(cls), 0) + n
        if counts:
            st.markdown("### Что вы сортировали")
            ui.bars([(f"{WASTE_INFO.get(cl, {}).get('emoji', '')} {ui.esc(rus(cl))}", n, str(n),
                      WASTE_INFO.get(cl, {}).get("color", ui.GREEN))
                     for cl, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)])
        st.markdown("### Викторины")
        if quizzes:
            ui.history([("🧩", f"{s} из {t} правильно", ui.GREEN if s == t else ui.AMBER,
                         ("ИИ-вопросы" if m == "ai" else "готовые вопросы") + (f" · +{pts} баллов" if pts else ""),
                         ui.nice_date(d)) for s, t, m, pts, d in quizzes[:6]])
        else:
            ui.empty("Ещё ни одной", f"Пройдите викторину — до +{5 * POINTS_PER_CORRECT_ANSWER} баллов за раз.")

# =====================================================================
# ВХОД / РЕГИСТРАЦИЯ
# =====================================================================
elif page == "Вход":
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        ui.page_header("Вход", "Баллы, рейтинг и история распознаваний — в вашем профиле.", BIN_COLORS)
        with st.form("login"):
            username = st.text_input("Логин")
            password = st.text_input("Пароль", type="password")
            if st.form_submit_button("Войти", type="primary", width="stretch"):
                uid = db.authenticate(conn, username, password)
                if uid:
                    st.session_state.user_id = uid
                    st.rerun()
                else:
                    st.error("Неверный логин или пароль")
        st.caption("Нет аккаунта? Откройте «Регистрация» в меню слева.")

elif page == "Регистрация":
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        ui.page_header("Регистрация", "Получайте баллы за каждое фото и правильный ответ, соревнуйтесь "
                       "с одноклассниками.", BIN_COLORS)
        with st.form("register"):
            username = st.text_input("Логин")
            password = st.text_input("Пароль (минимум 6 символов)", type="password")
            name = st.text_input("Имя")
            school = st.text_input("Школа и класс (необязательно), например «Гимназия №5, 10А»")
            if st.form_submit_button("Зарегистрироваться", type="primary", width="stretch"):
                if not (username and password and name):
                    st.error("Заполните логин, пароль и имя.")
                else:
                    ok, msg = db.register_user(conn, username, password, name, school)
                    if ok:  # сразу входим: второй раз вводить логин и пароль незачем
                        st.session_state.user_id = db.authenticate(conn, username, password)
                        st.session_state.welcome = True
                        st.rerun()
                    st.error(msg)

# ---------- Баллы в меню (в самом конце, после всех начислений) ----------
show_points()
