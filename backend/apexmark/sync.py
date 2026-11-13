"""Đồng bộ hình học (geometric resync): vá điểm yếu "gãy khi lệch lưới" của
apexmark bằng kỹ thuật template-matching mượn từ `blind_watermark.recover`
(guofei9987/blind_watermark, MIT License).

BỐI CẢNH: apexmark nhúng bit vào TRUNG BÌNH từng khối 4x4 cố định theo toạ độ
tuyệt đối. Bất kỳ phép biến đổi nào làm xê dịch lưới pixel (cắt, dịch, xoay,
resize không đồng nhất) đều làm sai lệch hoàn toàn ranh giới khối -> hỏng
watermark, dù nội dung ảnh gần như không đổi về mặt thị giác.

blind_watermark tự nó KHÔNG chống xoay/cắt bằng cơ chế đồng bộ hình học —
robust của nó với xoay 45° trong README đến từ nhúng LẶP LẠI hàng nghìn lần
(xem apexmark.redundancy). Nhưng thư viện này CÓ sẵn `recover.py`: dùng
`cv2.matchTemplate` đa tỉ lệ để tìm ảnh nhận được (có thể đã bị cắt/co giãn)
nằm ở đâu, tỉ lệ bao nhiêu, bên trong ảnh gốc/tham chiếu — rồi dựng lại đúng
khung hình gốc trước khi giải mã. Đây CHÍNH LÀ cơ chế còn thiếu của apexmark.

Module này chuyển thể ý tưởng đó nhưng đổi vai trò cho phù hợp triết lý
"khoá tự chứa" của apexmark (không cần giữ lại ảnh gốc riêng để đối chiếu):
  - Lúc embed (store_thumbnail=True), một ẢNH THU NHỎ (thumbnail) của chính
    ảnh đã nhúng watermark được lưu VÀO TRONG keys — đóng vai trò "ảnh tham
    chiếu" (ori_img trong recover.py gốc), chỉ tốn vài KB.
  - Lúc extract, ảnh nhận được (có thể đã bị tấn công) đóng vai trò "template"
    cần định vị bên trong ảnh tham chiếu thu nhỏ đó.
  - Sau khi định vị được (vị trí + tỉ lệ), dựng lại một khung ảnh đúng kích
    thước lúc nhúng ban đầu (`orig_shape`) rồi mới đưa vào `apexmark.extract()`.

GIỚI HẠN THÀNH THẬT (đo thực nghiệm, xem tests/test_sync.py):
  - Cắt / dịch / resize (kể cả kết hợp cả hai): khôi phục tốt, vì đây đúng
    loại tấn công mà thuật toán search_template được thiết kế để xử lý.
  - Xoay: KHÔNG có trong recover.py gốc. Module này bổ sung một bước dò góc
    xoay thô (brute-force trong `angle_range`, mặc định TẮT vì tốn thời gian)
    trước khi chạy search_template ở mỗi góc ứng viên. Chỉ đáng tin với góc
    xoay nhỏ-vừa (khuyến nghị |angle| <= 10-15°, bước 0.5-1°); xoay lớn (như
    45° trong demo của blind_watermark) đòi hỏi kết hợp thêm dự phòng mạnh từ
    `apexmark.redundancy`, không chỉ riêng bước đồng bộ này.
  - ẢNH CÓ KẾT CẤU LẶP LẠI/CHU KỲ (sóng, vân vải dệt, lưới ô, hoạ tiết lát
    gạch...): matchTemplate có thể báo điểm khớp CAO (>0.99) ở một VỊ TRÍ SAI
    (lệch đúng bội số chu kỳ của hoạ tiết) — đây là giới hạn kinh điển của
    correlation-based template matching, không phải lỗi implement, và KHÔNG
    có cách phát hiện tự động đáng tin cậy bằng các chỉ số thống kê đơn giản
    (đã thử z-score của bản đồ tương quan, không đủ phân biệt). Nếu ảnh của
    bạn có hoạ tiết lặp lại rõ, LUÔN kiểm tra bằng `apexmark.evaluate.
    run_battery()` trên chính ảnh đó trước khi tin cậy `resync()`/
    `extract_robust()` — đừng chỉ tin vào điểm số trả về.
  - Tấn công KẾT HỢP cực đoan (xoay lớn + cắt sâu + JPEG mạnh cùng lúc): xem
    README mục "Vá điểm yếu" — bước resample để sửa hình học có thể tự làm
    nhoè đủ để xoá tín hiệu QIM, dù định vị đúng vị trí. ĐÃ THỬ khắc phục
    bằng cách gộp xoay+co giãn thành 1 lần warpAffine (thay vì 2 lần resample
    riêng biệt) với giả thuyết giảm nhoè tích luỹ — ĐO ĐƯỢC KHÔNG CẢI THIỆN
    (tệ hơn ở phần lớn trường hợp thử), và đổi thử 4 loại nội suy khác nhau
    (LINEAR/AREA/CUBIC/LANCZOS4) cho CÙNG một BER. Kết luận: nút thắt ở đây
    không phải chất lượng nội suy, mà là SAI SỐ ĐỊNH VỊ tự thân (toạ độ vùng
    tìm được qua matchTemplate ở độ phân giải thumbnail, dù phóng lên đúng
    tỉ lệ, vẫn mang sai số vài pixel tại độ phân giải gốc) — không có cách
    sửa bằng khâu dựng-lại-ảnh, cần một thuật toán định vị chính xác hơn hẳn
    (ngoài phạm vi cải tiến hiện tại). Xem lịch sử trao đổi lúc phát triển
    hoặc CHANGELOG để biết chi tiết thử nghiệm.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .blocks import is_color, rgb_to_luma
from .imageio import normalize


class SyncUnavailable(RuntimeError):
    """Không có OpenCV (cv2) -- cần cho template matching. `pip install opencv-python-headless`."""


def is_available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def _require_cv2():
    if not is_available():
        raise SyncUnavailable(
            "apexmark.sync cần OpenCV để dò vị trí/tỉ lệ (template matching). "
            "Cài bằng: pip install opencv-python-headless"
        )
    import cv2
    return cv2


def make_thumbnail(luma: np.ndarray, max_side: int = 256) -> np.ndarray:
    """Thu nhỏ `luma` (float64, 0-255) về ảnh tham chiếu uint8, cạnh dài
    <= max_side. Dùng PIL (không cần cv2) để store_thumbnail=True hoạt động
    ngay cả khi chưa cài OpenCV -- chỉ resync() lúc extract mới cần cv2."""
    from PIL import Image as _PILImage
    h, w = luma.shape
    scale = max_side / max(h, w)
    if scale >= 1.0:
        return np.clip(luma, 0, 255).astype(np.uint8)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    im = _PILImage.fromarray(np.clip(luma, 0, 255).astype(np.uint8))
    return np.array(im.resize((new_w, new_h), _PILImage.BILINEAR))


def _search_crop_scale(cv2, reference: np.ndarray, received: np.ndarray,
                        scale_range=(0.5, 2.0), search_num: int = 60,
                        search_aspect: bool = False):
    """Chuyển thể `search_template` + `estimate_crop_parameters` của
    blind_watermark.recover (MIT) sang thao tác trực tiếp trên mảng numpy
    thay vì đọc/ghi file, và không dùng cache lru toàn cục (để an toàn khi
    gọi song song / nhiều ảnh khác nhau trong cùng tiến trình).

    reference : ảnh tham chiếu (haystack), 2D uint8/float.
    received  : ảnh cần định vị bên trong reference (needle), 2D.

    Trả về (x1, y1, x2, y2, score) -- vùng trong `reference` khớp nhất với
    `received` sau khi co giãn. search_aspect=True cho phép tỉ lệ x/y KHÁC
    NHAU (chống resize/crop không giữ tỉ lệ khung hình) -- chậm hơn, chỉ nên
    bật khi cần.
    """
    reference = reference.astype(np.float32)
    min_scale, max_scale = scale_range
    max_scale = min(max_scale,
                     reference.shape[0] / received.shape[0],
                     reference.shape[1] / received.shape[1])
    if max_scale <= 0:
        return None

    # --- pha 1: tỉ lệ đồng nhất (nhanh) ---
    best = None  # (score, ind, scale)
    lo, hi, n = min_scale, max_scale, search_num
    for _pass in range(2):
        candidates = []
        for scale in np.linspace(lo, hi, max(3, n)):
            w = max(1, round(received.shape[1] * scale))
            h = max(1, round(received.shape[0] * scale))
            if h > reference.shape[0] or w > reference.shape[1]:
                continue
            resized = cv2.resize(received.astype(np.float32), dsize=(w, h))
            scores = cv2.matchTemplate(reference, resized, cv2.TM_CCOEFF_NORMED)
            ind = np.unravel_index(np.argmax(scores, axis=None), scores.shape)
            candidates.append((float(scores[ind]), ind, scale))
        if not candidates:
            return None
        candidates.sort(key=lambda t: -t[0])
        best = candidates[0]
        scales_sorted = sorted(c[2] for c in candidates)
        pos = scales_sorted.index(best[2])
        lo = scales_sorted[max(0, pos - 1)]
        hi = scales_sorted[min(len(scales_sorted) - 1, pos + 1)]
        n = max(5, 2 * int((hi - lo) * max(received.shape[0], received.shape[1])) + 1)
        if hi - lo < 1e-6:
            break

    score, ind, scale = best
    y1, x1 = ind
    scale_x = scale_y = scale

    # --- pha 2 (tuỳ chọn): tinh chỉnh tỉ lệ x/y ĐỘC LẬP quanh scale đẳng
    # hướng vừa tìm được -- vá resize/crop không giữ tỉ lệ khung hình ---
    if search_aspect:
        best_aniso = (score, x1, y1, scale_x, scale_y)
        for sx in np.linspace(scale * 0.75, scale * 1.25, 7):
            for sy in np.linspace(scale * 0.75, scale * 1.25, 7):
                w = max(1, round(received.shape[1] * sx))
                h = max(1, round(received.shape[0] * sy))
                if h > reference.shape[0] or w > reference.shape[1]:
                    continue
                resized = cv2.resize(received.astype(np.float32), dsize=(w, h))
                scores = cv2.matchTemplate(reference, resized, cv2.TM_CCOEFF_NORMED)
                ind2 = np.unravel_index(np.argmax(scores, axis=None), scores.shape)
                s2 = float(scores[ind2])
                if s2 > best_aniso[0]:
                    yy1, xx1 = ind2
                    best_aniso = (s2, xx1, yy1, sx, sy)
        score, x1, y1, scale_x, scale_y = best_aniso

    w = round(received.shape[1] * scale_x)
    h = round(received.shape[0] * scale_y)
    return (x1, y1, x1 + w, y1 + h, score)


def _identity_score(cv2, reference: np.ndarray, received: np.ndarray) -> float:
    """Điểm tương quan nếu KHÔNG cắt/định vị gì cả -- cả `received` map
    thẳng vào toàn bộ khung hình. Dùng làm "giả thuyết rỗng" cạnh tranh với
    kết quả từ _search_crop_scale, để resync() không bao giờ chọn một vùng
    cắt nhỏ giả tạo (score cao do trùng hợp cục bộ) tệ hơn phương án đơn
    giản là tin cả ảnh nhận được đúng như nó vốn có."""
    resized = cv2.resize(received.astype(np.float32),
                          dsize=(reference.shape[1], reference.shape[0]))
    corr = np.corrcoef(resized.ravel(), reference.astype(np.float32).ravel())[0, 1]
    return float(corr) if np.isfinite(corr) else -1.0


def _rotate(cv2, img: np.ndarray, angle: float) -> np.ndarray:
    """Xoay quanh tâm ảnh, KHÔNG mở rộng khung (viền ngoài fill bằng biên
    lặp lại -- reflect -- để không tạo viền đen giả làm nhiễu matchTemplate)."""
    if angle == 0:
        return img
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img.astype(np.float32), M, (w, h),
                           borderMode=cv2.BORDER_REFLECT101)


def resync(image, keys: dict, *,
           scale_range=(0.5, 2.0), search_num: int = 60, search_aspect: bool = False,
           angle_range=(0.0, 0.0), angle_step: float = 1.0,
           min_score: float = 0.3, fast_path_score: float = 0.98,
           crop_margin: float = 0.10,
           verbose: bool = False) -> Optional[np.ndarray]:
    """Cố dựng lại khung ảnh đúng kích thước lúc embed() (`keys["orig_shape"]`)
    từ `image` (có thể đã bị cắt/dịch/co giãn/xoay), sẵn sàng đưa vào
    `apexmark.extract()`.

    Trả về mảng (H,W) luma float64 nếu tìm được vị trí đủ tin cậy, hoặc
    None nếu không (nên fallback về extract() trực tiếp trên ảnh gốc).

    Ở MỌI góc ứng viên, hai giả thuyết luôn cạnh tranh: (1) "được cắt/dịch
    một vùng con" (tìm bằng matchTemplate) và (2) "không cắt gì cả, cả ảnh
    map thẳng vào khung gốc" (identity). Phương án cắt-vùng-con CHỈ được
    chọn khi điểm của nó vượt identity ít nhất `crop_margin` -- nếu không,
    một chênh lệch nhỏ do NHIỄU NGẪU NHIÊN (vd ảnh chỉ bị thêm nhiễu Gauss,
    không hề bị cắt) có thể khiến matchTemplate "thắng" giả tạo bằng một
    vùng lệch vài pixel, tự gây thêm méo không cần thiết mà không sửa được
    gì thật. Nhờ biên an toàn này, resync() không bao giờ tệ hơn không làm
    gì trên ảnh chỉ bị nhiễu/nén/chỉnh màu (không hình học).

    angle_range   : (min_deg, max_deg) -- (0,0) mặc định = KHÔNG dò xoay
                    (nhanh, chỉ xử lý cắt/dịch/co giãn). Truyền vd (-10,10)
                    để bật dò xoay -- xem giới hạn thành thật ở docstring module.
    search_aspect : True = cho phép tỉ lệ x/y khác nhau (chống resize/crop
                    không giữ tỉ lệ khung hình). Chậm hơn đáng kể.
    """
    cv2 = _require_cv2()

    if "thumbnail" not in keys or "orig_shape" not in keys:
        raise ValueError(
            "keys không có 'thumbnail' -- nhúng lại với embed(..., "
            "store_thumbnail=True) thì mới dùng được resync()."
        )

    reference = np.asarray(keys["thumbnail"]).astype(np.float32)
    orig_shape = tuple(int(v) for v in np.asarray(keys["orig_shape"]))

    work, _ = normalize(image)
    luma = rgb_to_luma(work) if is_color(work) else work
    luma = luma.astype(np.float64)

    # --- fast path: kích thước khớp lúc nhúng + tương quan cao -> không tấn công hình học ---
    if luma.shape == orig_shape:
        corr = _identity_score(cv2, reference, luma)
        if corr >= fast_path_score:
            if verbose:
                print(f"apexmark.sync: fast-path, tuong quan={corr:.3f} -> khong can dong bo lai.")
            return luma

    angles = np.arange(angle_range[0], angle_range[1] + 1e-9,
                        max(angle_step, 1e-6)) if angle_range[1] > angle_range[0] else [0.0]

    # `reference` (thumbnail) THƯỜNG nhỏ hơn `orig_shape` nhiều lần (mặc định
    # cạnh dài tối đa 256px, trong khi ảnh gốc có thể lớn hơn hẳn) -- luôn
    # cần một hệ số co baseline = reference/orig CHỈ ĐỂ khớp kích thước, tách
    # biệt với hệ số co do CHÍNH tấn công gây ra. scale_range của người dùng
    # mô tả mức ĐỘ PHÓNG TO/THU NHỎ TƯƠNG ĐỐI do tấn công (attacker resize/
    # crop-zoom), không phải tỉ lệ tuyệt đối received/reference -- nên phải
    # nhân thêm baseline trước khi đưa vào _search_crop_scale.
    baseline = min(reference.shape[0] / orig_shape[0], reference.shape[1] / orig_shape[1])
    effective_scale_range = (scale_range[0] * baseline, scale_range[1] * baseline)

    best = None  # (score, angle, kind, box_or_None, rotated_image)
    for angle in angles:
        rotated = _rotate(cv2, luma, float(angle)) if angle != 0.0 else luma

        id_score = _identity_score(cv2, reference, rotated)
        if best is None or id_score > best[0]:
            best = (id_score, angle, "identity", None, rotated)

        result = _search_crop_scale(cv2, reference, rotated, scale_range=effective_scale_range,
                                     search_num=search_num, search_aspect=search_aspect)
        if result is not None:
            x1, y1, x2, y2, score = result
            # Toạ độ x1,y1,x2,y2 đang ở KHÔNG GIAN THU NHỎ (reference); diện
            # tích tương đối so với reference cũng chính là diện tích tương
            # đối so với orig_shape (cùng tỉ lệ khung hình), dùng được ngay
            # không cần quy đổi.
            box_frac = ((x2 - x1) * (y2 - y1)) / (reference.shape[0] * reference.shape[1])
            # Chấp nhận "crop" khi vùng tìm được THỰC SỰ nhỏ hơn đáng kể so
            # với toàn khung (đáng để sửa) VÀ vượt identity một biên đủ lớn.
            # Chỉ dùng điểm số (margin/tuyệt đối) KHÔNG đủ: nhiễu Gauss/muối-
            # tiêu không hề cắt ảnh vẫn có thể ngẫu nhiên khớp tốt hơn một
            # chút ở một vùng gần-như-toàn-khung (vd 99% diện tích) -- sửa
            # một vùng gần như toàn bộ ảnh không có ý nghĩa gì và chỉ tự gây
            # thêm nhiễu resample. Một dịch chuyển thật dù chỉ vài pixel vẫn
            # luôn để lại vùng nhỏ hơn RÕ RỆT (đo thực nghiệm: ~97.7% cho
            # dịch 3px/256px, so với ~99%+ cho nhiễu ngẫu nhiên không cắt).
            is_real_crop = box_frac < 0.98
            accept = is_real_crop and (score >= 0.97 or score > id_score + crop_margin)
            if accept and score > best[0]:
                best = (score, angle, "crop", (x1, y1, x2, y2), rotated)

        if verbose:
            crop_str = f" crop={result[4]:.3f}" if result else ""
            print(f"apexmark.sync: goc={angle:+.2f} identity={id_score:.3f}{crop_str}")

    if best is None or best[0] < min_score:
        if verbose:
            print(f"apexmark.sync: khong tim duoc vi tri du tin cay "
                  f"(score={0 if best is None else best[0]:.3f} < {min_score}).")
        return None

    score, angle, kind, box, rotated = best

    if kind == "identity":
        canvas = cv2.resize(rotated.astype(np.float32),
                             dsize=(orig_shape[1], orig_shape[0])).astype(np.float64)
        if verbose:
            print(f"apexmark.sync: chon goc={angle:+.2f} kieu=identity score={score:.3f}")
        return canvas

    x1, y1, x2, y2 = box
    # toạ độ trên đang ở KHÔNG GIAN THU NHỎ (reference) -> phóng lên orig_shape
    fy = orig_shape[0] / reference.shape[0]
    fx = orig_shape[1] / reference.shape[1]
    X1, Y1, X2, Y2 = int(round(x1 * fx)), int(round(y1 * fy)), int(round(x2 * fx)), int(round(y2 * fy))
    X1, Y1 = max(0, X1), max(0, Y1)
    X2, Y2 = min(orig_shape[1], max(X1 + 1, X2)), min(orig_shape[0], max(Y1 + 1, Y2))

    # ĐÃ THỬ gộp xoay+co giãn thành 1 lần warpAffine duy nhất (thay vì xoay
    # rồi resize riêng) với giả thuyết giảm nhoè do nội suy chồng nhau --
    # ĐO ĐƯỢC KHÔNG CẢI THIỆN (tệ hơn ở 3/4 trường hợp thử), và đổi cả 4 loại
    # nội suy (LINEAR/AREA/CUBIC/LANCZOS4) cho CÙNG một BER -- chứng tỏ nút
    # thắt không nằm ở chất lượng nội suy mà ở sai số ĐỊNH VỊ (toạ độ vùng
    # tìm được, dù đã phóng lên đúng tỉ lệ, vẫn có sai số vài pixel không thể
    # sửa bằng cách nội suy tốt hơn). Giữ lại cách 2 bước (đơn giản hơn, đã
    # kiểm chứng qua toàn bộ test suite) thay vì đổi sang cách phức tạp hơn
    # mà không có lợi ích đo được -- xem tests/test_sync.py.
    patch = cv2.resize(rotated.astype(np.float32), dsize=(X2 - X1, Y2 - Y1))
    canvas = np.zeros(orig_shape, dtype=np.float64)
    canvas[Y1:Y2, X1:X2] = patch

    if verbose:
        print(f"apexmark.sync: chon goc={angle:+.2f} kieu=crop score={score:.3f} "
              f"vung=({X1},{Y1},{X2},{Y2})")
    return canvas


def extract_robust(image, keys: dict, *, try_resync: bool = True,
                    aggregate: str = "mean", resync_kwargs: Optional[dict] = None,
                    verbose: bool = False) -> np.ndarray:
    """Tiện ích: thử resync() trước, thất bại thì trích trực tiếp trên ảnh gốc.

    Chỉ hữu ích nếu embed() đã được gọi với store_thumbnail=True. Nếu keys
    không có thumbnail, tương đương gọi thẳng apexmark.extract().
    """
    from .core import extract

    if try_resync and "thumbnail" in keys:
        recovered = resync(image, keys, verbose=verbose, **(resync_kwargs or {}))
        if recovered is not None:
            return extract(recovered, keys, aggregate=aggregate)
        if verbose:
            print("apexmark.sync: resync that bai, fallback trich xuat truc tiep.")
    return extract(image, keys, aggregate=aggregate)
