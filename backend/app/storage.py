"""Nơi lưu file của lịch sử (ảnh đã giấu tin, file khoá, ảnh thu nhỏ).

- Mặc định: thư mục backend/data/files trên máy chủ.
- Khi đặt SUPABASE_URL và SUPABASE_SERVICE_KEY: Supabase Storage (bucket riêng tư, tự tạo
  nếu chưa có). Dùng khi máy chủ không có ổ đĩa lâu dài, ví dụ gói miễn phí của Render.

Khoá file có dạng "<id người dùng>/<id mục>.<đuôi>", do máy chủ tự tạo, không lấy từ request."""
from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from .config import settings
from .db import DATA_DIR

KEY_RE = re.compile(r"^\d{1,12}/[0-9a-f]{24}\.(png|npz|jpg)$")


_log = logging.getLogger("apex.storage")


class StorageError(RuntimeError):
    pass


def _check(key: str) -> str:
    if not KEY_RE.match(key):
        raise StorageError("Khoá file không hợp lệ.")
    return key


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self.root / _check(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        p = self.root / _check(key)
        return p.read_bytes() if p.is_file() else None

    def delete(self, keys: list[str]) -> None:
        for k in keys:
            (self.root / _check(k)).unlink(missing_ok=True)


class SupabaseStorage:
    """Gọi REST API của Supabase Storage bằng thư viện chuẩn, không cần cài thêm gói."""

    def __init__(self, url: str, key: str, bucket: str, timeout: float = 30):
        self.base = url.rstrip("/") + "/storage/v1"
        self.key = key
        self.bucket = bucket
        self.timeout = timeout
        self._bucket_ready = False
        self._lock = threading.Lock()

    def _request(self, method: str, path: str, body: bytes | None = None,
                 content_type: str = "application/json", extra: dict | None = None):
        auth = {} if self.key.startswith("sb_") else {"Authorization": f"Bearer {self.key}"}
        req = urllib.request.Request(self.base + path, data=body, method=method, headers={
            "apikey": self.key,
            **auth,
            "Content-Type": content_type,
            **(extra or {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise StorageError(f"Không kết nối được kho lưu trữ: {e}") from None

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        with self._lock:
            if self._bucket_ready:
                return
            status, body = self._request("POST", "/bucket", json.dumps(
                {"id": self.bucket, "name": self.bucket, "public": False}).encode())
            # 200 = vừa tạo; 400/409 kèm "already exists" = đã có sẵn.
            if status >= 300 and b"exist" not in body.lower():
                _log.error("Supabase bucket %s: %s", status, body[:300])
                raise StorageError(f"Không tạo được bucket lưu trữ ({status}).")
            self._bucket_ready = True

    def _obj(self, key: str) -> str:
        return f"/object/{quote(self.bucket)}/{quote(_check(key))}"

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._ensure_bucket()
        status, body = self._request("POST", self._obj(key), data, content_type, {"x-upsert": "true"})
        if status >= 300:
            _log.error("Supabase put %s: %s", status, body[:300])
            raise StorageError(f"Không lưu được file ({status}).")

    def get(self, key: str) -> bytes | None:
        status, body = self._request("GET", self._obj(key))
        if status == 200:
            return body
        if status in (400, 404):  # Supabase trả 400 hoặc 404 khi không có file
            return None
        raise StorageError(f"Không đọc được file ({status}).")

    def delete(self, keys: list[str]) -> None:
        if not keys:
            return
        for k in keys:
            _check(k)
        status, _ = self._request("DELETE", f"/object/{quote(self.bucket)}",
                                  json.dumps({"prefixes": keys}).encode())
        if status >= 300 and status != 404:
            raise StorageError(f"Không xoá được file ({status}).")


def _make():
    if settings.supabase_url and settings.supabase_service_key:
        return SupabaseStorage(settings.supabase_url, settings.supabase_service_key, settings.supabase_bucket)
    return LocalStorage(DATA_DIR / "files")


storage = _make()
