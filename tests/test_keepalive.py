"""Keep-alive для Supabase (.github/supabase_keepalive.py): запрос проходит, ошибки понятны и без секретов."""
import os
import subprocess
import sys

from conftest import ROOT, TEST_DATABASE_URL, needs_postgres

SCRIPT = ROOT / ".github" / "supabase_keepalive.py"


def run(database_url):
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    return subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)


@needs_postgres
def test_ping_succeeds(pgconn):
    result = run(TEST_DATABASE_URL)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "база активна" in result.stdout


def test_missing_secret_fails_with_instructions():
    result = run(None)
    assert result.returncode == 1
    assert "SUPABASE_DATABASE_URL" in result.stdout


def test_unreachable_database_fails_without_leaking_secrets():
    result = run("postgresql://postgres.someproject:TopSecret123@127.0.0.1:1/postgres")
    assert result.returncode == 1
    assert "Supabase не ответил" in result.stdout
    assert "TopSecret123" not in result.stdout + result.stderr
    assert "someproject" not in result.stdout + result.stderr
