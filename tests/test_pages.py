"""Все страницы открываются без ошибок — в том числе графики рейтинга и таблицы профиля с данными."""
from conftest import photo

PAGES = ["Главная", "Распознать отходы", "Викторина", "Рейтинг", "Профиль"]


def test_all_pages_render_with_data(app):
    app.register_and_login()
    app.go("Распознать отходы").upload(photo("orange"))  # чтобы в рейтинге и профиле были данные
    for page in PAGES:
        app.go(page)  # app.run() внутри проверяет, что исключений нет
    assert app.at.dataframe, "в профиле должна быть таблица распознаваний"


def test_sidebar_points_stay_when_photo_is_rejected(app):
    """Фильтр «не мусор» обрывает страницу через st.stop() — строка с баллами в меню не должна пропадать."""
    app.register_and_login()
    app.detector.boxes = [(0, (0, 0, 320, 240))]  # человек на весь кадр
    app.go("Распознать отходы").upload(photo("orange"))
    assert any(b.label.startswith("Это точно отход") for b in app.at.button)  # фото действительно отклонено
    assert any("баллов" in s.value for s in app.at.sidebar.success)
