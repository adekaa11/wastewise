"""Фото «Модель ошиблась» — наш собственный датасет для дообучения.

Где хранятся:
- на сайте — приватный бакет Supabase Storage «feedback» (если заданы SUPABASE_URL и SUPABASE_SERVICE_KEY);
- локально и в тестах — папка data/feedback/, как раньше.

Раскладка одинаковая: <метка пользователя>/<md5 фото>.jpg. Это готовая структура датасета «папка = класс»:
train/feedback_export.py скачивает бакет в такие же папки, и обучение понимает их без переделки.
Кто и когда поставил метку, что ответила модель — в таблице scans (столбец feedback_path).
"""
import io
from pathlib import Path

BUCKET = "feedback"
MAX_SIDE = 800  # px: для обучения на 224–320 px хватает с запасом, а в бесплатном Supabase Storage — 1 ГБ


class StorageError(Exception):
    """Фото не сохранилось (нет сети, неверный ключ, …): сайт покажет сообщение и не начислит баллы."""


def encode_photo(image, max_side=MAX_SIDE):
    """Фото для датасета: JPEG, не больше max_side по длинной стороне."""
    photo = image.convert("RGB")
    photo.thumbnail((max_side, max_side))  # convert() уже сделал копию — исходное фото на странице не меняется
    buffer = io.BytesIO()
    photo.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def photo_path(label, image_hash):
    return f"{label}/{image_hash}.jpg"


class LocalFeedbackStore:
    """Папка на диске — локально и в тестах. На Streamlit Cloud она стирается при перезапуске."""

    kind = "local"

    def __init__(self, root):
        self.root = Path(root)

    def save(self, label, image_hash, data):
        path = self.root / photo_path(label, image_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"local:{photo_path(label, image_hash)}"


class SupabaseFeedbackStore:
    """Приватный бакет Supabase Storage через REST API — хватает requests (он приходит вместе со streamlit).

    Ключ — секретный (Project Settings → API Keys: secret sb_secret_… или старый service_role). Он обходит
    защиту бакета, поэтому живёт только на сервере (st.secrets) и никогда не попадает в браузер.
    """

    kind = "supabase"

    def __init__(self, url, key, bucket=BUCKET, timeout=20):
        import requests

        self._requests = requests
        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["apikey"] = key
        if key.startswith("eyJ"):  # старый ключ service_role — это JWT, его передают ещё и в Authorization
            self._session.headers["Authorization"] = f"Bearer {key}"
        # Новые ключи sb_secret_… — не JWT: их передают только в apikey, права подставляет шлюз Supabase.

    def save(self, label, image_hash, data):
        path = photo_path(label, image_hash)
        response = self._upload(path, data)
        if _bucket_missing(response):  # бакета нет (миграция не смогла его создать) — создаём и пробуем снова
            self.create_bucket()
            response = self._upload(path, data)
        _check(response, "загрузить фото")
        return f"supabase:{self.bucket}/{path}"

    def create_bucket(self):
        response = self._request("POST", "bucket", json={"id": self.bucket, "name": self.bucket, "public": False})
        if response.status_code >= 300 and "already exists" not in response.text.lower():
            _check(response, "создать бакет")

    def bucket_is_public(self):
        response = self._request("GET", f"bucket/{self.bucket}")
        _check(response, "проверить бакет")
        return bool(response.json().get("public"))

    # ---------- для train/feedback_export.py ----------

    def list_photos(self, folder, page_size=1000):
        """Все фото в папке-классе бакета: «glass/<md5>.jpg», …"""
        offset = 0
        while True:
            response = self._request("POST", f"object/list/{self.bucket}", json={
                "prefix": folder, "limit": page_size, "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            })
            _check(response, "получить список фото")
            items = response.json()
            for item in items:
                if item.get("id"):  # у вложенных «папок» id нет
                    yield f"{folder}/{item['name']}"
            if len(items) < page_size:
                return
            offset += page_size

    def download(self, path):
        response = self._request("GET", f"object/{self.bucket}/{path}")
        _check(response, "скачать фото")
        return response.content

    # ---------- HTTP ----------

    def _upload(self, path, data):
        return self._request("POST", f"object/{self.bucket}/{path}", data=data,
                             headers={"Content-Type": "image/jpeg", "x-upsert": "true"})

    def _request(self, method, path, **kwargs):
        try:
            return self._session.request(method, f"{self.base}/{path}", timeout=self.timeout, **kwargs)
        except self._requests.RequestException as error:
            raise StorageError(f"Supabase Storage недоступен: {type(error).__name__}") from error


def _bucket_missing(response):
    return response.status_code in (400, 404) and "bucket not found" in response.text.lower()


def _check(response, action):
    if response.status_code >= 300:
        # в ответе Supabase — короткое JSON-сообщение об ошибке, ключа в нём нет
        raise StorageError(f"Не удалось {action}: HTTP {response.status_code} {response.text[:200]}")
