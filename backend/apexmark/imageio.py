"""Chuẩn hoá ảnh đầu vào: chấp nhận mọi kiểu ảnh thông dụng, quy về thang
0-255 float64 để xử lý, rồi khôi phục lại đúng kiểu ban đầu ở đầu ra.

Xử lý được:
  - dtype: uint8, uint16, int16, float32/float64 (thang 0-1 hoặc 0-255), bool
  - kênh: grayscale (H,W), RGB (H,W,3), RGBA (H,W,4), grayscale-có-alpha (H,W,2),
          hoặc (H,W,1)
  - kênh alpha được GIỮ NGUYÊN, không nhúng vào (nhúng vào alpha sẽ làm hỏng
    độ trong suốt và thường bị mất khi lưu ảnh)
  - đường dẫn file hoặc đối tượng PIL.Image cũng nhận trực tiếp
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np


@dataclass
class ImageSpec:
    """Ghi lại đặc điểm ảnh gốc để khôi phục đúng như ban đầu ở đầu ra."""
    dtype: np.dtype
    was_float_unit: bool      # ảnh float thang 0..1 (không phải 0..255)
    scale_max: float          # giá trị lớn nhất của thang gốc (255, 65535, 1.0...)
    n_dims: int               # số chiều gốc (2 hoặc 3)
    n_channels: int           # số kênh gốc (0 nếu (H,W))
    alpha: Optional[np.ndarray]  # kênh alpha tách ra (nếu có)


def load_any(image: Any) -> np.ndarray:
    """Nhận đường dẫn / PIL.Image / numpy array, trả về numpy array."""
    if isinstance(image, np.ndarray):
        return image
    if isinstance(image, (str, os.PathLike)):
        from PIL import Image as _PILImage
        return np.array(_PILImage.open(image))
    if hasattr(image, "mode") and hasattr(image, "size"):  # PIL.Image
        return np.array(image)
    raise TypeError(
        f"Không nhận được ảnh từ kiểu {type(image).__name__}. Truyền vào numpy "
        f"array, đường dẫn file, hoặc PIL.Image."
    )


def normalize(image: Any) -> tuple[np.ndarray, ImageSpec]:
    """Quy ảnh về (H,W) hoặc (H,W,3) float64 thang 0-255, tách alpha ra riêng.

    Trả về (ảnh_đã_chuẩn_hoá, spec) — truyền spec vào denormalize() để khôi
    phục đúng dtype/số kênh/alpha ban đầu.
    """
    arr = load_any(image)
    if arr.ndim not in (2, 3):
        raise ValueError(f"Ảnh phải có 2 hoặc 3 chiều, nhận được shape {arr.shape}.")

    orig_dtype = arr.dtype
    n_dims = arr.ndim
    n_channels = arr.shape[2] if arr.ndim == 3 else 0

    # --- Tách alpha (nếu có) ---
    alpha = None
    work = arr
    if arr.ndim == 3:
        if arr.shape[2] == 2:        # grayscale + alpha
            alpha = arr[:, :, 1]
            work = arr[:, :, 0]
        elif arr.shape[2] == 4:      # RGBA
            alpha = arr[:, :, 3]
            work = arr[:, :, :3]
        elif arr.shape[2] == 1:      # (H,W,1)
            work = arr[:, :, 0]
        elif arr.shape[2] == 3:
            work = arr
        else:
            raise ValueError(
                f"Số kênh không hỗ trợ: {arr.shape[2]} (chỉ nhận 1, 2, 3 hoặc 4)."
            )

    work = work.astype(np.float64)

    # --- Quy về thang 0-255 ---
    was_float_unit = False
    if np.issubdtype(orig_dtype, np.floating):
        finite = work[np.isfinite(work)]
        vmax = float(finite.max()) if finite.size else 1.0
        vmin = float(finite.min()) if finite.size else 0.0
        if vmax <= 1.0 + 1e-9 and vmin >= -1e-9:
            was_float_unit = True
            scale_max = 1.0
            work = work * 255.0
        else:
            scale_max = 255.0
    elif orig_dtype == np.bool_:
        scale_max = 1.0
        was_float_unit = True
        work = work * 255.0
    else:
        info = np.iinfo(orig_dtype)
        scale_max = float(info.max)
        if scale_max != 255.0:
            work = work / scale_max * 255.0

    work = np.clip(work, 0, 255)
    spec = ImageSpec(dtype=orig_dtype, was_float_unit=was_float_unit,
                      scale_max=scale_max, n_dims=n_dims, n_channels=n_channels,
                      alpha=alpha)
    return work, spec


def denormalize(work: np.ndarray, spec: ImageSpec) -> np.ndarray:
    """Khôi phục ảnh về đúng dtype/số kênh/alpha như ảnh gốc."""
    out = np.clip(work, 0, 255)

    # --- Khôi phục thang giá trị ---
    if np.issubdtype(spec.dtype, np.floating):
        out = out / 255.0 if spec.was_float_unit else out
        out = out.astype(spec.dtype)
    elif spec.dtype == np.bool_:
        out = (out >= 127.5)
    else:
        if spec.scale_max != 255.0:
            out = out / 255.0 * spec.scale_max
        out = np.rint(out).astype(spec.dtype)

    # --- Khôi phục số kênh + ghép alpha ---
    if spec.n_dims == 3:
        if out.ndim == 2:
            out = out[:, :, None]
        if spec.n_channels == 1:
            pass  # đã là (H,W,1)
        elif spec.n_channels == 2:
            out = np.concatenate([out, spec.alpha[:, :, None].astype(out.dtype)], axis=2)
        elif spec.n_channels == 4:
            out = np.concatenate([out, spec.alpha[:, :, None].astype(out.dtype)], axis=2)
    elif spec.n_dims == 2 and out.ndim == 3:
        out = out[:, :, 0]

    return out
