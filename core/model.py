"""Нейросеть: загрузка модели YOLO и распознавание фото."""
import io
from pathlib import Path

from PIL import Image, ImageOps

ASSETS = Path(__file__).resolve().parent.parent / "assets"
MODEL_PATH = ASSETS / "best.pt"
DETECTOR_PATH = ASSETS / "yolo11n.pt"  # общий детектор COCO (80 классов) — «охранник» перед классификатором

# Классы COCO, которые точно НЕ отходы: человек и животные
NOT_WASTE = {0: "человек", 14: "птица", 15: "кошка", 16: "собака", 17: "лошадь", 18: "овца",
             19: "корова", 20: "слон", 21: "медведь", 22: "зебра", 23: "жираф"}
# Классы COCO, похожие на отходы: если они есть в кадре, фото пропускаем (человек держит бутылку — ок)
WASTE_LIKE = {39, 40, 41, 42, 43, 44, 45, 73}  # бутылка, бокал, стакан, вилка, нож, ложка, миска, книга/журнал

DARK_THRESHOLD = 35  # средняя яркость 0..255; ниже — снимок слишком тёмный


def load_model(path=MODEL_PATH):
    from ultralytics import YOLO  # импорт внутри — чтобы сайт открывался быстрее
    return YOLO(str(path))


def check_scene(detector, image: Image.Image):
    """Проверка «а мусор ли это вообще». Возвращает текст проблемы или None, если всё в порядке.

    Классификатор знает только 4 ответа и на ЛЮБОЕ фото выберет один из них
    (даже на селфи скажет «бумага, 99%»). Поэтому сначала смотрим общим детектором,
    нет ли в кадре человека или животного, и не слишком ли темно.
    """
    gray = image.convert("L")
    brightness = sum(i * c for i, c in enumerate(gray.histogram())) / (gray.width * gray.height)
    if brightness < DARK_THRESHOLD:
        return "Снимок слишком тёмный — включите свет или поднесите предмет к окну."

    if _has_face(gray):
        return "Похоже, в кадре лицо человека, а не отход. Сфотографируйте сам предмет крупным планом."

    result = detector.predict(image, conf=0.5, verbose=False)[0]
    area = image.width * image.height
    found_waste_like = False
    blocker = None
    for cls_id, (x1, y1, x2, y2) in zip(result.boxes.cls.tolist(), result.boxes.xyxy.tolist()):
        cls_id = int(cls_id)
        share = (x2 - x1) * (y2 - y1) / area
        if cls_id in WASTE_LIKE:
            found_waste_like = True
        # человек — только если занимает почти весь кадр: рука с предметом в руке — это нормально
        elif (cls_id == 0 and share > 0.40) or (cls_id in NOT_WASTE and cls_id != 0 and share > 0.10):
            blocker = NOT_WASTE[cls_id]
    if blocker and not found_waste_like:
        return f"Похоже, в кадре {blocker}, а не отход. Сфотографируйте сам предмет крупным планом."
    return None


def _has_face(gray: Image.Image):
    """Быстрый поиск лица встроенным в OpenCV детектором (без скачиваний)."""
    import cv2
    import numpy as np

    arr = cv2.equalizeHist(np.array(gray))
    side = int(min(arr.shape) * 0.15)  # лицо должно быть заметным, а не человечек на фоне
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return len(cascade.detectMultiScale(arr, 1.1, 6, minSize=(side, side))) > 0


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


MAX_SIDE = 1280  # px по длинной стороне: модели всё равно сжимают фото до 224–640 px


def load_image(raw: bytes):
    """Открыть загруженный файл как картинку. Возвращает None, если это не изображение.

    Фото с телефона бывают 4000×3000 и больше: держать их в памяти и прогонять через
    нейросети целиком бессмысленно — заранее уменьшаем до MAX_SIDE.
    """
    try:
        image = Image.open(io.BytesIO(raw))
        image.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG сразу читается в уменьшенном виде — быстрее
        image = ImageOps.exif_transpose(image).convert("RGB")  # поворот по данным камеры
    # Ловим любую ошибку: битый файл, «картинка-бомба» на сотни мегапикселей и т.п.
    # Широко — потому что ultralytics подменяет Image.open и на нечитаемом файле
    # бросает не только UnidentifiedImageError, но и ошибки своей доустановки pi-heif.
    except Exception:
        return None
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return image
