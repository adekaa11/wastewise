"""Postgres/Supabase (core/pg.py): миграции, защита таблиц, обрыв соединения, строка подключения.

Тесты с базой запускаются, если задан TEST_DATABASE_URL (в CI — контейнер postgres).
Проверки строки подключения работают всегда.
"""
import threading

import pytest

from conftest import TEST_DATABASE_URL, fresh_postgres, needs_postgres
from core import db, pg


@needs_postgres
def test_migrations_are_recorded_and_not_reapplied(pgconn):
    versions = [row[0] for row in pgconn.execute("SELECT version FROM schema_migrations")]
    assert versions == sorted(p.stem for p in pg.MIGRATIONS_DIR.glob("*.sql"))
    assert pgconn.apply_migrations() == []  # при следующем запуске сайта — ничего нового
    tables = {row[0] for row in pgconn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert {"users", "scans", "quiz_results", "schema_migrations"} <= tables


@needs_postgres
def test_tables_are_closed_for_supabase_api_roles(pgconn):
    """RLS без политик: роль вроде anon из REST API Supabase не видит ни одной строки, даже с правом SELECT."""
    db.register_user(pgconn, "alice", "secret1", "Алиса")
    pgconn.execute("DROP ROLE IF EXISTS ww_api_test")
    pgconn.execute("CREATE ROLE ww_api_test NOLOGIN")
    try:
        pgconn.execute("GRANT SELECT ON users TO ww_api_test")
        pgconn.execute("SET ROLE ww_api_test")
        assert pgconn.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        pgconn.execute("RESET ROLE")
        assert pgconn.execute("SELECT count(*) FROM users").fetchone()[0] == 1  # владелец (приложение) видит
        rls = dict(pgconn.execute(
            "SELECT relname, relrowsecurity FROM pg_class WHERE relname IN "
            "('users', 'scans', 'quiz_results', 'schema_migrations')").fetchall())
        assert rls == {"users": True, "scans": True, "quiz_results": True, "schema_migrations": True}
    finally:
        pgconn.execute("RESET ROLE")
        pgconn.execute("DROP OWNED BY ww_api_test")
        pgconn.execute("DROP ROLE ww_api_test")


@needs_postgres
def test_reconnects_after_connection_is_dropped(pgconn):
    """Supabase перезапустился / сеть мигнула: следующий запрос сам переподключается."""
    db.register_user(pgconn, "alice", "secret1", "Алиса")
    uid = db.authenticate(pgconn, "alice", "secret1")
    killer = db.get_conn(TEST_DATABASE_URL)
    killer.execute("SELECT pg_terminate_backend(?)", (pgconn._conn.info.backend_pid,))
    killer.close()

    db.add_points(pgconn, uid, 10)  # раньше здесь была бы ошибка «server closed the connection»
    assert db.get_user(pgconn, uid)["points"] == 10


@needs_postgres
def test_question_marks_and_percents_in_data(pgconn):
    """«?» и «%» в данных не путаются с подстановкой параметров."""
    assert db.register_user(pgconn, "100%?", "pa%s?ss", "Имя % ?", "Школа №5 (100%)")[0]
    uid = db.authenticate(pgconn, "100%?", "pa%s?ss")
    assert db.get_user(pgconn, uid)["school"] == "Школа №5 (100%)"
    assert db.leaderboard_schools(pgconn) == [("Школа №5 (100%)", 0, 1)]


@needs_postgres
def test_parallel_visitors_on_one_connection(pgconn):
    db.register_user(pgconn, "alice", "secret1", "Алиса")
    uid = db.authenticate(pgconn, "alice", "secret1")
    errors = []

    def visitor(t):
        try:
            for i in range(25):
                db.add_points(pgconn, uid, 1)
                db.correct_scan(pgconn, db.save_scan(pgconn, uid, "glass", 0.5, f"{t}-{i}"), "metal")
                db.global_stats(pgconn)
        except Exception as e:
            errors.append(repr(e))

    threads = [threading.Thread(target=visitor, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert db.get_user(pgconn, uid)["points"] == 200
    assert db.global_stats(pgconn)["corrected"] == 200


# ---------- строка подключения (без базы) ----------

POOLER = "postgresql://postgres.abcdefghijklmnop:secret@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"


def test_session_pooler_url_gets_ssl():
    assert pg._connect_options(POOLER)["sslmode"] == "require"
    assert "sslmode" not in pg._connect_options(POOLER + "?sslmode=verify-full")  # указано — не трогаем
    assert "sslmode" not in pg._connect_options("postgresql://postgres@127.0.0.1:5432/test")


@pytest.mark.parametrize("url, words", [
    ("postgresql://postgres:secret@db.abcdefghijklmnop.supabase.co:5432/postgres", "IPv6"),
    (POOLER.replace(":5432", ":6543"), "Session pooler"),
    (POOLER.replace("secret", "[YOUR-PASSWORD]"), "[YOUR-PASSWORD]"),
    (POOLER, "пароль"),
])
def test_connection_hints(url, words):
    assert words in pg.connection_hint(url)


def test_no_hint_for_ordinary_postgres():
    assert pg.connection_hint("postgresql://postgres@127.0.0.1:5432/test") is None


@needs_postgres
def test_migration_creates_private_feedback_bucket_in_supabase():
    """В Supabase есть таблица storage.buckets — миграция создаёт там приватный бакет feedback."""
    conn = fresh_postgres()
    try:
        conn.execute("DROP SCHEMA IF EXISTS storage CASCADE")
        conn.execute("CREATE SCHEMA storage")  # как в Supabase (упрощённо)
        conn.execute("CREATE TABLE storage.buckets (id TEXT PRIMARY KEY, name TEXT NOT NULL, public BOOLEAN DEFAULT false)")
        db.init_db(conn)
        assert conn.execute("SELECT id, public FROM storage.buckets").fetchall() == [("feedback", False)]
        assert "feedback_path" in [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'scans'")]
    finally:
        conn.execute("DROP SCHEMA IF EXISTS storage CASCADE")
        conn.close()
