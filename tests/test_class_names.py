"""Имена классов читаются из файла модели без torch — «Распознать отходы» открывается сразу."""
import io
import pickle
import time
import zipfile

from core import model
from core.content import WASTE_INFO


def test_real_model_names_without_loading_the_network():
    started = time.time()
    names = model.class_names()
    assert set(names.values()) == set(WASTE_INFO)  # все 7 типов, без загрузки torch
    assert time.time() - started < 2
    assert len(model.class_names(model.DETECTOR_PATH)) == 80  # детектор COCO


def test_broken_file_gives_none_so_app_falls_back(tmp_path):
    bad = tmp_path / "bad.pt"
    bad.write_bytes(b"not a zip")
    assert model.class_names(bad) is None


class Boom:
    def __reduce__(self):  # при обычной распаковке выполнил бы код
        return (exec, ("raise SystemExit('код из файла выполнился')",))


def test_code_inside_model_file_is_never_executed(tmp_path):
    path = tmp_path / "evil.pt"
    payload = pickle.dumps({"names": {0: "glass"}, "evil": Boom()})
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("evil/data.pkl", payload)
    assert model.class_names(path) == {0: "glass"}
