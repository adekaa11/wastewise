"""Open Images — электроника: вырезки предметов по рамкам → raw/openimages/crops/<класс>/.

    python -m train.openimages --out raw/openimages --per-class 200

Берём части validation и test Open Images V5: рамки там проверены людьми. Фото скачиваются из
общедоступного хранилища (AWS Open Data) без регистрации. Разметка — CC BY 4.0 (Google LLC),
фото помечены как CC BY 2.0: автор и ссылка на оригинал каждого фото пишутся в attribution.csv.
"""
import argparse
import csv
import io
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from train.sources import OPENIMAGES_CLASSES

BASE = "https://storage.googleapis.com/openimages"
CLASSES_URL = f"{BASE}/v5/class-descriptions-boxable.csv"
BOXES_URL = {"validation": f"{BASE}/v5/validation-annotations-bbox.csv", "test": f"{BASE}/v5/test-annotations-bbox.csv"}
IMAGES_URL = {"validation": f"{BASE}/2018_04/validation/validation-images-with-rotation.csv",
              "test": f"{BASE}/2018_04/test/test-images-with-rotation.csv"}
PHOTO_URL = "https://open-images-dataset.s3.amazonaws.com/{split}/{image_id}.jpg"


def select_boxes(class_rows, box_rows_by_split, image_rows, wanted=OPENIMAGES_CLASSES, per_class=200, min_area=0.02):
    """Какие рамки вырезать: только нужные классы, одиночные настоящие предметы, не крошечные.

    Пропускаем: группы предметов (IsGroupOf), рисунки и игрушки (IsDepiction), фото с поворотом
    (рамки размечены на повёрнутом фото). Не больше per_class рамок на класс и одной на фото.
    """
    names = {mid: name for mid, name in class_rows if name in wanted}
    rotated = {row["ImageID"] for row in image_rows if row.get("Rotation") not in ("", "0", "0.0", None)}
    chosen, per_name, used = [], Counter(), set()
    for split, rows in box_rows_by_split.items():
        for row in rows:
            name = names.get(row["LabelName"])
            if not name or row["IsGroupOf"] != "0" or row["IsDepiction"] != "0" or row["ImageID"] in rotated:
                continue
            box = tuple(float(row[k]) for k in ("XMin", "YMin", "XMax", "YMax"))
            if (box[2] - box[0]) * (box[3] - box[1]) < min_area or per_name[name] >= per_class:
                continue
            if (row["ImageID"], name) in used:
                continue
            used.add((row["ImageID"], name))
            per_name[name] += 1
            chosen.append((split, row["ImageID"], name, box))
    return chosen


def crop_box(photo, box, pad=0.1):
    """Вырезать рамку (доли 0..1 от размера фото) с запасом pad вокруг."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    left, top = max(0.0, x0 - pad * w), max(0.0, y0 - pad * h)
    right, bottom = min(1.0, x1 + pad * w), min(1.0, y1 + pad * h)
    return photo.crop((round(left * photo.width), round(top * photo.height),
                       round(right * photo.width), round(bottom * photo.height)))


def run(out_dir, per_class=200, workers=16, min_side=64, fetch=None):
    """Скачать разметку, нужные фото и вырезать предметы. fetch(url) → bytes | None (подменяется в тестах)."""
    out_dir = Path(out_dir)
    fetch = fetch or _http_get
    classes = list(csv.reader(io.StringIO(_text(fetch, CLASSES_URL))))
    boxes = {split: list(csv.DictReader(io.StringIO(_text(fetch, url)))) for split, url in BOXES_URL.items()}
    images = [row for url in IMAGES_URL.values() for row in csv.DictReader(io.StringIO(_text(fetch, url)))]
    info = {row["ImageID"]: row for row in images}
    chosen = select_boxes(classes, boxes, images, per_class=per_class)

    crops_dir = out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    photos = sorted({(split, image_id) for split, image_id, _, _ in chosen})

    def download(key):
        split, image_id = key
        target = out_dir / "images" / f"{image_id}.jpg"
        if not target.exists():
            data = fetch(PHOTO_URL.format(split=split, image_id=image_id))
            if not data:
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(download, photos))

    saved = 0
    with open(crops_dir / "attribution.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "original", "author", "license"])
        for split, image_id, name, box in chosen:
            path = out_dir / "images" / f"{image_id}.jpg"
            if not path.exists():
                continue
            try:
                with Image.open(path) as opened:
                    piece = crop_box(opened.convert("RGB"), box)
            except Exception:
                continue
            if min(piece.size) < min_side:
                continue
            file_name = f"{image_id}_{name.lower().replace(' ', '_')}.jpg"
            (crops_dir / name.lower()).mkdir(exist_ok=True)
            piece.save(crops_dir / name.lower() / file_name, "JPEG", quality=92)
            meta = info.get(image_id, {})
            writer.writerow([file_name, meta.get("OriginalLandingURL", ""), meta.get("Author", ""),
                             meta.get("License", "") or "CC BY 2.0"])
            saved += 1
    return saved


def _text(fetch, url):
    data = fetch(url)
    if not data:
        raise RuntimeError(f"Не удалось скачать разметку Open Images: {url} — проверьте интернет и запустите ещё раз")
    return data.decode("utf-8")


def _http_get(url):
    import requests

    try:
        response = requests.get(url, timeout=120)
        return response.content if response.ok else None
    except requests.RequestException:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="raw/openimages")
    parser.add_argument("--per-class", type=int, default=200, help="не больше рамок на класс Open Images")
    args = parser.parse_args()
    print(f"Вырезано предметов электроники: {run(args.out, args.per_class)} → {Path(args.out) / 'crops'}")


if __name__ == "__main__":
    main()
