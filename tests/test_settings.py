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
