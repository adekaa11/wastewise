"""Общие заготовки для тестов.

Настоящие нейросети (torch + ultralytics, ~2 ГБ) для тестов не нужны: вместо них
подставляются «поддельные» модели, которые отвечают мгновенно и считают вызовы.
Запуск:  pip install -r requirements.txt pytest  →  pytest
"""
import io
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from PIL import Image
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db, model  # noqa: E402


# Тесты хранилища идут на SQLite всегда, а на Postgres — если задан TEST_DATABASE_URL
# (в CI это контейнер postgres, см. .github/workflows/tests.yml). База в TEST_DATABASE_URL
# очищается перед каждым тестом — не указывайте там базу сайта!
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
BACKENDS = ["sqlite"] + (["postgres"] if TEST_DATABASE_URL else [])
needs_postgres = pytest.mark.skipif(not TEST_DATABASE_URL, reason="нужен TEST_DATABASE_URL с тестовым Postgres")


def fresh_postgres():
    """Соединение с пустой тестовой базой Postgres: все таблицы WasteWise удалены, миграции применятся заново."""
    conn = db.get_conn(TEST_DATABASE_URL)
    conn.execute("DROP TABLE IF EXISTS quiz_results, scans, users, schema_migrations CASCADE")
    return conn


@pytest.fixture
def pgconn():
    """Только Postgres: пустая тестовая база с применёнными миграциями."""
    if not TEST_DATABASE_URL:
        pytest.skip("нужен TEST_DATABASE_URL с тестовым Postgres")
    conn = fresh_postgres()
    db.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture(params=BACKENDS)
def store(request, tmp_path, monkeypatch):
    """Пустая база с таблицами — та же, с которой работает приложение (SQLite или Postgres)."""
    if request.param == "postgres":
        conn = fresh_postgres()
    else:
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
        conn = db.get_conn()
    db.init_db(conn)
    yield conn
    conn.close()


def backdate(conn, table, row_id, hours):
    """Сдвинуть дату записи в прошлое (для проверки окна «24 часа»)."""
    if getattr(conn, "dialect", "sqlite") == "postgres":
        past = f"timezone('utc', now()) - interval '{int(hours)} hours'"
    else:
        past = f"datetime('now', '-{int(hours)} hours')"
    conn.execute(f"UPDATE {table} SET date = {past} WHERE id = ?", (row_id,))
    conn.commit()


@pytest.fixture
def fake_storage():
    """Поддельный Supabase Storage (tests/fake_supabase.py) с приватным бакетом feedback."""
    from fake_supabase import FakeStorage

    fake = FakeStorage()
    yield fake
    fake.close()


class _List(list):
    def tolist(self):
        return list(self)


class FakeClassifier:
    """Вместо YOLO-классификатора: всегда «пластик, 90%»."""

    def __init__(self):
        self.calls = 0

    def predict(self, image, **kwargs):
        self.calls += 1
        probs = SimpleNamespace(data=_List([0.90, 0.05, 0.03, 0.02]))
        return [SimpleNamespace(probs=probs, names={0: "plastic", 1: "glass", 2: "metal", 3: "paper"})]


class FakeDetector:
    """Вместо YOLO-детектора: по умолчанию в кадре никого нет."""

    def __init__(self):
        self.calls = 0
        self.boxes = []  # что «увидит» детектор: [(класс COCO, (x1, y1, x2, y2)), ...]

    def predict(self, image, **kwargs):
        self.calls += 1
        boxes = SimpleNamespace(cls=_List(c for c, _ in self.boxes), xyxy=_List(b for _, b in self.boxes))
        return [SimpleNamespace(boxes=boxes)]


