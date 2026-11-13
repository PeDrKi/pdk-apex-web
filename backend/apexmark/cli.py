"""Giao diện dòng lệnh cho apexmark.

    # Nhúng một chuỗi text vào ảnh
    python -m apexmark embed anh.png -o stego.png -k keys.npz --text "ban quyen 2026"

    # Nhúng watermark ngẫu nhiên 256 bit (tái lập được qua --seed)
    python -m apexmark embed anh.png -o stego.png -k keys.npz --random-bits 256

    # Nhúng bền vững hơn: dự phòng x10 + lưu kèm ảnh thu nhỏ để phục hồi hình học
    python -m apexmark embed anh.png -o stego.png -k keys.npz --text "..." \\
        --redundancy 10 --delta 24 --store-thumbnail

    # Trích xuất
    python -m apexmark extract stego.png -k keys.npz

    # Trích xuất bền vững (ảnh có thể đã bị cắt/dịch/xoay nhẹ)
    python -m apexmark extract stego.png -k keys.npz --resync --rotate-range 15

    # Xem ảnh nhúng được tối đa bao nhiêu bit
    python -m apexmark capacity anh.png
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
from PIL import Image

from . import capacity as _capacity
from . import embed as _embed
from . import extract as _extract
from . import load_keys, save_keys


def _read_image(path: str) -> np.ndarray:
    img = Image.open(path)
    if img.mode not in ("L", "RGB", "RGBA"):
        img = img.convert("RGB")
    return np.array(img)


def _save_image(arr: np.ndarray, path: str) -> None:
    out = np.clip(arr, 0, 255).astype(np.uint8)
    if path.lower().endswith((".jpg", ".jpeg")):
        print("CẢNH BÁO: lưu sang JPEG (nén có mất mát) có thể làm hỏng watermark. "
              "Nên dùng .png để giữ nguyên ảnh đã nhúng.", file=sys.stderr)
    Image.fromarray(out).save(path)


def _text_to_bits(text: str) -> np.ndarray:
    data = text.encode("utf-8")
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def _bits_to_text(bits: np.ndarray) -> str:
    n = (bits.size // 8) * 8
    data = np.packbits(bits[:n].astype(np.uint8)).tobytes()
    return data.decode("utf-8", errors="replace")


def cmd_embed(args) -> int:
    img = _read_image(args.image)

    if args.text is not None:
        bits = _text_to_bits(args.text)
    elif args.random_bits is not None:
        bits = np.random.default_rng(args.seed).integers(0, 2, args.random_bits).astype(np.uint8)
    else:
        print("LỖI: cần --text hoặc --random-bits", file=sys.stderr)
        return 1

    cap = _capacity(img)
    budget = cap // args.redundancy
    if bits.size > budget:
        print(f"LỖI: watermark {bits.size} bit x redundancy {args.redundancy} vượt dung "
              f"lượng ảnh ({cap} khối -> {budget} bit khả dụng ở redundancy này).",
              file=sys.stderr)
        return 1

    bc7_aware = None if args.bc7 == "auto" else (args.bc7 == "on")
    stego, keys = _embed(img, bits, bc7_aware=bc7_aware,
                          compressonator_path=args.compressonator,
                          use_aco=not args.no_aco, use_ngdc=not args.no_ngdc,
                          delta_base=args.delta, redundancy=args.redundancy,
                          store_thumbnail=args.store_thumbnail,
                          thumbnail_max_side=args.thumbnail_max_side,
                          seed=args.seed, verbose=True)

    _save_image(stego, args.output)
    save_keys(keys, args.keys)
    print(f"✓ Đã nhúng {bits.size} bit vào {args.output}"
          + (f" (redundancy={args.redundancy})" if args.redundancy > 1 else ""))
    print(f"✓ Khoá lưu tại {args.keys} — CẦN file này để trích xuất, giữ cẩn thận.")
    if args.store_thumbnail:
        print("✓ Đã lưu kèm ảnh thu nhỏ trong keys -- dùng `extract --resync` nếu ảnh "
              "sau này bị cắt/dịch/xoay.")
    return 0


def cmd_extract(args) -> int:
    img = _read_image(args.image)
    keys = load_keys(args.keys)

    if args.resync:
        from . import sync as _sync
        if "thumbnail" not in keys:
            print("CẢNH BÁO: keys không có ảnh thu nhỏ (nhúng lúc trước không dùng "
                  "--store-thumbnail) -- --resync không có tác dụng, trích xuất như bình "
                  "thường.", file=sys.stderr)
        try:
            resync_kwargs = {}
            if args.rotate_range:
                resync_kwargs["angle_range"] = (-args.rotate_range, args.rotate_range)
                resync_kwargs["angle_step"] = 1.0
            bits = _sync.extract_robust(img, keys, aggregate=args.aggregate,
                                         resync_kwargs=resync_kwargs, verbose=args.verbose_sync)
        except _sync.SyncUnavailable as e:
            print(f"LỖI: {e}", file=sys.stderr)
            return 1
    else:
        bits = _extract(img, keys, aggregate=args.aggregate)

    if args.as_text:
        print(_bits_to_text(bits))
    else:
        print("".join(str(int(b)) for b in bits))
    return 0


def cmd_capacity(args) -> int:
    img = _read_image(args.image)
    cap = _capacity(img)
    if args.redundancy > 1:
        budget = cap // args.redundancy
        print(f"{cap} khối 4x4 -> {budget} bit khả dụng ở redundancy={args.redundancy} "
              f"({budget // 8} byte)")
    else:
        print(f"{cap} bit ({cap // 8} byte, tương đương ~{cap // 8} ký tự ASCII)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="apexmark", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("embed", help="Nhúng watermark vào ảnh")
    pe.add_argument("image")
    pe.add_argument("-o", "--output", required=True, help="Ảnh đầu ra (nên dùng .png)")
    pe.add_argument("-k", "--keys", required=True, help="File .npz lưu khoá")
    pe.add_argument("--text", help="Chuỗi text làm watermark")
    pe.add_argument("--random-bits", type=int, help="Nhúng N bit ngẫu nhiên")
    pe.add_argument("--bc7", choices=["auto", "on", "off"], default="auto",
                     help="Dùng BC7-aware heuristic (auto=bật nếu có CompressonatorCLI)")
    pe.add_argument("--compressonator", help="Đường dẫn CompressonatorCLI")
    pe.add_argument("--delta", type=float, default=12.0, help="Bước lượng tử cơ sở "
                     "(tăng lên 24-32 nếu ảnh nhiều chi tiết mịn/cần chống salt&pepper mạnh)")
    pe.add_argument("--redundancy", type=int, default=1,
                     help="Số khối dự phòng/bit (mặc định 1 = không đổi hành vi cũ). "
                          "Tăng lên (vd 5-20) để chống nhiễu cục bộ/che khuất/blur -- "
                          "đánh đổi dung lượng và PSNR, xem README mục redundancy")
    pe.add_argument("--store-thumbnail", action="store_true",
                     help="Lưu kèm ảnh thu nhỏ trong keys để dùng `extract --resync` sau "
                          "này phục hồi ảnh bị cắt/dịch/xoay (không cần cv2 lúc nhúng)")
    pe.add_argument("--thumbnail-max-side", type=int, default=256,
                     help="Cạnh dài tối đa (px) của ảnh thu nhỏ nói trên")
    pe.add_argument("--no-aco", action="store_true", help="Dùng greedy thay vì ACO (nhanh hơn)")
    pe.add_argument("--no-ngdc", action="store_true", help="Tắt hiệu chỉnh N-GDC")
    pe.add_argument("--seed", type=int, default=0)
    pe.set_defaults(func=cmd_embed)

    px = sub.add_parser("extract", help="Trích watermark từ ảnh")
    px.add_argument("image")
    px.add_argument("-k", "--keys", required=True)
    px.add_argument("--as-text", action="store_true", help="Giải mã bit thành text UTF-8")
    px.add_argument("--aggregate", choices=["mean", "kmeans"], default="mean",
                     help="Cách gộp phiếu bầu khi keys có redundancy>1 (chỉ có tác dụng "
                          "khi nhúng với --redundancy)")
    px.add_argument("--resync", action="store_true",
                     help="Thử dựng lại ảnh gốc (cắt/dịch/xoay) trước khi trích -- cần "
                          "cv2 (pip install opencv-python-headless) và keys có "
                          "--store-thumbnail lúc nhúng")
    px.add_argument("--rotate-range", type=float, default=0.0,
                     help="Bật dò góc xoay ±N độ khi --resync (mặc định 0 = không dò, "
                          "chỉ xử lý cắt/dịch/co giãn cho nhanh)")
    px.add_argument("--verbose-sync", action="store_true",
                     help="In chi tiết quá trình resync (điểm khớp từng góc...)")
    px.set_defaults(func=cmd_extract)

    pc = sub.add_parser("capacity", help="Xem dung lượng nhúng của ảnh")
    pc.add_argument("image")
    pc.add_argument("--redundancy", type=int, default=1,
                     help="Xem dung lượng khả dụng SAU KHI chia cho redundancy này")
    pc.set_defaults(func=cmd_capacity)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
