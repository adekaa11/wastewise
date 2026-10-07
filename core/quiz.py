"""Викторина: случайные вопросы из готового банка (core/content.py → QUIZ_BANK).

Работает без интернета и без ключей API. Раньше был ещё режим «вопросы по своему тексту» через OpenAI —
убран: он требовал платный ключ, мог сломаться во время показа и позволял накручивать баллы.
Правила сортировки не меняются, поэтому вопросы один раз написаны и проверены заранее.
"""
import random

from .content import QUIZ_BANK


def random_questions(n=5):
    qs = random.sample(QUIZ_BANK, k=min(n, len(QUIZ_BANK)))
    out = []
    for q in qs:
        opts = q["options"][:]
        random.shuffle(opts)
        out.append({**q, "options": opts})
    return out
