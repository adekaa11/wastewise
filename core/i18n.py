"""Языки сайта: русский и казахский (переключатель RUS / QAZ в меню, выбор хранится в ссылке ?lang=kk).

Как устроено (как gettext): в коде тексты пишутся по-русски и оборачиваются в _("…").
_() возвращает казахский перевод из словаря KK (core/i18n_kk.py), а если перевода нет — русский текст.
Поэтому русская версия сайта и тесты на русские тексты не меняются, а пропущенный перевод не ломает
страницу. Тест tests/test_i18n.py проверяет, что у каждого _("…") в app.py и core/ui.py перевод есть.

Тексты с подстановкой: _("Осталось {n}").format(n=3) — фигурные скобки одинаковые в обоих языках.
Описания отходов и вопросы викторины — длинные, они переведены отдельно (core/content_kk.py):
waste(), waste_name(), quiz_text().

Язык хранится в st.session_state["lang"] — у каждого посетителя свой (общая переменная модуля
перемешала бы языки разных учеников: Streamlit обслуживает всех в одном процессе).
"""
import re

from .content import QUIZ_BANK, WASTE_INFO, canonical
from .content_kk import QUIZ_KK, WASTE_KK
from .i18n_kk import KK

LANGS = {"ru": "RUS", "kk": "QAZ"}
DEFAULT = "ru"


def lang():
    """Язык текущего посетителя ("ru" или "kk")."""
    try:
        import streamlit as st

        value = st.session_state.get("lang", DEFAULT)
    except Exception:  # вне Streamlit (тесты, скрипты)
        return DEFAULT
    return value if value in LANGS else DEFAULT


def pick(value):
    """Язык из параметра ссылки или переключателя; что-то другое — язык по умолчанию."""
    value = str(value or "").strip().lower()
    return value if value in LANGS else DEFAULT


def _(text, language=None):
    if (language or lang()) == "kk":
        return KK.get(text, text)
    return text


_SCENE = re.compile(r"^Похоже, в кадре (.+), а не отход\. Сфотографируйте сам предмет крупным планом\.$")


def scene(problem, language=None):
    """Сообщение проверки кадра (core/model.py → check_scene) на языке сайта, включая «в кадре кошка»."""
    if (language or lang()) != "kk":
        return problem
    match = _SCENE.match(problem or "")
    if match:
        return KK["Похоже, в кадре {what}, а не отход. Сфотографируйте сам предмет крупным планом."].format(
            what=KK.get(match.group(1), match.group(1)))
    return KK.get(problem, problem)


def waste(cls, language=None):
    """Описание типа отходов (name, where, tips, not_accepted, fact, …) на языке сайта."""
    key = canonical(cls)
    info = WASTE_INFO.get(key, {})
    if (language or lang()) == "kk" and key in WASTE_KK:
        return {**info, **WASTE_KK[key]}
    return info


def waste_name(cls, language=None):
    return waste(cls, language).get("name", cls)


# Вопросы викторины: русский текст → перевод. Варианты ответа в QUIZ_KK — в том же порядке, что в QUIZ_BANK,
# поэтому ответы ученика хранятся по-русски (их и сравниваем), а на экран выводится перевод.
_QUIZ_MAP = {}
for _q in QUIZ_BANK:
    _kk = QUIZ_KK.get(_q["q"])
    if _kk:
        _QUIZ_MAP[_q["q"]] = _kk["q"]
        _QUIZ_MAP.update(zip(_q["options"], _kk["options"]))
        _QUIZ_MAP[_q["why"]] = _kk["why"]


def quiz_text(text, language=None):
    """Вопрос, вариант ответа или пояснение викторины на языке сайта."""
    if (language or lang()) == "kk":
        return _QUIZ_MAP.get(text, KK.get(text, text))
    return text
