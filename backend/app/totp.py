"""Mã dùng một lần theo thời gian (TOTP, RFC 6238): SHA-1, 6 chữ số, chu kỳ 30 giây.
Tương thích Google Authenticator, Microsoft Authenticator, Authy, 1Password..."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret, casefold=True)
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    num = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(num % 10 ** DIGITS).zfill(DIGITS)


def verify(secret: str, code: str, last_step: int = 0, now: Optional[float] = None) -> Optional[int]:
    """Trả về bước thời gian khớp (chấp nhận lệch một chu kỳ), None nếu sai.

    Bước đã dùng (<= last_step) bị từ chối để mã nhìn trộm được không dùng lại được.
    """
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return None
    current = int((time.time() if now is None else now) // STEP)
    hit = None
    for step in (current - 1, current, current + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            hit = step
    return hit


def uri(secret: str, username: str, issuer: str = "PDK APEX") -> str:
    label = quote(f"{issuer}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"
