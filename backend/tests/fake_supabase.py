"""Máy chủ giả lập một phần REST API của Supabase Storage, chỉ dùng cho test.

Chạy riêng: python tests/fake_supabase.py 54321 KHOA_BI_MAT"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote


def make_server(port: int, key: str):
    buckets: dict[str, dict] = {}
    files: dict[tuple[str, str], tuple[bytes, str]] = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code: int, body=b"", ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth(self) -> bool:
            ok = self.headers.get("apikey") == key and self.headers.get("authorization") == f"Bearer {key}"
            if not ok:
                self._reply(401, {"message": "Invalid JWT"})
            return ok

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("content-length") or 0))

        def _split(self):
            path = unquote(self.path)
            assert path.startswith("/storage/v1/"), path
            return path[len("/storage/v1/"):]

        def do_POST(self):
            if not self._auth():
                return
            p, body = self._split(), self._body()
            if p == "bucket":
                b = json.loads(body)
                if b["id"] in buckets:
                    return self._reply(400, {"statusCode": "409", "error": "Duplicate", "message": "The resource already exists"})
                buckets[b["id"]] = b
                return self._reply(200, {"name": b["id"]})
            _, bucket, name = p.split("/", 2)
            if bucket not in buckets:
                return self._reply(404, {"message": "Bucket not found"})
            if (bucket, name) in files and self.headers.get("x-upsert") != "true":
                return self._reply(400, {"message": "The resource already exists"})
            files[(bucket, name)] = (body, self.headers.get("content-type", ""))
            self._reply(200, {"Key": f"{bucket}/{name}"})

        def do_GET(self):
            if not self._auth():
                return
            _, bucket, name = self._split().split("/", 2)
            if (bucket, name) not in files:
                return self._reply(400, {"statusCode": "404", "error": "not_found", "message": "Object not found"})
            data, ctype = files[(bucket, name)]
            self._reply(200, data, ctype)

        def do_DELETE(self):
            if not self._auth():
                return
            _, bucket = self._split().split("/", 1)
            gone = [{"name": n} for n in json.loads(self._body())["prefixes"] if files.pop((bucket, n), None)]
            self._reply(200, gone)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.files = files
    srv.buckets = buckets
    return srv


def start(port: int = 0, key: str = "test-key"):
    srv = make_server(port, key)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    make_server(int(sys.argv[1]), sys.argv[2]).serve_forever()
