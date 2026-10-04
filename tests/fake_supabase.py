"""Поддельный Supabase Storage для тестов: тот же REST API (/storage/v1/…), данные — в памяти.

Проверяет ключ как настоящий шлюз: старый ключ service_role (JWT) — в apikey и Authorization,
новый sb_secret_… — только в apikey (в Authorization шлюз ждёт JWT пользователя).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

BUCKET_NOT_FOUND = {"statusCode": "404", "error": "Bucket not found", "message": "Bucket not found"}


class FakeStorage:
    def __init__(self, key="sb_secret_test-key", buckets=("feedback",)):
        self.key = key
        self.buckets = {name: {"id": name, "name": name, "public": False} for name in buckets}
        self.objects = {}  # "бакет/путь" → (байты, content-type)
        self.requests = []  # (метод, путь, заголовки)
        self.fail_uploads = False
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def _reply(self, code, body, content_type="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self):
                if self.headers.get("apikey") != fake.key:
                    return False
                if fake.key.startswith("eyJ"):
                    return self.headers.get("Authorization") == f"Bearer {fake.key}"
                return self.headers.get("Authorization") is None

            def _route(self, method):
                path = unquote(urlparse(self.path).path)
                fake.requests.append((method, path, dict(self.headers)))
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                if not self._authorized():
                    return self._reply(401, {"statusCode": "403", "error": "Unauthorized", "message": "Invalid key"})
                rest = path.removeprefix("/storage/v1/")
                if method == "POST" and rest == "bucket":
                    info = json.loads(body)
                    if info["id"] in fake.buckets:
                        return self._reply(400, {"statusCode": "409", "error": "Duplicate",
                                                 "message": "The resource already exists"})
                    fake.buckets[info["id"]] = {"id": info["id"], "name": info["name"], "public": info.get("public", False)}
                    return self._reply(200, {"name": info["id"]})
                if method == "GET" and rest.startswith("bucket/"):
                    bucket = fake.buckets.get(rest.removeprefix("bucket/"))
                    return self._reply(200, bucket) if bucket else self._reply(400, BUCKET_NOT_FOUND)
                if method == "POST" and rest.startswith("object/list/"):
                    bucket = rest.removeprefix("object/list/")
                    query = json.loads(body)
                    folder = query["prefix"].strip("/") + "/"
                    names = sorted(key.removeprefix(f"{bucket}/{folder}") for key in fake.objects
                                   if key.startswith(f"{bucket}/{folder}"))
                    page = names[query["offset"]:query["offset"] + query["limit"]]
                    return self._reply(200, [{"name": n, "id": f"id-{n}"} for n in page])
                if rest.startswith("object/"):
                    bucket, _, object_path = rest.removeprefix("object/").partition("/")
                    if bucket not in fake.buckets:
                        return self._reply(400, BUCKET_NOT_FOUND)
                    key = f"{bucket}/{object_path}"
                    if method == "GET":
                        if key not in fake.objects:
                            return self._reply(400, {"statusCode": "404", "error": "not_found", "message": "Object not found"})
                        return self._reply(200, fake.objects[key][0], fake.objects[key][1])
                    if fake.fail_uploads:
                        return self._reply(500, {"statusCode": "500", "error": "internal", "message": "boom"})
                    if key in fake.objects and self.headers.get("x-upsert") != "true":
                        return self._reply(400, {"statusCode": "409", "error": "Duplicate", "message": "exists"})
                    fake.objects[key] = (body, self.headers.get("Content-Type"))
                    return self._reply(200, {"Key": key})
                return self._reply(404, {"message": "no such route"})

        return Handler
