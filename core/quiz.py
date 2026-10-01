"""Викторина: готовые вопросы (работают офлайн) и генерация вопросов через OpenAI."""
import json
import os
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


def ai_available():
    return bool(os.getenv("OPENAI_API_KEY"))


def generate_questions(text, level, n=3):
    """Генерирует n вопросов по тексту. Бросает исключение, если что-то пошло не так."""
    from openai import OpenAI

    client = OpenAI()  # ключ берётся из переменной окружения OPENAI_API_KEY
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    prompt = f"""Составь викторину из {n} вопросов по тексту ниже. Уровень сложности: {level}.
Вопросы и ответы — на русском языке, строго по содержанию текста, без повторов.
Верни ТОЛЬКО JSON такого вида:
{{"questions": [{{"q": "вопрос", "options": ["вариант 1", "вариант 2", "вариант 3", "вариант 4"],
"correct": "точный текст правильного варианта", "why": "короткое объяснение"}}]}}

Текст:
{text}"""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},  # модель обязана вернуть корректный JSON
        temperature=0.7,
    )
    data = json.loads(resp.choices[0].message.content)
    questions = [
        q for q in data.get("questions", [])
        if q.get("q") and len(q.get("options", [])) >= 2 and q.get("correct") in q["options"]
    ]
    if not questions:
        raise ValueError("ИИ вернул вопросы в неправильном формате")
    return questions[:n]
