"""Сборка датасета из скачанных источников (raw/) → datasets/wastewise/{train,val,test}/<класс>/.

    python -m train.dataset --raw raw --out datasets/wastewise

Что делает:
- переводит классы источников в наши 7 (train/sources.py), лишнее пропускает;
- убирает дубликаты (одно и то же фото в двух датасетах) — иначе тестовое фото могло бы попасть в обучение;
- делит на train/val/test ПО ОТПЕЧАТКУ ФОТО (md5): одно и то же фото всегда в одной и той же части,
  даже когда добавляются новые источники. Поэтому тест у старой и новой модели — один и тот же;
- в train ограничивает число фото на класс (--max-per-class), чтобы большой класс не задавил маленький;
  наши фото («Модель ошиблась») берутся всегда целиком;
- уменьшает фото до --size px и пишет ATTRIBUTION.csv (откуда каждое фото и под какой лицензией).
"""
import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from train.sources import CLASSES, OURS, SOURCES

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SPLITS = ("train", "val", "test")


@dataclass
class Item:
    source: str
    path: Path
    cls: str
    md5: str


def split_of(md5, val_pct=10, test_pct=10):
    """Часть датасета по отпечатку фото: всегда одна и та же для одного и того же фото."""
    bucket = int(md5[:8], 16) % 100
    return "test" if bucket < test_pct else "val" if bucket < test_pct + val_pct else "train"


def collect(raw_dir, sources=SOURCES):
    """Все фото из raw/ с нашими классами. Возвращает (фото, счётчик пропущенных по причинам)."""
    items, skipped = [], Counter()
    for source in sources:
        root = Path(raw_dir) / source.folder
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
                continue
            if path.name.startswith(".") or "__MACOSX" in path.parts:
                continue  # служебные файлы macOS (._фото.jpg) — не фото, хотя и с расширением .jpg
            label = path.parent.name.lower()
            if label not in source.mapping:
                skipped[f"{source.name}: неизвестный класс «{path.parent.name}»"] += 1
                continue
            cls = source.mapping[label]
            if cls is None:
                skipped[f"{source.name}: не берём «{path.parent.name}»"] += 1
                continue
            items.append(Item(source.name, path, cls, hashlib.md5(path.read_bytes()).hexdigest()))
    return items, skipped


def deduplicate(items):
    """Одно фото — одна запись. Если копии подписаны разными классами — не берём ни одну (метка спорная)."""
    by_md5 = defaultdict(list)
    for item in items:
        by_md5[item.md5].append(item)
    kept, duplicates, conflicts = [], 0, 0
    for copies in by_md5.values():
        if len({c.cls for c in copies}) > 1:
            conflicts += 1  # отбрасываем все копии
            continue
        kept.append(copies[0])  # порядок SOURCES = приоритет: наше фото важнее копии из датасета
        duplicates += len(copies) - 1
    return kept, duplicates, conflicts


def cap_train(items, max_per_class):
    """Не больше max_per_class фото на класс в train; наши фото — всегда, остальные — по порядку отпечатков."""
    if not max_per_class:
        return items
    result, per_class = [], Counter()
    ours = [i for i in items if i.source == OURS.name]
    others = sorted((i for i in items if i.source != OURS.name), key=lambda i: i.md5)
    for item in ours + others:
        if item.source == OURS.name or per_class[item.cls] < max_per_class:
            result.append(item)
            per_class[item.cls] += 1
    return result


