"""Нейросеть: загрузка модели YOLO и распознавание фото."""
from pathlib import Path

from PIL import Image

MODEL_PATH = Path(__file__).resolve().parent.parent / "assets" / "best.pt"


def load_model(path=MODEL_PATH):
    from ultralytics import YOLO  # импорт внутри — чтобы сайт открывался быстрее
    return YOLO(str(path))


def classify(model, image: Image.Image, top_k=3):
    """Возвращает список [(класс, вероятность), ...] от самого вероятного к менее вероятному.

    Модель — классификатор (YOLOv8s-cls): она отвечает «что на фото целиком»,
    а не ищет несколько предметов с рамками.
    """
    image = image.convert("RGB")
    result = model.predict(image, verbose=False)[0]
    probs = result.probs.data.tolist()
    names = result.names  # {0: 'glass', 1: 'metal', ...}
    ranked = sorted(((names[i], p) for i, p in enumerate(probs)), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]
