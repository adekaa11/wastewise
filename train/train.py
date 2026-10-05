"""Дообучение модели WasteWise на собранном датасете (7 классов).

    python -m train.train --data datasets/wastewise --base assets/best.pt

Берём модель, которая сейчас на сайте (assets/best.pt), и дообучаем её. Всё, что сеть уже умеет
«видеть» в отходах, сохраняется; заменяется только последний слой — на 7 ответов вместо 4.
ultralytics делает это сам, когда классов в датасете больше, чем в модели.

Запускать на GPU (бесплатный Google Colab, ноутбук train/wastewise_colab.ipynb): на T4 — около часа.
Результат копируется в --out (по умолчанию models/new_best.pt) — дальше его проверяет train/evaluate.py.
"""
import argparse
import shutil
from pathlib import Path

DEFAULTS = {
    "epochs": 30,     # обычно хватает; если точность на val ещё растёт — можно больше
    "imgsz": 320,     # старая модель училась на 512: 320 почти так же точен, а учится в ~2,5 раза быстрее
    "batch": 64,
    "patience": 8,    # остановиться, если 8 эпох подряд нет улучшения
    "name": "wastewise7",
    "out": "models/new_best.pt",
}


def train(data, base="assets/best.pt", epochs=DEFAULTS["epochs"], imgsz=DEFAULTS["imgsz"], batch=DEFAULTS["batch"],
          patience=DEFAULTS["patience"], name=DEFAULTS["name"], device=None, workers=8, fraction=1.0,
          out=DEFAULTS["out"], hours=None):
    """Обучить, скопировать лучшую модель в out и вернуть этот путь."""
    from ultralytics import YOLO

    model = YOLO(base)
    model.train(
        data=str(data), epochs=epochs, imgsz=imgsz, batch=batch, patience=patience,
        name=name, exist_ok=True,  # папку запуска ultralytics выбирает сам (runs/…/<name>)
        seed=0, deterministic=True,  # повторный запуск на тех же данных даёт тот же результат
        workers=workers, device=device, fraction=fraction, plots=True,
        # hours: потолок по времени (например, на бесплатном сервере GitHub Actions задача живёт 6 часов).
        # ultralytics сам подстроит число эпох и всё равно сохранит лучшую модель.
        **({"time": hours} if hours else {}),
        # Аугментации ultralytics по умолчанию (случайная обрезка, поворот цвета, RandAugment, стирание
        # кусков) как раз учат модель узнавать предмет не только на белом фоне.
    )
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(model.trainer.best, out)  # постоянный путь: ноутбуку не нужно искать папку запуска
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", default="datasets/wastewise", help="папка из python -m train.dataset")
    parser.add_argument("--base", default="assets/best.pt", help="с какой модели начинать (текущая модель сайта)")
    for key in ("epochs", "imgsz", "batch", "patience"):
        parser.add_argument(f"--{key}", type=int, default=DEFAULTS[key])
    parser.add_argument("--name", default=DEFAULTS["name"])
    parser.add_argument("--device", default=None, help="0 — первая видеокарта, cpu — процессор (по умолчанию — сам)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--fraction", type=float, default=1.0, help="доля train для быстрой пробы (0.1 — 10%%)")
    parser.add_argument("--out", default=DEFAULTS["out"], help="куда положить лучшую модель")
    parser.add_argument("--hours", type=float, default=None, help="не дольше этого числа часов (по умолчанию — без лимита)")
    args = parser.parse_args(argv)

    best = train(args.data, args.base, args.epochs, args.imgsz, args.batch, args.patience, args.name,
                 args.device, args.workers, args.fraction, args.out, args.hours)
    print(f"\nГотово: {best}")
    print(f"Дальше: python -m train.evaluate --test {Path(args.data) / 'test'} --old {args.base} --new {best}")


if __name__ == "__main__":
    main()
