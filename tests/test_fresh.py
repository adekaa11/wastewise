"""После обновления кода на Streamlit Cloud изменившиеся модули core/ перечитываются (core/fresh.py)."""
import os
import sys
import time

from core import fresh


def test_changed_module_is_reloaded_with_its_dependents(tmp_path, monkeypatch):
    pkg = tmp_path / "pkgfresh"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "base.py").write_text("VALUE = 1\n")
    (pkg / "user.py").write_text("from .base import VALUE\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    import pkgfresh.base, pkgfresh.user  # noqa: E401
    names = ["pkgfresh.base", "pkgfresh.user"]
    fresh.mark(names)
    assert fresh.refresh(names) == []  # ничего не менялось — ничего не перечитываем

    (pkg / "base.py").write_text("VALUE = 2\nNEW = 'появилось после обновления'\n")
    later = time.time() + 5
    os.utime(pkg / "base.py", (later, later))
    assert fresh.refresh(names) == names  # и зависимый модуль тоже
    assert sys.modules["pkgfresh.base"].NEW and sys.modules["pkgfresh.user"].VALUE == 2


def test_module_loaded_before_the_check_is_reloaded(tmp_path, monkeypatch):
    """Старый процесс на сервере: модуль загружен до появления отметки — перечитываем (так чинится ImportError)."""
    (tmp_path / "oldmod.py").write_text("X = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    import oldmod  # noqa: F401
    assert fresh.refresh(["oldmod"]) == ["oldmod"]
    assert fresh.refresh(["oldmod"]) == []
