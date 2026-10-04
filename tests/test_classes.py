"""7 типов отходов: описания, старые метки, тексты сайта под старую (4 класса) и новую (7) модель."""
import pytest

from conftest import NEW_CLASSES, photo
from core.content import CLASS_ALIASES, WASTE_INFO, canonical
from core.model import WASTE_LIKE

FIELDS = {"name", "emoji", "color", "where", "tips", "not_accepted", "fact"}


def test_seven_classes_with_full_advice():
    assert list(WASTE_INFO) == ["glass", "metal", "paper", "plastic", "ewaste", "organic", "other"]
    for cls, info in WASTE_INFO.items():
        assert FIELDS <= set(info), cls
        assert info["tips"] and all(t.strip() for t in info["tips"]), cls
    assert set(NEW_CLASSES.values()) == set(WASTE_INFO)  # имена классов новой модели = ключи WASTE_INFO


def test_old_and_dataset_labels_map_to_our_classes():
    assert canonical("cardboard") == "paper"  # картон теперь вместе с бумагой
    assert canonical("trash") == "other" and canonical("battery") == "ewaste" and canonical("biological") == "organic"
    assert canonical("glass") == "glass"
    assert set(CLASS_ALIASES.values()) <= set(WASTE_INFO)


def test_not_waste_filter_lets_through_food_and_electronics():
    """Человек держит телефон или банан — это не «селфи», фото пропускаем к классификатору."""
    assert {46, 55, 63, 65, 67} <= WASTE_LIKE  # банан, торт, ноутбук, пульт, телефон
    assert 0 not in WASTE_LIKE  # человек


@pytest.mark.parametrize("model, count_text", [("old", "4 типа"), ("new", "7 типов")])
def test_page_describes_what_the_model_knows(app, model, count_text):
    if model == "new":
        app.classifier.names, app.classifier.probs = NEW_CLASSES, [0.02, 0.02, 0.02, 0.86, 0.04, 0.02, 0.02]
    app.go("Распознать отходы")
    assert any(f"Модель знает {count_text}" in c for c in app.captions())


def test_new_model_prediction_shows_new_class_advice(app):
    app.classifier.names, app.classifier.probs = NEW_CLASSES, [0.02, 0.02, 0.02, 0.86, 0.04, 0.02, 0.02]
    app.go("Распознать отходы").upload(photo("orange"))
    page = " ".join(m.value for m in app.at.markdown)
    assert "Органика" in page and "компост" in page


def test_low_confidence_names_types_the_old_model_does_not_know(app):
    app.classifier.probs = [0.40, 0.35, 0.15, 0.10]  # старая модель, неуверенно
    app.go("Распознать отходы").upload(photo("orange"))
    [warning] = [w.value for w in app.at.warning if "не уверена" in w.value]
    assert "батарейки и электроника" in warning and "органика" in warning


def test_feedback_offers_all_seven_types(app):
    app.go("Распознать отходы").upload(photo("orange"))  # даже со старой моделью — так собираем датасет
    assert list(app.at.selectbox[0].options) == [info["name"] for info in WASTE_INFO.values()]
