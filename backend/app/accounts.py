"""Tài khoản và lịch sử.

Khách dùng web không cần tài khoản và máy chủ không lưu gì của họ. Người đã
đăng nhập có thể lưu ảnh đã giấu tin cùng file khoá để lấy lại sau.

Bảo mật:
- Mật khẩu tài khoản băm bằng scrypt (muối riêng cho mỗi người), không lưu dạng gốc.
- Phiên đăng nhập là token ngẫu nhiên 256 bit trong cookie HttpOnly + SameSite=Strict;
  cơ sở dữ liệu chỉ giữ SHA-256 của token, nên lộ file dữ liệu cũng không dùng lại được phiên.
- Mật khẩu của NỘI DUNG GIẤU không bao giờ được lưu, kể cả với người đã đăng nhập.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import re
import secrets
import time
from typing import Optional
from urllib.parse import quote, urlsplit

import anyio
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile

from PIL import Image
from pydantic import BaseModel

from . import db
from .config import settings
from .imaging import ImageError, open_checked
from .security import KeysError, RateLimiter, client_ip, parse_keys
from .storage import StorageError, storage

router = APIRouter(prefix="/api")

COOKIE = "apex_session"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
ITEM_ID_RE = re.compile(r"^[0-9a-f]{24}$")
MIN_PASSWORD, MAX_PASSWORD = 8, 256
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# scrypt: N=2^15, r=8, p=1 (~32 MB bộ nhớ cho mỗi lần băm).
SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P = 15, 8, 1

_ip_limiter = RateLimiter(settings.login_attempts_per_min)
_name_limiter = RateLimiter(settings.login_attempts_per_min)


# ---------------------------------------------------------------- mật khẩu

def _scrypt(password: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=1 << log_n, r=r, p=p,
                          maxmem=256 * 1024 * 1024, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = _scrypt(password, salt, SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return f"scrypt${SCRYPT_LOG_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(h)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, log_n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = _scrypt(password, base64.b64decode(salt), int(log_n), int(r), int(p))
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


# Băm giả để thời gian phản hồi khi tên đăng nhập không tồn tại giống khi sai mật khẩu.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


# ---------------------------------------------------------------- phiên

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


def _is_https(request: Request) -> bool:
    if settings.cookie_secure in ("0", "1"):
        return settings.cookie_secure == "1"
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _start_session(con, user_id: int, request: Request, response: Response) -> None:
    now = int(time.time())
    con.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    token = secrets.token_urlsafe(32)
    ttl = settings.session_days * 86400
    con.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                (_token_hash(token), user_id, now, now + ttl))
    response.set_cookie(COOKIE, token, max_age=ttl, httponly=True, samesite="strict",
                        secure=_is_https(request), path="/")


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")


def current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 128:
        return None
    with db.connect() as con:
        row = con.execute(
            "SELECT u.id, u.username, u.created_at FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?", (_token_hash(token), int(time.time()))).fetchone()
    return dict(row) if row else None


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Bạn cần đăng nhập.")
    return user


def same_origin(request: Request) -> None:
    """Lớp chống CSRF thứ hai (bên cạnh SameSite=Strict): yêu cầu thay đổi dữ liệu
    phải đến từ chính trang web này."""
    origin = request.headers.get("origin")
    if not origin or origin in settings.cors_origins or origin in settings.trusted_origins:
        return
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    # So theo tên máy (bỏ cổng) để chế độ dev qua proxy của Vite vẫn chạy.
    if (urlsplit(origin).hostname or "") != host.rsplit(":", 1)[0].strip("[]"):
        raise HTTPException(403, "Yêu cầu không đến từ trang web này.")


def _throttle(request: Request, username: str) -> None:
    ip = client_ip(request.scope)
    if not _ip_limiter.allow(ip) or not _name_limiter.allow(username.lower()):
        raise HTTPException(429, "Bạn thử quá nhiều lần. Hãy đợi một phút rồi thử lại.",
                            headers={"Retry-After": "60"})


# ---------------------------------------------------------------- schemas

class Credentials(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current: str
    new: str


class PasswordConfirm(BaseModel):
    password: str


class UserOut(BaseModel):
    username: str
    created_at: int


class Me(BaseModel):
    user: Optional[UserOut]
    registration_open: bool


class ItemOut(BaseModel):
    id: str
    created_at: int
    name: str
    kind: str
    encrypted: bool
    width: int
    height: int
    psnr: Optional[float]
    redundancy: int
    stego_bytes: int
    keys_bytes: int


class HistoryOut(BaseModel):
    items: list[ItemOut]
    used_bytes: int
    max_bytes: int
    max_items: int


def _check_password(pw: str) -> None:
    if not MIN_PASSWORD <= len(pw) <= MAX_PASSWORD:
        raise HTTPException(400, f"Mật khẩu phải dài từ {MIN_PASSWORD} ký tự trở lên.")


# ---------------------------------------------------------------- auth

@router.get("/auth/me", response_model=Me)
def me(request: Request):
    u = current_user(request)
    return Me(user=UserOut(username=u["username"], created_at=u["created_at"]) if u else None,
              registration_open=settings.allow_registration)


@router.post("/auth/register", response_model=UserOut, dependencies=[Depends(same_origin)])
def register(body: Credentials, request: Request, response: Response):
    if not settings.allow_registration:
        raise HTTPException(403, "Trang này hiện không mở đăng ký.")
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "Tên đăng nhập dài 3 đến 32 ký tự, chỉ gồm chữ không dấu, số và các dấu . _ -")
    _check_password(body.password)
    if body.password.lower() == username.lower():
        raise HTTPException(400, "Mật khẩu không được trùng với tên đăng nhập.")
    _throttle(request, username)
    pw_hash = hash_password(body.password)
    now = int(time.time())
    with db.connect() as con:
        if con.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone():
            raise HTTPException(409, "Tên đăng nhập này đã có người dùng.")
        try:
            uid = con.execute("INSERT INTO users (username, pw_hash, created_at) VALUES (?,?,?) RETURNING id",
                              (username, pw_hash, now)).fetchone()["id"]
        except db.IntegrityError:  # hai người đăng ký cùng tên cùng lúc
            raise HTTPException(409, "Tên đăng nhập này đã có người dùng.")
        _start_session(con, uid, request, response)
    return UserOut(username=username, created_at=now)


@router.post("/auth/login", response_model=UserOut, dependencies=[Depends(same_origin)])
def login(body: Credentials, request: Request, response: Response):
    username = body.username.strip()
    _throttle(request, username[:64])
    with db.connect() as con:
        row = con.execute("SELECT id, username, pw_hash, created_at FROM users WHERE lower(username) = lower(?)",
                          (username,)).fetchone()
    ok = verify_password(body.password[:MAX_PASSWORD], row["pw_hash"] if row else _DUMMY_HASH)
    if not row or not ok:
        raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu.")
    with db.connect() as con:
        _start_session(con, row["id"], request, response)
    return UserOut(username=row["username"], created_at=row["created_at"])


@router.post("/auth/logout", dependencies=[Depends(same_origin)])
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with db.connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
    _clear_cookie(response)
    return {"ok": True}


@router.post("/auth/password", dependencies=[Depends(same_origin)])
def change_password(body: PasswordChange, request: Request, response: Response,
                    user: dict = Depends(require_user)):
    _throttle(request, user["username"])
    _check_password(body.new)
    with db.connect() as con:
        row = con.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not verify_password(body.current, row["pw_hash"]):
            raise HTTPException(401, "Mật khẩu hiện tại không đúng.")
        con.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_password(body.new), user["id"]))
        # Đổi mật khẩu thì đăng xuất mọi thiết bị, rồi cấp phiên mới cho thiết bị này.
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        _start_session(con, user["id"], request, response)
    return {"ok": True}


@router.post("/auth/delete", dependencies=[Depends(same_origin)])
def delete_account(body: PasswordConfirm, request: Request, response: Response,
                   user: dict = Depends(require_user)):
    _throttle(request, user["username"])
    with db.connect() as con:
        row = con.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not verify_password(body.password, row["pw_hash"]):
            raise HTTPException(401, "Mật khẩu không đúng.")
        ids = [r["id"] for r in con.execute("SELECT id FROM items WHERE user_id = ?", (user["id"],)).fetchall()]
        con.execute("DELETE FROM users WHERE id = ?", (user["id"],))  # sessions, items xoá theo
    _delete_files(user["id"], ids)
    _clear_cookie(response)
    return {"ok": True}


# ---------------------------------------------------------------- lịch sử

_EXT = {"stego": "png", "keys": "npz", "thumb": "jpg"}


def _keys_of(user_id: int, item_id: str) -> dict[str, str]:
    return {what: f"{int(user_id)}/{item_id}.{ext}" for what, ext in _EXT.items()}


def _delete_files(user_id: int, item_ids: list[str]) -> None:
    keys = [k for i in item_ids for k in _keys_of(user_id, i).values()]
    try:
        storage.delete(keys)
    except StorageError:
        pass  # dòng trong cơ sở dữ liệu đã xoá; file mồ côi không lộ ra được qua API


def _clean_name(name: str) -> str:
    name = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]", "_", name).strip(" .")
    return name[:120] or "anh"


def _thumbnail(img: Image.Image) -> bytes:
    t = img.convert("RGB")
    t.thumbnail((320, 320))
    buf = io.BytesIO()
    t.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _usage(con, user_id: int) -> tuple[int, int]:
    row = con.execute("SELECT COUNT(*) AS n, COALESCE(SUM(stego_bytes + keys_bytes), 0) AS b "
                      "FROM items WHERE user_id = ?", (user_id,)).fetchone()
    return row["n"], row["b"]


@router.get("/history", response_model=HistoryOut)
def list_history(user: dict = Depends(require_user)):
    with db.connect() as con:
        rows = con.execute("SELECT * FROM items WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                           (user["id"],)).fetchall()
        _, used = _usage(con, user["id"])
    return HistoryOut(items=[ItemOut(**{k: r[k] for k in ItemOut.model_fields}) for r in rows],
                      used_bytes=used, max_bytes=settings.max_storage_mb_per_user * 1024 * 1024,
                      max_items=settings.max_items_per_user)


def store_item(user_id: int, stego_data: bytes, keys_data: bytes, *, name: str, psnr: Optional[float],
               kind: str, encrypted: bool, redundancy: int, width: int, height: int, thumb_source) -> dict:
    """Ghi một mục vào lịch sử (dữ liệu đã được kiểm tra). thumb_source: ảnh PIL hoặc mảng uint8."""
    item_id = secrets.token_hex(12)
    keys = _keys_of(user_id, item_id)
    size = len(stego_data) + len(keys_data)
    if not isinstance(thumb_source, Image.Image):
        thumb_source = Image.fromarray(thumb_source)
    with db.connect() as con:
        n, used = _usage(con, user_id)
        if n >= settings.max_items_per_user:
            raise HTTPException(409, f"Lịch sử đã đầy ({settings.max_items_per_user} mục). Hãy xoá bớt mục cũ.")
        if used + size > settings.max_storage_mb_per_user * 1024 * 1024:
            raise HTTPException(409, f"Đã dùng hết {settings.max_storage_mb_per_user} MB lưu trữ. Hãy xoá bớt mục cũ.")
        try:
            storage.put(keys["stego"], stego_data, "image/png")
            storage.put(keys["keys"], keys_data, "application/octet-stream")
            storage.put(keys["thumb"], _thumbnail(thumb_source), "image/jpeg")
            row = dict(id=item_id, created_at=int(time.time()), name=_clean_name(name), kind=kind,
                       encrypted=bool(encrypted), width=int(width), height=int(height), psnr=psnr,
                       redundancy=int(redundancy), stego_bytes=len(stego_data), keys_bytes=len(keys_data))
            con.execute(
                "INSERT INTO items (id, user_id, created_at, name, kind, encrypted, width, height, psnr, "
                "redundancy, stego_bytes, keys_bytes) VALUES (:id, :user_id, :created_at, :name, :kind, "
                ":encrypted, :width, :height, :psnr, :redundancy, :stego_bytes, :keys_bytes)",
                {**row, "user_id": user_id})
        except Exception as e:
            _delete_files(user_id, [item_id])
            if isinstance(e, StorageError):
                raise HTTPException(503, "Kho lưu trữ đang lỗi, chưa lưu được. Hãy thử lại sau.")
            raise
    return row


@router.post("/history", response_model=ItemOut, dependencies=[Depends(same_origin)])
async def save_history(stego: UploadFile = File(...), keys: UploadFile = File(...),
                       name: str = Form("anh"), psnr: Optional[float] = Form(None),
                       user: dict = Depends(require_user)):
    stego_data = await stego.read(settings.max_upload_bytes + 1)
    keys_data = await keys.read(settings.max_upload_bytes + 1)
    if max(len(stego_data), len(keys_data)) > settings.max_upload_bytes:
        raise HTTPException(413, f"File vượt quá {settings.max_upload_mb} MB.")
    if not stego_data.startswith(PNG_MAGIC):
        raise HTTPException(400, "Ảnh đã giấu tin phải là file PNG.")
    if psnr is not None and not (0 <= psnr <= 200):
        psnr = None

    def work():
        # Cả hai file đều không tin cậy: kiểm tra y như khi đọc tin, và tự rút thông tin từ chúng
        # thay vì tin vào số liệu trình duyệt gửi lên.
        try:
            img = open_checked(stego_data, settings.max_pixels)
            k = parse_keys(keys_data)
        except (ImageError, KeysError) as e:
            raise HTTPException(400, str(e))
        return store_item(user["id"], stego_data, keys_data, name=name, psnr=psnr,
                          kind=str(k.get("payload_kind", "text")),
                          encrypted=bool(k.get("payload_encrypted", False)),
                          redundancy=int(k.get("redundancy", 1)), width=img.width, height=img.height,
                          thumb_source=img)

    return ItemOut(**await anyio.to_thread.run_sync(work))


def _owned_item(user: dict, item_id: str):
    if not ITEM_ID_RE.match(item_id):
        raise HTTPException(404, "Không tìm thấy mục này.")
    with db.connect() as con:
        row = con.execute("SELECT * FROM items WHERE id = ? AND user_id = ?", (item_id, user["id"])).fetchone()
    if not row:  # mục của người khác cũng trả 404, không để lộ là nó tồn tại
        raise HTTPException(404, "Không tìm thấy mục này.")
    return row


_FILES = {
    "stego": ("image/png", "{}_apex.png"),
    "keys": ("application/octet-stream", "{}_khoa.npz"),
    "thumb": ("image/jpeg", "{}_thumb.jpg"),
}


@router.get("/history/{item_id}/{what}")
def get_history_file(item_id: str, what: str, user: dict = Depends(require_user)):
    if what not in _FILES:
        raise HTTPException(404, "Không tìm thấy.")
    row = _owned_item(user, item_id)
    try:
        data = storage.get(_keys_of(user["id"], item_id)[what])
    except StorageError:
        raise HTTPException(503, "Kho lưu trữ đang lỗi. Hãy thử lại sau.")
    if data is None:
        raise HTTPException(404, "File của mục này không còn trên máy chủ.")
    media, pattern = _FILES[what]
    disp = "inline" if what == "thumb" else "attachment"
    return Response(data, media_type=media, headers={
        "content-disposition": f"{disp}; filename*=UTF-8''{quote(pattern.format(row['name']))}",
        # Ảnh thu nhỏ không đổi theo thời gian: cho trình duyệt giữ lại (riêng tư, không qua CDN).
        "cache-control": "private, max-age=86400" if what == "thumb" else "no-store",
    })


@router.delete("/history/{item_id}", dependencies=[Depends(same_origin)])
def delete_history_item(item_id: str, user: dict = Depends(require_user)):
    _owned_item(user, item_id)
    with db.connect() as con:
        con.execute("DELETE FROM items WHERE id = ? AND user_id = ?", (item_id, user["id"]))
    _delete_files(user["id"], [item_id])
    return {"ok": True}


@router.delete("/history", dependencies=[Depends(same_origin)])
def clear_history(user: dict = Depends(require_user)):
    with db.connect() as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM items WHERE user_id = ?", (user["id"],)).fetchall()]
        con.execute("DELETE FROM items WHERE user_id = ?", (user["id"],))
    _delete_files(user["id"], ids)
    return {"ok": True}
