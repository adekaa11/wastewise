"""Назначить роль пользователю: учитель видит отчёт своей школы, администратор — все школы и эко-карту.

Роль ставится только отсюда (или SQL в Supabase) — на сайте её выбрать нельзя, иначе любой стал бы «учителем».

    python -m core.roles teacher <логин> <код_школы>   # код как в QR: nis_astana
    python -m core.roles admin <логин>
    python -m core.roles student <логин>                # снять роль

База — та же, что у сайта: DATABASE_URL из .env / окружения, без него — локальный data/app.db.
"""
import os
import sys

from dotenv import load_dotenv

from . import db
from .qr import valid_school_id


def main(argv):
    if len(argv) < 2 or argv[0] not in db.ROLES:
        print(__doc__)
        return 2
    role, username = argv[0], argv[1]
    school_id = argv[2].strip().lower() if len(argv) > 2 else None
    if role == "teacher" and not school_id:
        print("Для учителя укажите код школы, например: python -m core.roles teacher ivanova nis_astana")
        return 2
    if school_id and not valid_school_id(school_id):
        print("Код школы: латиница, цифры, _ и -, от 2 до 40 символов (например nis_astana).")
        return 2
    load_dotenv()
    conn = db.get_conn(os.getenv("DATABASE_URL"))
    db.init_db(conn)
    if not db.set_role(conn, username, role, school_id):
        print(f"Пользователь «{username}» не найден.")
        return 1
    print(f"Готово: {username} → {role}" + (f", школа {school_id}" if school_id else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
