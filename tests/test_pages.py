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


def test_registration_logs_in_right_away(app):
    """После регистрации не нужно второй раз вводить логин и пароль."""
    app.register_and_login()
    assert any(b.label == "Выйти" for b in app.at.sidebar.button)
    assert app.at.sidebar.radio[0].options[-1] == "Профиль"


def test_user_text_is_escaped_in_html(app):
    """Имя и школа попадают в HTML рейтинга и профиля только экранированными — чужой код не выполнится."""
    app.go("Регистрация")
    for widget, value in zip(app.at.text_input, ["evil", "secret1", "<img src=x onerror=alert(1)>", "<b>Школа</b>"]):
        widget.input(value)
    app.button("Зарегистрироваться").click()
    app.run()
    for page in ["Рейтинг", "Профиль"]:
        html = " ".join(m.value for m in app.go(page).at.markdown)
        assert "<img src=x" not in html and "<b>Школа</b>" not in html
        assert "&lt;img src=x" in html
