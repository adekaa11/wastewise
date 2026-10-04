"""Ноутбук для Colab (train/wastewise_colab.ipynb): открывается, код без ошибок, команды и файлы на месте."""
import importlib
import json
import re

from conftest import ROOT

NOTEBOOK = ROOT / "train" / "wastewise_colab.ipynb"


def _cells(kind):
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    return ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == kind]


def test_python_in_every_code_cell_compiles():
    for source in _cells("code"):
        # строки !команда и %магия — для Colab; остальное должно быть правильным Python
        python = "\n".join("pass" if line.lstrip().startswith(("!", "%")) else line for line in source.splitlines())
        compile(python, str(NOTEBOOK), "exec")


def test_commands_and_files_exist():
    text = "\n".join(_cells("code") + _cells("markdown"))
    modules = set(re.findall(r"python -m (train\.\w+)", text)) | set(re.findall(r'"-m", "(train\.\w+)"', text))
    assert {"train.taco", "train.openimages", "train.feedback_export", "train.dataset", "train.train",
            "train.evaluate"} <= modules
    for name in modules:
        assert callable(getattr(importlib.import_module(name), "main")), name
    for path in ("assets/best.pt", "docs/TRAINING.md", "train/sources.py"):
        assert (ROOT / path).exists(), path


def test_old_and_new_model_are_compared_on_the_same_test_set():
    code = "\n".join(_cells("code"))
    assert "--out datasets/wastewise" in code
    assert "train.evaluate --test datasets/wastewise/test --old assets/best.pt --new models/new_best.pt" in code
    assert "--out models/new_best.pt" in code
