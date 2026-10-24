"""Свежие модули после обновления сайта.

Streamlit Cloud после git push перезапускает app.py, но процесс Python не перезапускает: модули из core/
остаются в памяти старыми. Тогда новый app.py просит у старого core/content.py то, чего там ещё нет, —
и сайт падает с ImportError (так было с KZ_FACTS 24.10.2026).

refresh() перечитывает модуль, только если его файл на диске изменился с момента загрузки. В обычной работе
(без обновлений) ничего не перечитывается — это быстро и не сбрасывает состояние (лимиты ИИ, замок базы).
"""
import importlib
import sys
from pathlib import Path

# Порядок важен: сначала модули без зависимостей, потом те, что из них импортируют.
ORDER = ["core.content", "core.content_kk", "core.i18n_kk", "core.i18n", "core.pg", "core.db", "core.model",
         "core.storage", "core.quiz", "core.qr", "core.report", "core.assistant", "core.roles", "core.ui"]


def _mtime(module):
    try:
        return Path(module.__file__).stat().st_mtime
    except (AttributeError, TypeError, OSError):
        return None


def refresh(names=ORDER):
    """Перед импортами в app.py: перечитать модули, загруженные раньше и с тех пор изменившиеся.

    Модуль без отметки _loaded_mtime загружен до появления этой проверки (старый процесс) — тоже перечитываем.
    Возвращает имена перечитанных (для лога и тестов).
    """
    reloaded = []
    for name in names:
        module = sys.modules.get(name)
        if module is None:
            continue  # ещё не загружен — app.py сейчас импортирует свежий
        # Если перечитали модуль, перечитываем и всё, что после него: иначе они держали бы ссылки на старые
        # объекты (from .content import WASTE_INFO).
        if reloaded or getattr(module, "_loaded_mtime", None) != _mtime(module):
            importlib.reload(module)
            reloaded.append(name)
    mark(names)
    return reloaded


def mark(names=ORDER):
    """После импортов в app.py: запомнить, с какой версии файла загружен каждый модуль."""
    for name in names:
        module = sys.modules.get(name)
        if module is not None:
            module._loaded_mtime = _mtime(module)
