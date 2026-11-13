"""Adaptive Block-Mean QIM: QIM luoi doi chuan (Chen & Wornell, 2001) ap
vao gia tri trung binh moi khoi 4x4 duoc chon, buoc luong tu Delta
thich ung theo do lech chuan cuc bo (khoi cang co texture cang "giau"
duoc muc dich mean lon hon ma khong lo)."""
from __future__ import annotations

import numpy as np


def adaptive_delta(block: np.ndarray, delta_base: float,
                    k_adapt: float = 0.5, delta_min: float = 4.0) -> float:
    local_std = float(block.std())
    delta = delta_base * (1.0 + k_adapt * (local_std / 32.0))
    return max(delta, delta_min)


def qim_embed_scalar(x: float, bit: int, delta: float) -> float:
    """QIM luoi doi vo huong chuan: bit=0 -> boi so gan nhat cua delta;
    bit=1 -> boi so gan nhat cua delta, lech di delta/2."""
    if bit == 0:
        return delta * round(x / delta)
    else:
        return delta * round((x - delta / 2) / delta) + delta / 2


def qim_extract_scalar(x: float, delta: float) -> int:
    """Quyet dinh bit theo khoang cach den diem luoi gan nhat."""
    d0 = abs(x - delta * round(x / delta))
    q1 = delta * round((x - delta / 2) / delta) + delta / 2
    d1 = abs(x - q1)
    return 0 if d0 < d1 else 1


def embed_bit_in_block_mean(img: np.ndarray, r: int, c: int, block_size: int,
                             bit: int, delta: float) -> None:
    """In-place: dich moi pixel trong khoi mot luong (target_mean -
    current_mean) de MEAN cua khoi ma hoa `bit` duoi QIM buoc `delta`,
    trong khi pattern noi bo cua khoi (phuong sai/texture) giu nguyen
    (dich DC thuan tuy)."""
    blk = img[r:r + block_size, c:c + block_size]
    x = float(blk.mean())
    y = qim_embed_scalar(x, bit, delta)
    shift = y - x
    img[r:r + block_size, c:c + block_size] = np.clip(blk + shift, 0, 255)


def extract_bit_from_block_mean(img: np.ndarray, r: int, c: int,
                                 block_size: int, delta: float) -> int:
    blk = img[r:r + block_size, c:c + block_size]
    x = float(blk.mean())
    return qim_extract_scalar(x, delta)
