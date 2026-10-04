"""Проверка requirements.txt без установки: что именно поставит Streamlit Cloud.

- torch и torchvision — CPU-сборки (версия с меткой +cpu), а не CUDA с PyPI;
- никаких nvidia-* и triton (это ~2–3 ГБ CUDA-библиотек, на сервере без видеокарты не нужны);
- OpenCV < 5 (в OpenCV 5 нет cv2.CascadeClassifier, см. core/model.py).

Принимает отчёт pip (JSON) или вывод uv:
    pip install --dry-run --ignore-installed --quiet --report pip.json -r requirements.txt
    uv pip install --dry-run --system -r requirements.txt > uv.txt 2>&1
    python .github/check_requirements.py pip.json uv.txt
"""
import json
import re
import sys


def resolved(path):
    """{пакет: версия} из отчёта pip (.json) или из вывода `uv pip install --dry-run`."""
    text = open(path, encoding="utf-8").read()
    if path.endswith(".json"):
        pairs = ((p["metadata"]["name"], p["metadata"]["version"]) for p in json.loads(text)["install"])
    else:
        pairs = re.findall(r"^\s*\+\s*([A-Za-z0-9_.\-]+)==(\S+)", text, flags=re.M)
    return {name.lower().replace("_", "-"): version for name, version in pairs}


def problems(pkgs):
    found = []
    for name in ("torch", "torchvision"):
        version = pkgs.get(name)
        if not version or not version.endswith("+cpu"):
            found.append(f"{name}=={version}: ожидалась CPU-сборка (+cpu)")
    cuda = sorted(n for n in pkgs if n.startswith("nvidia-") or n == "triton")
    if cuda:
        found.append("тянутся CUDA-библиотеки: " + ", ".join(cuda))
    opencv = pkgs.get("opencv-python")
    if not opencv or int(opencv.split(".")[0]) >= 5:
        found.append(f"opencv-python=={opencv}: нужен < 5")
    return found


if __name__ == "__main__":
    failed = False
    for path in sys.argv[1:]:
        pkgs = resolved(path)
        errors = problems(pkgs) if pkgs else ["пакеты не найдены — разрешение зависимостей не удалось?"]
        print(f"{path}: torch=={pkgs.get('torch')}, torchvision=={pkgs.get('torchvision')}, "
              f"opencv-python=={pkgs.get('opencv-python')}, всего пакетов: {len(pkgs)}")
        for e in errors:
            print(f"  ❌ {e}")
        failed |= bool(errors)
    sys.exit(1 if failed else 0)
