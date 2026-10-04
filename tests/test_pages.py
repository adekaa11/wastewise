"""Все страницы открываются без ошибок — в том числе графики рейтинга и таблицы профиля с данными."""
from conftest import photo

PAGES = ["Главная", "Распознать отходы", "Викторина", "Рейтинг", "Профиль"]


def test_all_pages_render_with_data(app):
    app.register_and_login()
    app.go("Распознать отходы").upload(photo("orange"))  # чтобы в рейтинге и профиле были данные
    for page in PAGES:
        app.go(page)  # app.run() внутри проверяет, что исключений нет
    assert app.at.dataframe, "в профиле должна быть таблица распознаваний"