def photo(color, size=(320, 240), fmt="JPEG"):
    """Светлое однотонное «фото» — разные цвета дают разные файлы."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


class _Upload:
    def __init__(self, raw):
        self._raw = raw

    def getvalue(self):
        return self._raw


class App:
    """Обёртка над AppTest: страница, загрузка фото, вход, баллы из базы."""

    def __init__(self, path, db_path, classifier, detector, uploads, database_url=None, secrets=None):
        self.at = AppTest.from_file(str(path), default_timeout=60)
        if database_url:  # как на Streamlit Cloud: строка подключения — в Secrets
            self.at.secrets["DATABASE_URL"] = database_url
        for key, value in (secrets or {}).items():
            self.at.secrets[key] = value
        self.feedback_dir = Path(path).parent / "data" / "feedback"
        self.db_path, self.database_url = db_path, database_url
        self.classifier, self.detector = classifier, detector
        self._uploads = uploads
        self.run()

    def run(self):
        self.at.run()
        assert not self.at.exception, [e.value for e in self.at.exception]
        return self

    def go(self, page):
        self.at.sidebar.radio[0].set_value(page)
        return self.run()

    def button(self, label):
        return next(b for b in self.at.button if b.label == label)

    def upload(self, raw):
        self._uploads["file"] = _Upload(raw) if raw is not None else None
        return self.run()

    def register_and_login(self, username="alice", password="secret1"):
        self.go("Регистрация")
        for widget, value in zip(self.at.text_input, [username, password, "Алиса", "Школа 1"]):
            widget.input(value)
        self.button("Зарегистрироваться").click()
        self.run()
        self.login(username, password)

    def login(self, username="alice", password="secret1"):
        self.go("Вход")
        self.at.text_input[0].input(username)
        self.at.text_input[1].input(password)
        self.button("Войти").click()
        self.run()

    def logout(self):
        next(b for b in self.at.sidebar.button if b.label == "Выйти").click()
        self.run()

    def query(self, sql, params=()):
        """Прочитать из базы приложения напрямую (SQLite-файл или тестовый Postgres)."""
        conn = db.get_conn(self.database_url) if self.database_url else sqlite3.connect(self.db_path)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def points(self, username="alice"):
        return self.query("SELECT points FROM users WHERE username = ?", (username,))[0][0]

    def scans(self):
        return self.query("SELECT user_id, predicted, corrected, image_hash FROM scans ORDER BY id")

    def captions(self):
        return [c.value for c in self.at.caption]


def start_app(tmp_path, monkeypatch, database_url=None, secrets=None):
    """Запустить приложение в отдельной папке: своя data/feedback, модели — поддельные."""
    for key in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        monkeypatch.delenv(key, raising=False)  # чтобы тесты не попали в настоящую базу и хранилище
    shutil.copy(ROOT / "app.py", tmp_path / "app.py")
    (tmp_path / "assets").mkdir()
    for name in ("Logo_waste_seg.jpg", "123.jpg"):
        shutil.copy(ROOT / "assets" / name, tmp_path / "assets" / name)

    classifier, detector = FakeClassifier(), FakeDetector()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "data" / "app.db")
    monkeypatch.setattr(model, "load_model",
                        lambda path=model.MODEL_PATH: detector if path == model.DETECTOR_PATH else classifier)
    monkeypatch.setattr(model, "_has_face", lambda gray: False)
    uploads = {"file": None}
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: uploads["file"])
    st.cache_data.clear()
    st.cache_resource.clear()
    return App(tmp_path / "app.py", db.DB_PATH, classifier, detector, uploads, database_url, secrets)


@pytest.fixture(params=BACKENDS)
def app(request, tmp_path, monkeypatch):
    """Приложение на SQLite (как локально) и, если задан TEST_DATABASE_URL, на Postgres (как на сайте)."""
    database_url = None
    if request.param == "postgres":
        fresh_postgres().close()  # пустая база: таблицы создаст само приложение миграциями
        database_url = TEST_DATABASE_URL
    yield start_app(tmp_path, monkeypatch, database_url)
    st.cache_data.clear()
    st.cache_resource.clear()
