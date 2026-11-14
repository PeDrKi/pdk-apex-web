"""apexmark — nhúng watermark bền vững với nén BC7 (ACO + Adaptive Block-Mean QIM).

Tách ra từ dự án nghiên cứu APEX để dùng độc lập. Hỗ trợ ảnh grayscale và
RGB, kích thước bất kỳ. Thành phần "BC7-aware" (ưu tiên khối bền dưới nén
BC7) là TUỲ CHỌN — cần AMD CompressonatorCLI; không có vẫn chạy bình thường.

    import apexmark
    stego, keys = apexmark.embed(img, bits)
    recovered = apexmark.extract(stego, keys)
"""
from .core import capacity, embed, extract, load_keys, save_keys

__version__ = "1.0.0"
__all__ = ["embed", "extract", "capacity", "save_keys", "load_keys", "__version__",
           "resync", "extract_robust", "attacks", "evaluate", "bc7"]


def __getattr__(name):
    # Lazy import: apexmark.sync cần cv2 (tuỳ chọn) chỉ khi thực sự gọi
    # resync()/extract_robust(), không bắt buộc phải cài để dùng embed/extract.
    if name in ("resync", "extract_robust"):
        from . import sync as _sync
        return getattr(_sync, name)
    if name in ("attacks", "evaluate", "bc7"):
        import importlib
        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
