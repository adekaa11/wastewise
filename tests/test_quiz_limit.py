"""Лимит: баллы за викторину — только за первые 3 викторины за последние 24 часа."""
import sqlite3

from core import db
from core.content import POINTS_PER_CORRECT_ANSWER, QUIZ_REWARDS_PER_DAY

FULL = 5 * POINTS_PER_CORRECT_ANSWER  # 5 вопросов, все правильно


def play_quiz(app, correct=True):
    """Пройти готовую викторину: все ответы правильные или все неправильные. Вернуть прирост баллов."""
    before = app.points()
    app.button("Начать новую викторину (5 вопросов)").click()
    app.run()
    quiz = app.at.session_state["quiz"]
    for i, q in enumerate(quiz["questions"]):
        answer = q["correct"] if correct else next(o for o in q["options"] if o != q["correct"])
        app.at.radio(key=f"q_{quiz['uid']}_{i}").set_value(answer)
    app.button("Проверить ответы").click()
    app.run()
    return app.points() - before


def test_points_only_for_first_three_quizzes_a_day(app):
    app.register_and_login()
    app.go("Викторина")
    gains = [play_quiz(app) for _ in range(QUIZ_REWARDS_PER_DAY + 1)]
    assert gains == [FULL] * QUIZ_REWARDS_PER_DAY + [0]  # раньше: +25 бесконечно
    assert any("лимит исчерпан" in i.value for i in app.at.info)
    assert any("осталось: 0 из 3" in c for c in app.captions())


def test_zero_score_quiz_does_not_use_up_the_limit(app):
    app.register_and_login()
    app.go("Викторина")
    for _ in range(QUIZ_REWARDS_PER_DAY):
        assert play_quiz(app, correct=False) == 0
    assert play_quiz(app) == FULL


def test_limit_is_a_rolling_24_hours(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    conn = db.get_conn()
    db.init_db(conn)
    db.register_user(conn, "alice", "secret1", "Алиса")
    uid = db.authenticate(conn, "alice", "secret1")
    for points in (25, 25, 25, 0):
        db.save_quiz(conn, uid, points // POINTS_PER_CORRECT_ANSWER, 5, "bank", points)
    assert db.rewarded_quizzes_last_day(conn, uid) == 3  # викторина с 0 баллов не считается

    conn.execute("UPDATE quiz_results SET date = datetime('now', '-25 hours') WHERE id = 1")
    conn.commit()
    assert db.rewarded_quizzes_last_day(conn, uid) == 2  # старше суток — освободилось место


def test_old_database_gets_points_column_with_backfill():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE quiz_results (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            score INTEGER NOT NULL, total INTEGER NOT NULL, mode TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO quiz_results (user_id, score, total, mode) VALUES (1, 4, 5, 'bank');
    """)
    db.init_db(conn)
    db.init_db(conn)
    # до лимита баллы начислялись всегда — в истории профиля они не должны стать нулём
    assert db.user_quizzes(conn, 1)[0][:4] == (4, 5, "bank", 4 * POINTS_PER_CORRECT_ANSWER)
