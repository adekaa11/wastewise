"""Переобучение модели на новой версии YOLO26 (запускать в Google Colab с GPU).

Шаги:
1. Скачайте датасет TrashNet (6 классов: cardboard, glass, metal, paper, plastic, trash),
   например с Kaggle или Hugging Face (garythung/trashnet).
2. Разложите фото так:
       dataset/train/<класс>/*.jpg   (~80% фото)
       dataset/val/<класс>/*.jpg     (~20% фото, НЕ те же, что в train)
3. Добавьте свои фото из data/feedback/<класс>/ в dataset/train/<класс>/ —
   это фото, которые пользователи исправили в приложении (ваше главное преимущество).
4. Запустите:  python train_yolo26.py
5. Скопируйте runs/classify/wastewise/weights/best.pt в assets/best.pt
   и добавьте описания новых классов (cardboard, trash) в core/content.py.
"""
from ultralytics import YOLO

model = YOLO("yolo26s-cls.pt")  # было yolov8s-cls.pt; если не скачивается — "yolo11s-cls.pt"
model.train(
    data="dataset",   # папка с train/ и val/
    imgsz=224,
    epochs=50,
    batch=32,
    patience=10,      # остановится сам, если 10 эпох подряд нет улучшения
    name="wastewise",
)
metrics = model.val()
print(f"Точность top-1: {metrics.top1:.1%}")
