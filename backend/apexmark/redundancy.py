"""Nhúng dư thừa (redundant embedding) + trích xuất thống kê.

Ý TƯỞNG MƯỢN TỪ blind_watermark: phần lớn sức bền của các lược đồ watermark
theo trường phái "blind_watermark" (guofei9987/blind_watermark) không đến từ
miền DWT-DCT-SVD, mà đến từ việc mỗi bit watermark được nhúng LẶP LẠI hàng
trăm/hàng nghìn lần rải khắp ảnh (redundancy = block_num // wm_size), rồi lúc
trích xuất lấy TRUNG BÌNH (hoặc phân cụm 1 chiều kiểu k-means) trên toàn bộ
các bản sao thay vì tin vào đúng 1 khối. Điều này khiến việc mất một phần khối
(do occlusion, muối tiêu, nén mạnh, hay một phần lưới bị lệch do xoay/cắt nhẹ)
không phá huỷ toàn bộ bit — chỉ làm giảm nhẹ độ tin cậy của phiếu bầu.

apexmark bản gốc nhúng đúng 1 bit / 1 khối, KHÔNG có dự phòng: một khối bị
lệch/hỏng là bit đó mất luôn.

Module này thêm dự phòng theo đúng tinh thần blind_watermark nhưng vẫn giữ
nguyên lõi apexmark: các khối vẫn được chọn từ heuristic ACO + BC7-aware của
apexmark (nên độ ưu tiên "bền BC7" không đổi), chỉ khác là mỗi bit được cấp
`redundancy` khối thay vì 1, và các khối này được trộn ngẫu nhiên (không xếp
theo cụm điểm số) để một vùng ảnh bị hỏng cục bộ không xoá sạch phiếu bầu của
riêng một bit nào.

Hàm `one_dim_kmeans_threshold` chuyển thể trực tiếp từ
`blind_watermark.bwm_core.one_dim_kmeans` (guofei9987/blind_watermark, MIT) —
dùng làm lựa chọn ngưỡng thích ứng thay cho ngưỡng cố định 0.5 khi phân bố
phiếu bầu bị lệch hệ thống (ví dụ ảnh bị chỉnh sáng/tương phản toàn cục).
"""
from __future__ import annotations

import numpy as np


def build_slot_bit_map(n_bits: int, redundancy: int, rng: np.random.RandomState) -> np.ndarray:
    """Trả về mảng độ dài `n_bits * redundancy`: slot thứ k sẽ mang bit nào.

    Gán tuần hoàn (0,1,...,n_bits-1,0,1,...) RỒI xáo trộn thứ tự slot. Xáo
    trộn là điểm khác biệt quan trọng so với gán tuần hoàn thuần tuý: khối
    được ACO/greedy chọn đã có thứ tự ưu tiên giảm dần theo heuristic, nếu
    không xáo trộn thì bit 0 luôn vơ hết các khối tốt nhất, bit cuối luôn
    lãnh các khối yếu nhất -- không công bằng và làm dự phòng vô nghĩa với
    tấn công cục bộ (một vùng ảnh hỏng sẽ lệch hẳn về phía một vài bit).
    """
    total = n_bits * redundancy
    base = np.tile(np.arange(n_bits, dtype=np.int64), redundancy)
    order = rng.permutation(total)
    return base[order]


def aggregate_votes(decisions: np.ndarray, bit_slot_map: np.ndarray, n_bits: int,
                     method: str = "mean") -> np.ndarray:
    """Gộp các quyết định 0/1 theo từng bit (nhiều slot -> 1 bit).

    decisions   : mảng 0/1, độ dài n_bits*redundancy, thứ tự khớp bit_slot_map.
    method      : "mean"   -> đa số phiếu, ngưỡng cố định 0.5.
                  "kmeans" -> ngưỡng thích ứng one_dim_kmeans (xem module docstring).
    """
    sums = np.zeros(n_bits)
    counts = np.zeros(n_bits)
    np.add.at(sums, bit_slot_map, decisions.astype(np.float64))
    np.add.at(counts, bit_slot_map, 1.0)
    counts[counts == 0] = 1.0  # an toàn, không nên xảy ra nếu build_slot_bit_map đúng
    avg = sums / counts

    if method == "kmeans":
        return one_dim_kmeans_threshold(avg).astype(np.uint8)
    return (avg >= 0.5).astype(np.uint8)


def one_dim_kmeans_threshold(values: np.ndarray) -> np.ndarray:
    """Phân cụm 1 chiều thành 2 nhóm (0/1) bằng lặp ngưỡng-trung điểm.

    Chuyển thể từ `blind_watermark.bwm_core.one_dim_kmeans`
    (github.com/guofei9987/blind_watermark, MIT License). Hữu ích khi phân bố
    `values` (trung bình phiếu bầu mỗi bit, trong [0,1]) bị lệch hệ thống khỏi
    0.5 -- ví dụ sau tấn công chỉnh sáng/tương phản toàn cục làm mọi phiếu bầu
    dịch cùng chiều -- ngưỡng cố định 0.5 lúc đó sai lệch, còn ngưỡng thích
    ứng tìm điểm chia tách 2 cụm thực tế trong chính dữ liệu quan sát được.
    """
    if values.size < 2 or values.max() == values.min():
        return values >= 0.5

    threshold = 0.5
    center = [values.min(), values.max()]
    e_tol = 1e-6
    for _ in range(300):
        threshold = (center[0] + center[1]) / 2
        is_class1 = values > threshold
        if not is_class1.any() or is_class1.all():
            break
        center = [values[~is_class1].mean(), values[is_class1].mean()]
        if abs((center[0] + center[1]) / 2 - threshold) < e_tol:
            threshold = (center[0] + center[1]) / 2
            break

    return values > threshold
