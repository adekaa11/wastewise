"""Фото «Модель ошиблась» + метка пользователя → наш датасет (core/storage.py).

На сайте — приватный бакет Supabase Storage (здесь — поддельный сервер с тем же REST API),
локально — папка data/feedback. Раскладка одинаковая: <метка>/<md5>.jpg.
"""
import io

import pytest
from PIL import Image

from conftest import photo, start_app
from core import db, storage
from core.content import POINTS_PER_FEEDBACK

HASH = "0123456789abcdef0123456789abcdef"


def jpeg(color="orange", size=(64, 48)):
    return storage.encode_photo(Image.new("RGB", size, color))


def test_encode_photo_shrinks_and_keeps_original():
    original = Image.new("RGB", (1280, 960), "orange")
    data = storage.encode_photo(original)
    saved = Image.open(io.BytesIO(data))
    assert saved.format == "JPEG" and saved.size == (800, 600)
    assert original.size == (1280, 960)  # фото на странице не меняется


def test_local_store_writes_label_folder(tmp_path):
    path = storage.LocalFeedbackStore(tmp_path).save("glass", HASH, b"img")
    assert path == f"local:glass/{HASH}.jpg"
    assert (tmp_path / "glass" / f"{HASH}.jpg").read_bytes() == b"img"


def test_supabase_store_uploads_to_private_bucket(fake_storage):
    store = storage.SupabaseFeedbackStore(fake_storage.url, fake_storage.key)
    data = jpeg()
    assert store.save("ewaste", HASH, data) == f"supabase:feedback/ewaste/{HASH}.jpg"
    assert fake_storage.objects[f"feedback/ewaste/{HASH}.jpg"] == (data, "image/jpeg")
    assert store.bucket_is_public() is False
    assert store.download(f"ewaste/{HASH}.jpg") == data
    store.save("ewaste", HASH, b"new")  # то же фото ещё раз — перезапись, а не ошибка
    assert fake_storage.objects[f"feedback/ewaste/{HASH}.jpg"][0] == b"new"


@pytest.mark.parametrize("key, sends_bearer", [
    ("sb_secret_abc123", False),            # новый секретный ключ — только в apikey
    ("eyJhbGciOiJIUzI1NiJ9.e30.sig", True),  # старый service_role (JWT) — ещё и в Authorization
])
def test_both_kinds_of_supabase_keys(key, sends_bearer):
    from fake_supabase import FakeStorage

    fake = FakeStorage(key=key)
    try:
        storage.SupabaseFeedbackStore(fake.url, key).save("glass", HASH, b"x")
        headers = fake.requests[-1][2]
        assert headers["apikey"] == key
        assert ("Authorization" in headers) is sends_bearer
    finally:
        fake.close()


def test_missing_bucket_is_created_private(fake_storage):
    fake_storage.buckets.clear()  # миграция не смогла создать бакет (нет прав)
    store = storage.SupabaseFeedbackStore(fake_storage.url, fake_storage.key)
    store.save("organic", HASH, b"x")
    assert fake_storage.buckets["feedback"]["public"] is False
    assert f"feedback/organic/{HASH}.jpg" in fake_storage.objects


def test_errors_become_storage_error(fake_storage):
    fake_storage.fail_uploads = True
    with pytest.raises(storage.StorageError, match="HTTP 500"):
        storage.SupabaseFeedbackStore(fake_storage.url, fake_storage.key).save("glass", HASH, b"x")
    with pytest.raises(storage.StorageError, match="HTTP 401"):
        storage.SupabaseFeedbackStore(fake_storage.url, "sb_secret_wrong").save("glass", HASH, b"x")
    with pytest.raises(storage.StorageError, match="недоступен"):
        storage.SupabaseFeedbackStore("http://127.0.0.1:1", "sb_secret_x", timeout=2).save("glass", HASH, b"x")


def test_list_photos_pages_through_folder(fake_storage):
    store = storage.SupabaseFeedbackStore(fake_storage.url, fake_storage.key)
    for i in range(5):
        store.save("paper", f"{i:032x}", b"x")
    store.save("glass", HASH, b"x")
    assert list(store.list_photos("paper", page_size=2)) == [f"paper/{i:032x}.jpg" for i in range(5)]


def test_feedback_path_is_stored_with_scan(store):
    scan_id = db.save_scan(store, None, "glass", 0.4, HASH)
    db.correct_scan(store, scan_id, "plastic", f"supabase:feedback/plastic/{HASH}.jpg")
    row = store.execute("SELECT corrected, feedback_path FROM scans WHERE id = ?", (scan_id,)).fetchone()
    assert tuple(row) == ("plastic", f"supabase:feedback/plastic/{HASH}.jpg")


# ---------- на сайте ----------

def _correct_last_photo(app, label):
    app.at.selectbox[0].set_value(label)
    app.run()
    app.button("Отправить исправление").click()
    app.run()


def test_site_saves_feedback_to_supabase(tmp_path, monkeypatch, fake_storage):
    app = start_app(tmp_path, monkeypatch, secrets={
        "SUPABASE_URL": fake_storage.url, "SUPABASE_SERVICE_KEY": fake_storage.key})
    app.register_and_login()
    app.go("Распознать отходы").upload(photo("orange"))
    before = app.points()
    _correct_last_photo(app, "glass")

    [(key, (data, content_type))] = fake_storage.objects.items()
    file_key = key.split("/")[-1].removesuffix(".jpg")
    assert key == f"feedback/glass/{file_key}.jpg" and content_type == "image/jpeg"
    assert Image.open(io.BytesIO(data)).format == "JPEG"
    assert app.query("SELECT corrected, feedback_path FROM scans") == [("glass", f"supabase:{key}")]
    assert app.points() - before == POINTS_PER_FEEDBACK
    assert not app.feedback_dir.exists()  # на диск сервера ничего не легло


def test_site_does_not_award_points_if_upload_fails(tmp_path, monkeypatch, fake_storage):
    fake_storage.fail_uploads = True
    app = start_app(tmp_path, monkeypatch, secrets={
        "SUPABASE_URL": fake_storage.url, "SUPABASE_SERVICE_KEY": fake_storage.key})
    app.register_and_login()
    app.go("Распознать отходы").upload(photo("orange"))
    before = app.points()
    _correct_last_photo(app, "glass")

    assert any("Не удалось сохранить фото" in e.value for e in app.at.error)
    assert app.points() == before
    assert app.query("SELECT corrected, feedback_path FROM scans") == [(None, None)]
    assert not app.button("Отправить исправление").disabled  # можно попробовать ещё раз

    fake_storage.fail_uploads = False
    app.button("Отправить исправление").click()
    app.run()
    assert app.points() - before == POINTS_PER_FEEDBACK


def test_site_without_supabase_saves_to_local_folder(app):
    app.go("Распознать отходы").upload(photo("orange"))
    _correct_last_photo(app, "metal")
    [saved] = list((app.feedback_dir / "metal").glob("*.jpg"))
    assert app.query("SELECT feedback_path FROM scans") == [(f"local:metal/{saved.name}",)]
