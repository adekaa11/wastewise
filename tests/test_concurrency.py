"""Улучшение №3: одна база и одни модели на всех посетителей — работа по очереди."""
import threading
import time

from PIL import Image

from conftest import FakeClassifier
from core import db, model


def _run_threads(target, n):
    errors = []

    def wrapped(i):
        try:
            target(i)
        except Exception as e:  # в старом коде здесь были DatabaseError / IntegrityError
            errors.append(repr(e))

    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def _shared_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    conn = db.get_conn()
    db.init_db(conn)
    return conn


def test_parallel_users_do_not_break_database(tmp_path, monkeypatch):
    conn = _shared_conn(tmp_path, monkeypatch)
    db.register_user(conn, "alice", "secret1", "Алиса", "Школа 1")
    uid = db.authenticate(conn, "alice", "secret1")
    rounds, threads = 150, 16

    def visitor(t):
        for i in range(rounds):
            db.add_points(conn, uid, 1)
            scan_id = db.save_scan(conn, uid, "glass", 0.5, f"{t}-{i}")
            db.correct_scan(conn, scan_id, "metal")
            db.global_stats(conn)
            db.leaderboard_users(conn)

    assert _run_threads(visitor, threads) == []
    assert db.get_user(conn, uid)["points"] == rounds * threads  # ни один балл не потерян
    assert db.global_stats(conn)["scans"] == rounds * threads


def test_same_login_registered_twice_at_once(tmp_path, monkeypatch):
    conn = _shared_conn(tmp_path, monkeypatch)
    results = []
    errors = _run_threads(lambda i: results.append(db.register_user(conn, "bob", "secret1", "Боб")), 8)
    assert errors == []  # раньше: необработанный IntegrityError → красная ошибка на странице
    assert sum(ok for ok, _ in results) == 1
    assert all(msg == "Такой логин уже занят." for ok, msg in results if not ok)


def test_failed_query_releases_lock_and_rolls_back(tmp_path, monkeypatch):
    conn = _shared_conn(tmp_path, monkeypatch)
    try:
        db.save_scan(conn, None, None, 0.5)  # predicted NOT NULL → ошибка внутри замка
    except Exception:
        pass
    # замок свободен: другой поток спокойно пишет в базу
    assert _run_threads(lambda i: db.save_scan(conn, None, "glass", 0.5), 4) == []
    assert db.global_stats(conn)["scans"] == 4


def test_model_is_never_called_from_two_threads_at_once():
    active, peak, lock = [0], [0], threading.Lock()

    class SlowClassifier(FakeClassifier):
        def predict(self, image, **kwargs):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            with lock:
                active[0] -= 1
            return super().predict(image, **kwargs)

    clf = SlowClassifier()
    image = Image.new("RGB", (64, 64), "orange")
    assert _run_threads(lambda i: model.classify(clf, image), 8) == []
    assert clf.calls == 8 and peak[0] == 1
