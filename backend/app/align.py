"""Căn chỉnh chính xác đến từng điểm ảnh + trích xuất có mặt nạ.

`apexmark.sync.resync()` định vị ảnh bị cắt/dịch bằng ảnh thu nhỏ (cạnh 256 px),
nên sai lệch vài điểm ảnh ở kích thước thật — đủ để làm hỏng lưới khối 4×4.
Module này tinh chỉnh tiếp ở độ phân giải gốc mà KHÔNG cần biết nội dung đã giấu:
sau khi nhúng QIM, trung bình mỗi khối luôn nằm trên lưới bội số của delta/2, nên
vị trí đúng là vị trí làm cho các trung bình khối "bám lưới" nhất.

Ngoài ra, các khối rơi ra ngoài phần ảnh còn lại (đã bị cắt mất) được loại khỏi
phép bỏ phiếu, thay vì đóng góp phiếu rác.
"""
from __future__ import annotations

import numpy as np

from apexmark.blocks import is_color, rgb_to_luma
from apexmark.chaotic import chaotic_unscramble
from apexmark.imageio import normalize
from apexmark.ngdc import piecewise_ngdc_correct
from apexmark.redundancy import one_dim_kmeans_threshold

B = 4
MAX_SAMPLE = 4000
ACCEPT_SCORE = 0.40      # ngẫu nhiên ≈ 0.5; đúng vị trí thường < 0.2


def to_luma(image) -> np.ndarray:
    work, _ = normalize(image)
    return (rgb_to_luma(work) if is_color(work) else work).astype(np.float64)


def _integral(img: np.ndarray) -> np.ndarray:
    s = np.zeros((img.shape[0] + 1, img.shape[1] + 1))
    np.cumsum(np.cumsum(img, axis=0), axis=1, out=s[1:, 1:])
    return s


def _block_means(S: np.ndarray, r: np.ndarray, c: np.ndarray) -> np.ndarray:
    return (S[r + B, c + B] - S[r, c + B] - S[r + B, c] + S[r, c]) / (B * B)


def _lattice_score(means: np.ndarray, deltas: np.ndarray) -> float:
    half = deltas / 2.0
    dist = np.abs(means - half * np.round(means / half))
    return float(np.mean(dist / (half / 2.0)))


def _bbox(canvas: np.ndarray):
    rows = np.flatnonzero(canvas.any(axis=1))
    cols = np.flatnonzero(canvas.any(axis=0))
    if not rows.size or not cols.size:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def refine(luma: np.ndarray, coarse: np.ndarray, keys: dict):
    """luma: ảnh nhận được (chưa căn chỉnh); coarse: khung do resync() dựng.
    Trả về (khung đã căn chỉnh, hộp hợp lệ (x1, y1, x2, y2) hoặc None = toàn khung)."""
    import cv2

    H, W = coarse.shape
    box = _bbox(coarse)
    if box is None:
        return coarse, None
    X1, Y1, X2, Y2 = box
    if (X2 - X1) * (Y2 - Y1) >= 0.98 * H * W:
        return coarse, None                      # không bị cắt: giữ nguyên kết quả resync
    h, w = luma.shape
    sx, sy = (X2 - X1) / w, (Y2 - Y1) / h
    if abs(sx - sy) > 0.03 * max(sx, sy):
        return coarse, box                       # méo tỉ lệ: ngoài phạm vi tinh chỉnh
    s0 = (sx + sy) / 2

    coords = np.asarray(keys["selected_coords"]).astype(np.int64)
    deltas = np.asarray(keys["deltas"]).astype(np.float64)
    if len(coords) > MAX_SAMPLE:
        pick = np.random.default_rng(0).choice(len(coords), MAX_SAMPLE, replace=False)
        coords, deltas = coords[pick], deltas[pick]
    r, c = coords[:, 0], coords[:, 1]

    thumb = np.asarray(keys["thumbnail"])
    R = int(min(16, np.ceil(1.5 * max(H / thumb.shape[0], W / thumb.shape[1])) + 2))
    scales = [s0 * (1 + e) for e in np.linspace(-0.02, 0.02, 11)]
    if abs(s0 - 1) < 0.03:
        scales = [1.0] + scales                  # cắt/dịch thuần tuý: không cần lấy mẫu lại

    best = (ACCEPT_SCORE, None)
    for s in scales:
        if s == 1.0:
            img = luma
        else:
            nw, nh = max(8, round(w * s)), max(8, round(h * s))
            img = cv2.resize(luma.astype(np.float32), (nw, nh),
                             interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR).astype(np.float64)
        ih, iw = img.shape
        S = _integral(img)
        for oy in range(Y1 - R, Y1 + R + 1):
            rr = r - oy
            ok_r = (rr >= 0) & (rr + B <= ih)
            for ox in range(X1 - R, X1 + R + 1):
                cc = c - ox
                ok = ok_r & (cc >= 0) & (cc + B <= iw)
                if ok.sum() < max(50, 0.15 * len(r)):
                    continue
                score = _lattice_score(_block_means(S, rr[ok], cc[ok]), deltas[ok])
                if score < best[0]:
                    best = (score, (img, oy, ox))
    if best[1] is None:
        return coarse, box

    img, oy, ox = best[1]
    ih, iw = img.shape
    canvas = np.zeros((H, W))
    y1, x1, y2, x2 = max(0, oy), max(0, ox), min(H, oy + ih), min(W, ox + iw)
    canvas[y1:y2, x1:x2] = img[y1 - oy:y2 - oy, x1 - ox:x2 - ox]
    return canvas, (x1, y1, x2, y2)


