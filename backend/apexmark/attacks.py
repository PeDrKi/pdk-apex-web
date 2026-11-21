"""Bộ mô phỏng tấn công tiêu chuẩn để ĐO ĐẠC HỆ THỐNG độ bền, thay vì kiểm tra
từng trường hợp rời rạc. Cấu trúc mượn từ `blind_watermark.att` (guofei9987,
MIT) — cùng nhóm tấn công (nén, nhiễu, lọc, hình học, che khuất) nhưng viết
lại để thao tác trực tiếp trên mảng numpy/luma của apexmark thay vì đọc/ghi
file, và có thang MỨC ĐỘ (mild/moderate/severe) rõ ràng cho từng tấn công
thay vì một tham số cố định.

DÙNG ĐỂ LÀM GÌ: mỗi thuật toán watermark có một "bản đồ độ bền" khác nhau —
không có ngưỡng phổ quát nào đúng cho mọi ảnh/tham số. Thay vì chỉ tin vào
một vài con số trong README, dùng `run_battery()` (xem apexmark.evaluate) để
tự đo trên chính ảnh/tham số của bạn.

Mỗi hàm attack_* nhận vào ảnh (2D grayscale hoặc 3D RGB, dtype bất kỳ trong
0-255) và trả về ảnh cùng shape/dtype dạng đã tấn công. `severity` càng cao
càng khắc nghiệt (thang 1-3: nhẹ/vừa/nặng), NGOẠI TRỪ jpeg_compress dùng
tham số `quality` trực tiếp (chất lượng càng THẤP càng khắc nghiệt).
"""
from __future__ import annotations

import io
from typing import Callable, Optional

import numpy as np
from PIL import Image


def _to_uint8(image: np.ndarray) -> np.ndarray:
    return np.clip(image, 0, 255).astype(np.uint8)


def _as_pil(image: np.ndarray) -> Image.Image:
    return Image.fromarray(_to_uint8(image))


# --------------------------------------------------------------------------- #
# Nén / lượng tử hoá
# --------------------------------------------------------------------------- #

def jpeg_compress(image: np.ndarray, quality: int = 50) -> np.ndarray:
    """quality: 1-100, càng thấp càng khắc nghiệt (mặc định blind_watermark
    hay test ở q50, q70, q90)."""
    buf = io.BytesIO()
    _as_pil(image).convert("RGB" if np.asarray(image).ndim == 3 else "L").save(
        buf, format="JPEG", quality=int(quality))
    buf.seek(0)
    out = np.array(Image.open(buf))
    return out if np.asarray(image).ndim == 3 else out


# --------------------------------------------------------------------------- #
# Nhiễu
# --------------------------------------------------------------------------- #

_SEV_NOISE_SIGMA = {1: 5, 2: 15, 3: 30}
_SEV_SALT_RATIO = {1: 0.01, 2: 0.05, 3: 0.15}


