"""Сравнение старой и новой модели на ОДНОМ тестовом наборе: точность по каждому классу.

    python -m train.evaluate --test datasets/wastewise/test --old assets/best.pt --new runs/classify/wastewise7/weights/best.pt

Точность класса — доля его тестовых фото, на которых модель ответила правильно (как на сайте: первый вариант).
Классы, которых старая модель не знает (батарейки, органика, прочее), у неё помечены «—».

Правило: новая модель не должна стать хуже на классах, которые знала старая. Если хотя бы на одном из
них точность упала больше чем на --tolerance процентных пунктов (по умолчанию 0 — «не хуже вообще»),
скрипт пишет ❌ и завершается с кодом 1: такую модель на сайт ставить нельзя.
"""
import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from core.content import WASTE_INFO, canonical
from core.model import classify, load_image

GUARD_DEFAULT = None  # None — все классы, которые знает старая модель


@dataclass(frozen=True)
class Sample:
    path: Path
    label: str
    source: str  # префикс имени файла из сборки датасета: trashnet__<md5>.jpg → trashnet


def load_samples(test_dir):
    samples = []
    for class_dir in sorted(p for p in Path(test_dir).iterdir() if p.is_dir()):
        for path in sorted(class_dir.glob("*.jpg")):
            source = path.name.split("__")[0] if "__" in path.name else "?"
            samples.append(Sample(path, canonical(class_dir.name), source))
    return samples


def model_classes(model):
    return {canonical(name) for name in model.names.values()}


def predict(model, samples):
    """Ответ модели на каждое фото — тем же путём, что на сайте (load_image + classify)."""
    answers = []
    for sample in samples:
        image = load_image(sample.path.read_bytes())
        answers.append(canonical(classify(model, image, top_k=1)[0][0]) if image is not None else None)
    return answers


def per_class(samples, answers, known):
    """{класс: (верно, всего)}; для классов, которых модель не знает, — None."""
    stats = defaultdict(lambda: [0, 0])
    for sample, answer in zip(samples, answers):
        stats[sample.label][1] += 1
        stats[sample.label][0] += answer == sample.label
    return {cls: (tuple(v) if cls in known else None) for cls, v in stats.items()}


def per_source(samples, answers, classes):
    """{источник: (верно, всего)} на фото выбранных классов: видно, где модель сильнее — на белом фоне или в жизни."""
    stats = defaultdict(lambda: [0, 0])
    for sample, answer in zip(samples, answers):
        if sample.label in classes:
            stats[sample.source][1] += 1
            stats[sample.source][0] += answer == sample.label
    return {source: tuple(v) for source, v in stats.items()}


def compare(old, new, guard, tolerance=0.0):
    """Список ошибок «новая хуже старой на классе X» (по классам из guard)."""
    failures = []
    for cls in guard:
        if old.get(cls) is None or new.get(cls) is None or old[cls][1] == 0:
            continue
        old_acc, new_acc = _pct(*old[cls]), _pct(*new[cls])
        if new_acc < old_acc - tolerance:
            failures.append(f"{_name(cls)}: было {old_acc:.1f}%, стало {new_acc:.1f}% "
                            f"({new[cls][0] - old[cls][0]:+d} из {old[cls][1]} фото)")
    return failures


def confusions(samples, answers, top=5):
    pairs = Counter((s.label, a) for s, a in zip(samples, answers) if a != s.label)
    return pairs.most_common(top)


def evaluate(old_model, new_model, samples, guard=GUARD_DEFAULT, tolerance=0.0):
    old_known, new_known = model_classes(old_model), model_classes(new_model)
    guard = sorted(guard or old_known)
    old_answers, new_answers = predict(old_model, samples), predict(new_model, samples)
    old, new = per_class(samples, old_answers, old_known), per_class(samples, new_answers, new_known)
    totals = Counter(s.label for s in samples)
    return {
        "classes": {cls: {"old": old[cls], "new": new[cls], "photos": totals[cls]} for cls in _ordered(old)},
        "old_classes_total": {"old": _total(old, guard), "new": _total(new, guard)},
        "all_classes_total_new": _total(new, list(new)),
        "by_source": {"old": per_source(samples, old_answers, guard), "new": per_source(samples, new_answers, guard)},
        "confusions_new": [(a, b, n) for (a, b), n in confusions(samples, new_answers)],
        "guard": guard,
        "failures": compare(old, new, guard, tolerance),
    }


