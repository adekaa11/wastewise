"""WasteWise — веб-приложение для сортировки отходов с помощью компьютерного зрения.

Запуск:  streamlit run app.py
"""
import base64
import io
import os
import hashlib
import uuid
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from PIL import Image, ImageOps

from core import db
from core.content import (LOW_CONFIDENCE, POINTS_PER_CORRECT_ANSWER, POINTS_PER_FEEDBACK,
                          POINTS_PER_SCAN, WASTE_INFO)
from core.model import DETECTOR_PATH, check_scene, classify, load_model
from core.quiz import ai_available, generate_questions, random_questions

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
FEEDBACK_DIR = ROOT / "data" / "feedback"

# ---------- Настройки и секреты ----------
load_dotenv(ROOT / ".env")
try:  # на Streamlit Cloud ключ хранится в «Secrets», а не в файле .env
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL"):
        if key in st.secrets and not os.getenv(key):
            os.environ[key] = st.secrets[key]
except Exception:
    pass

st.set_page_config(page_title="WasteWise — сортировка отходов", page_icon="♻️", layout="wide")


@st.cache_resource  # модель и база загружаются один раз, а не при каждом клике
def get_model():
    return load_model()


@st.cache_resource
def get_detector():
    return load_model(DETECTOR_PATH)


@st.cache_resource
def get_db():
    conn = db.get_conn()
    db.init_db(conn)
    return conn


conn = get_db()


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def rus(cls):
    return WASTE_INFO.get(cls, {}).get("name", cls)


# ---------- Состояние сессии ----------
for k, v in {"user_id": None, "quiz": None, "quiz_answers": {}, "quiz_done": False, "last_scan": None}.items():
    st.session_state.setdefault(k, v)

user = db.get_user(conn, st.session_state.user_id) if st.session_state.user_id else None