def gaussian_noise(image: np.ndarray, severity: int = 2, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sigma = _SEV_NOISE_SIGMA[severity]
    noisy = image.astype(np.float64) + rng.normal(0, sigma, image.shape)
    return np.clip(noisy, 0, 255)


def salt_pepper(image: np.ndarray, severity: int = 2, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    ratio = _SEV_SALT_RATIO[severity]
    out = image.astype(np.float64).copy()
    mask = rng.random(image.shape[:2]) < ratio
    vals = rng.choice([0, 255], size=int(mask.sum()))
    if out.ndim == 3:
        out[mask] = vals[:, None]
    else:
        out[mask] = vals
    return out


# --------------------------------------------------------------------------- #
# Lọc (giữ nguyên lưới pixel, nhưng làm mờ/nhiễu giá trị trung bình khối)
# --------------------------------------------------------------------------- #

_SEV_BLUR_KSIZE = {1: 3, 2: 5, 3: 7}


def median_blur(image: np.ndarray, severity: int = 1) -> np.ndarray:
    import cv2
    k = _SEV_BLUR_KSIZE[severity]
    return cv2.medianBlur(_to_uint8(image), k).astype(np.float64)


def gaussian_blur(image: np.ndarray, severity: int = 1) -> np.ndarray:
    import cv2
    k = _SEV_BLUR_KSIZE[severity]
    return cv2.GaussianBlur(_to_uint8(image), (k, k), 0).astype(np.float64)


def sharpen(image: np.ndarray, severity: int = 2) -> np.ndarray:
    import cv2
    amount = {1: 0.5, 2: 1.0, 3: 2.0}[severity]
    u8 = _to_uint8(image)
    blur = cv2.GaussianBlur(u8, (0, 0), 3)
    return np.clip(cv2.addWeighted(u8, 1 + amount, blur, -amount, 0), 0, 255).astype(np.float64)


# --------------------------------------------------------------------------- #
# Chỉnh màu / độ sáng-tương phản (biến đổi giá trị pixel, KHÔNG lệch lưới)
# --------------------------------------------------------------------------- #

_SEV_GAMMA = {1: 1.2, 2: 1.5, 3: 2.2}
_SEV_BRIGHTNESS = {1: 15, 2: 30, 3: 60}
_SEV_CONTRAST = {1: 0.85, 2: 0.7, 3: 0.5}


def gamma(image: np.ndarray, severity: int = 2, darken: bool = False) -> np.ndarray:
    g = _SEV_GAMMA[severity]
    if darken:
        g = 1 / g
    lut = ((np.arange(256) / 255.0) ** (1 / g)) * 255
    return lut[_to_uint8(image)]


def hist_equalize(image: np.ndarray) -> np.ndarray:
    import cv2
    if image.ndim == 3:
        yuv = cv2.cvtColor(_to_uint8(image), cv2.COLOR_RGB2YUV)
        yuv[:, :, 0] = cv2.equalizeHist(yuv[:, :, 0])
        return cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB).astype(np.float64)
    return cv2.equalizeHist(_to_uint8(image)).astype(np.float64)


def brightness(image: np.ndarray, severity: int = 2, darken: bool = False) -> np.ndarray:
    delta = _SEV_BRIGHTNESS[severity] * (-1 if darken else 1)
    return np.clip(image.astype(np.float64) + delta, 0, 255)


def contrast(image: np.ndarray, severity: int = 2) -> np.ndarray:
    factor = _SEV_CONTRAST[severity]
    return np.clip((image.astype(np.float64) - 127.5) * factor + 127.5, 0, 255)


# --------------------------------------------------------------------------- #
# Hình học (làm lệch lưới pixel -- cần apexmark.sync.resync để phục hồi)
# --------------------------------------------------------------------------- #

_SEV_RESIZE = {1: 0.8, 2: 0.6, 3: 0.4}
_SEV_ROTATE = {1: 2.0, 2: 8.0, 3: 20.0}
_SEV_CROP = {1: 0.05, 2: 0.15, 3: 0.30}
_SEV_SHIFT_FRAC = {1: 0.02, 2: 0.06, 3: 0.12}
_SEV_OCCLUDE_FRAC = {1: 0.1, 2: 0.2, 3: 0.35}


def resize(image: np.ndarray, severity: int = 2, restore_size: bool = True) -> np.ndarray:
    """Thu nhỏ giữ tỉ lệ. restore_size=True: phóng lại về kích thước gốc
    (kiểu tấn công "resize rồi upload lại kích thước cũ", giữ nguyên lưới
    -- KHÔNG cần resync); False: trả về kích thước đã thu nhỏ (cần resync)."""
    h, w = image.shape[:2]
    f = _SEV_RESIZE[severity]
    small = np.array(_as_pil(image).resize((max(1, round(w * f)), max(1, round(h * f)))))
    if not restore_size:
        return small.astype(np.float64)
    return np.array(Image.fromarray(small).resize((w, h))).astype(np.float64)


def resize_nonuniform(image: np.ndarray, severity: int = 2) -> np.ndarray:
    """Resize KHÔNG giữ tỉ lệ khung hình (bóp méo x/y khác nhau), rồi phục
    hồi lại kích thước gốc -- kiểu tấn công hay gặp khi ảnh bị chèn ép vào
    khung UI cố định."""
    h, w = image.shape[:2]
    fx = _SEV_RESIZE[severity]
    fy = 1.0 - (1.0 - fx) * 0.5  # méo nhẹ hơn theo trục còn lại
    warped = np.array(_as_pil(image).resize((max(1, round(w * fx)), max(1, round(h * fy)))))
    return np.array(Image.fromarray(warped).resize((w, h))).astype(np.float64)


def rotate(image: np.ndarray, severity: int = 1, restore_size: bool = True) -> np.ndarray:
    """restore_size=True: xoay trong khung cũ (viền góc bị cắt/đệm) --
    tương ứng angle_range trong resync(). False: mở khung đủ chứa cả ảnh
    xoay (không mất góc, nhưng shape thay đổi)."""
    deg = _SEV_ROTATE[severity]
    im = _as_pil(image)
    return np.array(im.rotate(deg, expand=not restore_size, fillcolor=0)).astype(np.float64)


def crop_resize(image: np.ndarray, severity: int = 1) -> np.ndarray:
    """Cắt rìa rồi phóng to lại đúng kích thước gốc -- cut_att3 kinh điển."""
    h, w = image.shape[:2]
    frac = _SEV_CROP[severity]
    cropped = image[int(h * frac):int(h * (1 - frac)), int(w * frac):int(w * (1 - frac))]
    return np.array(_as_pil(cropped).resize((w, h))).astype(np.float64)


def crop_no_resize(image: np.ndarray, severity: int = 1) -> np.ndarray:
    """Cắt rìa, KHÔNG phóng lại -- ảnh trả về NHỎ HƠN ảnh gốc."""
    h, w = image.shape[:2]
    frac = _SEV_CROP[severity]
    return image[int(h * frac):int(h * (1 - frac)), int(w * frac):int(w * (1 - frac))].astype(np.float64)


def shift(image: np.ndarray, severity: int = 1) -> np.ndarray:
    """Dịch pixel (crop 1 góc, KHÔNG resize) -- ảnh trả về nhỏ hơn."""
    h, w = image.shape[:2]
    px = max(1, int(min(h, w) * _SEV_SHIFT_FRAC[severity]))
    return image[px:, px:].astype(np.float64)


def occlusion(image: np.ndarray, severity: int = 2, seed: int = 0, fill: float = 255) -> np.ndarray:
    """Che một mảng vuông liên tục -- giống shelter_att của blind_watermark."""
    rng = np.random.default_rng(seed)
    frac = _SEV_OCCLUDE_FRAC[severity]
    h, w = image.shape[:2]
    side_h, side_w = int(h * frac), int(w * frac)
    y0 = rng.integers(0, max(1, h - side_h))
    x0 = rng.integers(0, max(1, w - side_w))
    out = image.astype(np.float64).copy()
    out[y0:y0 + side_h, x0:x0 + side_w] = fill
    return out


# --------------------------------------------------------------------------- #
# BC7 -- TẤN CÔNG CỐT LÕI apexmark được thiết kế để chống (xem tên gọi APEX).
# Không có bản mô phỏng/xấp xỉ: BC7 mã hoá theo endpoint+index rất đặc thù
# cho từng khối 4x4, một phép nén giả lập (vd lượng tử hoá thô) sẽ cho kết
# quả GÂY HIỂU LẦM thay vì hữu ích -- PHẢI dùng CompressonatorCLI thật.
# --------------------------------------------------------------------------- #

def _bc7_cli(exe_path=None) -> bool:
    from . import bc7 as _bc7
    try:
        _bc7.find_compressonator(exe_path)
        return True
    except _bc7.CompressonatorNotFound:
        return False


def bc7_compress(image: np.ndarray, exe_path: Optional[str] = None,
                  encode_with: str = "HPC") -> np.ndarray:
    """Nén BC7 THẬT qua AMD CompressonatorCLI. Cần cài đặt, xem
    `apexmark.bc7` (biến môi trường COMPRESSONATOR_PATH). Raise
    `apexmark.bc7.CompressonatorNotFound` nếu chưa cài -- KHÔNG âm thầm bỏ
    qua, vì đây là phép thử quan trọng nhất của toàn bộ thư viện này.

    encode_with : mặc định "HPC" -- GIỮ NGUYÊN theo bản nghiên cứu gốc, đừng
            đổi trừ khi chủ động muốn so sánh nhiều bộ mã hoá BC7 (xem
            `standard_battery(extra_bc7_modes=[...])`)."""
    from . import bc7 as _bc7
    fn = _bc7.make_best_bc7_fn(exe_path=exe_path, encode_with=encode_with) \
        if _bc7.inproc_available() and not _bc7_cli(exe_path) else _bc7.make_bc7_fn(exe_path=exe_path, encode_with=encode_with)
    return fn(image)


# --------------------------------------------------------------------------- #
# Kết hợp nhiều tấn công (mô phỏng chuỗi xử lý thực tế: chỉnh sửa -> đăng
# lên nền tảng tự nén/resize)
# --------------------------------------------------------------------------- #

def chain(image: np.ndarray, *attacks: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    """Áp lần lượt nhiều hàm attack_*, ví dụ:
    chain(img, lambda x: rotate(x, 1), lambda x: crop_resize(x, 1),
          lambda x: jpeg_compress(x, 70))
    """
    out = image
    for fn in attacks:
        out = fn(out)
    return out


# --------------------------------------------------------------------------- #
# Bộ tấn công chuẩn để quét (dict tên -> hàm nhận (image) và trả ảnh tấn công).
# `geometric=True` đánh dấu tấn công làm lệch lưới (cần resync để phục hồi).
# --------------------------------------------------------------------------- #

def standard_battery(severity: int = 2, seed: int = 0, include_bc7: bool = True,
                      bc7_exe_path: Optional[str] = None,
                      extra_bc7_modes: Optional[list] = None) -> dict:
    """Trả về {tên_tấn_công: (hàm(image)->image, geometric: bool)}.
    Dùng với apexmark.evaluate.run_battery().

    include_bc7 : True (mặc định) = có "nen_bc7_that" trong battery -- ĐÂY
            LÀ TẤN CÔNG QUAN TRỌNG NHẤT (lý do apexmark ra đời), luôn nên
            bật trừ khi máy chắc chắn không có CompressonatorCLI. Nếu thiếu
            tool, hàm sẽ raise CompressonatorNotFound khi thực sự chạy tới
            (evaluate.run_battery() bắt lỗi này và báo "lỗi: ..." thay vì
            crash, nhưng bạn sẽ KHÔNG có kết quả BC7 thật cho tới khi cài).
    extra_bc7_modes : danh sách tên bộ mã hoá BC7 KHÁC "HPC" (mặc định) muốn
            so sánh thêm, vd ["CPU"] -- mỗi tên thêm một mục
            "nen_bc7_that_<ten>" vào battery. TUỲ CHỌN, KHÔNG bật mặc định
            để không làm lệch kết quả đã có so với bản nghiên cứu gốc (vốn
            cố định dùng HPC). Tên hợp lệ tuỳ phiên bản CompressonatorCLI,
            chạy `<exe> -help` để xem đầy đủ.
    """
    s = severity
    battery = {}
    if include_bc7:
        battery["nen_bc7_that"] = (lambda img: bc7_compress(img, bc7_exe_path), False)
        for mode in (extra_bc7_modes or []):
            battery[f"nen_bc7_that_{mode.lower()}"] = (
                lambda img, m=mode: bc7_compress(img, bc7_exe_path, encode_with=m), False)
    battery.update({
        "jpeg_q50": (lambda img: jpeg_compress(img, 50), False),
        "jpeg_q30": (lambda img: jpeg_compress(img, 30), False),
        "gaussian_noise": (lambda img: gaussian_noise(img, s, seed), False),
        "salt_pepper": (lambda img: salt_pepper(img, s, seed), False),
        "median_blur": (lambda img: median_blur(img, s), False),
        "gaussian_blur": (lambda img: gaussian_blur(img, s), False),
        "sharpen": (lambda img: sharpen(img, s), False),
        "gamma_sang": (lambda img: gamma(img, s, darken=False), False),
        "gamma_toi": (lambda img: gamma(img, s, darken=True), False),
        "hist_equalize": (lambda img: hist_equalize(img), False),
        "brightness_sang": (lambda img: brightness(img, s, darken=False), False),
        "brightness_toi": (lambda img: brightness(img, s, darken=True), False),
        "contrast": (lambda img: contrast(img, s), False),
        "resize_giu_ti_le": (lambda img: resize(img, s, restore_size=True), False),
        "resize_khong_giu_ti_le": (lambda img: resize_nonuniform(img, s), True),
        "occlusion": (lambda img: occlusion(img, s, seed), False),
        "xoay": (lambda img: rotate(img, s, restore_size=True), True),
        "cat_va_resize": (lambda img: crop_resize(img, s), True),
        "cat_khong_resize": (lambda img: crop_no_resize(img, s), True),
        "dich_pixel": (lambda img: shift(img, s), True),
        "ket_hop_xoay_cat_jpeg": (
            lambda img: jpeg_compress(crop_resize(rotate(img, 1, restore_size=True), 1), 70),
            True,
        ),
    })
    return battery
