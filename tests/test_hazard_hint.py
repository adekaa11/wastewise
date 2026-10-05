"""Батарейки и электроника: подсказка, что их сдают только в спецпункты."""
from conftest import NEW_CLASSES, photo
from core.content import hazard_hint

EWASTE_FIRST = [0.81, 0.05, 0.04, 0.03, 0.03, 0.02, 0.02]   # порядок NEW_CLASSES: ewaste, glass, metal, …
EWASTE_SECOND = [0.30, 0.02, 0.55, 0.03, 0.04, 0.03, 0.03]  # «металл 55%, но может быть батарейка 30%»


def test_hint_levels():
    assert hazard_hint([("ewaste", 0.8), ("metal", 0.1)]) == "sure"
    assert hazard_hint([("battery", 0.8)]) == "sure"  # названия из датасетов тоже понимаем
    assert hazard_hint([("metal", 0.55), ("ewaste", 0.30)]) == "maybe"
    assert hazard_hint([("metal", 0.55), ("plastic", 0.3), ("ewaste", 0.21)]) == "maybe"
    assert hazard_hint([("metal", 0.85), ("ewaste", 0.10)]) is None  # маловероятно — не пугаем
    assert hazard_hint([("plastic", 0.9), ("glass", 0.05)]) is None  # старая модель такого класса не знает


def _warnings_and_infos(app):
    return [w.value for w in app.at.warning], [i.value for i in app.at.info]


def test_site_warns_about_special_collection_points(app):
    app.classifier.names, app.classifier.probs = NEW_CLASSES, EWASTE_FIRST
    app.go("Распознать отходы").upload(photo("orange"))
    warnings, _ = _warnings_and_infos(app)
    assert any("только в спецпункт" in w and "бокс для батареек" in w for w in warnings)
    assert any("Батарейки и электроника" in m.value for m in app.at.markdown)


def test_site_reminds_when_battery_is_second_guess(app):
    app.classifier.names, app.classifier.probs = NEW_CLASSES, EWASTE_SECOND
    app.go("Распознать отходы").upload(photo("orange"))
    warnings, infos = _warnings_and_infos(app)
    assert any("Если на фото батарейка" in i for i in infos)
    assert not any("только в спецпункт" in w for w in warnings)


def test_no_hint_for_ordinary_waste(app):
    app.go("Распознать отходы").upload(photo("orange"))  # старая модель: «пластик, 90%»
    warnings, infos = _warnings_and_infos(app)
    assert not any("спецпункт" in text or "батарейка" in text for text in warnings + infos)
