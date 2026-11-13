"""Chia khối + tính điểm heuristic (texture + BC7-robustness) cho từng khối.

KHÁC BẢN NGHIÊN CỨU GỐC: bản này hỗ trợ ảnh MÀU (RGB) và kích thước BẤT KỲ,
không chỉ grayscale 512x512.

- Ảnh màu: watermark được nhúng vào kênh LUMA (Y trong YCbCr) thay vì nhúng
  riêng từng kênh RGB. Lý do: nhúng vào 3 kênh riêng làm méo màu rõ rệt và
  không tăng dung lượng hữu ích (3 kênh RGB tương quan mạnh, nén BC7 lại
  làm việc trên không gian màu khác) — nhúng vào luma giữ được màu sắc và
  bền hơn dưới nén.
- Kích thước bất kỳ: phần dư không chia hết cho block_size ở cạnh phải/dưới
  được BỎ QUA (không nhúng vào đó), không pad — pad sẽ tạo khối nhân tạo mà
  lúc trích xuất trên ảnh đã bị tấn công có thể không tái tạo được.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np


def is_color(img: np.ndarray) -> bool:
    """True nếu ảnh là RGB/RGBA (3 chiều, kênh cuối >= 3)."""
    return img.ndim == 3 and img.shape[2] >= 3


def rgb_to_luma(img: np.ndarray) -> np.ndarray:
    """Lấy kênh luma (Y trong ITU-R BT.601) từ ảnh RGB, trả về float64 (H,W)."""
    r = img[:, :, 0].astype(np.float64)
    g = img[:, :, 1].astype(np.float64)
    b = img[:, :, 2].astype(np.float64)
    return 0.299 * r + 0.587 * g + 0.114 * b


def replace_luma(img: np.ndarray, new_luma: np.ndarray) -> np.ndarray:
    """Ghép kênh luma mới vào ảnh RGB, giữ nguyên sắc độ (chroma).

    Cách làm: tính độ lệch luma rồi cộng đều vào cả 3 kênh RGB. Đây là phép
    dịch DC thuần tuý trong không gian RGB — giữ nguyên hiệu số giữa các kênh
    (tức giữ nguyên màu), chỉ đổi độ sáng, khớp với cách embed_bit_in_block_mean
    dịch DC của khối.
    """
    old_luma = rgb_to_luma(img)
    delta = (new_luma - old_luma)[:, :, None]
    out = img.astype(np.float64).copy()
    out[:, :, :3] = np.clip(out[:, :, :3] + delta, 0, 255)
    return out


def _to_blocks(img: np.ndarray, block_size: int = 4) -> np.ndarray:
    """(H,W) -> (nh, nw, bs, bs). Phần dư ở cạnh phải/dưới bị cắt bỏ."""
    H, W = img.shape
    nh, nw = H // block_size, W // block_size
    cropped = img[:nh * block_size, :nw * block_size]
    return cropped.reshape(nh, block_size, nw, block_size).transpose(0, 2, 1, 3)


def max_capacity_bits(img: np.ndarray, block_size: int = 4) -> int:
    """Số bit tối đa nhúng được vào ảnh này (mỗi khối = 1 bit)."""
    H, W = img.shape[:2]
    return (H // block_size) * (W // block_size)


def compute_all_block_scores(
    luma: np.ndarray,
    bc7_attack_fn: Optional[Callable[[np.ndarray], np.ndarray]],
    block_size: int = 4,
):
    """Tính điểm texture + điểm BC7-robustness cho mọi khối không chồng lấp.

    `luma`: ảnh 2D (H,W) — với ảnh màu, truyền kênh luma vào đây.
    `bc7_attack_fn`: hàm nén/giải nén BC7 thật, gọi 1 LẦN cho toàn ảnh. Nếu
        None, bỏ qua hoàn toàn thành phần BC7-robustness (bc7_scores trả về
        toàn 0) — khi đó nên đặt w_bc7=0.0 ở combined_heuristic.

    Trả về (coords, texture_scores, bc7_scores); bc7_scores đã âm hoá
    (cao hơn = bền BC7 hơn).
    """
    H, W = luma.shape
    nh, nw = H // block_size, W // block_size
    blocks = _to_blocks(luma, block_size)

    tex = blocks.std(axis=(2, 3))

    if bc7_attack_fn is None:
        bc7 = np.zeros_like(tex)
    else:
        bc7_compressed = bc7_attack_fn(luma)
        if bc7_compressed.ndim == 3:
            bc7_compressed = rgb_to_luma(bc7_compressed)
        bc7_blocks = _to_blocks(bc7_compressed, block_size)
        mean_err = np.abs(bc7_blocks.mean(axis=(2, 3)) - blocks.mean(axis=(2, 3)))
        bc7 = -mean_err

    coords = [(r * block_size, c * block_size) for r in range(nh) for c in range(nw)]
    return coords, tex.flatten(), bc7.flatten()


def combined_heuristic(tex_scores: np.ndarray, bc7_scores: np.ndarray,
                        w_tex: float = 0.5, w_bc7: float = 0.5) -> np.ndarray:
    """Min-max chuẩn hoá cả 2 mảng điểm về [0,1] rồi kết hợp. Epsilon floor
    giữ xác suất chuyển ACO luôn xác định (không bao giờ bằng 0)."""
    def _norm(x):
        lo, hi = x.min(), x.max()
        if hi - lo < 1e-9:
            return np.ones_like(x)
        return (x - lo) / (hi - lo)

    h = w_tex * _norm(tex_scores) + w_bc7 * _norm(bc7_scores)
    return h + 1e-6
