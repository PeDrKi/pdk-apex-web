"""Backend nén BC7 THẬT qua AMD CompressonatorCLI (TUỲ CHỌN).

Thư viện apexmark KHÔNG bắt buộc phải có CompressonatorCLI: nếu không có,
bạn vẫn nhúng/trích xuất được bình thường, chỉ mất thành phần "BC7-aware"
khi chọn khối (xem `bc7_aware` trong apexmark.embed).

CÀI ĐẶT (nếu muốn dùng BC7-aware):
1. Tải Compressonator (AMD GPUOpen): https://gpuopen.com/compressonator/
   — bản portable CLI, giải nén là chạy được, không cần cài đặt.
2. Trỏ đường dẫn qua biến môi trường COMPRESSONATOR_PATH:
       Windows : set COMPRESSONATOR_PATH=C:\\path\\to\\compressonatorcli.exe
       Linux   : export COMPRESSONATOR_PATH=/path/to/compressonatorcli
   Hoặc truyền trực tiếp: `make_bc7_fn(exe_path="...")`.

Lệnh sử dụng (giữ nguyên như bản nghiên cứu gốc, để kết quả tái lập được):
    <exe> -fd BC7 -EncodeWith HPC <input.png> <output.dds>   # encode
    <exe> <input.dds> <output.png>                            # decode
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image


class CompressonatorNotFound(RuntimeError):
    """Không tìm thấy CompressonatorCLI — xem hướng dẫn cài ở đầu module này."""


def find_compressonator(exe_path: Optional[str] = None) -> str:
    """Tìm CompressonatorCLI theo thứ tự: tham số truyền vào -> biến môi
    trường COMPRESSONATOR_PATH -> PATH hệ thống. Raise CompressonatorNotFound
    nếu không thấy."""
    candidates = []
    if exe_path:
        candidates.append(exe_path)
    env = os.environ.get("COMPRESSONATOR_PATH")
    if env:
        candidates.append(env)
    for name in ("compressonatorcli", "compressonatorcli.exe", "CompressonatorCLI.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    for c in candidates:
        if c and Path(c).is_file():
            return c

    raise CompressonatorNotFound(
        "Không tìm thấy CompressonatorCLI. Đặt biến môi trường "
        "COMPRESSONATOR_PATH trỏ tới file thực thi, hoặc truyền exe_path=..., "
        "hoặc dùng bc7_aware=False để bỏ qua thành phần BC7-aware. "
        "Tải tại: https://gpuopen.com/compressonator/"
    )


def inproc_available() -> bool:
    """True nếu bộ mã hoá BC7 chạy trong tiến trình (ispc-texcomp + texture2ddecoder) dùng được.
    Đây là bộ mã hoá BC7 thật (Intel ISPC Texture Compressor), cài bằng pip, không cần file ngoài."""
    try:
        import ispc_texcomp  # noqa: F401
        import texture2ddecoder  # noqa: F401
        return True
    except Exception:
        return False


def is_available(exe_path: Optional[str] = None) -> bool:
    """True nếu có BC7 thật: CompressonatorCLI hoặc bộ mã hoá trong tiến trình."""
    try:
        find_compressonator(exe_path)
        return True
    except CompressonatorNotFound:
        return inproc_available()


def make_inproc_bc7_fn(profile: str = "basic", use_cache: bool = True) -> Callable[[np.ndarray], np.ndarray]:
    """Hàm `f(img) -> img_sau_BC7` dùng ispc-texcomp (mã hoá BC7 thật) + texture2ddecoder (giải mã).
    Cùng giao diện với make_bc7_fn. Ảnh không chia hết cho 4 được đệm mép rồi cắt lại."""
    import ispc_texcomp as I
    import texture2ddecoder as T
    settings = I.BC7EncSettings.from_profile(profile)
    cache: dict = {}

    def _bc7(img: np.ndarray) -> np.ndarray:
        arr = np.clip(img, 0, 255).astype(np.uint8)
        is_gray = arr.ndim == 2
        if use_cache:
            h = hashlib.blake2b(arr.tobytes(), digest_size=16)
            h.update(str(arr.shape).encode())
            h.update(profile.encode())
            key = h.hexdigest()
            if key in cache:
                return cache[key].copy()
        H, W = arr.shape[:2]
        rgb = np.stack([arr] * 3, axis=-1) if is_gray else arr[:, :, :3]
        ph, pw = (-H) % 4, (-W) % 4
        if ph or pw:
            rgb = np.pad(rgb, ((0, ph), (0, pw), (0, 0)), mode="edge")
        hh, ww = rgb.shape[:2]
        rgba = np.ascontiguousarray(np.dstack([rgb, np.full((hh, ww), 255, np.uint8)]))
        blocks = I.compress_blocks_bc7(I.RGBASurface(rgba, ww, hh), settings)
        raw = T.decode_bc7(bytes(blocks), ww, hh)  # BGRA
        dec = np.frombuffer(raw, np.uint8).reshape(hh, ww, 4)[:, :, [2, 1, 0]]
        out = dec[:H, :W].astype(np.float64)
        if is_gray:
            out = out.mean(axis=2)
        if use_cache:
            if len(cache) > 50:
                cache.pop(next(iter(cache)))
            cache[key] = out.copy()
        return out

    return _bc7


def make_best_bc7_fn(exe_path: Optional[str] = None, **kw) -> Callable[[np.ndarray], np.ndarray]:
    """CompressonatorCLI nếu tìm thấy (giữ đúng bản nghiên cứu), ngược lại bộ mã hoá trong tiến trình."""
    try:
        find_compressonator(exe_path)
        return make_bc7_fn(exe_path, **kw)
    except CompressonatorNotFound:
        if inproc_available():
            return make_inproc_bc7_fn()
        raise


def make_bc7_fn(exe_path: Optional[str] = None, timeout: float = 60.0,
                 use_cache: bool = True, encode_with: str = "HPC") -> Callable[[np.ndarray], np.ndarray]:
    """Trả về hàm `f(img) -> img_sau_BC7` dùng CompressonatorCLI thật.

    Hàm trả về nhận mảng 2D (grayscale) hoặc 3D (RGB) dtype bất kỳ, trả về
    mảng cùng shape, dtype float64. Có cache theo nội dung ảnh trong tiến
    trình để tránh gọi lại CLI cho cùng một ảnh.

    encode_with : bộ mã hoá BC7 của CompressonatorCLI (`-EncodeWith`).
            Mặc định "HPC" — GIỮ NGUYÊN như bản nghiên cứu gốc để kết quả
            tái lập được, ĐỪNG đổi giá trị này trừ khi bạn chủ động muốn so
            sánh nhiều bộ mã hoá (xem `apexmark.attacks.bc7_compress`). Các
            giá trị khác CompressonatorCLI hỗ trợ tuỳ phiên bản (thường có
            "CPU", "GPU" — chạy `<exe> -help` trên máy bạn để xem đầy đủ).
    """
    exe = find_compressonator(exe_path)
    cache: dict = {}

    def _bc7(img: np.ndarray) -> np.ndarray:
        arr = np.clip(img, 0, 255).astype(np.uint8)
        is_gray = arr.ndim == 2

        if use_cache:
            h = hashlib.blake2b(arr.tobytes(), digest_size=16)
            h.update(str(arr.shape).encode())
            h.update(encode_with.encode())
            key = h.hexdigest()
            if key in cache:
                return cache[key].copy()

        H, W = arr.shape[:2]
        rgb = np.stack([arr] * 3, axis=-1) if is_gray else arr[:, :, :3]

        tmp_dir = Path(tempfile.gettempdir()) / f"apexmark_bc7_{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        src, dds, dec = tmp_dir / "s.png", tmp_dir / "o.dds", tmp_dir / "d.png"
        try:
            Image.fromarray(rgb).save(src)
            r1 = subprocess.run([exe, "-fd", "BC7", "-EncodeWith", encode_with, str(src), str(dds)],
                                 capture_output=True, text=True, timeout=timeout)
            if r1.returncode != 0 or not dds.exists():
                raise RuntimeError(f"CompressonatorCLI encode lỗi ({r1.returncode}): "
                                    f"{r1.stdout}\n{r1.stderr}")
            r2 = subprocess.run([exe, str(dds), str(dec)],
                                 capture_output=True, text=True, timeout=timeout)
            if r2.returncode != 0 or not dec.exists():
                raise RuntimeError(f"CompressonatorCLI decode lỗi ({r2.returncode}): "
                                    f"{r2.stdout}\n{r2.stderr}")
            out = np.array(Image.open(dec).convert("RGB"), dtype=np.float64)
        finally:
            for f in (src, dds, dec):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                tmp_dir.rmdir()
            except OSError:
                pass

        out = out[:H, :W]
        if is_gray:
            out = out.mean(axis=2)

        if use_cache:
            if len(cache) > 5000:
                cache.pop(next(iter(cache)))
            cache[key] = out.copy()
        return out

    return _bc7
