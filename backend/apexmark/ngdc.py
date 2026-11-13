"""
Hieu chinh thong ke Piecewise N-GDC cho mien Block-Mean QIM cua APEX --
tuong tu N-GDC (Eq. 8) cua paper LWT-DCT-PSO, nhung dieu chinh vi
Block-Mean QIM de bi anh huong boi dich chuyen cuong do THAY DOI THEO VI
TRI (khong dong nhat) hon nhieu so voi he so DCT mid-band.

TAI SAO N-GDC TOAN CUC (1 bin) THAT BAI O DAY: histogram equalization
anh xa cuong do pixel qua 1 ham TOAN CUC, PHI TUYEN (dua tren CDF). Dieu
nay dich mean cua cac khoi KHAC NHAU mot luong khac nhau, phu thuoc gia
tri (do thuc nghiem: dich tu -36 den +31 muc, std=18.2, tren luoi nhung
Delta=12) du thong ke TONG (mean/std) tren toan bo khoi nhung gan nhu
khong doi. Mot phep hieu chinh affine toan cuc DUY NHAT (dang goc cua
Eq. 8) chi co the sua duoc mot dich chuyen+ty le DONG NHAT tren toan bo
phan phoi -- ve mat toan hoc KHONG THE sua mot phep anh xa phi tuyen
phu thuoc gia tri.

GIAI PHAP: N-GDC tuyen tinh tung doan. Chia cac khoi da nhung thanh K
bin theo muc cuong do SAU KHI NHUNG (gan bin co dinh ngay luc nhung, va
duoc chia se nhu khoa). Trong moi bin, ap dung CUNG mot hieu chinh
affine Eq. 8, nhung dung thong ke rieng tung bin.

RANG BUOC AN TOAN: neu 1 bin qua it khoi, mu1_bin/sigma1_bin tinh luc
nhung khong con la thong ke TONG HOP thuc su ma gan nhu chinh la gia tri
da nhung -- tuc "hieu chinh" ro ri dap an tu khoa thay vi thuc su phan
tich tin hieu bi tan cong. Da kiem chung thuc nghiem va chon
MIN_BLOCKS_PER_BIN = 32 lam san an toan cung (n_bins tu dong bi gioi
han de moi bin >= 32 khoi).
"""
from __future__ import annotations

import numpy as np

MIN_BLOCKS_PER_BIN = 32


def assign_bins(values: np.ndarray, n_bins: int = 8):
    """Chia bin theo SO LUONG BANG NHAU (quantile-based). n_bins bi gioi
    han am tham de moi bin co it nhat MIN_BLOCKS_PER_BIN mau.
    Tra ve (bin_ids, bin_edges, n_bins_used)."""
    max_safe_bins = max(1, len(values) // MIN_BLOCKS_PER_BIN)
    n_bins_used = min(n_bins, max_safe_bins)

    edges = np.quantile(values, np.linspace(0, 1, n_bins_used + 1))
    edges[0] -= 1e-6
    edges[-1] += 1e-6
    bin_ids = np.clip(np.digitize(values, edges) - 1, 0, n_bins_used - 1)
    return bin_ids, edges, n_bins_used


def compute_bin_stats(values: np.ndarray, bin_ids: np.ndarray, n_bins: int):
    mu = np.zeros(n_bins)
    sigma = np.zeros(n_bins)
    for k in range(n_bins):
        mask = bin_ids == k
        if mask.sum() > 0:
            mu[k] = values[mask].mean()
            sigma[k] = values[mask].std() + 1e-6
        else:
            mu[k] = 0.0
            sigma[k] = 1.0
    return mu, sigma


def piecewise_ngdc_correct(raw_values: np.ndarray, bin_ids: np.ndarray,
                            mu1_bin: np.ndarray, sigma1_bin: np.ndarray,
                            n_bins: int) -> np.ndarray:
    mu2_bin, sigma2_bin = compute_bin_stats(raw_values, bin_ids, n_bins)
    corrected = np.empty_like(raw_values)
    for k in range(n_bins):
        mask = bin_ids == k
        if mask.sum() == 0:
            continue
        corrected[mask] = (raw_values[mask] - mu2_bin[k]) * (sigma1_bin[k] / sigma2_bin[k]) + mu1_bin[k]
    return corrected
