"""PDK APEX Web — API giấu tin trong ảnh dựa trên apexmark.

Chạy dev:   uvicorn app.main:app --reload --port 8000   (trong thư mục backend/)
Tài liệu API tự sinh: http://localhost:8000/api/docs
"""
from __future__ import annotations

import logging
import base64
import io
import math
import time
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import anyio
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import apexmark

from . import align
from . import detect
from . import attacks as atk
from . import compare as cmp
from . import logo as logo_mod
from . import payload
from .config import settings
from .imaging import ImageError, psnr, read_image, to_png_bytes
from . import accounts
from .security import KeysError, SecurityMiddleware, parse_keys

# Log của ứng dụng (nhật ký bảo mật, lỗi kho lưu trữ) ra stdout để xem được trên Render.
_apex_log = logging.getLogger("apex")
if not _apex_log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s: [%(name)s] %(message)s"))
    _apex_log.addHandler(_h)
    _apex_log.setLevel(logging.INFO)
    _apex_log.propagate = False

app = FastAPI(
    title="PDK APEX Web API",
    version="1.0.0",
    description="Giấu thông điệp vào ảnh bằng apexmark (ACO + Adaptive Block-Mean QIM + N-GDC).",
    docs_url="/api/docs" if settings.enable_docs else None,
    openapi_url="/api/openapi.json" if settings.enable_docs else None,
    redoc_url=None,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )


# Nén gzip mức 1: rất nhanh, và lấy lại gần hết 33% phình ra do base64 trong JSON.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=1)
app.add_middleware(SecurityMiddleware)  # thêm sau cùng = lớp ngoài cùng


# ---------------------------------------------------------------- helpers

_limiter: Optional[anyio.CapacityLimiter] = None


async def _heavy(fn):
    """Chạy việc nặng (giải mã ảnh, nhúng, trích xuất) ở luồng phụ để vòng lặp sự kiện
    vẫn phục vụ được người khác. Số việc chạy cùng lúc bị giới hạn để không tràn RAM/CPU;
    yêu cầu dư ra sẽ xếp hàng chờ."""
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(settings.max_heavy_jobs)
    return await anyio.to_thread.run_sync(fn, limiter=_limiter)


async def _read_upload(f: UploadFile, what: str) -> bytes:
    data = await f.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"{what} vượt quá {settings.max_upload_mb} MB.")
    if not data:
        raise HTTPException(400, f"{what} trống.")
    return data


def _load_image(data: bytes) -> np.ndarray:
    try:
        return read_image(data)
    except ImageError as e:
        raise HTTPException(400, str(e))


def _check_redundancy(r: int) -> None:
    if not 1 <= r <= settings.max_redundancy:
        raise HTTPException(400, f"Độ dự phòng phải nằm trong 1..{settings.max_redundancy}.")


def _smallest_uint(a: np.ndarray) -> np.ndarray:
    if a.dtype.kind not in "iu" or a.size == 0 or int(a.min()) < 0:
        return a
    for t in (np.uint8, np.uint16, np.uint32):
        if int(a.max()) <= np.iinfo(t).max:
            return a.astype(t)
    return a


def _keys_to_bytes(keys: dict) -> bytes:
    """Lưu khoá gọn nhất có thể: mảng chỉ số dùng kiểu số nguyên nhỏ nhất vừa đủ,
    delta dùng float32 (sai số ~1e-7, không ảnh hưởng quyết định QIM)."""
    out = {}
    for name, v in keys.items():
        a = np.asarray(v)
        if name == "deltas":
            a = a.astype(np.float32)
        elif a.ndim >= 1:
            a = _smallest_uint(a)
        out[name] = a
    buf = io.BytesIO()
    np.savez_compressed(buf, **out)
    return buf.getvalue()


def _keys_from_bytes(data: bytes) -> dict:
    try:
        return parse_keys(data)
    except KeysError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "File khoá không hợp lệ (cần file .npz tạo lúc giấu tin).")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ---------------------------------------------------------------- schemas

