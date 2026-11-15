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
import logging
import re
import secrets
import threading
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
from .security import KeysError, RateLimiter, client_ip, conn_ip, parse_keys
from . import passwords, totp
from .passwords import weakness
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
_conn_limiter = RateLimiter(settings.login_attempts_per_min * 10)


# ---------------------------------------------------------------- mật khẩu

# Các yêu cầu đăng nhập chạy trong luồng riêng; không giới hạn thì vài chục lần băm cùng lúc
# sẽ ngốn hết RAM của máy chủ nhỏ. Yêu cầu đến sau xếp hàng chờ.
_scrypt_slots = threading.BoundedSemaphore(settings.max_password_jobs)


def _scrypt(password: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    with _scrypt_slots:
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
            "SELECT u.id, u.username, u.created_at, u.recovery_hash, u.totp FROM sessions s JOIN users u ON u.id = s.user_id "
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
    ip, cip = client_ip(request.scope), conn_ip(request.scope)
    if (not _ip_limiter.allow(ip) or (cip != ip and not _conn_limiter.allow(cip))
            or not _name_limiter.allow(username.lower())):
        raise HTTPException(429, "Bạn thử quá nhiều lần. Hãy đợi một phút rồi thử lại.",
                            headers={"Retry-After": "60"})


# ---------------------------------------------------------------- nhật ký bảo mật

_audit_log = logging.getLogger("apex.audit")
EVENT_LABELS = {
    "register": "Đăng ký tài khoản", "login_ok": "Đăng nhập", "login_fail": "Đăng nhập sai mật khẩu",
    "logout": "Đăng xuất", "password_change": "Đổi mật khẩu", "recover_ok": "Khôi phục bằng mã",
    "recover_fail": "Nhập sai mã khôi phục", "recovery_new": "Tạo mã khôi phục mới",
    "history_clear": "Xoá toàn bộ lịch sử", "2fa_on": "Bật xác thực hai lớp", "2fa_off": "Tắt xác thực hai lớp",
    "2fa_fail": "Nhập sai mã xác thực hai lớp",
}


def audit(con, request: Request, event: str, username: str, user_id: Optional[int] = None) -> None:
    """Ghi một sự kiện bảo mật vào cơ sở dữ liệu và log. Không bao giờ ghi mật khẩu hay mã."""
    ip = client_ip(request.scope)[:64]
    now = int(time.time())
    con.execute("INSERT INTO auth_events (ts, user_id, username, event, ip) VALUES (?,?,?,?,?)",
                (now, user_id, username.lower()[:64], event, ip))
    if secrets.randbelow(50) == 0:  # thỉnh thoảng dọn bản ghi cũ
        con.execute("DELETE FROM auth_events WHERE ts < ?", (now - settings.audit_keep_days * 86400,))
    _audit_log.info("%s user=%s ip=%s", event, username.lower()[:64], ip)


def _audit_now(request: Request, event: str, username: str, user_id: Optional[int] = None) -> None:
    with db.connect() as con:
        audit(con, request, event, username, user_id)


def _locked_out(request: Request, username: str) -> None:
    """Khoá tạm theo số lần sai gần đây, đếm trong cơ sở dữ liệu nên không mất khi máy chủ khởi động lại.

    Ngưỡng theo cặp (tên, IP) thấp; ngưỡng theo tên cao hơn nhiều để người khác khó cố tình
    khoá tài khoản của bạn, nhưng vẫn chặn được việc dò mật khẩu từ nhiều địa chỉ.
    """
    since = int(time.time()) - settings.lockout_window_min * 60
    name = username.lower()[:64]
    with db.connect() as con:
        rows = con.execute(
            "SELECT ip FROM auth_events WHERE username = ? AND ts > ? AND event IN ('login_fail', 'recover_fail', '2fa_fail')",
            (name, since)).fetchall()
    ip = client_ip(request.scope)[:64]
    if (sum(1 for r in rows if r["ip"] == ip) >= settings.lockout_fails_per_ip
            or len(rows) >= settings.lockout_fails_per_user):
        raise HTTPException(429, f"Sai quá nhiều lần. Hãy thử lại sau {settings.lockout_window_min} phút.",
                            headers={"Retry-After": str(settings.lockout_window_min * 60)})


# ---------------------------------------------------------------- xác thực hai lớp
# Cột users.totp: "p:<secret>" = đang cài, chưa xác nhận; "a:<secret>:<bước đã dùng>" = đang bật.

def _totp_active(value: Optional[str]) -> Optional[tuple[str, int]]:
    if not value or not value.startswith("a:"):
        return None
    _, secret, last = (value.split(":") + ["0"])[:3]
    return secret, int(last or 0)


# ---------------------------------------------------------------- mã khôi phục

_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_recovery_code() -> str:
    """5 nhóm 4 ký tự, khoảng 100 bit ngẫu nhiên."""
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(20))
    return "-".join(raw[i:i + 4] for i in range(0, 20, 4))


