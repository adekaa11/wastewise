"""Улучшение №1: кэш распознавания, уменьшение больших фото, битые файлы."""
import io
import sys
from types import SimpleNamespace

from PIL import Image

from conftest import photo
from core import model
from core.model import MAX_SIDE, load_image


def test_big_photo_is_downscaled():
    image = load_image(photo("orange", size=(4000, 3000)))
    assert max(image.size) == MAX_SIDE and image.size == (1280, 960)
    assert image.mode == "RGB"


def test_small_photo_is_untouched():
    assert load_image(photo("orange", size=(300, 200))).size == (300, 200)


def test_png_with_transparency_becomes_rgb():
    buf = io.BytesIO()
    Image.new("RGBA", (50, 40), (255, 0, 0, 128)).save(buf, "PNG")
    assert load_image(buf.getvalue()).mode == "RGB"


def test_exif_rotation_is_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # «камера повёрнута на 90°» — так сохраняют фото многие телефоны
    buf = io.BytesIO()
    Image.new("RGB", (400, 200), "orange").save(buf, "JPEG", exif=exif)
    assert load_image(buf.getvalue()).size == (200, 400)


def test_broken_file_returns_none():
    assert load_image(b"definitely not an image") is None
    assert load_image(photo("orange")[:100]) is None  # обрезанный JPEG


def test_models_do_not_rerun_on_every_click(app):
    app.go("Распознать отходы").upload(photo("orange"))
    assert (app.detector.calls, app.classifier.calls) == (1, 1)

    # любой клик = перезапуск скрипта Streamlit; раньше каждый раз заново работали обе нейросети
    app.at.selectbox[0].set_value("glass")
    app.run()
    app.run()
    assert (app.detector.calls, app.classifier.calls) == (1, 1)

    app.upload(photo("skyblue"))  # новое фото — модели работают
    assert (app.detector.calls, app.classifier.calls) == (2, 2)


def test_broken_upload_shows_message_instead_of_crash(app):
    app.go("Распознать отходы").upload(b"definitely not an image")
    assert any("Не удалось открыть файл" in e.value for e in app.at.error)
    assert app.classifier.calls == 0


def test_face_filter_skipped_when_opencv_has_no_cascade(monkeypatch):
    """OpenCV 5 убрал CascadeClassifier — проверка лица пропускается, а не роняет страницу."""
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace())
    assert model._has_face(Image.new("L", (100, 100), 200)) is False



def _scene(monkeypatch, boxes, size=(320, 240)):
    """check_scene с фальшивым детектором: boxes — [(класс COCO, рамка, уверенность), ...]."""
    from conftest import FakeDetector
    monkeypatch.setattr(model, "_has_face", lambda gray: False)  # в CI нет OpenCV
    detector = FakeDetector()
    detector.boxes = boxes
    return model.check_scene(detector, Image.new("RGB", size, "skyblue"))


def test_unsure_person_does_not_block_a_bottle(monkeypatch):
    """Смятая прозрачная бутылка на весь кадр: детектор видел «человека» на ~0.5 — фото отбрасывалось."""
    assert _scene(monkeypatch, [(0, (0, 0, 300, 240), 0.5)]) is None


def test_confident_person_still_blocks(monkeypatch):
    assert "человек" in _scene(monkeypatch, [(0, (0, 0, 300, 240), 0.9)])


def test_small_person_does_not_block(monkeypatch):
    assert _scene(monkeypatch, [(0, (0, 0, 60, 60), 0.95)]) is None  # рука или человечек на фоне


def test_weakly_seen_bottle_lets_photo_through(monkeypatch):
    assert _scene(monkeypatch, [(0, (0, 0, 300, 240), 0.9), (39, (100, 50, 200, 200), 0.3)]) is None


def test_animal_still_blocks(monkeypatch):
    assert "кошка" in _scene(monkeypatch, [(15, (0, 0, 200, 200), 0.8)])
