"""Danh mục phép tấn công cho tab "Thử tấn công" — bọc `apexmark.attacks`.

Mỗi phép có mức 1-3 (nhẹ/vừa/nặng); riêng JPEG dùng chất lượng 10-95.
`geometric=True` = phép làm lệch lưới điểm ảnh, cần căn chỉnh (resync) khi đọc.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import numpy as np

from apexmark import attacks as A

MAX_CHAIN = 6
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
BY_ID = {a.id: a for a in CATALOG}


class AttackError(ValueError):
    pass


@dataclass
class Step:
    attack: Attack
    value: int

    @property
    def label(self) -> str:
        if self.attack.param == "quality":
            return f"{self.attack.name} (Q{self.value})"
        if self.attack.param == "level":
            return f"{self.attack.name} (mức {self.value})"
        return self.attack.name


def parse_steps(raw: str) -> list[Step]:
    """raw: JSON `[{"id": "jpeg", "value": 50}, ...]` do người dùng gửi lên."""
    try:
        items = json.loads(raw)
    except (ValueError, RecursionError):
        raise AttackError("Danh sách phép tấn công không hợp lệ.")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_CHAIN:
        raise AttackError(f"Hãy chọn từ 1 đến {MAX_CHAIN} phép tấn công.")
    steps = []
    for it in items:
        if not isinstance(it, dict) or it.get("id") not in BY_ID:
            raise AttackError("Phép tấn công không tồn tại.")
        atk = BY_ID[it["id"]]
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
        out = np.asarray(s.attack.fn(out, s.value), dtype=np.float64)
        if out.ndim < 2 or min(out.shape[:2]) < 8:
            raise AttackError("Ảnh quá nhỏ sau khi tấn công.")
    return np.clip(out, 0, 255).astype(np.uint8)


def rotate_range_for(steps: list[Step]) -> float:
    """Biên độ dò góc xoay cần thiết để đọc lại ảnh sau chuỗi tấn công này."""
    degs = [ROTATE_DEG[s.value] for s in steps if s.attack.id == "rotate"]
    return min(25.0, sum(degs) + 2.0) if degs else 0.0