def _recovery_hash(code: str) -> str:
    # Mã có đủ entropy nên SHA-256 là đủ, không cần hàm băm chậm.
    norm = re.sub(r"[^A-Z0-9]", "", code.upper())
    return hashlib.sha256(("apex-recovery:" + norm).encode()).hexdigest()


# ---------------------------------------------------------------- schemas

class Credentials(BaseModel):
    username: str
    password: str
    code: Optional[str] = None  # mã 6 số của ứng dụng xác thực, khi tài khoản bật 2FA


class TotpCode(BaseModel):
    code: str


class TotpSetup(BaseModel):
    secret: str
    uri: str


class PasswordChange(BaseModel):
    current: str
    new: str


class PasswordConfirm(BaseModel):
    password: str


class UserOut(BaseModel):
    username: str
    created_at: int
    has_recovery: bool = False
    has_2fa: bool = False
    # Chỉ có ngay sau khi đăng ký, khôi phục hoặc tạo mã mới: hiện một lần rồi thôi.
    recovery_code: Optional[str] = None


class Recover(BaseModel):
    username: str
    code: str
    new: str


class EventOut(BaseModel):
    ts: int
    event: str
    label: str
    ip: str


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
    stego_sha256: Optional[str] = None
    keys_sha256: Optional[str] = None


class ProofOut(BaseModel):
    found: bool
    matched: Optional[str] = None  # "stego" hoặc "keys"
    registered_at: Optional[int] = None
    owner: Optional[str] = None
    name: Optional[str] = None


class HistoryOut(BaseModel):
    items: list[ItemOut]
    used_bytes: int
    max_bytes: int
    max_items: int


def _check_password(pw: str, username: str = "") -> None:
    if not MIN_PASSWORD <= len(pw) <= MAX_PASSWORD:
        raise HTTPException(400, f"Mật khẩu phải dài từ {MIN_PASSWORD} ký tự trở lên.")
    why = weakness(pw, username)
    if why:
        raise HTTPException(400, why)
    if settings.hibp_check:
        seen = passwords.pwned_count(pw)
        if seen > 0:
            raise HTTPException(400, f"Mật khẩu này đã xuất hiện {seen:,} lần trong các vụ lộ dữ liệu, "
                                     "kẻ xấu sẽ thử nó đầu tiên. Hãy chọn mật khẩu khác.")


# ---------------------------------------------------------------- auth

@router.get("/auth/me", response_model=Me)
def me(request: Request):
    u = current_user(request)
    return Me(user=UserOut(username=u["username"], created_at=u["created_at"],
                           has_recovery=bool(u["recovery_hash"]),
                           has_2fa=bool(_totp_active(u["totp"]))) if u else None,
              registration_open=settings.allow_registration)


@router.post("/auth/register", response_model=UserOut, dependencies=[Depends(same_origin)])
def register(body: Credentials, request: Request, response: Response):
    if not settings.allow_registration:
        raise HTTPException(403, "Trang này hiện không mở đăng ký.")
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "Tên đăng nhập dài 3 đến 32 ký tự, chỉ gồm chữ không dấu, số và các dấu . _ -")
    if body.password.lower() == username.lower():
        raise HTTPException(400, "Mật khẩu không được trùng với tên đăng nhập.")
    _check_password(body.password, username)
    _throttle(request, username)
    pw_hash = hash_password(body.password)
    code = _new_recovery_code()
    now = int(time.time())
    with db.connect() as con:
        if con.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone():
            raise HTTPException(409, "Tên đăng nhập này đã có người dùng.")
        try:
            uid = con.execute(
                "INSERT INTO users (username, pw_hash, created_at, recovery_hash) VALUES (?,?,?,?) RETURNING id",
                (username, pw_hash, now, _recovery_hash(code))).fetchone()["id"]
        except db.IntegrityError:  # hai người đăng ký cùng tên cùng lúc
            raise HTTPException(409, "Tên đăng nhập này đã có người dùng.")
        _start_session(con, uid, request, response)
        audit(con, request, "register", username, uid)
    return UserOut(username=username, created_at=now, has_recovery=True, recovery_code=code)


