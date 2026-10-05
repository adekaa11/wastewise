"""Хранилище (core/db.py): все функции, с которыми работает приложение.

Один и тот же набор тестов гоняется на каждой поддерживаемой базе (фикстура store в conftest.py).
"""
import threading

from conftest import backdate
from core import db


def _user(store, username="alice", school="Школа 1"):
    assert db.register_user(store, username, "secret1", username.title(), school) == (True, "Аккаунт создан. Теперь войдите.")
    return db.authenticate(store, username, "secret1")


def test_register_and_login(store):
    uid = _user(store)
    assert isinstance(uid, int)
    assert db.get_user(store, uid) == {"id": uid, "username": "alice", "name": "Alice", "school": "Школа 1", "points": 0}
    assert db.authenticate(store, "alice", "wrong-password") is None
    assert db.authenticate(store, "nobody", "secret1") is None
    assert db.authenticate(store, "  alice ", "secret1") == uid  # пробелы вокруг логина не мешают


def test_duplicate_login_is_rejected(store):
    _user(store)
    assert db.register_user(store, "alice", "other-pass", "Другая") == (False, "Такой логин уже занят.")


def test_duplicate_login_from_many_threads_at_once(store):
    results = []
    threads = [threading.Thread(target=lambda: results.append(db.register_user(store, "bob", "secret1", "Боб")))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(ok for ok, _ in results) == [False] * 7 + [True]


def test_points(store):
    uid = _user(store)
    db.add_points(store, uid, 10)
    db.add_points(store, uid, 5)
    db.add_points(store, None, 100)  # гость — ничего не происходит
    assert db.get_user(store, uid)["points"] == 15


def test_scans(store):
    uid = _user(store)
    first = db.save_scan(store, uid, "glass", 0.9, "hash-a")
    second = db.save_scan(store, None, "paper", 0.4, "hash-b")
    assert isinstance(first, int) and second > first

    assert db.find_scan(store, uid, "hash-a") == (first, None)
    assert db.find_scan(store, uid, "hash-b") is None  # чужое (гостевое) фото
    db.correct_scan(store, first, "plastic")
    assert db.find_scan(store, uid, "hash-a") == (first, "plastic")

    rows = db.user_scans(store, uid)
    assert [(p, round(c, 2), f) for p, c, f, _ in rows] == [("glass", 0.9, "plastic")]
    assert rows[0][3]  # дата заполняется базой


def test_quizzes_and_24h_window(store):
    uid = _user(store)
    for points in (25, 0, 15):
        db.save_quiz(store, uid, points // 5, 5, "bank", points)
    assert db.rewarded_quizzes_last_day(store, uid) == 2  # викторина без баллов не считается
    assert [row[:4] for row in db.user_quizzes(store, uid)] == [(3, 5, "bank", 15), (0, 5, "bank", 0), (5, 5, "bank", 25)]

    first_id = min(row[0] for row in store.execute("SELECT id FROM quiz_results").fetchall())
    backdate(store, "quiz_results", first_id, hours=25)
    assert db.rewarded_quizzes_last_day(store, uid) == 1


def test_leaderboards_and_stats(store):
    a = _user(store, "alice", "Школа 1")
    b = _user(store, "bob", "Школа 1")
    c = _user(store, "carl", "")
    for uid, pts in ((a, 30), (b, 20), (c, 50)):
        db.add_points(store, uid, pts)
    assert db.leaderboard_users(store) == [("Carl", "", 50), ("Alice", "Школа 1", 30), ("Bob", "Школа 1", 20)]
    assert db.leaderboard_schools(store) == [("Школа 1", 50, 2)]  # без школы в рейтинг школ не попадает

    s1 = db.save_scan(store, a, "glass", 0.9)
    db.save_scan(store, b, "glass", 0.8)
    db.correct_scan(store, s1, "metal")
    stats = db.global_stats(store)
    assert (stats["scans"], stats["users"], stats["corrected"]) == (2, 3, 1)
    assert sorted(stats["by_class"]) == [("glass", 1), ("metal", 1)]


def test_init_db_is_idempotent(store):
    uid = _user(store)
    db.init_db(store)  # повторный запуск при каждом старте сайта ничего не ломает и не стирает
    assert db.get_user(store, uid)["username"] == "alice"


def test_cascade_delete_of_user_history(store):
    uid = _user(store)
    db.save_scan(store, uid, "glass", 0.9)
    db.save_quiz(store, uid, 5, 5, "bank", 25)
    store.execute("DELETE FROM users WHERE id = ?", (uid,))
    store.commit()
    assert db.global_stats(store)["scans"] == 0


def test_user_place_totals_and_class_counts(store):
    """Профиль: место в рейтинге, сколько всего фото и викторин, что пользователь сортировал."""
    assert db.register_user(store, "alice", "secret1", "Alice", "")[0]
    assert db.register_user(store, "bobby", "secret1", "Bob", "")[0]
    alice, bob = db.authenticate(store, "alice", "secret1"), db.authenticate(store, "bobby", "secret1")
    db.add_points(store, bob, 30)
    db.add_points(store, alice, 30)  # те же баллы — выше тот, кто зарегистрировался раньше
    assert db.user_place(store, alice) == 1 and db.user_place(store, bob) == 2
    for i in range(25):  # больше, чем показывает история (20)
        db.save_scan(store, alice, "plastic" if i % 5 else "cardboard", 0.9, f"h{i}")
    db.save_quiz(store, alice, 5, 5, "bank", 25)
    assert db.user_totals(store, alice) == (25, 1)
    assert dict(db.user_class_counts(store, alice)) == {"plastic": 20, "cardboard": 5}
    assert db.leaderboard_users(store, with_ids=True)[0] == ("Alice", "", 30, alice)
