"""Казахский перевод: у каждого текста интерфейса есть перевод, подстановки {…} совпадают, викторина цела."""
import ast
import re
from pathlib import Path

import pytest

from core import i18n
from core.assistant import AssistantError
from core.content import LEVELS, POINT_KINDS, QUIZ_BANK, WASTE_INFO, HAZARD_MAYBE, HAZARD_SURE
from core.content_kk import QUIZ_KK, WASTE_KK
from core.i18n_kk import KK
from core.model import NOT_WASTE

ROOT = Path(__file__).resolve().parent.parent
FIELDS = re.compile(r"{(\w*)}")


def literals():
    """Все тексты вида _("…") в app.py и core/ui.py."""
    found = set()
    for name in ("app.py", "core/ui.py"):
        for node in ast.walk(ast.parse((ROOT / name).read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


def test_every_interface_text_is_translated():
    missing = sorted(t for t in literals() if t not in KK)
    assert not missing, f"нет казахского перевода: {missing}"


def test_dynamic_texts_are_translated():
    """Тексты, которые попадают в _() не буквально: меню, уровни, пункты карты, сообщения базы и ИИ."""
    dynamic = ["Главная", "Распознать отходы", "Спросить ИИ", "Викторина", "Рейтинг", "Эко-карта",
               "Панель учителя", "Профиль", "Вход", "Регистрация", HAZARD_SURE, HAZARD_MAYBE,
               "тип", "участник", "распознавание", "викторина", "фото",
               "Логин должен быть не короче 3 символов.", "Пароль должен быть не короче 6 символов.",
               "Такой логин уже занят.", "Аккаунт создан. Теперь войдите.",
               "Укажите название пункта.", "Неизвестный тип пункта.", "Координаты должны быть числами.",
               "Проверьте координаты: широта от -90 до 90, долгота от -180 до 180.", "Пункт добавлен на карту.",
               "Дата", "Класс", "Бак", "Итоговый тип", "Ответ модели", "Исправлено", "Верно у бака", "да", "нет"]
    dynamic += [title for _, title, _ in LEVELS] + list(NOT_WASTE.values())
    dynamic += [k["name"] for k in POINT_KINDS.values()] + [k["search"] for k in POINT_KINDS.values()]
    assert not [t for t in dynamic if t not in KK]


def test_placeholders_match():
    for ru, kk in KK.items():
        assert sorted(FIELDS.findall(ru)) == sorted(FIELDS.findall(kk)), ru
    assert "<mark>" in KK["Сфотографируй мусор — узнай, <mark>куда</mark> его выбросить"]


def test_assistant_errors_are_translatable():
    """Сообщения ИИ-помощника — шаблоны: сайт переводит их как _(template).format(**params)."""
    source = (ROOT / "core" / "assistant.py").read_text(encoding="utf-8")
    templates = re.findall(r'AssistantError\(\s*((?:"[^"]*"\s*)+)', source)
    assert len(templates) >= 7
    for chunk in templates:
        text = "".join(re.findall(r'"([^"]*)"', chunk))
        assert text in KK, text
    err = AssistantError("Слишком длинно: опишите предмет короче, до {n} символов.", n=200)
    assert str(err).endswith("до 200 символов.")
    assert "200" in KK[err.template].format(**err.params)


def test_waste_descriptions_are_complete():
    for key, info in WASTE_INFO.items():
        kk = WASTE_KK[key]
        assert {"name", "where", "tips", "not_accepted", "fact"} <= set(kk)
        assert len(kk["tips"]) == len(info["tips"]), key
    assert i18n.waste("cardboard", "kk")["name"] == "Қағаз және картон"  # старые имена тоже
    assert i18n.waste("glass", "kk")["color"] == WASTE_INFO["glass"]["color"]  # цвет общий
    assert i18n.waste_name("glass", "ru") == "Стекло"


def test_every_quiz_question_is_translated_option_by_option():
    for q in QUIZ_BANK:
        kk = QUIZ_KK[q["q"]]
        assert kk["q"] and kk["why"]
        assert len(kk["options"]) == 4 and len(set(kk["options"])) == 4, q["q"]
        # перевод правильного ответа — на том же месте, что и в русском варианте
        right = kk["options"][q["options"].index(q["correct"])]
        assert i18n.quiz_text(q["correct"], "kk") in kk["options"]
        assert right
    assert i18n.quiz_text(QUIZ_BANK[0]["q"], "ru") == QUIZ_BANK[0]["q"]


def test_same_russian_option_has_one_translation():
    """Один и тот же русский вариант в разных вопросах переводится одинаково — иначе подпись «прыгала» бы."""
    seen = {}
    for q in QUIZ_BANK:
        for ru, kk in zip(q["options"], QUIZ_KK[q["q"]]["options"]):
            seen.setdefault(ru, set()).add(kk)
    assert not {ru: kk for ru, kk in seen.items() if len(kk) > 1}


@pytest.mark.parametrize("problem, expected", [
    ("Похоже, в кадре кошка, а не отход. Сфотографируйте сам предмет крупным планом.", "мысық"),
    ("Снимок слишком тёмный — включите свет или поднесите предмет к окну.", "қараңғы"),
])
def test_scene_messages(problem, expected):
    assert expected in i18n.scene(problem, "kk")
    assert i18n.scene(problem, "ru") == problem


def test_pick_language():
    assert i18n.pick("KK") == "kk"
    assert i18n.pick("en") == "ru" and i18n.pick(None) == "ru"
