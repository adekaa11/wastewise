"""TACO — мусор «в природе»: скачать фото и вырезать каждый предмет по рамке → raw/taco/crops/<категория>/.

    python -m train.taco --out raw/taco

Разметка (COCO JSON, CC BY 4.0) берётся из репозитория авторов на GitHub, фото — с Flickr в размере 640 px
(быстрее оригиналов, для обучения на 320 px хватает). Рамки в разметке — в пикселях исходного фото,
поэтому при вырезании они масштабируются под скачанный размер.
"""
import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

ANNOTATIONS_URL = "https://raw.githubusercontent.com/pedropro/TACO/master/data/annotations.json"


def download(out_dir, workers=16):
    """Скачать разметку и фото. Уже скачанное не качается повторно. Возвращает число недоступных фото."""
    import requests

    out_dir = Path(out_dir)
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    annotations_path = out_dir / "annotations.json"
    if not annotations_path.exists():
        response = requests.get(ANNOTATIONS_URL, timeout=60)
        response.raise_for_status()
        annotations_path.write_bytes(response.content)
    data = json.loads(annotations_path.read_text(encoding="utf-8"))

    def fetch(image):
        target = out_dir / "images" / f"{image['id']}.jpg"
        if target.exists():
            return True
        for url in (image.get("flickr_640_url"), image.get("flickr_url")):
            if not url:
                continue
            try:
                response = requests.get(url, timeout=60)
                if response.ok and response.content:
                    target.write_bytes(response.content)
                    return True
            except requests.RequestException:
                pass
        return False

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(fetch, data["images"]))
    return results.count(False)


def crop(out_dir, crops_dir=None, min_side=48, pad=0.15):
    """Вырезать предметы: crops/<категория>/<id фото>_<id рамки>.jpg + crops/attribution.csv.

    min_side — меньшие предметы (в пикселях скачанного фото) пропускаются: по ним ничего не видно.
    pad — запас вокруг рамки (доля её размера): немного окружения помогает узнать предмет.
    """
    out_dir = Path(out_dir)
    crops_dir = Path(crops_dir or out_dir / "crops")
    data = json.loads((out_dir / "annotations.json").read_text(encoding="utf-8"))
    categories = {c["id"]: c["name"].lower() for c in data["categories"]}
    images = {im["id"]: im for im in data["images"]}
    by_image = {}
    for ann in data["annotations"]:
        by_image.setdefault(ann["image_id"], []).append(ann)

    crops_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    with open(crops_dir / "attribution.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "original", "author", "license"])
        for image_id, anns in sorted(by_image.items()):
            path = out_dir / "images" / f"{image_id}.jpg"
            if not path.exists():
                continue
            info = images[image_id]
            try:
                with Image.open(path) as opened:
                    photo = ImageOps.exif_transpose(opened).convert("RGB")  # разметка — по повёрнутому фото
            except Exception:
                continue
            scale_x, scale_y = photo.width / info["width"], photo.height / info["height"]
            if abs(scale_x - scale_y) > 0.05 * max(scale_x, scale_y):
                continue  # пропорции не совпали с разметкой (фото повёрнуто иначе) — рамки встанут криво
            for ann in anns:
                box = _padded_box(ann["bbox"], scale_x, scale_y, pad, photo.size)
                if box is None or min(box[2] - box[0], box[3] - box[1]) < min_side:
                    continue
                category = categories[ann["category_id"]]
                name = f"{image_id}_{ann['id']}.jpg"
                (crops_dir / category).mkdir(exist_ok=True)
                photo.crop(box).save(crops_dir / category / name, "JPEG", quality=92)
                writer.writerow([name, info.get("flickr_url") or "", "", info.get("license") or "TACO (CC BY 4.0)"])
                saved += 1
    return saved


def _padded_box(bbox, scale_x, scale_y, pad, size):
    x, y, w, h = bbox  # COCO: левый верхний угол, ширина, высота — в пикселях исходного фото
    x, y, w, h = x * scale_x, y * scale_y, w * scale_x, h * scale_y
    if w <= 0 or h <= 0:
        return None
    left, top = max(0, x - pad * w), max(0, y - pad * h)
    right, bottom = min(size[0], x + w + pad * w), min(size[1], y + h + pad * h)
    return (round(left), round(top), round(right), round(bottom)) if right > left and bottom > top else None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="raw/taco")
    parser.add_argument("--skip-download", action="store_true", help="только вырезать (фото уже скачаны)")
    args = parser.parse_args()
    if not args.skip_download:
        missing = download(args.out)
        print(f"Фото TACO скачаны (недоступно на Flickr: {missing}).")
    print(f"Вырезано предметов: {crop(args.out)} → {Path(args.out) / 'crops'}")


if __name__ == "__main__":
    main()