def _despeckle(frame: np.ndarray):
    """Thay các điểm ảnh cực trị (0/255) bằng trung vị 3×3 quanh nó. None nếu không cần."""
    try:
        import cv2
    except ImportError:
        return None
    u8 = np.clip(frame, 0, 255).astype(np.uint8)
    extreme = (u8 <= 1) | (u8 >= 254)
    frac = float(extreme.mean())
    if frac < 0.002 or frac > 0.6:
        return None
    out = frame.copy()
    out[extreme] = cv2.medianBlur(u8, 3)[extreme]
    return out


def masked_extract(frame: np.ndarray, keys: dict, box=None, aggregate: str = "mean") -> np.ndarray:
    """Như apexmark.extract(), nhưng chỉ các khối nằm trong `box` mới được bỏ phiếu."""
    coords = np.asarray(keys["selected_coords"]).astype(np.int64)
    deltas = np.asarray(keys["deltas"]).astype(np.float64)
    n_bits = int(keys["n_bits"])
    r, c = coords[:, 0], coords[:, 1]
    H, W = frame.shape
    valid = (r + B <= H) & (c + B <= W)
    if box is not None:
        x1, y1, x2, y2 = box
        valid &= (r >= y1) & (r + B <= y2) & (c >= x1) & (c + B <= x2)
    if not valid.any():
        raise ValueError("Phần ảnh còn lại không chứa khối nào đã nhúng.")

    slot_map = (np.asarray(keys["slot_bit_map"]).astype(np.int64) if "slot_bit_map" in keys
                else np.arange(n_bits))
    redundant = int(keys.get("redundancy", 1)) > 1
    half = deltas[valid] / 2.0
    use_ngdc = bool(keys.get("use_ngdc", False))

    # Thử vài cách đọc rồi giữ cách cho kết quả "nhất quán" nhất:
    #  - có/không hiệu chỉnh N-GDC (N-GDC bù lệch sáng/tương phản, nhưng thống kê của nó
    #    bị kéo lệch khi ảnh có vùng bị che);
    #  - có/không khử điểm nhiễu muối tiêu (điểm ảnh 0 hoặc 255 lạc lõng) trước khi đọc.
    # Độ nhất quán = các bản sao của cùng một bit đồng ý với nhau đến đâu; khi không có
    # dự phòng thì dùng độ bám lưới QIM. Cả hai đều không cần biết nội dung đã giấu.
    best = None
    for frame_v in (frame, _despeckle(frame)):
        if frame_v is None:
            continue
        raw = _block_means(_integral(frame_v), r[valid], c[valid])
        variants = [raw]
        if use_ngdc:
            variants.append(piecewise_ngdc_correct(
                raw, np.asarray(keys["ngdc_bin_ids"])[valid], keys["ngdc_mu1_bin"],
                keys["ngdc_sigma1_bin"], int(keys["n_bins"])))
        for m in variants:
            decisions = (np.round(m / half).astype(np.int64) & 1).astype(np.float64)
            sums, counts = np.zeros(n_bits), np.zeros(n_bits)
            np.add.at(sums, slot_map[valid], decisions)
            np.add.at(counts, slot_map[valid], 1.0)
            avg = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
            if redundant:
                quality = float(np.mean(np.abs(avg[counts > 0] - 0.5)))
            else:
                quality = -_lattice_score(m, deltas[valid])
            if best is None or quality > best[0] + 1e-9:
                best = (quality, avg)

    avg = best[1]
    if aggregate == "kmeans" and redundant:
        scrambled = one_dim_kmeans_threshold(avg).astype(np.uint8)
    else:
        scrambled = (avg >= 0.5).astype(np.uint8)
    return chaotic_unscramble(scrambled, np.asarray(keys["K1_perm"]).astype(np.int64))
