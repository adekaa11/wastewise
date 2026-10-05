"""Проверка requirements.txt без установки: что именно поставит Streamlit Cloud.

- torch и torchvision — CPU-сборки (версия с меткой +cpu), а не CUDA с PyPI;
- никаких nvidia-* и triton (это ~2–3 ГБ CUDA-библиотек, на сервере без видеокарты не нужны);
  исключение — nvidia-ml-py: крошечная Python-обёртка NVML (~50 КБ), её требует ultralytics;
- OpenCV < 5 (в OpenCV 5 нет cv2.CascadeClassifier, см. core/model.py).

Принимает отчёт pip (JSON) или вывод uv:
    pip install --dry-run --ignore-installed --quiet --report pip.json -r requirements.txt
    uv pip install --dry-run --system -r requirements.txt > uv.txt 2>&1
    python .github/check_requirements.py pip.json uv.txt
"""
import json
import os
import re
import sys

NOT_CUDA = {"nvidia-ml-py"}  # не CUDA-библиотека, а Python-обёртка для опроса видеокарт (нужна ultralytics)
WATCH = ("requests", "urllib3", "certifi")  # раньше uv брал их из индекса PyTorch, где лежат старые версии
# Не старше этих версий: в более старых — известные уязвимости (requests CVE-2024-47081,
# urllib3 CVE-2024-37891, certifi CVE-2024-39689).
MIN_VERSIONS = {"requests": (2, 32, 4), "urllib3": (2, 2, 2), "certifi": (2024, 7, 4)}


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
    cuda = sorted(n for n in pkgs if (n.startswith("nvidia-") and n not in NOT_CUDA) or n == "triton")
    if cuda:
        found.append("тянутся CUDA-библиотеки: " + ", ".join(cuda))
    opencv = pkgs.get("opencv-python")
    if not opencv or int(opencv.split(".")[0]) >= 5:
        found.append(f"opencv-python=={opencv}: нужен < 5")
    for name, minimum in MIN_VERSIONS.items():
        version = pkgs.get(name)
        if version and _release(version) < minimum:
            found.append(f"{name}=={version}: старая версия с известными уязвимостями (нужна ≥ {'.'.join(map(str, minimum))})")
    return found


def _release(version):
    """«2.28.1» → (2, 28, 1); суффиксы вроде «.post0» и «+cpu» отбрасываются."""
    parts = []
    for piece in re.split(r"[.+]", version)[:3]:
        digits = re.match(r"\d+", piece)
        parts.append(int(digits.group()) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))


if __name__ == "__main__":
    failed = False
    results = {}
    for path in sys.argv[1:]:
        pkgs = results[path] = resolved(path)
        errors = problems(pkgs) if pkgs else ["пакеты не найдены — разрешение зависимостей не удалось?"]
        line = (f"{path}: torch=={pkgs.get('torch')}, torchvision=={pkgs.get('torchvision')}, "
                f"opencv-python=={pkgs.get('opencv-python')}, "
                + ", ".join(f"{n}=={pkgs.get(n)}" for n in WATCH) + f", всего пакетов: {len(pkgs)}")
        print(line)
        if os.getenv("GITHUB_ACTIONS"):  # видно на странице запуска (Annotations), не открывая логи
            print(f"::notice title={os.path.basename(path)}::{line}")
        for e in errors:
            print(f"  ❌ {e}")
        failed |= bool(errors)
    # не ошибка, а подсказка: где pip и uv выбрали разные версии важных сетевых пакетов
    if len(results) == 2:
        (a, pa), (b, pb) = results.items()
        for name in WATCH:
            if pa.get(name) != pb.get(name):
                print(f"  ⚠️ {name}: {a} → {pa.get(name)}, {b} → {pb.get(name)}")
    sys.exit(1 if failed else 0)
