"""API chính của apexmark: nhúng/trích xuất watermark bền vững với nén BC7.

Dùng nhanh:
    import numpy as np
    from PIL import Image
    import apexmark

    img = np.array(Image.open("anh.png"))
    bits = np.random.randint(0, 2, 256)            # watermark tuỳ ý

    stego, keys = apexmark.embed(img, bits)         # nhúng
    apexmark.save_keys(keys, "keys.npz")            # lưu khoá để trích sau

    ...                                             # ảnh có thể bị nén/tấn công

    keys = apexmark.load_keys("keys.npz")
    recovered = apexmark.extract(stego, keys)       # trích xuất
    print("BER:", np.mean(recovered != bits))
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .aco import aco_select_blocks, greedy_top_n_blocks
from .blocks import (combined_heuristic, compute_all_block_scores, is_color,
                      max_capacity_bits, replace_luma, rgb_to_luma)
from .chaotic import chaotic_scramble, chaotic_unscramble
from .imageio import denormalize, normalize
from .ngdc import assign_bins, compute_bin_stats, piecewise_ngdc_correct
from .qim import adaptive_delta, embed_bit_in_block_mean, qim_extract_scalar

BLOCK_SIZE = 4


def embed(
    image: np.ndarray,
    bits: np.ndarray,
    *,
    bc7_aware: Optional[bool] = None,
    bc7_fn: Optional[Callable[[np.ndarray], np.ndarray]] = None,
    compressonator_path: Optional[str] = None,
    delta_base: float = 12.0,
    k_adapt: float = 0.5,
    use_aco: bool = True,
    n_ants: int = 20,
    n_iters: int = 15,
    w_tex: float = 0.5,
    w_bc7: float = 0.5,
    chaotic_x0: float = 0.531,
    chaotic_r: float = 3.9999,
    use_ngdc: bool = True,
    n_bins: int = 8,
    redundancy: int = 1,
    store_thumbnail: bool = False,
    thumbnail_max_side: int = 256,
    seed: int = 0,
    verbose: bool = False,
):
    """Nhúng `bits` vào `image`, trả về (ảnh_đã_nhúng, keys).

    image : ẢNH BẤT KỲ — numpy array, đường dẫn file, hoặc PIL.Image.
            Chấp nhận grayscale / RGB / RGBA / grayscale+alpha, dtype uint8,
            uint16, float (thang 0-1 hoặc 0-255), bool; kích thước bất kỳ.
            Ảnh màu: nhúng vào kênh luma, giữ nguyên sắc độ. Kênh alpha được
            giữ nguyên, không nhúng vào. Đầu ra cùng dtype/số kênh với đầu vào.
            Phần dư không chia hết cho 4 ở cạnh phải/dưới được bỏ qua.
    bits  : mảng 0/1 1D. Mỗi bit chiếm `redundancy` khối 4x4 — xem
            `capacity()` để biết tối đa nhúng được bao nhiêu bit (redundancy=1)
            vào ảnh này.

    bc7_aware : True  = dùng CompressonatorCLI để ưu tiên các khối bền BC7
                        (cần cài Compressonator, xem apexmark.bc7).
                False = bỏ qua thành phần này (chỉ dùng texture heuristic).
                None (mặc định) = TỰ ĐỘNG: bật nếu tìm thấy CompressonatorCLI,
                        ngược lại tự tắt và chạy tiếp (không raise lỗi).
    bc7_fn    : tự truyền hàm nén BC7 riêng (bỏ qua bc7_aware/compressonator_path).

    redundancy : số khối dự phòng cho MỖI bit (mặc định 1 = hành vi gốc,
            không đổi). Đặt > 1 để mượn triết lý "nhúng lặp lại nhiều lần +
            trích xuất thống kê" của blind_watermark: mỗi bit được rải vào
            `redundancy` khối khác nhau (xáo trộn để không dồn cụm), lúc
            extract() sẽ bỏ phiếu đa số (hoặc kmeans thích ứng) trên các
            bản sao đó. Tăng độ bền với nhiễu cục bộ/occlusion/tấn công một
            phần ảnh, đổi lại giảm dung lượng khả dụng còn cap // redundancy
            bit và giảm nhẹ PSNR (nhúng vào nhiều khối hơn). Xem
            `apexmark.redundancy`.
    store_thumbnail : True = lưu kèm trong keys một ảnh thu nhỏ (vài KB) của
            chính ảnh đã nhúng, dùng làm mốc cho `apexmark.sync.resync()` sau
            này để phục hồi ảnh bị cắt/dịch/co giãn/xoay nhẹ trước khi
            extract() — vá điểm yếu "gãy khi lệch lưới" của apexmark. Không
            bắt buộc cài OpenCV để bật cờ này (chỉ resync() lúc trích xuất
            mới cần cv2).
    thumbnail_max_side : cạnh dài tối đa (px) của ảnh thu nhỏ nói trên.

    Trả về (ảnh_đã_nhúng, keys); keys cần cho extract() — lưu bằng save_keys().
    """
    bits = np.asarray(bits).astype(np.uint8).ravel()
    n_bits = bits.size
    if redundancy < 1:
        raise ValueError("redundancy phải >= 1.")
    n_slots = n_bits * redundancy

    work, spec = normalize(image)
    color = is_color(work)
    luma = rgb_to_luma(work) if color else work

    cap = max_capacity_bits(luma, BLOCK_SIZE)
    if n_slots > cap:
        raise ValueError(
            f"Watermark {n_bits} bit x redundancy {redundancy} = {n_slots} khối "
            f"vượt dung lượng ảnh ({cap} khối 4x4 = "
            f"{luma.shape[0] // BLOCK_SIZE}x{luma.shape[1] // BLOCK_SIZE}). "
            f"Dùng apexmark.capacity(image) để kiểm tra trước, hoặc giảm "
            f"redundancy/số bit."
        )

    if bc7_fn is None:
        if bc7_aware is None:
            from . import bc7 as _bc7mod
            bc7_aware = _bc7mod.is_available(compressonator_path)
            if verbose and not bc7_aware:
                print("apexmark: không tìm thấy CompressonatorCLI -> tự tắt BC7-aware.")
        if bc7_aware:
            from . import bc7 as _bc7mod
            bc7_fn = _bc7mod.make_bc7_fn(compressonator_path)

    if bc7_fn is None:
        w_bc7_eff = 0.0
        w_tex_eff = 1.0
    else:
        w_bc7_eff, w_tex_eff = w_bc7, w_tex

    coords, tex_scores, bc7_scores = compute_all_block_scores(luma, bc7_fn, BLOCK_SIZE)
    heuristic = combined_heuristic(tex_scores, bc7_scores, w_tex_eff, w_bc7_eff)

    if use_aco:
        sel_idx, _ = aco_select_blocks(len(coords), n_slots, heuristic,
                                        n_ants=n_ants, n_iters=n_iters,
                                        rng_seed=seed, verbose=verbose)
    else:
        sel_idx = greedy_top_n_blocks(n_slots, heuristic)

    selected_coords = [coords[i] for i in sel_idx]
    scrambled, perm = chaotic_scramble(bits, chaotic_x0, chaotic_r)

    if redundancy > 1:
        from .redundancy import build_slot_bit_map
        slot_bit_map = build_slot_bit_map(n_bits, redundancy, np.random.RandomState(seed))
    else:
        slot_bit_map = np.arange(n_bits, dtype=np.int64)

    marked_luma = luma.copy()
    deltas = np.empty(n_slots)
    for k, (r, c) in enumerate(selected_coords):
        blk = marked_luma[r:r + BLOCK_SIZE, c:c + BLOCK_SIZE]
        delta = adaptive_delta(blk, delta_base, k_adapt)
        deltas[k] = delta
        bit_idx = int(slot_bit_map[k])
        embed_bit_in_block_mean(marked_luma, r, c, BLOCK_SIZE, int(scrambled[bit_idx]), delta)

    keys = {
        "selected_coords": np.array(selected_coords, dtype=np.int32),
        "deltas": deltas,
        "K1_perm": perm,
        "n_bits": n_bits,
        "redundancy": redundancy,
        "slot_bit_map": slot_bit_map,
        "use_ngdc": use_ngdc,
        "n_bins": n_bins,
        "is_color": color,
    }

    if use_ngdc:
        embedded_means = np.array([
            marked_luma[r:r + BLOCK_SIZE, c:c + BLOCK_SIZE].mean()
            for (r, c) in selected_coords
        ])
        bin_ids, _, n_bins_used = assign_bins(embedded_means, n_bins)
        mu1, sigma1 = compute_bin_stats(embedded_means, bin_ids, n_bins_used)
        keys.update({"ngdc_bin_ids": bin_ids, "ngdc_mu1_bin": mu1,
                     "ngdc_sigma1_bin": sigma1, "n_bins": n_bins_used})

    marked_work = replace_luma(work, marked_luma) if color else marked_luma

    if store_thumbnail:
        from .sync import make_thumbnail
        keys["thumbnail"] = make_thumbnail(marked_luma, thumbnail_max_side)
        keys["orig_shape"] = np.array(marked_luma.shape, dtype=np.int32)

    return denormalize(marked_work, spec), keys


def extract(image: np.ndarray, keys: dict, *, aggregate: str = "mean") -> np.ndarray:
    """Trích watermark từ `image` (có thể đã bị nén/tấn công) dùng `keys`
    trả về từ embed(). Nhận ảnh ở mọi dạng như embed(). Trả về mảng bit 0/1.

    aggregate : chỉ có tác dụng khi keys được nhúng với redundancy > 1.
            "mean"   = đa số phiếu trên các bản sao của mỗi bit (mặc định).
            "kmeans" = ngưỡng thích ứng one_dim_kmeans (xem apexmark.redundancy)
                       — thử khi "mean" cho BER cao dưới tấn công làm lệch
                       phân bố toàn cục (vd. chỉnh sáng/tương phản mạnh).
    """
    work, _ = normalize(image)
    luma = rgb_to_luma(work) if is_color(work) else work

    coords = keys["selected_coords"]
    n_bits = int(keys["n_bits"])
    deltas = keys["deltas"]
    redundancy = int(keys.get("redundancy", 1))
    n_slots = len(coords)

    max_r = int(coords[:, 0].max()) + BLOCK_SIZE if n_slots else 0
    max_c = int(coords[:, 1].max()) + BLOCK_SIZE if n_slots else 0
    if luma.shape[0] < max_r or luma.shape[1] < max_c:
        hint = (" Ảnh có vẻ đã bị cắt/thu nhỏ so với lúc nhúng — thử "
                "apexmark.sync.resync()/extract_robust() nếu embed() dùng "
                "store_thumbnail=True.") if "thumbnail" in keys else ""
        raise ValueError(
            f"Ảnh ({luma.shape[0]}x{luma.shape[1]}) nhỏ hơn vùng đã nhúng "
            f"watermark (cần tối thiểu {max_r}x{max_c}).{hint}"
        )

    raw_means = np.array([
        luma[int(r):int(r) + BLOCK_SIZE, int(c):int(c) + BLOCK_SIZE].mean()
        for (r, c) in coords
    ])

    if bool(keys.get("use_ngdc", False)):
        corrected = piecewise_ngdc_correct(
            raw_means, keys["ngdc_bin_ids"], keys["ngdc_mu1_bin"],
            keys["ngdc_sigma1_bin"], int(keys["n_bins"]),
        )
    else:
        corrected = raw_means

    decisions = np.array([qim_extract_scalar(corrected[k], deltas[k])
                           for k in range(n_slots)], dtype=np.uint8)

    if redundancy > 1:
        from .redundancy import aggregate_votes
        scrambled = aggregate_votes(decisions, keys["slot_bit_map"], n_bits, method=aggregate)
    else:
        scrambled = decisions

    return chaotic_unscramble(scrambled, keys["K1_perm"])


def capacity(image) -> int:
    """Số bit tối đa nhúng được vào ảnh này. Nhận ảnh ở mọi dạng như embed()."""
    work, _ = normalize(image)
    luma = rgb_to_luma(work) if is_color(work) else work
    return max_capacity_bits(luma, BLOCK_SIZE)


def save_keys(keys: dict, path) -> None:
    """Lưu keys ra file .npz để dùng lại sau (kể cả ở tiến trình/máy khác)."""
    np.savez_compressed(str(path), **{k: np.asarray(v) for k, v in keys.items()})


def load_keys(path) -> dict:
    """Nạp keys đã lưu bằng save_keys()."""
    with np.load(str(path), allow_pickle=False) as z:
        keys = {k: z[k] for k in z.files}
    for k in ("n_bits", "n_bins", "redundancy"):
        if k in keys:
            keys[k] = int(keys[k])
    for k in ("use_ngdc", "is_color"):
        if k in keys:
            keys[k] = bool(keys[k])
    return keys
