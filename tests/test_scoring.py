"""Улучшение №2: баллы за одно и то же фото начисляются один раз."""
import sqlite3

from conftest import photo
from core import db
from core.content import POINTS_PER_FEEDBACK, POINTS_PER_SCAN

A, B = photo("orange"), photo("skyblue")
REPEAT = "Это фото вы уже проверяли"


def test_old_database_gets_image_hash_column():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL, name TEXT NOT NULL, school TEXT DEFAULT '', points INTEGER DEFAULT 0,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE scans (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, predicted TEXT NOT NULL,
            confidence REAL NOT NULL, corrected TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO scans (user_id, predicted, confidence) VALUES (NULL, 'glass', 0.9);
    """)
    db.init_db(conn)
    db.init_db(conn)  # повторный запуск ничего не ломает
    assert "image_hash" in [r[1] for r in conn.execute("PRAGMA table_info(scans)")]
    assert db.global_stats(conn)["scans"] == 1  # старые записи на месте

    db.register_user(conn, "alice", "secret1", "Алиса")
    uid = db.authenticate(conn, "alice", "secret1")
    scan_id = db.save_scan(conn, uid, "glass", 0.9, "hash-a")
    assert db.find_scan(conn, uid, "hash-a") == (scan_id, None)
    assert db.find_scan(conn, uid + 1, "hash-a") is None  # у другого пользователя — своё


def test_alternating_two_photos_gives_points_once(app):
    app.register_and_login()
    app.go("Распознать отходы")
    start = app.points()

    app.upload(A)
    app.upload(B)
    assert app.points() - start == 2 * POINTS_PER_SCAN

    app.upload(A)  # раньше здесь снова было +10
    assert app.points() - start == 2 * POINTS_PER_SCAN
    assert any(REPEAT in c for c in app.captions())


def test_feedback_points_only_once_per_photo(app):
    app.register_and_login()
    app.go("Распознать отходы").upload(A)
    after_scan = app.points()

    app.button("Отправить исправление").click()
    app.run()
    assert app.points() - after_scan == POINTS_PER_FEEDBACK

    app.upload(B)
    app.upload(A)  # раньше кнопка снова становилась активной: +15 бесконечно
    assert app.button("Отправить исправление").disabled
    assert app.points() - after_scan == POINTS_PER_FEEDBACK + POINTS_PER_SCAN  # +10 только за новое фото B


def test_logout_and_login_does_not_reset_protection(app):
    app.register_and_login()
    app.go("Распознать отходы").upload(A)
    points = app.points()

    app.upload(None)
    app.logout()
    app.login()
    app.go("Распознать отходы").upload(A)
    assert app.points() == points
    assert any(REPEAT in c for c in app.captions())


def test_anonymous_switching_photos_does_not_inflate_stats(app):
    app.go("Распознать отходы")
    for raw in (A, B, A, B):
        app.upload(raw)
    assert len(app.scans()) == 2  # раньше было 4 записи
    assert not any(REPEAT in c for c in app.captions())  # гостю баллы не начисляются — и сообщать нечего
