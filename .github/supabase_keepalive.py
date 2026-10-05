"""Keep-alive для бесплатного Supabase: один простой запрос к таблице users.

Бесплатный проект Supabase ставится на паузу после недели без запросов. Этот скрипт
запускается из .github/workflows/supabase-keepalive.yml раз в 2 дня.
Строка подключения — из переменной DATABASE_URL (в workflow её задаёт секрет SUPABASE_DATABASE_URL).
В лог не попадают ни пароль, ни адрес базы: логи Actions могут быть видны всем.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.pg import PostgresConnection, connection_hint  # noqa: E402  те же настройки подключения, что у сайта


def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("::error::Не задан секрет SUPABASE_DATABASE_URL: Settings → Secrets and variables → Actions "
              "→ New repository secret. Подробно: docs/SUPABASE.md")
        return 1
    try:
        conn = PostgresConnection(url)
        try:
            conn.execute("SELECT 1 FROM users LIMIT 1").fetchall()
        finally:
            conn.close()
    except Exception as error:
        print(f"::error::Supabase не ответил ({type(error).__name__}). {connection_hint(url) or ''}".strip())
        if type(error).__name__ == "UndefinedTable":
            print("Таблиц ещё нет: откройте сайт один раз — приложение создаст их само (или см. docs/SUPABASE.md).")
        return 1
    print("Supabase ответил — база активна.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
