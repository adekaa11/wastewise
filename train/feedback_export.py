"""Наши фото «Модель ошиблась» из Supabase Storage → raw/feedback/<метка>/<md5>.jpg.

    SUPABASE_URL=… SUPABASE_SERVICE_KEY=… python -m train.feedback_export --out raw/feedback

Ключ — секретный (тот же, что у сайта в Secrets). В Google Colab его кладут в «Секреты» (значок ключа
слева), а не в текст ноутбука. Если одно и то же фото разные люди подписали по-разному, оно не берётся:
спорная метка научит модель хуже, чем её отсутствие.
"""
import argparse
import os
from collections import Counter, defaultdict
from pathlib import Path

from core.content import CLASS_ALIASES, WASTE_INFO
from core.storage import SupabaseFeedbackStore

LABELS = list(WASTE_INFO) + list(CLASS_ALIASES)  # и старые метки (cardboard), их переведёт сборка датасета


def export(store, out_dir, labels=LABELS):
    """Скачать фото по папкам-меткам. Возвращает (сколько фото на метку, сколько спорных пропущено)."""
    out_dir = Path(out_dir)
    paths_by_md5 = defaultdict(list)
    for label in labels:
        for path in store.list_photos(label):
            paths_by_md5[Path(path).stem].append((label, path))
    counts, disputed = Counter(), 0
    for md5, entries in sorted(paths_by_md5.items()):
        if len({label for label, _ in entries}) > 1:
            disputed += 1
            continue
        label, path = entries[0]
        target = out_dir / label / f"{md5}.jpg"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(store.download(path))
        counts[label] += 1
    return counts, disputed


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="raw/feedback")
    args = parser.parse_args()
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not (url and key):
        raise SystemExit("Нужны SUPABASE_URL и SUPABASE_SERVICE_KEY (секретный ключ) — см. docs/TRAINING.md")
    counts, disputed = export(SupabaseFeedbackStore(url, key), args.out)
    print(f"Наших фото: {sum(counts.values())} ({', '.join(f'{k} — {v}' for k, v in sorted(counts.items())) or 'пока нет'})")
    if disputed:
        print(f"Пропущено спорных (разные метки у одного фото): {disputed}")


if __name__ == "__main__":
    main()