@router.post("/auth/login", response_model=UserOut, dependencies=[Depends(same_origin)])
def login(body: Credentials, request: Request, response: Response):
    username = body.username.strip()
    _throttle(request, username[:64])
    _locked_out(request, username)
    with db.connect() as con:
        row = con.execute(
            "SELECT id, username, pw_hash, created_at, recovery_hash, totp FROM users WHERE lower(username) = lower(?)",
            (username,)).fetchone()
    ok = verify_password(body.password[:MAX_PASSWORD], row["pw_hash"] if row else _DUMMY_HASH)
    if not row or not ok:
        _audit_now(request, "login_fail", username, row["id"] if row else None)
        raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu.")
    active = _totp_active(row["totp"])
    step = None
    if active:
        # Chỉ hỏi mã sau khi mật khẩu đã đúng, để người ngoài không dò được tài khoản nào bật 2FA.
        if not body.code:
            raise HTTPException(428, "Tài khoản này bật xác thực hai lớp. Hãy nhập mã 6 số trong ứng dụng xác thực.")
        step = totp.verify(active[0], body.code[:16], active[1])
        if step is None:
            _audit_now(request, "2fa_fail", row["username"], row["id"])
            raise HTTPException(401, "Mã xác thực không đúng hoặc đã hết hạn.")
    with db.connect() as con:
        if active:
            con.execute("UPDATE users SET totp = ? WHERE id = ?", (f"a:{active[0]}:{step}", row["id"]))
        _start_session(con, row["id"], request, response)
        audit(con, request, "login_ok", row["username"], row["id"])
    return UserOut(username=row["username"], created_at=row["created_at"], has_recovery=bool(row["recovery_hash"]),
                   has_2fa=bool(active))


@router.post("/auth/2fa/setup", response_model=TotpSetup, dependencies=[Depends(same_origin)])
def totp_setup(body: PasswordConfirm, request: Request, user: dict = Depends(require_user)):
    """Bước 1: tạo khoá bí mật để thêm vào ứng dụng xác thực. Chưa có hiệu lực cho tới khi xác nhận mã."""
    _throttle(request, user["username"])
    if _totp_active(user["totp"]):
        raise HTTPException(409, "Xác thực hai lớp đang bật. Hãy tắt trước khi cài lại.")
    secret = totp.new_secret()
    with db.connect() as con:
        row = con.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not verify_password(body.password, row["pw_hash"]):
            raise HTTPException(401, "Mật khẩu không đúng.")
        con.execute("UPDATE users SET totp = ? WHERE id = ?", (f"p:{secret}", user["id"]))
    return TotpSetup(secret=secret, uri=totp.uri(secret, user["username"]))


@router.post("/auth/2fa/enable", dependencies=[Depends(same_origin)])
def totp_enable(body: TotpCode, request: Request, user: dict = Depends(require_user)):
    """Bước 2: nhập mã từ ứng dụng để chứng minh đã cài đúng, rồi mới bật."""
    _throttle(request, user["username"])
    pending = user["totp"] or ""
    if not pending.startswith("p:"):
        raise HTTPException(409, "Chưa bắt đầu cài xác thực hai lớp.")
    secret = pending[2:]
    step = totp.verify(secret, body.code[:16])
    if step is None:
        raise HTTPException(400, "Mã không đúng. Hãy kiểm tra giờ trên điện thoại rồi nhập mã mới nhất.")
    with db.connect() as con:
        con.execute("UPDATE users SET totp = ? WHERE id = ?", (f"a:{secret}:{step}", user["id"]))
        audit(con, request, "2fa_on", user["username"], user["id"])
    return {"ok": True}


