"""Режим для школ: QR-коды на баках, отчёт учителя, роли и казахский интерфейс."""
from datetime import datetime, timedelta, timezone

import pytest

from conftest import NEW_CLASSES, photo, start_app
from core import db, qr, report


NOW = datetime.now(timezone.utc).replace(tzinfo=None)


# ---------- Ссылка из QR-кода ----------

def test_qr_parse_accepts_only_known_values():
    assert qr.parse({"school_id": "nis_astana", "box": "Plastic"}) == qr.QR("nis_astana", "plastic")
    assert qr.parse({"school": "gym-5", "bin": "battery"}) == qr.QR("gym-5", "ewaste")  # синонимы и старые имена
    assert qr.parse({"school_id": "<script>", "box": "rocket"}) == qr.QR(None, None)
    assert qr.parse({"school_id": "a" * 41}).school_id is None
    assert not qr.parse({})


def test_qr_link_and_png():
    url = qr.link("https://ww.streamlit.app/?theme=dark", "nis_astana", "glass", "kk")
    assert url == "https://ww.streamlit.app/?school_id=nis_astana&box=glass&lang=kk"
    assert qr.parse(dict(p.split("=") for p in url.split("?")[1].split("&"))) == qr.QR("nis_astana", "glass")
    assert qr.png(url)[:8] == b"\x89PNG\r\n\x1a\n"


def test_qr_verdict():
    assert qr.verdict("paper", "cardboard") == "ok"  # старое имя класса — тот же бак
    assert qr.verdict("glass", "plastic") == "wrong"
    assert qr.verdict(None, "plastic") is None


# ---------- Отчёт учителя ----------

ROWS = [  # (дата UTC, класс, модель, исправление, бак)
    ("2026-10-20 05:00:00", "7А", "plastic", None, "plastic"),
    ("2026-10-20 06:00:00", "7А", "glass", None, "plastic"),       # ошибка: стекло у бака пластика
    ("2026-10-20 20:00:00", "7Б", "glass", "plastic", "plastic"),  # ученик исправил → верно; 20:00 UTC = 21 окт в Астане
    ("2026-10-21 07:00:00", None, "metal", None, None),            # гость, бак не указан
]


def test_summarize():
    s = report.summarize(ROWS)
    assert (s["total"], s["at_bins"], s["errors"]) == (4, 3, 1)
    assert s["accuracy"] == pytest.approx(2 / 3)
    assert s["classes"][0] == ("7А", 2, 0.5)
    assert ("—", 1, None) in s["classes"]
    assert s["mistakes"] == [(("plastic", "glass"), 1)]
    days = {str(d): (n, acc) for d, n, acc in s["daily"]}
    assert days["2026-10-20"] == (2, 0.5) and days["2026-10-21"] == (2, 1.0)  # время Казахстана, UTC+5


def test_csv_opens_in_excel():
    data = report.to_csv(ROWS, name=lambda c: c.upper())
    assert data.startswith(b"\xef\xbb\xbf")  # BOM — Excel узнаёт UTF-8
    lines = data.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Дата;Класс;Бак")
    assert lines[2].endswith("нет") and "GLASS" in lines[2]


# ---------- База: роли и сканы школы (SQLite и Postgres) ----------

def test_roles_and_school_scans(store):
    db.register_user(store, "teacher1", "secret1", "Учитель", class_label=" 7 а ")
    uid = db.authenticate(store, "teacher1", "secret1")
    assert db.user_access(store, uid) == {"role": "student", "school_id": None, "class_label": "7А"}
    assert db.set_role(store, "teacher1", "teacher", "nis_astana")
    assert db.user_access(store, uid)["role"] == "teacher"
    assert not db.set_role(store, "nobody", "teacher", "x1")
    with pytest.raises(ValueError):
        db.set_role(store, "teacher1", "superuser")

    db.save_scan(store, None, "glass", 0.9, "h1", school_id="nis_astana", bin="plastic", class_label=None)
    db.save_scan(store, uid, "plastic", 0.8, "h2", school_id="nis_astana", bin="plastic", class_label="7А")
    db.save_scan(store, uid, "paper", 0.8, "h3", school_id="other_school", bin="paper")
    rows = db.school_scans(store, "nis_astana", NOW - timedelta(days=1))
    assert [(r[1], r[2], r[4]) for r in rows] == [(None, "glass", "plastic"), ("7А", "plastic", "plastic")]
    assert db.school_scans(store, "nis_astana", NOW + timedelta(days=1)) == []
    assert db.school_ids(store) == ["nis_astana", "other_school"]


# ---------- Страницы ----------

def test_qr_link_opens_scanner_and_checks_the_bin(tmp_path, monkeypatch):
    """По QR со школьного бака: сразу «Распознать отходы», ответ «не в этот бак», фото — с кодом школы и бака."""
    app = start_app(tmp_path, monkeypatch, query={"school_id": "nis_astana", "box": "glass"})
    assert "nis_astana" in app.html()  # плашка «Школа · Бак» — значит, открыто распознавание
    app.upload(photo("orange"))  # поддельная модель всегда отвечает «пластик»
    assert any("Не в этот бак" in e.value for e in app.at.error)
    assert app.query("SELECT school_id, bin, user_id FROM scans") == [("nis_astana", "glass", None)]


