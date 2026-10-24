"""QR-режим для школьных экобоксов.

На каждом баке в школе висит QR-код со ссылкой на сайт, например:
    https://wastewise.streamlit.app/?school_id=nis_astana&box=plastic
Ученик сканирует его телефоном — сайт сразу открывает «Распознать отходы» для этой школы и этого бака,
а после фото говорит: «верно, бросай сюда» или «не сюда, это стекло». Фото сохраняется с кодом школы
и бака — из этого учитель видит, какие классы сортируют и где чаще ошибаются (core/report.py).

Параметры ссылки приходят от кого угодно, поэтому строго проверяются: код школы — только латиница,
цифры, «_» и «-», бак — только один из 7 типов WASTE_INFO. Всё остальное игнорируется.
"""
import io
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from .content import WASTE_INFO, canonical

_SCHOOL_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


def valid_school_id(value):
    return bool(value) and bool(_SCHOOL_ID.match(str(value)))


@dataclass(frozen=True)
class QR:
    school_id: str | None = None
    bin: str | None = None

    def __bool__(self):
        return bool(self.school_id or self.bin)


def _first(params, *names):
    for name in names:
        value = params.get(name)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value:
            return str(value).strip().lower()
    return None


def parse(params):
    """Из параметров ссылки (st.query_params или dict) — QR(school_id, bin). Неверное — None."""
    school = _first(params, "school_id", "school")
    box = _first(params, "box", "bin")
    box = canonical(box) if box else None  # старые имена тоже понимаем: battery → ewaste
    return QR(school if valid_school_id(school) else None, box if box in WASTE_INFO else None)


def verdict(box, final_cls):
    """У бака: "ok" — предмет для этого бака, "wrong" — нет, None — бак неизвестен."""
    if not box:
        return None
    return "ok" if canonical(final_cls) == box else "wrong"


def link(base_url, school_id, box=None, lang=None):
    """Ссылка для QR-кода на баке. lang="kk" — сайт откроется сразу на казахском."""
    params = {"school_id": school_id}
    if box:
        params["box"] = box
    if lang and lang != "ru":
        params["lang"] = lang
    return f"{base_url.split('?')[0].rstrip('/')}/?{urlencode(params)}"


def png(url, scale=8):
    """QR-код ссылки картинкой PNG — распечатать и наклеить на бак."""
    import segno  # маленькая библиотека без зависимостей; импорт здесь — нужна только учителю

    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()
