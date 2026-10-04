"""Оценка моделей (train/evaluate.py): точность по классам, старая vs новая, правило «не хуже на старых»."""
from types import SimpleNamespace

import pytest
from PIL import Image

from conftest import NEW_CLASSES, OLD_CLASSES, _List
from train import evaluate

COLORS = {"glass": (0, 200, 0), "metal": (150, 150, 150), "paper": (250, 250, 240), "plastic": (0, 0, 220),
          "ewaste": (200, 0, 0), "organic": (120, 80, 0), "other": (40, 40, 40)}


class ColorModel:
    """Поддельная модель: «узнаёт» класс по цвету фото; mistakes — какие классы с какой путает."""

    def __init__(self, names, mistakes=None):
        self.names = names
        self.mistakes = mistakes or {}

    def predict(self, image, **kwargs):
        pixel = image.convert("RGB").getpixel((0, 0))
        truth = min(COLORS, key=lambda c: sum((a - b) ** 2 for a, b in zip(COLORS[c], pixel)))
        answer = self.mistakes.get(truth, truth)
        if answer not in self.names.values():
            answer = next(iter(self.names.values()))  # класса не знает — отвечает что-то из своих
        probs = [0.9 if name == answer else 0.1 / (len(self.names) - 1) for name in self.names.values()]
        return [SimpleNamespace(probs=SimpleNamespace(data=_List(probs)), names=self.names)]


@pytest.fixture
def test_dir(tmp_path):
    for cls, color in COLORS.items():
        for i, source in enumerate(["trashnet", "realwaste", "realwaste", "ours"]):
            path = tmp_path / cls / f"{source}__{cls}{i}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (32, 32), color).save(path)
    return tmp_path


def test_per_class_accuracy_old_vs_new(test_dir):
    samples = evaluate.load_samples(test_dir)
    old = ColorModel(OLD_CLASSES, mistakes={"metal": "plastic"})  # старая путает металл с пластиком
    new = ColorModel(NEW_CLASSES)
    result = evaluate.evaluate(old, new, samples)
    assert result["classes"]["metal"] == {"old": (0, 4), "new": (4, 4), "photos": 4}
    assert result["classes"]["glass"]["old"] == (4, 4)
    assert result["classes"]["ewaste"]["old"] is None  # старая модель такого класса не знает
    assert result["guard"] == ["glass", "metal", "paper", "plastic"]
    assert result["old_classes_total"] == {"old": (12, 16), "new": (16, 16)}
    assert result["failures"] == []
    text = evaluate.format_report(result)
    assert "| Батарейки и электроника | 4 | — | 100.0% (4/4) |" in text and "✅" in text


def test_regression_on_old_class_is_reported(test_dir):
    samples = evaluate.load_samples(test_dir)
    old = ColorModel(OLD_CLASSES)
    new = ColorModel(NEW_CLASSES, mistakes={"glass": "other"})  # новая стала путать стекло с «прочим»
    result = evaluate.evaluate(old, new, samples)
    assert result["failures"] == ["Стекло: было 100.0%, стало 0.0% (-4 из 4 фото)"]
    assert "❌" in evaluate.format_report(result)
    assert ("glass", "other", 4) in result["confusions_new"]


def test_tolerance(test_dir):
    samples = evaluate.load_samples(test_dir)
    new = ColorModel(NEW_CLASSES, mistakes={"glass": "other"})
    assert evaluate.evaluate(ColorModel(OLD_CLASSES), new, samples, tolerance=100)["failures"] == []


def test_by_source_shows_where_the_model_improved(test_dir):
    samples = evaluate.load_samples(test_dir)
    result = evaluate.evaluate(ColorModel(OLD_CLASSES, mistakes={"paper": "glass"}), ColorModel(NEW_CLASSES), samples)
    assert result["by_source"]["old"]["realwaste"] == (6, 8) and result["by_source"]["new"]["realwaste"] == (8, 8)


def test_cli_exit_code(test_dir, monkeypatch, capsys):
    models = {"old.pt": ColorModel(OLD_CLASSES), "good.pt": ColorModel(NEW_CLASSES),
              "bad.pt": ColorModel(NEW_CLASSES, mistakes={"plastic": "other"})}
    monkeypatch.setattr(evaluate, "load_model", lambda path: models[path])
    assert evaluate.main(["--test", str(test_dir), "--old", "old.pt", "--new", "good.pt"]) == 0
    assert evaluate.main(["--test", str(test_dir), "--old", "old.pt", "--new", "bad.pt",
                          "--json", str(test_dir / "r.json")]) == 1
    assert "Пластик: было 100.0%, стало 0.0%" in capsys.readouterr().out
    assert (test_dir / "r.json").exists()
