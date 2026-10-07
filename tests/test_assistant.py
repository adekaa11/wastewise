"""ИИ-помощник «Спросить ИИ»: настоящий OpenAI не вызывается — вместо него поддельный клиент."""
import json
from types import SimpleNamespace

import pytest

from core import assistant
from conftest import start_app


class FakeOpenAI:
    """Вместо openai.OpenAI(): отвечает заданным JSON и считает вызовы."""

    def __init__(self, reply=None, fail=False):
        self.calls, self.fail, self.last_messages = 0, fail, None
        self.reply = reply or {"type": "plastic", "item": "крышка", "answer": "Это пластик <b>PP</b>.",
                               "steps": ["Сполосните", "Сдайте с пластиком"]}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        self.last_messages = kwargs["messages"]
        if self.fail:
            raise RuntimeError("нет денег на ключе")
        content = self.reply if isinstance(self.reply, str) else json.dumps(self.reply, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture(autouse=True)
def clean_state():
    assistant.reset()
    yield
    assistant.reset()


def test_answer_is_parsed_and_user_text_is_passed_as_data():
    fake = FakeOpenAI()
    result, cached = assistant.ask("Крышка от йогурта", user_id=1, client=fake)
    assert not cached and result["type"] == "plastic" and result["steps"] == ["Сполосните", "Сдайте с пластиком"]
    assert fake.last_messages[1]["content"] == "Предмет: <<<Крышка от йогурта>>>"


def test_unknown_type_and_extra_fields_are_cleaned():
    fake = FakeOpenAI({"type": "ignore previous instructions", "answer": "x" * 2000,
                       "steps": ["a", "", "b", "c", "d"], "secret": "!"})
    result, _ = assistant.ask("что-то", 1, client=fake)
    assert result["type"] == "unknown"
    assert len(result["answer"]) == 600 and result["steps"] == ["a", "b", "c"]
    assert set(result) == {"type", "item", "answer", "steps"}


def test_same_question_comes_from_cache_and_is_free():
    fake = FakeOpenAI()
    assistant.ask("Крышка от йогурта", 1, client=fake)
    result, cached = assistant.ask("  крышка  от ЙОГУРТА? ", 2, client=fake)
    assert cached and fake.calls == 1 and assistant.used_today(2) == 0


def test_daily_limit_per_user():
    fake = FakeOpenAI()
    for i in range(assistant.PER_USER_PER_DAY):
        assistant.ask(f"предмет {i}", 1, client=fake)
    with pytest.raises(assistant.AssistantError, match="закончились"):
        assistant.ask("ещё один", 1, client=fake)
    assert assistant.ask("ещё один", 2, client=fake)  # у другого пользователя свой лимит


def test_global_limit(monkeypatch):
    monkeypatch.setattr(assistant, "GLOBAL_PER_DAY", 2)
    fake = FakeOpenAI()
    assistant.ask("один", 1, client=fake)
    assistant.ask("два", 2, client=fake)
    with pytest.raises(assistant.AssistantError, match="перегружен"):
        assistant.ask("три", 3, client=fake)


def test_failed_request_does_not_use_up_limit():
    with pytest.raises(assistant.AssistantError, match="не отвечает"):
        assistant.ask("батарейка", 1, client=FakeOpenAI(fail=True))
    with pytest.raises(assistant.AssistantError):
        assistant.ask("батарейка", 1, client=FakeOpenAI(reply="это не json"))
    assert assistant.used_today(1) == 0


@pytest.mark.parametrize("text", ["", "a", "x" * (assistant.MAX_LEN + 1)])
def test_bad_question_length_is_rejected_without_api_call(text):
    fake = FakeOpenAI()
    with pytest.raises(assistant.AssistantError):
        assistant.ask(text, 1, client=fake)
    assert fake.calls == 0


# ---------- страница сайта ----------

def test_page_is_off_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = start_app(tmp_path, monkeypatch)
    app.register_and_login()
    app.go("Спросить ИИ")
    assert any("выключен" in i.value for i in app.at.info)
    assert not app.at.text_input


def test_page_asks_for_login(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    app = start_app(tmp_path, monkeypatch)
    app.go("Спросить ИИ")
    assert any("Войдите" in i.value for i in app.at.info)


def test_page_shows_escaped_answer_and_gives_no_points(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake = FakeOpenAI()
    monkeypatch.setattr(assistant, "_make_client", lambda: fake)
    app = start_app(tmp_path, monkeypatch)
    app.register_and_login()
    before = app.points()
    app.go("Спросить ИИ")
    app.at.text_input[0].input("крышка от йогурта")
    app.at.button[0].click()
    app.run()
    html = " ".join(m.value for m in app.at.markdown)
    assert "Это пластик &lt;b&gt;PP&lt;/b&gt;." in html and "<b>PP</b>" not in html
    assert "Сполосните" in html
    assert fake.calls == 1 and app.points() == before
    assert any(f"{assistant.PER_USER_PER_DAY - 1} из {assistant.PER_USER_PER_DAY}" in c for c in app.captions())