class Health(BaseModel):
    status: str
    apexmark_version: str
    sync_available: bool
    bc7_available: bool
    max_upload_mb: int
    max_redundancy: int
    detect_enabled: bool = False


class CapacityOut(BaseModel):
    width: int
    height: int
    capacity_bits: int
    redundancy: int
    usable_bits: int
    max_message_bytes: int
    max_message_bytes_encrypted: int


class EmbedOut(BaseModel):
    stego_png_base64: str
    keys_npz_base64: str
    width: int
    height: int
    n_bits: int
    capacity_bits: int
    usage_ratio: float
    psnr_db: Optional[float]
    encrypted: bool
    redundancy: int
    elapsed_ms: int
    kind: Literal["text", "logo", "file"]
    logo_preview_base64: Optional[str] = None
    logo_width: Optional[int] = None
    logo_height: Optional[int] = None
    saved_id: Optional[str] = None
    save_error: Optional[str] = None
    # Ước lượng khả năng bị phát hiện bởi người biết thuật toán (xem app/detect.py).
    detect_level: Optional[Literal["low", "medium", "high"]] = None
    detect_score: Optional[float] = None
    detect_baseline: Optional[float] = None
    detect_noise: Optional[float] = None


class ExtractOut(BaseModel):
    kind: Literal["text", "logo", "file"]
    message: str
    file_base64: Optional[str] = None
    file_name: Optional[str] = None
    # Chế độ raw: trả dữ liệu thô để trình duyệt tự giải mã (mật khẩu không gửi lên máy chủ).
    payload_base64: Optional[str] = None
    payload_format: Optional[str] = None
    logo_header: Optional[list[int]] = None
    logo_png_base64: Optional[str] = None
    logo_width: Optional[int] = None
    logo_height: Optional[int] = None
    integrity_ok: Optional[bool]
    encrypted: bool
    used_resync: bool
    n_bits: int
    elapsed_ms: int


# ---------------------------------------------------------------- routes

@app.get("/api/health", response_model=Health)
def health(db_check: bool = False):
    """db_check=true: chạm vào cơ sở dữ liệu (dùng cho lịch ping giữ Supabase không bị tạm dừng)."""
    from apexmark import bc7, sync
    if db_check:
        from . import db
        try:
            with db.connect() as con:
                con.execute("SELECT 1").fetchone()
        except Exception:
            raise HTTPException(503, "Không kết nối được cơ sở dữ liệu.")
    return Health(
        status="ok",
        apexmark_version=apexmark.__version__,
        sync_available=sync.is_available(),
        bc7_available=bc7.is_available(None),
        max_upload_mb=settings.max_upload_mb,
        max_redundancy=settings.max_redundancy,
        detect_enabled=settings.show_detect,
    )


