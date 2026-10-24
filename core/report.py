"""Отчёт учителя: как школа сортирует у экобоксов (QR-режим, core/qr.py).

На вход — строки из db.school_scans: (дата UTC, класс, ответ модели, исправление, бак).
Итоговый тип фото — исправление пользователя, если оно есть, иначе ответ модели.
«Ошибка у бака» — итоговый тип не совпадает с баком, у которого сфотографировали.

Функции чистые (без Streamlit и базы) — их легко проверить тестами.
"""
import csv
import io
from datetime import date, datetime, timedelta

from .content import canonical

LOCAL_OFFSET = timedelta(hours=5)  # база хранит UTC, школы — в Казахстане (UTC+5)
NO_CLASS = "—"  # гости и ученики без указанного класса


def local_day(value):
    """Дата из базы (строка SQLite или datetime Postgres, UTC) → день по времени Казахстана."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        return (value.replace(tzinfo=None) + LOCAL_OFFSET).date()
    return value if isinstance(value, date) else None


def _share(ok, total):
    return ok / total if total else None


def summarize(rows):
    """Сводка для страницы учителя.

    total — всего фото; at_bins — сделанных у бака (по QR); errors — не в тот бак;
    accuracy — доля верных у баков (None, если у баков ещё не фотографировали);
    classes — [(класс, фото, точность)], mistakes — [((бак, что это было), сколько)],
    daily — [(день, фото, точность)], types — [(тип, сколько)].
    """
    total = at_bins = errors = 0
    classes, daily, mistakes, types = {}, {}, {}, {}
    for when, label, predicted, corrected, box in rows:
        final = canonical(corrected or predicted)
        label = (label or "").strip() or NO_CLASS
        day = local_day(when)
        total += 1
        types[final] = types.get(final, 0) + 1
        per_class = classes.setdefault(label, [0, 0, 0])  # фото, у баков, верно
        per_day = daily.setdefault(day, [0, 0, 0])
        per_class[0] += 1
        per_day[0] += 1
        if box:
            at_bins += 1
            per_class[1] += 1
            per_day[1] += 1
            if final == box:
                per_class[2] += 1
                per_day[2] += 1
            else:
                errors += 1
                mistakes[(box, final)] = mistakes.get((box, final), 0) + 1
    return {
        "total": total,
        "at_bins": at_bins,
        "errors": errors,
        "accuracy": _share(at_bins - errors, at_bins),
        "classes": sorted(((k, n, _share(ok, q)) for k, (n, q, ok) in classes.items()),
                          key=lambda r: (-r[1], r[0])),
        "mistakes": sorted(mistakes.items(), key=lambda kv: (-kv[1], kv[0])),
        "daily": sorted(((d, n, _share(ok, q)) for d, (n, q, ok) in daily.items() if d), key=lambda r: r[0]),
        "types": sorted(types.items(), key=lambda kv: (-kv[1], kv[0])),
    }


def to_csv(rows, tr=lambda s: s, name=lambda cls: cls):
    """Отчёт для пилота — CSV, который открывается в Excel (UTF-8 с BOM, разделитель «;»).

    tr — перевод заголовков, name — название типа отходов на языке сайта.
    """
    buf = io.StringIO()
    out = csv.writer(buf, delimiter=";")
    out.writerow([tr("Дата"), tr("Класс"), tr("Бак"), tr("Итоговый тип"), tr("Ответ модели"),
                  tr("Исправлено"), tr("Верно у бака")])
    for when, label, predicted, corrected, box in rows:
        final = canonical(corrected or predicted)
        day = local_day(when)
        verdict = "" if not box else tr("да") if final == box else tr("нет")
        out.writerow([day.isoformat() if day else "", label or NO_CLASS, name(box) if box else "", name(final),
                      name(canonical(predicted)), name(canonical(corrected)) if corrected else "", verdict])
    return buf.getvalue().encode("utf-8-sig")
