"""Откуда берём фото для обучения: открытые датасеты (ссылки и лицензии) + наши фото «Модель ошиблась».

Каждый источник раскладывается в raw/<папка>/…/<класс источника>/<фото>; mapping переводит
класс источника (имя папки в нижнем регистре) в наш класс (ключ WASTE_INFO). None — не берём.

Лицензии проверены по страницам авторов (октябрь 2026). Итоговый датасет и модель — только для
учебного некоммерческого использования: RealWaste — CC BY-NC-SA, у части фото TACO и Garbage
Dataset лицензии свои. Авторство каждого фото — в ATTRIBUTION.csv собранного датасета.
"""
from dataclasses import dataclass, field

from core.content import CLASS_ALIASES, WASTE_INFO

CLASSES = list(WASTE_INFO)  # glass, metal, paper, plastic, ewaste, organic, other


@dataclass(frozen=True)
class Source:
    name: str      # короткое имя: оно же — префикс файлов в датасете (trashnet__<md5>.jpg)
    folder: str    # папка внутри raw/
    title: str
    url: str
    license: str
    note: str
    mapping: dict = field(default_factory=dict)
    optional: bool = False


OURS = Source(
    "ours", "feedback", "Наши фото «Модель ошиблась»",
    "Supabase Storage, приватный бакет feedback (train/feedback_export.py)",
    "собственные фото пользователей WasteWise (отправлены для дообучения)",
    "самые ценные: настоящие фото с телефонов, все идут в обучение без ограничений",
    mapping={**{c: c for c in CLASSES}, **CLASS_ALIASES},
)

TRASHNET = Source(
    "trashnet", "trashnet", "TrashNet (Thung & Yang, 2016)",
    "https://github.com/garythung/trashnet",
    "MIT",
    "2527 фото предметов на белом фоне — похожие на те, на которых училась старая модель",
    mapping={"cardboard": "paper", "glass": "glass", "metal": "metal", "paper": "paper",
             "plastic": "plastic", "trash": "other"},
)

REALWASTE = Source(
    "realwaste", "realwaste", "RealWaste (Single, Iranmanesh, Raad, 2023)",
    "https://github.com/sam-single/realwaste · https://archive.ics.uci.edu/dataset/908/realwaste",
    "CC BY-NC-SA 4.0 — так в репозитории авторов (на UCI указана CC BY 4.0; берём более строгую)",
    "4752 фото настоящего мусора на полигоне: грязь, мятые предметы, сложный фон; есть органика",
    mapping={"cardboard": "paper", "food organics": "organic", "glass": "glass", "metal": "metal",
             "miscellaneous trash": "other", "paper": "paper", "plastic": "plastic",
             "textile trash": "other", "vegetation": "organic"},
)

TACO = Source(
    "taco", "taco/crops", "TACO — Trash Annotations in Context (Proença & Simões, 2020)",
    "http://tacodataset.org · https://github.com/pedropro/TACO",
    "разметка CC BY 4.0; у каждого фото своя лицензия (Flickr CC, ODbL OpenLitterMap) — см. ATTRIBUTION.csv",
    "1500 фото мусора «в природе» (улицы, пляжи, лес); берём вырезки предметов по рамкам",
    mapping={
        # стекло
        "glass bottle": "glass", "broken glass": "glass", "glass jar": "glass", "glass cup": "glass",
        # металл (аэрозольные баллончики сдают отдельно как опасные — их не берём)
        "drink can": "metal", "food can": "metal", "metal bottle cap": "metal", "metal lid": "metal",
        "pop tab": "metal", "scrap metal": "metal", "aluminium foil": "metal",
        # бумага и картон
        "normal paper": "paper", "magazine paper": "paper", "wrapping paper": "paper", "paper bag": "paper",
        "corrugated carton": "paper", "egg carton": "paper", "meal carton": "paper", "other carton": "paper",
        "pizza box": "paper", "toilet tube": "paper",
        # пластик
        "clear plastic bottle": "plastic", "other plastic bottle": "plastic", "plastic bottle cap": "plastic",
        "plastic lid": "plastic", "disposable plastic cup": "plastic", "other plastic cup": "plastic",
        "plastic film": "plastic", "single-use carrier bag": "plastic", "polypropylene bag": "plastic",
        "garbage bag": "plastic", "disposable food container": "plastic", "other plastic container": "plastic",
        "spread tub": "plastic", "tupperware": "plastic", "plastic utensils": "plastic",
        "plastic straw": "plastic", "six pack rings": "plastic", "other plastic": "plastic",
        # несортируемое: многослойное, загрязнённое, пенопласт, окурки
        "cigarette": "other", "styrofoam piece": "other", "foam cup": "other", "foam food container": "other",
        "crisp packet": "other", "drink carton": "other", "paper cup": "other", "tissues": "other",
        "paper straw": "other", "rope & strings": "other", "shoe": "other", "plastic glooves": "other",
        "aluminium blister pack": "other", "carded blister pack": "other", "plastified paper bag": "other",
        "battery": "ewaste", "food waste": "organic",
        # не берём: неразмеченное, неоднозначное (обёртки бывают и пластиком, и многослойными), аэрозоли
        "unlabeled litter": None, "other plastic wrapper": None, "squeezable tube": None, "aerosol": None,
    },
)

# Электроника из Open Images (Google): вырезки по рамкам. Микрофоны не берём — это в основном сцена и люди.
OPENIMAGES_CLASSES = [
    "Mobile phone", "Laptop", "Computer keyboard", "Computer mouse", "Remote control", "Tablet computer",
    "Headphones", "Calculator", "Camera", "Light bulb", "Flashlight", "Torch", "Ipod", "Corded phone",
    "Telephone", "Digital clock", "Alarm clock", "Hair dryer", "Printer", "Computer monitor", "Television",
    "Toaster", "Kettle", "Mixer", "Blender",
]
OPENIMAGES = Source(
    "openimages", "openimages/crops", "Open Images V5 (Google) — электроника",
    "https://storage.googleapis.com/openimages/web/index.html",
    "разметка CC BY 4.0 (Google LLC); фото помечены как CC BY 2.0, автор и ссылка — в ATTRIBUTION.csv",
    "батареек в Open Images нет, зато есть телефоны, ноутбуки, пульты, лампочки, мелкая техника",
    mapping={name.lower(): "ewaste" for name in OPENIMAGES_CLASSES},
)

GARBAGE_DATASET = Source(
    "garbage", "garbage_dataset", "Garbage Dataset v2 (Kunwar, 2026)",
    "https://www.kaggle.com/datasets/sumn2u/garbage-classification-v2",
    "открытая, заявлена автором (на зеркалах — MIT); часть фото собрана из интернета — только для учёбы",
    "главный источник батареек (≈940 фото) и ещё ≈1000 фото органики; нужен бесплатный токен Kaggle",
    mapping={"battery": "ewaste", "biological": "organic", "cardboard": "paper", "clothes": "other",
             "glass": "glass", "metal": "metal", "paper": "paper", "plastic": "plastic", "shoes": "other",
             "trash": "other"},
    optional=True,
)

SOURCES = [OURS, TRASHNET, REALWASTE, TACO, OPENIMAGES, GARBAGE_DATASET]  # порядок = приоритет при дублях


def license_table():
    """Таблица источников для README и ноутбука."""
    rows = ["| Источник | Что даёт | Лицензия | Ссылка |", "|---|---|---|---|"]
    for s in SOURCES:
        rows.append(f"| {s.title}{' (по желанию)' if s.optional else ''} | {s.note} | {s.license} | {s.url} |")
    return "\n".join(rows)