@app.post("/api/capacity", response_model=CapacityOut)
async def capacity(image: UploadFile = File(...), redundancy: int = Form(1)):
    _check_redundancy(redundancy)
    img_bytes = await _read_upload(image, "Ảnh")

    def work():
        img = _load_image(img_bytes)
        cap = apexmark.capacity(img)
        usable = cap // redundancy
        return CapacityOut(
            width=img.shape[1], height=img.shape[0], capacity_bits=cap,
            redundancy=redundancy, usable_bits=usable,
            max_message_bytes=max(0, usable // 8 - payload.overhead_bytes(False)),
            max_message_bytes_encrypted=max(0, usable // 8 - payload.overhead_bytes(True)),
        )

    return await _heavy(work)


def _parse_logo_header(raw: str) -> tuple[int, int, int]:
    try:
        mode, h, w = (int(x) for x in raw.split(","))
    except ValueError:
        raise HTTPException(400, "Thông tin logo không hợp lệ.")
    if mode not in (0, 1) or not (0 < h <= logo_mod.MAX_SIDE and 0 < w <= logo_mod.MAX_SIDE):
        raise HTTPException(400, "Thông tin logo không hợp lệ.")
    return mode, h, w


@app.post("/api/embed", response_model=EmbedOut)
async def embed(
    image: UploadFile = File(...),
    kind: Literal["text", "logo", "file"] = Form("text"),
    message: str = Form(""),
    logo: Optional[UploadFile] = File(None),
    logo_mode: Literal["binary", "gray"] = Form("binary"),
    logo_invert: Literal["auto", "yes", "no"] = Form("auto"),
    logo_max_side: int = Form(0),
    file: Optional[UploadFile] = File(None),
    password: str = Form(""),
    # Chế độ "đóng gói sẵn": trình duyệt tự dựng (và mã hoá) dữ liệu theo định dạng
    # apexweb-v1 rồi gửi lên; máy chủ chỉ nhúng, không thấy mật khẩu hay nội dung.
    payload_file: Optional[UploadFile] = File(None, alias="payload"),
    payload_encrypted: bool = Form(False),
    logo_header: str = Form(""),
    redundancy: int = Form(5),
    auto_redundancy: bool = Form(False),
    delta: float = Form(5.0),
    store_thumbnail: bool = Form(True),
    use_aco: bool = Form(True),
    seed: int = Form(0),
    # Người đã đăng nhập có thể nhờ máy chủ lưu luôn kết quả vào lịch sử.
    save: bool = Form(False),
    save_name: str = Form("anh"),
    request: Request = None,
):
    _check_redundancy(redundancy)
    prepacked = payload_file is not None
    if not prepacked:
        if kind == "text" and not message:
            raise HTTPException(400, "Thông điệp không được để trống.")
        if kind == "logo" and logo is None:
            raise HTTPException(400, "Hãy chọn file logo cần giấu.")
        if kind == "file" and file is None:
            raise HTTPException(400, "Hãy chọn file cần giấu.")
    if len(message) > settings.max_message_chars or len(password) > 256:
        raise HTTPException(400, "Thông điệp hoặc mật khẩu quá dài.")
    if not 0 <= seed < 2**31:
        raise HTTPException(400, "Seed không hợp lệ.")
    if not 4.0 <= delta <= 64.0:
        raise HTTPException(400, "Cường độ nhúng (delta) phải nằm trong 4..64.")
    if not 0 <= logo_max_side <= logo_mod.MAX_SIDE:
        raise HTTPException(400, "Kích thước logo không hợp lệ.")
    img_bytes = await _read_upload(image, "Ảnh")

    logo_bytes = await _read_upload(logo, "Logo") if (kind == "logo" and not prepacked) else b""
    file_bytes = await _read_upload(file, "File") if (kind == "file" and not prepacked) else b""
    packed = await _read_upload(payload_file, "Dữ liệu") if prepacked else b""
    file_name = (file.filename if file is not None else None) or "file.bin"
    saver = None
    if save:
        accounts.same_origin(request)
        saver = await anyio.to_thread.run_sync(accounts.current_user, request)

    def work():
        t0 = time.perf_counter()
        img = _load_image(img_bytes)
        cap = apexmark.capacity(img)
        logo_preview = None
        header = None
        if prepacked:
            if len(packed) < payload.PLAIN_OVERHEAD:
                raise HTTPException(400, "Dữ liệu đóng gói không hợp lệ.")
            data, encrypted = packed, payload_encrypted
            if kind == "logo":
                header = _parse_logo_header(logo_header)
        else:
            encrypted = bool(password)
            if kind == "logo":
                max_body = cap // redundancy // 8 - payload.overhead_bytes(encrypted)
                try:
                    body, logo_preview = logo_mod.encode_logo(logo_bytes, max_body, logo_mode,
                                                              logo_invert, logo_max_side)
                except ImageError as e:
                    raise HTTPException(400, str(e))
                header = logo_mod.header_of(body)
            elif kind == "file":
                body = payload.pack_file(file_name, file_bytes)
            else:
                body = message.encode("utf-8")
            data = payload.encode_bytes(body, password or None, kind=kind)
        bits = payload.bytes_to_bits(data)
        if bits.size * redundancy > cap:
            max_bytes = max(0, cap // redundancy // 8 - payload.overhead_bytes(encrypted))
            raise HTTPException(
                400,
                f"Nội dung quá dài: cần {bits.size * redundancy:,} khối nhưng ảnh chỉ có "
                f"{cap:,}. Ở độ dự phòng {redundancy}, tối đa khoảng {max_bytes:,} byte. "
                f"Hãy rút ngắn nội dung, giảm độ dự phòng hoặc dùng ảnh lớn hơn.")
        # Dùng hết chỗ trống của ảnh để lặp lại nội dung nhiều lần hơn.
        red = max(redundancy, min(settings.max_redundancy, cap // bits.size)) if auto_redundancy else redundancy

        stego, keys = apexmark.embed(
            img, bits, bc7_aware=False, delta_base=delta, redundancy=red,
            store_thumbnail=store_thumbnail, use_aco=use_aco, seed=seed)
        keys["payload_format"] = payload.FORMAT
        keys["payload_kind"] = kind
        keys["payload_encrypted"] = encrypted
        if header is not None:
            keys["logo_header"] = np.array(header, dtype=np.int32)

        stego_u8 = np.clip(stego, 0, 255).astype(np.uint8)
        p = psnr(img, stego_u8)
        psnr_db = None if math.isinf(p) else round(p, 2)
        stego_png = to_png_bytes(stego_u8)
        keys_npz = _keys_to_bytes(keys)
        det = {}
        if settings.show_detect:
            try:
                det = detect.analyze(img, stego_u8)
            except Exception:  # bộ đo chỉ để tham khảo, không được làm hỏng việc giấu tin
                det = {}

        # Người đã đăng nhập: lưu luôn vào lịch sử ở đây để trình duyệt khỏi phải tải ảnh lên lần nữa.
        saved_id = save_error = None
        if saver:
            try:
                saved_id = accounts.store_item(
                    saver["id"], stego_png, keys_npz, name=save_name, psnr=psnr_db, kind=kind,
                    encrypted=encrypted, redundancy=red, width=img.shape[1], height=img.shape[0],
                    thumb_source=stego_u8)["id"]
            except HTTPException as e:
                save_error = str(e.detail)

        return EmbedOut(
            stego_png_base64=_b64(stego_png),
            keys_npz_base64=_b64(keys_npz),
            width=img.shape[1], height=img.shape[0],
            n_bits=int(bits.size), capacity_bits=cap,
            usage_ratio=bits.size * red / cap,
            psnr_db=psnr_db,
            encrypted=encrypted, redundancy=red,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
            kind=kind,
            detect_level=det.get("level"), detect_score=det.get("score"),
            detect_baseline=det.get("baseline"), detect_noise=det.get("noise"),
            logo_preview_base64=_b64(to_png_bytes(logo_preview)) if logo_preview is not None else None,
            logo_width=None if header is None else int(header[2]),
            logo_height=None if header is None else int(header[1]),
            saved_id=saved_id, save_error=save_error,
        )

    return await _heavy(work)


def _extract_bits(img: np.ndarray, k: dict, *, resync: bool, rotate_range: float,
                  aggregate: str) -> tuple[np.ndarray, bool]:
    """Trả về (bits, có_dùng_căn_chỉnh). Lỗi -> HTTPException 400."""
    try:
        if resync and "thumbnail" in k:
            from apexmark import sync
            if sync.is_available():
                kw = {}
                if rotate_range > 0:
                    kw = {"angle_range": (-rotate_range, rotate_range), "angle_step": 1.0}
                frame = sync.resync(img, k, **kw)
                if frame is None:
                    return apexmark.extract(img, k, aggregate=aggregate), True
                box = None
                if rotate_range == 0:
                    # Tinh chỉnh vị trí đến từng điểm ảnh, bỏ phiếu chỉ trên phần ảnh còn lại.
                    frame, box = align.refine(align.to_luma(img), frame, k)
                return align.masked_extract(frame, k, box, aggregate), True
        return apexmark.extract(img, k, aggregate=aggregate), False
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        # File khoá không khớp với ảnh theo cách chưa lường trước: không để lộ chi tiết nội bộ.
        raise HTTPException(400, "Không đọc được: file khoá không khớp với ảnh này.")


def _raw_out(bits: np.ndarray, k: dict, used_resync: bool, elapsed: int) -> ExtractOut:
    fmt = str(k.get("payload_format", ""))
    kind = str(k["payload_kind"]) if "payload_kind" in k else "text"
    return ExtractOut(
        kind=kind, message="", integrity_ok=None,
        encrypted=bool(k.get("payload_encrypted", False)), used_resync=used_resync,
        n_bits=int(bits.size), elapsed_ms=elapsed,
        payload_base64=_b64(payload.bits_to_bytes(bits)), payload_format=fmt,
        logo_header=[int(x) for x in k["logo_header"]] if "logo_header" in k else None)


def _decode_bits(bits: np.ndarray, k: dict, password: str, used_resync: bool,
                 elapsed: int) -> ExtractOut:
    data = payload.bits_to_bytes(bits)
    if str(k.get("payload_format", "")) != payload.FORMAT:
        # Khoá tạo từ CLI apexmark (--text): bit thô = UTF-8, không có CRC.
        return ExtractOut(kind="text", message=data.decode("utf-8", errors="replace"),
                          integrity_ok=None, encrypted=False, used_resync=used_resync,
                          n_bits=int(bits.size), elapsed_ms=elapsed)
    try:
        kind_key = str(k["payload_kind"]) if "payload_kind" in k else None
        enc_key = bool(k["payload_encrypted"]) if "payload_encrypted" in k else None
        dec = payload.decode(data, password or None,
                             kind=kind_key, encrypted=enc_key)
    except payload.WrongPassword as e:
        raise HTTPException(401, str(e))
    except payload.PayloadError as e:
        raise HTTPException(422, str(e))
    common = dict(integrity_ok=dec.integrity_ok, encrypted=dec.encrypted,
                  used_resync=used_resync, n_bits=int(bits.size), elapsed_ms=elapsed)
    if dec.is_logo:
        try:
            hdr = tuple(int(x) for x in k["logo_header"]) if "logo_header" in k else None
            arr = logo_mod.decode_logo(dec.body, hdr)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return ExtractOut(kind="logo", message="", logo_png_base64=_b64(to_png_bytes(arr)),
                          logo_width=int(arr.shape[1]), logo_height=int(arr.shape[0]), **common)
    if dec.kind == "file":
        try:
            name, content = payload.unpack_file(dec.body)
        except payload.PayloadError as e:
            raise HTTPException(422, str(e))
        return ExtractOut(kind="file", message="", file_name=name, file_base64=_b64(content), **common)
    return ExtractOut(kind="text", message=dec.message, **common)


@app.post("/api/extract", response_model=ExtractOut)
async def extract(
    image: UploadFile = File(...),
    keys: UploadFile = File(...),
    password: str = Form(""),
    resync: bool = Form(True),
    rotate_range: float = Form(0.0),
    aggregate: Literal["mean", "kmeans"] = Form("mean"),
    raw: bool = Form(False),
):
    if len(password) > 256:
        raise HTTPException(400, "Mật khẩu quá dài.")
    if not 0 <= rotate_range <= 30:
        raise HTTPException(400, "Biên độ dò xoay phải nằm trong 0..30 độ.")
    img_bytes = await _read_upload(image, "Ảnh")
    keys_bytes = await _read_upload(keys, "File khoá")

    def work():
        img = _load_image(img_bytes)
        k = _keys_from_bytes(keys_bytes)
        t0 = time.perf_counter()
        bits, used_resync = _extract_bits(img, k, resync=resync, rotate_range=rotate_range,
                                          aggregate=aggregate)
        elapsed = int((time.perf_counter() - t0) * 1000)
        if raw:
            return _raw_out(bits, k, used_resync, elapsed)
        return _decode_bits(bits, k, password, used_resync, elapsed)

    return await _heavy(work)


# ---------------------------------------------------------------- thử tấn công

class AttackInfo(BaseModel):
    id: str
    name: str
    group: str
    param: Literal["level", "quality", "none"]
    geometric: bool
    hint: str


class AttackOut(BaseModel):
    attacked_png_base64: str
    width: int
    height: int
    steps: list[str]
    ber: Optional[float] = None            # tỉ lệ bit sai so với ảnh chưa bị tấn công
    status: Optional[Literal["intact", "partial", "broken"]] = None
    extract: Optional[ExtractOut] = None
    extract_error: Optional[str] = None
    elapsed_ms: int


class BatteryRow(BaseModel):
    id: str
    name: str
    group: str
    geometric: bool
    ber: Optional[float]
    status: Literal["intact", "partial", "broken"]
    error: Optional[str] = None


class BatteryOut(BaseModel):
    level: int
    n_bits: int
    encrypted: bool
    rows: list[BatteryRow]
    intact: int
    partial: int
    broken: int
    elapsed_ms: int


def _status(ber: Optional[float], encrypted: bool) -> str:
    """intact = đọc lại đúng 100%; partial = còn đọc được, sai vài bit; broken = hỏng.
    Nội dung đã mã hoá thì chỉ cần sai 1 bit là không giải mã được."""
    if ber is None:
        return "broken"
    if ber == 0:
        return "intact"
    return "partial" if (not encrypted and ber <= 0.05) else "broken"


def _reference_bits(img: np.ndarray, k: dict) -> np.ndarray:
    return _extract_bits(img, k, resync=False, rotate_range=0, aggregate="mean")[0]


def _attack_and_read(img, k, steps, ref_bits):
    """-> (ảnh sau tấn công, bits đọc được | None, ber | None, lỗi | None, used_resync)"""
    attacked = atk.apply_steps(img, steps)
    try:
        bits, used = _extract_bits(attacked, k, resync=True,
                                   rotate_range=atk.rotate_range_for(steps), aggregate="mean")
    except HTTPException as e:
        return attacked, None, None, str(e.detail), False
    return attacked, bits, float(np.mean(bits != ref_bits)), None, used


@app.get("/api/attacks", response_model=list[AttackInfo])
def list_attacks():
    return [AttackInfo(id=a.id, name=a.name, group=a.group, param=a.param,
                       geometric=a.geometric, hint=a.hint) for a in atk.CATALOG]


@app.post("/api/attack", response_model=AttackOut)
async def attack(
    image: UploadFile = File(...),
    steps: str = Form(...),
    keys: Optional[UploadFile] = File(None),
    password: str = Form(""),
    raw: bool = Form(False),
):
    """Áp chuỗi phép tấn công lên ảnh. Nếu gửi kèm file khoá, thử đọc lại nội dung
    từ ảnh đã bị tấn công và so với ảnh chưa bị tấn công."""
    if len(steps) > 2000 or len(password) > 256:
        raise HTTPException(400, "Dữ liệu gửi lên không hợp lệ.")
    try:
        plan = atk.parse_steps(steps)
    except atk.AttackError as e:
        raise HTTPException(400, str(e))
    img_bytes = await _read_upload(image, "Ảnh")
    keys_bytes = await _read_upload(keys, "File khoá") if keys is not None else None

    def work():
        img = _load_image(img_bytes)
        k = _keys_from_bytes(keys_bytes) if keys_bytes is not None else None
        t0 = time.perf_counter()
        out = dict(ber=None, status=None, extract=None, extract_error=None)
        try:
            if k is None:
                attacked = atk.apply_steps(img, plan)
            else:
                ref = _reference_bits(img, k)
                attacked, bits, ber, err, used = _attack_and_read(img, k, plan, ref)
                encrypted = bool(k.get("payload_encrypted", False))
                out.update(ber=ber, extract_error=err, status=_status(ber, encrypted))
                if bits is not None:
                    try:
                        out["extract"] = (_raw_out(bits, k, used, 0) if raw
                                          else _decode_bits(bits, k, password, used, 0))
                    except HTTPException as e:
                        out["extract_error"] = str(e.detail)
        except atk.AttackError as e:
            raise HTTPException(400, str(e))
        return AttackOut(attacked_png_base64=_b64(to_png_bytes(attacked)),
                         width=int(attacked.shape[1]), height=int(attacked.shape[0]),
                         steps=[s.label for s in plan],
                         elapsed_ms=int((time.perf_counter() - t0) * 1000), **out)

    return await _heavy(work)


@app.post("/api/attack/battery", response_model=BatteryOut)
async def attack_battery(
    image: UploadFile = File(...),
    keys: UploadFile = File(...),
    level: int = Form(2),
):
    """Chạy lần lượt TẤT CẢ phép tấn công ở một mức, báo phép nào còn đọc được."""
    if level not in (1, 2, 3):
        raise HTTPException(400, "Mức độ phải là 1, 2 hoặc 3.")
    img_bytes = await _read_upload(image, "Ảnh")
    keys_bytes = await _read_upload(keys, "File khoá")

    def work():
        img = _load_image(img_bytes)
        k = _keys_from_bytes(keys_bytes)
        t0 = time.perf_counter()
        ref = _reference_bits(img, k)
        encrypted = bool(k.get("payload_encrypted", False))
        jpeg_q = {1: 75, 2: 50, 3: 30}[level]
        rows = []
        for a in atk.CATALOG:
            step = atk.Step(a, jpeg_q if a.param == "quality" else level)
            try:
                _, _, ber, err, _ = _attack_and_read(img, k, [step], ref)
            except Exception:
                ber, err = None, "Không áp dụng được phép này lên ảnh."
            rows.append(BatteryRow(id=a.id, name=step.label, group=a.group, geometric=a.geometric,
                                   ber=ber, status=_status(ber, encrypted), error=err))
        count = lambda st: sum(r.status == st for r in rows)  # noqa: E731
        return BatteryOut(level=level, n_bits=int(ref.size), encrypted=encrypted, rows=rows,
                          intact=count("intact"), partial=count("partial"), broken=count("broken"),
                          elapsed_ms=int((time.perf_counter() - t0) * 1000))

    return await _heavy(work)


# ---------------------------------------------------------------- so sánh ảnh

class CompareOut(BaseModel):
    heatmap_png_base64: str
    overlay_png_base64: str
    width: int
    height: int
    changed_pixels: int
    changed_ratio: float
    changed_blocks: int
    total_blocks: int
    max_diff: int
    mean_diff: float
    psnr_db: Optional[float]


@app.post("/api/compare", response_model=CompareOut)
async def compare_images(original: UploadFile = File(...), stego: UploadFile = File(...)):
    a_bytes = await _read_upload(original, "Ảnh gốc")
    b_bytes = await _read_upload(stego, "Ảnh đã giấu tin")

    def work():
        a, b = _load_image(a_bytes), _load_image(b_bytes)
        try:
            r = cmp.compare(a, b)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return CompareOut(heatmap_png_base64=_b64(to_png_bytes(r.pop("heatmap"))),
                          overlay_png_base64=_b64(to_png_bytes(r.pop("overlay"))), **r)

    return await _heavy(work)


app.include_router(accounts.router)


# ---------------------------------------------------------------- frontend (production)

# Mặc định tự tìm frontend/dist cạnh thư mục backend (sau khi `npm run build`).
_static_default = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_static_cfg = Path(settings.static_dir) if settings.static_dir else _static_default
if _static_cfg.is_dir() and (_static_cfg / "index.html").is_file():
    _static = _static_cfg.resolve()
    if (_static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Không tìm thấy.")
        candidate = (_static / full_path).resolve()
        if full_path and candidate.is_file() and _static in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_static / "index.html")
