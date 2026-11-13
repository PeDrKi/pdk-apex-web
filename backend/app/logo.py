"""Chuyển logo <-> bytes để giấu vào ảnh (dựa trên examples/hide_image.py của apexmark).

Body logo:  mode (1) | height (2, BE) | width (2, BE) | dữ liệu điểm ảnh
    mode 0 = đen trắng, 1 bit/điểm ảnh (np.packbits), 1 = nét logo
    mode 1 = 256 mức xám, 1 byte/điểm ảnh

Logo được tự thu nhỏ (giữ tỉ lệ) cho vừa dung lượng còn lại của ảnh chứa.
"""
from __future__ import annotations

import struct

import numpy as np
from PIL import Image

from .config import settings
from .imaging import ImageError, open_checked

HEADER_LEN = 5
MAX_SIDE = 512
MODES = {"binary": 0, "gray": 1}


def _load_gray(data: bytes) -> np.ndarray:
    """Đọc logo thành ảnh xám; vùng trong suốt được coi là nền trắng."""
    img = open_checked(data, settings.max_pixels)
    if img.mode == "P":
        img = img.convert("RGBA")
    if "A" in img.getbands():
        rgba = np.asarray(img.convert("RGBA")).astype(np.float64)
        alpha = rgba[..., 3] / 255.0
        luma = 0.299 * rgba[..., 0] + 0.587 * rgba[..., 1] + 0.114 * rgba[..., 2]
        return luma * alpha + 255.0 * (1.0 - alpha)
    return np.asarray(img.convert("L")).astype(np.float64)


def _otsu(gray: np.ndarray) -> float:
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    total = gray.size
    sum_all = np.dot(np.arange(256), hist)
    sum_b = w_b = 0.0
    best_var, best_t = -1.0, 127.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        var = w_b * w_f * (sum_b / w_b - (sum_all - sum_b) / w_f) ** 2
        if var > best_var:
            best_var, best_t = var, float(t)
    return best_t


def _to_binary(gray: np.ndarray, invert: str) -> np.ndarray:
    """1 = nét logo. "auto": phần chiếm ít diện tích hơn là nét."""
    bright = gray > _otsu(gray)
    flip = bright.mean() > 0.5 if invert == "auto" else invert == "yes"
    return (~bright if flip else bright).astype(np.uint8)


def fit_size(h0: int, w0: int, max_body_bytes: int, mode: str,
             max_side: int = 0) -> tuple[int, int]:
    """max_side > 0: giới hạn cạnh dài của logo (logo nhỏ hơn -> còn chỗ để dự phòng)."""
    bits_per_px = 1 if mode == "binary" else 8
    budget_px = max(0, (max_body_bytes - HEADER_LEN) * 8 // bits_per_px)
    side = min(MAX_SIDE, max_side) if max_side > 0 else MAX_SIDE
    scale = min(1.0, (budget_px / (h0 * w0)) ** 0.5, side / max(h0, w0))
    h, w = max(1, int(h0 * scale)), max(1, int(w0 * scale))
    while h * w > budget_px and (h > 1 or w > 1):
        h, w = max(1, h - 1), max(1, w - 1)
    return h, w


def encode_logo(data: bytes, max_body_bytes: int, mode: str = "binary",
                invert: str = "auto", max_side: int = 0) -> tuple[bytes, np.ndarray]:
    """Trả về (body để giấu, ảnh xem trước uint8 đúng như sẽ đọc ra)."""
    if mode not in MODES:
        raise ImageError("Chế độ logo không hợp lệ.")
    gray = _load_gray(data)
    h0, w0 = gray.shape
    h, w = fit_size(h0, w0, max_body_bytes, mode, max_side)
    if h * w < 64:
        raise ImageError("Ảnh chứa quá nhỏ để giấu logo. Hãy dùng ảnh lớn hơn, giảm độ "
                         "dự phòng hoặc chọn chế độ đen trắng.")
    if (h, w) != (h0, w0):
        gray = np.asarray(Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8))
                          .resize((w, h), Image.LANCZOS)).astype(np.float64)

    head = struct.pack(">BHH", MODES[mode], h, w)
    if mode == "binary":
        ink = _to_binary(gray, invert)
        return head + np.packbits(ink.ravel()).tobytes(), render(ink, 0)
    px = np.clip(gray, 0, 255).astype(np.uint8)
    return head + px.tobytes(), px


def render(arr: np.ndarray, mode_id: int) -> np.ndarray:
    """Đen trắng: nét logo màu đen trên nền trắng."""
    return ((1 - arr) * 255).astype(np.uint8) if mode_id == 0 else arr


def header_of(body: bytes) -> tuple[int, int, int]:
    return struct.unpack(">BHH", body[:HEADER_LEN])


def decode_logo(body: bytes, header: tuple[int, int, int] | None = None) -> np.ndarray:
    """header: (mode, h, w) lưu trong file khoá — dùng thay cho header trong ảnh,
    vì header trong ảnh có thể bị lật bit khi ảnh bị nén/cắt."""
    if len(body) < HEADER_LEN:
        raise ValueError("Dữ liệu logo bị hỏng.")
    mode_id, h, w = header if header is not None else header_of(body)
    if mode_id not in (0, 1) or not (0 < h <= MAX_SIDE and 0 < w <= MAX_SIDE):
        raise ValueError("Không đọc được thông tin logo: ảnh đã bị biến đổi quá mạnh hoặc sai khoá.")
    data = np.frombuffer(body[HEADER_LEN:], dtype=np.uint8)
    if mode_id == 0:
        bits = np.unpackbits(data)
        if bits.size < h * w:
            bits = np.pad(bits, (0, h * w - bits.size))
        return render(bits[:h * w].reshape(h, w), 0)
    if data.size < h * w:
        data = np.pad(data, (0, h * w - data.size), constant_values=255)
    return data[:h * w].reshape(h, w)