def test_qr_right_bin(tmp_path, monkeypatch):
    app = start_app(tmp_path, monkeypatch, query={"school_id": "nis_astana", "box": "plastic"})
    app.upload(photo("orange"))
    assert any("Верно" in s.value for s in app.at.success)


def test_guest_scans_freely_and_is_invited_to_register(tmp_path, monkeypatch):
    """Гость распознаёт без входа и без лимита (так работают QR-коды), а после 3 фото видит приглашение."""
    app = start_app(tmp_path, monkeypatch)
    app.go("Распознать отходы")
    for color in ("orange", "teal", "pink"):
        app.upload(photo(color))
    assert any("Зарегистрируйтесь" in i.value for i in app.at.info)
    app.upload(photo("olive"))  # четвёртое фото тоже распознаётся
    assert len(app.scans()) == 4


def test_teacher_panel(tmp_path, monkeypatch):
    app = start_app(tmp_path, monkeypatch, query={"school_id": "nis_astana", "box": "glass"})
    app.classifier.names, app.classifier.probs = NEW_CLASSES, [0.02, 0.02, 0.02, 0.02, 0.02, 0.05, 0.85]
    app.register_and_login("teacher1")
    app.upload(photo("orange"))
    assert "Панель учителя" not in app.at.sidebar.radio[0].options  # ученику панель не видна

    app.set_role("teacher1", "teacher", "nis_astana")
    assert "Панель учителя" in app.at.sidebar.radio[0].options
    app.go("Панель учителя")
    html = app.html()
    assert "Частые ошибки у баков" in html and "Пластик" in html
    assert any("Скачать отчёт" in b.label for b in app.at.get("download_button"))


def test_teacher_prints_qr_codes_for_all_bins(tmp_path, monkeypatch):
    app = start_app(tmp_path, monkeypatch, secrets={"APP_URL": "https://ww.streamlit.app"})
    app.register_and_login("teacher3")
    app.set_role("teacher3", "teacher", "gym_5")
    app.go("Панель учителя")
    pngs = [b for b in app.at.get("download_button") if b.label == "Скачать PNG"]
    assert len(pngs) == 7  # по QR-коду на каждый из 7 баков
    links = " ".join(c.value for c in app.at.code)
    assert "https://ww.streamlit.app/?school_id=gym_5&box=plastic" in links


def test_teacher_without_school_sees_instructions(tmp_path, monkeypatch):
    app = start_app(tmp_path, monkeypatch)
    app.register_and_login("teacher2")
    app.set_role("teacher2", "teacher")
    app.go("Панель учителя")
    assert any("python -m core.roles" in i.value for i in app.at.info)


def test_kazakh_interface(tmp_path, monkeypatch):
    app = start_app(tmp_path, monkeypatch, query={"lang": "kk"})
    assert "Қоқысты суретке түсір" in app.html()
    # AppTest не знает format_func приложения, поэтому в казахском меню выбираем по казахской подписи
    app.go("Қалдықты тану").upload(photo("orange"))
    html = app.html()
    assert "Пластик" in html and "Қайда апару керек" in html
    app.go("Викторина")
    app.button("Жаңа викторина бастау (5 сұрақ)").click()
    app.run()
    assert "сұрақтың 1-сі" in app.html()


def test_page_survives_language_switch(tmp_path, monkeypatch):
    """Смена языка перерисовывает меню с новыми подписями, но открытая страница остаётся та же."""
    app = start_app(tmp_path, monkeypatch)
    app.go("Рейтинг")
    app.at.session_state["lang_pick"] = "kk"
    app.run()
    assert "Кім ең көп сұрыптайды" in app.html()


def test_home_shows_model_accuracy_and_hides_zero_counters(tmp_path, monkeypatch):
    app = start_app(tmp_path, monkeypatch)
    labels = [m.label for m in app.at.metric]
    assert "Точность модели" in labels
    assert next(m.value for m in app.at.metric if m.label == "Точность модели") == "85,7%"
    assert "Исправлений от пользователей" not in labels  # пустой счётчик (0) не показываем


def test_for_schools_page_explains_connection_and_data(tmp_path, monkeypatch):
    app = start_app(tmp_path, monkeypatch)
    app.go("Для школ")
    html = app.html()
    assert "Наклейте QR-коды" in html and "не сохраняется" in html and "OpenAI" in html
    assert any(b.label == "Написать в Telegram" for b in app.at.get("link_button"))


def test_home_shows_official_kazakhstan_figures_with_sources(tmp_path, monkeypatch):
    app = start_app(tmp_path, monkeypatch)
    html = app.html()
    assert all(v in html for v in ("4,5+ млн т", "25,8%", "95%"))
    assert "primeminister.kz" in html and "inform.kz" in html
