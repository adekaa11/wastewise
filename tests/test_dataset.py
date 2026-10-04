"""Сборка датасета (train/): источники → 7 классов, дубли, стабильное деление, вырезки TACO и Open Images."""
import csv
import io
import json
import random

from PIL import Image

from core import storage
from train import dataset, feedback_export, openimages, taco
from train.sources import CLASSES, SOURCES


def _jpeg(path, color, size=(120, 90)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")
    return path


def _random_color(rng):
    return tuple(rng.randrange(256) for _ in range(3))


def test_split_is_stable_and_roughly_80_10_10():
    rng = random.Random(0)
    hashes = ["%032x" % rng.getrandbits(128) for _ in range(5000)]
    splits = [dataset.split_of(h) for h in hashes]
    assert splits == [dataset.split_of(h) for h in hashes]  # одно фото — всегда одна часть
    share = {s: splits.count(s) / len(splits) for s in dataset.SPLITS}
    assert 0.77 < share["train"] < 0.83 and 0.08 < share["val"] < 0.12 and 0.08 < share["test"] < 0.12


def _make_raw(raw, rng, per_class=40):
    """Маленькие «датасеты» в тех же раскладках, что настоящие."""
    for cls in ("cardboard", "glass", "metal", "paper", "plastic", "trash"):
        for i in range(per_class):
            _jpeg(raw / "trashnet" / "dataset-resized" / cls / f"{cls}{i}.jpg", _random_color(rng))
    for cls in ("Food Organics", "Vegetation", "Miscellaneous Trash"):
        for i in range(per_class):
            _jpeg(raw / "realwaste" / "RealWaste" / cls / f"{cls}_{i}.jpg", _random_color(rng))
    for i in range(per_class):
        _jpeg(raw / "openimages" / "crops" / "mobile phone" / f"oi{i}.jpg", _random_color(rng))
    _jpeg(raw / "trashnet" / "dataset-resized" / "unknown_class" / "x.jpg", (1, 2, 3))
    junk = raw / "trashnet" / "__MACOSX" / "dataset-resized" / "glass" / "._glass1.jpg"  # как в архиве TrashNet
    junk.parent.mkdir(parents=True)
    junk.write_bytes(b"\x00\x05\x16\x07AppleDouble")


def test_build_maps_classes_and_fills_every_split(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "ds"
    _make_raw(raw, random.Random(1))
    report = dataset.build(raw, out, size=64, max_per_class=0)

    assert sorted(p.name for p in (out / "train").iterdir()) == sorted(CLASSES)
    assert dataset.check(report) == [] or all("модель выучит" in p for p in dataset.check(report))
    total = {cls: sum(report["splits"][s][cls] for s in dataset.SPLITS) for cls in CLASSES}
    assert total == {"glass": 40, "metal": 40, "paper": 80, "plastic": 40, "other": 80, "organic": 80, "ewaste": 40}
    assert report["skipped"] == {"trashnet: неизвестный класс «unknown_class»": 1}

    some = next((out / "test" / "organic").glob("realwaste__*.jpg"))
    assert max(Image.open(some).size) <= 64  # уменьшено
    rows = list(csv.DictReader(open(out / "ATTRIBUTION.csv", encoding="utf-8")))
    assert len(rows) == sum(total.values())
    assert {r["license"] for r in rows if r["source"] == "trashnet"} == {"MIT"}
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["splits"] == report["splits"]


def test_duplicates_and_disputed_labels(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "ds"
    same = _jpeg(raw / "trashnet" / "dataset-resized" / "glass" / "g.jpg", (10, 20, 30))
    (raw / "feedback" / "glass").mkdir(parents=True)
    (raw / "feedback" / "glass" / "a.jpg").write_bytes(same.read_bytes())       # наша копия того же фото
    disputed = _jpeg(raw / "trashnet" / "dataset-resized" / "metal" / "m.jpg", (40, 50, 60))
    (raw / "realwaste" / "RealWaste" / "Plastic").mkdir(parents=True)
    (raw / "realwaste" / "RealWaste" / "Plastic" / "p.jpg").write_bytes(disputed.read_bytes())  # металл или пластик?

    report = dataset.build(raw, out, size=64)
    files = [p.name for p in out.rglob("*.jpg")]
    assert len(files) == 1 and files[0].startswith("ours__")  # дубль убран, наша копия важнее
    assert report["duplicates_removed"] == 1 and report["conflicting_labels"] == 1


def test_adding_a_source_does_not_move_test_photos(tmp_path):
    raw = tmp_path / "raw"
    _make_raw(raw, random.Random(2))
    dataset.build(raw, tmp_path / "v1", size=64)
    before = {p.name for p in (tmp_path / "v1" / "test").rglob("*.jpg")}
    for i in range(30):
        _jpeg(raw / "feedback" / "organic" / f"new{i}.jpg", _random_color(random.Random(100 + i)))
    dataset.build(raw, tmp_path / "v2", size=64)
    after = {p.name for p in (tmp_path / "v2" / "test").rglob("*.jpg")}
    assert before <= after  # старые тестовые фото на месте, новые лишь добавились


def test_train_cap_keeps_all_our_photos(tmp_path):
    raw = tmp_path / "raw"
    rng = random.Random(3)
    for i in range(60):
        _jpeg(raw / "trashnet" / "dataset-resized" / "glass" / f"g{i}.jpg", _random_color(rng))
    for i in range(20):
        _jpeg(raw / "feedback" / "glass" / f"o{i}.jpg", _random_color(rng))
    report = dataset.build(raw, tmp_path / "ds", size=32, max_per_class=10)
    train = list((tmp_path / "ds" / "train" / "glass").glob("*.jpg"))
    ours = [p for p in train if p.name.startswith("ours__")]
    assert len(train) == report["splits"]["train"]["glass"]
    assert len(ours) == len([1 for p in (raw / "feedback" / "glass").glob("*.jpg")
                             if dataset.split_of(_md5(p)) == "train"])  # все наши — в train
    assert len(train) - len(ours) <= max(0, 10 - len(ours))


def _md5(path):
    import hashlib
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_check_reports_missing_class(tmp_path):
    raw = tmp_path / "raw"
    _jpeg(raw / "trashnet" / "dataset-resized" / "glass" / "g.jpg", (1, 1, 1))
    problems = dataset.check(dataset.build(raw, tmp_path / "ds", size=32))
    assert any("ewaste" in p and "нет ни одного" in p for p in problems)


def test_every_source_maps_only_to_our_classes():
    for source in SOURCES:
        assert {v for v in source.mapping.values() if v} <= set(CLASSES), source.name
        assert source.license and source.url, source.name


# ---------- TACO ----------

def _taco_fixture(root):
    """Фото 1600×1200 размечено, а скачалась версия 640×480 — рамки нужно масштабировать."""
    annotations = {
        "images": [{"id": 7, "width": 1600, "height": 1200, "flickr_url": "https://flickr/7_o.jpg", "license": "CC"},
                   {"id": 8, "width": 1200, "height": 1600, "flickr_url": "https://flickr/8_o.jpg"}],
        "categories": [{"id": 1, "name": "Glass bottle"}, {"id": 2, "name": "Cigarette"}],
        "annotations": [
            {"id": 70, "image_id": 7, "category_id": 1, "bbox": [400, 300, 400, 600]},  # большая бутылка
            {"id": 71, "image_id": 7, "category_id": 2, "bbox": [10, 10, 40, 20]},      # крошечный окурок
            {"id": 80, "image_id": 8, "category_id": 1, "bbox": [100, 100, 500, 500]},  # фото повёрнуто иначе
        ],
    }
    (root / "images").mkdir(parents=True)
    (root / "annotations.json").write_text(json.dumps(annotations))
    image = Image.new("RGB", (640, 480), "white")
    image.paste((0, 128, 0), (160, 120, 320, 360))  # «бутылка» там, где рамка (в масштабе 0.4)
    image.save(root / "images" / "7.jpg")
    Image.new("RGB", (640, 480), "white").save(root / "images" / "8.jpg")  # 640×480, а размечено 1200×1600


def test_taco_crops_scaled_boxes_and_skips_bad_ones(tmp_path):
    _taco_fixture(tmp_path)
    assert taco.crop(tmp_path, min_side=48, pad=0.0) == 1
    [crop] = list((tmp_path / "crops" / "glass bottle").glob("*.jpg"))
    piece = Image.open(crop)
    assert piece.size == (160, 240)
    assert piece.getpixel((80, 120))[1] > 100  # внутри — зелёная «бутылка»
    rows = list(csv.DictReader(open(tmp_path / "crops" / "attribution.csv", encoding="utf-8")))
    assert rows == [{"file": "7_70.jpg", "original": "https://flickr/7_o.jpg", "author": "", "license": "CC"}]


# ---------- Open Images ----------

def _oi_fetch(photos):
    classes = "/m/050k8,Mobile phone\n/m/0hg7b,Microphone\n/m/01c648,Laptop\n"
    header = "ImageID,Source,LabelName,Confidence,XMin,XMax,YMin,YMax,IsOccluded,IsTruncated,IsGroupOf,IsDepiction,IsInside\n"
    validation = header + "\n".join([
        "img1,x,/m/050k8,1,0.25,0.75,0.25,0.75,0,0,0,0,0",   # телефон — берём
        "img2,x,/m/050k8,1,0.1,0.9,0.1,0.9,0,0,1,0,0",       # группа телефонов — нет
        "img3,x,/m/050k8,1,0.1,0.9,0.1,0.9,0,0,0,1,0",       # рисунок — нет
        "img4,x,/m/0hg7b,1,0.1,0.9,0.1,0.9,0,0,0,0,0",       # микрофон — не наш класс
        "img5,x,/m/01c648,1,0.4,0.45,0.4,0.45,0,0,0,0,0",    # крошечный ноутбук — нет
        "img6,x,/m/01c648,1,0.1,0.9,0.1,0.9,0,0,0,0,0",      # повёрнутое фото — нет
    ]) + "\n"
    meta = ("ImageID,Subset,OriginalURL,OriginalLandingURL,License,AuthorProfileURL,Author,Title,OriginalSize,"
            "OriginalMD5,Thumbnail300KURL,Rotation\n"
            "img1,validation,o,https://flickr/img1,https://creativecommons.org/licenses/by/2.0/,a,Анна,t,1,m,th,\n"
            "img6,validation,o,https://flickr/img6,https://creativecommons.org/licenses/by/2.0/,a,Б,t,1,m,th,90.0\n")

    def fetch(url):
        if url == openimages.CLASSES_URL:
            return classes.encode()
        if url == openimages.BOXES_URL["validation"]:
            return validation.encode()
        if url == openimages.BOXES_URL["test"]:
            return header.encode()
        if url in openimages.IMAGES_URL.values():
            return meta.encode() if "validation" in url else meta.splitlines()[0].encode()
        photos.append(url)
        buffer = io.BytesIO()
        Image.new("RGB", (400, 300), "gray").save(buffer, "JPEG")
        return buffer.getvalue()

    return fetch


def test_openimages_selects_and_crops_electronics(tmp_path):
    downloaded = []
    assert openimages.run(tmp_path, fetch=_oi_fetch(downloaded)) == 1
    assert downloaded == [openimages.PHOTO_URL.format(split="validation", image_id="img1")]  # лишнее не качаем
    [crop] = list((tmp_path / "crops" / "mobile phone").glob("*.jpg"))
    assert Image.open(crop).size == (240, 180)  # 0.5 ширины/высоты + запас 10% с каждой стороны
    rows = list(csv.DictReader(open(tmp_path / "crops" / "attribution.csv", encoding="utf-8")))
    assert rows[0]["author"] == "Анна" and rows[0]["original"] == "https://flickr/img1"
    assert "by/2.0" in rows[0]["license"]


def test_crops_become_dataset_classes(tmp_path):
    _taco_fixture(tmp_path / "raw" / "taco")
    taco.crop(tmp_path / "raw" / "taco", min_side=48)
    openimages.run(tmp_path / "raw" / "openimages", fetch=_oi_fetch([]))
    report = dataset.build(tmp_path / "raw", tmp_path / "ds", size=64)
    total = {cls: sum(report["splits"][s][cls] for s in dataset.SPLITS) for cls in CLASSES}
    assert total["glass"] == 1 and total["ewaste"] == 1
    rows = {r["source"]: r for r in csv.DictReader(open(tmp_path / "ds" / "ATTRIBUTION.csv", encoding="utf-8"))}
    assert rows["openimages"]["author"] == "Анна" and rows["taco"]["license"] == "CC"


# ---------- наши фото из Supabase Storage ----------

def test_feedback_export_downloads_by_label_and_skips_disputed(tmp_path, fake_storage):
    store = storage.SupabaseFeedbackStore(fake_storage.url, fake_storage.key)
    store.save("ewaste", "a" * 32, b"battery-photo")
    store.save("organic", "b" * 32, b"peel-photo")
    store.save("glass", "c" * 32, b"jar")
    store.save("plastic", "c" * 32, b"jar")  # то же фото, другая метка — спорное
    counts, disputed = feedback_export.export(store, tmp_path)
    assert dict(counts) == {"ewaste": 1, "organic": 1} and disputed == 1
    assert (tmp_path / "ewaste" / f"{'a' * 32}.jpg").read_bytes() == b"battery-photo"
