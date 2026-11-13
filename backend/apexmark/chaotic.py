"""Ma hoa/giai ma hon loan (logistic map) dung chung cho watermark bits,
giong het dinh nghia o notebook 2 (baseline) va notebook 3 (APEX) de 2
he thong co cung muc bao mat, so sanh cong bang."""
from __future__ import annotations

import numpy as np


def chaotic_sequence(length: int, x0: float = 0.531, r: float = 3.9999) -> np.ndarray:
    """Chuoi hon loan tu logistic map, tat dinh voi (x0, r) -- day chinh
    la khoa bi mat K1."""
    seq = np.empty(length)
    x = x0
    for i in range(length):
        x = r * x * (1 - x)
        seq[i] = x
    return seq


def chaotic_scramble(bits: np.ndarray, key_x0: float = 0.531,
                      key_r: float = 3.9999) -> tuple[np.ndarray, np.ndarray]:
    """Xao tron mang bit 1D bang hoan vi sinh tu chuoi hon loan da sap
    xep. Tra ve (scrambled_bits, perm_indices) -- perm_indices la khoa K1,
    can de giai xao tron."""
    seq = chaotic_sequence(bits.size, key_x0, key_r)
    perm = np.argsort(seq)
    return bits[perm], perm


def chaotic_unscramble(scrambled_bits: np.ndarray, perm: np.ndarray) -> np.ndarray:
    out = np.empty_like(scrambled_bits)
    out[perm] = scrambled_bits
    return out
