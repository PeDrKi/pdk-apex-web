"""Ước lượng khả năng bị phát hiện (steganalysis) cho ảnh đã giấu tin bằng apexmark.

Giả định theo nguyên lý Kerckhoffs: kẻ tấn công biết thuật toán nhưng không có file khoá.
apexmark lượng tử hoá giá trị trung bình của các khối 4x4 về một lưới có bước Delta/2, với
Delta = delta * (1 + 0.5 * độ lệch chuẩn của khối / 32). Trong ảnh tự nhiên, trung bình khối
phân bố đều so với lưới đó; trong ảnh đã nhúng, các khối mang tin dồn về các điểm lưới.
Bộ đo thử từng giá trị delta nguyên mà công cụ cho phép và đo mức dồn đó (độ dài véc-tơ
tổng hợp, từ 0 = không có dấu vết đến 1 = mọi khối đều nằm đúng lưới).
"""
from __future__ import annotations

import numpy as np

from apexmark.blocks import rgb_to_luma

BLOCK = 4
DELTAS = np.arange(4, 49, dtype=np.float64)  # khoảng delta mà giao diện cho chọn
K_ADAPT, DELTA_MIN = 0.5, 4.0


def _luma(img: np.ndarray) -> np.ndarray:
    a = np.asarray(img)
    if a.ndim == 3:
        if a.shape[2] in (2, 4):
            a = a[..., :-1]
        a = rgb_to_luma(a) if a.shape[2] == 3 else a[..., 0]
    return a.astype(np.float64)


def lattice_scores(img: np.ndarray) -> np.ndarray:
    """Mức dồn về lưới QIM cho từng delta trong DELTAS."""
    luma = _luma(img)
    h, w = (luma.shape[0] // BLOCK) * BLOCK, (luma.shape[1] // BLOCK) * BLOCK
    blocks = luma[:h, :w].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).transpose(0, 2, 1, 3).reshape(-1, BLOCK * BLOCK)
    mean, std = blocks.mean(axis=1), blocks.std(axis=1)
    # Khối chạm 0 hoặc 255 bị cắt lúc nhúng nên không theo lưới; khối phẳng tuyệt đối của ảnh vẽ
    # (logo, ảnh chụp màn hình) vốn đã nằm trên số nguyên và gây báo động giả.
    keep = (blocks.min(axis=1) > 0) & (blocks.max(axis=1) < 255) & (std > 0.25)
    mean, std = mean[keep], std[keep]
    if mean.size < 64:
        return np.zeros(DELTAS.size)
    out = np.empty(DELTAS.size)
    for i, d in enumerate(DELTAS):
        step = np.maximum(d * (1.0 + K_ADAPT * std / 32.0), DELTA_MIN) / 2.0
        out[i] = np.abs(np.exp(2j * np.pi * mean / step).mean())
    return out


def analyze(cover: np.ndarray, stego: np.ndarray) -> dict:
    """So ảnh đã giấu tin với ảnh gốc: dấu vết lưới tăng thêm bao nhiêu, và mức đánh giá."""
    s, c = lattice_scores(stego), lattice_scores(cover)
    i = int(np.argmax(s - c))
    excess = float(max(0.0, s[i] - c[i]))
    n = max(1, (_luma(stego).shape[0] // BLOCK) * (_luma(stego).shape[1] // BLOCK))
    # Ngưỡng nhiễu: với n khối ngẫu nhiên, mức dồn tự nhiên vào khoảng 1/sqrt(n); lấy dư ra cho 45 lần thử.
    noise = 3.0 / np.sqrt(n)
    level = "low" if excess < noise else "medium" if excess < 0.10 else "high"
    return {"score": round(float(s[i]), 4), "baseline": round(float(c[i]), 4), "excess": round(excess, 4),
            "noise": round(float(noise), 4), "level": level}
