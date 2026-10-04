"""Где приложение хранит данные: DATABASE_URL из st.secrets → Postgres/Supabase, без него — SQLite."""
import streamlit as st

from conftest import start_app
from core import db


def test_without_database_url_uses_local_sqlite(tmp_path, monkeypatch):
    app = start_app(tmp_path, monkeypatch)
    app.register_and_login()
    assert db.DB_PATH.exists()  # data/app.db, как раньше
    assert app.points() == 0
    st.cache_resource.clear()


def test_unreachable_database_shows_message_instead_of_crash(tmp_path, monkeypatch):
    # Supabase на паузе / неверный пароль / нет сети — здесь просто закрытый порт
    app = start_app(tmp_path, monkeypatch, "postgresql://postgres:secret@127.0.0.1:1/postgres")
    assert any("Не удалось подключиться к базе данных" in e.value for e in app.at.error)
    assert not any("secret" in e.value for e in app.at.error)  # пароль на страницу не попадает
    assert not db.DB_PATH.exists()  # и тихо переключиться на SQLite сайт тоже не должен
    st.cache_resource.clear()


# ---------- строка в логе при старте: какая база используется ----------

import logging  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

import pytest  # noqa: E402

from conftest import TEST_DATABASE_URL, fresh_postgres, needs_postgres  # noqa: E402
from core import pg  # noqa: E402


class _Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def site_log():
    handler = _Records()
    logging.getLogger("wastewise").addHandler(handler)
    yield handler.messages
    logging.getLogger("wastewise").removeHandler(handler)


def test_startup_log_says_sqlite(tmp_path, monkeypatch, site_log):
    start_app(tmp_path, monkeypatch)
    [line] = [m for m in site_log if m.startswith("База данных:")]
    assert "SQLite" in line and "DATABASE_URL" in line
    st.cache_resource.clear()


@needs_postgres
def test_startup_log_says_postgres_without_secrets(tmp_path, monkeypatch, site_log):
    fresh_postgres().close()
    start_app(tmp_path, monkeypatch, TEST_DATABASE_URL)
    [line] = [m for m in site_log if m.startswith("База данных:")]
    assert line.startswith("База данных: Postgres ")
    parsed = urlparse(TEST_DATABASE_URL)
    assert parsed.hostname not in line and TEST_DATABASE_URL not in line
    if parsed.password:
        assert parsed.password not in line
    st.cache_resource.clear()


def test_misplaced_secret_is_named_but_not_shown(tmp_path, monkeypatch, site_log):
    secret = "postgresql://postgres.abcdefghijklmnop:TopSecret123@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    start_app(tmp_path, monkeypatch, secrets={"connections": {"supabase": {"url": secret}}})
    hints = [m for m in site_log if "под именем" in m]
    assert hints and "connections.supabase.url" in hints[0]
    assert not any("TopSecret123" in m or "abcdefghijklmnop" in m for m in site_log)
    st.cache_resource.clear()


@pytest.mark.parametrize("url, text", [
    ("postgresql://postgres.ref:pw@aws-0-eu-central-1.pooler.supabase.com:5432/postgres", "Supabase (Postgres) через Session pooler"),
    ("postgresql://postgres.ref:pw@aws-0-eu-central-1.pooler.supabase.com:6543/postgres", "Supabase (Postgres) через Transaction pooler"),
    ("postgresql://postgres:pw@db.abcdefghijklmnop.supabase.co:5432/postgres", "Supabase (Postgres), прямое подключение"),
    ("postgresql://postgres@127.0.0.1:5432/test", "Postgres"),
])
def test_connection_description_has_no_secrets(url, text):
    assert pg.describe_url(url) == text
    assert "pw" not in text and "ref" not in text