def format_report(result):
    lines = ["Точность по классам (тестовые фото, которых модели не видели при обучении):", "",
             "| Класс | Фото | Старая | Новая | Разница |", "|---|---:|---:|---:|---:|"]
    for cls, row in result["classes"].items():
        old, new = row["old"], row["new"]
        diff = f"{_pct(*new) - _pct(*old):+.1f} п.п." if old and new else ""
        lines.append(f"| {_name(cls)} | {row['photos']} | {_fmt(old)} | {_fmt(new)} | {diff} |")
    old_total, new_total = result["old_classes_total"]["old"], result["old_classes_total"]["new"]
    lines += ["", f"Старые классы вместе ({', '.join(_name(c).lower() for c in result['guard'])}): "
                  f"старая {_fmt(old_total)}, новая {_fmt(new_total)}.",
              f"Все классы, новая модель: {_fmt(result['all_classes_total_new'])}.", "",
              "Старые классы по источникам фото (белый фон → настоящие фото):", "",
              "| Источник | Фото | Старая | Новая |", "|---|---:|---:|---:|"]
    for source, new in sorted(result["by_source"]["new"].items()):
        old = result["by_source"]["old"].get(source)
        lines.append(f"| {source} | {new[1]} | {_fmt(old)} | {_fmt(new)} |")
    if result["confusions_new"]:
        lines += ["", "Чаще всего новая модель путает: " + "; ".join(
            f"{_name(a).lower()} → {_name(b).lower() if b else '?'} ({n})" for a, b, n in result["confusions_new"])]
    lines.append("")
    if result["failures"]:
        lines.append("❌ Новая модель ХУЖЕ старой: " + "; ".join(result["failures"]))
        lines.append("   Не заменяйте assets/best.pt. Что попробовать — в docs/TRAINING.md, раздел «Если стало хуже».")
    else:
        lines.append("✅ На старых классах новая модель не хуже старой — её можно ставить на сайт.")
    return "\n".join(lines)


def _ordered(classes):
    return [c for c in WASTE_INFO if c in classes] + sorted(set(classes) - set(WASTE_INFO))


def _total(stats, classes):
    rows = [stats[c] for c in classes if stats.get(c)]
    return (sum(r[0] for r in rows), sum(r[1] for r in rows)) if rows else None


def _pct(correct, total):
    return 100.0 * correct / total if total else 0.0


def _fmt(value):
    return "—" if not value else f"{_pct(*value):.1f}% ({value[0]}/{value[1]})"


def _name(cls):
    return WASTE_INFO.get(cls, {}).get("name", cls) if cls else "?"


def load_model(path):
    from core.model import load_model as load

    return load(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--test", default="datasets/wastewise/test", help="папка test из сборки датасета")
    parser.add_argument("--old", default="assets/best.pt", help="модель, которая сейчас на сайте")
    parser.add_argument("--new", required=True, help="новая модель (runs/classify/…/weights/best.pt)")
    parser.add_argument("--tolerance", type=float, default=0.0,
                        help="на сколько процентных пунктов можно просесть на старом классе (по умолчанию 0)")
    parser.add_argument("--json", help="сохранить результат в JSON")
    args = parser.parse_args(argv)

    samples = load_samples(args.test)
    if not samples:
        raise SystemExit(f"В {args.test} нет фото — сначала соберите датасет (python -m train.dataset)")
    result = evaluate(load_model(args.old), load_model(args.new), samples, tolerance=args.tolerance)
    print(format_report(result))
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