def build(raw_dir, out_dir, size=448, max_per_class=3000, val_pct=10, test_pct=10, sources=SOURCES):
    """Собрать датасет. Возвращает сводку {часть: {класс: число}} и пишет её в summary.json."""
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    items, skipped = collect(raw_dir, sources)
    items, duplicates, conflicts = deduplicate(items)
    by_split = defaultdict(list)
    for item in items:
        by_split[split_of(item.md5, val_pct, test_pct)].append(item)
    by_split["train"] = cap_train(by_split["train"], max_per_class)

    attribution = _load_attribution(raw_dir, sources)
    if out_dir.exists():
        shutil.rmtree(out_dir)  # собираем заново целиком, чтобы не осталось фото от прошлой сборки
    summary = {split: {cls: 0 for cls in CLASSES} for split in SPLITS}
    by_source = Counter()
    licenses = {s.name: s.license for s in sources}
    out_dir.mkdir(parents=True)
    with open(out_dir / "ATTRIBUTION.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "source", "license", "original", "author"])
        for split in SPLITS:
            for cls in CLASSES:
                (out_dir / split / cls).mkdir(parents=True, exist_ok=True)
            for item in by_split[split]:
                name = f"{item.source}__{item.md5}.jpg"
                target = out_dir / split / item.cls / name
                if not _save_resized(item.path, target, size):
                    skipped[f"{item.source}: файл не открывается"] += 1
                    continue
                summary[split][item.cls] += 1
                by_source[(split, item.source)] += 1
                extra = attribution.get((item.source, item.path.name), {})
                writer.writerow([f"{split}/{item.cls}/{name}", item.source,
                                 extra.get("license") or licenses[item.source],
                                 extra.get("original", ""), extra.get("author", "")])

    report = {"splits": summary, "by_source": {f"{s}/{src}": n for (s, src), n in sorted(by_source.items())},
              "duplicates_removed": duplicates, "conflicting_labels": conflicts, "skipped": dict(skipped)}
    (out_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def check(report, min_train=30):
    """Проблемы собранного датасета: пустой класс в какой-то части не даст обучению запуститься."""
    problems = []
    for split in SPLITS:
        for cls, n in report["splits"][split].items():
            if n == 0:
                problems.append(f"нет ни одного фото класса «{cls}» в {split} — добавьте источник с этим классом")
    for cls, n in report["splits"]["train"].items():
        if 0 < n < min_train:
            problems.append(f"в train всего {n} фото класса «{cls}» — модель выучит его плохо")
    return problems


def format_report(report):
    lines = ["| Класс | train | val | test |", "|---|---:|---:|---:|"]
    for cls in CLASSES:
        lines.append(f"| {cls} | " + " | ".join(str(report["splits"][s][cls]) for s in SPLITS) + " |")
    lines.append("| **всего** | " + " | ".join(str(sum(report["splits"][s].values())) for s in SPLITS) + " |")
    lines.append("")
    lines.append("По источникам: " + ", ".join(f"{k} — {v}" for k, v in report["by_source"].items()))
    lines.append(f"Дубликатов убрано: {report['duplicates_removed']}, спорных меток: {report['conflicting_labels']}")
    return "\n".join(lines)


def _save_resized(src, target, size):
    try:
        with Image.open(src) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((size, size))
            image.save(target, "JPEG", quality=90)  # без EXIF: в наших фото не остаётся геометок
        return True
    except Exception:
        return False


def _load_attribution(raw_dir, sources):
    """attribution.csv, которые пишут шаги TACO и Open Images: файл → оригинал, автор, лицензия."""
    result = {}
    for source in sources:
        root = Path(raw_dir) / source.folder
        for path in root.rglob("attribution.csv") if root.exists() else []:
            with open(path, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    result[(source.name, row["file"])] = row
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw", default="raw", help="папка со скачанными источниками")
    parser.add_argument("--out", default="datasets/wastewise", help="куда собрать датасет")
    parser.add_argument("--size", type=int, default=448, help="фото уменьшаются до этого размера, px")
    parser.add_argument("--max-per-class", type=int, default=3000, help="не больше фото на класс в train (0 — без лимита)")
    args = parser.parse_args()
    report = build(args.raw, args.out, args.size, args.max_per_class)
    print(format_report(report))
    problems = check(report)
    for problem in problems:
        print(f"⚠️ {problem}")
    raise SystemExit(1 if any("нет ни одного" in p for p in problems) else 0)


if __name__ == "__main__":
    main()
