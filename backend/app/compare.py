"""So sánh ảnh gốc và ảnh đã giấu tin: bản đồ nhiệt và vị trí điểm ảnh thay đổi."""
from __future__ import annotations

import numpy as np

BLOCK = 4


def _rgb(a: np.ndarray) -> np.ndarray:
    if a.ndim == 2:
        return np.repeat(a[..., None], 3, axis=2)
    return a[..., :3]


def compare(original: np.ndarray, stego: np.ndarray) -> dict:
    a, b = _rgb(original).astype(np.int16), _rgb(stego).astype(np.int16)
    if a.shape != b.shape:
        raise ValueError(
            f"Hai ảnh khác kích thước ({a.shape[1]}×{a.shape[0]} và {b.shape[1]}×{b.shape[0]}). "
            "Hãy chọn đúng ảnh gốc và ảnh đã giấu tin từ ảnh đó.")
    diff = np.abs(a - b).max(axis=2)          # mức thay đổi lớn nhất trên 3 kênh, mỗi điểm ảnh
    changed = diff > 0
    h, w = diff.shape
    max_diff = int(diff.max())

    # Bản đồ nhiệt: đen -> lục -> vàng -> trắng, chuẩn hoá theo mức thay đổi lớn nhất.
    t = diff.astype(np.float64) / max(1, max_diff)
    heat = np.zeros((h, w, 3), np.float64)
    heat[..., 1] = np.clip(t * 2.2, 0, 1) * 229
    heat[..., 0] = np.clip((t - 0.4) * 2.5, 0, 1) * 255
    heat[..., 2] = np.clip(t * 2.2, 0, 1) * 160 * (1 - np.clip((t - 0.4) * 2.5, 0, 1)) \
        + np.clip((t - 0.8) * 5, 0, 1) * 255
    heat[~changed] = (7, 11, 16)

    # Lớp phủ: ảnh gốc xám, làm tối; điểm ảnh thay đổi tô màu nổi bật.
    gray = (0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]) * 0.45
    overlay = np.repeat(gray[..., None], 3, axis=2)
    strength = (0.55 + 0.45 * t)[changed][:, None]
    overlay[changed] = overlay[changed] * (1 - strength) + np.array([255, 45, 120]) * strength

    hb, wb = h // BLOCK, w // BLOCK
    blocks = changed[:hb * BLOCK, :wb * BLOCK].reshape(hb, BLOCK, wb, BLOCK).any(axis=(1, 3))
    mse = float(np.mean((a - b).astype(np.float64) ** 2))

    return {
        "heatmap": np.clip(heat, 0, 255).astype(np.uint8),
        "overlay": np.clip(overlay, 0, 255).astype(np.uint8),
        "width": w, "height": h,
        "changed_pixels": int(changed.sum()),
        "changed_ratio": float(changed.mean()),
        "changed_blocks": int(blocks.sum()),
        "total_blocks": int(hb * wb),
        "max_diff": max_diff,
        "mean_diff": float(diff[changed].mean()) if changed.any() else 0.0,
        "psnr_db": None if mse == 0 else round(10 * np.log10(255.0 ** 2 / mse), 2),
    }