# ---------- Боковое меню ----------
with st.sidebar:
    st.markdown(f'<img src="data:image/jpeg;base64,{b64(ASSETS / "Logo_waste_seg.jpg")}" width="180">',
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

# =====================================================================
# ГЛАВНАЯ
# =====================================================================
if page == "Главная":
    st.markdown(
        f"""<div style="background-image:linear-gradient(rgba(0,0,0,.35),rgba(0,0,0,.35)),
        url('data:image/jpeg;base64,{b64(ASSETS / "123.jpg")}');background-size:cover;background-position:center;
        border-radius:14px;padding:70px 30px;text-align:center;color:white;margin-bottom:24px">
        <h1 style="color:white;margin:0;font-size:clamp(1.6rem,5vw,2.8rem)">Сфотографируй мусор — узнай, куда его выбросить</h1>
        <p style="font-size:1.15rem;margin-top:12px">Нейросеть определяет тип отхода, а приложение учит правильной сортировке</p>
        </div>""",
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    c1.markdown("#### 📸 1. Сфотографируй\nЗагрузи фото или сними с камеры телефона.")
    c2.markdown("#### 🧠 2. ИИ распознает\nМодель определит: стекло, металл, бумага или пластик.")
    c3.markdown("#### ♻️ 3. Сортируй правильно\nСоветы, куда выбросить, и что НЕ принимают.")

    stats = db.global_stats(conn)
    m1, m2, m3 = st.columns(3)
    m1.metric("Распознано фото", stats["scans"])
    m2.metric("Участников", stats["users"])
    m3.metric("Исправлений от пользователей", stats["corrected"])

    st.subheader("Почему это важно")
    st.write(
        "По данным Всемирного банка, объём твёрдых бытовых отходов в мире к 2050 году может вырасти на 70% "
        "по сравнению с 2016 годом. Главный барьер переработки — неправильная сортировка: "
        "одна грязная или «чужая» вещь может испортить целую партию вторсырья."
    )
    st.caption("Автор проекта: Кадыргажы Айзере, школа-гимназия № 5, г. Астана.")

# =====================================================================
# РАСПОЗНАВАНИЕ
# =====================================================================
elif page == "Распознать отходы":
    st.title("📸 Распознать отходы")
    st.caption("Модель пока знает 4 типа: стекло, металл, бумага, пластик. "
               "Лучше всего работает, если на фото один предмет на однотонном фоне.")

    tab_upload, tab_camera = st.tabs(["Загрузить фото", "Снять камерой"])
    with tab_upload:
        uploaded = st.file_uploader("Выберите изображение", type=["jpg", "jpeg", "png", "webp"])
    with tab_camera:
        shot = st.camera_input("Сделайте снимок") if st.toggle("Включить камеру") else None
    file = shot or uploaded

    if file is not None:
        raw = file.getvalue()
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        file_key = hashlib.md5(raw).hexdigest()

        with st.spinner("Нейросеть анализирует фото…"):
            problem = check_scene(get_detector(), image)
        if problem and st.session_state.get("force_key") != file_key:
            c_img, c_msg = st.columns([1, 1.3])
            c_img.image(image, use_container_width=True)
            with c_msg:
                st.warning(f"🤔 {problem}")
                st.caption("Модель обучена только на отходах. На других фото она всё равно выберет "
                           "один из 4 типов, поэтому сначала мы проверяем, что в кадре.")
                if st.button("Это точно отход — распознать"):
                    st.session_state.force_key = file_key
                    st.rerun()
            st.stop()

        with st.spinner("Нейросеть анализирует фото…"):
            ranked = classify(get_model(), image)
        best_cls, best_p = ranked[0]
        info = WASTE_INFO.get(best_cls, {})

        # одно и то же фото не даёт баллы повторно
        if st.session_state.last_scan is None or st.session_state.last_scan["key"] != file_key:
            scan_id = db.save_scan(conn, user["id"] if user else None, best_cls, best_p)
            st.session_state.last_scan = {"key": file_key, "id": scan_id, "fixed": False}
            if user:
                db.add_points(conn, user["id"], POINTS_PER_SCAN)
                st.toast(f"+{POINTS_PER_SCAN} баллов!", icon="⭐")

        col_img, col_res = st.columns([1, 1.3])
        col_img.image(image, use_container_width=True)
        with col_res:
            if best_p < LOW_CONFIDENCE:
                st.warning(
                    f"Модель не уверена ({best_p:.0%}). Возможно, это **{rus(best_cls)}** или "
                    f"**{rus(ranked[1][0])}**. Если предмет из смешанного материала или это картон, "
                    "органика, батарейка — модель такие типы ещё не знает."
                )
            st.markdown(
                f"<h2 style='color:{info.get('color', '#2E7D32')};margin-bottom:0'>"
                f"{info.get('emoji', '')} {rus(best_cls)}</h2>",
                unsafe_allow_html=True,
            )
            st.progress(best_p, text=f"Уверенность: {best_p:.0%}")
            if best_p < LOW_CONFIDENCE:
                st.caption(f"Советы ниже — для варианта «{rus(best_cls)}».")
            st.markdown(f"**Куда:** {info.get('where', '')}")
            st.markdown("**Как подготовить:**\n" + "\n".join(f"- {t}" for t in info.get("tips", [])))
            st.error(f"**Не принимают:** {info.get('not_accepted', '')}", icon="🚫")
            st.info(f"💡 {info.get('fact', '')}")
            with st.expander("Другие варианты модели"):
                for cls, p in ranked:
                    st.write(f"{rus(cls)} — {p:.1%}")

        st.divider()
        st.markdown("**Модель ошиблась?** Укажите правильный ответ — фото попадёт в набор для дообучения.")
        fc1, fc2 = st.columns([2, 1])
        options = [c for c in WASTE_INFO] + ["cardboard", "organic", "other"]
        labels = {**{c: rus(c) for c in WASTE_INFO}, "cardboard": "Картон", "organic": "Органика", "other": "Другое"}
        correct = fc1.selectbox("Правильный тип", options, format_func=lambda c: labels[c])
        if fc2.button("Отправить исправление", disabled=st.session_state.last_scan["fixed"]):
            folder = FEEDBACK_DIR / correct
            folder.mkdir(parents=True, exist_ok=True)
            image.save(folder / f"{file_key}.jpg", quality=92)
            db.correct_scan(conn, st.session_state.last_scan["id"], correct)
            st.session_state.last_scan["fixed"] = True
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
    st.title("🧩 Викторина по сортировке")
    mode = st.radio("Режим", ["Готовые вопросы", "Вопросы по своему тексту (ИИ)"], horizontal=True)

    if mode == "Готовые вопросы":
        if st.button("Начать новую викторину (5 вопросов)", type="primary"):
            st.session_state.quiz = {"mode": "bank", "questions": random_questions(5), "uid": uuid.uuid4().hex}
            st.session_state.quiz_answers, st.session_state.quiz_done = {}, False
    else:
        if not ai_available():
            st.info("Для этого режима нужен ключ OpenAI (OPENAI_API_KEY). Готовые вопросы работают без него.")
        text = st.text_area("Вставьте текст об экологии или сортировке", height=150)
        level = st.selectbox("Сложность", ["лёгкий", "средний", "сложный"])
        if st.button("Сгенерировать", type="primary", disabled=not ai_available() or len(text) < 50):
            try:
                with st.spinner("ИИ составляет вопросы…"):
                    qs = generate_questions(text, level)
                st.session_state.quiz = {"mode": "ai", "questions": qs, "uid": uuid.uuid4().hex}
                st.session_state.quiz_answers, st.session_state.quiz_done = {}, False
            except Exception as e:
                st.error(f"Не получилось сгенерировать вопросы: {e}")
        if 0 < len(text) < 50:
            st.caption("Текст слишком короткий — нужно хотя бы 50 символов.")

    quiz = st.session_state.quiz
    if quiz:
        for i, q in enumerate(quiz["questions"]):
            st.session_state.quiz_answers[i] = st.radio(
                f"**{i + 1}. {q['q']}**", q["options"], index=None, key=f"q_{quiz['uid']}_{i}",
                disabled=st.session_state.quiz_done,
            )
        if not st.session_state.quiz_done and st.button("Проверить ответы"):
            if None in st.session_state.quiz_answers.values():
                st.warning("Ответьте на все вопросы.")
            else:
                st.session_state.quiz_done = True
                score = sum(st.session_state.quiz_answers[i] == q["correct"] for i, q in enumerate(quiz["questions"]))
                st.session_state.quiz_score = score
                if user:
                    db.save_quiz(conn, user["id"], score, len(quiz["questions"]), quiz["mode"])
                    db.add_points(conn, user["id"], score * POINTS_PER_CORRECT_ANSWER)
                st.rerun()
        if st.session_state.quiz_done:
            total = len(quiz["questions"])
            score = st.session_state.get("quiz_score", 0)
            st.subheader(f"Результат: {score} из {total}")
            if user:
                st.success(f"+{score * POINTS_PER_CORRECT_ANSWER} баллов")
            for i, q in enumerate(quiz["questions"]):
                ok = st.session_state.quiz_answers[i] == q["correct"]
                st.markdown(f"{'✅' if ok else '❌'} **{q['q']}** — правильно: *{q['correct']}*. {q.get('why', '')}")

# =====================================================================
# РЕЙТИНГ
# =====================================================================
elif page == "Рейтинг":
    st.title("🏆 Рейтинг")
    st.caption(f"Баллы: +{POINTS_PER_SCAN} за распознавание, +{POINTS_PER_CORRECT_ANSWER} за правильный ответ, "
               f"+{POINTS_PER_FEEDBACK} за исправление ошибки модели.")
    t1, t2 = st.tabs(["Участники", "Школы"])
    with t1:
        rows = db.leaderboard_users(conn)
        if rows:
            df = pd.DataFrame(rows, columns=["Имя", "Школа / класс", "Баллы"])
            df.index = range(1, len(df) + 1)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Пока никого нет — зарегистрируйтесь первым!")
    with t2:
        rows = db.leaderboard_schools(conn)
        if rows:
            df = pd.DataFrame(rows, columns=["Школа / класс", "Баллы", "Участников"])
            st.altair_chart(
                alt.Chart(df).mark_bar(color="#2E7D32").encode(
                    x=alt.X("Баллы:Q"), y=alt.Y("Школа / класс:N", sort="-x")),
                use_container_width=True,
            )
        else:
            st.info("Укажите школу при регистрации, чтобы она появилась в рейтинге.")

    stats = db.global_stats(conn)
    if stats["by_class"]:
        st.subheader("Что чаще всего распознают")
        df = pd.DataFrame([(rus(c), n) for c, n in stats["by_class"]], columns=["Тип", "Количество"])
        st.altair_chart(alt.Chart(df).mark_arc(innerRadius=50).encode(
            theta="Количество:Q", color="Тип:N"), use_container_width=True)

# =====================================================================
# ПРОФИЛЬ
# =====================================================================
elif page == "Профиль" and user:
    st.title(f"👋 {user['name']}")
    a, b, c = st.columns(3)
    a.metric("Баллы", user["points"])
    scans = db.user_scans(conn, user["id"])
    quizzes = db.user_quizzes(conn, user["id"])
    b.metric("Распознаваний", len(scans))
    c.metric("Викторин", len(quizzes))
    st.write(f"Логин: `{user['username']}` · Школа: {user['school'] or '—'}")
    if scans:
        st.subheader("Последние распознавания")
        st.dataframe(pd.DataFrame(
            [(rus(p), f"{c:.0%}", rus(f) if f else "", d) for p, c, f, d in scans],
            columns=["Ответ модели", "Уверенность", "Исправлено на", "Дата"]), use_container_width=True)
    if quizzes:
        st.subheader("Викторины")
        st.dataframe(pd.DataFrame(
            [(f"{s}/{t}", "ИИ" if m == "ai" else "Готовые", d) for s, t, m, d in quizzes],
            columns=["Результат", "Режим", "Дата"]), use_container_width=True)

# =====================================================================
# ВХОД / РЕГИСТРАЦИЯ
# =====================================================================
elif page == "Вход":
    st.title("Вход")
    with st.form("login"):
        username = st.text_input("Логин")
        password = st.text_input("Пароль", type="password")
        if st.form_submit_button("Войти", type="primary"):
            uid = db.authenticate(conn, username, password)
            if uid:
                st.session_state.user_id = uid
                st.rerun()
            else:
                st.error("Неверный логин или пароль")

elif page == "Регистрация":
    st.title("Регистрация")
    with st.form("register"):
        username = st.text_input("Логин")
        password = st.text_input("Пароль (минимум 6 символов)", type="password")
        name = st.text_input("Имя")
        school = st.text_input("Школа и класс (необязательно), например «Гимназия №5, 10А»")
        if st.form_submit_button("Зарегистрироваться", type="primary"):
            if not (username and password and name):
                st.error("Заполните логин, пароль и имя.")
            else:
                ok, msg = db.register_user(conn, username, password, name, school)
                (st.success if ok else st.error)(msg)

# ---------- Баллы в меню (в самом конце, после всех начислений) ----------
if user:
    fresh = db.get_user(conn, user["id"])
    points_slot.success(f"👤 {fresh['name']} · ⭐ {fresh['points']} баллов")