@router.post("/auth/2fa/disable", dependencies=[Depends(same_origin)])
def totp_disable(body: PasswordConfirm, request: Request, user: dict = Depends(require_user)):
    _throttle(request, user["username"])
    with db.connect() as con:
        row = con.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not verify_password(body.password, row["pw_hash"]):
            raise HTTPException(401, "Mật khẩu không đúng.")
        con.execute("UPDATE users SET totp = NULL WHERE id = ?", (user["id"],))
        audit(con, request, "2fa_off", user["username"], user["id"])
    return {"ok": True}


@router.post("/auth/recover", response_model=UserOut, dependencies=[Depends(same_origin)])
def recover(body: Recover, request: Request, response: Response):
    """Quên mật khẩu: đặt mật khẩu mới bằng mã khôi phục. Mã dùng xong là hết hiệu lực, cấp mã mới."""
    username = body.username.strip()
    _throttle(request, username[:64])
    _locked_out(request, username)
    with db.connect() as con:
        row = con.execute(
            "SELECT id, username, created_at, recovery_hash FROM users WHERE lower(username) = lower(?)",
            (username,)).fetchone()
    given = _recovery_hash(body.code[:64])
    if not row or not row["recovery_hash"] or not hmac.compare_digest(given, row["recovery_hash"]):
        _audit_now(request, "recover_fail", username, row["id"] if row else None)
        raise HTTPException(401, "Tên đăng nhập hoặc mã khôi phục không đúng.")
    _check_password(body.new, row["username"])
    pw_hash = hash_password(body.new)
    code = _new_recovery_code()
    with db.connect() as con:
        # Mã khôi phục cũng là lối thoát khi mất điện thoại: tắt luôn xác thực hai lớp.
        con.execute("UPDATE users SET pw_hash = ?, recovery_hash = ?, totp = NULL WHERE id = ?",
                    (pw_hash, _recovery_hash(code), row["id"]))
        con.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        _start_session(con, row["id"], request, response)
        audit(con, request, "recover_ok", row["username"], row["id"])
    return UserOut(username=row["username"], created_at=row["created_at"], has_recovery=True, recovery_code=code)


@router.post("/auth/recovery-code", response_model=UserOut, dependencies=[Depends(same_origin)])
def new_recovery_code(body: PasswordConfirm, request: Request, user: dict = Depends(require_user)):
    """Tạo mã khôi phục mới (mã cũ hết hiệu lực). Cần nhập lại mật khẩu."""
    _throttle(request, user["username"])
    code = _new_recovery_code()
    with db.connect() as con:
        row = con.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not verify_password(body.password, row["pw_hash"]):
            raise HTTPException(401, "Mật khẩu không đúng.")
        con.execute("UPDATE users SET recovery_hash = ? WHERE id = ?", (_recovery_hash(code), user["id"]))
        audit(con, request, "recovery_new", user["username"], user["id"])
    return UserOut(username=user["username"], created_at=user["created_at"], has_recovery=True, recovery_code=code)


@router.get("/auth/activity", response_model=list[EventOut])
def activity(user: dict = Depends(require_user)):
    """Hoạt động bảo mật gần đây của chính tài khoản này."""
    with db.connect() as con:
        rows = con.execute("SELECT ts, event, ip FROM auth_events WHERE user_id = ? ORDER BY ts DESC, id DESC LIMIT 30",
                           (user["id"],)).fetchall()
    return [EventOut(ts=r["ts"], event=r["event"], label=EVENT_LABELS.get(r["event"], r["event"]), ip=r["ip"])
            for r in rows]


@router.post("/auth/logout", dependencies=[Depends(same_origin)])
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        user = current_user(request)
        with db.connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
            if user:
                audit(con, request, "logout", user["username"], user["id"])
    _clear_cookie(response)
    return {"ok": True}


