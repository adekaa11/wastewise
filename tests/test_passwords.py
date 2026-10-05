"""Пароли хранятся только как хэш — на обеих базах (SQLite и Postgres/Supabase)."""
import hashlib
import re

import pytest

from conftest import needs_postgres
from core import db

PBKDF2 = re.compile(r"^pbkdf2\$[0-9a-f]{32}\$[0-9a-f]{64}$")  # pbkdf2$<соль 16 байт>$<sha256>


def _stored(store, username):
    return store.execute("SELECT password FROM users WHERE username = ?", (username,)).fetchone()[0]


def test_password_is_stored_as_salted_pbkdf2_hash(store):
    db.register_user(store, "alice", "secret1", "Алиса", "Школа 1")
    stored = _stored(store, "alice")
    assert PBKDF2.match(stored)
    assert "secret1" not in stored
    row = store.execute("SELECT * FROM users WHERE username = ?", ("alice",)).fetchone()
    assert "secret1" not in str(row)  # открытого пароля нет ни в одном столбце
    assert db.verify_password(stored, "secret1") and not db.verify_password(stored, "secret2")


def test_same_password_gives_different_hashes(store):
    """Соль: у двух учеников с одинаковым паролем хэши разные — готовые таблицы подбора не помогут."""
    db.register_user(store, "alice", "qwerty123", "Алиса")
    db.register_user(store, "bob", "qwerty123", "Боб")
    assert _stored(store, "alice") != _stored(store, "bob")


def test_legacy_sha256_hash_is_upgraded_on_login(store):
    legacy = hashlib.sha256(b"oldpass1").hexdigest()  # так хранила пароли версия 1
    store.execute("INSERT INTO users (username, password, name) VALUES (?, ?, ?)", ("old", legacy, "Старый"))
    store.commit()

    assert db.authenticate(store, "old", "wrongpass") is None
    assert _stored(store, "old") == legacy  # неверный пароль ничего не меняет

    uid = db.authenticate(store, "old", "oldpass1")
    assert uid is not None
    assert PBKDF2.match(_stored(store, "old"))  # теперь PBKDF2 с солью
    assert db.authenticate(store, "old", "oldpass1") == uid  # и вход по-прежнему работает


@needs_postgres
def test_supabase_refuses_plain_text_password(pgconn):
    """Ограничение CHECK в Supabase: даже ошибка в коде не сохранит пароль открытым текстом."""
    with pytest.raises(pgconn.IntegrityError):  # CheckViolation — разновидность IntegrityError
        pgconn.execute("INSERT INTO users (username, password, name) VALUES (?, ?, ?)", ("x", "secret1", "X"))
