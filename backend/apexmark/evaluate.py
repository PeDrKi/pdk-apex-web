"""Chạy toàn bộ bộ tấn công chuẩn (`apexmark.attacks`) trên một ảnh + bits,
đo BER với extract() thường và extract_robust() (resync+redundancy), trả về
bảng kết quả -- dùng cho phần thực nghiệm/so sánh thuật toán trong nghiên cứu.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from . import attacks as _attacks
from .blocks import is_color, rgb_to_luma
from .core import embed, extract
from .imageio import normalize


def _ber(a, b) -> float:
    return float(np.mean(np.asarray(a) != np.asarray(b)))


def run_battery(image, bits: np.ndarray, *, embed_kwargs: Optional[dict] = None,
                 battery: Optional[dict] = None, severity: int = 2, seed: int = 0,
                 include_robust: Optional[bool] = None, resync_kwargs: Optional[dict] = None,
                 verbose: bool = False) -> list:
    """Nhúng 1 lần, chạy toàn bộ `battery` (mặc định `attacks.standard_battery`),
    trích xuất bằng cả `extract()` thường và `extract_robust()`, trả về danh
    sách dict — mỗi phần tử 1 dòng, sẵn sàng đưa vào pandas.DataFrame(kết_quả).

    embed_kwargs    : truyền cho apexmark.embed(), vd
                       {"redundancy": 5, "store_thumbnail": True, "seed": 7}.
                       Cần store_thumbnail=True để cột "ber_robust" có nghĩa
                       với các tấn công hình học.
    include_robust  : None (mặc định) = tự bật nếu embed_kwargs có
                       store_thumbnail=True và đã cài OpenCV.
    resync_kwargs   : truyền cho `sync.extract_robust()` CỦA RIÊNG các tấn
                       công được đánh dấu `geometric=True` trong battery (vd
                       "xoay" trong standard_battery) -- các tấn công không
                       hình học (nén/nhiễu/chỉnh màu...) luôn dùng resync()
                       mặc định (nhanh, không dò góc) bất kể tham số này, để
                       tránh làm chậm cả battery một cách không cần thiết.
                       QUAN TRỌNG: `resync()` mặc định KHÔNG dò góc xoay
                       (angle_range=(0,0)) -- nếu battery có tấn công xoay và
                       bạn muốn cột ber_robust của nó phản ánh đúng khả năng
                       sửa được, truyền vd `resync_kwargs={"angle_range":
                       (-15, 15), "angle_step": 1.0}`.
                       CẢNH BÁO HIỆU NĂNG: bật angle_range làm MỌI tấn công
                       geometric=True (kể cả loại không xoay như cắt/dịch)
                       chậm hẳn -- mỗi tấn công có thể tốn hàng chục giây với
                       angle_range rộng (đã đo: ±25° ~25-30s/tấn công trên
                       ảnh 384×384). Nếu chỉ cần đo riêng khả năng chống
                       xoay, lọc `battery` chỉ còn tấn công đó trước khi gọi,
                       thay vì chạy cả 22 tấn công với angle_range bật sẵn.

    Mỗi dòng kết quả: {"attack", "geometric", "ber_extract", "ber_robust"}.
    "ber_robust" = None nếu include_robust=False hoặc resync không khả dụng.
    """
    embed_kwargs = dict(embed_kwargs or {})
    embed_kwargs.setdefault("seed", seed)
    battery = battery if battery is not None else _attacks.standard_battery(severity, seed)

    stego, keys = embed(image, bits, **embed_kwargs)

    if include_robust is None:
        from . import sync as _sync
        include_robust = bool(embed_kwargs.get("store_thumbnail")) and _sync.is_available()

    work, _ = normalize(stego)
    luma = rgb_to_luma(work) if is_color(work) else work

    rows = []
    for name, (attack_fn, is_geometric) in battery.items():
        row = {"attack": name, "geometric": is_geometric, "ber_extract": None, "ber_robust": None}
        try:
            attacked = attack_fn(luma)
        except Exception as e:
            # vd nen_bc7_that khi chưa cài CompressonatorCLI -- báo lỗi rõ
            # ràng thay vì làm crash toàn bộ battery giữa chừng.
            row["ber_extract"] = f"lỗi tấn công: {e}"
            row["ber_robust"] = f"lỗi tấn công: {e}" if include_robust else None
            rows.append(row)
            if verbose:
                print(f"{name:25s} LỖI KHI TẤN CÔNG: {e}")
            continue

        try:
            row["ber_extract"] = _ber(extract(attacked, keys), bits)
        except Exception as e:  # ảnh sau tấn công có thể quá nhỏ để extract() thường chạy
            row["ber_extract"] = f"lỗi: {e}"

        if include_robust:
            from . import sync as _sync
            try:
                # Chỉ áp resync_kwargs (vd dò góc xoay -- tốn thời gian) cho
                # tấn công ĐƯỢC ĐÁNH DẤU hình học; áp cho mọi tấn công (kể cả
                # nén/nhiễu/chỉnh màu) sẽ làm cả battery chậm hẳn một cách vô
                # ích, vì phần lớn không cần dò gì cả (đã đo: khiến 1 lần
                # chạy battery từ vài giây thành TREO >120s).
                rk = resync_kwargs if is_geometric else None
                rec = _sync.extract_robust(attacked, keys, resync_kwargs=rk)
                row["ber_robust"] = _ber(rec, bits)
            except Exception as e:
                row["ber_robust"] = f"lỗi: {e}"

        if verbose:
            be = row["ber_extract"]
            br = row["ber_robust"]
            be_s = be if isinstance(be, str) else f"{be:.4f}"
            br_s = "-" if br is None else (br if isinstance(br, str) else f"{br:.4f}")
            print(f"{name:25s} geometric={str(is_geometric):5s} ber_extract={be_s:>10s} ber_robust={br_s:>10s}")
        rows.append(row)
    return rows


def summarize(rows: list, ber_threshold: float = 0.10) -> str:
    """Bảng tóm tắt dạng text đơn giản (không cần pandas)."""
    lines = [f"{'Tấn công':25s} {'Hình học':9s} {'extract()':>12s} {'extract_robust()':>18s}"]
    lines.append("-" * 68)
    for r in rows:
        def fmt(v):
            if v is None:
                return "-"
            if isinstance(v, str):
                return "lỗi"
            mark = "OK" if v <= ber_threshold else "GAY"
            return f"{v:.4f} {mark}"
        lines.append(f"{r['attack']:25s} {'co' if r['geometric'] else '':9s} "
                      f"{fmt(r['ber_extract']):>12s} {fmt(r['ber_robust']):>18s}")
    return "\n".join(lines)


def run_battery_multi(images: list, bits: np.ndarray, *, image_names: Optional[list] = None,
                       **run_battery_kwargs) -> list:
    """Chạy `run_battery()` trên NHIỀU ảnh, gộp kết quả theo từng tấn công
    thành trung bình + độ lệch chuẩn -- một lần chạy/một ảnh chỉ là giai
    thoại (anecdote), không phải kết luận; kết quả trên ảnh khác nhau có thể
    lệch nhiều (đã đo: ảnh thật vs ảnh tổng hợp cần tham số khác hẳn nhau để
    đạt cùng độ bền). Dùng hàm này thay vì gọi run_battery() lặp tay khi cần
    số liệu đưa vào báo cáo/luận văn.

    images          : danh sách ảnh (mỗi ảnh — path, PIL.Image, hoặc mảng —
                       như apexmark.embed() chấp nhận).
    image_names     : tên hiển thị cho từng ảnh (mặc định "anh_0", "anh_1"...).
    **run_battery_kwargs : truyền y hệt cho run_battery() ở MỖI ảnh (embed_kwargs,
                       battery, severity, resync_kwargs...).

    Trả về danh sách dict, một dòng mỗi (tấn công): {"attack", "geometric",
    "n_anh", "ber_extract_mean", "ber_extract_std", "ber_robust_mean",
    "ber_robust_std", "n_loi"} -- "n_loi" đếm số ảnh mà tấn công đó lỗi (vd
    thiếu CompressonatorCLI, hoặc ảnh quá nhỏ sau tấn công) trên tổng số ảnh.
    """
    if image_names is None:
        image_names = [f"anh_{i}" for i in range(len(images))]
    assert len(image_names) == len(images)

    per_image_rows = []  # list[list[dict]]
    for img in images:
        per_image_rows.append(run_battery(img, bits, **run_battery_kwargs))

    attack_order = [r["attack"] for r in per_image_rows[0]] if per_image_rows else []

    merged = []
    for attack_name in attack_order:
        is_geo = None
        extract_vals, robust_vals = [], []
        n_loi = 0  # đếm SỐ ẢNH bị lỗi (tối đa 1 lần/ảnh), không đếm theo từng nhánh
        for rows in per_image_rows:
            row = next((r for r in rows if r["attack"] == attack_name), None)
            if row is None:
                continue
            is_geo = row["geometric"]
            be, br = row["ber_extract"], row["ber_robust"]
            anh_loi = False
            if isinstance(be, str):
                anh_loi = True
            else:
                extract_vals.append(be)
            if br is not None:
                if isinstance(br, str):
                    anh_loi = True
                else:
                    robust_vals.append(br)
            if anh_loi:
                n_loi += 1

        def _mean_std(vals):
            if not vals:
                return None, None
            arr = np.asarray(vals, dtype=float)
            return float(arr.mean()), float(arr.std())

        em, es = _mean_std(extract_vals)
        rm, rs = _mean_std(robust_vals)
        merged.append({
            "attack": attack_name, "geometric": is_geo, "n_anh": len(images),
            "ber_extract_mean": em, "ber_extract_std": es,
            "ber_robust_mean": rm, "ber_robust_std": rs,
            "n_loi": n_loi,
        })
    return merged


def summarize_multi(rows: list, ber_threshold: float = 0.10) -> str:
    """Bảng tóm tắt cho kết quả run_battery_multi() -- có thêm độ lệch chuẩn
    và số ảnh lỗi, để thấy rõ mức ổn định qua nhiều ảnh thay vì 1 con số duy
    nhất dễ gây ảo tưởng chắc chắn."""
    lines = [f"{'Tấn công':25s} {'extract() (TB±lệch)':>22s} {'extract_robust() (TB±lệch)':>28s} {'Lỗi':>6s}"]
    lines.append("-" * 85)
    for r in rows:
        def fmt(mean, std):
            if mean is None:
                return "-"
            mark = "OK" if mean <= ber_threshold else "GAY"
            return f"{mean:.4f}±{std:.4f} {mark}"
        n = r["n_anh"]
        lines.append(f"{r['attack']:25s} {fmt(r['ber_extract_mean'], r['ber_extract_std']):>22s} "
                      f"{fmt(r['ber_robust_mean'], r['ber_robust_std']):>28s} "
                      f"{r['n_loi']}/{n:>4d}")
    return "\n".join(lines)
