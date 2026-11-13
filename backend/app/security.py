"""Các lớp bảo vệ của API: giới hạn kích thước request, giới hạn tần suất,
header bảo mật, và kiểm tra file khoá do người dùng tải lên."""
from __future__ import annotations

import io
import math
import time
import zipfile
from collections import defaultdict, deque

import numpy as np

from .config import settings

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
}


class _TooLarge(Exception):
    pass


class RateLimiter:
    """Cửa sổ trượt 60 giây theo IP, lưu trong bộ nhớ của tiến trình."""

    def __init__(self, per_minute: int):
        self.limit = per_minute
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self._hits) > 10_000:  # không để bảng phình vô hạn
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 60]:
                del self._hits[k]
        return True


rate_limiter = RateLimiter(settings.rate_limit_per_min)


def client_ip(scope) -> str:
    """IP dùng để giới hạn tần suất. Sau proxy (Render, Vercel, Nginx…) IP kết nối là của proxy,
    nên lấy IP đầu tiên trong header do proxy ghi (CLIENT_IP_HEADER)."""
    if settings.client_ip_header:
        for k, v in scope.get("headers") or []:
            if k.decode("latin-1").lower() == settings.client_ip_header:
                first = v.decode("latin-1").split(",")[0].strip()
                if first:
                    return first[:64]
    client = scope.get("client")
    return client[0] if client else "?"


def _rate_limited(method: str, path: str) -> bool:
    """Giới hạn mọi yêu cầu ghi/xoá và các yêu cầu đọc file lịch sử (tốn băng thông)."""
    if not path.startswith("/api/"):
        return False
    return method in ("POST", "PUT", "PATCH", "DELETE") or path.startswith("/api/history")


async def _plain(send, status: int, detail: str, extra: list | None = None):
    body = ('{"detail":"' + detail + '"}').encode("utf-8")
    headers = [(b"content-type", b"application/json; charset=utf-8"),
               (b"content-length", str(len(body)).encode())]
    headers += [(k.encode(), v.encode()) for k, v in SECURITY_HEADERS.items()]
    await send({"type": "http.response.start", "status": status, "headers": headers + (extra or [])})
    await send({"type": "http.response.body", "body": body})


class SecurityMiddleware:
    """ASGI middleware thuần: chạy TRƯỚC khi Starlette đọc/ghi tạm body ra đĩa."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        headers = dict(scope.get("headers") or [])
        is_api_write = scope["method"] in ("POST", "PUT", "PATCH") and path.startswith("/api/")
        limit = settings.max_request_bytes

        if _rate_limited(scope["method"], path):
            if not rate_limiter.allow(client_ip(scope)):
                return await _plain(send, 429, "Bạn gửi quá nhiều yêu cầu. Hãy thử lại sau một phút.",
                                    [(b"retry-after", b"60")])
        if is_api_write:
            try:
                declared = int(headers.get(b"content-length", b"-1"))
            except ValueError:
                declared = -1
            if declared > limit:
                return await _plain(send, 413, "Dữ liệu gửi lên quá lớn.")

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    raise _TooLarge()
            return msg

        https = scope.get("scheme") == "https" or headers.get(b"x-forwarded-proto") == b"https"

        async def secure_send(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
                present = {k.lower() for k, _ in msg.get("headers", [])}
                extra = [(k.encode(), v.encode()) for k, v in SECURITY_HEADERS.items()
                         if k.encode() not in present]
                if path.startswith("/api/"):
                    if b"cache-control" not in present:
                        extra.append((b"cache-control", b"no-store"))
                elif msg.get("status") == 200 and b"cache-control" not in present:
                    if path.startswith("/assets/"):
                        # Tên file trong /assets có mã băm nội dung nên cache vĩnh viễn được.
                        extra.append((b"cache-control", b"public, max-age=31536000, immutable"))
                    elif path.rsplit(".", 1)[-1] in ("png", "ico", "svg", "webp", "woff2"):
                        extra.append((b"cache-control", b"public, max-age=86400"))
                    else:
                        extra.append((b"cache-control", b"no-cache"))  # index.html: luôn hỏi lại
                if https:
                    extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                msg = {**msg, "headers": list(msg.get("headers", [])) + extra}
            await send(msg)

        try:
            await self.app(scope, limited_receive, secure_send)
        except _TooLarge:
            if not started:
                await _plain(send, 413, "Dữ liệu gửi lên quá lớn.")


# ---------------------------------------------------------------- file khoá

class KeysError(ValueError):
    pass


MAX_KEYS_UNCOMPRESSED = 64 * 1024 * 1024
MAX_KEYS_MEMBERS = 32
MAX_THUMB_SIDE = 2048
MAX_COORD = 100_000


def check_npz_size(data: bytes) -> None:
    """Chặn "zip bomb": file .npz nhỏ nhưng giải nén ra hàng GB."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
    except zipfile.BadZipFile:
        raise KeysError("File khoá không hợp lệ (cần file .npz tạo lúc giấu tin).")
    if len(infos) > MAX_KEYS_MEMBERS or sum(i.file_size for i in infos) > MAX_KEYS_UNCOMPRESSED:
        raise KeysError("File khoá quá lớn hoặc bất thường.")


