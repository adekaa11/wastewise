"""Банк вопросов викторины: каждый вопрос корректен, повторов нет, все 7 типов отходов покрыты."""
from core.content import QUIZ_BANK
from core.quiz import random_questions


def test_every_question_is_well_formed():
    for q in QUIZ_BANK:
        assert q["q"] and q["why"], q
        assert len(q["options"]) == 4, q["q"]
        assert len(set(q["options"])) == 4, f"повтор варианта: {q['q']}"
        assert q["correct"] in q["options"], f"правильного ответа нет среди вариантов: {q['q']}"


def test_no_duplicate_questions_and_enough_of_them():
    texts = [q["q"] for q in QUIZ_BANK]
    assert len(texts) == len(set(texts))
    assert len(texts) >= 50


def test_random_questions_keep_correct_answer():
    for q in random_questions(5):
        assert q["correct"] in q["options"]
