"""Danh mục phép tấn công cho tab "Thử tấn công" — bọc `apexmark.attacks`.

Mỗi phép có mức 1-3 (nhẹ/vừa/nặng); riêng JPEG dùng chất lượng 10-95.
`geometric=True` = phép làm lệch lưới điểm ảnh, cần căn chỉnh (resync) khi đọc.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from PIL import Image

from apexmark import attacks as A

MAX_CHAIN = 1
ROTATE_DEG = {1: 2.0, 2: 8.0, 3: 20.0}


@dataclass(frozen=True)
class Attack:
    id: str
    name: str
    group: str
    param: str            # "level" | "quality" | "none"
    geometric: bool
    fn: Callable[[np.ndarray, int], np.ndarray]
    hint: str = ""


CATALOG: list[Attack] = [
    Attack("jpeg", "Nén JPEG", "Nén", "quality", False, lambda im, v: A.jpeg_compress(im, v),
           "Chất lượng càng thấp càng khắc nghiệt"),
    Attack("bc7", "Nén BC7 thật", "Nén", "none", False, lambda im, v: A.bc7_compress(im),
           "Nén texture BC7 (GPU) rồi giải nén"),
    Attack("gaussian_noise", "Nhiễu Gauss", "Nhiễu", "level", False, lambda im, v: A.gaussian_noise(im, v)),
    Attack("salt_pepper", "Nhiễu muối tiêu", "Nhiễu", "level", False, lambda im, v: A.salt_pepper(im, v)),
    Attack("median_blur", "Làm mờ median", "Lọc", "level", False, lambda im, v: A.median_blur(im, v)),
    Attack("gaussian_blur", "Làm mờ Gauss", "Lọc", "level", False, lambda im, v: A.gaussian_blur(im, v)),
    Attack("sharpen", "Làm nét", "Lọc", "level", False, lambda im, v: A.sharpen(im, v)),
    Attack("brightness_up", "Tăng sáng", "Màu sắc", "level", False, lambda im, v: A.brightness(im, v)),
    Attack("brightness_down", "Giảm sáng", "Màu sắc", "level", False,
           lambda im, v: A.brightness(im, v, darken=True)),
    Attack("contrast", "Giảm tương phản", "Màu sắc", "level", False, lambda im, v: A.contrast(im, v)),
    Attack("gamma_up", "Gamma sáng", "Màu sắc", "level", False, lambda im, v: A.gamma(im, v)),
    Attack("gamma_down", "Gamma tối", "Màu sắc", "level", False, lambda im, v: A.gamma(im, v, darken=True)),
    Attack("hist_equalize", "Cân bằng histogram", "Màu sắc", "none", False, lambda im, v: A.hist_equalize(im)),
    Attack("resize", "Thu nhỏ rồi phóng lại", "Hình học", "level", False, lambda im, v: A.resize(im, v)),
    Attack("resize_nonuniform", "Bóp méo tỉ lệ", "Hình học", "level", True,
           lambda im, v: A.resize_nonuniform(im, v)),
    Attack("occlusion", "Che một vùng", "Hình học", "level", False, lambda im, v: A.occlusion(im, v)),
    Attack("rotate", "Xoay", "Hình học", "level", True, lambda im, v: A.rotate(im, v),
           "2°, 8° hoặc 20°"),
    Attack("crop_resize", "Cắt mép rồi phóng lại", "Hình học", "level", True, lambda im, v: A.crop_resize(im, v)),
    Attack("crop", "Cắt mép", "Hình học", "level", True, lambda im, v: A.crop_no_resize(im, v)),
    Attack("shift", "Dịch điểm ảnh", "Hình học", "level", True, lambda im, v: A.shift(im, v)),
]
MAX_SIDE = 4000
MAX_PIXELS_OUT = 4_200_000


def _crop_custom(im: np.ndarray, p: dict) -> np.ndarray:
    h, w = im.shape[:2]
    x0, y0 = int(round(p["x"] * w)), int(round(p["y"] * h))
    x1, y1 = int(round((p["x"] + p["w"]) * w)), int(round((p["y"] + p["h"]) * h))
    x0, y0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
    x1, y1 = max(x0 + 1, min(x1, w)), max(y0 + 1, min(y1, h))
    return im[y0:y1, x0:x1].astype(np.float64)


def _erase_custom(im: np.ndarray, p: dict) -> np.ndarray:
    """Xoá (tô trắng) vùng đã chọn, ảnh giữ nguyên kích thước và lưới điểm ảnh."""
    h, w = im.shape[:2]
    x0, y0 = int(round(p["x"] * w)), int(round(p["y"] * h))
    x1, y1 = int(round((p["x"] + p["w"]) * w)), int(round((p["y"] + p["h"]) * h))
    out = im.astype(np.float64).copy()
    out[y0:y1, x0:x1] = 255
    return out


def _resize_custom(im: np.ndarray, p: dict) -> np.ndarray:
    img = Image.fromarray(np.clip(im, 0, 255).astype(np.uint8))
    return np.asarray(img.resize((int(p["w"]), int(p["h"])), Image.BILINEAR), dtype=np.float64)


# Phép chỉnh tay (người dùng tự kéo vùng cắt / nhập kích thước). Không nằm trong CATALOG
# (không tính vào 20 phép và bảng quét), nhưng dùng được trong chuỗi tấn công.
CUSTOM: dict[str, Attack] = {
    "crop_custom": Attack("crop_custom", "Cắt vùng tự chọn", "Chỉnh tay", "region", True,
                          lambda im, v: im, "Kéo chọn vùng trên ảnh"),
    "erase_custom": Attack("erase_custom", "Xoá vùng tự chọn", "Chỉnh tay", "region", False,
                           lambda im, v: im, "Kéo chọn vùng để xoá (tô trắng)"),
    "resize_custom": Attack("resize_custom", "Đổi kích thước tự chọn", "Chỉnh tay", "size", True,
                            lambda im, v: im, "Nhập chiều rộng và chiều cao"),
}
_CUSTOM_FN = {"crop_custom": _crop_custom, "erase_custom": _erase_custom, "resize_custom": _resize_custom}
BY_ID = {a.id: a for a in CATALOG}
BY_ID.update(CUSTOM)


class AttackError(ValueError):
    pass


@dataclass
class Step:
    attack: Attack
    value: int
    params: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.attack.id == "crop_custom":
            p = self.params
            return f"Cắt vùng {p['w'] * 100:.0f}%×{p['h'] * 100:.0f}% từ ({p['x'] * 100:.0f}%, {p['y'] * 100:.0f}%)"
        if self.attack.id == "erase_custom":
            p = self.params
            return f"Xoá vùng {p['w'] * 100:.0f}%×{p['h'] * 100:.0f}% tại ({p['x'] * 100:.0f}%, {p['y'] * 100:.0f}%)"
        if self.attack.id == "resize_custom":
            return f"Đổi kích thước {int(self.params['w'])}×{int(self.params['h'])}"
        if self.attack.param == "quality":
            return f"{self.attack.name} (Q{self.value})"
        if self.attack.param == "level":
            return f"{self.attack.name} (mức {self.value})"
        return self.attack.name


def _num(v, lo, hi) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise AttackError("Thông số chỉnh tay không hợp lệ.")
    return float(v)


def _parse_custom(aid: str, raw) -> dict:
    if not isinstance(raw, dict):
        raise AttackError("Thiếu thông số cho phép chỉnh tay.")
    if aid in ("crop_custom", "erase_custom"):
        p = {k: _num(raw.get(k), 0.0, 1.0) for k in ("x", "y", "w", "h")}
        if p["w"] < 0.02 or p["h"] < 0.02 or p["x"] + p["w"] > 1.0001 or p["y"] + p["h"] > 1.0001:
            raise AttackError("Vùng cắt không hợp lệ.")
        return p
    return {k: float(int(_num(raw.get(k), 8, MAX_SIDE))) for k in ("w", "h")}


def parse_steps(raw: str) -> list[Step]:
    """raw: JSON `[{"id": "jpeg", "value": 50}, ...]` do người dùng gửi lên."""
    try:
        items = json.loads(raw)
    except (ValueError, RecursionError):
        raise AttackError("Danh sách phép tấn công không hợp lệ.")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_CHAIN:
        raise AttackError("Hãy chọn đúng 1 phép tấn công.")
    steps = []
    for it in items:
        if not isinstance(it, dict) or it.get("id") not in BY_ID:
            raise AttackError("Phép tấn công không tồn tại.")
        atk = BY_ID[it["id"]]
        if atk.id in _CUSTOM_FN:
            steps.append(Step(atk, 0, _parse_custom(atk.id, it.get("params"))))
            continue
        v = it.get("value", 2)
        if isinstance(v, bool) or not isinstance(v, int):
            raise AttackError("Mức độ tấn công không hợp lệ.")
        if atk.param == "quality" and not 5 <= v <= 95:
            raise AttackError("Chất lượng JPEG phải nằm trong 5..95.")
        if atk.param == "level" and v not in (1, 2, 3):
            raise AttackError("Mức độ phải là 1, 2 hoặc 3.")
        steps.append(Step(atk, v))
    return steps


def apply_steps(image: np.ndarray, steps: list[Step]) -> np.ndarray:
    out = image[..., :3] if image.ndim == 3 and image.shape[2] == 4 else image
    out = out.astype(np.float64)
    for s in steps:
        if s.attack.id in _CUSTOM_FN:
            out = _CUSTOM_FN[s.attack.id](out, s.params)
        else:
            out = np.asarray(s.attack.fn(out, s.value), dtype=np.float64)
        if out.ndim >= 2 and out.shape[0] * out.shape[1] > MAX_PIXELS_OUT:
            raise AttackError("Ảnh sau khi chỉnh quá lớn (tối đa khoảng 4 triệu điểm ảnh).")
        if out.ndim < 2 or min(out.shape[:2]) < 8:
            raise AttackError("Ảnh quá nhỏ sau khi tấn công.")
    return np.clip(out, 0, 255).astype(np.uint8)


def rotate_range_for(steps: list[Step]) -> float:
    """Biên độ dò góc xoay cần thiết để đọc lại ảnh sau chuỗi tấn công này."""
    degs = [ROTATE_DEG[s.value] for s in steps if s.attack.id == "rotate"]
    return min(25.0, sum(degs) + 2.0) if degs else 0.0