def parse_keys(data: bytes) -> dict:
    """Đọc và kiểm tra file khoá .npz không tin cậy. Ném KeysError nếu không hợp lệ."""
    check_npz_size(data)
    try:
        # allow_pickle=False: không bao giờ giải tuần tự hoá đối tượng Python từ file tải lên.
        with np.load(io.BytesIO(data), allow_pickle=False) as z:
            keys = {k: z[k] for k in z.files}
        for k in ("n_bits", "n_bins", "redundancy"):
            if k in keys:
                keys[k] = int(keys[k])
        for k in ("use_ngdc", "is_color"):
            if k in keys:
                keys[k] = bool(keys[k])
    except Exception:
        raise KeysError("File khoá không hợp lệ (cần file .npz tạo lúc giấu tin).")
    validate_keys(keys)
    return keys


def _ints(a, name: str, lo: int, hi: int, shape_len: int | None = None) -> np.ndarray:
    a = np.asarray(a)
    if a.dtype.kind not in "iu" or (shape_len is not None and a.shape != (shape_len,)):
        raise KeysError(f"File khoá hỏng: trường {name} không hợp lệ.")
    if a.size and (int(a.min()) < lo or int(a.max()) > hi):
        raise KeysError(f"File khoá hỏng: trường {name} nằm ngoài phạm vi.")
    return a


def _floats(a, name: str, min_len: int, positive: bool = False) -> np.ndarray:
    a = np.asarray(a)
    if a.dtype.kind not in "fiu" or a.ndim != 1 or a.size < min_len or not np.isfinite(a).all():
        raise KeysError(f"File khoá hỏng: trường {name} không hợp lệ.")
    if positive and a.size and float(a.min()) <= 0:
        raise KeysError(f"File khoá hỏng: trường {name} phải dương.")
    return a


def validate_keys(keys: dict) -> None:
    """File khoá là dữ liệu KHÔNG TIN CẬY: kiểm tra mọi trường trước khi đưa
    vào apexmark, để file cố tình làm sai không gây lỗi chỉ số, chia cho 0
    hay cấp phát bộ nhớ khổng lồ."""
    for k in ("selected_coords", "deltas", "K1_perm", "n_bits"):
        if k not in keys:
            raise KeysError("File khoá thiếu dữ liệu apexmark.")

    max_slots = settings.max_pixels // 16
    n_bits = int(keys["n_bits"])
    redundancy = int(keys.get("redundancy", 1))
    if not (1 <= redundancy <= settings.max_redundancy and 1 <= n_bits <= max_slots):
        raise KeysError("File khoá hỏng: số bit hoặc độ dự phòng không hợp lệ.")
    n_slots = n_bits * redundancy
    if n_slots > max_slots:
        raise KeysError("File khoá hỏng: quá nhiều khối.")

    coords = np.asarray(keys["selected_coords"])
    if coords.dtype.kind not in "iu" or coords.shape != (n_slots, 2):
        raise KeysError("File khoá hỏng: toạ độ khối không hợp lệ.")
    if int(coords.min()) < 0 or int(coords.max()) > MAX_COORD:
        raise KeysError("File khoá hỏng: toạ độ khối nằm ngoài phạm vi.")

    if _floats(keys["deltas"], "deltas", n_slots, positive=True).size != n_slots:
        raise KeysError("File khoá hỏng: trường deltas không hợp lệ.")

    perm = _ints(keys["K1_perm"], "K1_perm", 0, n_bits - 1, n_bits)
    if np.unique(perm).size != n_bits:
        raise KeysError("File khoá hỏng: hoán vị không hợp lệ.")

    if "slot_bit_map" in keys:
        _ints(keys["slot_bit_map"], "slot_bit_map", 0, n_bits - 1, n_slots)
    elif redundancy > 1:
        raise KeysError("File khoá thiếu bảng dự phòng.")

    if bool(keys.get("use_ngdc", False)):
        for k in ("ngdc_bin_ids", "ngdc_mu1_bin", "ngdc_sigma1_bin", "n_bins"):
            if k not in keys:
                raise KeysError("File khoá thiếu tham số N-GDC.")
        n_bins = int(keys["n_bins"])
        if not 1 <= n_bins <= 256:
            raise KeysError("File khoá hỏng: số bin không hợp lệ.")
        _ints(keys["ngdc_bin_ids"], "ngdc_bin_ids", 0, n_bins - 1, n_slots)
        _floats(keys["ngdc_mu1_bin"], "ngdc_mu1_bin", n_bins)
        _floats(keys["ngdc_sigma1_bin"], "ngdc_sigma1_bin", n_bins)

    if "thumbnail" in keys or "orig_shape" in keys:
        if "thumbnail" not in keys or "orig_shape" not in keys:
            raise KeysError("File khoá hỏng: thiếu ảnh thu nhỏ hoặc kích thước gốc.")
        th = np.asarray(keys["thumbnail"])
        if (th.dtype.kind not in "fiu" or th.ndim != 2 or min(th.shape) < 8
                or max(th.shape) > MAX_THUMB_SIDE or not np.isfinite(th).all()):
            raise KeysError("File khoá hỏng: ảnh thu nhỏ không hợp lệ.")
        shape = _ints(keys["orig_shape"], "orig_shape", 4, MAX_COORD, 2)
        if math.prod(int(v) for v in shape) > settings.max_pixels:
            raise KeysError("File khoá hỏng: kích thước gốc quá lớn.")

    if "logo_header" in keys:
        _ints(keys["logo_header"], "logo_header", 0, 4096, 3)
    if "payload_kind" in keys and str(keys["payload_kind"]) not in ("text", "logo", "file"):
        raise KeysError("File khoá hỏng: loại nội dung không hợp lệ.")
