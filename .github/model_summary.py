"""Короткая сводка обучения в аннотациях запуска GitHub Actions — её видно, не открывая логи.

    python .github/model_summary.py <папка с результатом обучения>

Читает models/compare.json (train.evaluate) и datasets/wastewise/summary.json (train.dataset), если они есть.
"""
import json
import os
import sys
from pathlib import Path


def notice(title, text):
    line = f"{title}: {text}"
    print(line)
    if os.getenv("GITHUB_ACTIONS"):
        print(f"::notice title={title}::{text}")


def pct(pair):
    return f"{pair[0] / pair[1] * 100:.1f}% ({pair[0]}/{pair[1]})" if pair and pair[1] else "—"


def main(root):
    root = Path(root)
    summary = next(iter(root.rglob("summary.json")), None)
    if summary:
        splits = json.loads(summary.read_text(encoding="utf-8"))["splits"]
        notice("Датасет, train", ", ".join(f"{c} {n}" for c, n in splits["train"].items()))
        notice("Датасет, test", ", ".join(f"{c} {n}" for c, n in splits["test"].items()))
    compare = next(iter(root.rglob("compare.json")), None)
    if not compare:
        notice("Сравнение", "compare.json нет — обучение или оценка не дошли до конца")
        return 0
    result = json.loads(compare.read_text(encoding="utf-8"))
    rows = [f"{cls} {pct(row['old'])} → {pct(row['new'])}" for cls, row in result["classes"].items()]
    notice("Точность по классам (старая → новая)", "; ".join(rows))
    notice("Старые классы вместе", f"{pct(result['old_classes_total']['old'])} → {pct(result['old_classes_total']['new'])}")
    notice("Все классы, новая", pct(result["all_classes_total_new"]))
    notice("Итог", "❌ хуже старой: " + "; ".join(result["failures"]) if result["failures"]
           else "✅ на старых классах не хуже — можно ставить на сайт")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