@router.post("/auth/password", dependencies=[Depends(same_origin)])
def change_password(body: PasswordChange, request: Request, response: Response,
                    user: dict = Depends(require_user)):
    _throttle(request, user["username"])
    _check_password(body.new, user["username"])
    with db.connect() as con:
        row = con.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not verify_password(body.current, row["pw_hash"]):
            raise HTTPException(401, "Mật khẩu hiện tại không đúng.")
        con.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_password(body.new), user["id"]))
        # Đổi mật khẩu thì đăng xuất mọi thiết bị, rồi cấp phiên mới cho thiết bị này.
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        _start_session(con, user["id"], request, response)
        audit(con, request, "password_change", user["username"], user["id"])
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
        con.execute("DELETE FROM auth_events WHERE user_id = ?", (user["id"],))
        _audit_log.info("account_delete user=%s", user["username"].lower())
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
                       redundancy=int(redundancy), stego_bytes=len(stego_data), keys_bytes=len(keys_data),
                       stego_sha256=hashlib.sha256(stego_data).hexdigest(),
                       keys_sha256=hashlib.sha256(keys_data).hexdigest())
            con.execute(
                "INSERT INTO items (id, user_id, created_at, name, kind, encrypted, width, height, psnr, "
                "redundancy, stego_bytes, keys_bytes, stego_sha256, keys_sha256) VALUES (:id, :user_id, "
                ":created_at, :name, :kind, :encrypted, :width, :height, :psnr, :redundancy, :stego_bytes, "
                ":keys_bytes, :stego_sha256, :keys_sha256)",
                {**row, "user_id": user_id})
        except Exception as e:
            _delete_files(user_id, [item_id])
            if isinstance(e, StorageError):
                logging.getLogger("apex.storage").error("store_item: %s", e)
                raise HTTPException(503, f"Kho lưu trữ đang lỗi, chưa lưu được ({e}). Hãy thử lại sau.")
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
            sealed = _sealed_meta(keys_data)
            k = sealed or parse_keys(keys_data)
        except (ImageError, KeysError) as e:
            raise HTTPException(400, str(e))
        return store_item(user["id"], stego_data, keys_data, name=name, psnr=psnr,
                          kind=str(k.get("payload_kind", "text")),
                          encrypted=bool(k.get("payload_encrypted", False)),
                          redundancy=int(k.get("redundancy", 1)), width=img.width, height=img.height,
                          thumb_source=img)

    return ItemOut(**await anyio.to_thread.run_sync(work))


SEALED_MAGIC = b"APEXKEY1"
_SEALED_KINDS = ("text", "logo", "file")


def _sealed_meta(data: bytes) -> Optional[dict]:
    """File khoá đã được trình duyệt bọc bằng mật khẩu (xem frontend/src/lib/keyfile.ts).

    Máy chủ không mở được nên chỉ kiểm tra khung và đọc phần đầu không mã hoá để hiện trong lịch sử.
    """
    if not data.startswith(SEALED_MAGIC):
        return None
    if len(data) < 8 + 3 + 16 + 12 + 16 + 1 or data[8] >= len(_SEALED_KINDS):
        raise KeysError("File khoá được bảo vệ bằng mật khẩu bị hỏng.")
    return {"payload_kind": _SEALED_KINDS[data[8]], "payload_encrypted": True,
            "redundancy": max(1, int.from_bytes(data[9:11], "big"))}


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@router.get("/proof/{digest}", response_model=ProofOut)
def proof(digest: str):
    """Tra dấu thời gian: SHA-256 của ảnh đã giấu tin hoặc của file khoá đã được lưu vào tài khoản lúc nào.

    Công khai có chủ đích: người giữ đúng file mới tính ra được mã băm, và chỉ nhận về tên tài khoản,
    tên mục và thời điểm lưu sớm nhất.
    """
    digest = digest.lower()
    if not SHA256_RE.match(digest):
        raise HTTPException(400, "Mã băm SHA-256 không hợp lệ.")
    with db.connect() as con:
        for what in ("stego", "keys"):
            row = con.execute(
                f"SELECT i.created_at, i.name, u.username FROM items i JOIN users u ON u.id = i.user_id "
                f"WHERE i.{what}_sha256 = ? ORDER BY i.created_at ASC, i.id ASC LIMIT 1", (digest,)).fetchone()
            if row:
                return ProofOut(found=True, matched=what, registered_at=row["created_at"],
                                owner=row["username"], name=row["name"])
    return ProofOut(found=False)


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
def clear_history(request: Request, user: dict = Depends(require_user)):
    with db.connect() as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM items WHERE user_id = ?", (user["id"],)).fetchall()]
        con.execute("DELETE FROM items WHERE user_id = ?", (user["id"],))
        audit(con, request, "history_clear", user["username"], user["id"])
    _delete_files(user["id"], ids)
    return {"ok": True}
