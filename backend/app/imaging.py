"""Đọc/ghi ảnh từ bytes tải lên, tính PSNR."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import settings

# Chỉ mở các định dạng phổ biến: giảm bề mặt tấn công từ các bộ giải mã ít dùng của Pillow.
ALLOWED_FORMATS = ["PNG", "JPEG", "WEBP", "BMP", "TIFF", "GIF"]


class ImageError(ValueError):
    pass


def read_image(data: bytes) -> np.ndarray:
    img = open_checked(data, settings.max_pixels)

    if img.mode in ("LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
    elif img.mode not in ("L", "RGB", "RGBA"):
        img = img.convert("RGB")
    return np.array(img)


def open_checked(data: bytes, max_pixels: int) -> Image.Image:
    """Mở ảnh không tin cậy: kiểm tra định dạng và số điểm ảnh TRƯỚC khi giải nén."""
    try:
        img = Image.open(io.BytesIO(data), formats=ALLOWED_FORMATS)
        w, h = img.size
        if w * h > max_pixels:
            raise ImageError(f"Ảnh quá lớn ({w}x{h}). Giới hạn {max_pixels:,} điểm ảnh.")
        img = ImageOps.exif_transpose(img)
        img.load()
        return img
    except ImageError:
        raise
    except UnidentifiedImageError:
        raise ImageError("File không phải ảnh hợp lệ (hỗ trợ PNG, JPEG, WEBP, BMP, TIFF, GIF).")
    except Image.DecompressionBombError:
        raise ImageError("Ảnh quá lớn.")
    except Exception:
        raise ImageError("Không đọc được ảnh: file bị hỏng.")


def to_png_bytes(arr: np.ndarray) -> bytes:
    out = np.clip(arr, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    mse = float(np.mean((a - b) ** 2))
    if mse == 0:
        return float("inf")
    return 10.0 * np.log10(255.0 ** 2 / mse)
